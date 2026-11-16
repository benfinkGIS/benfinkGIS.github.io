"""Build the whole-lake terrain: the lake DEM set into the surrounding country.

1. Averages the 1 m lake DEM to 30 m cells (read from its 2 m overview, so
   each 30 m cell is the mean of up to 225 values) and records how much of
   each cell the lake DEM covers.
2. Mosaics the 3DEP 10 m tiles for the frame and averages them to 30 m.
3. Uses the lake DEM wherever it has data and 3DEP everywhere else, weighted
   by coverage in cells the lake DEM only partly fills.
4. Burns Glen Canyon Dam back in (a 30 m average flattens a wall 8 m thick)
   and marks which cells belong to the reservoir: ground at or below the
   record high water level that connects to the lake above the dam.

Writes to processed/: terrain_30m.tif, terrain_30m.npy, lake_cover_30m.npy,
reservoir_30m.npy, context_10m.tif and terrain.json (frame, ranges, checks).

    py -I tools/powell/07_build_terrain.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util
import json
import time

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds
from scipy import ndimage

from common import (CELL, CONTEXT_CELL, DEM_COLS, DEM_ROWS, EAC_FILE, EPSG_DEM, FRAME_COLS, FRAME_ROWS, FRAME_X0,
                    FRAME_X1, FRAME_Y0, FRAME_Y1, FULL_POOL_FT, PAD_CELLS, PROCESSED, RAW, RAW_DEM,
                    reclamation_ft_to_dem_m)

# Glen Canyon Dam's crest, west abutment to east, read off the 1 m DEM (EPSG:6341)
DAM_CREST = [(456690, 4087880), (456730, 4087960), (456790, 4088035), (456860, 4088080), (456950, 4088097),
             (457040, 4088088), (457120, 4088065)]
LAKE_SEED = (456900, 4088400)            # open water just above the dam


def lake_dem_path():
    return next((RAW_DEM / "extracted").rglob("*_1m.tif"))


def lake_to_30m():
    """Mean and coverage of the lake DEM in 30 m cells, on the DEM's own grid."""
    cache = PROCESSED / "lake_dem_30m.npz"              # delete this file to redo the averaging
    if cache.exists():
        saved = np.load(cache)
        return saved["mean"], saved["cover"]
    mean = np.full((DEM_ROWS, DEM_COLS), np.nan, dtype="float32")
    cover = np.zeros((DEM_ROWS, DEM_COLS), dtype="float32")
    k = 15                                              # 2 m cells per 30 m cell
    t0 = time.time()
    with rasterio.open(lake_dem_path(), OVERVIEW_LEVEL="0only") as ds:
        assert abs(ds.transform.a - 2.0) < 1e-6, ds.transform
        strip = 20                                      # 30 m rows per read
        for r0 in range(0, DEM_ROWS, strip):
            n = min(strip, DEM_ROWS - r0)
            rows = min(n * k, ds.height - r0 * k)
            if rows <= 0:
                break
            a = ds.read(1, window=Window(0, r0 * k, ds.width, rows), masked=True).filled(np.nan)
            block = np.full((n * k, DEM_COLS * k), np.nan, dtype="float32")
            block[:rows, :ds.width] = a
            block = block.reshape(n, k, DEM_COLS, k)
            ok = np.isfinite(block)
            count = ok.sum(axis=(1, 3))
            total = np.where(ok, block, 0).sum(axis=(1, 3), dtype="float64")
            with np.errstate(invalid="ignore", divide="ignore"):
                mean[r0:r0 + n] = np.where(count > 0, total / count, np.nan)
            cover[r0:r0 + n] = count / (k * k)
            if r0 % 400 == 0:
                print(f"  lake DEM rows {r0 + n} of {DEM_ROWS} ({time.time() - t0:.0f} s)", flush=True)
    np.savez_compressed(cache, mean=mean, cover=cover)
    return mean, cover


