#!/usr/bin/env python3
"""DRAFT: summarise who lives close to The Loop and who lives far from it, for the
closer-vs-farther page (tools/loop-review/access.html).

Usage (from the repo root, after tools/build_loop.py and tools/build_network.py):
    py tools/build_access.py             # uses cached downloads where it has them
    py tools/build_access.py --refresh   # download the place boundaries again

Reads   tools/loop-review/blocks.geojson      one point per populated Census block, with its
                                              baseline ride time to the Loop
        tools/loop-review/loop_draft.geojson  the draft Loop
Writes  tools/loop-review/access.json         everything the page draws:
          bands    residents by ride-time band (the whole study area split five ways)
          far      residents farther than each threshold in THRESHOLDS
          places   the same, per city / town / census-designated place
          hexes    the same, per map cell (hexagons HEX_R_M metres from centre to corner)

"Ride time" is the unweighted baseline from build_network.py: shortest legal route at 10 mph,
with no allowance for how stressful the streets are. Treat the numbers as a first cut.

Place boundaries: U.S. Census Bureau TIGERweb, 2020 Census vintage (public domain). A block
belongs to the place its internal point falls in.
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
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from build_loop import UA
from build_network import M_LAT, M_LON, SPEED_MPH, STUDY_BBOX, fetch_blocks

THRESHOLDS = (10, 15, 20, 30)                     # minutes; "far" = more than this
BAND_EDGES = (0, 10, 15, 20, 30, math.inf)        # the five bands of the split bar
HEX_R_M = 800.0                                   # hexagon size: centre to corner, metres
PLACES = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/%d/query"
PLACE_LAYERS = {25: "incorporated", 26: "census-designated"}   # Census 2020 vintage
NO_PLACE = "Outside any city or named community"
OUT_DIR = Path(__file__).resolve().parent / "loop-review"


def fetch_places(cache, refresh):
    f = cache / "pima_places_2020.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text(encoding="utf-8"))
    s, w, n, e = STUDY_BBOX
    out = []
    for layer, kind in PLACE_LAYERS.items():
        q = urllib.parse.urlencode({
            "geometry": "%f,%f,%f,%f" % (w, s, e, n), "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "GEOID,NAME,BASENAME", "outSR": 4326,
            "returnGeometry": "true", "f": "geojson"})
        for attempt in range(4):
            try:
                req = urllib.request.Request(PLACES % layer + "?" + q, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=180) as r:
                    d = json.loads(r.read().decode("utf-8"))
                if "error" in d or "features" not in d:
                    raise RuntimeError(str(d)[:200])
                break
            except Exception as ex:
                print("  TIGERweb places: %s" % ex, file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit("TIGERweb failed; nothing written.")
        for ft in d["features"]:
            p = ft["properties"]
            out.append({"geoid": p["GEOID"], "name": p["BASENAME"], "full_name": p["NAME"], "kind": kind,
                        "geometry": ft["geometry"]})
    f.write_text(json.dumps(out), encoding="utf-8")
    return out


def hex_of(x, y):
    """Axial (q, r) of the pointy-top hexagon containing the point (metres)."""
    q = (math.sqrt(3) / 3 * x - y / 3) / HEX_R_M
    r = (2 / 3 * y) / HEX_R_M
    cx, cz = q, r
    cy = -cx - cz
    rx, ry, rz = round(cx), round(cy), round(cz)
    dx, dy, dz = abs(rx - cx), abs(ry - cy), abs(rz - cz)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy <= dz:
        rz = -rx - ry
    return int(rx), int(rz)


def hex_ring(q, r):
    cx, cy = HEX_R_M * math.sqrt(3) * (q + r / 2), HEX_R_M * 1.5 * r
    ring = [[round((cx + HEX_R_M * math.cos(math.radians(30 + 60 * k))) / M_LON, 5),
             round((cy + HEX_R_M * math.sin(math.radians(30 + 60 * k))) / M_LAT, 5)] for k in range(6)]
    return ring + ring[:1]


def far_counts(minutes, pop):
    return {str(t): int(pop[minutes > t].sum()) for t in THRESHOLDS}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache-dir", default=str(Path(tempfile.gettempdir()) / "finkgeo_loop_cache"))
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    blocks_fc = json.loads((OUT_DIR / "blocks.geojson").read_text(encoding="utf-8"))
    feats = blocks_fc["features"]
    lon = np.array([f["geometry"]["coordinates"][0] for f in feats])
    lat = np.array([f["geometry"]["coordinates"][1] for f in feats])
    pop = np.array([f["properties"]["pop"] for f in feats])
    mins = np.array([f["properties"]["min"] for f in feats])
    total = int(pop.sum())

    # ---- bands and thresholds for the whole study area ----
    labels = ["10 min or less", "10 to 15 min", "15 to 20 min", "20 to 30 min", "Over 30 min"]
    bands = [{"label": labels[i], "lo": BAND_EDGES[i], "hi": None if math.isinf(BAND_EDGES[i + 1]) else BAND_EDGES[i + 1],
              "pop": int(pop[(mins > BAND_EDGES[i]) & (mins <= BAND_EDGES[i + 1]) | ((i == 0) & (mins <= BAND_EDGES[1]))].sum())}
             for i in range(5)]
    assert sum(b["pop"] for b in bands) == total, "bands do not add up"

    # ---- per place ----
    places = fetch_places(cache, args.refresh)
    geoms = [shape(p["geometry"]) for p in places]
    tree = STRtree(geoms)
    which = np.full(len(feats), -1)
    for i in range(len(feats)):
        pt = Point(lon[i], lat[i])
        for k in tree.query(pt):
            if geoms[int(k)].contains(pt):
                which[i] = int(k)
                break
    rows = []
    for k, p in enumerate(places):
        m = which == k
        if pop[m].sum() > 0:
            rows.append({"name": p["name"], "kind": p["kind"], "pop": int(pop[m].sum()), "far": far_counts(mins[m], pop[m])})
    m = which == -1
    rows.append({"name": NO_PLACE, "kind": "none", "pop": int(pop[m].sum()), "far": far_counts(mins[m], pop[m])})
    assert sum(r["pop"] for r in rows) == total, "places do not add up"
    rows.sort(key=lambda r: -r["pop"])

    # ---- per hexagon ----
    cells = collections.defaultdict(list)
    for i in range(len(feats)):
        cells[hex_of(lon[i] * M_LON, lat[i] * M_LAT)].append(i)
    hexes = []
    for (q, r), idx in cells.items():
        idx = np.array(idx)
        p = pop[idx]
        hexes.append({"ring": hex_ring(q, r), "pop": int(p.sum()),
                      "far": [int(p[mins[idx] > t].sum()) for t in THRESHOLDS],
                      "min": round(float((mins[idx] * p).sum() / p.sum()), 1)})
    assert sum(h["pop"] for h in hexes) == total, "hexagons do not add up"

    # ---- county residents outside the study area: how far from the Loop in a straight line? ----
    loop = json.loads((OUT_DIR / "loop_draft.geojson").read_text(encoding="utf-8"))
    lxy = np.array([[c[0] * M_LON, c[1] * M_LAT] for f in loop["features"] for c in f["geometry"]["coordinates"]])
    s, w, n, e = STUDY_BBOX
    outside = [b for b in fetch_blocks(cache, False)
               if (b["POP100"] or 0) > 0 and not (s <= float(b["INTPTLAT"]) <= n and w <= float(b["INTPTLON"]) <= e)]
    oxy = np.array([[float(b["INTPTLON"]) * M_LON, float(b["INTPTLAT"]) * M_LAT] for b in outside])
    opop = np.array([b["POP100"] for b in outside])
    odist_mi = cKDTree(lxy).query(oxy)[0] / 1609.344
    out_note = {"population": int(opop.sum()), "nearest_straight_line_miles": round(float(odist_mi.min()), 1),
                "population_within_5_straight_line_miles": int(opop[odist_mi < 5].sum())}

    data = {"meta": {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                     "status": "DRAFT baseline: shortest legal route at %g mph, no traffic-stress weighting" % SPEED_MPH["bike"],
                     "population": total, "thresholds": list(THRESHOLDS), "hex_radius_m": HEX_R_M,
                     "study_bbox_south_west_north_east": list(STUDY_BBOX), "outside_study_area": out_note,
                     "loop_miles": loop.get("metadata", {}).get("miles_total")},
            "bands": bands, "far": far_counts(mins, pop), "places": rows, "hexes": hexes}
    (OUT_DIR / "access.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    print("study-area residents:", total)
    for b in bands:
        print("  %-16s %8d  %4.1f%%" % (b["label"], b["pop"], 100 * b["pop"] / total))
    print("farther than:", {t: "%d (%.1f%%)" % (v, 100 * v / total) for t, v in data["far"].items()})
    print("hexagons:", len(hexes), "| places with residents:", len(rows) - 1)
    print("outside the study area:", out_note)
    print("places by residents more than 20 min away:")
    for r in sorted(rows, key=lambda r: -r["far"]["20"])[:14]:
        print("  %-40s pop %7d  far20 %7d (%4.1f%%)" % (r["name"], r["pop"], r["far"]["20"], 100 * r["far"]["20"] / max(r["pop"], 1)))


if __name__ == "__main__":
    main()
