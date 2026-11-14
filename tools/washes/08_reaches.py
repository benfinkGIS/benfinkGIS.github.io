"""Step 3: describe every channel reach and write the web map's data.

Runs in ArcGIS Pro's Python (needs Spatial Analyst):

  <Pro python> tools/washes/08_reaches.py [--tag name]

A reach is one stretch of channel between two confluences, from step 2b.
Each gets:

  name          the county wash name, when at least half the reach lies
                within NEAR_M of a county wash carrying that name (further
                for the big washes, see NEAR_BIG_M)
  county_share  share of the reach within NEAR_M of any county-mapped wash
  street_share  share of the reach on street pavement (centerline buffered
                by a half-width that depends on the road class)
  kind          "street" when street_share is over half: storm water running
                down a road, not a wash. Otherwise "wash"
  canopy_pct    average share of tree canopy within 10 m, along the reach
  rip_class     the county riparian class that covers most of the reach
                (H, A, B, C or D), blank when under RIP_MIN of it is mapped
  rip_share     share of the reach inside any mapped riparian habitat
  bobcat, flycatcher, queen
                iNaturalist records within SIGHT_M whose nearest reach is
                this one (records placed to 100 m or better only)

A named wash's length is the county's own centerline inside the study area.
The lidar traces more than that (side threads in a wide bed, the last metres
of each tributary), which is kept as traced_km. Its canopy, riparian and
sighting figures are over every reach that carries its name.

It also measures the reverse: how much of the county wash network the lidar
channels find (within NEAR_M), by flow class.

Writes the reaches to the geodatabase, then tucson-washes/data/channels.geojson
(every reach, for the map) and washes.json (named washes and the figures on
the page).
"""
import argparse
import json
import time
from collections import defaultdict

import arcpy
from arcpy.sa import (Con, EucDistance, IsNull, Raster, ZonalStatisticsAsTable)

from common import BBOX, EPSG, PROJECT, SIGHTINGS, SPECIES, WORK

NEAR_M = 15
# A centerline drawn down a river bed 100 m wide can sit well away from the
# lidar's low-flow thread, so the larger county washes get a wider tolerance.
NEAR_BIG_M = {4: 30, 5: 30, 6: 60}     # by county flow class: 2,000 cfs and up; over 10,000
MIN_NAMED_KM = 0.5
SIGHT_M = 50
RIP_MIN = 0.3
RIP_CODE = {"D": 1, "C": 2, "B": 3, "A": 4, "H": 5}
STREET_HALF_WIDTH_M = {"Interstate highway": 12, "Interstate ramp": 6, "Frontage road": 7,
                       "State route": 12, "State route ramp": 6, "Major local road": 10,
                       "Minor local road": 6}
FLOW_CLASSES = ["UNDER 500 CFS", "500-1000 CFS", "1000-2000 CFS", "2000-5000 CFS",
                "5000-10000 CFS", "OVER 10000 CFS"]


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def zonal(links, value, stat, table):
    ZonalStatisticsAsTable(links, "VALUE", value, table, "DATA", stat)
    field = {"MEAN": "MEAN", "MAJORITY": "MAJORITY", "MAXIMUM": "MAX"}[stat]
    return {r[0]: (r[1], r[2]) for r in arcpy.da.SearchCursor(table, ["VALUE", "COUNT", field])}


def code_field(fc, field, mapping, source):
    arcpy.management.AddField(fc, field, "SHORT")
    with arcpy.da.UpdateCursor(fc, [source, field]) as cur:
        for row in cur:
            row[1] = mapping(row[0])
            cur.updateRow(row)


