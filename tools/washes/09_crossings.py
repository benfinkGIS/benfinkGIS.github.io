"""Step 4: find every place a wash meets a road or the railroad, and type it.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/washes/09_crossings.py

A crossing is where a wash reach (not street drainage) intersects a county
street centerline or the railroad. Crossings on the same reach within
MERGE_M of each other are one crossing (the two sides of a divided road).
Where the reach and the road run within ALONG_DEG of parallel the wash is
following the road, not crossing it, and the point is set aside.

Each crossing is measured on the original 1 m bare-ground lidar, before the
culvert cuts of step 2b:

  hump_m   how far the ground rises above the channel bed where the reach
           passes the road: the highest ground along the reach near the
           crossing, minus a straight line fitted through the bed from 15
           to 80 m up and down stream. A road fill over a pipe shows as a hump; a
           bridge does not, because bridge decks are not in bare ground.
  step_m   the sharpest change in ground level along the road centerline
           within STEP_REACH_M of the crossing (further on the big washes,
           whose bridges are long), over STEP_RUN_M. A road that dips through
           a wash changes level gently. Where a deck has been removed the
           centerline drops off the abutment at once.

and typed by rule:

  open span  a step no car could drive: a bridge, or a box culvert wide
             enough that the lidar survey treated it as one
  culvert    no step, and a hump of HUMP_MIN_M or more: a pipe or box under
             road fill
  at-grade   neither: the road goes through the wash bed

The county flood-map structures and the National Bridge Inventory name the
type at the crossings they cover. Those are recorded beside the rule's
answer, not used to change it, so the two can be compared.

Writes crossings to the geodatabase and work/crossings.json.
"""
import json
import math
import time
from collections import Counter, defaultdict

import arcpy
import numpy as np

from common import BBOX, EPSG, PROJECT, WORK

MERGE_M = 40
ALONG_DEG = 25
HUMP_MIN_M = 0.6
HUMP_NEAR_M = 12          # look this far past the crossing for the top of the fill
BED_FROM_M, BED_TO_M = 15, 80
BED_TRIM_M = 0.25
STEP_REACH_M = 40
STEP_RUN_M = 6
STEP_MIN_M = 1.2          # 20% over 6 m: steeper than a paved dip
INVENTORY_M = 30
# No wash crosses these at grade. Where the lidar shows neither a hump nor a
# step there (a pipe under a fill wider than the bed samples reach), the
# crossing is typed culvert and flagged as assumed.
NEVER_AT_GRADE = {"Interstate highway", "Interstate ramp", "Railroad"}
# The hand check re-chose the two cut-offs (12_check_score.py writes rules.json).
if (PROJECT / "rules.json").exists():
    _rule = json.loads((PROJECT / "rules.json").read_text())["crossing"]
    HUMP_MIN_M, STEP_MIN_M = _rule["hump_min_m"], _rule["step_min_m"]
ROAD_RANK = {"Minor local road": 1, "Major local road": 2, "Frontage road": 2,
             "State route ramp": 3, "Interstate ramp": 3, "State route": 4,
             "Railroad": 5, "Interstate highway": 6}


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Line:
    """A polyline as vertex arrays, for fast positions and measures."""

    def __init__(self, geom):
        pts = [(p.X, p.Y) for part in geom for p in part if p]
        self.xy = np.array(pts, "float64")
        seg = np.hypot(*np.diff(self.xy, axis=0).T)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])

    def at(self, s):
        s = np.clip(s, 0, self.length)
        return np.interp(s, self.cum, self.xy[:, 0]), np.interp(s, self.cum, self.xy[:, 1])

    def measure(self, x, y):
        a, b = self.xy[:-1], self.xy[1:]
        d = b - a
        den = np.maximum((d * d).sum(axis=1), 1e-9)
        t = np.clip(((x - a[:, 0]) * d[:, 0] + (y - a[:, 1]) * d[:, 1]) / den, 0, 1)
        px, py = a[:, 0] + t * d[:, 0], a[:, 1] + t * d[:, 1]
        i = int(np.argmin((px - x) ** 2 + (py - y) ** 2))
        return float(self.cum[i] + t[i] * math.sqrt(den[i]))

    def bearing(self, s, span=6):
        x0, y0 = self.at(s - span)
        x1, y1 = self.at(s + span)
        return math.degrees(math.atan2(y1 - y0, x1 - x0))


