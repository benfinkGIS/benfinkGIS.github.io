"""Desktop screen of Tucson neighborhoods for the canopy scenario project.

Ranks every registered City of Tucson neighborhood association by how green
it is, so the two study sites (a well-shaded reference and an improvement
candidate) are picked from numbers and not from memory.

What it measures: the share of each neighborhood where NAIP's NDVI is above a
threshold, on a 4 m grid. That is green vegetation of any kind (trees, shrubs,
watered turf), so it is a ranking tool only. The real canopy figure comes
later from lidar.

Writes to tucson-canopy/work/screen/ (git-ignored):
  neighborhoods.geojson  boundaries with the screen results (UTM 12N)
  screen.csv             one row per neighborhood
  ndvi.npy, ndvi.json    the NDVI grid and its georeferencing
  tiles/                 cached NAIP downloads

Only NAME, STATUS and WARD are requested from the city layer. It also holds
officers' names, phones and emails, which this project has no use for.

Run:  py tools/screen_canopy_sites.py [--cell 4] [--ndvi 0.2]
"""
import argparse
import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tucson-canopy" / "work" / "screen"
NHA_URL = ("https://gis.tucsonaz.gov/arcgis/rest/services/PublicMaps/"
           "NeighborhoodsPlans/MapServer/0/query")
NAIP_URL = ("https://imagery.nationalmap.gov/arcgis/rest/services/"
            "USGSNAIPPlus/ImageServer")
EPSG = 26912          # NAD83 / UTM zone 12N, metres
TILE_PX = 2000        # 4000 px requests time out on this server
UA = {"User-Agent": "canopy-screen/1.0"}


def get(url, params, tries=5, timeout=120):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
        except requests.RequestException:
            pass
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"gave up on {url}")


def neighborhoods():
    r = get(NHA_URL, dict(where="1=1", outFields="NAME,STATUS,WARD",
                          outSR=EPSG, f="geojson"))
    feats = r.json()["features"]
    return [f for f in feats if f.get("geometry")]


def rings(geom):
    """Yield (outer, holes) for each polygon part."""
    polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
             else [geom["coordinates"]])
    for p in polys:
        yield p[0], p[1:]


def ring_area(ring):
    a = np.asarray(ring)
    x, y = a[:, 0], a[:, 1]
    return abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2


def naip_tile(job):
    path, bbox, w, h = job
    if not path.exists():
        r = get(NAIP_URL + "/exportImage", dict(
            bbox=",".join(f"{v:.1f}" for v in bbox), bboxSR=EPSG,
            imageSR=EPSG, size=f"{w},{h}", format="png",
            bandIds="3,0,1",          # near infrared, red, green
            interpolation="RSP_BilinearInterpolation", f="image"))
        Image.open(io.BytesIO(r.content)).verify()
        path.write_bytes(r.content)
    return path