def rasters(gdb, folder):
    """Rasterise the county layers the reaches are compared with."""
    made = {}
    # Riparian class; where polygons overlap the richer class wins.
    arcpy.management.CopyFeatures(f"{gdb}/riparian", "memory/rip")
    code_field("memory/rip", "code", lambda c: RIP_CODE.get((c or "").replace("IRA-", ""), 0), "CLASS")
    arcpy.conversion.PolygonToRaster("memory/rip", "code", str(folder / "rip_code.tif"),
                                     "CELL_CENTER", "code", 1)
    made["rip"] = Con(Raster(str(folder / "rip_code.tif")) > 0, Raster(str(folder / "rip_code.tif")))

    # Street pavement.
    arcpy.management.CopyFeatures(f"{gdb}/streets", "memory/st")
    code_field("memory/st", "half", lambda c: STREET_HALF_WIDTH_M.get(c, 6), "ROADCAT_DS")
    arcpy.analysis.PairwiseBuffer("memory/st", "memory/st_buf", "half", "ALL")
    arcpy.management.AddField("memory/st_buf", "one", "SHORT")
    arcpy.management.CalculateField("memory/st_buf", "one", "1")
    arcpy.conversion.PolygonToRaster("memory/st_buf", "one", str(folder / "street.tif"),
                                     "CELL_CENTER", None, 1)
    made["street"] = Raster(str(folder / "street.tif"))

    # County washes: any, and by name.
    names = sorted({(r[0] or "").strip() for r in arcpy.da.SearchCursor(f"{gdb}/washes", ["WASHNAME"])}
                   - {"", "UNKNOWN"})
    ids = {n: i + 1 for i, n in enumerate(names)}
    arcpy.management.CopyFeatures(f"{gdb}/washes", "memory/w")
    code_field("memory/w", "name_id", lambda n: ids.get((n or "").strip(), 0), "WASHNAME")
    code_field("memory/w", "flow", lambda c: FLOW_CLASSES.index(c) + 1 if c in FLOW_CLASSES else 0,
               "CFS_SHORT2")
    code_field("memory/w", "tol", lambda f: NEAR_BIG_M.get(f, NEAR_M), "flow")
    arcpy.analysis.PairwiseBuffer("memory/w", "memory/w_any", "tol", "ALL")
    arcpy.management.AddField("memory/w_any", "one", "SHORT")
    arcpy.management.CalculateField("memory/w_any", "one", "1")
    arcpy.conversion.PolygonToRaster("memory/w_any", "one", str(folder / "county_near.tif"),
                                     "CELL_CENTER", None, 1)
    made["county"] = Raster(str(folder / "county_near.tif"))
    named = arcpy.management.MakeFeatureLayer("memory/w", "named_lyr", "name_id > 0")
    # Where two named washes meet, the one carrying more water keeps its name.
    arcpy.analysis.PairwiseBuffer(named, "memory/w_named", "tol", "NONE")
    arcpy.conversion.PolygonToRaster("memory/w_named", "name_id", str(folder / "county_name.tif"),
                                     "CELL_CENTER", "flow", 1)
    made["name"] = Raster(str(folder / "county_name.tif"))
    # County centerlines as cells, one zone per flow class, for the reverse check.
    arcpy.conversion.PolylineToRaster("memory/w", "flow", str(folder / "county_line.tif"),
                                      "MAXIMUM_LENGTH", None, 1)
    made["county_line"] = Raster(str(folder / "county_line.tif"))
    return made, {i: n for n, i in ids.items()}


def sightings(gdb):
    """Count records by nearest reach, within SIGHT_M."""
    sr = arcpy.SpatialReference(EPSG)
    wgs = arcpy.SpatialReference(4326)
    out = {}
    lyr = arcpy.management.MakeFeatureLayer(f"{gdb}/reaches", "wash_lyr", "kind = 'wash'")
    for sp in SPECIES:
        gj = json.loads((SIGHTINGS / f"{sp['id']}.geojson").read_text())
        fc = f"{gdb}/sightings_{sp['id']}"
        if arcpy.Exists(fc):
            arcpy.management.Delete(fc)
        arcpy.management.CreateFeatureclass(gdb, f"sightings_{sp['id']}", "POINT", spatial_reference=sr)
        arcpy.management.AddField(fc, "inat_id", "LONG")
        arcpy.management.AddField(fc, "obs_date", "TEXT", field_length=12)
        used = 0
        with arcpy.da.InsertCursor(fc, ["SHAPE@", "inat_id", "obs_date"]) as cur:
            for f in gj["features"]:
                acc = f["properties"].get("accuracy_m")
                if acc is not None and acc > 100:
                    continue
                x, y = f["geometry"]["coordinates"]
                p = arcpy.PointGeometry(arcpy.Point(x, y), wgs).projectAs(sr)
                if not (BBOX[0] <= p.firstPoint.X <= BBOX[2] and BBOX[1] <= p.firstPoint.Y <= BBOX[3]):
                    continue
                cur.insertRow([p, f["properties"]["id"], f["properties"].get("date") or ""])
                used += 1
        arcpy.analysis.GenerateNearTable(fc, lyr, "memory/near", f"{SIGHT_M} Meters",
                                         closest="CLOSEST")
        counts = defaultdict(int)
        for (fid,) in arcpy.da.SearchCursor("memory/near", ["NEAR_FID"]):
            counts[fid] += 1
        arcpy.management.Delete("memory/near")
        out[sp["id"]] = dict(counts=counts, used=used, near=sum(counts.values()))
    return out


