"""Step 2b: build the channel network from the 1 m lidar elevation.

Runs in ArcGIS Pro's Python (needs Spatial Analyst):

  "%LOCALAPPDATA%\\Programs\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe"
      tools/washes/06_channels.py [--window x0 y0 x1 y1] [--tag name]

What it does, in order:

  1. Loads the county layers into work/washes.gdb.
  2. Mosaics the USGS 1 m tiles over the study box (work/dem/dem_1m.tif).
  3. Cuts culverts. Bare-ground lidar keeps road and rail embankments but
     not the pipes under them, so water in the model would pond behind every
     road. Wherever a county-mapped wash crosses a street or the railroad,
     a strip 20 m wide and up to 60 m long is lowered to the lowest ground
     in it, which opens the embankment at channel-bed level.
  4. Fills the remaining pits, then runs D8 flow direction and accumulation.
     Washes the county has not mapped still pond behind their roads and
     spill over the low point of the crown, which is usually at the dip or
     the culvert.
  5. Keeps every cell that drains at least MIN_AREA_M2 as a channel, splits
     the channels at confluences, and writes them as lines with Strahler
     order and the area draining to the downstream end of each.

With --window the same steps run on a small box into a separate geodatabase,
for timing and for trying thresholds.
"""
import argparse
import json
import time
from pathlib import Path

import arcpy
from arcpy.sa import (Con, Fill, FlowAccumulation, FlowDirection, IsNull, Raster,
                      StreamLink, StreamOrder, StreamToFeature, ZonalStatistics,
                      ZonalStatisticsAsTable)

from common import BBOX, CONTEXT, EPSG, WORK

MIN_AREA_M2 = 20000      # a channel starts where 2 ha drains to a cell
CUT_HALF_WIDTH_M = 10    # culvert cut: this far either side of the mapped wash
CUT_REACH_M = 30         # and this far up and down the wash from the crossing
VECTORS = dict(washes="POLYLINE", streets="POLYLINE", railroads="POLYLINE",
               riparian="POLYGON", parks="POLYGON", protected="POLYGON",
               structures="POLYLINE", nhd_named="POLYLINE", bridges_nbi="POINT")


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_vectors(gdb):
    for name, kind in VECTORS.items():
        if not arcpy.Exists(f"{gdb}/{name}"):
            arcpy.conversion.JSONToFeatures(str(CONTEXT / f"{name}.geojson"),
                                            f"{gdb}/{name}", kind)
            arcpy.management.DefineProjection(f"{gdb}/{name}", arcpy.SpatialReference(EPSG))


def mosaic(box, out):
    if arcpy.Exists(str(out)):
        return
    tiles = sorted(str(p) for p in (WORK / "dem").glob("USGS_1M_*.tif"))
    arcpy.env.extent = arcpy.Extent(*box)
    arcpy.management.MosaicToNewRaster(
        tiles, str(out.parent), out.name, arcpy.SpatialReference(EPSG),
        "32_BIT_FLOAT", 1, 1, "FIRST", "FIRST")


def culvert_zones(gdb):
    """Strips of mapped wash at each street or rail crossing."""
    if arcpy.Exists(f"{gdb}/culvert_cuts"):
        return
    arcpy.management.Merge([f"{gdb}/streets", f"{gdb}/railroads"], "memory/ways",
                           field_mappings=None)
    arcpy.analysis.PairwiseIntersect([f"{gdb}/washes", "memory/ways"],
                                     f"{gdb}/crossings_county", "ONLY_FID",
                                     output_type="POINT")
    arcpy.analysis.PairwiseBuffer(f"{gdb}/crossings_county", "memory/near",
                                  f"{CUT_REACH_M} Meters", "ALL")
    arcpy.analysis.PairwiseClip(f"{gdb}/washes", "memory/near", "memory/strips")
    arcpy.analysis.PairwiseBuffer("memory/strips", "memory/cuts",
                                  f"{CUT_HALF_WIDTH_M} Meters", "ALL")
    arcpy.management.MultipartToSinglepart("memory/cuts", f"{gdb}/culvert_cuts")
    for m in ("ways", "near", "strips", "cuts"):
        arcpy.management.Delete(f"memory/{m}")


