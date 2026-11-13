#!/usr/bin/env python3
"""KXCI 91.3 FM signal reach, step 2: terrain-modelled field strength.

Usage (from the repo root, after tools/build_kxci.py):
    py tools/model_kxci_terrain.py            # elevation, model, block tallies
    py tools/model_kxci_terrain.py --rerun    # run the model again (elevation stays cached)

Needs Python 3 with numpy, scipy, pillow, pyproj, geopandas and itmlogic
(pip install itmlogic: a pure-Python port of the NTIA/ITS Irregular Terrain Model,
better known as Longley-Rice).

What it does
------------
1. Downloads USGS 3DEP elevation for a square around the tower, 30 m cells, UTM 12N.
2. Draws 720 radials from the tower (every half degree), reads the terrain profile
   along each at 100 m steps, and runs the ITM in point-to-point mode to a receiver
   every 200 m out to 75 km. Two receiver heights: 9.1 m (the 30 ft rooftop antenna
   the FCC curves assume) and 1.5 m (a car or a kitchen radio).
3. Turns ITM's attenuation relative to free space into field strength:
       E (dBu) = 106.92 + 10 log10(ERP kW) - 20 log10(d km) - A
   using the median in time, location and situation, to line up with F(50,50).
4. Reads the modelled field at every census block's internal point and counts who is
   at or above 60 dBu, inside and outside the FCC contour.

Assumptions worth knowing
-------------------------
- ERP is the licensed 18 kW in every direction (the antenna is non-directional). The
  vertical pattern of the four-bay antenna is ignored, so places almost under the tower
  are a little optimistic.
- Bare-earth terrain only: no buildings, no trees, no multipath, no co-channel or
  adjacent-channel interference.
- Ground: relative permittivity 15, conductivity 0.005 S/m (average ground);
  continental temperate climate; surface refractivity 301 N-units reduced for the
  mean elevation of each path; horizontal polarisation.

Output
------
kxci-signal/work/dem.npy, dem.json        elevation and its extent
kxci-signal/work/field.npz                field strength on the polar grid
kxci-signal/work/kxci.gpkg (layer blocks) gains dbu_9m, dbu_1p5m
kxci-signal/work/summary.json             gains the "terrain" section
"""
import argparse
import cmath
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "kxci-signal" / "work"
TILES = WORK / "tiles"

DEM_URL = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
           "3DEPElevation/ImageServer/exportImage")
CELL = 30.0               # elevation cell, metres
HALF = 78_000.0           # half-width of the elevation square, metres
TILE_PX = 1300

N_AZ = 720                # radials
STEP = 100.0              # terrain profile spacing, metres
RX_EVERY = 2              # a receiver every RX_EVERY profile steps (200 m)
R_MAX = 75_000.0
R_MIN = 1_000.0           # ITM is not valid closer than 1 km
RX_HEIGHTS = (9.1, 1.5)
FMHZ = 91.3
THRESH = 60.0             # dBu, same level as the FCC service contour

EPS, SGM, ENS0, KLIM, MDVAR = 15.0, 0.005, 301.0, 5, 3


# ---------------------------------------------------------------- elevation

def download(params, path):
    if path.exists() and path.stat().st_size > 10000:
        return "cached"
    req = urllib.request.Request(DEM_URL + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "terrain-scene/0.1"})
    for attempt in range(8):        # the USGS servers return 500/502 now and then
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read()
            if body[:1] == b"{":
                raise RuntimeError(body[:200].decode())
            break
        except Exception as exc:
            if attempt == 7:
                raise
            print(f"  retry {attempt + 1} {path.name}: {exc}", flush=True)
            time.sleep(6 * (attempt + 1))
    tmp = path.with_suffix(".part")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    return f"{len(body) / 1e6:.1f} MB"