def run(gdb, folder, box, web):
    sr = arcpy.SpatialReference(EPSG)
    arcpy.env.overwriteOutput = True
    arcpy.env.parallelProcessingFactor = "75%"
    arcpy.env.outputCoordinateSystem = sr
    arcpy.env.snapRaster = str(folder / "flow_acc.tif")
    arcpy.env.cellSize = 1
    arcpy.env.extent = arcpy.Extent(*box)
    links = Raster(str(folder / "stream_link.tif"))

    msg("county layers to rasters")
    ras, name_of = rasters(gdb, folder)

    msg("zonal figures along each reach")
    cells = {k: v[0] for k, v in zonal(links, links, "MAXIMUM", "memory/z_cells").items()}
    canopy = zonal(links, Raster(str(WORK / "canopy" / "canopy_share_10m.tif")), "MEAN", "memory/z_can")
    rip = zonal(links, ras["rip"], "MAJORITY", "memory/z_rip")
    street = zonal(links, ras["street"], "MAXIMUM", "memory/z_st")
    county = zonal(links, ras["county"], "MAXIMUM", "memory/z_cty")
    named = zonal(links, ras["name"], "MAJORITY", "memory/z_name")

    msg("reaches")
    fc = f"{gdb}/reaches"
    arcpy.management.CopyFeatures(f"{gdb}/channels_raw", fc)
    for name, kind, length in (("name", "TEXT", 60), ("kind", "TEXT", 8), ("rip_class", "TEXT", 2),
                               ("county_share", "FLOAT", None), ("street_share", "FLOAT", None),
                               ("rip_share", "FLOAT", None), ("canopy_pct", "FLOAT", None),
                               ("bobcat", "SHORT", None), ("flycatcher", "SHORT", None),
                               ("queen", "SHORT", None)):
        arcpy.management.AddField(fc, name, kind, field_length=length)
    code_of = {v: k for k, v in RIP_CODE.items()}
    fields = ["grid_code", "name", "kind", "rip_class", "county_share", "street_share",
              "rip_share", "canopy_pct"]
    with arcpy.da.UpdateCursor(fc, fields) as cur:
        for row in cur:
            g = row[0]
            n = max(cells.get(g, 1), 1)
            share = lambda t: round(min(t.get(g, (0, 0))[0] / n, 1.0), 3)
            row[1] = name_of[named[g][1]].title() if g in named and named[g][0] / n >= 0.5 else None
            row[5] = share(street)
            row[2] = "street" if row[5] > 0.5 else "wash"
            row[6] = share(rip)
            row[3] = code_of.get(rip[g][1]) if g in rip and row[6] >= RIP_MIN else None
            row[4] = share(county)
            row[7] = round(canopy[g][1], 1) if g in canopy else None
            cur.updateRow(row)

    msg("sightings")
    seen = sightings(gdb)
    with arcpy.da.UpdateCursor(fc, ["OID@", "bobcat", "flycatcher", "queen"]) as cur:
        for row in cur:
            for i, sp in enumerate(("bobcat", "flycatcher", "queen")):
                row[i + 1] = seen[sp]["counts"].get(row[0], 0)
            cur.updateRow(row)

    msg("how much of the county network the lidar finds")
    chan = Con(IsNull(links), 0, 1)
    dist = EucDistance(Con(chan == 1, 1), max(NEAR_BIG_M.values()))
    line = ras["county_line"]
    tol = Con(line >= 6, NEAR_BIG_M[6], Con(line >= 4, NEAR_BIG_M[4], NEAR_M))
    found = Con(IsNull(dist), 0, Con(dist <= tol, 100, 0))
    ZonalStatisticsAsTable(ras["county_line"], "VALUE", found, "memory/z_found", "DATA", "MEAN")
    completeness = {}
    tot_n = tot_f = 0
    for v, n, mean in arcpy.da.SearchCursor("memory/z_found", ["VALUE", "COUNT", "MEAN"]):
        label = FLOW_CLASSES[v - 1] if v else "flow not stated"
        completeness[label] = dict(found_pct=round(mean, 1))
        tot_n += n
        tot_f += n * mean
    completeness["all"] = dict(found_pct=round(tot_f / tot_n, 1))
    for v in completeness.values():
        v.pop("km", None)        # cell counts overstate the length of a diagonal line
    frame = arcpy.Polygon(arcpy.Array([arcpy.Point(*p) for p in (
        (box[0], box[1]), (box[0], box[3]), (box[2], box[3]), (box[2], box[1]))]), sr)
    arcpy.analysis.PairwiseClip(f"{gdb}/washes", frame, "memory/w_in")
    county_len = defaultdict(float)      # the county's own centerline length, by name
    total = 0.0
    for length, name in arcpy.da.SearchCursor("memory/w_in", ["SHAPE@LENGTH", "WASHNAME"]):
        total += length
        county_len[(name or "").strip().title()] += length
    completeness["all"]["km"] = round(total / 1000)

    msg("summaries and web files")
    export(fc, web, seen, completeness, box, county_len)


