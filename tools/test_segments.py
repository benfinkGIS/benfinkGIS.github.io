#!/usr/bin/env python3
"""DRAFT: what would a new Loop segment do? Counts the residents each candidate segment would
bring within reach of the Loop, for the closer-vs-farther page (tools/loop-review/access.html).

Usage (from the repo root, after build_loop.py, build_network.py and build_access.py):
    py tools/test_segments.py                         # screen washes and existing paths
    py tools/test_segments.py --geojson my_lines.geojson   # also test your own lines
                                                           # (LineString features with a "name")

Candidates
----------
wash           every named waterway in OpenStreetMap inside the study area, minus the parts that
               already have the Loop within LOOP_NEAR_M. The Loop is built along washes, so these
               are the obvious corridors. A wash with several separate new parts gives one
               candidate per part.
existing path  every named paved bike path in OpenStreetMap that is not part of the draft Loop
               and is at least MIN_PATH_MI long: what if it were joined to the Loop system?
custom         lines passed with --geojson.

How a candidate is scored
-------------------------
The candidate is treated as if it were Loop. An existing path is entered at its real junctions.
A wash or custom line does not exist yet, so it is entered from any public street or path
within ACCESS_M of it. That is generous: a real path would have fewer entrances, and some
washes have no room for a path at all. Read the results as a screen for where to look, not as
proposals. Ride times are the same unweighted baseline as the rest of the draft.

Writes tools/loop-review/segments.json.
"""
import argparse
import collections
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import LineString, box, shape
from shapely.ops import linemerge, unary_union

from build_loop import OVERPASS, overpass
from build_network import M_LAT, M_LON, SPEED_MPH, STUDY_BBOX, prepare_search, private_pass

THRESHOLDS = (10, 15, 20, 30)      # minutes, as on the page
ACCESS_M = 75                      # a path that does not exist yet can be joined from streets this close
LOOP_NEAR_M = 150                  # parts of a wash this close to the Loop already have it
CONNECT_M = 200                    # a candidate this close to the Loop counts as connecting to it
MIN_NEW_MI = 1.5                   # shortest wash part worth testing
MIN_PATH_MI = 2.0                  # shortest existing path worth testing
SAMPLE_M = 25                      # spacing of the points used to find streets near a line
SEARCH_LIMIT_MIN = 35              # no need to search past the longest threshold
KEEP = 40                          # candidates written to the page's data file
TOP_SINGLES = 8                    # the page ranks this many candidates; they are also tested all at once
PACKAGE_STEPS = 8                  # how many candidates the combined build-out adds
MIN_STEP_GAIN = 500                # ...stopping early once the next one helps fewer residents than this
MIN_STEP_GAIN_PER_MILE = 2000      # the per-mile build-out skips anything adding fewer residents than this,
                                   # so a short path past a few homes cannot win on its ratio alone
OUT_DIR = Path(__file__).resolve().parent / "loop-review"
MI = 1609.344


def to_m(coords):
    return [(c[0] * M_LON, c[1] * M_LAT) for c in coords]


def lines_of(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "LineString"]


def side_name(part, whole):
    dx, dy = part.centroid.x - whole.centroid.x, part.centroid.y - whole.centroid.y
    return ("east" if dx > 0 else "west") if abs(dx) > abs(dy) else ("north" if dy > 0 else "south")


