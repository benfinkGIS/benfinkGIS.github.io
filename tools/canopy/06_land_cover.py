"""Step 3: land cover for each site.

Runs in ArcGIS Pro's Python (Spatial Analyst):

  <Pro python> tools/canopy/06_land_cover.py [site_id ...]

Classes
  1 Tree canopy       2 Roof          3 Pavement
  4 Low vegetation    5 Bare ground   6 Water

How it decides
  Lidar settles what stands up. Tree canopy is the first-pass canopy from
  step 2 (tall, and green or porous, thin strips removed) plus its fringe:
  green vegetation at least 1 m tall within 1 m of a crown. Roofs are the
  lidar's building class where no tree overhangs, with one-cell scan gaps
  closed.

  Everything else is ground, and a Random Trees classifier sorts it into
  pavement, low vegetation and bare ground from seven inputs: the four NAIP
  bands, NDVI, lidar ground intensity and vegetation height.

  The classifier is trained on samples the script draws itself, from places
  where the answer is not in doubt:
    pavement        flat ground within 2.5 m of a street centerline that is
                    dark to the lidar (asphalt), plus flat, bright, grey
                    ground (concrete)
    low vegetation  green, bright in the near infrared, and under 2.5 m
    bare ground     flat, not green, bright to the lidar, inside a parcel and
                    well away from the street, and not grey
  "Dark" and "bright" are split at the natural break in the site's own ground
  intensity (Otsu's method), so nothing is tuned by hand per site.

  Shadows are the trap: shaded pavement has a plant-like NDVI in the photo.
  Ground that is darker in the near infrared than nearly all of the site's
  tree canopy is therefore never sampled as vegetation, and shaded streets and
  yards are sampled as pavement and bare ground, told apart by the lidar
  intensity, which has no shadows. After classifying, any "low vegetation"
  that is neither sunlit foliage nor shrub-shaped is treated as shade and
  decided by intensity alone.

  Solid objects 0.5 to 2.5 m tall that are not foliage (cars, sheds, walls)
  take the class of the nearest open ground, since they hide what is under
  them.

  Water is a rule: flat, open, and much brighter in green than near infrared.

No training polygon is digitised by hand, so a new site needs no new labels.
The map is checked afterwards against points labelled by a person who has not
seen it (steps 07 and 08).

Writes to work/<site>/<site>.gdb: land_cover (with class names and colours)
and land_cover_seeds (the training points). Beside it: land_cover.json,
ql_land_cover.png and the classifier definition.
"""
import json
import sys

import arcpy
import numpy as np
from scipy import ndimage
from arcpy.sa import (ClassifyRaster, EucDistance, MajorityFilter, Raster,
                      TrainRandomTreesClassifier)

from common import EPSG, site_dir, sites, work_bbox

CELL = 0.5
CLASSES = {1: ("Tree canopy", (38, 115, 0)), 2: ("Roof", (168, 56, 0)),
           3: ("Pavement", (104, 104, 104)), 4: ("Low vegetation", (163, 255, 115)),
           5: ("Bare ground", (245, 202, 122)), 6: ("Water", (0, 112, 255))}
FLAT_M = 0.3            # ground-level: nothing taller than this in the cell
TREE_MIN_M = 2.5
LIT_SHARE = 0.75        # of the median tree crown's near-infrared brightness
POROUS = 0.15           # share of multi-return pulses that marks foliage
FRINGE_MIN_M = 1.0      # crown edges count as canopy down to this height...
FRINGE_CELLS = 2        # ...within this many cells of a crown
STREET_CORE_M = 2.5     # this close to a centerline is carriageway
STREET_CLEAR_M = 8.0    # bare-ground samples stay this far from a centerline
SAMPLES = 3000          # training points per class
SEED = 20261113


