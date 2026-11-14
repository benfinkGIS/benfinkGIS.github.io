"""Step 2b: check every site geodatabase and write its metadata.

Runs in ArcGIS Pro's Python. For each site it tests the layers against the
schema below and writes work/<site>/qa_report.csv, one row per test, PASS or
FAIL. Nothing downstream should run on a site with a FAIL.

Tests
  exists      the layer is in the geodatabase
  crs         it is in the project coordinate system
  not_empty   vectors have features; rasters have data cells
  geometry    no null or empty shapes (vectors)
  covers      the layer reaches all four sides of the work area (rasters,
              and the vector layers that should blanket the site)
  grid        analysis rasters share one cell size and one origin
  range       raster values fall inside what is physically sensible

It then writes a summary, description, credits and use limits into each
layer's metadata, so the geodatabase explains itself when it is handed over.

Run:  <Pro python> tools/canopy/05_check_and_document.py [site_id ...]
"""
import csv
import json
import sys

import arcpy
from arcpy import metadata as md

from common import EPSG, site_dir, sites, work_bbox

CELL = 0.5
LIDAR_CREDIT = ("USGS 3D Elevation Program, AZ_PimaCounty_2021_B21 "
                "(work unit AZ_PimaCo_2_2021), flown 27 Sep to 17 Nov 2021, "
                "quality level 1")
NAIP_CREDIT = "USDA NAIP, flown 18 Oct 2023, served by the USGS NAIPPlus image service"
COUNTY = "Pima County GIS open data, downloaded November 2026"
CITY = "City of Tucson open data, downloaded November 2026"
SKETCH = ("Planning-level analysis for a portfolio project. Not surveyed, "
          "not a planting plan.")

# name: (kind, must cover the work area, value range, summary, credit)
SCHEMA = {
    "boundary": ("vector", False, None, "Neighborhood association boundary", CITY),
    "work_area": ("vector", True, None,
                  "Boundary box plus buffer; the extent of every raster", "Derived"),
    "buildings": ("vector", False, None,
                  "Building footprints (machine-drawn from Bing imagery)", COUNTY),
    "parcels": ("vector", True, None,
                "Parcels with parcel number and use code only; no owner details", COUNTY),
    "streets": ("vector", False, None, "Street centerlines", COUNTY),
    "washes": ("vector", False, None, "Wash network within 1 km", COUNTY),
    "parks": ("vector", False, None, "Parks and recreation areas within 1 km", COUNTY),
    "dtm": ("raster", True, (500, 1500),
            "Bare-ground elevation in metres, from ground-classified lidar returns",
            LIDAR_CREDIT),
    "dsm": ("raster", True, (500, 1600),
            "Top-surface elevation in metres, highest first return per cell",
            LIDAR_CREDIT),
    "chm": ("raster", True, (0, 100),
            "Height above ground in metres (surface minus bare ground). "
            "Includes buildings and wires until they are masked", LIDAR_CREDIT),
    "veg_height": ("raster", True, (0, 100),
                   "Height above ground in metres of lidar returns that are neither "
                   "ground nor building: trees and shrubs, plus cars, walls, poles "
                   "and wires", LIDAR_CREDIT),
    "roof_lidar": ("raster", True, (0, 1),
                   "1 where the lidar's building class has points", LIDAR_CREDIT),
    "intensity": ("raster", True, (0, 65535),
                  "Average lidar return strength of ground-classified points; "
                  "shadow-free ground brightness in the near infrared", LIDAR_CREDIT),
    "multi_return": ("raster", True, (0, 1),
                     "Share of lidar returns per cell from multi-return pulses; "
                     "high in tree crowns", LIDAR_CREDIT),
    "naip_2023": ("raster", True, (0, 255),
                  "Four-band aerial imagery at 0.3 m: red, green, blue, near infrared",
                  NAIP_CREDIT),
    "ndvi": ("raster", True, (-1, 1), "NDVI from the 2023 imagery on the lidar grid",
             NAIP_CREDIT),
    "canopy_first": ("raster", True, (0, 1),
                     "First-pass tree canopy (1 = canopy): vegetation height of 2.5 m "
                     "or more that is green or porous to lidar, with strips one or "
                     "two cells wide removed. Superseded by the land cover",
                     LIDAR_CREDIT + "; " + NAIP_CREDIT),
}
# Layers from later steps; checked once they exist
LATER = {
    "land_cover": ("raster", True, (1, 6),
                   "Land cover: 1 tree canopy, 2 roof, 3 pavement, 4 low vegetation, "
                   "5 bare ground, 6 water. Trees and roofs from lidar structure; "
                   "ground classes from a Random Trees classifier trained on "
                   "automatically drawn samples", LIDAR_CREDIT + "; " + NAIP_CREDIT),
    "land_cover_seeds": ("vector", False, None,
                         "Training points the land cover classifier was given, "
                         "drawn by rule", "Derived"),
    "accuracy_points": ("vector", False, None,
                        "Stratified random accuracy sample. Classified = mapped "
                        "class, GrndTruth = class labelled by a person from the "
                        "2023 imagery (-1 = not labelled or could not tell)", "Derived"),
    "plantable": ("raster", True, (0, 3),
                  "Where a trunk could go: 0 none, 1 street right-of-way strip, "
                  "2 residential yard, 3 park or school edge. Open ground clear of "
                  "roofs, pavement, existing crowns, overhead lines and street "
                  "corners by the distances in 09_plantable.py", "Derived"),
    "runoff_m2": ("raster", True, (0, 1e9),
                  "Square metres of roof and pavement draining to within 2 m of "
                  "the cell, routed over the lidar ground surface", LIDAR_CREDIT),
    "overhead": ("raster", True, (0, 1),
                 "1 where the lidar shows wires or poles: things 4 m or taller "
                 "that are neither tree nor roof", LIDAR_CREDIT),
    "street_corners": ("vector", False, None,
                       "Street intersections, where three or more centerline "
                       "segments meet", COUNTY),
    "trees": ("vector", False, None,
              "Proposed trees. Scenario: 1 street trees, 2 streets and homes, "
              "3 full build-out; each scenario includes the lower numbers. "
              "Crown_m and Height_m are published mature sizes; Runoff_m2 is the "
              "roof and pavement draining to the spot", "Derived; mature sizes "
              "from the Arizona Municipal Water Users Association plant pages"),
}
for _n in (0, 1, 2, 3):
    LATER[f"shade_s{_n}"] = ("raster", True, (0, 1),
                             "1 where the ground is in shade at 4 p.m. on 15 July, "
                             + ("today" if _n == 0 else f"under scenario {_n}")
                             + ". Shadows cast by tree crowns and roofs, treated as solid",
                             LIDAR_CREDIT)
