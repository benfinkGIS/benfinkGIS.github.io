#!/usr/bin/env python3
"""DRAFT: build the street-and-path network around The Loop, place Pima County residents
on it, and run a baseline ride-time check.

Usage (from the repo root, after tools/build_loop.py):
    py tools/build_network.py             # uses cached downloads where it has them
    py tools/build_network.py --refresh   # download everything again

Needs Python 3 with numpy, scipy and shapely (shapely only through build_loop.py).

What it builds
--------------
Network   Every OpenStreetMap way a person on a bike can use inside STUDY_BBOX, cut into
          edges at intersections. Each edge gets a travel time from its length and a speed
          (SPEED_MPH): ride on streets, cycleways and paved or bike-signed paths; go slower
          on unpaved trails; walk the bike on plain footways and steps. One-way streets are
          one-way. Freeways, closed paths and public roads signed bicycle=no are left out.
          Private streets (gated communities, apartment complexes, the air base) are kept
          but can only start a trip: someone who lives on one can ride out to the public
          streets, and nobody can cut through.
          Two ways only connect where OSM gives them a shared node, so a path that passes
          under a road is not joined to it.

Residents 2020 Census blocks for Pima County (population and housing units, from the Census
          Bureau's TIGERweb service). Each block's people are placed at the block's internal
          point and attached to the nearest street intersection that can reach the Loop.
          This is a block-level stand-in for individual homes: fine in town, rough for the
          large blocks at the desert edge (see snap_m in the output).

Baseline  Shortest travel time from every intersection to the nearest node of the draft
          Loop (tools/loop-review/loop_draft.geojson). There is NO traffic-stress weighting
          yet: a mile on a 45 mph arterial costs the same as a mile on a quiet street. It is
          a check that the network hangs together, not a finding.

Outputs
-------
tools/loop-review/blocks.geojson         one point per populated block in the study area
tools/loop-review/network_summary.json   counts, miles by road class, population by ride time
<cache dir>/network.npz                  the graph itself (large; kept out of the repo)

Data: streets (c) OpenStreetMap contributors, ODbL. Census data: U.S. Census Bureau, public domain.
"""
import argparse
import collections
import json
import math
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from build_loop import OVERPASS, UA, overpass   # same folder; shares the Overpass cache

# ---- study area --------------------------------------------------------------
STUDY_BBOX = (32.03, -111.30, 32.50, -110.70)    # south, west, north, east: the Loop plus a few miles
TILES = 4                                        # the download is split into TILES x TILES Overpass queries
STATE_FIPS, COUNTY_FIPS = "04", "019"            # Arizona, Pima County

# ---- travel speeds (mph) -------------------------------------------------------
SPEED_MPH = {"bike": 10.0,      # streets, cycleways, paved or bike-signed paths
             "trail": 5.0,      # unpaved paths and tracks
             "walk": 3.0,       # walking the bike: plain footways, bicycle=dismount
             "steps": 1.5}
STREET = ("trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service", "road")
CLASSES = STREET + ("cycleway", "path", "track", "footway", "steps")
HOME_STREET = ("primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service", "road")
PAVED = {"paved", "asphalt", "concrete", "concrete:plates", "concrete:lanes", "paving_stones", "chipseal"}
SKIP_RE = ("^(motorway|motorway_link|proposed|construction|abandoned|razed|planned|platform|raceway|corridor|"
           "elevator|bus_guideway|busway|rest_area|services|escape|emergency_bay|bus_stop|bridleway|via_ferrata)$")
PRIVATE_ACCESS = {"private", "military", "residents"}   # usable only to leave home, never as a cut-through
FAR_SNAP_M = 300                                 # blocks attached from farther than this are flagged
ISLAND_EXTRA_M = 100                             # ...as are blocks pushed this much past a cut-off street

# metres per degree at the middle of the study area (32.26 N); good to about 0.2% across it
M_LAT, M_LON = 110895.0, 94225.0
TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/12/query"
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "loop-review"


