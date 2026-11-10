#!/usr/bin/env python3
"""DRAFT: assemble the full extent of The Loop (Chuck Huckelberry Loop) from OpenStreetMap
and write the layers the review map in tools/loop-review/ shows.

Usage (from the repo root):
    py tools/build_loop.py             # query Overpass (responses are cached), write the GeoJSON
    py tools/build_loop.py --refresh   # ignore the cache and query again

Needs Python 3 and shapely (pip install shapely).

Why this exists
---------------
OpenStreetMap's route relation "The Loop" covers only about 78 of the Loop's roughly
137 miles. The rest is mapped, but under other routes, under section names, or with
no name at all. This script pulls the pieces together by rule, so every piece on the
review map says which rule put it there:

    route_loop        member of relation "The Loop" (or its Santa Cruz River Park sub-route)
    route_cdo         member of relation "Canada del Oro"
    named             bike path carrying a Loop section name (SECTION_NAMES) but in no Loop route
    santa_cruz_south  unnamed cycleway inside SANTA_CRUZ_SOUTH_BOX (both banks, about Ajo to Valencia)
    gap_fill          unnamed cycleway pieces, at most GAP_FILL_MAX_MI long, that join two
                      parts of the above

The last two are this project's guesses, not OSM labels. Check them on the imagery.

It also writes two sets of points:
    connections   every OSM node the draft Loop shares with a street or path that is not
                  part of it (a possible entrance)
    separated     every place the draft Loop crosses a road without sharing a node
                  (an underpass or overpass: not an entrance)

Data: (c) OpenStreetMap contributors, ODbL. https://www.openstreetmap.org/copyright
"""
import argparse
import collections
import hashlib
import json
import math
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import LineString
from shapely.strtree import STRtree

# ---- study area and rules ----------------------------------------------------
BBOX = "32.0,-111.35,32.55,-110.65"          # south,west,north,east: Tucson metro incl. Marana, Oro Valley, Vail
REL_LOOP = 3113036                           # route relation "The Loop" (incomplete)
REL_CDO = 9728113                            # route relation "Canada del Oro"
SECTION_NAMES = {
    "The Loop", "The Loop (scenic)", "The Loop (spur)",
    "Santa Cruz River Path", "Santa Cruz River Pedestrian Bridge",
    "Julian Wash Greenway", "Julian Wash Greenway Path",
    "Tucson Diversion Channel Greenway",
    "Rillito River Path", "Rillito Connector",
    "Harrison Greenway Path",
}
SANTA_CRUZ_SOUTH_BOX = (32.130, -110.998, 32.195, -110.984)   # south, west, north, east
GAP_FILL_MAX_MI = 1.5
GAP_FILL_MIN_SPAN_M = 150                    # the two ends a gap-filler joins must be this far apart
NEAR_M = 250                                 # roads this close to a Loop node are tested for crossings
CLUSTER_M = 80                               # crossings of one divided road closer than this are merged

ROAD = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"}
PATHLIKE = {"cycleway", "footway", "path", "pedestrian", "steps", "track", "bridleway"}
ROAD_RE = "^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street)(_link)?$"

OVERPASS = [                                  # tried in this order; a server that answers moves to the front
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",   # worldwide data, but can lag the others by weeks
]
UA = "finkgeo-loop-map/0.1 (personal project; https://finkgeo.com)"
OUT_DIR = Path(__file__).resolve().parent / "loop-review"


# ---- Overpass ------------------------------------------------------------------
def overpass(query, cache_dir, refresh):
    """POST a query, trying each server in turn with backoff. Responses are cached by query text."""
    key = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    cached = cache_dir / (key + ".json")
    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last = None
    for attempt in range(5):
        for url in list(OVERPASS):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=240) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if data.get("remark"):
                    raise RuntimeError("Overpass remark: " + data["remark"])
                cached.write_text(json.dumps(data), encoding="utf-8")
                OVERPASS.remove(url)                    # ask the server that worked first next time
                OVERPASS.insert(0, url)
                return data
            except Exception as e:                      # 502/504/timeouts are routine on public servers
                last = e
                print("  %s: %s" % (url.split("/")[2], e), file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    raise SystemExit("Overpass failed on every server: %s" % last)


# ---- geometry helpers ------------------------------------------------------------
def hav(a, b):
    """Metres between two (lon, lat) points."""
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(x))


def coords(w):
    return [(p["lon"], p["lat"]) for p in w["geometry"]]


def miles(w):
    c = coords(w)
    return sum(hav(c[i], c[i + 1]) for i in range(len(c) - 1)) / 1609.344


def hw_class(hw):
    hw = (hw or "").replace("_link", "")
    if hw in ROAD:
        return "road"
    if hw == "service":
        return "service"
    if hw in PATHLIKE:
        return "path"
    return "other"


def rnd(c):
    return [round(c[0], 6), round(c[1], 6)]