class Ground:
    def __init__(self, path):
        self.z = arcpy.RasterToNumPyArray(str(path), nodata_to_value=np.nan)
        self.x0, self.y1 = BBOX[0], BBOX[3]
        self.rows, self.cols = self.z.shape

    def low(self, x, y):
        """Lowest ground in the 3 x 3 m around each point."""
        c = np.clip(np.floor(np.atleast_1d(x) - self.x0).astype(int), 1, self.cols - 2)
        r = np.clip(np.floor(self.y1 - np.atleast_1d(y)).astype(int), 1, self.rows - 2)
        out = np.full(c.shape, np.inf)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                out = np.fmin(out, self.z[r + dr, c + dc])
        return out

    def at(self, x, y):
        c = np.clip(np.floor(np.atleast_1d(x) - self.x0).astype(int), 0, self.cols - 1)
        r = np.clip(np.floor(self.y1 - np.atleast_1d(y)).astype(int), 0, self.rows - 1)
        return self.z[r, c]


def main():
    arcpy.env.overwriteOutput = True
    gdb = str(WORK / "washes.gdb")
    sr = arcpy.SpatialReference(EPSG)

    msg("reaches, roads and their intersections")
    reach, up, down = {}, defaultdict(list), {}
    fields = ["OID@", "SHAPE@", "from_node", "to_node", "drain_ha", "name", "kind"]
    for oid, geom, fn, tn, ha, name, kind in arcpy.da.SearchCursor(f"{gdb}/reaches", fields):
        reach[oid] = dict(line=Line(geom), fn=fn, tn=tn, ha=ha, name=name, kind=kind)
    by_from = {v["fn"]: k for k, v in reach.items()}
    for k, v in reach.items():
        down[k] = by_from.get(v["tn"])
        if v["tn"] in by_from:
            up[by_from[v["tn"]]].append(k)

    arcpy.management.CopyFeatures(f"{gdb}/streets", "memory/ways")
    arcpy.management.AddField("memory/ways", "way_class", "TEXT", field_length=24)
    arcpy.management.CalculateField("memory/ways", "way_class", "!ROADCAT_DS!")
    arcpy.management.CopyFeatures(f"{gdb}/railroads", "memory/rail")
    arcpy.management.AddField("memory/rail", "way_class", "TEXT", field_length=24)
    arcpy.management.CalculateField("memory/rail", "way_class", "'Railroad'")
    arcpy.management.Append("memory/rail", "memory/ways", "NO_TEST")
    way = {}
    for oid, geom, cls, street in arcpy.da.SearchCursor("memory/ways", ["OID@", "SHAPE@", "way_class", "STREET"]):
        way[oid] = dict(line=Line(geom), cls=cls or "Minor local road", street=street or "")
    wash_lyr = arcpy.management.MakeFeatureLayer(f"{gdb}/reaches", "wash_only", "kind = 'wash'")
    arcpy.analysis.PairwiseIntersect([wash_lyr, "memory/ways"], "memory/x", "ONLY_FID", output_type="POINT")
    arcpy.management.MultipartToSinglepart("memory/x", "memory/x1")
    names = [f.name for f in arcpy.ListFields("memory/x1") if f.name.startswith("FID_")]
    raw = defaultdict(list)
    for rid, wid, (x, y) in arcpy.da.SearchCursor("memory/x1", names + ["SHAPE@XY"]):
        if not (BBOX[0] + 60 < x < BBOX[2] - 60 and BBOX[1] + 60 < y < BBOX[3] - 60):
            continue
        r, w = reach[rid]["line"], way[wid]["line"]
        m, mw = r.measure(x, y), w.measure(x, y)
        ang = abs((r.bearing(m) - w.bearing(mw) + 90) % 180 - 90)
        raw[rid].append(dict(m=m, mw=mw, wid=wid, x=x, y=y, angle=ang))
    msg(sum(len(v) for v in raw.values()), "raw intersections on", len(raw), "reaches")

    msg("reading the ground")
    ground = Ground(WORK / "dem" / "dem_1m.tif")

    def along(rid, s):
        """Point s metres along a reach, carrying on into the next reach up or down."""
        for _ in range(4):
            line = reach[rid]["line"]
            if s < 0 and up.get(rid):
                rid = max(up[rid], key=lambda k: reach[k]["ha"])
                s += reach[rid]["line"].length
            elif s > line.length and down.get(rid):
                s -= line.length
                rid = down[rid]
            else:
                break
        return reach[rid]["line"].at(s)

    def bed_line(rid, m0, m1):
        """Straight line through the channel bed either side of a crossing.

        Ground is sampled from BED_FROM_M to BED_TO_M up and down stream. A wide
        road fill can still be under some of those samples, so the line is
        fitted three times, each time dropping samples that stand more than
        BED_TRIM_M above it: what is left is bed.
        """
        offs = np.arange(BED_FROM_M, BED_TO_M + 1, 5.0)
        s = np.concatenate([m0 - offs[::-1], m1 + offs])
        z = np.array([float(ground.low(*along(rid, v))[0]) for v in s])
        ok = np.isfinite(z)
        s, z = s[ok], z[ok]
        if len(s) < 4:
            return lambda v: np.full(np.shape(v), np.nan)
        keep = np.ones(len(s), bool)
        for _ in range(3):
            b, a = np.polyfit(s[keep], z[keep], 1)
            below = z - (a + b * s) <= BED_TRIM_M
            if below.sum() < 4 or below.sum() == keep.sum():
                break
            keep = below
        return lambda v: a + b * np.asarray(v)

    msg("measuring")
    out, set_aside = [], 0
    for rid, pts in raw.items():
        pts.sort(key=lambda p: p["m"])
        groups = [[pts[0]]]
        for p in pts[1:]:
            if p["m"] - groups[-1][-1]["m"] <= MERGE_M:
                groups[-1].append(p)
            else:
                groups.append([p])
        for g in groups:
            cross = [p for p in g if p["angle"] >= ALONG_DEG]
            if not cross:
                set_aside += 1
                continue
            top = max(cross, key=lambda p: ROAD_RANK.get(way[p["wid"]]["cls"], 1))
            m0, m1 = cross[0]["m"], cross[-1]["m"]
            fit = bed_line(rid, m0, m1)
            span = np.arange(m0 - HUMP_NEAR_M, m1 + HUMP_NEAR_M + 1, 2.0)
            xs, ys = zip(*(along(rid, s) for s in span))
            profile = ground.low(np.array(xs), np.array(ys))
            hump = float(np.nanmax(profile - fit(span)))
            if not np.isfinite(hump):
                hump = 0.0
            drop = float(fit(m0 - BED_FROM_M) - fit(m1 + BED_FROM_M))
            w = way[top["wid"]]["line"]
            ha = reach[rid]["ha"]
            far = STEP_REACH_M * (5 if ha >= 1000 else 2 if ha >= 100 else 1)
            s = np.arange(top["mw"] - far, top["mw"] + far + 1, 1.0)
            s = s[(s >= 0) & (s <= w.length)]
            zr = ground.at(*w.at(s))
            step = float(np.nanmax(np.abs(zr[STEP_RUN_M:] - zr[:-STEP_RUN_M]))) if len(zr) > STEP_RUN_M else 0.0
            assumed = False
            if step >= STEP_MIN_M:
                kind = "open span"
            elif hump >= HUMP_MIN_M:
                kind = "culvert"
            elif way[top["wid"]]["cls"] in NEVER_AT_GRADE:
                kind, assumed = "culvert", True
            else:
                kind = "at-grade"
            out.append(dict(
                reach=rid, x=top["x"], y=top["y"], way=way[top["wid"]]["cls"],
                street=way[top["wid"]]["street"], ways=len(cross),
                hump_m=round(hump, 2), step_m=round(step, 2),
                drop_m=round(drop, 2), rule=kind, assumed=assumed,
                wash=reach[rid]["name"] or "", drain_ha=reach[rid]["ha"]))
    msg(len(out), "crossings;", set_aside, "set aside as running along a road")

    msg("inventories")
    arcpy.management.CreateFeatureclass(gdb, "crossings", "POINT", spatial_reference=sr)
    fc = f"{gdb}/crossings"
    spec = [("reach_id", "LONG"), ("way_class", "TEXT"), ("street", "TEXT"), ("ways", "SHORT"),
            ("hump_m", "FLOAT"), ("step_m", "FLOAT"), ("drop_m", "FLOAT"), ("rule_type", "TEXT"),
            ("assumed", "SHORT"),
            ("wash", "TEXT"), ("drain_ha", "DOUBLE"), ("inventory", "TEXT"), ("inv_source", "TEXT")]
    for name, kind in spec:
        arcpy.management.AddField(fc, name, kind, field_length=60 if kind == "TEXT" else None)
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY", "reach_id", "way_class", "street", "ways", "hump_m",
                                    "step_m", "drop_m", "rule_type", "assumed", "wash", "drain_ha"]) as cur:
        for c in out:
            cur.insertRow([(c["x"], c["y"]), c["reach"], c["way"], c["street"], c["ways"], c["hump_m"],
                           c["step_m"], c["drop_m"], c["rule"], int(c["assumed"]), c["wash"], c["drain_ha"]])

    # What the inventories call the nearest structure, if one is within reach.
    arcpy.management.CopyFeatures(f"{gdb}/structures", "memory/fm")
    arcpy.management.CopyFeatures(f"{gdb}/bridges_nbi", "memory/nbi")
    near = {}
    arcpy.analysis.GenerateNearTable(fc, "memory/nbi", "memory/n1", f"{INVENTORY_M} Meters", closest="CLOSEST")
    nbi = {r[0]: r[1:] for r in arcpy.da.SearchCursor(
        "memory/nbi", ["OID@", "STRUCTURE_TYPE_043B", "STRUCTURE_LEN_MT_049", "SERVICE_UND_042B"])}
    for cid, nid in arcpy.da.SearchCursor("memory/n1", ["IN_FID", "NEAR_FID"]):
        typ, length, under = nbi[nid]
        if str(under) in ("5", "6", "7", "8", "9", "0"):       # over a waterway (or mixed, or other)
            near[cid] = ("culvert" if str(typ) == "19" else "bridge", "National Bridge Inventory")
    arcpy.analysis.GenerateNearTable(fc, "memory/fm", "memory/n2", f"{INVENTORY_M} Meters", closest="CLOSEST")
    fm = {r[0]: (r[1] or "").upper() for r in arcpy.da.SearchCursor("memory/fm", ["OID@", "STRUCT_TYP"])}
    for cid, sid in arcpy.da.SearchCursor("memory/n2", ["IN_FID", "NEAR_FID"]):
        t = fm[sid]
        kind = "bridge" if "BRIDGE" in t else "culvert" if "CULVERT" in t else None
        if kind and cid not in near:
            near[cid] = (kind, "county flood map")
    agree = Counter()
    with arcpy.da.UpdateCursor(fc, ["OID@", "rule_type", "inventory", "inv_source"]) as cur:
        for row in cur:
            if row[0] in near:
                row[2], row[3] = near[row[0]]
                agree[(row[2], row[1])] += 1
                cur.updateRow(row)

    stats = dict(
        crossings=len(out), set_aside_along_road=set_aside,
        assumed_culverts=sum(c["assumed"] for c in out),
        by_rule=dict(Counter(c["rule"] for c in out)),
        by_way=dict(Counter(c["way"] for c in out)),
        rule_by_way={w: dict(Counter(c["rule"] for c in out if c["way"] == w))
                     for w in sorted({c["way"] for c in out})},
        inventory_vs_rule={f"{inv} in inventory, rule says {rule}": n for (inv, rule), n in sorted(agree.items())},
        settings=dict(merge_m=MERGE_M, along_deg=ALONG_DEG, hump_min_m=HUMP_MIN_M,
                      step_min_m=STEP_MIN_M, step_run_m=STEP_RUN_M, inventory_m=INVENTORY_M))
    (WORK / "crossings.json").write_text(json.dumps(stats, indent=2))
    msg(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