def blurb(w, avg, top_five):
    """Two to four plain sentences for a named wash's pop-up, built from its figures."""
    km, can, rip = w["km"], w["canopy_pct"], w["riparian_pct"]
    seen = w["sightings"]
    if top_five:
        out = [f"One of the five longest named washes here, at {km} km."]
    elif km >= 5:
        out = [f"A long run: {km} km through the study area."]
    elif km >= 1.5:
        out = [f"A mid-sized wash, {km} km end to end."]
    else:
        out = [f"Short: {km} km and done."]
    if can >= avg * 1.5:
        out.append(f"Leafy, with {can:.0f}% tree canopy within 10 m against {avg:.0f}% for washes overall.")
    elif can <= avg * 0.6:
        out.append(f"Thin on trees: {can:.0f}% canopy within 10 m against {avg:.0f}% for washes overall.")
    else:
        out.append(f"About average for shade, with {can:.0f}% canopy within 10 m.")
    top = max(w["classes"], key=w["classes"].get) if w["classes"] else None
    if rip >= 60 and top:
        out.append(f"The county maps {rip}% of it as riparian habitat, mostly class {top}.")
    elif rip >= 20:
        out.append(f"The county maps only {rip}% of it as riparian habitat.")
    else:
        out.append("Almost none of it is on the county's riparian map.")
    if seen["bobcat"]:
        out.append(f"iNaturalist has {seen['bobcat']} bobcat record{'s' if seen['bobcat'] != 1 else ''} beside it.")
    elif seen["flycatcher"] or seen["queen"]:
        out.append("No bobcat records beside it yet.")
    else:
        out.append("No records of the three focal species beside it yet.")
    return " ".join(out)


