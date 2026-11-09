#!/usr/bin/env python3
"""Build tucson-golf-water/data/courses.geojson from OpenStreetMap.

Usage (from the repo root):
    py tools/build_courses.py                 # query Overpass, write the GeoJSON
    py tools/build_courses.py --cache raw.json  # reuse a saved Overpass response

Needs Python 3 and shapely (pip install shapely). Not part of the site itself:
the site only serves the GeoJSON this script writes.

What "active" means here
------------------------
OpenStreetMap has no disused/abandoned golf courses in this area, so a course
that has closed is usually still tagged leisure=golf_course. "Active" therefore
means: mapped as a golf course in OSM *and* not on the EXCLUDE list below.
EXCLUDE records courses confirmed closed from news reports. It is a hand-kept
list, so re-check it whenever the data is refreshed.

Data: (c) OpenStreetMap contributors, ODbL. https://www.openstreetmap.org/copyright
"""
import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

# ---- study area ---------------------------------------------------------
CENTER = (-110.9747, 32.2226)          # downtown Tucson (lon, lat)
RADIUS_MI = 32                         # "Tucson area" = within ~32 miles of downtown
BBOX = (31.6, -111.6, 32.8, -110.3)    # S, W, N, E: wide net; RADIUS_MI does the real cut

OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
UA = "finkgeo-golf-map/0.1 (personal project; https://finkgeo.com)"

# ---- hand-kept decisions (OSM type+id, e.g. "relation/3535718") ----------
# Closed courses that OSM still shows as golf courses.
EXCLUDE_CLOSED = {
    "relation/3535788": "Del Lago Golf Club (Vail): closed after final round 9 Aug 2026. "
                        "https://www.kold.com/2026/08/07/del-lago-golf-club-closure-threatens-vail-economy-leaves-employees-searching-work/",
    "way/263254191": "Quail Canyon Golf Course: closed years ago; site rezoned for housing by Pima County. "
                     "https://www.kgun9.com/news/local-news/pima-county-board-of-supervisors-approve-rezoning-of-quail-canyon-golf-course-for-housing-developments",
    "way/159516471": "General William Blanchard Golf Course (Davis-Monthan AFB): closed 1 May 2018. "
                     "https://www.dm.af.mil/Media/Article/1493568/blanchard-golf-course-to-close/",
}
# Mapping artifacts rather than separate courses.
EXCLUDE_TECHNICAL = {
    "relation/3552031": "El Conquistador resort outline; covered by its Cañada, Conquistador and Pusch Ridge courses.",
    "relation/3535718": "Randolph Golf Complex outline; covered by the Randolph (North) and Dell Urich courses.",
    "way/1108352200": "0.2-acre unnamed sliver next to the closed Del Lago course.",
    "node/1338978085": "Point feature for the JW Marriott resort; the Starr Pass polygon is used instead.",
}
# Boundaries checked against the imagery and found wanting; shown in the popup.
QUALITY_NOTES = {
    "relation/3548873": "OpenStreetMap outlines only part of this course (checked against the imagery, Nov 2026).",
}
# Unnamed polygons that belong to a named course: {child: parent}.
MERGE_INTO = {
    "way/706498984": "relation/3540481",   # extra nine of Omni Tucson National, 29 m away
}