# ---- which ways a bike can use, how fast, and in which direction -------------------
def classify(t):
    """(class, mph, direction, private) for a way's tags, or None if a person with a bike cannot use it.
    direction: 0 = both ways, 1 = only in the way's drawn direction, -1 = only against it.
    private: True for gated/private/military streets, which only the people living on them may use."""
    hw = t.get("highway", "")
    if hw.endswith("_link"):
        hw = hw[:-5]
    bike = t.get("bicycle")
    signed = bike in ("yes", "designated", "permissive")
    access = t.get("access")
    closed = access == "no" and not signed
    private = (access in PRIVATE_ACCESS or bike == "private") and not signed
    if t.get("service") == "drive-through":
        return None
    paved = t.get("surface") in PAVED
    S = SPEED_MPH
    if hw in STREET:
        if closed or (bike == "no" and private):
            # A street closed to the public (here mostly the air base, tagged access=no) or a gated
            # street signed no-bikes still has people living on it: treat it as private.
            private = True
        elif bike == "no":
            return None
        cls, mph = hw, S["walk"] if bike == "dismount" else S["bike"]
    elif closed:
        return None
    elif hw == "cycleway":
        cls, mph = hw, S["bike"]
    elif hw in ("footway", "pedestrian"):
        if t.get("foot") == "no" and not signed:
            return None
        cls, mph = "footway", S["bike"] if signed else S["walk"]
    elif hw in ("path", "track"):
        cls = hw
        mph = S["walk"] if bike in ("no", "dismount") else S["bike"] if (signed or paved) else S["trail"]
    elif hw == "steps":
        cls, mph = hw, S["steps"]
    else:
        return None
    direction = 0
    if cls in STREET or cls == "cycleway":
        ow = t.get("oneway")
        if ow in ("yes", "true", "1") or (ow is None and t.get("junction") in ("roundabout", "circular")):
            direction = 1
        elif ow in ("-1", "reverse"):
            direction = -1
        contraflow = t.get("oneway:bicycle") == "no" or any(
            "opposite" in (t.get(k) or "") for k in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both"))
        if contraflow:
            direction = 0
    return cls, mph, direction, private


def download_ways(cache, refresh):
    s, w, n, e = STUDY_BBOX
    ways, stamps, gaps = {}, set(), [0]
    for i in range(TILES):
        for j in range(TILES):
            box = (s + (n - s) * i / TILES, w + (e - w) * j / TILES, s + (n - s) * (i + 1) / TILES, w + (e - w) * (j + 1) / TILES)
            q = ('[out:json][timeout:240][maxsize:1073741824];way[highway][highway!~"%s"](%.5f,%.5f,%.5f,%.5f);out geom;'
                 % ((SKIP_RE,) + box))
            d = overpass(q, cache, refresh)
            stamps.add(d.get("osm3s", {}).get("timestamp_osm_base", "?")[:10])
            got = 0
            for el in d["elements"]:
                if el["type"] != "way" or el["id"] in ways or len(el.get("nodes", [])) < 2:
                    continue
                c = classify(el.get("tags", {}))
                if c is None:
                    continue
                # A server can return a way with some node positions missing (null); drop those nodes.
                pairs = [(nd, (p["lon"], p["lat"])) for nd, p in zip(el["nodes"], el["geometry"]) if p]
                if len(pairs) < len(el["nodes"]):
                    gaps[0] += 1
                if len(pairs) < 2:
                    continue
                ways[el["id"]] = ([nd for nd, _ in pairs], [xy for _, xy in pairs], c)
                got += 1
            print("  tile %d/%d: %d new usable ways" % (i * TILES + j + 1, TILES * TILES, got), flush=True)
    if gaps[0]:
        print("  note: %d ways came back with some node positions missing" % gaps[0], flush=True)
    return ways, sorted(stamps)


def build_graph(ways):
    """Cut ways into edges at intersections. Returns node arrays and edge arrays."""
    use = collections.Counter()
    for nodes, _, _ in ways.values():
        use.update(nodes)
        use[nodes[0]] += 1                        # way ends are always kept
        use[nodes[-1]] += 1
    index, lon, lat = {}, [], []

    def node(osm_id, xy):
        k = index.get(osm_id)
        if k is None:
            k = index[osm_id] = len(lon)
            lon.append(xy[0])
            lat.append(xy[1])
        return k

    eu, ev, em, emin, ecls, edir, eway, epriv = [], [], [], [], [], [], [], []
    for wid, (nodes, xy, (cls, mph, direction, private)) in ways.items():
        start, dist = 0, 0.0
        for i in range(1, len(nodes)):
            dist += math.hypot((xy[i][0] - xy[i - 1][0]) * M_LON, (xy[i][1] - xy[i - 1][1]) * M_LAT)
            if use[nodes[i]] > 1:
                if nodes[start] != nodes[i]:
                    dist = max(dist, 0.1)
                    eu.append(node(nodes[start], xy[start]))
                    ev.append(node(nodes[i], xy[i]))
                    em.append(dist)
                    emin.append(dist / 1609.344 / mph * 60)
                    ecls.append(CLASSES.index(cls))
                    edir.append(direction)
                    eway.append(wid)
                    epriv.append(private)
                start, dist = i, 0.0
    ids = np.fromiter(index.keys(), dtype=np.int64, count=len(index))
    return {"node_id": ids, "lon": np.array(lon), "lat": np.array(lat),
            "u": np.array(eu, dtype=np.int32), "v": np.array(ev, dtype=np.int32),
            "m": np.array(em), "min": np.array(emin), "cls": np.array(ecls, dtype=np.int8),
            "dir": np.array(edir, dtype=np.int8), "way": np.array(eway, dtype=np.int64),
            "priv": np.array(epriv, dtype=bool)}, index


def reversed_arcs(g, edges):
    """Arcs for searching outward from a destination: an allowed trip a->b becomes an arc b->a."""
    fwd, back = edges & (g["dir"] >= 0), edges & (g["dir"] <= 0)   # travel u->v allowed / v->u allowed
    return (np.concatenate([g["v"][fwd], g["u"][back]]), np.concatenate([g["u"][fwd], g["v"][back]]),
            np.concatenate([g["min"][fwd], g["min"][back]]))


def fastest_matrix(rows, cols, vals, n):
    order = np.lexsort((vals, cols, rows))                # keep the fastest of any parallel edges
    rows, cols, vals = rows[order], cols[order], vals[order]
    first = np.ones(len(rows), dtype=bool)
    first[1:] = (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])
    return csr_matrix((vals[first], (rows[first], cols[first])), shape=(n, n))


