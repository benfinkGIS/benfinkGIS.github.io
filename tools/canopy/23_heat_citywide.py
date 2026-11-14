"""Step 9d: the canopy-to-temperature relationship across all of Tucson.

Runs in the system Python with Earth Engine (after ee_signin.py and
14_heat.py):

  py tools/canopy/23_heat_citywide.py

14_heat.py fits surface temperature to land cover inside the two study
neighborhoods, where canopy barely varies from block to block. This step
fits it across the whole built-up city instead, on a 90 m grid, which is the
method the project set out to use:

  temperature   the same Landsat 8 and 9 summer median as step 13
  tree canopy   Meta and WRI's global canopy height map (about 1 m), counted
                as canopy at 2 m or taller. It is first compared with the
                lidar canopy in the two neighborhoods' blocks, and the fitted
                slope converts its units to lidar canopy
  pavement      NLCD 2021 impervious surface
  elevation     USGS 3DEP, because the basin floor is warmer than its edges
  where         blocks that are at least half developed land in NLCD, inside
                the box around the city's neighborhood associations

Two fits are reported. The plain fit compares blocks across the whole city.
The local fit compares each block only with others in the same square of
about 1.8 km, which removes whatever differs between parts of town (soil,
irrigation, distance from the mountains). Intervals come from resampling
2.7 km squares, so neighbouring blocks are not counted as independent.

Still surface temperature at about 11 a.m., and still an association, not an
experiment: leafier blocks differ from bare ones in more than their trees.

Writes work/heat_citywide.json and work/citywide_blocks.npz.
"""
import csv
import importlib.util
import io
import json
import time
from pathlib import Path

import ee
import numpy as np
import requests
from PIL import Image

from common import EPSG, WORK

BLOCK = 90
TILE = 100                 # blocks per download tile side
META = "projects/meta-forest-monitoring-okw37/assets/CanopyHeight"
CANOPY_MIN_M = 2
YEARS = (2021, 2022, 2023)
LOCAL_CELLS = 20           # 1.8 km squares for the local fit
BOOT_CELLS = 30            # 2.7 km squares for the intervals
SCEN = ["Street trees", "Streets and homes", "Full build-out"]
Image.MAX_IMAGE_PIXELS = None

_spec = importlib.util.spec_from_file_location(
    "lst", Path(__file__).with_name("13_surface_temperature.py"))
_lst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lst)


def stack():
    """One image on a 90 m grid: temperature, canopy, pavement, elevation,
    developed share, clear-scene count."""
    proj = ee.Projection(f"EPSG:{EPSG}")
    col = None
    for sat in ("LC08", "LC09"):
        for year in YEARS:
            c = ee.ImageCollection(f"LANDSAT/{sat}/C02/T1_L2").filterDate(f"{year}-06-01", f"{year}-09-01")
            col = c if col is None else col.merge(c)
    lst = col.map(_lst.clear_celsius)
    canopy = ee.ImageCollection(META).mosaic().gte(CANOPY_MIN_M)
    nlcd = ee.ImageCollection("USGS/NLCD_RELEASES/2021_REL/NLCD").first()
    developed = nlcd.select("landcover").gte(21).And(nlcd.select("landcover").lte(24))

    def to_blocks(img, native_m):
        return (img.toFloat().setDefaultProjection(proj.atScale(native_m))
                .reduceResolution(ee.Reducer.mean(), maxPixels=12000))

    return ee.Image.cat([
        to_blocks(lst.median(), 30).rename("lst"),
        to_blocks(canopy.unmask(0), 1.2).rename("canopy"),
        to_blocks(nlcd.select("impervious").divide(100), 30).rename("pavement"),
        to_blocks(ee.Image("USGS/3DEP/10m").select("elevation"), 10).rename("elevation"),
        to_blocks(developed, 30).rename("developed"),
        to_blocks(lst.count(), 30).rename("clear"),
    ]).toFloat()


def download(img, x0, y1, cols, rows):
    url = img.getDownloadURL(dict(
        format="NPY", crs=f"EPSG:{EPSG}", crs_transform=[BLOCK, 0, x0, 0, -BLOCK, y1],
        dimensions=[cols, rows]))
    for i in range(5):
        r = requests.get(url, timeout=600)
        if r.status_code == 200:
            return np.load(io.BytesIO(r.content))
        time.sleep(10 * (i + 1))
    raise SystemExit(f"Earth Engine download failed: {r.status_code} {r.text[:200]}")


def fit(y, X):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, 1 - resid.var() / y.var()


def demean(v, groups):
    sums = np.bincount(groups, weights=v)
    return v - (sums / np.bincount(groups))[groups]