def otsu(values):
    """Threshold that best splits a two-humped set of numbers."""
    lo, hi = np.percentile(values, [1, 99])
    hist, edges = np.histogram(np.clip(values, lo, hi), 256)
    mids = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids) / np.maximum(w0, 1)
    m1 = (np.sum(hist * mids) - np.cumsum(hist * mids)) / np.maximum(w1, 1)
    return float(mids[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def classify(site):
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    tmp = d / "tmp"
    tmp.mkdir(exist_ok=True)
    sr = arcpy.SpatialReference(EPSG)
    x0, y0, x1, y1 = work_bbox(site)
    ll = arcpy.Point(x0, y0)
    rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
    arcpy.env.workspace = gdb
    arcpy.env.overwriteOutput = True
    arcpy.env.outputCoordinateSystem = sr
    arcpy.env.extent = arcpy.Extent(x0, y0, x1, y1)
    arcpy.env.cellSize = CELL
    arcpy.env.snapRaster = f"{gdb}/chm"

    def grab(path, nodata=0):
        return arcpy.RasterToNumPyArray(path, ll, cols, rows, nodata_to_value=nodata)

    def put(arr, path):
        r = arcpy.NumPyArrayToRaster(arr, ll, CELL, CELL)
        arcpy.management.CopyRaster(r, path)
        arcpy.management.DefineProjection(path, sr)

    # Imagery on the lidar grid
    naip05 = str(tmp / "naip05.tif")
    arcpy.management.Resample(f"{gdb}/naip_2023", naip05, CELL, "BILINEAR")
    R, G, B, N = [a.astype(np.float32) for a in grab(naip05)]
    ndvi = grab(f"{gdb}/ndvi", -1)
    chm = grab(f"{gdb}/chm")
    veg = grab(f"{gdb}/veg_height")
    inten = grab(f"{gdb}/intensity")

    # One stack of everything the classifier sees. It must be integer: on a
    # floating-point stack Classify Raster returns a single class everywhere.
    # NDVI is stored as (ndvi + 1) x 10000 and height in centimetres
    feats = str(tmp / "features.tif")
    # Height counts only where the cell is green and porous to the lidar, so
    # a parked car or a wall (solid) is judged by its colour, not as a shrub
    multi = grab(f"{gdb}/multi_return")
    shrubby = (ndvi >= 0.10) & (multi >= POROUS)
    green_h = np.where(shrubby, veg, 0)
    stack = np.stack([R, G, B, N, (ndvi + 1) * 10000, np.clip(inten, 0, 65535),
                      np.clip(green_h * 100, 0, 65535)]).astype(np.uint16)
    arcpy.management.CopyRaster(arcpy.NumPyArrayToRaster(stack, ll, CELL, CELL),
                                feats, pixel_type="16_BIT_UNSIGNED")
    arcpy.management.DefineProjection(feats, sr)
    # Close one-cell gaps the scan pattern leaves inside roofs
    roof = ndimage.binary_closing(grab(f"{gdb}/roof_lidar") == 1,
                                  structure=np.ones((3, 3), bool))
    # Crown fringe: step 2 trims thin crown edges along with the power lines.
    # Give back green vegetation at least 1 m tall within 1 m of a crown
    core = grab(f"{gdb}/canopy_first") == 1
    fringe = (veg >= FRINGE_MIN_M) & (ndvi >= 0.15)
    tree = core | (fringe & ndimage.binary_dilation(
        core, structure=np.ones((3, 3), bool), iterations=FRINGE_CELLS))
    street_m = grab(EucDistance(f"{gdb}/streets", cell_size=CELL), 1e6)
    arcpy.conversion.PolygonToRaster(f"{gdb}/parcels", "OBJECTID",
                                     str(tmp / "parcel.tif"), cellsize=CELL)
    parcel = grab(str(tmp / "parcel.tif"), 0) > 0

    bright = (R + G + B) / 3
    red = (R - B) / np.maximum(R + B, 1)          # soil is tan, concrete grey
    ndwi = (G - N) / np.maximum(G + N, 1)
    open_flat = (chm < FLAT_M) & ~roof & ~tree
    # Shadows and dark paint have a high NDVI without being plants. Real
    # foliage in sunlight is bright in the near infrared, so ground darker
    # there than three-quarters of the site's typical tree crown is treated
    # as not green. (The first version of this map used the darkest 5% of
    # canopy as the cut-off; the accuracy check showed that let shadows on
    # pale soil through as low vegetation.)
    lit = N >= LIT_SHARE * np.median(N[core])
    dry = open_flat & ((ndvi < 0.08) | ~lit)
    split = otsu(inten[dry])
    grey = (red < 0.06) & (bright > 150)

    seeds = {
        3: (dry & (street_m <= STREET_CORE_M) & (inten < split)) |
           (dry & (ndvi < 0.05) & grey & (inten >= split)),
        4: ~roof & ~tree & (veg < TREE_MIN_M) & lit &
           ((ndvi >= 0.20) | ((veg >= 0.5) & shrubby)),
        5: dry & parcel & (street_m >= STREET_CLEAR_M) & (inten >= split) & ~grey,
    }
    rng = np.random.default_rng(SEED)
    pts = f"{gdb}/land_cover_seeds"
    if arcpy.Exists(pts):
        arcpy.management.Delete(pts)
    arcpy.management.CreateFeatureclass(gdb, "land_cover_seeds", "POINT",
                                        spatial_reference=sr)
    arcpy.management.AddField(pts, "Classname", "TEXT", field_length=30)
    arcpy.management.AddField(pts, "Classvalue", "LONG")
    counts = {}
    with arcpy.da.InsertCursor(pts, ["SHAPE@XY", "Classname", "Classvalue"]) as cur:
        for code, mask in seeds.items():
            rr, cc = np.nonzero(mask)
            counts[CLASSES[code][0]] = int(rr.size)
            if rr.size == 0:
                raise SystemExit(f"{site['id']}: no training cells for {CLASSES[code][0]}")
            pick = rng.choice(rr.size, min(SAMPLES, rr.size), replace=False)
            for r, c in zip(rr[pick], cc[pick]):
                cur.insertRow(((x0 + (c + 0.5) * CELL, y1 - (r + 0.5) * CELL),
                               CLASSES[code][0], code))

    ecd = str(d / f"{site['id']}_ground.ecd")
    TrainRandomTreesClassifier(feats, pts, ecd, max_num_trees=100,
                               max_tree_depth=30, max_samples_per_class=SAMPLES)
    # The output holds each class's position in the classifier, not its code;
    # the codes are in its attribute table
    raw = str(tmp / "ground_classes.tif")
    ClassifyRaster(feats, ecd).save(raw)
    code_of = {int(v): int(c) for v, c in
               arcpy.da.SearchCursor(raw, ["Value", "Classvalue"])}
    smooth = grab(MajorityFilter(raw, "EIGHT", "HALF"), 255)
    g = np.full(smooth.shape, 5, np.uint8)
    for value, code in code_of.items():
        g[smooth == value] = code

    # Cars, sheds and walls: solid things 0.5 to 2.5 m tall hide the ground,
    # and their paint misleads the classifier. Give each the class of the
    # nearest ground cell that is not under one
    solid = (veg >= 0.5) & (veg < TREE_MIN_M) & ~shrubby & ~roof & ~tree
    near = ndimage.distance_transform_edt(solid, return_distances=False,
                                          return_indices=True)
    g = np.where(solid, g[near[0], near[1]], g)

    # Low vegetation has to be sunlit foliage or have a shrub's structure.
    # Anything else the classifier called vegetation is shade: decide it by
    # the lidar intensity, which shade does not affect
    shade = (g == 4) & ~lit & ~(shrubby & (veg >= 0.3))
    g = np.where(shade, np.where(inten < split, 3, 5), g).astype(np.uint8)

    water = open_flat & (ndwi > 0.25) & (B > R) & (ndvi < 0)
    lc = g.astype(np.uint8)
    lc[water] = 6
    lc[roof] = 2
    lc[tree] = 1
    out = f"{gdb}/land_cover"
    put(lc, out)
    arcpy.management.BuildRasterAttributeTable(out, "Overwrite")
    arcpy.management.AddField(out, "Class_name", "TEXT", field_length=30)
    with arcpy.da.UpdateCursor(out, ["Value", "Class_name"]) as cur:
        for v, _ in cur:
            cur.updateRow((v, CLASSES[int(v)][0]))
    clr = tmp / "land_cover.clr"
    clr.write_text("\n".join(f"{k} {c[0]} {c[1]} {c[2]}"
                             for k, (_, c) in CLASSES.items()))
    arcpy.management.AddColormap(out, input_CLR_file=str(clr))

    arcpy.conversion.PolygonToRaster(f"{gdb}/boundary", "OBJECTID",
                                     str(tmp / "inside.tif"), cellsize=CELL)
    inside = grab(str(tmp / "inside.tif"), 0) > 0
    share = {name: round(float((lc[inside] == k).mean() * 100), 1)
             for k, (name, _) in CLASSES.items()}
    summary = dict(site=site["id"], share_pct=share,
                   canopy_core_pct=round(float(core[inside].mean() * 100), 1),
                   impervious_pct=round(share["Roof"] + share["Pavement"], 1),
                   intensity_split=round(split, 1), training_cells=counts,
                   samples_per_class=SAMPLES)
    (d / "land_cover.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1), flush=True)

    from PIL import Image
    pal = np.zeros((7, 3), np.uint8)
    for k, (_, c) in CLASSES.items():
        pal[k] = c
    Image.fromarray(pal[lc]).save(str(d / "ql_land_cover.png"))


def main():
    if arcpy.CheckOutExtension("Spatial") != "CheckedOut":
        raise SystemExit("Spatial Analyst licence not available")
    for s in sites(sys.argv[1:]):
        classify(s)


if __name__ == "__main__":
    main()
