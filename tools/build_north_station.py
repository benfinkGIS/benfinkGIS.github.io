"""Screen sites for a northern Tucson-area station on the Phoenix-Tucson passenger rail corridor.

ADOT's Service Development Plan (FRA Corridor ID program) will choose station
locations along the Union Pacific line. This script looks for land beside that
line, north of the downtown Tucson depot and inside Pima County, that could
hold a station, then asks how many residents each site would serve by car.

    py -I tools/build_north_station.py            # everything
    py -I tools/build_north_station.py --refresh  # ignore cached downloads

Sources (all keyless, read-only queries):
  Pima County GIS open data (gisdata.pima.gov): Railroads, Parcels - Regional,
  Street Network, Floodways, FEMA flood hazard zones, building footprints.
  2020 Census blocks for Pima County (cached by tools/build_network.py).

Geometry is handled in EPSG:2868 (Arizona Central state plane, international
feet), the county's native system, and written out in WGS84.

Downloads are cached in tucson-north-station/work/ (git-ignored: the parcel
file carries owner names). Published outputs go to tucson-north-station/data/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString, Point, box, mapping, shape
from shapely.ops import nearest_points, substring, transform, unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "tucson-north-station"
WORK = PROJECT / "work"
DATA = PROJECT / "data"
BLOCK_CACHE = Path(tempfile.gettempdir()) / "finkgeo_loop_cache" / "pima_blocks_2020.json"

BASE = "https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData"
RAIL = f"{BASE}/Transportation/MapServer/8"
STREETS = f"{BASE}/Transportation/MapServer/11"
PARCELS = f"{BASE}/LandRecords/MapServer/12"
BUILDINGS = f"{BASE}/LandRecords/MapServer/3"
FLOODWAY = f"{BASE}/FloodControl2/MapServer/11"
FEMA = f"{BASE}/FloodControl2/MapServer/8"

MAINLINE_OID = 12            # the UP main line, Vail to the Pinal County line
DEPOT = (-110.9654, 32.2231)  # Tucson depot, 400 N Toole Ave (lon, lat)
FT_PER_MI = 5280.0

# ---- screening assumptions (all stated on the page) -------------------------
MIN_RAIL_MI = 8.0        # closer than this to the depot is not a second station
CORRIDOR_FT = 1500.0     # how far from the track parcels are pulled
ROW_GAP_FT = 100.0       # site edge within this of the railroad's own land
MIN_FRONTAGE_FT = 800.0  # track length beside the site, enough for a platform
MIN_ACRES = 5.0          # platform, building, bus loop and a few hundred spaces
MIN_DEPTH_FT = 300.0     # land narrower than this is a strip, not a station site
HIGHWAY_INSIDE_FT = 300.0  # this much highway centre line inside a parcel = right-of-way
MAX_FLOODWAY_SHARE = 0.25
MAX_BUILT_SHARE = 0.03   # building footprint share of an "open" site
STRAIGHT_FT = 15.0       # track may bow this far from a straight line per platform

# free-flow speeds by county road category, mph (signals are not modelled)
SPEED = {
    "INTERSTATE": 65, "RMP_INT": 30, "RMP_STRT": 30, "RMP_RDMJ": 25,
    "FRNT_RD": 40, "ST_RT": 36, "LRD_MJ": 30, "LRD_MN": 20, "IND_RT": 35,
}
# places with a familiar drive time to the depot, to check the speeds against
CHECKS = {
    "Oracle Rd at Tangerine Rd (Oro Valley)": (-110.944, 32.427),
    "Sunrise Dr at Swan Rd (Foothills)": (-110.8927, 32.3085),
    "Twin Peaks Rd at I-10 (outlets)": (-111.0986, 32.3597),
    "Marana Rd at I-10": (-111.2180, 32.4570),
    "Broadway at Kolb (east side)": (-110.8410, 32.2210),
}
NO_ACCESS = {"INTERSTATE", "RMP_INT", "RMP_STRT", "RMP_RDMJ"}  # no driveways here
BANDS = (10, 15, 20, 30)
LIMITS = (15, 20, 30)    # drive limits offered on the page

to_ll = Transformer.from_crs(2868, 4326, always_xy=True)
to_sp = Transformer.from_crs(4326, 2868, always_xy=True)

session = requests.Session()
session.headers["User-Agent"] = "station-screening-script/1.0"


def query(layer: str, params: dict, tag: str, refresh: bool) -> list[dict]:
    """Paged ArcGIS query returning GeoJSON features in EPSG:2868, cached on disk."""
    WORK.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps([layer, params], sort_keys=True).encode()).hexdigest()[:12]
    path = WORK / f"{tag}_{key}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    feats, offset = [], 0
    while True:
        p = {"where": "1=1", "outFields": "*", "outSR": 2868, "f": "geojson",
             "resultOffset": offset, "resultRecordCount": 2000, "orderByFields": "OBJECTID"}
        p.update(params)
        for attempt in range(5):
            try:
                r = session.get(f"{layer}/query", params=p, timeout=120)
                r.raise_for_status()
                d = r.json()
                if "error" in d:
                    raise RuntimeError(d["error"])
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 4:
                    raise
                print(f"   retry {tag} ({e})", file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        got = d.get("features", [])
        feats.extend(got)
        if len(got) < 2000 and not d.get("exceededTransferLimit") and not d.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(got)
        if not got:
            break
    path.write_text(json.dumps(feats))
    return feats


def envelope(geom, pad: float) -> dict:
    x0, y0, x1, y1 = geom.bounds
    return {"geometry": f"{x0 - pad},{y0 - pad},{x1 + pad},{y1 + pad}",
            "geometryType": "esriGeometryEnvelope", "inSR": 2868,
            "spatialRel": "esriSpatialRelIntersects"}


def ll(geom):
    return transform(lambda x, y, z=None: to_ll.transform(x, y), geom)


# ---- 1. the rail line -------------------------------------------------------
def load_mainline(refresh: bool):
    feats = query(RAIL, {"outFields": "OBJECTID,CFCC_CD,RR_NAME"}, "rail", refresh)
    main = next(shape(f["geometry"]) for f in feats if f["properties"]["OBJECTID"] == MAINLINE_OID)
    if isinstance(main, MultiLineString):
        raise SystemExit("main line came back in pieces; check the source layer")
    depot = Point(*to_sp.transform(*DEPOT))
    # orient so that distance grows toward the northwest (Phoenix) end
    a, b = Point(main.coords[0]), Point(main.coords[-1])
    if a.y > b.y:
        main = LineString(list(main.coords)[::-1])
    m0 = main.project(depot)
    print(f"main line {main.length / FT_PER_MI:.1f} mi; depot sits {depot.distance(main):.0f} ft from it, "
          f"{(main.length - m0) / FT_PER_MI:.1f} rail mi from the county line")
    north = substring(main, m0, main.length)   # depot -> Pinal County line
    others = [shape(f["geometry"]) for f in feats if f["properties"]["OBJECTID"] != MAINLINE_OID]
    return north, others


# ---- 2. parcels beside the line ---------------------------------------------
def load_parcels(north: LineString, refresh: bool) -> list[dict]:
    fields = ("OBJECTID,PARCEL,GISACRES,JURIS_OL,CURZONE_OL,ADDRESS_OL,PARCEL_USE,"
              "MAIL1,MAIL2,FCV,LEGAL1,TAXYR")
    start = MIN_RAIL_MI * FT_PER_MI - 2640
    seen: dict[int, dict] = {}
    step = 2 * FT_PER_MI
    m = start
    while m < north.length:
        piece = substring(north, m, min(m + step, north.length))
        for f in query(PARCELS, {**envelope(piece, CORRIDOR_FT), "outFields": fields},
                       f"parcels_{int(m)}", refresh):
            seen.setdefault(f["properties"]["OBJECTID"], f)
        m += step
    corridor = north.buffer(CORRIDOR_FT)
    out = []
    for f in seen.values():
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty or not g.intersects(corridor):
            continue
        out.append({**f["properties"], "geom": g})
    print(f"{len(out)} parcels within {CORRIDOR_FT:.0f} ft of the line beyond rail mile {start / FT_PER_MI:.1f}")
    return out


def chunked(layer: str, north: LineString, tag: str, fields: str, refresh: bool, pad: float = CORRIDOR_FT):
    """Everything in a layer that touches the corridor, fetched in 2-mile envelopes."""
    seen: dict[int, dict] = {}
    m = MIN_RAIL_MI * FT_PER_MI - 2640
    step = 2 * FT_PER_MI
    while m < north.length:
        piece = substring(north, m, min(m + step, north.length))
        for f in query(layer, {**envelope(piece, pad), "outFields": fields}, f"{tag}_{int(m)}", refresh):
            if f.get("geometry"):
                seen.setdefault(f["properties"]["OBJECTID"], f)
        m += step
    out = []
    for f in seen.values():
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        if not g.is_empty:
            out.append((f["properties"], g))
    return out


# ---- 3. sites ---------------------------------------------------------------
def owner_key(name) -> str:
    return " ".join(str(name or "").upper().replace(",", " ").replace(".", " ").split())


def owner_type(name) -> str:
    n = owner_key(name)
    for prefix, label in (("UNION PACIFIC", "Union Pacific"), ("TOWN OF MARANA", "Town of Marana"),
                          ("PIMA COUNTY", "Pima County"), ("STATE OF ARIZONA", "State of Arizona"),
                          ("CITY OF TUCSON", "City of Tucson"), ("UNITED STATES", "United States")):
        if n.startswith(prefix):
            return label
    return "Private"


def use_class(code) -> str:
    c = str(code or "").strip()
    if c.startswith("00"):
        return "vacant"
    if c.startswith("4"):
        return "farm or ranch"
    if c[:2] in ("94", "95", "96", "97", "99"):
        return "public"
    if c.startswith("51"):
        return "railroad"
    if c.startswith("5"):
        return "utility"
    return "developed"


OPEN_USES = {"vacant", "farm or ranch", "public"}
PLAT_WORDS = re.compile(r"\b(BLOCK|BLKS?|SQ\d{6,})\b")   # a recorded subdivision plat, not a section description


def cautions(members, floodplain_share) -> list[str]:
    """Things the screen cannot settle but a reader should know before trusting a site."""
    out = []
    platted = any(PLAT_WORDS.search(str(m["LEGAL1"] or "").upper()) for m in members)
    kind = owner_type(members[0]["MAIL1"])
    if platted and kind != "Private":
        out.append("came to its public owner through a subdivision plat, so it may be set aside for drainage or open space")
    elif platted:
        out.append("already platted as part of a planned development")
    if any(m["use"] == "farm or ranch" for m in members):
        out.append("farmed or grazed today")
    if floodplain_share >= 0.5:
        out.append("more than half in a 1% flood zone")
    return out


def build_sites(parcels, north, buildings, floodway, sfha, highway):
    up = [p["geom"] for p in parcels
          if owner_type(p["MAIL1"]) == "Union Pacific" and p["geom"].distance(north) <= 300]
    row = unary_union(up + [north.buffer(50)])
    for p in parcels:
        p["use"] = use_class(p["PARCEL_USE"])
        p["okey"] = owner_key(p["MAIL1"])
    # a parcel with the interstate, a ramp or a frontage road running through it is
    # highway right-of-way, whatever the assessor's use code says
    open_p = [p for p in parcels if p["use"] in OPEN_USES and (p["GISACRES"] or 0) > 0.05
              and p["geom"].intersection(highway).length <= HIGHWAY_INSIDE_FT]

    # group touching open parcels that share an owner
    geoms = [p["geom"] for p in open_p]
    tree = STRtree(geoms)
    parent = list(range(len(open_p)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, g in enumerate(geoms):
        for j in tree.query(g.buffer(10)):
            if j > i and open_p[i]["okey"] == open_p[j]["okey"] and g.distance(geoms[j]) <= 10:
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(open_p)):
        groups[find(i)].append(open_p[i])

    b_tree = STRtree(buildings) if buildings else None
    sites = []
    for members in groups.values():
        geom = unary_union([m["geom"] for m in members])
        if geom.distance(row) > ROW_GAP_FT:
            continue
        # the roomy part: land outside the floodway that is at least MIN_DEPTH_FT across
        dry = geom.difference(floodway) if floodway is not None else geom
        roomy = dry.buffer(-MIN_DEPTH_FT / 2).buffer(MIN_DEPTH_FT / 2).intersection(dry)
        thin = roomy.is_empty or roomy.distance(row) > ROW_GAP_FT
        shape_used = geom if thin else roomy
        gap = shape_used.distance(row)
        # the stretch of track the site lies beside
        edge = shape_used.boundary.intersection(row.buffer(max(gap, 1) + 60))
        pts = []
        for part in getattr(edge, "geoms", [edge]):
            if part.geom_type == "LineString" and part.length > 0:
                step = max(1, int(part.length // 50))
                pts += [part.interpolate(k * part.length / step) for k in range(step + 1)]
            elif part.geom_type == "Point":
                pts.append(part)
        if not pts:
            continue
        ms = [north.project(q) for q in pts]
        m0, m1 = min(ms), max(ms)
        frontage = m1 - m0
        mid = (m0 + m1) / 2
        # least bow from a straight line over any platform-length stretch beside the site
        bow = 0.0
        if frontage >= MIN_FRONTAGE_FT:
            best, k = None, m0
            while k + MIN_FRONTAGE_FT <= m1 + 1:
                seg = substring(north, k, k + MIN_FRONTAGE_FT)
                chord = LineString([seg.coords[0], seg.coords[-1]])
                d = max(chord.distance(Point(c)) for c in seg.coords)
                best = d if best is None else min(best, d)
                k += 100
            bow = best or 0.0
        # which side of the track the site is on
        a = north.interpolate(max(mid - 50, 0))
        b = north.interpolate(min(mid + 50, north.length))
        c = geom.representative_point()
        cross = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
        side = "west" if cross > 0 else "east"
        area = geom.area
        fw = geom.intersection(floodway).area if floodway is not None else 0.0
        fz = geom.intersection(sfha).area if sfha is not None else 0.0
        built = 0.0
        if b_tree is not None:
            built = sum(buildings[j].intersection(geom).area for j in b_tree.query(geom))
        usable = 0.0 if thin else roomy.area / 43560.0
        fails = []
        if mid / FT_PER_MI < MIN_RAIL_MI:
            fails.append(f"under {MIN_RAIL_MI:.0f} rail miles from the depot")
        if thin:
            fails.append(f"nowhere {MIN_DEPTH_FT:.0f} ft deep beside the track")
        elif frontage < MIN_FRONTAGE_FT:
            fails.append(f"only {frontage:.0f} ft beside the track")
        if not thin and usable < MIN_ACRES:
            fails.append(f"{usable:.1f} usable acres")
        if fw / area > MAX_FLOODWAY_SHARE:
            fails.append(f"{100 * fw / area:.0f}% in the floodway")
        if built / area > MAX_BUILT_SHARE:
            fails.append(f"{100 * built / area:.0f}% under buildings")
        if bow > STRAIGHT_FT:
            fails.append("track curves here")
        sites.append({
            "geom": geom, "members": members, "owner": members[0]["MAIL1"],
            "owner_type": owner_type(members[0]["MAIL1"]),
            "use": sorted({m["use"] for m in members}),
            "juris": sorted({str(m["JURIS_OL"]).title() for m in members if m["JURIS_OL"]}),
            "zoning": sorted({str(m["CURZONE_OL"]) for m in members if m["CURZONE_OL"]}),
            "acres": area / 43560.0, "usable_acres": usable, "rail_mi": mid / FT_PER_MI,
            "frontage_ft": frontage, "gap_ft": gap, "bow_ft": bow, "side": side,
            "floodway_share": fw / area, "sfha_share": fz / area, "built_share": built / area,
            "platform": north.interpolate(mid), "fails": fails,
            "roomy": geom if thin else roomy, "cautions": cautions(members, fz / area),
        })
    sites.sort(key=lambda s: s["rail_mi"])
    for i, s in enumerate(sites, 1):
        s["id"] = i
    return sites, row


# ---- 4. the street network --------------------------------------------------
def load_network(refresh: bool):
    feats = query(STREETS, {"outFields": "OBJECTID,ROADCAT_CD,FINT,TINT,TRAVDIR_CD,STREET"}, "streets", refresh)
    xy: dict[int, tuple] = {}
    rows, cols, mins = [], [], []
    segs, seg_cat, seg_nodes, seg_name = [], [], [], []
    local = set()
    skipped = 0
    for f in feats:
        p = f["properties"]
        if not f.get("geometry") or p["FINT"] is None or p["TINT"] is None:
            skipped += 1
            continue
        g = shape(f["geometry"])
        if g.geom_type == "MultiLineString":
            g = max(g.geoms, key=lambda q: q.length)
        cat = p["ROADCAT_CD"]
        a, b = int(p["FINT"]), int(p["TINT"])
        xy.setdefault(a, g.coords[0][:2])
        xy.setdefault(b, g.coords[-1][:2])
        t = g.length / FT_PER_MI / SPEED.get(cat, 25) * 60.0
        d = p["TRAVDIR_CD"]
        if d in ("B", "W"):
            rows.append(a); cols.append(b); mins.append(t)
        if d in ("B", "A"):
            rows.append(b); cols.append(a); mins.append(t)
        segs.append(g); seg_cat.append(cat); seg_nodes.append((a, b)); seg_name.append(p["STREET"])
        if cat not in NO_ACCESS:
            local.update((a, b))
    ids = sorted(xy)
    idx = {n: i for i, n in enumerate(ids)}
    n = len(ids)
    r = np.array([idx[v] for v in rows]); c = np.array([idx[v] for v in cols]); w = np.array(mins)
    order = np.lexsort((w, c, r))               # keep the faster of duplicate links
    r, c, w = r[order], c[order], w[order]
    keep = np.ones(len(r), bool)
    keep[1:] = (r[1:] != r[:-1]) | (c[1:] != c[:-1])
    graph = csr_matrix((np.maximum(w[keep], 1e-4), (r[keep], c[keep])), shape=(n, n))
    coords = np.array([xy[v] for v in ids])
    print(f"street network: {len(segs)} links, {n} junctions ({skipped} links without junction ids skipped)")
    return {"graph": graph, "rgraph": graph.T.tocsr(), "coords": coords, "idx": idx, "segs": segs,
            "cat": seg_cat, "seg_nodes": seg_nodes, "name": seg_name,
            "local": np.array(sorted(idx[v] for v in local))}


def site_access(site, net, seg_tree, barriers):
    """Nearest street a driveway could reach without crossing the track or the interstate."""
    g = site["roomy"]            # the part a station would sit on, not a tail of the parcel
    best = None
    for j in seg_tree.query(g.buffer(2000)):
        if net["cat"][j] in NO_ACCESS:
            continue
        seg = net["segs"][j]
        d = g.distance(seg)
        if best is not None and d >= best[0]:
            continue
        p_site, p_seg = nearest_points(g, seg)
        if d > 1 and LineString([p_site, p_seg]).intersects(barriers):
            continue
        best = (d, j, p_seg)
    if best is None:
        return None
    d, j, p_seg = best
    a, b = net["seg_nodes"][j]
    ca, cb = net["coords"][net["idx"][a]], net["coords"][net["idx"][b]]
    node = a if p_seg.distance(Point(*ca)) <= p_seg.distance(Point(*cb)) else b
    return {"dist_ft": d, "node": net["idx"][node], "street": net["name"][j], "cat": net["cat"][j]}


def load_blocks():
    if not BLOCK_CACHE.exists():
        raise SystemExit(f"missing {BLOCK_CACHE}; run tools/build_network.py once to fetch Census blocks")
    blocks = [b for b in json.loads(BLOCK_CACHE.read_text()) if b["POP100"] > 0]
    lon = np.array([float(b["INTPTLON"]) for b in blocks])
    lat = np.array([float(b["INTPTLAT"]) for b in blocks])
    x, y = to_sp.transform(lon, lat)
    return np.column_stack([x, y]), np.array([b["POP100"] for b in blocks]), lon, lat


def times_to(net, node: int) -> np.ndarray:
    """Drive minutes from every junction to this one."""
    return dijkstra(net["rgraph"], directed=True, indices=node)


def analyse(refresh: bool):
    north, _ = load_mainline(refresh)
    parcels = load_parcels(north, refresh)
    buildings = [g for _, g in chunked(BUILDINGS, north, "bldg", "OBJECTID", refresh)]
    fw = [g for _, g in chunked(FLOODWAY, north, "floodway", "OBJECTID", refresh)]
    fema = chunked(FEMA, north, "fema", "OBJECTID,ZONE,ZONE2", refresh)
    floodway = unary_union(fw) if fw else None
    sfha_parts = [g for p, g in fema
                  if str(p.get("ZONE") or "").upper().replace("ZONE", "").strip().startswith(("A", "V"))]
    sfha = unary_union(sfha_parts) if sfha_parts else None
    print(f"{len(buildings)} building footprints, {len(fw)} floodway pieces, "
          f"{len(sfha_parts)} of {len(fema)} FEMA zones are 1% flood zones")

    net = load_network(refresh)
    seg_tree = STRtree(net["segs"])
    reach = north.buffer(CORRIDOR_FT + 500)
    highway = unary_union([s for s, c in zip(net["segs"], net["cat"])
                           if (c in NO_ACCESS or c == "FRNT_RD") and s.intersects(reach)])
    sites, row = build_sites(parcels, north, buildings, floodway, sfha, highway)
    print(f"{len(sites)} open sites beside the railroad's land; "
          f"{sum(1 for s in sites if not s['fails'])} pass the land screen")
    interstate = unary_union([s for s, c in zip(net["segs"], net["cat"]) if c == "INTERSTATE"])
    barriers = unary_union([north, interstate])
    bxy, bpop, blon, blat = load_blocks()
    local_tree = cKDTree(net["coords"][net["local"]])
    dist, j = local_tree.query(bxy)
    bnode = net["local"][j]
    last_min = dist / FT_PER_MI / 20.0 * 60.0     # the stretch off the network, 20 mph
    attached = dist <= FT_PER_MI
    total_pop = int(bpop.sum())
    print(f"{int(bpop[attached].sum()):,} of {total_pop:,} county residents attached to the network")

    depot_node = net["local"][local_tree.query(to_sp.transform(*DEPOT))[1]]
    t_depot = times_to(net, depot_node)
    D = t_depot[bnode] + last_min
    D[~attached] = np.inf
    for name, pt in CHECKS.items():
        k = net["local"][local_tree.query(to_sp.transform(*pt))[1]]
        print(f"   check: {name} to the depot {t_depot[k]:.0f} min")
    ramp_nodes = np.array(sorted({net["idx"][n] for (a, b), c in zip(net["seg_nodes"], net["cat"])
                                  if c == "RMP_INT" for n in (a, b)}))

    for s in sites:
        acc = site_access(s, net, seg_tree, barriers)
        s["access"] = acc
        if acc is None:
            s["fails"].append("no street reaches it without crossing the track or I-10")
            continue
        t_nodes = times_to(net, acc["node"]) + acc["dist_ft"] / FT_PER_MI / 15.0 * 60.0
        T = t_nodes[bnode] + last_min
        T[~attached] = np.inf
        s["t_nodes"], s["T"] = t_nodes, T
        s["within"] = {b: int(bpop[T <= b].sum()) for b in BANDS}
        s["fresh"] = {b: int(bpop[(T <= b) & (D > b)].sum()) for b in BANDS}
        s["new20"] = s["fresh"][20]
        s["closer"] = int(bpop[(T < D) & (T <= 30)].sum())
        gain = (T <= 45) & np.isfinite(D)
        s["saved_min"] = float((bpop[gain] * np.clip(D[gain] - T[gain], 0, None)).sum())
        s["to_depot_min"] = float(t_depot[acc["node"]])
        s["to_ramp_min"] = float(t_nodes[ramp_nodes].min())
    blocks = {"xy": bxy, "pop": bpop, "lon": blon, "lat": blat, "D": D, "node": bnode, "attached": attached}
    net["t_depot"] = t_depot
    net["n_parcels"] = len(parcels)
    return north, sites, row, net, blocks, total_pop


# ---- 5. outputs -------------------------------------------------------------
def ring_ll(coords, nd=5):
    xs, ys = zip(*[(c[0], c[1]) for c in coords])
    lon, lat = to_ll.transform(np.array(xs), np.array(ys))
    return [[round(float(a), nd), round(float(b), nd)] for a, b in zip(lon, lat)]


def geom_ll(geom, tol=4.0, nd=6):
    """Polygon or MultiPolygon in feet -> GeoJSON-style coordinate lists in lon/lat."""
    g = geom.simplify(tol)
    polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    out = []
    for p in polys:
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        out.append([ring_ll(p.exterior.coords, nd)] + [ring_ll(r.coords, nd) for r in p.interiors])
    return out


def drive_area(net, t_nodes, limit):
    """Rough outline of the streets reachable within the limit: quarter-mile cells
    around every junction and street point that can be reached, merged and smoothed."""
    if "samples" not in net:
        xy, ends = [], []
        for seg, (a, b) in zip(net["segs"], net["seg_nodes"]):
            n = int(seg.length // 1000)
            for k in range(1, n + 1):
                p = seg.interpolate(k * seg.length / (n + 1))
                xy.append((p.x, p.y))
                ends.append((net["idx"][a], net["idx"][b]))
        net["samples"] = (np.array(xy), np.array(ends))
    sxy, sends = net["samples"]
    ok = np.isfinite(t_nodes) & (t_nodes <= limit)
    pts = np.vstack([net["coords"][ok], sxy[ok[sends[:, 0]] & ok[sends[:, 1]]]])
    if len(pts) < 4:
        return []
    cell = 1320.0
    keys = np.unique(np.floor(pts / cell).astype(np.int64), axis=0)
    area = unary_union([box(kx * cell - 660, ky * cell - 660, (kx + 1) * cell + 660, (ky + 1) * cell + 660)
                        for kx, ky in keys])
    area = area.buffer(1000).buffer(-1400).buffer(400)
    if area.geom_type == "MultiPolygon":      # drop specks
        area = unary_union([g for g in area.geoms if g.area > 4e6])
    return geom_ll(area, tol=300, nd=4)


def letters():
    for i in range(26 * 27):
        yield chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26)


def write_outputs(north, sites, net, blocks, total_pop):
    import csv
    import datetime
    DATA.mkdir(parents=True, exist_ok=True)
    D, bpop = blocks["D"], blocks["pop"]
    lab = letters()
    out_sites, sheds = [], {}
    sheds["depot"] = {str(b): drive_area(net, net["t_depot"], b) for b in LIMITS}
    for s in sites:
        s["pass"] = not s["fails"]
        s["label"] = next(lab) if s["pass"] else None
        acc = s.get("access") or {}
        c = s["geom"].representative_point()
        lon, lat = to_ll.transform(c.x, c.y)
        plon, plat = to_ll.transform(s["platform"].x, s["platform"].y)
        owner = s["owner_type"] if s["owner_type"] != "Private" else "Private owner"
        if owner_key(s["owner"]).startswith("CORTARO-MARANA IRRIGATION"):
            owner = "Cortaro-Marana Irrigation District"
        out_sites.append({
            "id": s["id"], "label": s["label"], "pass": s["pass"], "fails": s["fails"],
            "cautions": s["cautions"],
            "mile": round(s["rail_mi"], 1), "side": s["side"],
            "acres": round(s["acres"], 1), "usable": round(s["usable_acres"], 1),
            "frontage": int(round(s["frontage_ft"], -1)), "owner": owner, "use": s["use"],
            "juris": s["juris"], "zoning": s["zoning"], "parcels": len(s["members"]),
            "floodway": round(s["floodway_share"], 3), "floodplain": round(s["sfha_share"], 3),
            "built": round(s["built_share"], 4),
            "street": str(acc.get("street") or "").title() or None,
            "street_ft": int(round(acc.get("dist_ft", 0))) if acc else None,
            "ramp_min": round(s["to_ramp_min"], 1) if "to_ramp_min" in s else None,
            "depot_min": round(s["to_depot_min"], 1) if "to_depot_min" in s else None,
            "within": {str(b): s["within"][b] for b in LIMITS} if "within" in s else None,
            "fresh": {str(b): s["fresh"][b] for b in LIMITS} if "fresh" in s else None,
            "closer": s.get("closer"), "saved_hours": round(s.get("saved_min", 0) / 60) if "saved_min" in s else None,
            "lon": round(lon, 6), "lat": round(lat, 6), "platform": [round(plon, 6), round(plat, 6)],
            "geom": geom_ll(s["geom"]),
        })
        if s["pass"]:
            sheds[s["label"]] = {str(b): drive_area(net, s["t_nodes"], b) for b in LIMITS}
    line = north.simplify(8)
    miles = []
    for mi in range(0, int(north.length / FT_PER_MI) + 1):
        p = north.interpolate(mi * FT_PER_MI)
        lon, lat = to_ll.transform(p.x, p.y)
        miles.append([mi, round(lon, 5), round(lat, 5)])
    doc = {
        "generated": datetime.date.today().isoformat(),
        "county_pop": total_pop,
        "limits": list(LIMITS),
        "depot": {"lon": DEPOT[0], "lat": DEPOT[1],
                  "within": {str(b): int(bpop[D <= b].sum()) for b in LIMITS}},
        "county_line_mi": round(north.length / FT_PER_MI, 1),
        "funnel": {"parcels": net["n_parcels"], "open_sites": len(sites),
                   "passing": sum(1 for s in sites if s["pass"])},
        "assumptions": {
            "min_rail_mi": MIN_RAIL_MI, "corridor_ft": CORRIDOR_FT, "row_gap_ft": ROW_GAP_FT,
            "min_frontage_ft": MIN_FRONTAGE_FT, "min_acres": MIN_ACRES, "min_depth_ft": MIN_DEPTH_FT,
            "max_floodway_share": MAX_FLOODWAY_SHARE, "max_built_share": MAX_BUILT_SHARE,
            "straight_ft": STRAIGHT_FT, "speeds_mph": SPEED,
        },
        "rail": ring_ll(line.coords),
        "miles": miles,
        "sites": out_sites,
        "sheds": sheds,
    }
    path = DATA / "station.json"
    path.write_text(json.dumps(doc, separators=(",", ":")))
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} KB)")

    # the review sheet keeps owner names and parcel numbers; it stays in work/
    with open(WORK / "sites_review.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "label", "pass", "rail_mi", "side", "acres", "usable_acres", "frontage_ft", "owner",
                    "use", "jurisdiction", "zoning", "floodway_pct", "floodplain_pct", "built_pct", "street",
                    "within20", "new20", "closer", "lat", "lon", "parcels", "fails"])
        for s, o in zip(sites, out_sites):
            w.writerow([s["id"], s["label"] or "", s["pass"], o["mile"], s["side"], o["acres"], o["usable"],
                        o["frontage"], s["owner"], "/".join(s["use"]), "/".join(s["juris"]), "/".join(s["zoning"]),
                        round(100 * s["floodway_share"]), round(100 * s["sfha_share"]), round(100 * s["built_share"], 1),
                        o["street"] or "", (s.get("within") or {}).get(20, ""), (s.get("fresh") or {}).get(20, ""),
                        s.get("closer", ""), o["lat"], o["lon"],
                        " ".join(str(m["PARCEL"]) for m in s["members"]), "; ".join(s["fails"])])
    print(f"wrote {(WORK / 'sites_review.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    north, sites, row, net, blocks, total_pop = analyse(args.refresh)
    write_outputs(north, sites, net, blocks, total_pop)
    D, bpop = blocks["D"], blocks["pop"]
    print(f"\nwithin 20 min of the downtown depot: {int(bpop[D <= 20].sum()):,} of {total_pop:,}")
    print("\n id  mile side  acres usable front gap  bow  fw% sfha% built% |    w10     w15     w20   new20  closer saved(k) ramp depot | owner / use / zoning / street / fails")
    for s in sites:
        w = s.get("within", {})
        acc = s.get("access") or {}
        print(f"{s['id']:3d} {s['rail_mi']:5.1f} {s['side']:4s} {s['acres']:6.1f} {s['usable_acres']:6.1f} {s['frontage_ft']:5.0f} "
              f"{s['gap_ft']:3.0f} {s['bow_ft']:4.0f} {100*s['floodway_share']:4.0f} {100*s['sfha_share']:5.0f} {100*s['built_share']:5.1f} | "
              f"{w.get(10,0):6,d} {w.get(15,0):7,d} {w.get(20,0):7,d} {s.get('new20',0):7,d} {s.get('closer',0):7,d} {s.get('saved_min',0)/1000:7.0f} "
              f"{s.get('to_ramp_min',float('nan')):5.1f} {s.get('to_depot_min',float('nan')):5.1f} | {s['owner']} / {','.join(s['use'])} / {','.join(s['zoning'])} / "
              f"{acc.get('street')} {acc.get('dist_ft',0):.0f}ft / {'; '.join(s['fails'])}")
