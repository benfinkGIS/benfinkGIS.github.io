"""Report what the downloaded Lake Powell DEM actually is, and draw a preview.

Finds every raster under raw/tbdem/extracted/, prints its format, coordinate
system, vertical datum, units, cell size, extent, nodata value and internal
layout, and writes the same facts to processed/dem_report.json. With --preview
it also reads the raster at a coarse cell size (default 60 m) and writes a
shaded-relief picture, processed/dem_preview.png, plus the elevation range.

    py -I tools/powell/04_inspect_dem.py --preview
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from common import PROCESSED, RAW_DEM

RASTER_TYPES = {".tif", ".tiff", ".img", ".vrt", ".adf", ".gdb"}


def find_rasters():
    root = RAW_DEM / "extracted"
    found = [p for p in root.rglob("*") if p.suffix.lower() in RASTER_TYPES and p.name != "hdr.adf"]
    return sorted(set(found))


def describe(path):
    with rasterio.open(path) as ds:
        crs = ds.crs
        info = {
            "file": str(path.relative_to(RAW_DEM)),
            "size_on_disk_gb": round(sum(f.stat().st_size for f in ([path] if path.is_file() else path.rglob("*"))
                                         if f.is_file()) / 1e9, 2),
            "driver": ds.driver,
            "columns": ds.width, "rows": ds.height, "bands": ds.count,
            "cell_size": [abs(ds.transform.a), abs(ds.transform.e)],
            "bounds": [round(v, 3) for v in ds.bounds],
            "crs_name": crs.to_wkt().split('"')[1] if crs else None,
            "crs_epsg": crs.to_epsg() if crs else None,
            "crs_is_compound": bool(crs and crs.to_wkt().startswith(("COMPD_CS", "COMPOUNDCRS"))),
            "horizontal_units": crs.linear_units if crs else None,
            "data_type": ds.dtypes[0], "nodata": ds.nodata,
            "band_units": ds.units[0], "band_description": ds.descriptions[0],
            "block_shape": list(ds.block_shapes[0]),
            "compression": ds.compression.value if ds.compression else None,
            "overview_factors": ds.overviews(1),
            "tags": ds.tags(), "band_tags": ds.tags(1),
            "crs_wkt": crs.to_wkt() if crs else None,
        }
    return info


def preview(path, cell, out_png):
    """Read the raster in strips at a coarse cell size, by averaging, and shade it."""
    t0 = time.time()
    with rasterio.open(path) as ds:
        step = max(1, round(cell / abs(ds.transform.a)))
        h, w = ds.height // step, ds.width // step
        dem = np.full((h, w), np.nan, dtype="float32")
        strip = max(1, 4096 // step)                    # output rows per read
        for r0 in range(0, h, strip):
            n = min(strip, h - r0)
            a = ds.read(1, window=Window(0, r0 * step, w * step, n * step), out_shape=(n, w),
                        resampling=Resampling.average, masked=True)
            dem[r0:r0 + n] = a.filled(np.nan)
            print(f"  preview rows {r0 + n} of {h} ({time.time() - t0:.0f} s)", flush=True)
        x0, y1 = ds.bounds.left, ds.bounds.top
    np.save(PROCESSED / "dem_preview.npy", dem)
    valid = np.isfinite(dem)
    stats = {"preview_cell_m": step * 1.0, "preview_shape": [h, w],
             "valid_share": round(float(valid.mean()), 4),
             "elevation_min": round(float(np.nanmin(dem)), 2), "elevation_max": round(float(np.nanmax(dem)), 2),
             "elevation_percentiles_1_50_99": [round(float(v), 1) for v in np.nanpercentile(dem, [1, 50, 99])]}

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    filled = np.where(valid, dem, np.nanmin(dem))
    lo, hi = np.nanpercentile(dem, [0.5, 99.5])
    rgb = LightSource(azdeg=315, altdeg=40).shade(filled, cmap=plt.get_cmap("gist_earth"), vmin=lo - 150, vmax=hi + 80,
                                                   vert_exag=3, dx=step, dy=step, blend_mode="soft")
    rgb[~valid] = (0.99, 0.99, 0.98, 1)
    fig = plt.figure(figsize=(w / 200, h / 200), dpi=200)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.imshow(rgb, extent=(x0, x0 + w * step, y1 - h * step, y1))
    ax.set_axis_off()
    fig.savefig(out_png)
    print(out_png)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="also read the raster coarsely and draw it")
    ap.add_argument("--cell", type=float, default=60.0, help="preview cell size in metres")
    args = ap.parse_args()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    rasters = find_rasters()
    if not rasters:
        raise SystemExit("no raster found under raw/tbdem/extracted/ (run 03_get_dem.py first)")
    report = []
    for path in rasters:
        info = describe(path)
        for k, v in info.items():
            if k != "crs_wkt":
                print(f"  {k}: {v}")
        print("  crs_wkt:", info["crs_wkt"])
        report.append(info)
    if args.preview:
        main_raster = max(rasters, key=lambda p: report[rasters.index(p)]["columns"])
        report[rasters.index(main_raster)]["preview"] = preview(main_raster, args.cell, PROCESSED / "dem_preview.png")
        print(" ", report[rasters.index(main_raster)]["preview"])
    (PROCESSED / "dem_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
