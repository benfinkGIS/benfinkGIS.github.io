#!/usr/bin/env python3
"""DRAFT: find places to grab a beer near The Loop and work out the ride off the path to each.

Usage (from the repo root, after tools/build_loop.py and tools/build_network.py):
    py tools/build_loop_beer.py             # uses cached downloads where it has them
    py tools/build_loop_beer.py --refresh   # download the licences and OSM places again

Needs Python 3 with numpy, scipy and shapely.

What it does
------------
Places    Active Arizona liquor licences in Pima County, from the City of Tucson's public
          "Liquor License - Active" map layer (the state's licence list, downloaded daily
          and geocoded by the City and Pima County). Only licences to pour on the premises
          are used: series 3 (microbrewery), 6 (bar), 7 (beer and wine bar), 11 (hotel) and
          12 (restaurant). Shops, wholesalers, private clubs, government and one-off permits
          are left out. Several licences at one address under one name are one place.
          Licensee names are never read: only the business name, address and licence number.

Kinds     brewery     holds a microbrewery licence, or has "brewing", "brewery" or
                      "cider house" in its name
          bar         bar licence (series 6)
          beerwine    beer and wine bar licence (series 7)
          restaurant  restaurant licence (series 12)
          venue       hotels, resorts, golf clubs, cinemas and the like, picked out by name
                      (VENUE_RE), whatever licence they hold

Names     The licence list is in capitals. Where OpenStreetMap has a bar, pub, brewery or
          restaurant of a similar name within OSM_MATCH_M, its spelling, website and opening
          hours are used; otherwise the name is put in title case by rule.

Ride      The fastest legal ride from the Loop to each place over the street-and-path
          network built by tools/build_network.py (10 mph, one-way streets respected,
          no cutting through private streets, no traffic-stress weighting). Each place
          is attached to the nearest public intersection the Loop can reach, and the route
          is traced back to the point where it leaves the Loop.

Section   The part of the Loop a route leaves from, named after the nearest of the rivers
          and washes the Loop follows (from OpenStreetMap), or the Loop path's own name.

Location  The licence points are the City's geocoding of the licence addresses, and about one
          in a hundred is well off (for example a few East Congress addresses placed on West
          Congress). Where OpenStreetMap has the only similarly named place within OSM_FAR_M
          and its house number agrees (or it has none and the place is not a numbered chain
          store), the place is moved there. Every move is listed in the output's metadata.

Edits     tools/loop_beer_edits.json, if present, can drop places by name, change kinds and
          move places the rule above cannot fix (names as in the licence list, in capitals):
          {"exclude": ["NAME", ...], "kind": {"NAME": "bar", ...}, "move": {"NAME": [lon, lat], ...}}

Output
------
tucson-loop-beer/data/spots.json   places within MAX_MIN minutes, each with its ride time,
                                   distance, exit point, Loop section and route line

Data: Arizona Department of Liquor Licenses and Control, via City of Tucson and Pima County GIS
(provided "as is"); streets and names (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import difflib
import json
import math
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString, Point

from build_loop import OVERPASS, UA, overpass
from build_network import M_LAT, M_LON, SPEED_MPH, STUDY_BBOX, fastest_matrix

MAX_MIN = 10.0              # places farther than this from the Loop are left out
FAR_SNAP_M = 150            # a place attached to the network from farther than this is flagged
SAME_PLACE_M = 60           # licences this close together under one name are one place
OSM_MATCH_M = 200           # how far an OSM place may be from the licence point and still match
OSM_FAR_M = 2000            # ...and how far away a lone namesake is looked for when the point may be wrong
SECTION_NEAR_M = 500        # an exit this close to a river or wash takes its name
THIN_DEG = 0.00003          # about 3 m: route lines are thinned this much for drawing
LICENCES = "https://gis.tucsonaz.gov/public/rest/services/PublicMaps/PermitsCode/MapServer/16/query"
SERIES = {3: "Microbrewery", 6: "Bar", 7: "Beer and wine bar", 11: "Hotel or motel", 12: "Restaurant"}
KINDS = ("brewery", "bar", "beerwine", "restaurant", "venue")
BREW_RE = re.compile(r"BREWING|BREWERY|BREWERS|BREW ?HOUSE|CIDER HOUSE")
VENUE_RE = re.compile(
    r"HOTEL|MOTEL|RESORT|SUITES|\bINNS?\b|\bLODGE\b|MARRIOTT|HILTON|HYATT|SHERATON|WESTIN|ALOFT|HOMEWOOD|"
    r"\bGOLF|COUNTRY CLUB|AIRPORT|CASINO|CINEMA|THEAT(RE|ER)|\bAMC\b|HARKINS|CINEMARK|\bBOWL|\bLANES\b|ARENA|"
    r"STADIUM|CONVENTION|EXPO CENTER|PERFORMING ARTS|MUSEUM|SKI VALLEY|ASSISTED|SENIOR LIVING|RETIREMENT|"
    r"BROOKDALE|\bRV\b|UNIVERSITY OF ARIZONA|RACE ?TRACK|RACEWAY|FAIRGROUNDS|\bSPA\b|\bZOO\b")
ROOT = Path(__file__).resolve().parent.parent
LOOP_FILE = ROOT / "tools" / "loop-review" / "loop_draft.geojson"
EDITS_FILE = ROOT / "tools" / "loop_beer_edits.json"
OUT = ROOT / "tucson-loop-beer" / "data" / "spots.json"

# rivers and washes as OSM names them -> the Loop section shown on the page
WATERWAY = {"Rillito River": "Rillito River", "Santa Cruz River": "Santa Cruz River",
            "Cañada del Oro": "Cañada del Oro", "Big Wash": "Big Wash", "Pantano Wash": "Pantano Wash",
            "Julian Wash": "Julian Wash",
            "Tanque Verde Wash": "Rillito River"}      # the Loop's short reach on the Tanque Verde joins the Rillito path
# named Loop ways -> section, for exits that are not beside one of the waterways
LOOP_NAME = {"Rillito River Path": "Rillito River", "Rillito Connector": "Rillito River",
             "Santa Cruz River Path": "Santa Cruz River", "Santa Cruz River Pedestrian Bridge": "Santa Cruz River",
             "Julian Wash Greenway Path": "Julian Wash", "Julian Wash Greenway": "Julian Wash",
             "Tucson Diversion Channel Greenway": "Julian Wash", "Harrison Greenway Path": "Harrison Greenway",
             "Cañada del Oro": "Cañada del Oro"}

SMALL = {"a", "an", "and", "at", "by", "de", "del", "el", "la", "las", "los", "of", "on", "the", "y"}
KEEP_UPPER = {"BBQ", "II", "III", "IV", "AZ", "USA", "VFW", "LLC", "RA", "AMC", "TPC", "BJ'S", "PF", "JW", "DJ'S", "RJ'S", "TTT"}
ADDR_WORD = {"ROAD": "Rd", "STREET": "St", "AVENUE": "Ave", "BOULEVARD": "Blvd", "DRIVE": "Dr", "HIGHWAY": "Hwy",
             "PLACE": "Pl", "LANE": "Ln", "TRAIL": "Trl", "WAY": "Way", "LOOP": "Loop", "STE": "Ste", "SUITE": "Ste"}


# ---- names ---------------------------------------------------------------------------
def cap(w):
    if w in KEEP_UPPER or re.search(r"\d", w) or (len(w) == 1 and w.isalpha()):
        return w
    parts = re.split(r"([-/&'.])", w.lower())
    out = []
    for i, p in enumerate(parts):
        after_apostrophe = i >= 2 and parts[i - 1] == "'" and len(p) <= 1      # JOHN'S -> John's
        out.append(p if after_apostrophe or not p else p[0].upper() + p[1:])
    s = "".join(out)
    return "Mc" + s[2].upper() + s[3:] if re.match(r"Mc[a-z]{3}", s) else s


def nice_name(name):
    name = re.sub(r"\s+", " ", name).strip()
    if name != name.upper():                    # already in mixed case
        return name
    words = name.split(" ")
    return " ".join(w.lower() if (w.lower() in SMALL and i) else cap(w) for i, w in enumerate(words))


def nice_addr(addr):
    words = re.sub(r"\s+", " ", addr or "").strip().split(" ")
    out = []
    for w in words:
        u = w.upper()
        out.append(ADDR_WORD[u] if u in ADDR_WORD else w if (len(w) <= 2 and w.isalpha()) or re.search(r"\d|#", w) else cap(u))
    return " ".join(out).strip()


def name_key(name):
    k = re.sub(r"[^A-Z0-9 ]", "", re.sub(r"&|\+", " AND ", name.upper()))
    k = re.sub(r"\b(THE|LLC|INC|COMPANY|CO|RESTAURANT|AND)\b", " ", k)
    return re.sub(r"\s+", "", k)


def similar(a, b):
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return (len(short) >= 5 and short in long_) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def dist_m(a, b):
    return math.hypot((a["lon"] - b["lon"]) * M_LON, (a["lat"] - b["lat"]) * M_LAT)


# ---- licences ------------------------------------------------------------------------
def series_of(no):
    no = (no or "").strip()
    if re.fullmatch(r"0\d{11}", no):            # current numbering: three digits of series first
        return int(no[:3])
    if re.fullmatch(r"\d{8}", no):              # older numbering: two digits of series first
        return int(no[:2])
    return None                                 # interim permits, growler and sampling add-ons, and so on


def fetch_licences(cache, refresh):
    f = cache / "tucson_liquor_active.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text(encoding="utf-8"))
    rows, offset, page = [], 0, 1000
    while True:
        q = urllib.parse.urlencode({
            "where": "1=1", "outFields": "LICENSENO,BUSINESSNAME,BUSINESSADDRESS,ADDRESSMATCHED",
            "outSR": 4326, "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": page, "f": "json"})
        for attempt in range(4):
            try:
                req = urllib.request.Request(LICENCES + "?" + q, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read().decode("utf-8"))
                if "error" in d:
                    raise RuntimeError(d["error"])
                break
            except Exception as e:
                print("  licence layer: %s" % e, file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit("The licence layer did not answer; nothing written.")
        feats = d.get("features", [])
        rows += [dict(ft["attributes"], lon=ft["geometry"]["x"], lat=ft["geometry"]["y"]) for ft in feats if ft.get("geometry")]
        offset += len(feats)
        if len(feats) < page:
            break
    data = {"downloaded": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "rows": rows}
    f.write_text(json.dumps(data), encoding="utf-8")
    return data


def places_from_licences(rows, edits):
    s, w, n, e = STUDY_BBOX
    exclude = {x.strip().upper() for x in edits.get("exclude", [])}
    forced = {k.strip().upper(): v for k, v in edits.get("kind", {}).items()}
    moves = {k.strip().upper(): v for k, v in edits.get("move", {}).items()}
    places, dropped = [], 0
    for r in rows:
        ser = series_of(r["LICENSENO"])
        raw = re.sub(r"\s+", " ", r["BUSINESSNAME"] or "").strip()
        if ser not in SERIES or not raw or not (s <= r["lat"] <= n and w <= r["lon"] <= e):
            continue
        if raw.upper() in exclude:
            dropped += 1
            continue
        rec = {"raw": raw, "key": name_key(raw), "lon": r["lon"], "lat": r["lat"], "series": {ser}, "moved": "",
               "addr": nice_addr(r["BUSINESSADDRESS"] or r["ADDRESSMATCHED"])}
        if raw.upper() in moves:
            rec["lon"], rec["lat"] = moves[raw.upper()]
            rec["moved"] = "by hand (tools/loop_beer_edits.json)"
        for p in places:
            if dist_m(p, rec) <= SAME_PLACE_M and similar(p["key"], rec["key"]):
                p["series"].add(ser)
                break
        else:
            places.append(rec)
    for p in places:
        up = p["raw"].upper()
        p["kind"] = (forced.get(up) or
                     ("brewery" if 3 in p["series"] or BREW_RE.search(up) else
                      "venue" if 11 in p["series"] or VENUE_RE.search(up) else
                      "bar" if 6 in p["series"] else "beerwine" if 7 in p["series"] else "restaurant"))
        p["name"] = nice_name(p["raw"])
    return places, dropped


# ---- OpenStreetMap: nicer names, websites, hours; rivers for the Loop sections ----------
def fetch_osm(cache, refresh):
    box = "%.5f,%.5f,%.5f,%.5f" % STUDY_BBOX
    q = ('[out:json][timeout:180];(nwr[amenity~"^(bar|pub|biergarten|restaurant|cafe|fast_food|nightclub)$"][name](%s);'
         'nwr[craft~"^(brewery|cidery)$"][name](%s);nwr[microbrewery=yes][name](%s););out center tags;' % (box, box, box))
    d = overpass(q, cache, refresh)
    out = []
    for el in d["elements"]:
        t, c = el.get("tags", {}), el.get("center") or el
        site = t.get("website") or t.get("contact:website") or ""
        if site and not re.match(r"^https?://", site):
            site = "https://" + site
        out.append({"name": t["name"].strip(), "key": name_key(t["name"]), "lon": c["lon"], "lat": c["lat"],
                    "web": site, "hours": t.get("opening_hours", ""), "outdoor": t.get("outdoor_seating") == "yes",
                    "house": (t.get("addr:housenumber") or "").strip()})
    return out, d.get("osm3s", {}).get("timestamp_osm_base", "?")[:10]


def fetch_waterways(cache, refresh):
    box = "%.5f,%.5f,%.5f,%.5f" % STUDY_BBOX
    q = ('[out:json][timeout:120];way[waterway][name~"^(%s)$"](%s);out geom;' % ("|".join(WATERWAY), box))
    lines = []
    for el in overpass(q, cache, refresh)["elements"]:
        pts = [(p["lon"] * M_LON, p["lat"] * M_LAT) for p in el.get("geometry", []) if p]
        if len(pts) > 1:
            lines.append((WATERWAY[el["tags"]["name"]], LineString(pts)))
    return lines


def way_geometries(cache, wanted):
    """Node ids and coordinates of the wanted ways, read back from the cached Overpass responses."""
    found = {}
    files = sorted(cache.glob("*.json"), key=lambda f: f.name != "loop_network_patch.json")   # the patch wins
    for f in files:
        if f.name.startswith(("pima_", "tucson_")) or f.stat().st_size < 200000:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for el in (d if isinstance(d, list) else d.get("elements", [])):
            if el.get("type", "way") == "way" and el.get("id") in wanted and el["id"] not in found and el.get("geometry"):
                pairs = [(nd, (p["lon"], p["lat"])) for nd, p in zip(el["nodes"], el["geometry"]) if p]
                found[el["id"]] = ([nd for nd, _ in pairs], [xy for _, xy in pairs])
        if len(found) == len(wanted):
            break
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="download the licences and OSM places again")
    ap.add_argument("--cache-dir", default=str(Path(tempfile.gettempdir()) / "finkgeo_loop_cache"))
    ap.add_argument("--server", help="Overpass interpreter URL to try first")
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    npz = cache / "network.npz"
    if not npz.exists():
        raise SystemExit("Run tools/build_network.py first: %s is missing." % npz)
    if args.server:
        if args.server in OVERPASS:
            OVERPASS.remove(args.server)
        OVERPASS.insert(0, args.server)
    edits = json.loads(EDITS_FILE.read_text(encoding="utf-8")) if EDITS_FILE.exists() else {}

    print("1/5 liquor licences (City of Tucson layer)", flush=True)
    lic = fetch_licences(cache, args.refresh)
    places, dropped = places_from_licences(lic["rows"], edits)
    print("  %d licences in the county, %d places to pour in the study area" % (len(lic["rows"]), len(places)), flush=True)

    print("2/5 names and rivers from OpenStreetMap", flush=True)
    osm, osm_date = fetch_osm(cache, args.refresh)
    waterways = fetch_waterways(cache, args.refresh)
    tree = cKDTree(np.array([[o["lon"] * M_LON, o["lat"] * M_LAT] for o in osm]))
    matched = 0
    for p in places:
        near = tree.query_ball_point([p["lon"] * M_LON, p["lat"] * M_LAT], OSM_FAR_M)
        hits = sorted((dist_m(p, osm[j]), j) for j in near if similar(p["key"], osm[j]["key"]))
        o = osm[hits[0][1]] if hits else None
        if o and hits[0][0] > OSM_MATCH_M:
            # A namesake, but not close. Trust it over the licence point only when it is the only one around
            # and the house numbers agree (or OSM has none and this is not one branch of a numbered chain).
            house = re.match(r"\d+", p["addr"])
            agree = o["house"] == house.group(0) if (o["house"] and house) else (not o["house"] and "#" not in p["raw"])
            if len(hits) == 1 and agree and not p["moved"]:
                p["moved"] = "to the OpenStreetMap place of the same name, %d m away" % round(hits[0][0])
                p["lon"], p["lat"] = o["lon"], o["lat"]
            else:
                o = None
        p.update(web=o["web"] if o else "", hours=o["hours"] if o else "", outdoor=bool(o and o["outdoor"]))
        p["osm"] = bool(o)
        if o:
            matched += 1
            p["name"] = o["name"]
    print("  %d of %d places matched to an OSM name (OSM data as of %s)" % (matched, len(places), osm_date), flush=True)

    print("3/5 rides out from the Loop", flush=True)
    g = dict(np.load(npz))
    n = len(g["lon"])
    pub = ~g["priv"]
    fwd, back = pub & (g["dir"] >= 0), pub & (g["dir"] <= 0)
    rows = np.concatenate([g["u"][fwd], g["v"][back]])        # arcs in the direction of travel, away from the Loop
    cols = np.concatenate([g["v"][fwd], g["u"][back]])
    vals = np.concatenate([g["min"][fwd], g["min"][back]])
    eidx = np.concatenate([np.flatnonzero(fwd), np.flatnonzero(back)])
    t, pred, _src = dijkstra(fastest_matrix(rows, cols, vals, n), directed=True, indices=g["loop_nodes"],
                             min_only=True, return_predecessors=True)
    order = np.lexsort((vals, cols, rows))[::-1]              # slowest first, so the fastest edge is written last
    arc = {(int(r), int(c)): int(e) for r, c, e in zip(rows[order], cols[order], eidx[order])}

    print("4/5 attaching places to the network", flush=True)
    is_loop = np.zeros(n, dtype=bool)
    is_loop[g["loop_nodes"]] = True
    on_pub = np.zeros(n, dtype=bool)
    on_pub[g["u"][pub]] = True
    on_pub[g["v"][pub]] = True
    good = np.flatnonzero(on_pub & np.isfinite(t))
    xy = np.column_stack([g["lon"] * M_LON, g["lat"] * M_LAT])
    pxy = np.array([[p["lon"] * M_LON, p["lat"] * M_LAT] for p in places])
    snap_d, k = cKDTree(xy[good]).query(pxy)

    loop = json.loads(LOOP_FILE.read_text(encoding="utf-8"))
    # straight-line distance to the path itself, not just to its junctions
    loop_lines = MultiLineString([[(x * M_LON, y * M_LAT) for x, y in f["geometry"]["coordinates"]] for f in loop["features"]])
    crow = np.array([loop_lines.distance(Point(x, y)) for x, y in pxy])
    way_name = {f["properties"]["way"]: f["properties"].get("name") for f in loop["features"]}
    node_ways = {}
    for e in np.flatnonzero(np.isin(g["way"], list(way_name))):
        for nd in (int(g["u"][e]), int(g["v"][e])):
            node_ways.setdefault(nd, set()).add(int(g["way"][e]))

    named = {nd: sorted({LOOP_NAME[way_name[w]] for w in ws if way_name.get(w) in LOOP_NAME}) for nd, ws in node_ways.items()}
    named = {nd: v[0] for nd, v in named.items() if v}
    named_ids = np.array(sorted(named))
    named_tree = cKDTree(xy[named_ids])

    def section(node):
        """The river or wash beside the exit; failing that, the nearest part of the Loop that has a name."""
        pt = Point(xy[node][0], xy[node][1])
        d, name = min((ln.distance(pt), nm) for nm, ln in waterways)
        if d <= SECTION_NEAR_M:
            return name
        d2, j = named_tree.query(xy[node])
        return named[int(named_ids[j])] if d2 <= 6 * SECTION_NEAR_M else name if d <= 3 * SECTION_NEAR_M else "Other"

    picked = []
    for i, p in enumerate(places):
        node = int(good[k[i]])
        minutes = float(t[node]) + snap_d[i] / 1609.344 / SPEED_MPH["bike"] * 60
        if minutes > MAX_MIN:
            continue
        path = [node]
        while not is_loop[path[-1]] and pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        path.reverse()                                        # Loop exit first, place last
        p.update(min=minutes, snap_m=float(snap_d[i]), crow_m=float(crow[i]), path=path)
        picked.append(p)

    print("5/5 tracing %d routes" % len(picked), flush=True)
    steps = {(a, b) for p in picked for a, b in zip(p["path"], p["path"][1:])}
    geoms = way_geometries(cache, {int(g["way"][arc[s]]) for s in steps})
    sections, out = {}, []
    for p in picked:
        path = p.pop("path")
        line, metres = [(float(g["lon"][path[0]]), float(g["lat"][path[0]]))], 0.0
        for a, b in zip(path, path[1:]):
            e = arc[(a, b)]
            metres += float(g["m"][e])
            piece = None
            w = geoms.get(int(g["way"][e]))
            if w:
                ia = [j for j, nd in enumerate(w[0]) if nd == int(g["node_id"][a])]
                ib = [j for j, nd in enumerate(w[0]) if nd == int(g["node_id"][b])]
                pairs = [(x, y) for x in ia for y in ib if x != y]
                if pairs:
                    ja, jb = min(pairs, key=lambda s: abs(s[0] - s[1]))
                    piece = w[1][ja:jb + 1] if ja < jb else w[1][jb:ja + 1][::-1]
            line += piece[1:] if piece else [(float(g["lon"][b]), float(g["lat"][b]))]
        line.append((p["lon"], p["lat"]))                     # last hop: from the street to the door
        thin = LineString(line).simplify(THIN_DEG)
        if path[0] not in sections:
            sections[path[0]] = section(path[0])
        out.append({
            "name": p["name"], "kind": p["kind"], "lic": [SERIES[x] for x in sorted(p["series"])],
            "lon": round(p["lon"], 5), "lat": round(p["lat"], 5),
            "min": round(p["min"], 1), "mi": round((metres + p["snap_m"]) / 1609.344, 2),
            "crow_mi": round(p["crow_m"] / 1609.344, 2), "far_snap": bool(p["snap_m"] > FAR_SNAP_M),
            "exit": [round(float(g["lon"][path[0]]), 5), round(float(g["lat"][path[0]]), 5)],
            "section": sections[path[0]],
            "route": [[round(x, 5), round(y, 5)] for x, y in thin.coords],
            "addr": p["addr"], "web": p["web"], "hours": p["hours"], "outdoor": p["outdoor"]})
    out.sort(key=lambda s: (s["min"], s["name"]))

    meta = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "status": "DRAFT: places as the licence list has them, not checked on the ground",
            "licences_downloaded": lic["downloaded"], "osm_names_as_of": osm_date,
            "max_minutes": MAX_MIN, "speed_mph": SPEED_MPH["bike"],
            "places_in_study_area": len(places), "places_within_max": len(out),
            "by_kind": {kd: sum(s["kind"] == kd for s in out) for kd in KINDS},
            "matched_to_osm_name": sum(1 for p in picked if p.get("osm")),
            "far_from_a_street": sum(s["far_snap"] for s in out), "dropped_by_edits": dropped,
            "moved": [{"name": p["raw"], "address": p["addr"], "moved": p["moved"]} for p in places if p["moved"]],
            "study_bbox_south_west_north_east": STUDY_BBOX,
            "attribution": "Arizona Department of Liquor Licenses and Control via City of Tucson and Pima County GIS; "
                           "(c) OpenStreetMap contributors, ODbL"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "spots": out}, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    for lim in (2, 5, 10):
        print("  within %2d min: %s" % (lim, {kd: int(sum(s["kind"] == kd and s["min"] <= lim for s in out)) for kd in KINDS}))
    print("%s  %.0f KB" % (OUT, OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
