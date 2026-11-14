"""Step 10d: package each site's GIS files for handing over.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/20_package.py [site_id ...]

A file geodatabase only opens in Esri software, so the hand-over copy is in
open formats: one GeoPackage of vector layers and a set of compressed
GeoTIFFs per site, with a plain-text list of what each layer is.

Writes tucson-canopy/work/deliverable/<site>/ and a zip beside it:
  <site>.gpkg          boundary, proposed trees and their crowns, accuracy
                       points, street corners, washes, riparian habitat, parks
  *.tif                land cover, canopy height, plantable zones, runoff,
                       canopy and shade under each scenario
  LAYERS.txt           what each layer is, its units and its source

The parcel layer is left out: it is the county's to give, and the analysis
only used it to tell yards from streets. Nothing here carries owner names.
"""
import shutil
import sys

import arcpy

from common import EPSG, WORK, site_dir, sites

VECTORS = {
    "boundary": "Neighborhood association boundary (City of Tucson)",
    "trees": "Proposed trees, one point each. Scenario 1 = street trees, 2 = streets and homes, "
             "3 = full build-out; each includes the lower numbers. Crown_m and Height_m are published "
             "mature sizes; Runoff_m2 is the roof and pavement draining to within 2 m; RunoffFed = 1 "
             "where that is 50 m2 or more; InBoundary = 1 inside the neighborhood",
    "tree_crowns": "The proposed trees inside the boundary as mature crown circles",
    "accuracy_points": "Stratified random accuracy sample. Classified = mapped class, GrndTruth = class "
                       "labelled by hand from the 2023 photo (-1 = could not tell). Classes: 1 tree canopy, "
                       "2 roof, 3 pavement, 4 low vegetation, 5 bare ground, 6 water",
    "street_corners": "Street intersections used for the corner setback (Pima County streets)",
    "washes": "Wash network within 1 km (Pima County Regional Flood Control District)",
    "riparian": "Mapped riparian habitat within 1 km (Pima County riparian classification)",
    "parks": "Parks, greenways and school grounds within 1 km (Pima County)",
}
RASTERS = {
    "land_cover": ("Land cover: 1 tree canopy, 2 roof, 3 pavement, 4 low vegetation, 5 bare ground, "
                   "6 water. Low vegetation and bare ground are not reliably separated; treat as open ground"),
    "veg_height": "Height above ground, metres, of lidar returns that are neither ground nor building",
    "plantable": "Where a trunk could go: 0 none, 1 street strip, 2 home yard, 3 park or school edge",
    "runoff_m2": "Square metres of roof and pavement draining to within 2 m of the cell",
    "canopy_s1": "Tree canopy with street trees at mature size (1 = canopy)",
    "canopy_s2": "Tree canopy with streets-and-homes planting at mature size",
    "canopy_s3": "Tree canopy at full build-out",
    "shade_s0": "Ground in shade at 4 p.m. on 15 July, today (1 = shade)",
    "shade_s1": "Ground in shade at 4 p.m. on 15 July with street trees",
    "shade_s2": "Ground in shade at 4 p.m. on 15 July with streets-and-homes planting",
}


def package(site):
    gdb = str(site_dir(site) / f"{site['id']}.gdb")
    out = WORK / "deliverable" / site["id"]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    arcpy.env.overwriteOutput = True
    arcpy.env.compression = "LZW"
    arcpy.env.pyramid = "NONE"
    arcpy.env.rasterStatistics = "NONE"
    gpkg = str(out / f"{site['id']}.gpkg")
    arcpy.management.CreateSQLiteDatabase(gpkg, "GEOPACKAGE")
    lines = [f"{site['name']}: GIS layers from the Tucson Neighborhood Canopy Scenario",
             f"Coordinate system: EPSG:{EPSG} (NAD83 / UTM zone 12N), metres. Rasters: 0.5 m cells.",
             "Lidar: USGS 3DEP, autumn 2021. Imagery: USDA NAIP, 18 October 2023.",
             "A planning sketch, not a survey or a planting plan.",
             "Method and results: https://finkgeo.com/tucson-canopy/", "",
             f"Vector layers in {site['id']}.gpkg", ""]
    for name, what in VECTORS.items():
        if not arcpy.Exists(f"{gdb}/{name}"):
            continue
        arcpy.conversion.ExportFeatures(f"{gdb}/{name}", f"{gpkg}/{name}")
        n = int(arcpy.management.GetCount(f"{gdb}/{name}")[0])
        lines.append(f"  {name} ({n:,} features): {what}")
    lines += ["", "Rasters (GeoTIFF, LZW)", ""]
    for name, what in RASTERS.items():
        arcpy.management.CopyRaster(f"{gdb}/{name}", str(out / f"{name}.tif"))
        lines.append(f"  {name}.tif: {what}")
    (out / "LAYERS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for junk in list(out.glob("*.xml")) + list(out.glob("*.ovr")) + list(out.glob("*.tfw")) + list(out.glob("*.cpg")):
        junk.unlink()
    zipped = shutil.make_archive(str(out), "zip", out)
    size = sum(p.stat().st_size for p in out.iterdir()) / 1e6
    print(f"{site['id']}: {len(list(out.iterdir()))} files, {size:.0f} MB; zip "
          f"{__import__('os').path.getsize(zipped) / 1e6:.0f} MB", flush=True)


def main():
    for s in sites(sys.argv[1:]):
        package(s)


if __name__ == "__main__":
    main()
