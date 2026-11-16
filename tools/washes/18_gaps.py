"""Step 10: where a repair would add the most movement.

Three kinds of gap, one for each animal, each a change to its resistance
surface and nothing else (the habitat surface is left as it is):

  bobcat      a road crossing rebuilt as an open span: where a wash meets the
              Interstate 10 corridor (freeway, ramps, frontage roads and the
              railroad together), a state route or a major road
  flycatcher  trees planted along a stretch of wash until 30% of the ground
              within 20 m is under canopy
  queen       a planted strip along a stretch where the traced channel leaves
              its wash and runs down a street or over open ground, between
              two stretches of wash

--shortlist  picks the candidates. Interstate and state route crossings are
             all kept; the rest are ranked by a first guess (how much movement
             the ground would carry if it were uniform, times the share of the
             resistance the repair takes away) and the best kept, spaced apart.
--run        reruns Omniscape around each candidate with and without the
             repair (tools/washes/julia/gaps.jl).
--score      measures, for each, the movement added through the gap, ranks
             them by species and writes tucson-washes/data/gaps.geojson and
             work/gaps/results.json.

Added movement is the change in current summed over the repair and the ground
within 50 m of it, divided by the repair's length along the wash, in units of
the mean current of a cell in the study area. Counting the 50 m either side
leaves out movement that only steps sideways onto the repaired strip.

The bobcat reruns use the coarser window step of its culvert runs (step 8c);
--run --test id,id --fine repeats chosen ones at the main run's step, and
--run --test id --every runs every window on the cut-out, to check that
skipping the windows a repair cannot reach changes nothing.

Run:  propy tools/washes/18_gaps.py --shortlist | --run [--test id,id] [--fine] [--every] | --score
"""
import importlib
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict

import arcpy
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from common import BBOX, EPSG, PROJECT, ROOT, WORK

CONN = WORK / "connectivity"
OUT = WORK / "gaps"
GDB = str(WORK / "washes.gdb")
CELL = 10
X0, Y0, X1, Y1 = BBOX
NX, NY = int((X1 - X0) / CELL), int((Y1 - Y0) / CELL)
P = json.loads((PROJECT / "resistance.json").read_text(encoding="utf-8"))