def run(box, gdb, folder):
    sr = arcpy.SpatialReference(EPSG)
    arcpy.env.overwriteOutput = True
    arcpy.env.parallelProcessingFactor = "75%"
    arcpy.env.pyramid = "NONE"
    stats = dict(box=box, min_area_m2=MIN_AREA_M2)

    msg("vectors")
    load_vectors(gdb)
    culvert_zones(gdb)
    stats["county_crossings"] = int(arcpy.management.GetCount(f"{gdb}/crossings_county")[0])
    stats["culvert_cuts"] = int(arcpy.management.GetCount(f"{gdb}/culvert_cuts")[0])

    msg("elevation mosaic")
    dem_path = folder / "dem_1m.tif"
    mosaic(box, dem_path)
    arcpy.env.outputCoordinateSystem = sr
    arcpy.env.snapRaster = str(dem_path)
    arcpy.env.cellSize = 1
    arcpy.env.extent = arcpy.Extent(*box)
    dem = Raster(str(dem_path))

    msg("culvert cuts")
    cut_path = folder / "dem_cut.tif"
    if not arcpy.Exists(str(cut_path)):
        zmin = ZonalStatistics(f"{gdb}/culvert_cuts", "OBJECTID", dem, "MINIMUM", "DATA")
        Con(IsNull(zmin), dem, zmin).save(str(cut_path))
        del zmin

    msg("fill")
    fill_path = folder / "dem_fill.tif"
    if not arcpy.Exists(str(fill_path)):
        Fill(str(cut_path)).save(str(fill_path))

    msg("flow direction")
    fdir_path = folder / "flow_dir.tif"
    if not arcpy.Exists(str(fdir_path)):
        FlowDirection(str(fill_path), "NORMAL", None, "D8").save(str(fdir_path))

    msg("flow accumulation")
    acc_path = folder / "flow_acc.tif"
    if not arcpy.Exists(str(acc_path)):
        acc_tmp = FlowAccumulation(str(fdir_path), None, "INTEGER", "D8")
        # Saving this raster in place failed on the full study area (ERROR 010240);
        # copying it out works.
        arcpy.management.CopyRaster(acc_tmp, str(acc_path), pixel_type="32_BIT_SIGNED")
        del acc_tmp

    msg("channels")
    acc = Raster(str(acc_path))
    streams = Con(acc >= MIN_AREA_M2, 1)
    links = StreamLink(streams, str(fdir_path))
    links.save(str(folder / "stream_link.tif"))
    order = StreamOrder(streams, str(fdir_path), "STRAHLER")
    order.save(str(folder / "stream_order.tif"))
    StreamToFeature(links, str(fdir_path), f"{gdb}/channels_raw", "NO_SIMPLIFY")

    msg("channel attributes")
    for name, source, stat, field in (("area", acc, "MAXIMUM", "MAX"),
                                      ("order", order, "MAXIMUM", "MAX")):
        ZonalStatisticsAsTable(links, "VALUE", source, f"{gdb}/link_{name}", "DATA", stat)
    area = {r[0]: r[1] for r in arcpy.da.SearchCursor(f"{gdb}/link_area", ["VALUE", "MAX"])}
    strahler = {r[0]: r[1] for r in arcpy.da.SearchCursor(f"{gdb}/link_order", ["VALUE", "MAX"])}
    arcpy.management.AddField(f"{gdb}/channels_raw", "drain_ha", "DOUBLE")
    arcpy.management.AddField(f"{gdb}/channels_raw", "strahler", "SHORT")
    total = 0.0
    with arcpy.da.UpdateCursor(f"{gdb}/channels_raw",
                               ["grid_code", "drain_ha", "strahler", "SHAPE@LENGTH"]) as cur:
        for row in cur:
            row[1] = round(area.get(row[0], 0) / 10000, 2)
            row[2] = int(strahler.get(row[0], 0))
            total += row[3]
            cur.updateRow(row)
    stats["channel_links"] = int(arcpy.management.GetCount(f"{gdb}/channels_raw")[0])
    stats["channel_km"] = round(total / 1000, 1)
    (folder / "channels.json").write_text(json.dumps(stats, indent=2))
    msg(json.dumps(stats))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", nargs=4, type=float)
    ap.add_argument("--tag", default="test")
    a = ap.parse_args()
    arcpy.CheckOutExtension("Spatial")
    if a.window:
        folder = WORK / f"window_{a.tag}"
        box = tuple(a.window)
    else:
        folder = WORK / "dem"
        box = BBOX
    folder.mkdir(parents=True, exist_ok=True)
    gdb = WORK / ("washes.gdb" if not a.window else f"window_{a.tag}/{a.tag}.gdb")
    if not arcpy.Exists(str(gdb)):
        arcpy.management.CreateFileGDB(str(gdb.parent), gdb.name)
    run(box, str(gdb), folder)


if __name__ == "__main__":
    main()
