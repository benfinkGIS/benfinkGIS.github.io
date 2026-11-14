"""Step 10a: write what the web page reads.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/15_publish_web.py

Writes tucson-canopy/data/ (this folder is published; don't edit it by hand):
  canopy.json              every figure and table on the page, the site
                           boundaries, and the proposed trees inside them
  <site>_canopy.png        today's tree canopy
  <site>_cover.png         land cover, with low vegetation and bare ground
                           merged as open ground
  <site>_shade0..3.png     ground in shade at 4 p.m. on 15 July, today and
                           under each scenario (roofs left clear)

The images are the 0.5 m analysis rasters, cut to the neighborhood boundary,
with transparent backgrounds. The page lays them over a basemap by their
corner coordinates. They are in UTM; over a square kilometre the difference
from the web map's projection is under a metre.

Nothing here is computed: every number is copied from the JSON files the
earlier steps wrote.
"""
import json

import arcpy
import numpy as np
from PIL import Image

from common import EPSG, PROJECT, WORK, site_dir, sites, work_bbox

CELL = 0.5
OUT = PROJECT / "data"
SPECIES = json.loads((PROJECT / "species.json").read_text(encoding="utf-8"))
CARBON = json.loads((PROJECT / "carbon_factors.json").read_text(encoding="utf-8"))
CANOPY_RGB = (27, 175, 122)
COVER = {1: ("Tree canopy", (0, 131, 0)), 2: ("Roof", (98, 80, 214)),
         3: ("Pavement", (107, 107, 102)), 4: ("Open ground", (237, 161, 0)),
         6: ("Water", (42, 120, 214))}
SHADE_RGB = (16, 66, 129)
SCEN = ["Street trees", "Streets and homes", "Full build-out"]
SR = arcpy.SpatialReference(EPSG)
WGS = arcpy.SpatialReference(4326)


def to_lonlat(points):
    """UTM points to (lat, lon), six decimals."""
    if not points:
        return []
    mp = arcpy.Multipoint(arcpy.Array([arcpy.Point(x, y) for x, y in points]), SR)
    return [[round(p.Y, 6), round(p.X, 6)] for p in mp.projectAs(WGS)]


def save(index, colours, path):
    """Palette PNG: index 0 is transparent."""
    im = Image.fromarray(index.astype(np.uint8), "P")
    pal = [0, 0, 0]
    for k in range(1, 256):
        pal += list(colours.get(k, (0, 0, 0)))
    im.putpalette(pal)
    im.save(path, transparency=0, optimize=True)