def prepare_search(g):
    """Build the search matrices once, so many sets of destinations can be tried (tools/test_segments.py)."""
    n = len(g["lon"])
    public = ~g["priv"]
    has_public, on_private = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    has_public[g["u"][public]] = True
    has_public[g["v"][public]] = True
    on_private[g["u"][g["priv"]]] = True
    on_private[g["v"][g["priv"]]] = True
    return {"n": n, "public": fastest_matrix(*reversed_arcs(g, public), n),
            "private_arcs": reversed_arcs(g, g["priv"]), "has_public": has_public, "on_private": on_private}


def private_pass(prep, t_pub):
    """Extend public-street times onto private streets, which may only start a trip.
    Every node where a private street meets the public network is a gate: an extra start node feeds
    each gate its public time, and the search runs inward from the gates over private streets only."""
    minutes = t_pub.copy()
    rows, cols, vals = prep["private_arcs"]
    if len(rows):
        n = prep["n"]
        gates = np.flatnonzero(prep["on_private"] & np.isfinite(t_pub))
        rows = np.concatenate([rows, np.full(len(gates), n)])
        cols = np.concatenate([cols, gates])
        vals = np.concatenate([vals, np.maximum(t_pub[gates], 1e-6)])
        t_priv = dijkstra(fastest_matrix(rows, cols, vals, n + 1), directed=True, indices=n)[:n]
        # Only people who live on private streets get to use them.
        use = ~prep["has_public"] | ~np.isfinite(t_pub)
        minutes[use] = np.minimum(t_pub[use], t_priv[use])
    return minutes


def time_to_loop(g, loop_nodes):
    """Minutes from every node to the nearest Loop node, travelling legally toward it.
    Returns (minutes, minutes on public streets only, nodes that have no public street)."""
    prep = prepare_search(g)
    t_pub = dijkstra(prep["public"], directed=True, indices=loop_nodes, min_only=True)
    return private_pass(prep, t_pub), t_pub, ~prep["has_public"]