def export(fc, web, seen, completeness, box, county_len):
    wgs = arcpy.SpatialReference(4326)
    fields = ["SHAPE@", "name", "kind", "rip_class", "county_share", "street_share", "rip_share",
              "canopy_pct", "drain_ha", "strahler", "bobcat", "flycatcher", "queen", "SHAPE@LENGTH"]
    feats = []
    washes = defaultdict(lambda: dict(m=0.0, can=0.0, rip=defaultdict(float), ripm=0.0, ha=0.0,
                                      bobcat=0, flycatcher=0, queen=0, county_m=0.0,
                                      box=[180, 90, -180, -90]))
    tot = dict(wash_m=0.0, street_m=0.0, new_m=0.0, named_m=0.0, can=0.0, rip_m=0.0,
               new_can=0.0, links=0)
    with arcpy.da.SearchCursor(fc, fields) as cur:
        for (shape, name, kind, rc, cty, st, rs, can, ha, order, bob, fly, qn, length) in cur:
            can = can or 0.0
            tot["links"] += 1
            if kind == "street":
                tot["street_m"] += length
            else:
                tot["wash_m"] += length
                tot["can"] += can * length
                tot["rip_m"] += (rs or 0) * length
                if (cty or 0) < 0.5:
                    tot["new_m"] += length
                    tot["new_can"] += can * length
                if name:
                    tot["named_m"] += length
            geom = shape.generalize(1.5).projectAs(wgs)
            lines = [[[round(p.X, 5), round(p.Y, 5)] for p in part if p] for part in geom]
            props = dict(ha=round(ha, 1), o=order, c=round(can), k=1 if kind == "street" else 0,
                         cty=1 if (cty or 0) >= 0.5 else 0, km=round(length / 1000, 2))
            if name:
                props["n"] = name
            if rc:
                props["r"] = rc
            for key, val in (("b", bob), ("f", fly), ("q", qn)):
                if val:
                    props[key] = val
            feats.append(dict(type="Feature", properties=props, geometry=dict(
                type="LineString" if len(lines) == 1 else "MultiLineString",
                coordinates=lines[0] if len(lines) == 1 else lines)))
            if name and kind == "wash":
                w = washes[name]
                w["m"] += length
                w["can"] += can * length
                w["ripm"] += (rs or 0) * length
                if rc:
                    w["rip"][rc] += length
                w["ha"] = max(w["ha"], ha)
                w["bobcat"] += bob or 0
                w["flycatcher"] += fly or 0
                w["queen"] += qn or 0
                e = geom.extent
                w["box"] = [min(w["box"][0], e.XMin), min(w["box"][1], e.YMin),
                            max(w["box"][2], e.XMax), max(w["box"][3], e.YMax)]
    web.mkdir(parents=True, exist_ok=True)
    (web / "channels.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=feats),
                                                     separators=(",", ":")))
    rows = []
    for name, w in sorted(washes.items()):
        if w["m"] < MIN_NAMED_KM * 1000:
            continue
        rows.append(dict(
            name=name, km=round(county_len.get(name, w["m"]) / 1000, 1),
            traced_km=round(w["m"] / 1000, 1), canopy_pct=round(w["can"] / w["m"], 1),
            riparian_pct=round(100 * w["ripm"] / w["m"]),
            classes={k: round(100 * v / w["m"]) for k, v in sorted(w["rip"].items(), reverse=True)},
            drains_km2=round(w["ha"] / 100, 1),
            sightings=dict(bobcat=w["bobcat"], flycatcher=w["flycatcher"], queen=w["queen"]),
            box=[round(v, 5) for v in w["box"]]))
    avg = tot["can"] / tot["wash_m"]
    longest = sorted((r["km"] for r in rows), reverse=True)[:5]
    for r in rows:
        r["blurb"] = blurb(r, avg, r["km"] >= longest[-1])
    canopy_info = json.loads((WORK / "canopy" / "canopy.json").read_text())
    naip = json.loads((WORK / "naip" / "imagery.json").read_text())
    wgs_box = arcpy.Extent(*box, spatial_reference=arcpy.SpatialReference(EPSG)).projectAs(wgs)
    summary = dict(
        built=time.strftime("%Y-%m-%d"),
        box=[round(wgs_box.XMin, 5), round(wgs_box.YMin, 5), round(wgs_box.XMax, 5), round(wgs_box.YMax, 5)],
        area_km2=round((box[2] - box[0]) * (box[3] - box[1]) / 1e6),
        reaches=tot["links"],
        wash_km=round(tot["wash_m"] / 1000), street_km=round(tot["street_m"] / 1000),
        new_km=round(tot["new_m"] / 1000), named_km=round(tot["named_m"] / 1000),
        canopy_along_washes_pct=round(tot["can"] / tot["wash_m"], 1),
        canopy_along_new_pct=round(tot["new_can"] / max(tot["new_m"], 1), 1),
        canopy_study_area_pct=canopy_info.get("study_area_canopy_pct"),
        riparian_share_of_wash_length_pct=round(100 * tot["rip_m"] / tot["wash_m"]),
        county_found=completeness,
        sightings={k: dict(placed_to_100m=v["used"], within_50m_of_a_wash=v["near"])
                   for k, v in seen.items()},
        canopy_rule=canopy_info, imagery_dates=naip.get("acquired"),
        settings=dict(min_area_ha=2, near_m=NEAR_M, near_big_m=sorted(set(NEAR_BIG_M.values())),
                      min_named_km=MIN_NAMED_KM, sight_m=SIGHT_M, rip_min=RIP_MIN,
                      street_half_width_m=STREET_HALF_WIDTH_M),
        washes=rows)
    (web / "washes.json").write_text(json.dumps(summary, indent=1))
    msg(json.dumps({k: v for k, v in summary.items() if k not in ("washes", "canopy_rule", "settings")}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag")
    a = ap.parse_args()
    arcpy.CheckOutExtension("Spatial")
    if a.tag:
        folder = WORK / f"window_{a.tag}"
        gdb = folder / f"{a.tag}.gdb"
        box = tuple(json.loads((folder / "channels.json").read_text())["box"])
        web = folder / "web"
    else:
        folder, gdb, box, web = WORK / "dem", WORK / "washes.gdb", BBOX, PROJECT / "data"
    run(str(gdb), folder, box, web)


if __name__ == "__main__":
    main()
