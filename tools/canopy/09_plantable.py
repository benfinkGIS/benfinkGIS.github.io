"""Step 5: where a tree could go, and where runoff collects.

Runs in ArcGIS Pro's Python (Spatial Analyst):

  <Pro python> tools/canopy/09_plantable.py [site_id ...]

Plantable ground is open ground in the land cover (low vegetation or bare)
where a trunk would be clear of everything below. The distances are planning
assumptions, set at the top of this file; they are not from a code or a
utility standard.

  buildings          3 m from any roof
  pavement           1 m from mapped pavement
  existing canopy    2 m from an existing crown
  overhead lines     3 m from wires and poles, found in the lidar as things
                     4 m or taller that are neither tree nor roof
  street corners     10 m from a street intersection (right-of-way only)
  parks and schools  only the outer 10 m, so fields stay open

Each plantable cell gets a zone, which is what the scenarios are built from:
  1 street     the public right-of-way: ground outside every parcel and
               within 5 m of street pavement
  2 yard       residential parcels (assessor use codes 01 to 08)
  3 park edge  the rim of parks and school grounds
Other parcels (commercial, industrial, rail, government) are left out.

Runoff: water is routed downhill over the lidar ground surface with roofs
raised so they shed outward. Each cell gets the area of roof and pavement
that drains through it. `runoff_m2` is the largest such area within 2 m: what
a basin or a curb cut at that spot could tap, which is how Dunbar Spring
waters its street trees.

Writes to <site>.gdb: plantable (zone raster), runoff_m2, overhead,
street_corners. Beside it: plantable.json and ql_plantable.png.
"""
import json
import sys

import arcpy
import numpy as np
from arcpy.sa import Con, Fill, FlowAccumulation, FlowDirection, Raster
from scipy import ndimage

from common import EPSG, site_dir, sites, work_bbox

CELL = 0.5
BUILDING_M = 3.0
PAVEMENT_M = 1.0
CANOPY_M = 2.0
OVERHEAD_M = 3.0
OVERHEAD_MIN_M = 4.0
CORNER_M = 10.0
STREET_STRIP_M = 5.0                # street trees stay this close to the pavement
PARK_EDGE_M = 10.0
TAP_M = 2.0                         # reach of a basin or curb cut
RESIDENTIAL = tuple(f"{i:02d}" for i in range(1, 9))
ZONES = {1: "street", 2: "yard", 3: "park edge"}


