"""Step 6a: draw the hand-check sample and fetch an image chip set for each item.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/washes/11_check_sample.py

Two samples, both stratified random with a fixed seed:

  crossings   PER_CROSSING_TYPE of each rule type (open span, culvert,
              at-grade); crossings typed by assumption are left out
  beds        channel reaches at least MIN_REACH_M long with enough bed in
              view, by how much of the strip looked like concrete: most of it,
              some of it, little of it. The item is the reach's midpoint.

For each item three 420 px chips come from the USGS NAIP service at its
native 0.3 m: natural colour and colour infrared close up, and natural colour
wide. Writes to work/check/:

  points.json   item ids in shuffled order, with task and position only
  key.json      what the rule said about each item. The labelling page is
                never given this file.
  chips/        <id>_rgb.jpg, <id>_cir.jpg, <id>_wide.jpg
  sample_attrs.json   each item's measures as they were when it was drawn

Once labelling has started a re-run only fetches chips that are still missing;
it never draws a new sample, which would orphan the labels.
"""
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import arcpy
import requests

from common import EPSG, USER_AGENT, WORK

SEED = 20261114
PER_CROSSING_TYPE = 60
BED_STRATA = [("most", 0.5, 1.01, 60), ("some", 0.2, 0.5, 40), ("little", 0.0, 0.2, 60)]
MIN_REACH_M = 60
SEEN_MIN = 0.3
CLOSE_M = {"x": 75, "b": 60}
WIDE_M = 300
PX = 420
NAIP = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage"
OUT = WORK / "check"


def chip(job):
    path, x, y, size, bands = job
    if path.exists():
        return True
    h = size / 2
    for i in range(6):
        try:
            r = requests.get(NAIP, params=dict(
                bbox=f"{x - h:.2f},{y - h:.2f},{x + h:.2f},{y + h:.2f}", bboxSR=EPSG, imageSR=EPSG,
                size=f"{PX},{PX}", format="jpg", bandIds=bands,
                interpolation="RSP_BilinearInterpolation", f="image"),
                headers=USER_AGENT, timeout=120)
            if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
                path.write_bytes(r.content)
                return True
        except requests.RequestException:
            pass
        time.sleep(4 * (i + 1))
    return False


REACH_FIELDS = ["drain_ha", "strahler", "county_share", "street_share", "rip_share", "canopy_pct",
                "concrete_share", "seen_share", "img_texture", "bed_rough_cm", "straightness",
                "incision_cm", "SHAPE@LENGTH", "name"]
CROSS_FIELDS = ["reach_id", "way_class", "street", "hump_m", "step_m", "drop_m", "rule_type",
                "inventory", "inv_source", "ways"]


def snapshot():
    """Freeze every sampled item's measures as they were when it was drawn.

    Later steps re-run the crossing and reach scripts, which renumbers rows.
    The scoring reads this file, so the labels stay tied to what was shown.
    """
    gdb = str(WORK / "washes.gdb")
    key = json.loads((OUT / "key.json").read_text())["items"]
    reach = {r[0]: dict(zip(REACH_FIELDS, r[1:]))
             for r in arcpy.da.SearchCursor(f"{gdb}/reaches", ["OID@"] + REACH_FIELDS)}
    cross = {r[0]: dict(zip(CROSS_FIELDS, r[1:]))
             for r in arcpy.da.SearchCursor(f"{gdb}/crossings", ["OID@"] + CROSS_FIELDS)}
    out = {}
    for pid, k in key.items():
        if k["task"] == "x":
            c = cross[k["oid"]]
            out[pid] = dict(crossing=c, reach=reach[c["reach_id"]])
        else:
            out[pid] = dict(reach=reach[k["oid"]])
    (OUT / "sample_attrs.json").write_text(json.dumps(out, indent=1))
    print("measures frozen for", len(out), "items", flush=True)