# ---- water use: Pima County memo (tools/pima_golf_water_memo.json) ------
# Every mapped course needs a decision here, so a refresh that brings in a new course
# fails loudly instead of silently showing no water data.
#   rows:     memo row keys whose figures belong to the course (summed when more than one)
#   separate: show the rows as separate lines instead of adding them
#   note:     extra caveat shown in the popup
WATER_MATCH = {
    "relation/3524420": {"rows": ["arizona_national"]},                      # Arizona National
    "relation/3534980": {"rows": ["canoa_ranch"]},                           # Canoa Ranch
    "relation/12736703": {"rows": ["el_conquistador"], "note": "El Conquistador's two 18-hole courses (Conquistador and Cañada) share one figure in the county memo, so the same number appears on both. Do not add them."},   # Cañada
    "way/264353987": {"rows": ["el_conquistador"], "note": "El Conquistador's two 18-hole courses (Conquistador and Cañada) share one figure in the county memo, so the same number appears on both. Do not add them."},      # Conquistador
    "relation/3557520": {"rows": ["cc_green_valley"]},                       # Country Club of Green Valley
    "way/263321891": {"rows": ["crooked_tree"]},                             # Crooked Tree
    "relation/12317450": {"rows": ["dell_urich"]},                           # Dell Urich
    "way/263223599": {"rows": ["desert_hills"]},                             # Desert Hills
    "relation/3149820": {"rows": ["dorado"]},                                # Dorado
    "relation/14083323": {"rows": ["el_rio"]},                               # El Rio
    "relation/3295540": {"rows": ["forty_niners"]},                          # Forty Niner
    "way/263348234": {"rows": ["fred_enke"]},                                # Fred Enke
    "relation/3524385": {"rows": ["haven"]},                                 # Haven
    "relation/3521496": {"rows": ["la_paloma"]},                             # La Paloma
    "relation/3540481": {"rows": ["omni_tucson_national"]},                  # Omni Tucson National
    "relation/3540695": {"rows": ["oro_valley_cc"]},                         # Oro Valley CC
    "relation/3540824": {"rows": ["pusch_ridge"], "note": "Matched to the memo's 'Pusch Ridge Hilton Resort' entry (9 holes, same Oro Valley resort)."},    # Pusch Ridge
    "relation/3545614": {"rows": ["quail_creek"], "note": "This is the largest figure in the memo and is reclaimed water delivered to a recharge facility, so it may not be comparable to other courses' irrigation use."},  # Quail Creek
    "way/263063105": {"rows": ["quarry_pines"]},                             # Quarry Pines
    "relation/12317451": {"rows": ["randolph"]},                             # Randolph (North)
    "relation/3540831": {"rows": ["rolling_hills"]},                         # Rolling Hills
    "relation/3535021": {"rows": ["san_ignacio"]},                           # San Ignacio
    "way/875644322": {"rows": ["sewailo"], "note": "Last reported to ADWR in 2017, per the memo."},               # Sewailo
    "way/263136208": {"rows": ["silverbell"]},                               # Silverbell
    "relation/3255194": {"rows": ["skyline"]},                               # Skyline
    "relation/14067367": {"rows": ["starr_pass"]},                           # Starr Pass
    "relation/20674321": {"rows": ["gallery_dove_mt", "gallery_south"], "separate": True, "note": "The memo lists two entries for The Gallery and does not say whether the 36-hole entry already includes the South course, so they are shown separately, not added."},   # The Gallery
    "relation/3526798": {"rows": ["dove_mt_1", "dove_mt_2"], "note": "The memo lists this 27-hole course under two facility numbers (546.36 and 299.04 acre-feet); the figure above is their sum."},       # The Golf Club at Dove Mountain
    "relation/3286601": {"rows": ["highlands"]},                             # The Highlands at Dove Mountain
    "relation/21163920": {"rows": ["stone_canyon"]},                         # The Stone Canyon Club
    "relation/3533856": {"rows": ["views_sun_city_vistoso"]},                # The Views
    "relation/3523210": {"rows": ["torres_blancas"]},                        # Torres Blancas
    "way/108291873": {"rows": ["tucson_cc"]},                                # Tucson Country Club
    "way/262948500": {"rows": ["tucson_estates"]},                           # Tucson Estates
    "relation/14061123": {"rows": ["ventana_canyon"]},                       # Ventana Canyon
}
# Courses with no memo figure, and why (shown in the popup).
NO_WATER = {
    "relation/3535004": "Not listed in the county memo.",                                  # Canoa Hills
    "way/191987768": "Not listed in the county memo.",                                     # Voyager RV Resort
    "way/264439629": "Not in the county memo, which covers Pima County; this course is in Pinal County.",   # Mountain View (SaddleBrooke)
    "way/264466053": "Not in the county memo, which covers Pima County; this course is in Pinal County.",   # The Preserve (SaddleBrooke)
    "way/264149657": "Not in the county memo, which covers Pima County; this course is in Pinal County.",   # SaddleBrooke One
    "relation/3548873": "Not in the county memo, which covers Pima County; this course is in Pinal County.",# SaddleBrooke Ranch
}
WATER_MEMO = Path(__file__).with_name("pima_golf_water_memo.json")


