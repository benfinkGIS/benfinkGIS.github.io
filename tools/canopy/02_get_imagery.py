"""Step 1b: download each site's boundary and its NAIP imagery.

Boundary: the City of Tucson neighborhood association polygon named in
sites.json. Only NAME, STATUS and WARD are requested; the layer's contact
fields are left on the server.

Imagery: the newest NAIP on the USGS NAIPPlus service, all four bands (red,
green, blue, near infrared), at its native 0.3 m, as GeoTIFF tiles covering
the site's working box. The acquisition dates the service reports for the
site are written to imagery.json.

Run:  py tools/canopy/02_get_imagery.py [site_id ...]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from common import EPSG, site_dir, sites, work_bbox

NHA = ("https://gis.tucsonaz.gov/arcgis/rest/services/PublicMaps/"
       "NeighborhoodsPlans/MapServer/0/query")
NAIP = ("https://imagery.nationalmap.gov/arcgis/rest/services/"
        "USGSNAIPPlus/ImageServer")
CELL = 0.3
TILE_PX = 2000        # larger requests time out on this server


def get(url, params, tries=6, timeout=180):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
        except requests.RequestException:
            pass
        time.sleep(4 * (i + 1))
    raise SystemExit(f"gave up on {url}")


def boundary(site, out):
    name = site["boundary_name"].replace("'", "''")
    r = get(NHA, dict(where=f"NAME = '{name}'", outFields="NAME,STATUS,WARD",
                      outSR=EPSG, f="geojson"))
    gj = r.json()
    if len(gj.get("features", [])) != 1:
        raise SystemExit(f"{site['id']}: expected one boundary, got "
                         f"{len(gj.get('features', []))}")
    gj["crs"] = dict(type="name", properties=dict(name=f"EPSG:{EPSG}"))
    (out / "boundary.geojson").write_text(json.dumps(gj))


def tile(job):
    path, bbox, w, h = job
    if not path.exists():
        r = get(NAIP + "/exportImage", dict(
            bbox=",".join(f"{v:.2f}" for v in bbox), bboxSR=EPSG, imageSR=EPSG,
            size=f"{w},{h}", format="tiff", pixelType="U8",
            bandIds="0,1,2,3", interpolation="RSP_NearestNeighbor", f="image"))
        if r.content[:2] not in (b"II", b"MM"):
            raise SystemExit(f"not a TIFF: {r.content[:200]!r}")
        path.write_bytes(r.content)
    return path


def dates(site):
    x0, y0, x1, y1 = work_bbox(site)
    r = get(NAIP + "/query", dict(
        geometry=f"{x0},{y0},{x1},{y1}", geometryType="esriGeometryEnvelope",
        inSR=EPSG, spatialRel="esriSpatialRelIntersects",
        returnGeometry="false", f="json",
        outFields="Year,acquisition_date,resolution_value,Category"))
    out = set()
    for f in r.json().get("features", []):
        a = f["attributes"]
        if a.get("Category") == 1 and a.get("acquisition_date"):
            out.add((time.strftime("%Y-%m-%d", time.gmtime(a["acquisition_date"] / 1000)),
                     a.get("resolution_value")))
    return sorted(out)


def main():
    for s in sites(sys.argv[1:]):
        out = site_dir(s)
        boundary(s, out)
        x0, y0, x1, y1 = work_bbox(s)
        span = CELL * TILE_PX
        (out / "naip").mkdir(exist_ok=True)
        jobs = []
        ny = int(-(-(y1 - y0) // span))
        nx = int(-(-(x1 - x0) // span))
        for r in range(ny):
            for c in range(nx):
                bx, by = x0 + c * span, y0 + r * span
                w = min(TILE_PX, round((x1 - bx) / CELL))
                h = min(TILE_PX, round((y1 - by) / CELL))
                jobs.append((out / "naip" / f"naip_r{r}_c{c}.tif",
                             (bx, by, bx + w * CELL, by + h * CELL), w, h))
        with ThreadPoolExecutor(4) as pool:
            done = list(pool.map(tile, jobs))
        d = dates(s)
        (out / "imagery.json").write_text(json.dumps(dict(
            source="USGS NAIPPlus image service", cell_m=CELL,
            bands=["red", "green", "blue", "near infrared"],
            acquired=[dict(date=a, resolution_m=b) for a, b in d],
            tiles=[p.name for p in done]), indent=1))
        print(s["id"], len(done), "NAIP tiles; acquired", d)


if __name__ == "__main__":
    main()