def main():
    if "--snapshot" in sys.argv:
        return snapshot()
    labels = OUT / "labels.json"
    if labels.exists() and json.loads(labels.read_text()):
        if not (OUT / "points.json").exists():
            raise SystemExit("labels exist but the sample is missing; not drawing a new one")
        # Labelling has started: only fetch chips that are still missing.
        pts = json.loads((OUT / "points.json").read_text())
        sr0, wgs0 = arcpy.SpatialReference(EPSG), arcpy.SpatialReference(4326)
        jobs = []
        for pid, it in pts["items"].items():
            q = arcpy.PointGeometry(arcpy.Point(it["lon"], it["lat"]), wgs0).projectAs(sr0).firstPoint
            close = CLOSE_M[it["task"]]
            jobs += [(OUT / "chips" / f"{pid}_rgb.jpg", q.X, q.Y, close, "0,1,2"),
                     (OUT / "chips" / f"{pid}_cir.jpg", q.X, q.Y, close, "3,0,1"),
                     (OUT / "chips" / f"{pid}_wide.jpg", q.X, q.Y, WIDE_M, "0,1,2")]
        with ThreadPoolExecutor(6) as pool:
            done = list(pool.map(chip, jobs))
        print(sum(done), "chips present;", len(done) - sum(done), "failed", flush=True)
        return
    (OUT / "chips").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    gdb = str(WORK / "washes.gdb")
    sr, wgs = arcpy.SpatialReference(EPSG), arcpy.SpatialReference(4326)
    items = []

    by_type = {}
    for oid, (x, y), rule, assumed in arcpy.da.SearchCursor(
            f"{gdb}/crossings", ["OID@", "SHAPE@XY", "rule_type", "assumed"]):
        if not assumed:
            by_type.setdefault(rule, []).append((oid, x, y))
    for rule, rows in sorted(by_type.items()):
        for oid, x, y in rng.sample(rows, min(PER_CROSSING_TYPE, len(rows))):
            items.append(dict(task="x", oid=oid, x=x, y=y, rule=rule, stratum=rule))

    beds = {s[0]: [] for s in BED_STRATA}
    for oid, geom, kind, share, seen, rule in arcpy.da.SearchCursor(
            f"{gdb}/reaches", ["OID@", "SHAPE@", "kind", "concrete_share", "seen_share", "bed_rule"]):
        if kind != "wash" or geom.length < MIN_REACH_M or (seen or 0) < SEEN_MIN:
            continue
        mid = geom.positionAlongLine(0.5, True).firstPoint
        for name, lo, hi, _ in BED_STRATA:
            if lo <= share < hi:
                beds[name].append((oid, mid.X, mid.Y, rule))
    for name, _, _, n in BED_STRATA:
        for oid, x, y, rule in rng.sample(beds[name], min(n, len(beds[name]))):
            items.append(dict(task="b", oid=oid, x=x, y=y, rule=rule, stratum=name))

    rng.shuffle(items)
    points, key, jobs = {}, {}, []
    for i, it in enumerate(items):
        pid = f"{it['task']}{rng.getrandbits(32):08x}"
        p = arcpy.PointGeometry(arcpy.Point(it["x"], it["y"]), sr).projectAs(wgs).firstPoint
        points[pid] = dict(task=it["task"], lat=round(p.Y, 6), lon=round(p.X, 6))
        key[pid] = dict(task=it["task"], oid=it["oid"], rule=it["rule"], stratum=it["stratum"])
        close = CLOSE_M[it["task"]]
        jobs += [(OUT / "chips" / f"{pid}_rgb.jpg", it["x"], it["y"], close, "0,1,2"),
                 (OUT / "chips" / f"{pid}_cir.jpg", it["x"], it["y"], close, "3,0,1"),
                 (OUT / "chips" / f"{pid}_wide.jpg", it["x"], it["y"], WIDE_M, "0,1,2")]
    (OUT / "points.json").write_text(json.dumps(dict(
        ids=list(points), items=points, close_m=CLOSE_M, wide_m=WIDE_M)))
    (OUT / "key.json").write_text(json.dumps(dict(
        seed=SEED, drawn=time.strftime("%Y-%m-%d"), items=key,
        population=dict(crossings={k: len(v) for k, v in by_type.items()},
                        beds={k: len(v) for k, v in beds.items()})), indent=1))
    print(len(items), "items;", len(jobs), "chips to fetch", flush=True)
    with ThreadPoolExecutor(6) as pool:
        done = list(pool.map(chip, jobs))
    print(sum(done), "chips fetched;", len(done) - sum(done), "failed", flush=True)
    print(json.loads((OUT / "key.json").read_text())["population"])
    snapshot()


if __name__ == "__main__":
    main()