# ---- assemble the draft Loop -------------------------------------------------------
def assemble(loop_ways, cdo_ids, paths):
    sel = {}                                                    # way id -> (tier, way)
    for i, w in loop_ways.items():
        sel[i] = ("route_loop", w)
    for i in cdo_ids:
        if i in paths and i not in sel:
            sel[i] = ("route_cdo", paths[i])
    for i, w in paths.items():
        if i not in sel and w.get("tags", {}).get("name") in SECTION_NAMES:
            sel[i] = ("named", w)
    s, wst, n, e = SANTA_CRUZ_SOUTH_BOX
    for i, w in paths.items():
        if i in sel or w["tags"].get("highway") != "cycleway":
            continue
        c = coords(w)[len(w["geometry"]) // 2]
        if s <= c[1] <= n and wst <= c[0] <= e:
            sel[i] = ("santa_cruz_south", w)

    def gap_fill_pass():
        selnodes = {nd for _, w in sel.values() for nd in w["nodes"]}
        cand = {i: w for i, w in paths.items()
                if i not in sel and w["tags"].get("highway") == "cycleway" and not w["tags"].get("name")}
        by_node = collections.defaultdict(list)
        for i, w in cand.items():
            for nd in w["nodes"]:
                by_node[nd].append(i)
        seen, added = set(), 0
        for i in cand:
            if i in seen:
                continue
            comp, stack = [], [i]
            seen.add(i)
            while stack:                                        # connected run of unnamed cycleways
                j = stack.pop()
                comp.append(j)
                for nd in cand[j]["nodes"]:
                    for k in by_node[nd]:
                        if k not in seen:
                            seen.add(k)
                            stack.append(k)
            if sum(miles(cand[j]) for j in comp) > GAP_FILL_MAX_MI:
                continue
            touch = {}
            for j in comp:
                for nd, c in zip(cand[j]["nodes"], coords(cand[j])):
                    if nd in selnodes:
                        touch[nd] = c
            pts = list(touch.values())
            if len(pts) >= 2 and max(hav(a, b) for a in pts for b in pts) > GAP_FILL_MIN_SPAN_M:
                for j in comp:
                    sel[j] = ("gap_fill", cand[j])
                added += len(comp)
        return added

    while gap_fill_pass():
        pass
    return sel


# ---- connections and grade-separated crossings ----------------------------------------
def connections(sel, near):
    node_xy, node_loopways = {}, collections.defaultdict(list)
    for _, w in sel.values():
        for nd, c in zip(w["nodes"], coords(w)):
            node_xy[nd] = c
            node_loopways[nd].append(w)
    touching = collections.defaultdict(list)
    for i, w in near.items():
        if i in sel or not w.get("tags", {}).get("highway"):
            continue
        for nd in set(w["nodes"]):
            if nd in node_xy:
                touching[nd].append(w)
    feats = []
    for nd, ws in touching.items():
        classes = {hw_class(w["tags"]["highway"]) for w in ws}
        kind = next(k for k in ("road", "service", "path", "other") if k in classes)
        # where the Loop itself runs on a street, every side street "connects": flag those apart
        on_street = all(hw_class(w.get("tags", {}).get("highway")) in ("road", "service") for w in node_loopways[nd])
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": rnd(node_xy[nd])},
                      "properties": {"layer": "connection", "kind": "on_street" if on_street else kind,
                                     "node": nd,
                                     "names": sorted({w["tags"]["name"] for w in ws if w["tags"].get("name")}),
                                     "types": sorted({w["tags"]["highway"] for w in ws})}})
    return feats