def main():
    OUT.mkdir(exist_ok=True)
    acc = json.loads((WORK / "accuracy" / "accuracy.json").read_text())
    acc_first = json.loads((WORK / "accuracy" / "accuracy_first_map.json").read_text())
    heat = json.loads((WORK / "heat.json").read_text())
    doc = dict(
        species=[dict(name=s["common"], latin=s["latin"], height_ft=s["height_ft"],
                      width_ft=s["width_ft"], radius_m=s["radius_m"], water=s["water"],
                      needs_runoff=s["needs_runoff"], share=s["share"], url=s["url"],
                      colour="#%02x%02x%02x" % tuple(s["colour"])) for s in SPECIES["species"]],
        scenarios=SCEN,
        colours=dict(canopy="#%02x%02x%02x" % CANOPY_RGB, shade="#%02x%02x%02x" % SHADE_RGB,
                     cover={name: "#%02x%02x%02x" % c for name, c in COVER.values()}),
        carbon=dict(storage=CARBON["storage_kgC_per_m2"], low=CARBON["storage_city_range"][0],
                    high=CARBON["storage_city_range"][1],
                    uptake=CARBON["gross_sequestration_arizona_kgC_per_m2_yr"],
                    net=CARBON["net_share_of_gross"], url=CARBON["url"]),
        heat=dict(blocks=heat["blocks"], block_m=heat["block_m"], r2=heat["r2_within_sites"],
                  scatter=heat["residual_sd_degC"], coef=heat["coefficients_vs_open_ground"]),
        accuracy=dict(points=acc["sites"]["both sites"]["all classes"]["points"],
                      cant_tell=acc["skipped"]["cant_tell"], both={}, first_map={}),
        sites=[])
    for q in ("tree canopy or not", "impervious or not", "open ground merged", "all classes"):
        r = acc["sites"]["both sites"][q]
        doc["accuracy"]["both"][q] = dict(
            overall=r["overall_accuracy"], low=r["overall_95"][0], high=r["overall_95"][1],
            kappa=r["kappa"], users=r["users"], producers=r["producers"])
        f = acc_first["sites"]["both sites"].get(q)
        if f:
            doc["accuracy"]["first_map"][q] = f["overall_accuracy"]

    for s in sites():
        d = site_dir(s)
        gdb = str(d / f"{s['id']}.gdb")
        x0, y0, x1, y1 = work_bbox(s)
        ll = arcpy.Point(x0, y0)
        rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
        grab = lambda p: arcpy.RasterToNumPyArray(p, ll, cols, rows, nodata_to_value=0)
        inside = grab(str(d / "tmp" / "inside.tif")) > 0
        lc = grab(f"{gdb}/land_cover")

        save(np.where(inside & (lc == 1), 1, 0), {1: CANOPY_RGB}, OUT / f"{s['id']}_canopy.png")
        merged = np.where(lc == 5, 4, lc)
        save(np.where(inside, merged, 0), {k: c for k, (_, c) in COVER.items()},
             OUT / f"{s['id']}_cover.png")
        for n in range(4):
            sh = grab(f"{gdb}/shade_s{n}") == 1
            save(np.where(inside & sh & (lc != 2), 1, 0), {1: SHADE_RGB},
                 OUT / f"{s['id']}_shade{n}.png")

        gj = json.loads((d / "boundary.geojson").read_text())["features"][0]["geometry"]
        polys = gj["coordinates"] if gj["type"] == "MultiPolygon" else [gj["coordinates"]]
        boundary = [to_lonlat([tuple(p[:2]) for p in poly[0]]) for poly in polys]
        corners = to_lonlat([(x0, y0), (x1, y1)])

        names = [sp["common"] for sp in SPECIES["species"]]
        rows_t = [(shp[0], shp[1], names.index(sp), scen, fed)
                  for shp, sp, scen, fed, ok in arcpy.da.SearchCursor(
                      f"{gdb}/trees", ["SHAPE@XY", "Species", "Scenario", "RunoffFed",
                                       "InBoundary"]) if ok]
        ll_t = to_lonlat([(r[0], r[1]) for r in rows_t])
        trees = [[a, b, r[2], r[3], r[4]] for (a, b), r in zip(ll_t, rows_t)]

        land = json.loads((d / "land_cover.json").read_text())
        plant = json.loads((d / "plantable.json").read_text())
        scen = json.loads((d / "scenarios.json").read_text())
        shade = json.loads((d / "shade.json").read_text())
        carbon = json.loads((d / "carbon.json").read_text())
        check = json.loads((d / "shade_photo_check.json").read_text())
        summ = json.loads((d / "summary.json").read_text())
        a = acc["sites"][s["id"]]
        share = land["share_pct"]
        site = dict(
            id=s["id"], name=s["name"], role=s["role"], area_km2=s["area_km2"],
            bounds=corners, boundary=boundary, trees=trees,
            lidar_points_per_m2=summ["lidar"]["points_per_m2"],
            cover=dict(mapped={"Tree canopy": share["Tree canopy"], "Roof": share["Roof"],
                               "Pavement": share["Pavement"],
                               "Open ground": round(share["Low vegetation"] + share["Bare ground"], 1)},
                       corrected={k: round(v * 100, 1) for k, v in
                                  a["open ground merged"]["corrected_share"].items()
                                  if k != "Water"}),
            accuracy={q: a[q]["overall_accuracy"] for q in a},
            plantable=plant["plantable_pct"], plantable_ha=plant["plantable_ha"],
            street_edge_km=shade["street_edge_km"],
            sun=dict(azimuth=shade["sun_azimuth"], elevation=shade["sun_elevation"]),
            photo_check=dict(time=check["time"], agreement=check["agreement"]),
            lst=heat["sites"][s["id"]]["mean_lst_degC"],
            today=dict(canopy=scen["existing"]["canopy_pct"],
                       edge=shade["scenarios"]["Today"]["street edge"],
                       pavement=shade["scenarios"]["Today"]["pavement"],
                       open=shade["scenarios"]["Today"]["open ground"]),
            scenarios=[])
        for name in SCEN:
            v, sh, c = scen["scenarios"][name], shade["scenarios"][name], carbon["scenarios"][name]
            h = heat["sites"][s["id"]]["scenarios"][name]
            site["scenarios"].append(dict(
                name=name, trees=v["trees"], by_species=[v["by_species"].get(n, 0) for n in names],
                canopy=v["canopy_pct"], canopy_added_ha=v["canopy_added_ha"],
                runoff_fed=v["runoff_fed_share"],
                exposed_pavement_covered=v["exposed_pavement_covered_pct"],
                edge=sh["street edge"], edge_km=sh["street_edge_shaded_km"],
                pavement=sh["pavement"], open=sh["open ground"],
                carbon=c["stored_tC"], carbon_low=c["stored_tC_low"],
                carbon_high=c["stored_tC_high"], uptake=c["uptake_net_tC_yr"],
                lst=h["mean_change_degC"], lst_low=h["interval_95"][0],
                lst_high=h["interval_95"][1]))
        doc["sites"].append(site)
        print(s["id"], len(trees), "trees inside the boundary", flush=True)

    (OUT / "canopy.json").write_text(json.dumps(doc, separators=(",", ":")))
    total = sum(p.stat().st_size for p in OUT.iterdir())
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:34s} {p.stat().st_size / 1024:7.0f} KB")
    print(f"  total {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