def naip_dates(x, y):
    r = get(NAIP_URL + "/query", dict(
        geometry=f"{x},{y}", geometryType="esriGeometryPoint", inSR=EPSG,
        spatialRel="esriSpatialRelIntersects", returnGeometry="false",
        outFields="Year,acquisition_date,resolution_value,Category",
        f="json"))
    rows = [f["attributes"] for f in r.json().get("features", [])]
    out = set()
    for a in rows:
        if a.get("Category") == 1 and a.get("acquisition_date"):
            d = time.strftime("%Y-%m-%d", time.gmtime(a["acquisition_date"] / 1000))
            out.add((d, a.get("resolution_value")))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=float, default=4.0, help="grid cell, m")
    ap.add_argument("--ndvi", type=float, default=0.2,
                    help="NDVI above this counts as green")
    args = ap.parse_args()
    cell = args.cell
    (OUT / "tiles").mkdir(parents=True, exist_ok=True)

    feats = neighborhoods()
    print(len(feats), "neighborhood polygons;",
          "status values:", sorted({f["properties"]["STATUS"] or "" for f in feats}))

    xs, ys = [], []
    for f in feats:
        for outer, _ in rings(f["geometry"]):
            a = np.asarray(outer)
            xs += [a[:, 0].min(), a[:, 0].max()]
            ys += [a[:, 1].min(), a[:, 1].max()]
    span = cell * TILE_PX
    x0 = np.floor(min(xs) / span) * span
    y0 = np.floor(min(ys) / span) * span
    nx = int(np.ceil((max(xs) - x0) / span))
    ny = int(np.ceil((max(ys) - y0) / span))
    y1 = y0 + ny * span
    print(f"grid {nx} x {ny} tiles of {span / 1000:.0f} km at {cell} m")

    jobs = []
    for r in range(ny):
        for c in range(nx):
            bx = x0 + c * span
            by = y1 - (r + 1) * span
            jobs.append((OUT / "tiles" / f"naip_{cell:g}m_r{r}_c{c}.png",
                         (bx, by, bx + span, by + span), TILE_PX, TILE_PX))
    with ThreadPoolExecutor(4) as pool:
        paths = list(pool.map(naip_tile, jobs))

    ndvi = np.zeros((ny * TILE_PX, nx * TILE_PX), np.float32)
    nodata = np.zeros(ndvi.shape, bool)
    for i, p in enumerate(paths):
        r, c = divmod(i, nx)
        a = np.asarray(Image.open(p).convert("RGB"), np.float32)
        nir, red = a[..., 0], a[..., 1]
        s = nir + red
        v = np.where(s > 0, (nir - red) / np.maximum(s, 1), 0)
        sl = (slice(r * TILE_PX, (r + 1) * TILE_PX),
              slice(c * TILE_PX, (c + 1) * TILE_PX))
        ndvi[sl] = v
        nodata[sl] = s == 0
    np.save(OUT / "ndvi.npy", ndvi)
    (OUT / "ndvi.json").write_text(json.dumps(
        dict(epsg=EPSG, cell=cell, x0=x0, y_top=y1, shape=ndvi.shape,
             bands="NDVI from NAIP bands 4 and 1")))

    rows = []
    for f in feats:
        g = f["geometry"]
        area = 0.0
        bx0 = by0 = np.inf
        bx1 = by1 = -np.inf
        for outer, holes in rings(g):
            area += ring_area(outer) - sum(ring_area(h) for h in holes)
            a = np.asarray(outer)
            bx0, bx1 = min(bx0, a[:, 0].min()), max(bx1, a[:, 0].max())
            by0, by1 = min(by0, a[:, 1].min()), max(by1, a[:, 1].max())
        c0 = int((bx0 - x0) // cell)
        c1 = int(np.ceil((bx1 - x0) / cell))
        r0 = int((y1 - by1) // cell)
        r1 = int(np.ceil((y1 - by0) / cell))
        w, h = c1 - c0, r1 - r0
        m = Image.new("1", (w, h), 0)
        d = ImageDraw.Draw(m)
        to_px = lambda ring: [((x - x0) / cell - c0, (y1 - y) / cell - r0)
                              for x, y in ring]
        for outer, holes in rings(g):
            d.polygon(to_px(outer), fill=1)
            for hole in holes:
                d.polygon(to_px(hole), fill=0)
        mask = np.asarray(m, bool) & ~nodata[r0:r1, c0:c1]
        vals = ndvi[r0:r1, c0:c1][mask]
        p = f["properties"]
        res = dict(name=p["NAME"], status=p["STATUS"], ward=p["WARD"],
                   km2=round(area / 1e6, 3),
                   green_pct=round(float((vals > args.ndvi).mean() * 100), 1) if vals.size else None,
                   ndvi_mean=round(float(vals.mean()), 3) if vals.size else None,
                   x=round((bx0 + bx1) / 2), y=round((by0 + by1) / 2))
        p.update(res)
        rows.append(res)

    rows.sort(key=lambda r: -(r["green_pct"] or 0))
    with open(OUT / "screen.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (OUT / "neighborhoods.geojson").write_text(json.dumps(
        dict(type="FeatureCollection",
             crs=dict(type="name", properties=dict(name=f"EPSG:{EPSG}")),
             features=feats)))

    mid = rows[len(rows) // 2]
    print("NAIP at a central point:", naip_dates(mid["x"], mid["y"]))
    fit = [r for r in rows if 0.4 <= r["km2"] <= 2.5 and r["green_pct"] is not None]
    print(f"\n{len(fit)} of {len(rows)} are 0.4 to 2.5 km2. Greenest and least green:")
    for r in fit[:15] + [None] + fit[-20:]:
        if r is None:
            print("   ...")
            continue
        print(f"  {r['green_pct']:5.1f}%  ndvi {r['ndvi_mean']:.3f}  "
              f"{r['km2']:5.2f} km2  ward {r['ward'] or '-':<4} {r['name']}  [{r['status']}]")


if __name__ == "__main__":
    main()