def fetch_dem(tx_x, tx_y):
    from PIL import Image
    meta_path, dem_path = WORK / "dem.json", WORK / "dem.npy"
    x0 = round(tx_x - HALF)
    y1 = round(tx_y + HALF)
    n = round(2 * HALF / CELL)
    if meta_path.exists() and dem_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta["x0"] == x0 and meta["y1"] == y1 and meta["n"] == n:
            return np.load(dem_path), meta
    TILES.mkdir(parents=True, exist_ok=True)
    jobs = []
    for r, top in enumerate(range(0, n, TILE_PX)):
        h = min(TILE_PX, n - top)
        for c, left in enumerate(range(0, n, TILE_PX)):
            w = min(TILE_PX, n - left)
            bx1, by2 = x0 + left * CELL, y1 - top * CELL
            bbox = (bx1, by2 - h * CELL, bx1 + w * CELL, by2)
            params = dict(format="tiff", pixelType="F32", noData=-9999,
                          interpolation="RSP_BilinearInterpolation",
                          bbox=",".join(str(v) for v in bbox), bboxSR=26912, imageSR=26912,
                          size=f"{w},{h}", f="image")
            jobs.append((r, c, TILES / f"dem_{x0}_{y1}_r{r}_c{c}.tif", params))

    def run(job):
        r, c, path, params = job
        print(f"  dem r{r} c{c}: {download(params, path)}", flush=True)
        return r, c, path

    with ThreadPoolExecutor(3) as pool:
        done = list(pool.map(run, jobs))
    grid = {}
    for r, c, path in done:
        grid.setdefault(r, {})[c] = path
    z = np.vstack([np.hstack([np.array(Image.open(grid[r][c]), dtype="float32")
                              for c in sorted(grid[r])]) for r in sorted(grid)])
    z[z < -1000] = np.nan
    empty = float(np.isnan(z).mean())
    print(f"  dem {z.shape}, {np.nanmin(z):.0f} to {np.nanmax(z):.0f} m, "
          f"{empty * 100:.3f}% empty")
    z = np.where(np.isnan(z), np.nanmin(z), z).astype("float32")
    meta = dict(x0=x0, y1=y1, n=n, cell=CELL, crs=26912)
    np.save(dem_path, z)
    meta_path.write_text(json.dumps(meta))
    return z, meta


def sample_dem(z, meta, x, y):
    """Bilinear elevation at UTM x, y (arrays)."""
    from scipy.ndimage import map_coordinates
    col = (np.asarray(x) - meta["x0"]) / meta["cell"] - 0.5
    row = (meta["y1"] - np.asarray(y)) / meta["cell"] - 0.5
    return map_coordinates(z, [row, col], order=1, mode="nearest")


# ---------------------------------------------------------------- the model

def itm_attenuation(elev, step, h_tx, h_rx):
    """Median ITM attenuation relative to free space (dB) and the warning code."""
    from itmlogic.preparatory_subroutines.qlrpfl import qlrpfl
    from itmlogic.statistics.avar import avar
    prop = {"kwx": 0, "wn": FMHZ / 47.7}
    prop["ens"] = ENS0 * math.exp(-(sum(elev) / len(elev)) / 9460)
    prop["gme"] = 157e-9 * (1 - 0.04665 * math.exp(prop["ens"] / 179.3))
    zq = complex(EPS, 376.62 * SGM / prop["wn"])
    prop["zgnd"] = cmath.sqrt(zq - 1)          # horizontal polarisation
    prop["hg"] = [h_tx, h_rx]
    prop["klimx"], prop["mdvarx"], prop["lvar"] = KLIM, MDVAR, 5
    prop["klim"], prop["mdvar"] = KLIM, MDVAR
    prop["pfl"] = [len(elev) - 1, step] + elev
    prop = qlrpfl(prop)
    a, prop = avar(0.0, 0.0, 0.0, prop)
    return a, prop["kwx"]


def run_radial(job):
    idx, elev, h_tx, erp_kw = job
    k0 = int(round(R_MIN / STEP))
    ks = range(k0, len(elev), RX_EVERY)
    out = np.full((len(RX_HEIGHTS), len(ks)), np.nan, dtype="float32")
    warn = np.zeros(len(ks), dtype="uint8")
    for j, k in enumerate(ks):
        d_km = k * STEP / 1000
        free = 106.92 + 10 * math.log10(erp_kw) - 20 * math.log10(d_km)
        for h, h_rx in enumerate(RX_HEIGHTS):
            try:
                a, kwx = itm_attenuation(elev[:k + 1], STEP, h_tx, h_rx)
            except (ValueError, ZeroDivisionError, OverflowError):
                continue
            out[h, j] = free - a
            if h == 0:
                warn[j] = kwx
    return idx, out, warn