def separated(sel, near):
    roads = [w for i, w in near.items() if i not in sel and hw_class(w.get("tags", {}).get("highway")) == "road"]
    lines = [LineString(coords(w)) for w in roads]
    tree = STRtree(lines)
    hits = []
    for _, w in sel.values():
        lg, wn, wt = LineString(coords(w)), set(w["nodes"]), w.get("tags", {})
        for k in tree.query(lg):
            r, rg = roads[int(k)], lines[int(k)]
            if not lg.intersects(rg) or wn & set(r["nodes"]):
                continue
            rt = r["tags"]
            if rt.get("bridge"):
                how = "road on bridge"
            elif wt.get("tunnel"):
                how = "path in tunnel"
            elif wt.get("bridge"):
                how = "path on bridge"
            elif rt.get("tunnel"):
                how = "road in tunnel"
            else:
                how = "NOT TAGGED"                              # missing connection or untagged underpass
            pt = lg.intersection(rg).representative_point()
            hits.append(((pt.x, pt.y), rt.get("name") or "(unnamed road)", how))
    clusters = []                                               # merge the carriageways of one road
    for xy, name, how in hits:
        for c in clusters:
            if hav(c["xy"], xy) < CLUSTER_M:
                c["names"].add(name)
                c["how"].add(how)
                c["n"] += 1
                break
        else:
            clusters.append({"xy": xy, "names": {name}, "how": {how}, "n": 1})
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": rnd(c["xy"])},
              "properties": {"layer": "separated", "kind": "untagged" if "NOT TAGGED" in c["how"] else "separated",
                             "names": sorted(c["names"]), "how": sorted(c["how"]), "pairs": c["n"]}}
             for c in clusters]
    return feats, len(hits)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="ignore cached Overpass responses")
    ap.add_argument("--cache-dir", default=str(Path(tempfile.gettempdir()) / "finkgeo_loop_cache"))
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    print("1/4 Loop route members")
    d = overpass("[out:json][timeout:120];rel(%d)->.r1;rel(r.r1)->.r2;(way(r.r1);way(r.r2););out geom;" % REL_LOOP,
                 cache, args.refresh)
    loop_ways = {w["id"]: w for w in d["elements"] if w["type"] == "way"}
    print("2/4 Canada del Oro route members")
    d = overpass("[out:json][timeout:60];rel(%d);way(r);out ids;" % REL_CDO, cache, args.refresh)
    cdo_ids = {w["id"] for w in d["elements"] if w["type"] == "way"}
    print("3/4 bike paths in the study area")
    d = overpass('[out:json][timeout:180];(way[highway=cycleway](%s);'
                 'way[highway~"^(path|footway)$"][bicycle~"^(designated|yes)$"](%s););out geom;' % (BBOX, BBOX),
                 cache, args.refresh)
    paths = {w["id"]: w for w in d["elements"] if w["type"] == "way"}
    if not loop_ways or not cdo_ids or not paths:
        raise SystemExit("A query came back empty; not writing anything.")

    sel = assemble(loop_ways, cdo_ids, paths)

    print("4/4 streets and paths touching or crossing the draft Loop")
    # `around` on a set of ways returned nothing on the public servers, so go through the ways' nodes.
    d = overpass('[out:json][timeout:240];way(id:%s)->.loop;node(w.loop)->.ln;'
                 '(way(bn.ln)[highway];way(around.ln:%d)[highway~"%s"];);out geom;'
                 % (",".join(str(i) for i in sorted(sel)), NEAR_M, ROAD_RE), cache, args.refresh)
    near = {w["id"]: w for w in d["elements"] if w["type"] == "way"}

    conn = connections(sel, near)
    sep, sep_pairs = separated(sel, near)

    # tools/build_network.py reads this so the Loop and the streets touching it are always in the
    # network exactly as mapped here, even if its own street download is older or has holes.
    patch = {i: w for i, w in near.items()}
    patch.update({i: w for i, (_, w) in sel.items()})
    (cache / "loop_network_patch.json").write_text(json.dumps(
        [{"id": i, "nodes": w["nodes"], "geometry": w["geometry"], "tags": w.get("tags", {})} for i, w in patch.items()]),
        encoding="utf-8")

    tier_mi, tier_n = collections.Counter(), collections.Counter()
    lines = []
    for i, (tier, w) in sorted(sel.items()):
        t, mi = w.get("tags", {}), miles(w)
        tier_mi[tier] += mi
        tier_n[tier] += 1
        lines.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [rnd(c) for c in coords(w)]},
                      "properties": {"way": i, "tier": tier, "name": t.get("name"), "highway": t.get("highway"),
                                     "surface": t.get("surface"), "bridge": t.get("bridge"), "tunnel": t.get("tunnel"),
                                     "miles": round(mi, 3)}})
    others = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [rnd(c) for c in coords(w)]},
               "properties": {"way": i, "name": w["tags"].get("name"), "surface": w["tags"].get("surface"),
                              "miles": round(miles(w), 3)}}
              for i, w in sorted(paths.items()) if i not in sel and w["tags"].get("highway") == "cycleway"]

    meta = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "status": "DRAFT for review; the santa_cruz_south and gap_fill tiers are guesses",
            "miles_total": round(sum(tier_mi.values()), 1),
            "tiers": {k: {"ways": tier_n[k], "miles": round(tier_mi[k], 1)} for k in tier_mi},
            "connections": dict(collections.Counter(f["properties"]["kind"] for f in conn)),
            "separated_crossings": len([f for f in sep if f["properties"]["kind"] == "separated"]),
            "separated_pairs": sep_pairs,
            "untagged_crossings": len([f for f in sep if f["properties"]["kind"] == "untagged"]),
            "attribution": "(c) OpenStreetMap contributors, ODbL"}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, feats in (("loop_draft", lines), ("other_paths", others), ("points", conn + sep)):
        fc = {"type": "FeatureCollection", "metadata": meta, "features": feats}
        (OUT_DIR / (name + ".geojson")).write_text(json.dumps(fc, separators=(",", ":"), ensure_ascii=False),
                                                   encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
