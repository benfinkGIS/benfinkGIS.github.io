"""Step 1a: download the USGS 3DEP lidar tiles that cover each site.

Asks The National Map which point-cloud tiles of the chosen lidar project
overlap each site's working box (boundary plus buffer), downloads the ones
not already on disk, and writes a manifest so later steps know which tiles
belong to which site.

Run:  py tools/canopy/01_get_lidar.py [site_id ...]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pyproj
import requests

from common import EPSG, LIDAR, sites, work_bbox

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
PROJECT_NAME = "AZ_PimaCounty_2021_B21"   # 2021 Pima County flight
MIN_OVERLAP_M = 20                        # ignore tiles that only share an edge


def tnm_items(bbox_ll):
    for i in range(6):
        try:
            r = requests.get(TNM, params=dict(
                datasets="Lidar Point Cloud (LPC)", max=200, outputFormat="JSON",
                bbox=",".join(f"{v:.6f}" for v in bbox_ll)), timeout=120)
            return r.json()["items"]
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(5 * (i + 1))
    raise SystemExit("The National Map did not answer")


def download(url, path):
    """Fetch one tile, picking up a part-finished file where it stopped."""
    if path.exists() and path.stat().st_size > 0:
        return path
    tmp = path.with_suffix(".part")
    for i in range(12):
        have = tmp.stat().st_size if tmp.exists() else 0
        try:
            head = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(url, stream=True, timeout=120, headers=head) as r:
                if r.status_code == 416:          # already complete
                    break
                r.raise_for_status()
                mode = "ab" if r.status_code == 206 else "wb"
                with open(tmp, mode) as fh:
                    for chunk in r.iter_content(1 << 18):
                        fh.write(chunk)
            break
        except requests.RequestException:
            time.sleep(5 * (i + 1))
    else:
        raise SystemExit(f"could not download {url}")
    tmp.replace(path)
    return path


def main():
    LIDAR.mkdir(parents=True, exist_ok=True)
    to_ll = pyproj.Transformer.from_crs(EPSG, 4326, always_xy=True)
    to_utm = pyproj.Transformer.from_crs(4326, EPSG, always_xy=True)
    manifest, jobs = {}, []
    for s in sites(sys.argv[1:]):
        x0, y0, x1, y1 = work_bbox(s)
        lo, hi = to_ll.transform(x0, y0), to_ll.transform(x1, y1)
        tiles = []
        for it in tnm_items((lo[0], lo[1], hi[0], hi[1])):
            if PROJECT_NAME not in it["title"]:
                continue
            bb = it["boundingBox"]
            tx0, ty0 = to_utm.transform(bb["minX"], bb["minY"])
            tx1, ty1 = to_utm.transform(bb["maxX"], bb["maxY"])
            if (min(x1, tx1) - max(x0, tx0) < MIN_OVERLAP_M or
                    min(y1, ty1) - max(y0, ty0) < MIN_OVERLAP_M):
                continue
            name = it["downloadURL"].rsplit("/", 1)[-1]
            print(f"{s['id']}: {name}  {it['sizeInBytes'] / 1e6:.0f} MB", flush=True)
            jobs.append((it["downloadURL"], LIDAR / name))
            tiles.append(dict(file=name, url=it["downloadURL"],
                              published=it.get("publicationDate"),
                              meta=it.get("metaUrl")))
        if not tiles:
            raise SystemExit(f"no {PROJECT_NAME} tiles found for {s['id']}")
        manifest[s["id"]] = tiles
    # The USGS server is slow per connection, so fetch the tiles side by side
    with ThreadPoolExecutor(8) as pool:
        for path in pool.map(lambda j: download(*j), jobs):
            print("have", path.name, f"{path.stat().st_size / 1e6:.0f} MB", flush=True)
    out = LIDAR / "manifest.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    old.update(manifest)
    out.write_text(json.dumps(dict(project=PROJECT_NAME, **{k: v for k, v in old.items() if k != "project"}), indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