def run_model(z, meta, tx_x, tx_y, h_tx, erp_kw):
    n_r = int(round(R_MAX / STEP)) + 1
    d = np.arange(n_r) * STEP
    az = np.arange(N_AZ) * (360.0 / N_AZ)
    jobs = []
    for i, a in enumerate(np.radians(az)):
        elev = sample_dem(z, meta, tx_x + d * math.sin(a), tx_y + d * math.cos(a))
        jobs.append((i, [float(v) for v in elev], h_tx, erp_kw))
    k0 = int(round(R_MIN / STEP))
    rx_d = d[k0::RX_EVERY]
    field = np.full((len(RX_HEIGHTS), N_AZ, len(rx_d)), np.nan, dtype="float32")
    warn = np.zeros((N_AZ, len(rx_d)), dtype="uint8")
    t0 = time.time()
    workers = max(1, (os.cpu_count() or 4) - 2)
    with ProcessPoolExecutor(workers) as pool:
        for n, (i, out, w) in enumerate(pool.map(run_radial, jobs, chunksize=4), 1):
            field[:, i, :] = out
            warn[i] = w
            if n % 90 == 0:
                print(f"  {n}/{N_AZ} radials, {time.time() - t0:.0f} s", flush=True)
    np.savez_compressed(WORK / "field.npz", field=field, warn=warn, az=az, d=rx_d,
                        rx_heights=np.array(RX_HEIGHTS), tx=np.array([tx_x, tx_y]),
                        h_tx=h_tx, erp_kw=erp_kw)
    return field, warn, rx_d


def field_at(field2d, rx_d, tx_x, tx_y, x, y):
    """Modelled field (dBu) at UTM points, bilinear on the polar grid. NaN off the grid."""
    from scipy.ndimage import map_coordinates
    dx, dy = np.asarray(x) - tx_x, np.asarray(y) - tx_y
    dist = np.hypot(dx, dy)
    a = (np.degrees(np.arctan2(dx, dy)) % 360.0) / (360.0 / N_AZ)
    r = (dist - rx_d[0]) / (rx_d[1] - rx_d[0])
    wrapped = np.vstack([field2d, field2d[:1]])
    filled = np.where(np.isnan(wrapped), -999.0, wrapped)
    out = map_coordinates(filled, [a, np.clip(r, 0, len(rx_d) - 1)], order=1, mode="nearest")
    out[(dist > rx_d[-1]) | (out < -500)] = np.nan
    return out


# ---------------------------------------------------------------- tallies

