"""Step 3b: draw the accuracy sample and cut an image chip for every point.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/07_accuracy_points.py [--per-class 25] [site_id ...]

Sample design: stratified random, the strata being the mapped classes inside
each neighborhood boundary, with the same number of points in every class
(fewer where a class has fewer cells than that). Equal allocation gives the
rare classes enough points to judge; step 08 weights each class by its mapped
area so the overall figure is not skewed by it.

Outputs
  work/<site>/<site>.gdb/accuracy_points   point layer with Esri's field
                                           names (Classified, GrndTruth), so
                                           Compute Confusion Matrix reads it
  work/accuracy/chips/<id>_{rgb,cir,wide}.jpg
  work/accuracy/points.json   what the labelling page loads: ids only, in
                              shuffled order, with no hint of the mapped class
  work/accuracy/key.json      id to site, cell and mapped class. The page
                              never loads this
  work/accuracy/strata.json   cells in each mapped class when the sample was
                              drawn, which step 08 uses as weights

The person labelling sees only the 2023 photo. They do not see the map, the
lidar, or which class a point was drawn from.

Re-running draws the same points (fixed seed) unless the map has changed.
"""
import argparse
import json

import arcpy
import numpy as np
from PIL import Image

from common import EPSG, WORK, site_dir, sites, work_bbox

CELL = 0.5
SEED = 20261113
NAIP_CELL = 0.3
CLOSE_M, WIDE_M = 30, 150      # ground width of the two views
CHIP_PX = 420


def chip(img, x, y, x0, y1, width_m):
    """Square crop of the mosaic centred on a map coordinate."""
    half = width_m / 2 / NAIP_CELL
    cx, cy = (x - x0) / NAIP_CELL, (y1 - y) / NAIP_CELL
    box = (round(cx - half), round(cy - half), round(cx + half), round(cy + half))
    resample = Image.NEAREST if width_m <= CLOSE_M else Image.LANCZOS
    return img.crop(box).resize((CHIP_PX, CHIP_PX), resample)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=25)
    ap.add_argument("site", nargs="*")
    args = ap.parse_args()
    arcpy.CheckOutExtension("Spatial")
    arcpy.env.overwriteOutput = True
    rng = np.random.default_rng(SEED)
    out = WORK / "accuracy"
    (out / "chips").mkdir(parents=True, exist_ok=True)
    sr = arcpy.SpatialReference(EPSG)
    key, strata = [], {}
    for s in sites(args.site):
        d = site_dir(s)
        gdb = str(d / f"{s['id']}.gdb")
        x0, y0, x1, y1 = work_bbox(s)
        ll = arcpy.Point(x0, y0)
        rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
        lc = arcpy.RasterToNumPyArray(f"{gdb}/land_cover", ll, cols, rows,
                                      nodata_to_value=0)
        inside = arcpy.RasterToNumPyArray(str(d / "tmp" / "inside.tif"), ll,
                                          cols, rows, nodata_to_value=0) > 0
        naip = arcpy.RasterToNumPyArray(f"{gdb}/naip_2023", nodata_to_value=0)
        nr = arcpy.Raster(f"{gdb}/naip_2023")
        nx0, ny1 = nr.extent.XMin, nr.extent.YMax
        rgb = Image.fromarray(np.moveaxis(naip[:3], 0, -1))
        cir = Image.fromarray(np.moveaxis(naip[[3, 0, 1]], 0, -1))

        pts = f"{gdb}/accuracy_points"
        if arcpy.Exists(pts):
            arcpy.management.Delete(pts)
        arcpy.management.CreateFeatureclass(gdb, "accuracy_points", "POINT",
                                            spatial_reference=sr)
        arcpy.management.AddField(pts, "PointID", "TEXT", field_length=12)
        arcpy.management.AddField(pts, "Classified", "LONG")
        arcpy.management.AddField(pts, "GrndTruth", "LONG")
        counts = {}
        with arcpy.da.InsertCursor(pts, ["SHAPE@XY", "PointID", "Classified",
                                         "GrndTruth"]) as cur:
            for code in sorted(int(c) for c in np.unique(lc[inside]) if c > 0):
                rr, cc = np.nonzero(inside & (lc == code))
                n = min(args.per_class, rr.size)
                counts[code] = dict(points=n, cells=int(rr.size))
                for i in rng.choice(rr.size, n, replace=False):
                    x = x0 + (cc[i] + 0.5) * CELL
                    y = y1 - (rr[i] + 0.5) * CELL
                    pid = f"{rng.integers(0, 16**8):08x}"
                    cur.insertRow(((x, y), pid, code, -1))
                    key.append(dict(id=pid, site=s["id"], x=x, y=y,
                                    classified=code))
                    chip(rgb, x, y, nx0, ny1, CLOSE_M).save(
                        out / "chips" / f"{pid}_rgb.jpg", quality=92)
                    chip(cir, x, y, nx0, ny1, CLOSE_M).save(
                        out / "chips" / f"{pid}_cir.jpg", quality=92)
                    chip(rgb, x, y, nx0, ny1, WIDE_M).save(
                        out / "chips" / f"{pid}_wide.jpg", quality=88)
        strata[s["id"]] = {str(k): v["cells"] for k, v in counts.items()}
        print(s["id"], counts, flush=True)

    order = rng.permutation(len(key))
    (out / "key.json").write_text(json.dumps(key, indent=1))
    # Cells in each class when the sample was drawn: the weights for step 08
    (out / "strata.json").write_text(json.dumps(strata, indent=1))
    (out / "points.json").write_text(json.dumps(dict(
        close_m=CLOSE_M, wide_m=WIDE_M, cell_m=CELL,
        imagery="NAIP, 18 October 2023",
        ids=[key[i]["id"] for i in order])))
    print(len(key), "points;", "ids unique:", len({k["id"] for k in key}) == len(key))


if __name__ == "__main__":
    main()