def build(site):
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    tmp = d / "tmp"
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

    def put(arr, name):
        r = arcpy.NumPyArrayToRaster(arr, ll, CELL, CELL)
        arcpy.management.CopyRaster(r, f"{gdb}/{name}")
        arcpy.management.DefineProjection(f"{gdb}/{name}", sr)

    def away(mask, metres):
        """True where the nearest cell of `mask` is at least this far off."""
        if not mask.any():
            return np.ones(mask.shape, bool)
        return ndimage.distance_transform_edt(~mask) * CELL >= metres

    lc = grab(f"{gdb}/land_cover")
    veg = grab(f"{gdb}/veg_height")
    dtm = grab(f"{gdb}/dtm")
    tree, roof, pave = lc == 1, lc == 2, lc == 3
    open_ground = (lc == 4) | (lc == 5)

    # Wires and poles: tall, not tree, not roof. Lone cells are noise
    tall = (veg >= OVERHEAD_MIN_M) & ~tree & ~roof
    overhead = tall & (ndimage.uniform_filter(tall.astype(np.float32), 5) * 25 >= 3)

    # Parcels by kind
    arcpy.management.MakeFeatureLayer(f"{gdb}/parcels", "res", " OR ".join(
        f"PARCEL_USE LIKE '{p}%'" for p in RESIDENTIAL))
    arcpy.conversion.PolygonToRaster("res", "OBJECTID", str(tmp / "res.tif"),
                                     cellsize=CELL)
    arcpy.management.Delete("res")
    residential = grab(str(tmp / "res.tif")) > 0
    parcel = grab(str(tmp / "parcel.tif")) > 0
    park = np.zeros(lc.shape, bool)
    if arcpy.Exists(f"{gdb}/parks"):
        arcpy.conversion.PolygonToRaster(f"{gdb}/parks", "OBJECTID",
                                         str(tmp / "park.tif"), cellsize=CELL)
        park = grab(str(tmp / "park.tif")) > 0
    park_rim = park & ~away(~park, PARK_EDGE_M)

    # Street intersections: places where three or more segment ends meet
    ends = {}
    with arcpy.da.SearchCursor(f"{gdb}/streets", ["SHAPE@"]) as cur:
        for (shp,) in cur:
            for pt in (shp.firstPoint, shp.lastPoint):
                k = (round(pt.X), round(pt.Y))
                ends[k] = ends.get(k, 0) + 1
    corner = np.zeros(lc.shape, bool)
    pts = f"{gdb}/street_corners"
    if arcpy.Exists(pts):
        arcpy.management.Delete(pts)
    arcpy.management.CreateFeatureclass(gdb, "street_corners", "POINT", spatial_reference=sr)
    with arcpy.da.InsertCursor(pts, ["SHAPE@XY"]) as cur:
        for (x, y), n in ends.items():
            if n >= 3:
                cur.insertRow(((x, y),))
                r, c = int((y1 - y) / CELL), int((x - x0) / CELL)
                if 0 <= r < rows and 0 <= c < cols:
                    corner[r, c] = True

    clear = (open_ground & away(roof, BUILDING_M) & away(pave, PAVEMENT_M) &
             away(tree, CANOPY_M) & away(overhead, OVERHEAD_M))
    zone = np.zeros(lc.shape, np.uint8)
    zone[clear & park_rim] = 3
    zone[clear & residential & ~park] = 2
    # Street strip: un-parcelled ground beside street pavement. Un-parcelled
    # ground further back (wash banks, drainage land) is not a street
    street_pave = pave & ~parcel
    strip = ~parcel & ~park & ~away(street_pave, STREET_STRIP_M)
    zone[clear & strip & away(corner, CORNER_M)] = 1
    put(zone, "plantable")
    put(overhead.astype(np.uint8), "overhead")

    # Runoff: roofs raised 5 m so water runs off them, not through them
    surface = arcpy.NumPyArrayToRaster((dtm + np.where(roof, 5.0, 0)).astype(np.float32),
                                       ll, CELL, CELL)
    hard = arcpy.NumPyArrayToRaster((roof | pave).astype(np.float32), ll, CELL, CELL)
    acc = FlowAccumulation(FlowDirection(Fill(surface)), hard, "FLOAT")
    area = grab(Con(acc >= 0, acc), 0) * CELL * CELL
    reach = int(round(TAP_M / CELL))
    yy, xx = np.ogrid[-reach:reach + 1, -reach:reach + 1]
    runoff = ndimage.maximum_filter(area, footprint=xx * xx + yy * yy <= reach * reach)
    put(runoff.astype(np.float32), "runoff_m2")

    inside = grab(str(tmp / "inside.tif")) > 0
    n = inside.sum()
    summary = dict(
        site=site["id"],
        open_ground_pct=round(float(open_ground[inside].mean() * 100), 1),
        plantable_pct={name: round(float((zone[inside] == k).mean() * 100), 1)
                       for k, name in ZONES.items()},
        plantable_ha={name: round(float((zone[inside] == k).sum() * CELL * CELL / 1e4), 2)
                      for k, name in ZONES.items()},
        open_ground_ruled_out_pct=round(float((open_ground & (zone == 0))[inside].sum() / n * 100), 1),
        street_corners=int(sum(1 for v in ends.values() if v >= 3)),
        overhead_pct=round(float(overhead[inside].mean() * 100), 2),
        runoff_fed_share_of_plantable=round(float(
            (runoff[inside & (zone > 0)] >= 50).mean()), 2),
        rules=dict(street_strip_m=STREET_STRIP_M, building_m=BUILDING_M, pavement_m=PAVEMENT_M, canopy_m=CANOPY_M,
                   overhead_m=OVERHEAD_M, corner_m=CORNER_M, park_edge_m=PARK_EDGE_M))
    (d / "plantable.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1), flush=True)

    from PIL import Image
    pal = np.array([[235, 235, 235], [230, 97, 1], [94, 60, 153], [0, 136, 55]], np.uint8)
    img = pal[zone]
    img[(zone == 0) & tree] = (170, 200, 160)
    img[(zone == 0) & roof] = (150, 150, 150)
    img[(zone == 0) & pave] = (200, 200, 200)
    Image.fromarray(img).save(str(d / "ql_plantable.png"))


def main():
    if arcpy.CheckOutExtension("Spatial") != "CheckedOut":
        raise SystemExit("Spatial Analyst licence not available")
    for s in sites(sys.argv[1:]):
        build(s)


if __name__ == "__main__":
    main()