def tally_blocks(field, rx_d, tx_x, tx_y):
    import geopandas as gpd
    gpkg = WORK / "kxci.gpkg"
    blocks = gpd.read_file(gpkg, layer="blocks")
    for h, name in enumerate(("dbu_9m", "dbu_1p5m")):
        blocks[name] = field_at(field[h], rx_d, tx_x, tx_y, blocks.px.values, blocks.py.values)
    # inside the 1 km ring the model does not run; the tower is in plain sight there
    near = blocks.dist_km < R_MIN / 1000
    blocks.loc[near, ["dbu_9m", "dbu_1p5m"]] = 120.0
    blocks.to_file(gpkg, layer="blocks", driver="GPKG")

    pop, hh, w = blocks["pop"], blocks.households, blocks.in_fcc
    out = {}
    for name in ("dbu_9m", "dbu_1p5m"):
        ok = (blocks[name] >= THRESH).astype(float)
        out[name] = dict(
            served=dict(population=round(float((pop * ok).sum())),
                        households=round(float((hh * ok).sum()))),
            inside_fcc_served=round(float((pop * w * ok).sum())),
            inside_fcc_shadowed=round(float((pop * w * (1 - ok)).sum())),
            inside_fcc_shadowed_households=round(float((hh * w * (1 - ok)).sum())),
            outside_fcc_served=round(float((pop * (1 - w) * ok).sum())))
    by_place = []
    for name, sub in blocks[blocks.place != ""].groupby("place"):
        total = int(sub["pop"].sum())
        if total < 1000:
            continue
        ok = (sub.dbu_9m >= THRESH).astype(float)
        ok_car = (sub.dbu_1p5m >= THRESH).astype(float)
        by_place.append(dict(
            place=name, population=total,
            inside_fcc=round(float((sub["pop"] * sub.in_fcc).sum())),
            modelled_9m=round(float((sub["pop"] * ok).sum())),
            modelled_1p5m=round(float((sub["pop"] * ok_car).sum())),
            shadowed_9m=round(float((sub["pop"] * sub.in_fcc * (1 - ok)).sum())),
            median_dbu_9m=round(float(np.average(
                sub.dbu_9m.fillna(0), weights=np.maximum(sub["pop"], 1e-9))), 1)))
    by_place.sort(key=lambda r: -r["population"])
    out["by_place"] = by_place
    return out, blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", action="store_true", help="run the ITM again")
    args = ap.parse_args()
    from pyproj import Transformer

    summary_path = WORK / "summary.json"
    if not summary_path.exists():
        sys.exit("run tools/build_kxci.py first")
    summary = json.loads(summary_path.read_text())
    lic = summary["licence"]
    tx_x, tx_y = Transformer.from_crs(4269, 26912, always_xy=True).transform(lic["lon"], lic["lat"])

    print("elevation")
    z, meta = fetch_dem(tx_x, tx_y)
    ground = float(sample_dem(z, meta, [tx_x], [tx_y])[0])
    h_tx = lic["rcamsl_m"] - ground
    print(f"  ground at the tower {ground:.0f} m, antenna centre {h_tx:.0f} m above it")

    npz = WORK / "field.npz"
    if npz.exists() and not args.rerun:
        f = np.load(npz)
        field, warn, rx_d = f["field"], f["warn"], f["d"]
        print("model: cached")
    else:
        print("model")
        field, warn, rx_d = run_model(z, meta, tx_x, tx_y, h_tx, lic["erp_kw"])

    print("blocks")
    terrain, blocks = tally_blocks(field, rx_d, tx_x, tx_y)
    terrain.update(
        model="ITM (Longley-Rice) point-to-point, itmlogic", threshold_dbu=THRESH,
        radials=N_AZ, profile_step_m=STEP, receiver_step_m=STEP * RX_EVERY,
        radius_km=R_MAX / 1000, rx_heights_m=list(RX_HEIGHTS),
        tower_ground_m=round(ground), antenna_agl_m=round(h_tx),
        ground=dict(eps=EPS, sigma=SGM), climate=KLIM, ens0=ENS0,
        warn_share=round(float((warn >= 3).mean()), 4),
        failed_share=round(float(np.isnan(field[0]).mean()), 4))
    summary["terrain"] = terrain
    summary_path.write_text(json.dumps(summary, indent=1))

    fcc = summary["inside_fcc"]["population"]
    for name, label in (("dbu_9m", "9.1 m rooftop"), ("dbu_1p5m", "1.5 m car")):
        t = terrain[name]
        print(f"\n{label}: {t['served']['population']:,} residents at {THRESH:.0f} dBu or more")
        print(f"  inside the FCC contour and served   {t['inside_fcc_served']:>9,}")
        print(f"  inside the FCC contour, shadowed    {t['inside_fcc_shadowed']:>9,} "
              f"({t['inside_fcc_shadowed'] / fcc * 100:.1f}% of {fcc:,})")
        print(f"  outside the FCC contour but served  {t['outside_fcc_served']:>9,}")
    print(f"\nmodel warnings (kwx 3+): {terrain['warn_share'] * 100:.1f}% of points; "
          f"failed: {terrain['failed_share'] * 100:.2f}%")
    for p in terrain["by_place"][:20]:
        print(f"  {p['place']:26s} pop {p['population']:>8,}  fcc {p['inside_fcc']:>8,}  "
              f"itm9 {p['modelled_9m']:>8,}  itm1.5 {p['modelled_1p5m']:>8,}  "
              f"mean {p['median_dbu_9m']:5.1f} dBu")


if __name__ == "__main__":
    main()
