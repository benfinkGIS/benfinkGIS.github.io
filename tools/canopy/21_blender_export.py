"""Step 10e (part 1): cut a block of each neighborhood for the 3D render.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/21_blender_export.py [--size 400] [site_id ...]

Blender cannot read a geodatabase, so this writes plain arrays for a square
block of each site (centre in BLOCKS below) to work/<site>/blender/:

  ground.npy    bare-ground elevation, metres, row 0 = north
  roof.npy      roof height above ground (0 where there is no building)
  canopy.npy    height above ground of today's tree canopy (0 elsewhere)
  texture.png   the 2023 aerial photo over the block
  scene.json    cell size, block size, sun position, the species palette and
                every proposed tree in the block (position in metres from the
                block's south-west corner, ground height, species, mature
                crown radius and height, scenario)

Roof heights are median-filtered: raw lidar roofs are speckled at half a
metre and render as rubble.
"""
import argparse
import json

import arcpy
import numpy as np
from PIL import Image
from scipy import ndimage

from common import PROJECT, site_dir, sites, work_bbox

CELL = 0.5
# block centres, UTM 12N: a stretch of ordinary streets in each neighborhood
BLOCKS = {"dunbar_spring": (502330, 3566150), "western_hills_ii": (505655, 3560845)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=float, default=400, help="block side, metres")
    ap.add_argument("site", nargs="*")
    args = ap.parse_args()
    species = json.loads((PROJECT / "species.json").read_text(encoding="utf-8"))
    names = [s["common"] for s in species["species"]]
    for s in sites(args.site):
        d = site_dir(s)
        gdb = str(d / f"{s['id']}.gdb")
        out = d / "blender"
        out.mkdir(exist_ok=True)
        cx, cy = BLOCKS[s["id"]]
        half = args.size / 2
        wx0, wy0, wx1, wy1 = work_bbox(s)
        # keep the block inside the work area and on the raster grid
        x0 = min(max(round((cx - half - wx0) / CELL) * CELL + wx0, wx0), wx1 - args.size)
        y0 = min(max(round((cy - half - wy0) / CELL) * CELL + wy0, wy0), wy1 - args.size)
        n = int(args.size / CELL)
        ll = arcpy.Point(x0, y0)
        grab = lambda name: arcpy.RasterToNumPyArray(f"{gdb}/{name}", ll, n, n,
                                                     nodata_to_value=0).astype(np.float32)
        dtm, chm, veg, lc = grab("dtm"), grab("chm"), grab("veg_height"), grab("land_cover")
        roof = np.where(lc == 2, chm, 0)
        roof = np.where(lc == 2, ndimage.median_filter(roof, size=5), 0)
        canopy = np.where(lc == 1, veg, 0)
        np.save(out / "ground.npy", dtm)
        np.save(out / "roof.npy", roof.astype(np.float32))
        np.save(out / "canopy.npy", canopy.astype(np.float32))

        photo = arcpy.RasterToNumPyArray(f"{gdb}/naip_2023", ll, round(args.size / 0.3),
                                         round(args.size / 0.3), nodata_to_value=0)
        Image.fromarray(np.moveaxis(photo[:3], 0, -1)).save(out / "texture.png")

        trees = []
        for (x, y), sp, scen, crown, height in arcpy.da.SearchCursor(
                f"{gdb}/trees", ["SHAPE@XY", "Species", "Scenario", "Crown_m", "Height_m"]):
            if x0 + 2 <= x <= x0 + args.size - 2 and y0 + 2 <= y <= y0 + args.size - 2:
                r, c = int((y0 + args.size - y) / CELL), int((x - x0) / CELL)
                trees.append([round(x - x0, 2), round(y - y0, 2), round(float(dtm[r, c]), 2),
                              names.index(sp), round(crown / 2, 2), round(height, 2), int(scen)])
        shade = json.loads((d / "shade.json").read_text())
        (out / "scene.json").write_text(json.dumps(dict(
            site=s["id"], name=s["name"], cell_m=CELL, size_m=args.size, origin=[x0, y0],
            ground_min=float(dtm.min()), sun_azimuth=shade["sun_azimuth"],
            sun_elevation=shade["sun_elevation"], crown_base_m=species["crown_base_m"],
            species=[dict(name=sp["common"], colour=sp["colour"]) for sp in species["species"]],
            trees=trees)))
        print(s["id"], f"block {args.size:.0f} m at {x0:.0f}, {y0:.0f};",
              f"canopy {float((canopy > 0).mean()) * 100:.1f}%, roofs {float((roof > 0).mean()) * 100:.1f}%;",
              {k: sum(1 for t in trees if t[6] <= k) for k in (1, 2, 3)}, "trees by scenario", flush=True)


if __name__ == "__main__":
    main()