def water_for(key, memo):
    """The 'water' property for one course, from the transcribed county memo."""
    if key in NO_WATER:
        return {"none": NO_WATER[key]}
    m = WATER_MATCH[key]
    rows = [memo["rows"][k] for k in m["rows"]]
    notes = [m["note"]] if m.get("note") else []
    notes += [r["memo_note"] for r in rows if r.get("memo_note")]
    out = {
        "memo_name": " + ".join(r["memo_name"] for r in rows),
        "source_text": rows[0]["source_text"],
    }
    if m.get("separate"):
        out["year"] = rows[0]["year"]
        out["items"] = [[f'{r["memo_name"]} ({r["holes"]} holes)', round(sum(a for _, a in r["use"]), 2)] for r in rows]
    else:
        years = {r["year"] for r in rows}
        assert len(years) == 1, f"{key}: memo rows have different years {years}"
        mix = {}
        for r in rows:
            for label, af in r["use"]:
                mix[label] = round(mix.get(label, 0) + af, 2)
        out["year"] = years.pop()
        out["af"] = round(sum(mix.values()), 2)
        out["mix"] = [[label, af] for label, af in mix.items()]
    out["supply"] = list(dict.fromkeys(label for r in rows for label, af in r["use"] if af > 0))
    if notes:
        out["note"] = " ".join(notes)
    return out


def log(*a):
    print(*a, file=sys.stderr)


def fetch(cache):
    if cache:
        return json.loads(Path(cache).read_text(encoding="utf-8"))
    s, w, n, e = BBOX
    query = f'[out:json][timeout:120];nwr["leisure"="golf_course"]({s},{w},{n},{e});out geom;'
    body = urllib.parse.urlencode({"data": query}).encode()
    wait = 5
    for attempt in range(1, 7):
        for url in OVERPASS:
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as ex:  # public Overpass servers are often busy
                log(f"  {url} failed (attempt {attempt}): {ex}")
        time.sleep(wait)
        wait *= 2
    sys.exit("Overpass unavailable; try again later or pass --cache.")


def lonlat(pts):
    return [(p["lon"], p["lat"]) for p in pts]


def element_geometry(e):
    """Polygon/MultiPolygon for a way or multipolygon relation, else None."""
    if e["type"] == "way":
        pts = lonlat(e.get("geometry", []))
        if len(pts) >= 4 and pts[0] == pts[-1]:
            return Polygon(pts).buffer(0)
        return None
    if e["type"] == "relation":
        def lines(role_is_inner):
            return [LineString(lonlat(m["geometry"])) for m in e.get("members", [])
                    if m["type"] == "way" and m.get("geometry")
                    and (m.get("role") == "inner") == role_is_inner]
        outer, inner = lines(False), lines(True)
        if not outer:
            return None
        g = unary_union(list(polygonize(unary_union(outer))))
        if inner:
            g = g.difference(unary_union(list(polygonize(unary_union(inner)))))
        return g if not g.is_empty else None
    return None


def acres(g):
    """Approximate area in acres using a local equirectangular projection."""
    c = g.centroid
    kx = 111320 * math.cos(math.radians(c.y))
    return affinity.scale(g, kx, 110574, origin=(0, 0)).area / 4046.856


def miles_from_center(g):
    c = g.centroid
    dx = (c.x - CENTER[0]) * 111320 * math.cos(math.radians(CENTER[1]))
    dy = (c.y - CENTER[1]) * 110574
    return math.hypot(dx, dy) / 1609.34


def round_coords(obj, nd=6):
    if isinstance(obj, (list, tuple)):
        return [round_coords(x, nd) for x in obj]
    return round(obj, nd) if isinstance(obj, float) else obj