LATER["height_s0"] = ("raster", True, (0, 100),
                      "Height above ground of today's tree crowns and roofs; wires, "
                      "poles, cars and walls left out", LIDAR_CREDIT)
for _n in (1, 2, 3):
    LATER[f"canopy_s{_n}"] = ("raster", True, (0, 1),
                              f"Tree canopy under scenario {_n}: existing canopy "
                              "plus the mature crowns of the proposed trees",
                              "Derived")
    LATER[f"height_s{_n}"] = ("raster", True, (0, 100),
                              f"Height above ground under scenario {_n}: the lidar "
                              "heights of today's crowns and roofs with the proposed crowns added as domes",
                              LIDAR_CREDIT)
OPTIONAL = {"riparian", "protected"}        # may be absent near a site
OPTIONAL_INFO = {
    "riparian": ("vector", False, None, "Mapped riparian habitat within 1 km", COUNTY),
    "protected": ("vector", False, None, "Protected lands within 1 km", COUNTY),
}
GRID = ["dtm", "dsm", "chm", "veg_height", "roof_lidar", "intensity", "multi_return", "ndvi",
        "canopy_first", "land_cover", "plantable", "runoff_m2", "overhead",
        "canopy_s1", "canopy_s2", "canopy_s3", "height_s0", "height_s1",
        "height_s2", "height_s3", "shade_s0", "shade_s1", "shade_s2", "shade_s3"]


def check(site):
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    x0, y0, x1, y1 = work_bbox(site)
    rows = []

    def add(layer, test, ok, detail=""):
        rows.append(dict(site=site["id"], layer=layer, test=test,
                         result="PASS" if ok else "FAIL", detail=str(detail)))

    schema = dict(SCHEMA)
    for name in OPTIONAL:
        if arcpy.Exists(f"{gdb}/{name}"):
            schema[name] = OPTIONAL_INFO[name]
    for name, info in LATER.items():
        if arcpy.Exists(f"{gdb}/{name}"):
            schema[name] = info
    origins = {}
    for name, (kind, covers, rng, summary, credit) in schema.items():
        path = f"{gdb}/{name}"
        if not arcpy.Exists(path):
            add(name, "exists", False)
            continue
        add(name, "exists", True)
        desc = arcpy.Describe(path)
        add(name, "crs", desc.spatialReference.factoryCode == EPSG,
            desc.spatialReference.name)
        e = desc.extent
        if kind == "vector":
            n = int(arcpy.management.GetCount(path)[0])
            add(name, "not_empty", n > 0, f"{n} features")
            bad = sum(1 for (shp,) in arcpy.da.SearchCursor(path, ["SHAPE@"])
                      if shp is None or shp.pointCount == 0)
            add(name, "geometry", bad == 0, f"{bad} null or empty")
        else:
            r = arcpy.Raster(path)
            lo = float(arcpy.management.GetRasterProperties(path, "MINIMUM")[0])
            hi = float(arcpy.management.GetRasterProperties(path, "MAXIMUM")[0])
            add(name, "not_empty", hi >= lo, f"{r.width} x {r.height}")
            add(name, "range", rng[0] <= lo and hi <= rng[1], f"{lo:.2f} to {hi:.2f}")
            if name in GRID:
                origins[name] = (round(r.meanCellWidth, 4),
                                 round((e.XMin - x0) % CELL, 3),
                                 round((e.YMin - y0) % CELL, 3))
        if covers:
            tol = 1.0
            ok = (e.XMin <= x0 + tol and e.YMin <= y0 + tol and
                  e.XMax >= x1 - tol and e.YMax >= y1 - tol)
            add(name, "covers", ok,
                f"{e.XMin:.1f} {e.YMin:.1f} {e.XMax:.1f} {e.YMax:.1f}")
        m = md.Metadata(path)
        m.title = f"{site['name']}: {name}"
        m.summary = summary
        m.description = (f"{summary}. Part of the Tucson Neighborhood Canopy "
                         f"Scenario, site '{site['name']}' ({site['role']}). "
                         f"Coordinate system EPSG:{EPSG}, metres.")
        m.credits = credit
        m.accessConstraints = SKETCH
        m.tags = "tree canopy, lidar, land cover, Tucson, " + site["name"]
        m.save()
    if origins:
        add("analysis rasters", "grid", len(set(origins.values())) == 1,
            json.dumps(origins))

    with open(d / "qa_report.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    fails = [r for r in rows if r["result"] == "FAIL"]
    print(f"{site['id']}: {len(rows)} tests, {len(fails)} failed", flush=True)
    for r in fails:
        print("  FAIL", r["layer"], r["test"], r["detail"], flush=True)
    return not fails


def main():
    ok = all([check(s) for s in sites(sys.argv[1:])])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