def main():
    ee.Initialize(project=(WORK / "ee_project.txt").read_text().strip())
    gj = json.loads((WORK / "screen" / "neighborhoods.geojson").read_text())
    xs, ys = [], []
    for f in gj["features"]:
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            a = np.asarray(poly[0])
            xs += [a[:, 0].min(), a[:, 0].max()]
            ys += [a[:, 1].min(), a[:, 1].max()]
    snap = lambda v, up: ((v - 15) // BLOCK + (1 if up else 0)) * BLOCK + 15
    x0, y1 = snap(min(xs), False), snap(max(ys), True)
    cols = int((snap(max(xs), True) - x0) / BLOCK)
    rows = int((y1 - snap(min(ys), False)) / BLOCK)
    print(f"city grid: {cols} x {rows} blocks of {BLOCK} m", flush=True)

    img = stack()
    names = ["lst", "canopy", "pavement", "elevation", "developed", "clear"]
    cache = WORK / "citywide_blocks.npz"
    if cache.exists():
        grid = dict(np.load(cache))
    else:
        grid = {n: np.full((rows, cols), np.nan, np.float32) for n in names}
        for r in range(0, rows, TILE):
            for c in range(0, cols, TILE):
                h, w = min(TILE, rows - r), min(TILE, cols - c)
                arr = download(img, x0 + c * BLOCK, y1 - r * BLOCK, w, h)
                for n in names:
                    grid[n][r:r + h, c:c + w] = arr[n]
                print(f"  tile row {r}, col {c}", flush=True)
        np.savez_compressed(cache, x0=x0, y1=y1, **grid)

    # ---- calibrate the canopy layer against the lidar blocks -------------
    blocks = [b for b in csv.DictReader(open(WORK / "heat_blocks.csv")) if b["lst_degC"] != "nan"]
    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Rectangle(
            [float(b["x"]) - 45, float(b["y"]) - 45, float(b["x"]) + 45, float(b["y"]) + 45],
            proj=f"EPSG:{EPSG}", geodesic=False), {"i": i}) for i, b in enumerate(blocks)])
    res = (ee.ImageCollection(META).mosaic().gte(CANOPY_MIN_M).unmask(0)
           .reduceRegions(fc, ee.Reducer.mean(), scale=1.2, crs=f"EPSG:{EPSG}").getInfo())
    meta = np.full(len(blocks), np.nan)
    for f in res["features"]:
        meta[f["properties"]["i"]] = f["properties"]["mean"]
    lidar = np.array([float(b["share_tree"]) for b in blocks])
    slope, intercept = np.polyfit(lidar, meta, 1)
    calib = dict(blocks=len(blocks), r=round(float(np.corrcoef(lidar, meta)[0, 1]), 2),
                 slope=round(float(slope), 3), intercept=round(float(intercept), 3))
    print("canopy layer vs lidar:", calib, flush=True)

    # ---- the fits ----------------------------------------------------------
    ok = (np.isfinite(grid["lst"]) & np.isfinite(grid["canopy"]) & np.isfinite(grid["pavement"]) &
          np.isfinite(grid["elevation"]) & (grid["developed"] >= 0.5) & (grid["clear"] >= 5))
    rr, cc = np.nonzero(ok)
    y = grid["lst"][ok].astype(float)
    canopy, pave = grid["canopy"][ok].astype(float), grid["pavement"][ok].astype(float)
    elev = grid["elevation"][ok].astype(float)
    X = np.column_stack([np.ones(len(y)), canopy, pave, elev - elev.mean()])
    plain, r2_plain = fit(y, X)
    local_id = (rr // LOCAL_CELLS) * 10000 + cc // LOCAL_CELLS
    _, local_id = np.unique(local_id, return_inverse=True)
    Xl = np.column_stack([demean(v, local_id) for v in (canopy, pave, elev)])
    yl = demean(y, local_id)
    local, r2_local = fit(yl, Xl)

    boot_id = (rr // BOOT_CELLS) * 10000 + cc // BOOT_CELLS
    uniq, boot_id = np.unique(boot_id, return_inverse=True)
    members = [np.nonzero(boot_id == k)[0] for k in range(len(uniq))]
    rng = np.random.default_rng(20261114)
    draws = {"plain": [], "local": []}
    for _ in range(400):
        pick = np.concatenate([members[k] for k in rng.integers(0, len(uniq), len(uniq))])
        draws["plain"].append(fit(y[pick], X[pick])[0][1])
        draws["local"].append(fit(yl[pick], Xl[pick])[0][0])

    def summary(beta_canopy, beta_pave, r2, key):
        lo, hi = np.percentile(draws[key], [2.5, 97.5])
        return dict(
            canopy_degC_per_full_block=round(float(beta_canopy), 2),
            interval_95=[round(float(lo), 2), round(float(hi), 2)],
            pavement_degC_per_full_block=round(float(beta_pave), 2), r2=round(float(r2), 2),
            # per unit of lidar canopy: the layer sees `slope` of what the lidar does
            canopy_lidar_units=round(float(beta_canopy * slope), 2),
            interval_lidar_units=[round(float(lo * slope), 2), round(float(hi * slope), 2)])

    out = dict(
        blocks=int(ok.sum()), block_m=BLOCK, grid=[int(cols), int(rows)],
        canopy_layer="Meta and WRI global canopy height, 2 m or taller",
        calibration=calib,
        canopy_share=dict(mean=round(float(canopy.mean()), 3),
                          p5=round(float(np.percentile(canopy, 5)), 3),
                          p95=round(float(np.percentile(canopy, 95)), 3)),
        lst=dict(mean=round(float(y.mean()), 1), sd=round(float(y.std()), 2)),
        plain=summary(plain[1], plain[2], r2_plain, "plain"),
        local=summary(local[0], local[1], r2_local, "local"),
        elevation_degC_per_100m=round(float(plain[3] * 100), 2),
        local_square_m=LOCAL_CELLS * BLOCK, bootstrap_square_m=BOOT_CELLS * BLOCK, sites={})

    # ---- apply to the scenarios -------------------------------------------
    for site in sorted({b["site"] for b in blocks}):
        mine = [b for b in blocks if b["site"] == site]
        w = np.array([float(b["inside_share"]) for b in mine]) + 1e-9
        out["sites"][site] = {}
        for n, name in enumerate(SCEN, 1):
            added = np.average([float(b[f"new_canopy_s{n}"]) for b in mine], weights=w)
            est = {}
            for key in ("plain", "local"):
                b = out[key]
                est[key] = dict(
                    change_degC=round(float(added * b["canopy_lidar_units"]), 2),
                    interval_95=[round(float(added * b["interval_lidar_units"][0]), 2),
                                 round(float(added * b["interval_lidar_units"][1]), 2)])
            out["sites"][site][name] = dict(canopy_added_share=round(float(added), 3), **est)
    (WORK / "heat_citywide.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