def fetch_blocks(cache, refresh):
    f = cache / "pima_blocks_2020.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text(encoding="utf-8"))
    rows, offset, page = [], 0, 4000
    while True:
        q = urllib.parse.urlencode({
            "where": "STATE='%s' AND COUNTY='%s'" % (STATE_FIPS, COUNTY_FIPS),
            "outFields": "GEOID,POP100,HU100,INTPTLAT,INTPTLON,AREALAND", "returnGeometry": "false",
            "orderByFields": "GEOID", "resultOffset": offset, "resultRecordCount": page, "f": "json"})
        for attempt in range(4):
            try:
                req = urllib.request.Request(TIGERWEB + "?" + q, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read().decode("utf-8"))
                if "error" in d:
                    raise RuntimeError(d["error"])
                break
            except Exception as e:
                print("  TIGERweb: %s" % e, file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit("TIGERweb failed; no blocks written.")
        feats = d.get("features", [])
        rows += [a["attributes"] for a in feats]
        offset += len(feats)
        if len(feats) < page:
            break
    f.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="download OSM and Census data again")
    ap.add_argument("--cache-dir", default=str(Path(tempfile.gettempdir()) / "finkgeo_loop_cache"))
    ap.add_argument("--server", help="Overpass interpreter URL to try first")
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    loop_file = OUT_DIR / "loop_draft.geojson"
    if not loop_file.exists():
        raise SystemExit("Run tools/build_loop.py first: %s is missing." % loop_file)
    loop_way_ids = {f["properties"]["way"] for f in json.loads(loop_file.read_text(encoding="utf-8"))["features"]}

    print("1/4 streets and paths from OpenStreetMap (%d tiles)" % (TILES * TILES), flush=True)
    if args.server:
        if args.server in OVERPASS:
            OVERPASS.remove(args.server)
        OVERPASS.insert(0, args.server)
    ways, osm_dates = download_ways(cache, args.refresh)
    # Make sure the Loop and the ways touching it match the Loop draft (see tools/build_loop.py).
    patched = 0
    patch_file = cache / "loop_network_patch.json"
    if patch_file.exists():
        for el in json.loads(patch_file.read_text(encoding="utf-8")):
            c = classify(el["tags"])
            if c is None or (el["id"] in ways and el["id"] not in loop_way_ids):
                continue
            patched += el["id"] not in ways
            ways[el["id"]] = (el["nodes"], [(p["lon"], p["lat"]) for p in el["geometry"]], c)
    else:
        print("  warning: no loop_network_patch.json in the cache; run tools/build_loop.py first", file=sys.stderr)
    print("2/4 building the graph from %d ways" % len(ways), flush=True)
    g, index = build_graph(ways)
    n = len(g["lon"])
    loop_nodes = sorted({index[nd] for wid in loop_way_ids if wid in ways for nd in ways[wid][0] if nd in index})
    loop_missing = sorted(wid for wid in loop_way_ids if wid not in ways)
    if not loop_nodes:
        raise SystemExit("No Loop nodes found in the network.")
    minutes, t_pub, private_only = time_to_loop(g, loop_nodes)
    reach = np.isfinite(minutes)

    print("3/4 Census blocks for Pima County", flush=True)
    blocks = fetch_blocks(cache, args.refresh)
    blon = np.array([float(b["INTPTLON"]) for b in blocks])
    blat = np.array([float(b["INTPTLAT"]) for b in blocks])
    pop = np.array([b["POP100"] or 0 for b in blocks])
    hu = np.array([b["HU100"] or 0 for b in blocks])
    s, w, nth, e = STUDY_BBOX
    inside = (blat >= s) & (blat <= nth) & (blon >= w) & (blon <= e)

    print("4/4 attaching blocks to the network", flush=True)
    home_cls = np.isin(g["cls"], [CLASSES.index(c) for c in HOME_STREET])
    on_street = np.zeros(n, dtype=bool)
    on_street[g["u"][home_cls]] = True
    on_street[g["v"][home_cls]] = True
    xy = np.column_stack([g["lon"] * M_LON, g["lat"] * M_LAT])
    bxy = np.column_stack([blon * M_LON, blat * M_LAT])
    good = np.flatnonzero(on_street & reach)              # street intersections that can reach the Loop
    anyst = np.flatnonzero(on_street)
    d_good, k_good = cKDTree(xy[good]).query(bxy)
    d_any, k_any = cKDTree(xy[anyst]).query(bxy)
    snap_node = good[k_good]
    # the nearest street cannot reach the Loop at all, and the one used instead is a good deal farther
    island = ~reach[anyst[k_any]] & (d_good - d_any > ISLAND_EXTRA_M)
    block_min = minutes[snap_node] + d_good / 1609.344 / SPEED_MPH["bike"] * 60

    # ---- summary ----
    study = inside & (pop > 0)
    pop_study, pop_county = int(pop[inside].sum()), int(pop.sum())
    bands = {}
    for limit in (5, 10, 15, 20, 30):
        p = int(pop[study & (block_min <= limit)].sum())
        bands["within_%d_min" % limit] = {"population": p, "share_of_study_area": round(p / pop_study, 4),
                                          "share_of_county": round(p / pop_county, 4)}
    miles_by_class = {c: round(float(g["m"][g["cls"] == k].sum()) / 1609.344, 1) for k, c in enumerate(CLASSES)}
    far = study & (d_good > FAR_SNAP_M)
    via_private = study & private_only[snap_node]
    summary = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "status": "DRAFT baseline: shortest travel time, no traffic-stress weighting",
        "study_bbox_south_west_north_east": STUDY_BBOX, "speeds_mph": SPEED_MPH,
        "network": {"osm_data_as_of": osm_dates, "ways_added_from_loop_build": patched,
                    "ways": len(ways), "nodes": n, "edges": int(len(g["u"])),
                    "one_way_edges": int((g["dir"] != 0).sum()),
                    "miles_total": round(float(g["m"].sum()) / 1609.344, 1), "miles_by_class": miles_by_class,
                    "private_streets": {"edges": int(g["priv"].sum()),
                                        "miles": round(float(g["m"][g["priv"]].sum()) / 1609.344, 1),
                                        "nodes_only_on_private_streets": int(private_only.sum()),
                                        "nodes_that_reach_the_loop_only_through_them": int((reach & ~np.isfinite(t_pub)).sum())},
                    "loop_nodes": len(loop_nodes), "loop_ways_not_in_network": loop_missing,
                    "nodes_that_cannot_reach_loop": int((~reach).sum()),
                    "street_nodes_that_cannot_reach_loop": int((on_street & ~reach).sum())},
        "residents": {"blocks_in_county": len(blocks), "population_county": pop_county,
                      "housing_units_county": int(hu.sum()),
                      "blocks_in_study_area": int(inside.sum()), "populated_blocks_in_study_area": int(study.sum()),
                      "population_study_area": pop_study, "housing_units_study_area": int(hu[inside].sum()),
                      "population_outside_study_area": pop_county - pop_study,
                      "blocks_attached_from_over_%d_m" % FAR_SNAP_M: {"blocks": int(far.sum()), "population": int(pop[far].sum())},
                      "blocks_attached_to_private_streets": {"blocks": int(via_private.sum()),
                                                             "population": int(pop[via_private].sum())},
                      "blocks_whose_nearest_street_is_cut_off": {"blocks": int((study & island).sum()),
                                                                 "population": int(pop[study & island].sum())},
                      "median_attach_distance_m": round(float(np.median(d_good[study])), 1)},
        "baseline_ride_time_to_loop": bands,
        "attribution": "Streets (c) OpenStreetMap contributors, ODbL; population: U.S. Census Bureau, 2020 Census",
    }

    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(float(blon[i]), 6), round(float(blat[i]), 6)]},
              "properties": {"geoid": blocks[i]["GEOID"], "pop": int(pop[i]), "hu": int(hu[i]),
                             "min": round(float(block_min[i]), 6), "snap_m": int(round(float(d_good[i]))),
                             "island": bool(island[i]), "private": bool(private_only[snap_node[i]])}}
             for i in np.flatnonzero(study)]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "blocks.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "metadata": summary, "features": feats}, separators=(",", ":")), encoding="utf-8")
    (OUT_DIR / "network_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sidx = np.flatnonzero(study)                           # same order as the features in blocks.geojson
    np.savez_compressed(cache / "network.npz", minutes_to_loop=minutes, minutes_public_only=t_pub,
                        loop_nodes=np.array(loop_nodes), block_node=snap_node[sidx], block_snap_m=d_good[sidx],
                        block_pop=pop[sidx], block_lon=blon[sidx], block_lat=blat[sidx], **g)
    print(json.dumps(summary, indent=2))
    print("graph saved to", cache / "network.npz")


if __name__ == "__main__":
    main()
