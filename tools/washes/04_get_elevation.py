"""Step 1d: download the USGS 1 m bare-ground elevation tiles over the study area.

These are the 10 km tiles USGS made from the 2021 Pima County lidar flight
(the same flight Project 1 uses). About 300 MB each; six cover the draft
study area. Downloads resume if interrupted.

Run:  py tools/washes/04_get_elevation.py
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from common import BBOX, USER_AGENT, WORK, bbox_lonlat

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
PROJECT = "AZ_PimaCounty_2021_B21"
OUT = WORK / "dem"


def tiles():
    for i in range(6):
        try:
            r = requests.get(TNM, params=dict(
                datasets="Digital Elevation Model (DEM) 1 meter",
                bbox=",".join(f"{v:.5f}" for v in bbox_lonlat()),
                max=100, outputFormat="JSON"), headers=USER_AGENT, timeout=120).json()
            break
        except (requests.RequestException, ValueError):
            time.sleep(5 * (i + 1))
    else:
        raise SystemExit("the USGS product list did not answer")
    out = []
    for it in r["items"]:
        url = it["downloadURL"]
        if PROJECT not in url:
            continue
        # Tile names carry the upper-left corner in 10 km units: x48y357.
        name = url.rsplit("/", 1)[1]
        x = int(name.split("_x")[1][:2]) * 10000
        y = int(name.split("y")[1][:3]) * 10000
        if x < BBOX[2] and x + 10000 > BBOX[0] and y - 10000 < BBOX[3] and y > BBOX[1]:
            out.append((name, url))
    return sorted(out)


def fetch(item):
    name, url = item
    path = OUT / name
    part = OUT / (name + ".part")
    if path.exists():
        return name, path.stat().st_size, "already here"
    for attempt in range(8):
        have = part.stat().st_size if part.exists() else 0
        try:
            with requests.get(url, headers={**USER_AGENT, "Range": f"bytes={have}-"},
                              stream=True, timeout=120) as r:
                if r.status_code == 416:
                    break
                r.raise_for_status()
                mode = "ab" if r.status_code == 206 else "wb"
                with open(part, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            break
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    else:
        return name, 0, "failed"
    part.rename(path)
    return name, path.stat().st_size, "downloaded"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    todo = tiles()
    print(len(todo), "tiles:", [n for n, _ in todo], flush=True)
    with ThreadPoolExecutor(3) as pool:
        done = list(pool.map(fetch, todo))
    for name, size, how in done:
        print(f"{name}  {size / 1e6:.0f} MB  {how}", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(dict(
        fetched=time.strftime("%Y-%m-%d"), source=TNM, project=PROJECT,
        tiles=[dict(name=n, bytes=s, status=h) for n, s, h in done]), indent=2))


if __name__ == "__main__":
    main()