def out_lines(geom):
    return [[[round(x / M_LON, 5), round(y / M_LAT, 5)] for x, y in ln.coords] for ln in lines_of(geom.simplify(15))]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="download the waterways again")
    ap.add_argument("--cache-dir", default=str(Path(tempfile.gettempdir()) / "finkgeo_loop_cache"))
    ap.add_argument("--server", help="Overpass interpreter URL to try first")
    ap.add_argument("--geojson", help="extra candidate lines to test (LineString features with a name)")
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    if args.server:
        if args.server in OVERPASS:
            OVERPASS.remove(args.server)
        OVERPASS.insert(0, args.server)

    # ---- the network, the residents on it, and today's times ----
    z = np.load(cache / "network.npz")
    g = {k: z[k] for k in ("lon", "lat", "u", "v", "m", "min", "cls", "dir", "way", "priv")}
    prep = prepare_search(g)
    t_pub0 = z["minutes_public_only"]
    bnode, bpop = z["block_node"], z["block_pop"]
    leg = z["block_snap_m"] / MI / SPEED_MPH["bike"] * 60
    base = z["minutes_to_loop"][bnode] + leg
    base_far = {str(t): int(bpop[base > t].sum()) for t in THRESHOLDS}
    public_nodes = np.flatnonzero(prep["has_public"])
    tree = cKDTree(np.column_stack([g["lon"][public_nodes] * M_LON, g["lat"][public_nodes] * M_LAT]))

    def score(sources):
        """For each limit, which blocks the candidate brings within it (True/False per block).
        Times with several candidates are the smallest of their separate times, so the blocks a
        set of candidates brings within reach are exactly the union of these."""
        t = dijkstra(prep["public"], directed=True, indices=sources, min_only=True, limit=SEARCH_LIMIT_MIN)
        new = private_pass(prep, np.minimum(t_pub0, t))[bnode] + leg
        return {T: (base > T) & (new <= T) for T in THRESHOLDS}

    def near_nodes(geom):
        pts = []
        for ln in lines_of(geom):
            k = max(2, int(ln.length / SAMPLE_M) + 1)
            pts += [ln.interpolate(i / (k - 1), normalized=True).coords[0] for i in range(k)]
        hits = tree.query_ball_point(np.array(pts), ACCESS_M)
        return np.unique(public_nodes[np.fromiter((j for h in hits for j in h), dtype=np.int64)]) if pts else np.array([], dtype=np.int64)

    loop = json.loads((OUT_DIR / "loop_draft.geojson").read_text(encoding="utf-8"))
    loop_geom = unary_union([LineString(to_m(f["geometry"]["coordinates"])) for f in loop["features"]])
    loop_buf = loop_geom.buffer(LOOP_NEAR_M)
    s, w, n, e = STUDY_BBOX
    study = box(w * M_LON, s * M_LAT, e * M_LON, n * M_LAT)
    cands = []                                                     # (name, kind, geometry in metres, source nodes)

    # ---- washes ----
    d = overpass('[out:json][timeout:180];way[waterway~"^(river|stream|wash|canal|drain|ditch)$"][name](%s,%s,%s,%s);out geom;'
                 % STUDY_BBOX, cache, args.refresh)
    by_name = collections.defaultdict(list)
    for el in d["elements"]:
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) if p]
        if el["type"] == "way" and len(pts) >= 2:
            by_name[el["tags"]["name"]].append(LineString(to_m(pts)))
    for name, lines in sorted(by_name.items()):
        whole = unary_union(lines).intersection(study)
        new = whole.difference(loop_buf)
        merged = linemerge(new) if new.geom_type == "MultiLineString" else new
        parts = [ln for ln in lines_of(merged) if ln.length > 0]
        groups = []                                                # pieces within 300 m of each other are one part
        for ln in parts:
            for grp in groups:
                if any(ln.distance(o) < 300 for o in grp):
                    grp.append(ln)
                    break
            else:
                groups.append([ln])
        groups = [unary_union(grp) for grp in groups]
        groups = [grp for grp in groups if grp.length / MI >= MIN_NEW_MI]
        for grp in groups:
            label = name if len(groups) == 1 else "%s, %s part" % (name, side_name(grp, whole))
            cands.append((label, "wash", grp, near_nodes(grp)))

    # ---- existing paved paths that are not part of the Loop ----
    others = json.loads((OUT_DIR / "other_paths.geojson").read_text(encoding="utf-8"))["features"]
    paths = collections.defaultdict(list)
    for f in others:
        if f["properties"].get("name"):
            paths[f["properties"]["name"]].append(f)
    for name, fs in sorted(paths.items()):
        if sum(f["properties"]["miles"] for f in fs) < MIN_PATH_MI:
            continue
        on = np.isin(g["way"], [f["properties"]["way"] for f in fs]) & ~g["priv"]
        nodes = np.unique(np.concatenate([g["u"][on], g["v"][on]]))
        geom = unary_union([LineString(to_m(f["geometry"]["coordinates"])) for f in fs])
        cands.append((name, "existing path", geom, nodes))

    # ---- your own lines ----
    if args.geojson:
        for f in json.loads(Path(args.geojson).read_text(encoding="utf-8"))["features"]:
            geom = shape(f["geometry"])
            geom = unary_union([LineString(to_m(ln.coords)) for ln in lines_of(geom)])
            cands.append(((f.get("properties") or {}).get("name") or "Custom line", "custom", geom, near_nodes(geom)))

    # ---- score ----
    rows = []
    for name, kind, geom, nodes in cands:
        if len(nodes) < 2:
            continue
        cover = score(nodes)
        gained = {str(T): int(bpop[cover[T]].sum()) for T in THRESHOLDS}
        miles = geom.length / MI
        rows.append({"name": name, "kind": kind, "miles": round(miles, 1), "entrances": int(len(nodes)), "_cover": cover,
                     "connects_to_loop": bool(geom.distance(loop_geom) <= CONNECT_M),
                     "gained": gained, "gained_per_mile": {k: int(round(v / miles)) for k, v in gained.items()},
                     "lines": out_lines(geom)})
    rows.sort(key=lambda r: -r["gained"]["20"])

    # ---- built together: add candidates one at a time, counting overlap once. Two ways to choose:
    #        residents  the candidate that helps the most residents not already helped
    #        per_mile   the candidate that helps the most such residents per mile of NEW path.
    #                   An existing path needs no new path, so it goes first whenever it clears
    #                   the minimum. ----
    def build_out(T, per_mile):
        covered = np.zeros(len(bpop), dtype=bool)
        chosen, steps, total, miles, new_miles = [], [], 0, 0.0, 0.0
        floor = MIN_STEP_GAIN_PER_MILE if per_mile else MIN_STEP_GAIN
        for _ in range(PACKAGE_STEPS):
            best = None
            for i, r in enumerate(rows):
                if i in chosen or r["gained"][str(T)] == 0:
                    continue
                add = int(bpop[r["_cover"][T] & ~covered].sum())
                if add < floor:
                    continue
                cost = 0.0 if r["kind"] == "existing path" else r["miles"]
                rank = (add / cost if cost else math.inf, add) if per_mile else (add, 0)
                if best is None or rank > best[0]:
                    best = (rank, i, add, cost)
            if best is None:
                break
            _, i, add, cost = best
            chosen.append(i)
            covered |= rows[i]["_cover"][T]
            total, miles, new_miles = total + add, miles + rows[i]["miles"], new_miles + cost
            steps.append({"row": i, "added": add, "total": total, "miles_total": round(miles, 1),
                          "new_miles_total": round(new_miles, 1), "per_new_mile": int(round(add / cost)) if cost else None})
        return steps

    packages = {mode: {str(T): build_out(T, mode == "per_mile") for T in THRESHOLDS} for mode in ("per_mile", "residents")}

    # ---- the top-ranked singles, all built at once: how much of their separate totals is overlap? ----
    together, tops = {}, set()
    for T in THRESHOLDS:
        idx = [i for i in sorted(range(len(rows)), key=lambda i: -rows[i]["gained"][str(T)])[:TOP_SINGLES]
               if rows[i]["gained"][str(T)] > 0]
        tops.update(idx)
        union = np.zeros(len(bpop), dtype=bool)
        for i in idx:
            union |= rows[i]["_cover"][T]
        together[str(T)] = {"segments": len(idx), "miles": round(sum(rows[i]["miles"] for i in idx), 1),
                            "total": int(bpop[union].sum()),
                            "sum_of_singles": int(sum(rows[i]["gained"][str(T)] for i in idx))}

    # ---- what the page gets: the strongest candidates, plus every one a list above uses ----
    used = tops | {st["row"] for mode in packages.values() for steps in mode.values() for st in steps}
    order = sorted(range(len(rows)), key=lambda i: -max(rows[i]["gained"].values()))
    keep_idx = order[:KEEP] + [i for i in order[KEEP:] if i in used]
    where = {i: k for k, i in enumerate(keep_idx)}
    for mode in packages.values():
        for steps in mode.values():
            for st in steps:
                st["i"] = where[st.pop("row")]
    keep = [rows[i] for i in keep_idx]
    for r in rows:
        del r["_cover"]

    data = {"meta": {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                     "status": "DRAFT screen: generous entrances, unweighted ride times, no check that a path would fit",
                     "access_m": ACCESS_M, "loop_near_m": LOOP_NEAR_M, "min_new_miles": MIN_NEW_MI,
                     "min_path_miles": MIN_PATH_MI, "thresholds": list(THRESHOLDS), "candidates_tested": len(rows),
                     "far_today": base_far, "package_steps": PACKAGE_STEPS},
            "candidates": keep, "packages": packages, "top_together": together}
    (OUT_DIR / "segments.json").write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    print("far today:", base_far, "| candidates tested:", len(rows), "| written:", len(keep))
    print("%-44s %-13s %6s %5s %4s | %7s %7s %7s %7s | %s" % ("candidate", "kind", "miles", "entr", "conn", ">10", ">15", ">20", ">30", "per mi @20"))
    for r in rows[:28]:
        gn = r["gained"]
        print("%-44s %-13s %6.1f %5d %4s | %7d %7d %7d %7d | %d" % (r["name"][:44].encode("ascii", "replace").decode(), r["kind"], r["miles"], r["entrances"],
              "yes" if r["connects_to_loop"] else "no", gn["10"], gn["15"], gn["20"], gn["30"], r["gained_per_mile"]["20"]))
    print("\ntop %d singles built at once:" % TOP_SINGLES, together)
    print("\nexisting paths tested:")
    for r in rows:
        if r["kind"] == "existing path":
            print("  %-44s %5.1f mi  gained %s" % (r["name"][:44].encode("ascii", "replace").decode(), r["miles"], r["gained"]))
    for mode in ("per_mile", "residents"):
        for T in THRESHOLDS:
            print("\nbuilt together, chosen by %s, limit %d min (far today %d):" % (mode, T, base_far[str(T)]))
            for st in packages[mode][str(T)]:
                print("  + %-42s adds %7d  total %7d  new mi %5.1f  per new mi %s" % (
                    keep[st["i"]]["name"][:42].encode("ascii", "replace").decode(), st["added"], st["total"],
                    st["new_miles_total"], st["per_new_mile"]))


if __name__ == "__main__":
    main()
