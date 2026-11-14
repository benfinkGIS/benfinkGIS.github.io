"""Step 2: build each site's geodatabase: vectors, lidar surfaces, imagery.

Runs in ArcGIS Pro's Python (needs Spatial Analyst and 3D Analyst):

  "%LOCALAPPDATA%\\Programs\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe"
      tools/canopy/04_build_surfaces.py [site_id ...]

For every site in sites.json it writes work/<site>/<site>.gdb with the same
layer names, so later steps and other sites never need special cases:

  boundary        neighborhood polygon
  work_area       the boundary's box plus the buffer; every raster covers it
  buildings, parcels, streets            county layers over the work area
  washes, riparian, parks, protected     county layers out to 1 km beyond it
  dtm             bare ground elevation, from ground-classified returns
  dsm             top surface, highest first return in each cell
  chm             dsm minus dtm: height above ground of whatever is there
  veg_height      height above ground of returns that are neither ground nor
                  building: trees and shrubs, plus cars, walls, poles, wires
  roof_lidar      1 where the lidar's building class has points
  intensity       average lidar return strength of single-return ground
                  points: a shadow-free picture of how bright the ground is
  multi_return    share of returns in each cell that came from a pulse with
                  more than one return (high in tree crowns, low on roofs)
  naip_2023       4-band NAIP mosaic at 0.3 m
  ndvi            NDVI from that imagery, on the lidar grid
  canopy_first    first-pass tree canopy: tall, and green or porous to lidar.
                  A starting point only; the land cover step replaces it

All rasters except the imagery share one 0.5 m grid. Quick-look PNGs and a
summary.json land beside the geodatabase.
"""
import json
import sys
from pathlib import Path

import arcpy
import numpy as np
from arcpy.sa import Con, Expand, Float, IsNull, Raster, SetNull, Shrink

from common import EPSG, LIDAR, site_dir, sites, work_bbox

CELL = 0.5            # m; the 2021 flight averages well over 8 points per m2
TREE_MIN_M = 2.5      # shorter vegetation is treated as shrub
NDVI_GREEN = 0.10     # first-pass only
MULTI_POROUS = 0.25   # first-pass only
THIN_CELLS = 1        # strips this many cells wide (each side) are dropped
NOISE = [7, 18]       # low and high noise classes
CONTEXT = dict(buildings="POLYGON", parcels="POLYGON", streets="POLYLINE",
               washes="POLYLINE", riparian="POLYGON", parks="POLYGON",
               protected="POLYGON")


def msg(*a):
    print(*a, flush=True)


def las_dataset(site, d):
    """LAS dataset over the site's tiles. LAZ is unpacked first if Pro
    cannot read it directly."""
    manifest = json.loads((LIDAR / "manifest.json").read_text())
    tiles = [str(LIDAR / t["file"]) for t in manifest[site["id"]]]
    lasd = str(d / f"{site['id']}.lasd")
    if arcpy.Exists(lasd):
        return lasd
    try:
        arcpy.management.CreateLasDataset(tiles, lasd, compute_stats="COMPUTE_STATS")
        if int(arcpy.Describe(lasd).pointCount or 0) > 0:
            return lasd
        arcpy.management.Delete(lasd)
    except arcpy.ExecuteError:
        msg("  LAZ not read directly; converting to LAS")
    las_dir = d / "las"
    las_dir.mkdir(exist_ok=True)
    arcpy.conversion.ConvertLas(tiles, str(las_dir), compression="NO_COMPRESSION",
                                las_options="REARRANGE_POINTS",
                                out_las_dataset=lasd)
    arcpy.management.LasDatasetStatistics(lasd, "OVERWRITE_EXISTING_STATS")
    return lasd


def class_codes(lasd):
    """Class codes present, with point counts, from the dataset statistics."""
    out = str(Path(lasd).with_suffix(".stats.csv"))
    arcpy.management.LasDatasetStatistics(lasd, "SKIP_EXISTING_STATS", out,
                                          "DATASET", "COMMA", "DECIMAL_POINT")
    rows = {}
    for line in Path(out).read_text().splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) > 3 and parts[1] == "ClassCodes":
            rows[parts[0]] = int(float(parts[2]))
    return rows


def quicklook(arr, path, cmap, vmin, vmax):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.imsave(path, arr, cmap=cmap, vmin=vmin, vmax=vmax)