def holes_label(tags):
    c = tags.get("golf:course", "")
    return c.replace("_hole", "") if c.endswith("_hole") else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="saved Overpass JSON to use instead of querying")
    ap.add_argument("--out", default="tucson-golf-water/data/courses.geojson")
    args = ap.parse_args()

    raw = fetch(args.cache)
    stamp = raw.get("osm3s", {}).get("timestamp_osm_base", "")

    items = {}
    for e in raw["elements"]:
        key = f'{e["type"]}/{e["id"]}'
        items[key] = (e, element_geometry(e))

    kept, dropped = {}, []
    for key, (e, g) in items.items():
        tags = e.get("tags", {})
        label = tags.get("name") or key
        if key in EXCLUDE_CLOSED:
            dropped.append((label, "closed", EXCLUDE_CLOSED[key].split(" http")[0]))
        elif key in EXCLUDE_TECHNICAL:
            dropped.append((label, "technical", EXCLUDE_TECHNICAL[key]))
        elif g is None:
            dropped.append((label, "no polygon", key))
        elif miles_from_center(g) > RADIUS_MI:
            dropped.append((label, "outside area", f"{miles_from_center(g):.0f} mi from downtown"))
        elif key not in MERGE_INTO:
            kept[key] = (e, g)

    for child, parent in MERGE_INTO.items():
        if parent in kept and items[child][1] is not None:
            e, g = kept[parent]
            kept[parent] = (e, unary_union([g, items[child][1]]))

    unnamed = [k for k, (e, _) in kept.items() if not e.get("tags", {}).get("name")]
    if unnamed:
        sys.exit(f"Unnamed features need a decision (EXCLUDE_* or MERGE_INTO): {unnamed}")

    memo = json.loads(WATER_MEMO.read_text(encoding="utf-8"))
    undecided = [f'{k} ({e["tags"]["name"]})' for k, (e, _) in kept.items() if k not in WATER_MATCH and k not in NO_WATER]
    if undecided:
        sys.exit(f"Courses need a water-use decision (WATER_MATCH or NO_WATER): {undecided}")
    stale = [k for k in list(WATER_MATCH) + list(NO_WATER) if k not in kept]
    if stale:
        log(f"Note: water rules for courses no longer on the map: {stale}")
    used_rows = {r for m in WATER_MATCH.values() for r in m["rows"]}
    unused = [k for k, r in memo["rows"].items() if k not in used_rows and not r.get("closed")]
    if unused:
        log(f"Note: memo rows not matched to any mapped course: {unused}")

    features = []
    for key, (e, g) in sorted(kept.items(), key=lambda kv: kv[1][0]["tags"]["name"].lower()):
        t = e["tags"]
        if isinstance(g, MultiPolygon):
            g = MultiPolygon([orient(p) for p in g.geoms])
        else:
            g = orient(g)
        g = g.simplify(0.00001, preserve_topology=True)   # ~1 m
        props = {
            "name": t["name"],
            "acres": round(acres(g)),
            "osm": f"https://www.openstreetmap.org/{key}",
        }
        if t.get("access"):
            props["access"] = t["access"]
        if holes_label(t):
            props["holes"] = holes_label(t)
        if t.get("website"):
            props["website"] = t["website"]
        if key in QUALITY_NOTES:
            props["note"] = QUALITY_NOTES[key]
        props["water"] = water_for(key, memo)
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": g.geom_type, "coordinates": round_coords(mapping(g)["coordinates"])},
        })

    out = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "OpenStreetMap contributors (ODbL), leisure=golf_course, via Overpass API",
            "osm_data_timestamp": stamp,
            "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "area": f"within {RADIUS_MI} miles of downtown Tucson",
            "water_source": f'{memo["source"]["title"]}, {memo["source"]["publisher"]}, {memo["source"]["date"]}',
            "water_source_url": memo["source"]["url"],
            "excluded_closed": [
                v.split(" http")[0] for v in EXCLUDE_CLOSED.values()
            ],
        },
        "features": features,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    log(f"Kept {len(features)} courses -> {path} ({path.stat().st_size / 1024:.0f} KB), OSM data as of {stamp}")
    log("Dropped:")
    for label, why, note in sorted(dropped, key=lambda d: (d[1], d[0])):
        log(f"  [{why}] {label}: {note}")


if __name__ == "__main__":
    main()