def context_mosaic():
    """The 3DEP tiles as one 10 m array for the frame."""
    spec = importlib.util.spec_from_file_location("get_context", Path(__file__).with_name("06_get_context.py"))
    get_context = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(get_context)
    ratio = round(CELL / CONTEXT_CELL)
    out = np.full((FRAME_ROWS * ratio, FRAME_COLS * ratio), np.nan, dtype="float32")
    for r, c, bbox, w, h in get_context.tiles():
        with rasterio.open(get_context.tile_path(r, c)) as ds:
            a = ds.read(1, masked=True).filled(np.nan)
        assert a.shape == (h, w), (a.shape, h, w)
        a[a < -1000] = np.nan
        top = round((FRAME_Y1 - bbox[3]) / CONTEXT_CELL)
        left = round((bbox[0] - FRAME_X0) / CONTEXT_CELL)
        out[top:top + h, left:left + w] = a
    return out


def burn_dam(terrain):
    """Give the dam's cells the highest 1 m value inside them, and return the barrier mask."""
    barrier = np.zeros(terrain.shape, dtype=bool)
    pts = []
    for (xa, ya), (xb, yb) in zip(DAM_CREST[:-1], DAM_CREST[1:]):
        n = int(np.hypot(xb - xa, yb - ya) // 5) + 1
        pts += [(xa + (xb - xa) * i / n, ya + (yb - ya) * i / n) for i in range(n + 1)]
    for x, y in pts:
        barrier[int((FRAME_Y1 - y) // CELL), int((x - FRAME_X0) // CELL)] = True
    barrier = ndimage.binary_dilation(barrier, structure=np.ones((3, 3), bool))
    with rasterio.open(lake_dem_path()) as ds:
        for r, c in zip(*np.nonzero(barrier)):
            x0, y1 = FRAME_X0 + c * CELL, FRAME_Y1 - r * CELL
            a = ds.read(1, window=from_bounds(x0, y1 - CELL, x0 + CELL, y1, ds.transform), masked=True)
            if a.count():
                terrain[r, c] = max(terrain[r, c], float(a.max()))
    return barrier


def main():
    print("averaging the lake DEM to 30 m")
    lake, cover_dem = lake_to_30m()
    lake_full = np.full((FRAME_ROWS, FRAME_COLS), np.nan, dtype="float32")
    cover = np.zeros((FRAME_ROWS, FRAME_COLS), dtype="float32")
    lake_full[PAD_CELLS:PAD_CELLS + DEM_ROWS, PAD_CELLS:PAD_CELLS + DEM_COLS] = lake
    cover[PAD_CELLS:PAD_CELLS + DEM_ROWS, PAD_CELLS:PAD_CELLS + DEM_COLS] = cover_dem

    print("mosaicking 3DEP")
    ctx10 = context_mosaic()
    print(f"  3DEP 10 m: {ctx10.shape}, {np.isnan(ctx10).mean():.4%} empty, "
          f"{np.nanmin(ctx10):.1f} to {np.nanmax(ctx10):.1f} m")
    profile = dict(driver="GTiff", dtype="float32", count=1, crs=f"EPSG:{EPSG_DEM}", nodata=-9999.0,
                   compress="deflate", predictor=3, tiled=True, blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER")
    with rasterio.open(PROCESSED / "context_10m.tif", "w", width=ctx10.shape[1], height=ctx10.shape[0],
                       transform=from_origin(FRAME_X0, FRAME_Y1, CONTEXT_CELL, CONTEXT_CELL), **profile) as dst:
        dst.write(np.where(np.isfinite(ctx10), ctx10, -9999.0).astype("float32"), 1)
    ratio = round(CELL / CONTEXT_CELL)
    with np.errstate(invalid="ignore"):
        ctx = np.nanmean(ctx10.reshape(FRAME_ROWS, ratio, FRAME_COLS, ratio), axis=(1, 3)).astype("float32")
    del ctx10

    # How well the two sources agree on dry ground both of them cover
    full_pool_m = reclamation_ft_to_dem_m(FULL_POOL_FT)
    both = (cover > 0.999) & (lake_full > full_pool_m + 5) & np.isfinite(ctx)
    diff = (lake_full - ctx)[both]
    agreement = {"cells": int(both.sum()), "median_m": round(float(np.median(diff)), 2),
                 "mean_m": round(float(diff.mean()), 2),
                 "p05_p95_m": [round(float(v), 2) for v in np.percentile(diff, [5, 95])]}
    print("  lake DEM minus 3DEP on shared dry ground:", agreement)

    terrain = np.where(cover > 0, cover * np.nan_to_num(lake_full) + (1 - cover) * ctx, ctx).astype("float32")
    terrain = np.where(np.isfinite(terrain), terrain, lake_full)           # 3DEP gaps, if any, inside the lake DEM
    barrier = burn_dam(terrain)

    # Reservoir cells: at or below the record high level (plus a little), joined to the lake above the dam
    high_m = reclamation_ft_to_dem_m(3708.34) + 2.0
    low = (terrain <= high_m) & (cover > 0) & ~barrier
    labels, _ = ndimage.label(low, structure=np.ones((3, 3), bool))
    seed = labels[int((FRAME_Y1 - LAKE_SEED[1]) // CELL), int((LAKE_SEED[0] - FRAME_X0) // CELL)]
    assert seed > 0, "the seed point above the dam is not below the high water level"
    reservoir = labels == seed

    # Check the flooded area at full pool against the USGS table for the same lake bed
    eac = pd.read_csv(RAW / "capacity" / EAC_FILE)
    usgs_km2 = float(np.interp(FULL_POOL_FT, eac["Elevation_ft_NGVD29"], eac["Area_acres"])) * 0.0040468564
    mine_km2 = float((reservoir & (terrain <= full_pool_m)).sum()) * CELL * CELL / 1e6
    print(f"  area flooded at full pool: {mine_km2:.1f} km2 here, {usgs_km2:.1f} km2 in the USGS table "
          f"({(mine_km2 / usgs_km2 - 1) * 100:+.1f}%)")

    with rasterio.open(PROCESSED / "terrain_30m.tif", "w", width=FRAME_COLS, height=FRAME_ROWS,
                       transform=from_origin(FRAME_X0, FRAME_Y1, CELL, CELL), **profile) as dst:
        dst.write(terrain, 1)
    np.save(PROCESSED / "terrain_30m.npy", terrain)
    np.save(PROCESSED / "lake_cover_30m.npy", cover)
    np.save(PROCESSED / "reservoir_30m.npy", reservoir)
    info = {"crs_epsg": EPSG_DEM, "cell_m": CELL, "cols": FRAME_COLS, "rows": FRAME_ROWS,
            "x0": FRAME_X0, "y0": FRAME_Y0, "x1": FRAME_X1, "y1": FRAME_Y1,
            "elevation_min_m": round(float(np.nanmin(terrain)), 2), "elevation_max_m": round(float(np.nanmax(terrain)), 2),
            "empty_cells": int(np.isnan(terrain).sum()),
            "reservoir_cells": int(reservoir.sum()), "reservoir_lowest_m": round(float(terrain[reservoir].min()), 2),
            "full_pool_m_navd88": round(full_pool_m, 3),
            "area_at_full_pool_km2": round(mine_km2, 1), "usgs_area_at_full_pool_km2": round(usgs_km2, 1),
            "lake_dem_minus_3dep_on_dry_ground": agreement,
            "dam_crest": DAM_CREST, "lake_seed": LAKE_SEED}
    (PROCESSED / "terrain.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in info.items() if k not in ("dam_crest",)}, indent=1))


if __name__ == "__main__":
    main()
