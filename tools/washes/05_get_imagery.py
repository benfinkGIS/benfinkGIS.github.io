"""Step 2a: download 4-band NAIP imagery at 1 m over the study area.

The newest NAIP on the USGS NAIPPlus service (red, green, blue, near
infrared), resampled from its native 0.3 m to 1 m, as GeoTIFF tiles of
2 x 2 km. The same imagery is fetched over Project 1's two neighborhoods,
where the canopy has been mapped from lidar and checked by hand, so the
canopy rule used here can be set and scored against it.

Run:  py tools/washes/05_get_imagery.py
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from common import BBOX, EPSG, ROOT, USER_AGENT, WORK

NAIP = ("https://imagery.nationalmap.gov/arcgis/rest/services/"
        "USGSNAIPPlus/ImageServer")
CELL = 1.0
TILE_PX = 2000        # larger requests time out on this server


def get(url, params, tries=8, timeout=240):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=USER_AGENT, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
        except requests.RequestException:
            pass
        time.sleep(5 * (i + 1))
    raise SystemExit(f"gave up on {url}")


def tile(job):
    path, bbox, w, h = job
    if not path.exists():
        for attempt in range(4):
            r = get(NAIP + "/exportImage", dict(
                bbox=",".join(f"{v:.2f}" for v in bbox), bboxSR=EPSG, imageSR=EPSG,
                size=f"{w},{h}", format="tiff", pixelType="U8",
                bandIds="0,1,2,3", interpolation="RSP_BilinearInterpolation", f="image"))
            if r.content[:2] in (b"II", b"MM"):
                break
            time.sleep(10 * (attempt + 1))
        else:
            raise SystemExit(f"not a TIFF: {r.content[:200]!r}")
        path.write_bytes(r.content)
    return path


def jobs_for(box, folder):
    x0, y0, x1, y1 = box
    folder.mkdir(parents=True, exist_ok=True)
    span = CELL * TILE_PX
    out = []
    for r in range(int(-(-(y1 - y0) // span))):
        for c in range(int(-(-(x1 - x0) // span))):
            bx, by = x0 + c * span, y0 + r * span
            w = min(TILE_PX, round((x1 - bx) / CELL))
            h = min(TILE_PX, round((y1 - by) / CELL))
            out.append((folder / f"naip_r{r:02d}_c{c:02d}.tif",
                        (bx, by, bx + w * CELL, by + h * CELL), w, h))
    return out


def dates(box):
    x0, y0, x1, y1 = box
    r = get(NAIP + "/query", dict(
        geometry=f"{x0},{y0},{x1},{y1}", geometryType="esriGeometryEnvelope",
        inSR=EPSG, spatialRel="esriSpatialRelIntersects",
        returnGeometry="false", f="json",
        outFields="Year,acquisition_date,resolution_value,Category"))
    out = set()
    for f in r.json().get("features", []):
        a = f["attributes"]
        if a.get("Category") == 1 and a.get("acquisition_date"):
            out.add(time.strftime("%Y-%m-%d", time.gmtime(a["acquisition_date"] / 1000)))
    return sorted(out)


def main():
    jobs = jobs_for(BBOX, WORK / "naip")
    canopy = json.loads((ROOT / "tucson-canopy" / "sites.json").read_text(encoding="utf-8"))
    cal = {}
    for s in canopy["sites"]:
        x0, y0, x1, y1 = s["bbox_utm12n"]
        b = canopy["buffer_m"]
        box = (x0 - b, y0 - b, x1 + b, y1 + b)
        cal[s["id"]] = box
        jobs += jobs_for(box, WORK / "naip_cal" / s["id"])
    print(len(jobs), "tiles to fetch", flush=True)
    with ThreadPoolExecutor(6) as pool:
        done = list(pool.map(tile, jobs))
    (WORK / "naip" / "imagery.json").write_text(json.dumps(dict(
        source="USGS NAIPPlus image service", cell_m=CELL,
        bands=["red", "green", "blue", "near infrared"],
        acquired=dates(BBOX), calibration_boxes=cal, tiles=len(done)), indent=1))
    print(len(done), "tiles; acquired", dates(BBOX), flush=True)


if __name__ == "__main__":
    main()