CORRIDOR = ("Interstate highway", "Interstate ramp", "Frontage road", "Railroad")
CORRIDOR_RANKS = (2, 3, 6, 7)       # railroad, frontage road, interstate ramp, interstate
STATE = ("State route", "State route ramp")
CORRIDOR_JOIN_M = 250               # crossings this close are one place on the corridor
CORRIDOR_REACH_M = 300              # how far either side the new span may run
STATE_JOIN_M = 100
POINT_REACH_M = 25                  # a single crossing: the cells within this of it
MAJOR_MIN_HA = 20                   # major-road crossings of small washes are left out
MAJOR_KEEP, MAJOR_APART_M = 20, 300
PLANT_WITHIN_CELLS = 2              # planting reaches 20 m either side of the wash line
PLANT_MIN_M, PLANT_MAX_M = 200, 800
PLANT_KEEP, PLANT_APART_M = 25, 500
LINK_WITHIN_CELLS = 1
LINK_MIN_M, LINK_MAX_M = 50, 800
LINK_KEEP, LINK_APART_M = 25, 400
JOIN_SHARE = 0.5                    # a neighbouring reach joins a stretch at this share of the seed's score
MEASURE_CELLS = 5                   # added movement is counted this far either side of the repair
PUBLISH, PUBLISH_APART_M = 5, 1500  # the page lists this many per animal, no two closer than this
LETTER = {"bobcat": "B", "flycatcher": "F", "queen": "Q"}
NOTES = PROJECT / "gaps_notes.json"  # hand-written place and action for each listed gap, by id
WEB = PROJECT / "data" / "gaps.json"


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def rc(x, y):
    return int((Y1 - y) // CELL), int((x - X0) // CELL)


def xy(r, c):
    return X0 + (c + 0.5) * CELL, Y1 - (r + 0.5) * CELL


def line_cells(pts, step=2.5):
    """Cells a line passes through, in order."""
    out, seen = [], set()
    for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
        n = max(int(np.hypot(xb - xa, yb - ya) / step), 1)
        for t in np.linspace(0, 1, n + 1):
            cell = rc(xa + t * (xb - xa), ya + t * (yb - ya))
            if cell not in seen and 0 <= cell[0] < NY and 0 <= cell[1] < NX:
                seen.add(cell)
                out.append(cell)
    return out


def grow(cells, k):
    """The cells within k cells of any of the given cells."""
    off = [(dr, dc) for dr in range(-k, k + 1) for dc in range(-k, k + 1) if dr * dr + dc * dc <= (k + 0.5) ** 2]
    out = {(r + dr, c + dc) for r, c in cells for dr, dc in off}
    return sorted((r, c) for r, c in out if 0 <= r < NY and 0 <= c < NX)


def disc(x, y, reach):
    k = int(np.ceil(reach / CELL))
    r0, c0 = rc(x, y)
    out = []
    for r in range(max(r0 - k, 0), min(r0 + k + 1, NY)):
        for c in range(max(c0 - k, 0), min(c0 + k + 1, NX)):
            cx, cy = xy(r, c)
            if (cx - x) ** 2 + (cy - y) ** 2 <= reach ** 2:
                out.append((r, c))
    return out


def take(a, cells):
    rr, cc = np.array(cells).T
    return a[rr, cc]


def groups(points, join_m):
    """Indices of points grouped by single linkage."""
    parent = list(range(len(points)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in cKDTree(points).query_pairs(join_m):
        parent[find(a)] = find(b)
    out = defaultdict(list)
    for i in range(len(points)):
        out[find(i)].append(i)
    return list(out.values())


def surfaces():
    """Each animal's resistance as it is, and with every cell repaired."""
    S = importlib.import_module("14_surfaces")
    L = dict(np.load(CONN / "layers_10m.npz"))
    made = np.load(CONN / "surfaces.npz")
    base = {sp: made[f"{sp}_resistance"].astype("float64") for sp in ("bobcat", "flycatcher", "queen")}
    src = {sp: made[f"{sp}_source"].astype("float64") for sp in base}
    planted = dict(L, canopy=np.maximum(L["canopy"], P["flycatcher"]["cover_full_at"]))
    fixed = dict(bobcat=np.minimum(base["bobcat"], P["bobcat"]["crossing"]["open_span"]),
                 flycatcher=np.minimum(S.flycatcher(planted, P["flycatcher"])[0].astype("float64"),
                                       base["flycatcher"]),
                 queen=np.minimum(base["queen"], P["queen"]["wash_or_riparian"]))
    return L, base, fixed, src


def first_guess(sp, cells, base, fixed, pot):
    rr, cc = np.array(cells).T
    return float((pot[sp][rr, cc] * (1 - fixed[sp][rr, cc] / base[sp][rr, cc])).mean())


def read_reaches():
    out = {}
    fields = ["OID@", "kind", "name", "from_node", "to_node", "drain_ha", "canopy_pct", "SHAPE@"]
    for oid, kind, name, fn, tn, ha, canopy, shape in arcpy.da.SearchCursor(f"{GDB}/reaches", fields):
        pts = [(p.X, p.Y) for part in shape for p in part if p]
        cells = line_cells(pts)
        if cells:
            out[oid] = dict(kind=kind, name=name or "", fn=fn, tn=tn, ha=ha or 0, canopy=canopy,
                            length=shape.length, cells=cells, pts=pts)
    return out


def read_crossings():
    fields = ["SHAPE@XY", "way_class", "street", "rule_type", "wash", "drain_ha", "inventory"]
    return [dict(x=r[0][0], y=r[0][1], cls=r[1], street=(r[2] or "").strip(), type=r[3],
                 wash=(r[4] or "").strip(), ha=r[5] or 0, inventory=r[6])
            for r in arcpy.da.SearchCursor(f"{GDB}/crossings", fields)]


def common_name(names):
    c = Counter(n for n in names if n)
    return c.most_common(1)[0][0] if c else ""


def spaced(cands, keep, apart_m):
    out = []
    for c in sorted(cands, key=lambda c: -c["guess"]):
        if all(np.hypot(c["x"] - o["x"], c["y"] - o["y"]) >= apart_m for o in out):
            out.append(c)
        if len(out) == keep:
            break
    return out


def corridor_span(cx, cy, L, highway_xy):
    """A straight line across the interstate corridor through (cx, cy), square to the freeway."""
    near = highway_xy[np.hypot(highway_xy[:, 0] - cx, highway_xy[:, 1] - cy) <= 600]
    if len(near) < 20:
        return None
    d = near - near.mean(axis=0)
    along = np.linalg.eigh(d.T @ d)[1][:, -1]
    across = np.array([-along[1], along[0]])
    belongs = np.isin(L["road"], CORRIDOR_RANKS)
    hits = []
    for t in np.arange(-CORRIDOR_REACH_M, CORRIDOR_REACH_M + 1, 5.0):
        r, c = rc(cx + t * across[0], cy + t * across[1])
        if 0 <= r < NY and 0 <= c < NX and belongs[r, c]:
            hits.append(t)
    if not hits:
        return None
    t0, t1 = min(hits) - 20, max(hits) + 20
    return [(cx + t * across[0], cy + t * across[1]) for t in (t0, t1)]


def bobcat_candidates(L, base, fixed, pot, crossings):
    out = []
    highway = np.argwhere(L["road"] == 7)
    highway_xy = np.array([xy(r, c) for r, c in highway])
    # the Interstate 10 corridor: one candidate where one or more washes meet it
    rows = [c for c in crossings if c["cls"] in CORRIDOR]
    for g in groups(np.array([[c["x"], c["y"]] for c in rows]), CORRIDOR_JOIN_M):
        part = [rows[i] for i in g]
        cx, cy = np.mean([c["x"] for c in part]), np.mean([c["y"] for c in part])
        span = corridor_span(cx, cy, L, highway_xy)
        if span is None:
            continue                                    # a railroad crossing away from the freeway
        cells = grow(line_cells(span), 1)
        if ((take(L["road"], cells) == 7) & (take(L["xing"], cells) == 1)).any():
            continue                                    # already under an inventoried river bridge
        out.append(dict(kind="crossing", group="interstate", cells=cells, along=len(line_cells(span)),
                        x=cx, y=cy, line=span, street="Interstate 10",
                        wash=common_name(c["wash"] for c in part), ha=max(c["ha"] for c in part),
                        now=sorted({c["type"] for c in part}), points=len(part)))
    # state routes: every crossing that is not already an open span
    rows = [c for c in crossings if c["cls"] in STATE]
    for g in groups(np.array([[c["x"], c["y"]] for c in rows]), STATE_JOIN_M):
        part = [rows[i] for i in g]
        if any(c["type"] == "open span" for c in part):
            continue
        cells = sorted({cell for c in part for cell in disc(c["x"], c["y"], POINT_REACH_M)})
        out.append(dict(kind="crossing", group="state route", cells=cells, along=2 * POINT_REACH_M // CELL,
                        x=float(np.mean([c["x"] for c in part])), y=float(np.mean([c["y"] for c in part])),
                        street=common_name(c["street"] for c in part), wash=common_name(c["wash"] for c in part),
                        ha=max(c["ha"] for c in part), now=sorted({c["type"] for c in part}), points=len(part)))
    # major roads: the best by first guess
    major = []
    for c in crossings:
        if c["cls"] == "Major local road" and c["type"] != "open span" and c["ha"] >= MAJOR_MIN_HA:
            cells = disc(c["x"], c["y"], POINT_REACH_M)
            major.append(dict(kind="crossing", group="major road", cells=cells, along=2 * POINT_REACH_M // CELL,
                              x=c["x"], y=c["y"], street=c["street"], wash=c["wash"], ha=c["ha"],
                              now=[c["type"]], points=1))
    for c in out + major:
        c["guess"] = first_guess("bobcat", c["cells"], base, fixed, pot)
        c["cost_now"] = round(float(take(base["bobcat"], c["cells"]).max()), 1)
    msg("bobcat: interstate", sum(c["group"] == "interstate" for c in out), "state route",
        sum(c["group"] == "state route" for c in out), "major roads to choose from", len(major))
    return out + spaced(major, MAJOR_KEEP, MAJOR_APART_M)


def stretch_meta(chain, reaches):
    pts = [p for o in chain for p in reaches[o]["pts"]]
    cells = [cell for o in chain for cell in reaches[o]["cells"]]
    mid = cells[len(cells) // 2]
    x, y = xy(*mid)
    return dict(x=x, y=y, lines=[reaches[o]["pts"] for o in chain], reaches=chain,
                length_m=round(sum(reaches[o]["length"] for o in chain)),
                wash=common_name(reaches[o]["name"] for o in chain),
                ha=max(reaches[o]["ha"] for o in chain))


def planting_candidates(reaches, base, fixed, pot):
    """Stretches of wash where planting would open the most ground to the flycatcher."""
    by_from, by_to = defaultdict(list), defaultdict(list)
    for o, r in reaches.items():
        by_from[r["fn"]].append(o)
        by_to[r["tn"]].append(o)
    score = {o: first_guess("flycatcher", grow(r["cells"], PLANT_WITHIN_CELLS), base, fixed, pot)
             for o, r in reaches.items() if r["kind"] == "wash"}
    used, out = set(), []
    for seed in sorted(score, key=lambda o: -score[o]):
        if seed in used or score[seed] <= 0:
            continue
        chain, length = [seed], reaches[seed]["length"]
        for nodes, end in ((by_from, "tn"), (by_to, "fn")):       # downstream, then upstream
            while length < PLANT_MAX_M:
                tip = chain[-1] if end == "tn" else chain[0]
                nxt = [o for o in nodes[reaches[tip][end]] if o in score and o not in used and o not in chain
                       and score[o] >= JOIN_SHARE * score[seed]]
                if not nxt:
                    break
                o = max(nxt, key=lambda o: score[o])
                chain = chain + [o] if end == "tn" else [o] + chain
                length += reaches[o]["length"]
        used.update(chain)
        if length < PLANT_MIN_M:
            continue
        path = [cell for o in chain for cell in reaches[o]["cells"]]
        cells = grow(path, PLANT_WITHIN_CELLS)
        c = dict(kind="planting", group="planting", cells=cells, along=len(set(path)), **stretch_meta(chain, reaches))
        c["guess"] = first_guess("flycatcher", cells, base, fixed, pot)
        c["canopy_pct"] = round(float(np.average([reaches[o]["canopy"] or 0 for o in chain],
                                                 weights=[reaches[o]["length"] for o in chain])), 1)
        out.append(c)
        if len(out) >= 400:
            break
    msg("flycatcher: stretches to choose from", len(out))
    return spaced(out, PLANT_KEEP, PLANT_APART_M)


def link_candidates(reaches, base, fixed, pot):
    """Runs of street flow or unchannelled flow path with wash at both ends."""
    by_from, by_to = defaultdict(list), defaultdict(list)
    for o, r in reaches.items():
        by_from[r["fn"]].append(o)
        by_to[r["tn"]].append(o)
    out, seen = [], set()
    for o, r in reaches.items():
        if r["kind"] == "wash" or not any(reaches[u]["kind"] == "wash" for u in by_to[r["fn"]]):
            continue
        chain, length = [o], r["length"]
        while True:
            down = by_from[reaches[chain[-1]]["tn"]]
            if not down or length > LINK_MAX_M:
                chain = None
                break
            if reaches[down[0]]["kind"] == "wash":
                break
            chain.append(down[0])
            length += reaches[down[0]]["length"]
        if not chain or length < LINK_MIN_M or tuple(chain) in seen:
            continue
        seen.add(tuple(chain))
        path = [cell for o in chain for cell in reaches[o]["cells"]]
        cells = grow(path, LINK_WITHIN_CELLS)
        c = dict(kind="link", group="link", cells=cells, along=len(set(path)), **stretch_meta(chain, reaches))
        c["guess"] = first_guess("queen", cells, base, fixed, pot)
        c["on"] = Counter(reaches[o]["kind"] for o in chain).most_common(1)[0][0]
        out.append(c)
    msg("queen: links to choose from", len(out))
    return spaced(out, LINK_KEEP, LINK_APART_M)


def shortlist():
    OUT.mkdir(exist_ok=True)
    L, base, fixed, src = surfaces()
    pot = {sp: np.load(CONN / "arrays" / f"{sp}.npz")["potential"] for sp in base}
    crossings = read_crossings()
    reaches = read_reaches()
    msg("read", len(reaches), "reaches and", len(crossings), "crossings")
    tree = cKDTree(np.array([[c["x"], c["y"]] for c in crossings]))
    cands = []
    for sp, found in (("bobcat", bobcat_candidates(L, base, fixed, pot, crossings)),
                      ("flycatcher", planting_candidates(reaches, base, fixed, pot)),
                      ("queen", link_candidates(reaches, base, fixed, pot))):
        radius = round(P[sp]["radius_m"] / CELL)
        for c in found:
            c["species"] = sp
            c["id"] = f"{sp[0]}{round(c['x'] / 10) % 100000:05d}{round(c['y'] / 10) % 100000:05d}"
            rr, cc = np.array(c["cells"]).T
            c["edge_cells"] = int(min(rr.min(), cc.min(), NY - 1 - rr.max(), NX - 1 - cc.max()))
            c["near_edge"] = bool(c["edge_cells"] < radius)
            if not c.get("street"):
                d, i = tree.query([c["x"], c["y"]])
                c["near_street"], c["near_street_m"] = crossings[i]["street"], round(float(d))
            cands.append(c)
    for c in cands:
        c["cells"] = [list(map(int, cell)) for cell in c["cells"]]
    (OUT / "candidates.json").write_text(json.dumps(cands))
    for sp in base:
        base[sp].tofile(OUT / f"{sp}_base.bin")
        fixed[sp].tofile(OUT / f"{sp}_fixed.bin")
        src[sp].tofile(OUT / f"{sp}_source.bin")
    msg("candidates:", dict(Counter((c["species"], c["group"]) for c in cands)))


def julia():
    import shutil
    exe = os.environ.get("JULIA") or shutil.which("julia")
    if not exe:
        from pathlib import Path
        found = sorted((Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Julia").glob("julia-*/bin/julia.exe"))
        exe = str(found[-1]) if found else None
    if not exe:
        raise SystemExit("Julia not found: install it, or set JULIA to julia.exe")
    return exe


def cutout(c, fine=False):
    """The part of the grid a candidate is rerun on. The bobcat's windows are large and
    slow, so its reruns step the window further (as the culvert runs in step 8c do)
    unless `fine` asks for the main run's step."""
    p = P[c["species"]]
    radius, block = round(p["radius_m"] / CELL), p["block"] if fine else p.get("variant_block", p["block"])
    pad = 2 * radius + 2 * block + 5
    rr, cc = np.array(c["cells"]).T
    return (max(rr.min() - pad, 0), min(rr.max() + pad, NY - 1), max(cc.min() - pad, 0),
            min(cc.max() + pad, NX - 1), radius, block)


def run(only=None, every=False, fine=False):
    cands = json.loads((OUT / "candidates.json").read_text())
    if only:
        cands = [c for c in cands if c["id"] in only]
    cands.sort(key=lambda c: c["species"] == "bobcat")      # the slow ones last
    lines = [f"{NY}\t{NX}"]
    for c in cands:
        r0, r1, c0, c1, radius, block = cutout(c, fine)
        tag = c["id"] + ("_every" if every else "") + ("_fine" if fine else "")
        (np.array(c["cells"], "int32") + 1).tofile(OUT / f"fp_{tag}.bin")
        lines.append("\t".join(map(str, [tag, c["species"], r0 + 1, r1 + 1, c0 + 1, c1 + 1, radius, block,
                                         int(every)])))
    (OUT / "jobs.tsv").write_text("\n".join(lines) + "\n")
    threads = str(max(1, (os.cpu_count() or 2) - 2))
    subprocess.run([julia(), f"--project={ROOT / 'tools' / 'washes' / 'julia'}", "-t", threads,
                    str(ROOT / "tools" / "washes" / "julia" / "gaps.jl"), str(OUT)], check=True)


def delta(c, fine=False):
    r0, r1, c0, c1, _, _ = cutout(c, fine)
    tag = c["id"] + ("_fine" if fine else "")
    a = np.fromfile(OUT / f"delta_{tag}.bin", "float32").reshape(r1 - r0 + 1, c1 - c0 + 1)
    return a, r0, c0


def measure(c, runs, fine=False):
    """Added movement through the gap, and normalized current on it before and after."""
    d, r0, c0 = delta(c, fine)
    A = runs[c["species"]]
    rr, cc = np.array(c["cells"]).T
    zone = np.zeros(d.shape, bool)
    zone[rr - r0, cc - c0] = True
    zone = ndimage.distance_transform_edt(~zone) <= MEASURE_CELLS + 0.5
    mean = float(A["current"].mean())
    pot = np.maximum(A["potential"][rr, cc], 1e-9)
    before = A["current"][rr, cc]
    return dict(gain=round(float(d[zone].sum()) / c["along"] / mean, 3),
                on_repair=round(float(d[rr - r0, cc - c0].sum()) / c["along"] / mean, 3),
                moved=round(float(np.abs(d).sum()) / 2 / mean, 1),
                before=round(float((before / pot).mean()), 2),
                after=round(float(((before + d[rr - r0, cc - c0]) / pot).mean()), 2))


def lonlat(points):
    sr, wgs = arcpy.SpatialReference(EPSG), arcpy.SpatialReference(4326)
    out = []
    for x, y in points:
        p = arcpy.PointGeometry(arcpy.Point(float(x), float(y)), sr).projectAs(wgs).firstPoint
        out.append([round(p.X, 6), round(p.Y, 6)])
    return out


def thin(pts, step=12.0):
    out = [pts[0]]
    for q in pts[1:-1]:
        if np.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) >= step:
            out.append(q)
    return out + [pts[-1]]


def surroundings(rows):
    """Nearest larger roads and parks around each listed gap, for writing its notes."""
    names, pts = [], []
    for name, cls, shape in arcpy.da.SearchCursor(f"{GDB}/streets", ["STREET", "ROADCAT_DS", "SHAPE@"]):
        if cls in ("Major local road", "State route", "Interstate highway") and name:
            for d in np.arange(0, shape.length, 40.0):
                q = shape.positionAlongLine(d).firstPoint
                pts.append((q.X, q.Y))
                names.append(name.strip())
    tree = cKDTree(np.array(pts))
    parks = [(n, s) for n, s in arcpy.da.SearchCursor(f"{GDB}/parks", ["NAME", "SHAPE@"])]
    sr = arcpy.SpatialReference(EPSG)
    for c in rows:
        d, i = tree.query([c["x"], c["y"]], k=400)
        seen = {}
        for dist, j in zip(d, i):
            if names[j] not in seen:
                dx, dy = pts[j][0] - c["x"], pts[j][1] - c["y"]
                seen[names[j]] = f"{round(dist)} m {'N' if dy > 0 else 'S'}{'E' if dx > 0 else 'W'}"
            if len(seen) == 3:
                break
        here = arcpy.PointGeometry(arcpy.Point(c["x"], c["y"]), sr)
        c["roads_near"] = seen
        c["parks_near"] = sorted({n for n, s in parks if s.distanceTo(here) <= 400})


def publish(rows):
    """The listed gaps for the page: the best few for each animal, spaced apart."""
    notes = json.loads(NOTES.read_text(encoding="utf-8")) if NOTES.exists() else {}
    listed = []
    for sp in LETTER:
        part = sorted((c for c in rows if c["species"] == sp), key=lambda c: -c["gain"])
        if not part:
            continue
        kept = []
        for c in part:
            if all(np.hypot(c["x"] - k["x"], c["y"] - k["y"]) >= PUBLISH_APART_M for k in kept):
                kept.append(c)
            if len(kept) == PUBLISH:
                break
        for i, c in enumerate(kept):
            c["label"] = f"{LETTER[sp]}{i + 1}"
            c["index"] = round(100 * c["gain"] / part[0]["gain"])
        listed += kept
    surroundings(listed)
    out = []
    for c in listed:
        rr, cc = np.array(c["cells"]).T
        corners = lonlat([(X0 + cc.min() * CELL - 60, Y1 - (rr.max() + 1) * CELL - 60),
                          (X0 + (cc.max() + 1) * CELL + 60, Y1 - rr.min() * CELL + 60)])
        lines = c.get("lines") or ([c["line"]] if c.get("line") else [])
        n = notes.get(c["id"], {})
        g = dict(id=c["id"], label=c["label"], species=c["species"], kind=c["kind"], group=c["group"],
                 at=lonlat([(c["x"], c["y"])])[0], box=corners[0] + corners[1],
                 lines=[lonlat(thin(l)) for l in lines], rank_of=sum(r["species"] == c["species"] for r in rows),
                 rank=c["rank"], index=c["index"], before=c["before"], after=c["after"],
                 near_edge=c["near_edge"], where=n.get("where", ""), short=n.get("short", ""), now=n.get("now", ""),
                 action=n.get("action", ""))
        if c.get("length_m"):
            g["length_m"] = c["length_m"]
        if c.get("fine"):
            g["fine"] = dict(before=c["fine"]["before"], after=c["fine"]["after"])
        out.append(g)
        print(f"{c['label']} {c['id']} idx {c['index']:3} {c['before']} -> {c['after']} "
              f"{c.get('wash') or '-'} | {c.get('street') or ''} | {c.get('now') or c.get('on') or c.get('canopy_pct')} "
              f"| {c.get('length_m', '')} | ha {round(c['ha'])} | {c['roads_near']} | {c['parks_near']}"
              f"{' | EDGE' if c['near_edge'] else ''}")
    tried = Counter((c["species"], c["group"]) for c in rows)
    fine = [(c["gain"], c["fine"]["gain"]) for c in rows if c.get("fine")]
    doc = dict(built=time.strftime("%Y-%m-%d"), measure_m=MEASURE_CELLS * CELL, apart_m=PUBLISH_APART_M,
               tried={sp: {g: n for (s, g), n in tried.items() if s == sp} for sp in LETTER},
               plant_within_m=PLANT_WITHIN_CELLS * CELL, plant_to=P["flycatcher"]["cover_full_at"],
               corridor_reach_m=CORRIDOR_REACH_M, major_min_ha=MAJOR_MIN_HA,
               bobcat_block=P["bobcat"].get("variant_block"), gaps=out)
    cats = [c for c in rows if c["species"] == "bobcat"]
    if cats:        # how the best crossing of each kind of road compares with the best of all
        top = max(c["gain"] for c in cats)
        doc["bobcat_best"] = {g: round(100 * max(c["gain"] for c in cats if c["group"] == g) / top)
                              for g in sorted({c["group"] for c in cats})}
        first = max(cats, key=lambda c: c["gain"])
        doc["bobcat_near_best"] = int(sum(
            np.hypot(c["x"] - first["x"], c["y"] - first["y"]) <= 2 * PUBLISH_APART_M
            for c in sorted(cats, key=lambda c: -c["gain"])[:6]))
    if fine:
        a, b = np.array(fine).T
        doc["fine_check"] = dict(n=len(fine), block=P["bobcat"]["block"],
                                 same_order=bool((np.argsort(-a) == np.argsort(-b)).all()),
                                 largest_change=round(float(np.abs(b / a - 1).max()), 3))
    WEB.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    msg("wrote", WEB.name, len(out), "gaps", WEB.stat().st_size, "bytes")


def score():
    cands = json.loads((OUT / "candidates.json").read_text())
    done = {l.split("\t")[0]: float(l.split("\t")[1]) for l in (OUT / "done.tsv").read_text().splitlines()}
    runs = {sp: np.load(CONN / "arrays" / f"{sp}.npz") for sp in ("bobcat", "flycatcher", "queen")}
    runs = {sp: {k: a[k] for k in ("current", "potential")} for sp, a in runs.items()}
    rows = []
    for c in cands:
        if c["id"] not in done:
            continue
        c.update(measure(c, runs), seconds=done[c["id"]])
        if c["id"] + "_fine" in done:           # the same repair at the main run's window step
            c["fine"] = measure(c, runs, fine=True)
        rows.append(c)
    for sp in runs:
        part = sorted((c for c in rows if c["species"] == sp), key=lambda c: -c["gain"])
        for i, c in enumerate(part):
            c["rank"] = i + 1
    slim = [{k: v for k, v in c.items() if k not in ("cells", "lines", "line", "reaches")} for c in rows]
    slim.sort(key=lambda c: (c["species"], c["rank"]))
    (OUT / "results.json").write_text(json.dumps(slim, indent=1))
    for c in slim:
        where = c.get("street") or f"near {c.get('near_street')}"
        print(f"{c['species'][:5]:5} {c['rank']:2} {c['id']} {c['group'][:10]:10} gain {c['gain']:7.2f} "
              f"norm {c['before']:5.2f} -> {c['after']:5.2f} guess {c['guess']:9.1f} "
              f"{'EDGE ' if c['near_edge'] else ''}{c.get('wash') or '-'} | {where} | "
              f"{c.get('length_m', '')} {c.get('now', '')} {c['seconds']}s")
    publish(rows)
    return rows


def main():
    if "--shortlist" in sys.argv:
        shortlist()
    if "--run" in sys.argv:
        i = sys.argv.index("--test") if "--test" in sys.argv else None
        only = sys.argv[i + 1].split(",") if i else None
        if only and "--every" in sys.argv:      # every window on the cut-out: checks the short cut
            run(only, every=True)
        run(only, fine="--fine" in sys.argv)
    if "--score" in sys.argv:
        score()


if __name__ == "__main__":
    main()