def build(site):
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    if not arcpy.Exists(gdb):
        arcpy.management.CreateFileGDB(str(d), f"{site['id']}.gdb")
    sr = arcpy.SpatialReference(EPSG)
    x0, y0, x1, y1 = work_bbox(site)
    arcpy.env.workspace = gdb
    arcpy.env.overwriteOutput = True
    arcpy.ClearEnvironment("outputCoordinateSystem")
    arcpy.ClearEnvironment("extent")
    arcpy.ClearEnvironment("snapRaster")

    msg(site["id"], "boundary and work area")
    arcpy.conversion.JSONToFeatures(str(d / "boundary.geojson"),
                                    f"{gdb}/boundary", "POLYGON")
    box = arcpy.Polygon(arcpy.Array([arcpy.Point(*p) for p in
                                     [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]]), sr)
    arcpy.management.CopyFeatures([box], f"{gdb}/work_area")

    for name, kind in CONTEXT.items():
        src = d / "context" / f"{name}.geojson"
        if arcpy.Exists(f"{gdb}/{name}"):
            arcpy.management.Delete(f"{gdb}/{name}")
        if src.exists() and json.loads(src.read_text())["features"]:
            arcpy.conversion.JSONToFeatures(str(src), f"{gdb}/{name}", kind)

    # Raster settings go on only after the vectors are in: JSON To Features
    # fails with an output coordinate system set in the environment
    arcpy.env.outputCoordinateSystem = sr
    arcpy.env.extent = arcpy.Extent(x0, y0, x1, y1)
    arcpy.env.cellSize = CELL

    msg(site["id"], "lidar")
    lasd = las_dataset(site, d)
    desc = arcpy.Describe(lasd)
    codes = class_codes(lasd)
    msg("  points", desc.pointCount, "| CRS", desc.spatialReference.name,
        "| classes", codes)

    keep = [int(c.split("_")[0]) if "_" in c else int(c) for c in codes]
    keep = [c for c in keep if c not in NOISE]

    arcpy.management.MakeLasDatasetLayer(lasd, "ground", class_code=[2])
    arcpy.conversion.LasDatasetToRaster(
        "ground", f"{gdb}/dtm", "ELEVATION",
        "BINNING AVERAGE NATURAL_NEIGHBOR", "FLOAT", "CELLSIZE", CELL)

    arcpy.management.MakeLasDatasetLayer(lasd, "first", class_code=keep,
                                         return_values=["1"])
    arcpy.conversion.LasDatasetToRaster(
        "first", f"{gdb}/dsm", "ELEVATION",
        "BINNING MAXIMUM NATURAL_NEIGHBOR", "FLOAT", "CELLSIZE", CELL)

    chm = Con(Raster(f"{gdb}/dsm") - Raster(f"{gdb}/dtm") < 0, 0,
              Raster(f"{gdb}/dsm") - Raster(f"{gdb}/dtm"))
    chm.save(f"{gdb}/chm")

    # Height of whatever is neither ground nor building: trees, shrubs, and
    # also cars, walls, poles and wires. No void filling, so empty cells are 0
    tmp = d / "tmp"
    tmp.mkdir(exist_ok=True)
    arcpy.management.MakeLasDatasetLayer(lasd, "other", class_code=[1])
    arcpy.conversion.LasDatasetToRaster(
        "other", str(tmp / "other_top.tif"), "ELEVATION",
        "BINNING MAXIMUM NONE", "FLOAT", "CELLSIZE", CELL)
    top = Raster(str(tmp / "other_top.tif"))
    veg = Con(IsNull(top), 0, Con(top - Raster(f"{gdb}/dtm") < 0, 0,
                                  top - Raster(f"{gdb}/dtm")))
    veg.save(f"{gdb}/veg_height")

    def count(layer, name):
        """Points per cell for a LAS layer, with empty cells as 0."""
        out = str(tmp / f"{name}.tif")
        arcpy.management.LasPointStatsAsRaster(layer, out, "POINT_COUNT",
                                               "CELLSIZE", CELL)
        return Con(IsNull(Raster(out)), 0, Raster(out))

    # Share of returns that belong to multi-return pulses, per cell
    arcpy.management.MakeLasDatasetLayer(lasd, "all", class_code=keep)
    arcpy.management.MakeLasDatasetLayer(
        lasd, "multi", class_code=keep,
        return_values=["FIRST_OF_MANY", "LAST_OF_MANY", "2", "3", "4", "5", "6", "7"])
    n_all = count("all", "n_all")
    multi = Con(n_all == 0, 0, Float(count("multi", "n_multi")) / Float(n_all))
    multi.save(f"{gdb}/multi_return")

    # Ground brightness at the laser's wavelength (near infrared). Unlike the
    # photo it has no shadows, and asphalt is much darker than soil
    # Single returns only: a pulse that clipped a tree first comes back weak
    arcpy.management.MakeLasDatasetLayer(lasd, "ground_single", class_code=[2],
                                         return_values=["SINGLE"])
    arcpy.conversion.LasDatasetToRaster(
        "ground_single", f"{gdb}/intensity", "INTENSITY",
        "BINNING AVERAGE NATURAL_NEIGHBOR", "FLOAT", "CELLSIZE", CELL)

    # Roofs, straight from the lidar's own building class
    if any(c.startswith("6") for c in codes):
        arcpy.management.MakeLasDatasetLayer(lasd, "bldg", class_code=[6])
        roof = Con(count("bldg", "n_bldg") > 0, 1, 0)
    else:
        roof = Con(n_all >= 0, 0)
    roof.save(f"{gdb}/roof_lidar")

    msg(site["id"], "imagery")
    tiles = sorted(str(p) for p in (d / "naip").glob("naip_*.tif"))
    arcpy.env.cellSize = None
    arcpy.management.MosaicToNewRaster(tiles, gdb, "naip_2023", sr,
                                       "8_BIT_UNSIGNED", 0.3, 4, "LAST", "FIRST")
    arcpy.env.cellSize = CELL
    arcpy.env.snapRaster = f"{gdb}/chm"
    red = Float(Raster(f"{gdb}/naip_2023/Band_1"))
    nir = Float(Raster(f"{gdb}/naip_2023/Band_4"))
    ndvi = SetNull((nir + red) == 0, (nir - red) / (nir + red))
    ndvi.save(f"{gdb}/ndvi")

    msg(site["id"], "first-pass canopy")
    raw = Con((Raster(f"{gdb}/veg_height") >= TREE_MIN_M) &
              ((Raster(f"{gdb}/ndvi") >= NDVI_GREEN) |
               (Raster(f"{gdb}/multi_return") >= MULTI_POROUS)), 1, 0)
    # Power lines and roof-edge specks are one or two cells wide. Shrinking
    # by a cell removes them; growing back restores the crowns that survive
    opened = Expand(Shrink(raw, THIN_CELLS, [1]), THIN_CELLS, [1])
    canopy = Con((opened == 1) & (raw == 1), 1, 0)
    canopy.save(f"{gdb}/canopy_first")

    # Share of the neighborhood under first-pass canopy
    arcpy.env.snapRaster = f"{gdb}/chm"
    arcpy.conversion.PolygonToRaster(f"{gdb}/boundary", "OBJECTID",
                                     str(tmp / "inside.tif"), cellsize=CELL)
    ll = arcpy.Point(x0, y0)
    shape = (round((y1 - y0) / CELL), round((x1 - x0) / CELL))
    grab = lambda name, nd: arcpy.RasterToNumPyArray(
        name, ll, shape[1], shape[0], nodata_to_value=nd)
    inside = grab(str(tmp / "inside.tif"), 0) > 0
    can = grab(f"{gdb}/canopy_first", 0) == 1
    h = grab(f"{gdb}/veg_height", 0)
    roof_a = grab(f"{gdb}/roof_lidar", 0) == 1
    nd = grab(f"{gdb}/ndvi", -1)
    summary = dict(
        site=site["id"], cell_m=CELL, grid=list(shape),
        lidar=dict(points=int(desc.pointCount), crs=desc.spatialReference.name,
                   classes=codes,
                   points_per_m2=round(int(desc.pointCount) / (
                       (desc.extent.XMax - desc.extent.XMin) *
                       (desc.extent.YMax - desc.extent.YMin)), 1)),
        neighborhood_km2=round(float(inside.sum()) * CELL * CELL / 1e6, 3),
        first_pass_canopy_pct=round(float(can[inside].mean() * 100), 1),
        roof_pct=round(float(roof_a[inside].mean() * 100), 1),
        tall_not_canopy_pct=round(float(((h >= TREE_MIN_M) & ~can)[inside].mean() * 100), 1),
        canopy_height_m=dict(
            median=round(float(np.median(h[can & inside])), 1),
            p90=round(float(np.percentile(h[can & inside], 90)), 1),
            max=round(float(h[can & inside].max()), 1)),
        settings=dict(tree_min_m=TREE_MIN_M, ndvi_green=NDVI_GREEN,
                      multi_porous=MULTI_POROUS, thin_cells=THIN_CELLS))
    (d / "summary.json").write_text(json.dumps(summary, indent=1))
    msg(json.dumps(summary, indent=1))

    quicklook(np.clip(grab(f"{gdb}/chm", 0), 0, 15), str(d / "ql_chm.png"), "viridis", 0, 15)
    quicklook(np.clip(h, 0, 15), str(d / "ql_veg_height.png"), "viridis", 0, 15)
    quicklook(nd, str(d / "ql_ndvi.png"), "RdYlGn", -0.3, 0.5)
    quicklook(grab(f"{gdb}/multi_return", 0), str(d / "ql_multi.png"), "magma", 0, 1)
    rgb = arcpy.RasterToNumPyArray(f"{gdb}/naip_2023", ll, nodata_to_value=0)
    rgb = np.moveaxis(rgb[:3], 0, -1)
    from PIL import Image
    Image.fromarray(rgb).save(str(d / "ql_naip.jpg"), quality=90)
    # Canopy outline over the photo, for checking by eye
    big = np.asarray(Image.fromarray((can * 255).astype(np.uint8)).resize(
        (rgb.shape[1], rgb.shape[0]), Image.NEAREST)) > 0
    edge = big & ~(np.roll(big, 1, 0) & np.roll(big, -1, 0) &
                   np.roll(big, 1, 1) & np.roll(big, -1, 1))
    over = rgb.copy()
    over[edge] = (255, 235, 0)
    Image.fromarray(over).save(str(d / "ql_canopy_over_naip.jpg"), quality=90)


def main():
    for ext in ("Spatial", "3D"):
        if arcpy.CheckOutExtension(ext) != "CheckedOut":
            raise SystemExit(f"{ext} Analyst licence not available")
    for s in sites(sys.argv[1:]):
        build(s)


if __name__ == "__main__":
    main()
