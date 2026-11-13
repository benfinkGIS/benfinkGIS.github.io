#!/usr/bin/env python
"""Empty Homes: count winter homes, vacant homes and unfinished buildings in Pima County.

Writes empty-homes/data/empty.json, which the page at /empty-homes/ reads.

    py tools/build_empty_homes.py            # uses downloads cached in empty-homes/work/raw
    py tools/build_empty_homes.py --refresh  # download everything again (about 10 minutes)

Sources (all public, no key):
  - Parcels: City of Tucson / Pima County parcel layer (use code, owner mailing address, value).
  - Legal class: Pima County Assessor "Class Master" files for two tax years.
  - Vacancy: Census ACS 2020-2024 5-year tables B25002 and B25004 (summary files).
  - Vacant-building cases: City of Tucson code enforcement cases.
  - Boundaries: Census TIGER 2020 tracts and places.

A "winter home" here is a house, condo/townhome or manufactured home that
  1. the Assessor taxes as legal class 4.1 (not a primary residence, not a registered rental),
  2. has its tax bill mailed outside Arizona,
  3. is owned by a person or family trust, not a company, and
  4. is not on Mt Lemmon (ZIP 85619).
Winter homes are published only as counts per hexagon, never as points, and never with owner names.
"""
import argparse, collections, csv, datetime, io, json, math, re, statistics, sys, time, zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "empty-homes" / "work" / "raw"
OUT = ROOT / "empty-homes" / "data" / "empty.json"

PARCELS = "https://gis.tucsonaz.gov/public/rest/services/IT/ZoomTucson/MapServer/32/query"
CASES = "https://mapdata.tucsonaz.gov/arcgis/rest/services/PublicMaps/PermitsCode/MapServer/102/query"
CLASS_URL = "https://www.asr.pima.gov/Downloads/Data/realprop/20{y}/noticeval/ClsMst{y}.ZIP"
CLASS_YEARS = (27, 26)                  # tax years 2027 and 2026: the two the Assessor publishes
ACS_YEAR = 2024
ACS_URL = ("https://www2.census.gov/programs-surveys/acs/summary_file/{y}/"
           "table-based-SF/data/5YRData/acsdt5y{y}-{t}.dat")
TIGER = "https://www2.census.gov/geo/tiger/TIGER2020/{kind}/tl_2020_04_{name}.zip"
COUNTY, TUCSON = "0500000US04019", "1600000US0477000"

# Point-in-Time Count, Tucson Pima Collaboration to End Homelessness (entered by hand from the release)
HOMELESS = {"count": 2130, "date": "2026-01-27", "prior": 2218, "prior_year": 2025}

HOME_TYPES = {"RES SINGLE FAM": "house", "RES COND/TWHS": "condo", "RES MOBL HM SUJ AFF": "manufactured",
              "RES SUB MOBL HM": "manufactured", "RES UNS MOBL HM": "manufactured"}
PRIMARY = {"03.01", "03.02", "03.03"}
COMPANY = re.compile(r"\b(LLC|L L C|INC|CORP|CORPORATION|LP|LLP|LLLP|LTD|BANK|COMPANY|PROPERTIES|HOLDINGS|"
                     r"INVESTMENTS?|HOMES|PARTNERS|PARTNERSHIP|ASSOCIATION|ASSN|ASSOC|HOA|FUND|FUNDING|CAPITAL|"
                     r"REALTY|VENTURES|GROUP|ENTERPRISES|BORROWER|MORTGAGE|FEDERAL|SECRETARY|HOUSING|CHURCH|"
                     r"FOUNDATION|UNIVERSITY|CITY OF|COUNTY|STATE OF|UNITED STATES|RENTALS?|SFR|REO|OWNER)\b")
LEMMON_ZIP = "85619"
HEX_M = 800            # hexagon size (centre to corner), metres
HEX_MIN = 5            # hexagons with fewer winter homes are counted but not drawn
PLACE_MIN_HOMES = 1500
VACANT_CASE_TYPES = ("Vacant/Nuisance Buildings", "VANS Program", "Lien Foreclosure Program")
UNFINISHED_HOMES = {"2801": "house", "2887": "house", "2803": "apartments", "2807": "condo"}
JAM = -1e8             # ACS writes large negative numbers where it has no estimate
UA = {"User-Agent": "Mozilla/5.0 (build_empty_homes)"}


def get(url, tries=5, **kw):
    for i in range(tries):
        try:
            r = requests.request(kw.pop("method", "GET"), url, timeout=180, headers=UA, **kw)
            if r.status_code == 200:
                return r
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = str(e)
        time.sleep(4 * (i + 1))
    sys.exit(f"gave up on {url}: {err}")


def arcgis_rows(url, where, fields):
    """Every row matching `where`, paged by OBJECTID (attributes only)."""
    rows, last = [], -1
    while True:
        d = get(url, method="POST", data={"where": f"({where}) AND OBJECTID>{last}", "outFields": "OBJECTID," + fields,
                                          "returnGeometry": "false", "orderByFields": "OBJECTID", "f": "json"}).json()
        if "error" in d:
            sys.exit(f"{url}: {d['error']}")
        got = [f["attributes"] for f in d.get("features", [])]
        if not got:
            return rows
        rows += got
        last = got[-1]["OBJECTID"]
        if len(rows) % 40000 < len(got):
            print(f"  {len(rows):,} rows", flush=True)


def cached_json(name, refresh, make):
    path = RAW / name
    if path.exists() and not refresh:
        if name.endswith(".jsonl"):
            return [json.loads(line) for line in path.open(encoding="utf-8")]
        return json.loads(path.read_text(encoding="utf-8"))
    data = make()
    if name.endswith(".jsonl"):
        path.write_text("".join(json.dumps(r) + "\n" for r in data), encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")
    return data


def improvement_classes(yy, refresh):
    """Parcel -> set of legal classes on its improvement (the building), from the Class Master file."""
    path = RAW / f"ClsMst{yy}.ZIP"
    if not path.exists() or refresh:
        path.write_bytes(get(CLASS_URL.format(y=yy)).content)
    out = collections.defaultdict(set)
    z = zipfile.ZipFile(path)
    member = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    with z.open(member) as f:
        rd = csv.reader(io.TextIOWrapper(f, encoding="latin-1", newline=""))
        next(rd); next(rd)
        for r in rd:
            if len(r) >= 8 and r[4].strip() == "I":
                out[r[1].strip()].add(r[7].strip())
    return out


def acs(table, refresh):
    """County, Tucson and Pima tract rows of one ACS table, as {GEO_ID: {column: number}}."""
    path = RAW / f"acs{ACS_YEAR}_{table}.psv"
    if not path.exists() or refresh:
        kept, first = [], True
        with get(ACS_URL.format(y=ACS_YEAR, t=table), stream=True) as r:
            r.encoding = "utf-8"
            for line in r.iter_lines(decode_unicode=True):
                if first or line.startswith(("1400000US04019", COUNTY, TUCSON)):
                    kept.append(line)
                first = False
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        print(f"ACS {table}: {len(kept) - 1} rows")
    df = pd.read_csv(path, sep="|", dtype={"GEO_ID": str}).set_index("GEO_ID")
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.where(df > JAM)


def shapes(kind, name, refresh):
    folder = RAW / f"tl_2020_04_{name}"
    if not folder.exists() or refresh:
        z = zipfile.ZipFile(io.BytesIO(get(TIGER.format(kind=kind, name=name)).content))
        folder.mkdir(parents=True, exist_ok=True)
        for m in z.namelist():                       # flat extract, known extensions only
            if Path(m).suffix.lower() in {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
                (folder / Path(m).name).write_bytes(z.read(m))
    return gpd.read_file(next(folder.glob("*.shp")))


def med(values):
    values = [v for v in values if v]
    return round(statistics.median(values)) if values else None


def day(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date() if ms else None


def rings(geom, nd=4):
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    return [[[round(x, nd), round(y, nd)] for x, y in p.exterior.coords] for p in polys if not p.is_empty]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="download everything again")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today()

    # ---------- homes and their legal class ----------
    print("parcels")
    parcels = cached_json("res_parcels.jsonl", a.refresh, lambda: arcgis_rows(
        PARCELS, "PPT_DESC='Residential'",
        "PARCEL,PARCEL_USE,SPT_DESC,MAIL1,CITY,STATE_PROVINCE,COUNTRY,POSTAL_CODE,SITE_ZIP,JURIS_OL,FCV,LON,LAT"))
    now, before = (improvement_classes(y, a.refresh) for y in CLASS_YEARS)

    seen, homes = set(), []
    for p in parcels:
        kind = HOME_TYPES.get((p["SPT_DESC"] or "").strip())
        if not kind or p["PARCEL"] in seen:
            continue
        seen.add(p["PARCEL"])
        cl = now.get(p["PARCEL"], set())
        state, country = (p["STATE_PROVINCE"] or "").strip(), (p["COUNTRY"] or "").strip()
        homes.append({
            "parcel": p["PARCEL"], "kind": kind, "fcv": p["FCV"], "lon": p["LON"], "lat": p["LAT"],
            "cls": "4.1" if cl == {"04.01"} else "3" if cl and cl <= PRIMARY else "other",
            "same_before": before.get(p["PARCEL"]) == {"04.01"},
            "away": not (state == "AZ" and not country),
            "from": "Canada" if country.upper() == "CANADA" else (state if state and not country else "Other countries"),
            "company": bool(COMPANY.search((p["MAIL1"] or "").upper())),
            "lemmon": (p["SITE_ZIP"] or "").strip() == LEMMON_ZIP,
            "juris": (p["JURIS_OL"] or "").strip().title(),
        })
    c41 = [h for h in homes if h["cls"] == "4.1"]
    away = [h for h in c41 if h["away"]]
    people = [h for h in away if not h["company"]]
    winter = [h for h in people if not h["lemmon"]]
    primary = [h for h in homes if h["cls"] == "3"]
    for h in homes:
        h["winter"] = False
    for h in winter:
        h["winter"] = True
    print(f"homes {len(homes):,}  class 4.1 {len(c41):,}  away {len(away):,}  people {len(people):,}  winter {len(winter):,}")

    kinds = ["house", "condo", "manufactured"]
    values = [{"kind": k, "winter_n": sum(h["kind"] == k for h in winter),
               "winter_median": med(h["fcv"] for h in winter if h["kind"] == k),
               "primary_median": med(h["fcv"] for h in primary if h["kind"] == k)} for k in kinds]
    values.append({"kind": "all", "winter_n": len(winter), "winter_median": med(h["fcv"] for h in winter),
                   "primary_median": med(h["fcv"] for h in primary)})
    origin = collections.Counter(h["from"] for h in winter).most_common()

    # ---------- winter homes per hexagon (the only place their locations are published) ----------
    to_m = Transformer.from_crs(4326, 26912, always_xy=True)
    to_ll = Transformer.from_crs(26912, 4326, always_xy=True)

    def cell(lon, lat):
        x, y = to_m.transform(lon, lat)
        q, r = (math.sqrt(3) / 3 * x - y / 3) / HEX_M, (2 / 3 * y) / HEX_M
        rq, rr, rs = round(q), round(r), round(-q - r)
        dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs + q + r)
        if dq > dr and dq > ds:
            rq = -rr - rs
        elif dr > ds:
            rr = -rq - rs
        return rq, rr

    def corners(q, r):
        cx, cy = HEX_M * math.sqrt(3) * (q + r / 2), HEX_M * 1.5 * r
        pts = [to_ll.transform(cx + HEX_M * math.cos(math.radians(60 * k + 30)),
                               cy + HEX_M * math.sin(math.radians(60 * k + 30))) for k in range(6)]
        return [[round(lat, 5), round(lon, 5)] for lon, lat in pts]

    in_hex = collections.defaultdict(lambda: [0, 0])
    no_point = 0
    for h in homes:
        if not (h["lon"] and h["lat"]):
            no_point += h["winter"]
            continue
        c = in_hex[cell(h["lon"], h["lat"])]
        c[0] += 1
        c[1] += h["winter"]
    hexes = [{"c": corners(*k), "n": v[1], "homes": v[0]} for k, v in in_hex.items() if v[1] >= HEX_MIN]
    drawn = sum(x["n"] for x in hexes)
    print(f"hexagons drawn {len(hexes)}  winter homes in them {drawn:,}  not drawn {len(winter) - drawn:,}")

    # ---------- winter homes by community ----------
    places = shapes("PLACE", "place", a.refresh)[["NAME", "geometry"]].to_crs(4326)
    pts = gpd.GeoDataFrame(
        {"winter": [h["winter"] for h in homes if h["lon"] and h["lat"]]},
        geometry=[Point(h["lon"], h["lat"]) for h in homes if h["lon"] and h["lat"]], crs=4326)
    joined = gpd.sjoin(pts, places, how="left", predicate="within")
    joined = joined[~joined.index.duplicated()]
    joined["NAME"] = joined["NAME"].fillna("Outside any town or named community")
    by_place = joined.groupby("NAME")["winter"].agg(["size", "sum"])
    place_rows = [{"place": n, "homes": int(r["size"]), "winter": int(r["sum"])}
                  for n, r in by_place.iterrows() if r["size"] >= PLACE_MIN_HOMES]
    place_rows.sort(key=lambda r: -r["winter"])

    # ---------- Census vacancy ----------
    print("census")
    occ, vac = acs("b25002", a.refresh), acs("b25004", a.refresh)

    def census_row(geo):
        v = lambda t, c: None if pd.isna(t.at[geo, c]) else int(t.at[geo, c])
        return {"units": v(occ, "B25002_E001"), "vacant": v(occ, "B25002_E003"), "vacant_moe": v(occ, "B25002_M003"),
                "for_rent": v(vac, "B25004_E002"), "rented_empty": v(vac, "B25004_E003"),
                "for_sale": v(vac, "B25004_E004"), "sold_empty": v(vac, "B25004_E005"),
                "seasonal": v(vac, "B25004_E006"), "seasonal_moe": v(vac, "B25004_M006"),
                "migrant": v(vac, "B25004_E007"),
                "other": v(vac, "B25004_E008"), "other_moe": v(vac, "B25004_M008")}

    tracts = shapes("TRACT", "tract", a.refresh)
    tracts = tracts[tracts["COUNTYFP"] == "019"].to_crs(4326)
    tract_rows = []
    for _, t in tracts.iterrows():
        geo = "1400000US" + t["GEOID"]
        if geo not in occ.index:
            continue
        row = census_row(geo)
        if not row["units"]:
            continue
        geom = t["geometry"].simplify(0.0006, preserve_topology=True)
        tract_rows.append({"id": t["GEOID"], "g": [[[y, x] for x, y in ring] for ring in rings(geom)],
                           "units": row["units"], "other": row["other"], "other_moe": row["other_moe"],
                           "seasonal": row["seasonal"], "vacant": row["vacant"]})

    # ---------- unfinished buildings ----------
    print("unfinished buildings")
    part = cached_json("unfinished.json", a.refresh, lambda: arcgis_rows(
        PARCELS, "UPPER(USE_DESC) LIKE '%PART%COMP%'",
        "PARCEL,PARCEL_USE,USE_DESC,ADDRESS_OL,JURIS_OL,GISACRES,LASTCHANGE,LON,LAT"))
    unfinished = []
    for p in part:
        kind = UNFINISHED_HOMES.get(p["PARCEL_USE"], "commercial")
        changed = day(p["LASTCHANGE"])
        unfinished.append({"lat": round(p["LAT"], 5), "lon": round(p["LON"], 5), "kind": kind,
                           "use": " ".join((p["USE_DESC"] or "").split()).capitalize(),
                           "addr": (p["ADDRESS_OL"] or "").strip().title() or None,
                           "juris": (p["JURIS_OL"] or "").strip().title(),
                           "acres": round(p["GISACRES"] or 0, 1), "changed": changed.year if changed else None,
                           "parcel": p["PARCEL"]})
    unfinished_n = collections.Counter(u["kind"] for u in unfinished)

    # ---------- Tucson vacant-building cases ----------
    print("code cases")
    quoted = ",".join("'" + t + "'" for t in VACANT_CASE_TYPES)
    cases = cached_json("vacant_cases.json", a.refresh, lambda: arcgis_rows(
        CASES, f"casetype IN ({quoted})",
        "CASENUMBER,status,OPENEDDATE,MainAddress,PARCEL,casetype,PRO_URL,LAT,LON"))
    opened = [day(c["OPENEDDATE"]) for c in cases if c["OPENEDDATE"]]
    still = {}
    for c in cases:
        if (c["status"] or "").startswith("Closed") or not (c["LAT"] and c["LON"] and c["OPENEDDATE"]):
            continue
        key = c["PARCEL"] or c["MainAddress"]
        if key not in still or c["OPENEDDATE"] < still[key]["OPENEDDATE"]:
            still[key] = c
    case_rows = []
    for c in still.values():
        d = day(c["OPENEDDATE"])
        case_rows.append({"lat": round(c["LAT"], 5), "lon": round(c["LON"], 5), "addr": (c["MainAddress"] or "").title(),
                          "opened": d.isoformat(), "years": round((today - d).days / 365.25, 1),
                          "status": c["status"], "url": c["PRO_URL"]})
    case_rows.sort(key=lambda r: r["opened"])

    out = {
        "generated": today.isoformat(),
        "homeless": HOMELESS,
        "census": {"year": f"{ACS_YEAR - 4}-{ACS_YEAR}", "county": census_row(COUNTY), "tucson": census_row(TUCSON)},
        "winter": {
            "total": len(winter), "homes": len(homes), "both_years": sum(h["same_before"] for h in winter),
            "tax_years": [2000 + y for y in sorted(CLASS_YEARS)],
            "funnel": {"class41": len(c41), "away": len(away), "people": len(people), "winter": len(winter),
                       "companies": len(away) - len(people), "lemmon": len(people) - len(winter),
                       "class41_arizona": len(c41) - len(away)},
            "by_kind": {k: sum(h["kind"] == k for h in winter) for k in kinds},
            "values": values,
            "over_1m": sum((h["fcv"] or 0) >= 1e6 for h in winter),
            "under_250k": sum(0 < (h["fcv"] or 0) < 250e3 for h in winter),
            "origin": [{"from": k, "n": n} for k, n in origin[:12]],
            "origin_rest": sum(n for _, n in origin[12:]),
            "juris": collections.Counter(h["juris"] for h in winter).most_common(),
            "places": place_rows, "place_min_homes": PLACE_MIN_HOMES,
            "hex_m": HEX_M, "hex_min": HEX_MIN, "hexes": hexes, "not_drawn": len(winter) - drawn,
        },
        "tracts": tract_rows,
        "unfinished": {"sites": unfinished, "count": dict(unfinished_n), "total": len(unfinished)},
        "cases": {"open": case_rows, "all": len(cases), "open_cases": sum(not (c["status"] or "").startswith("Closed") for c in cases),
                  "since": min(opened).isoformat(), "over_2y": sum(r["years"] >= 2 for r in case_rows)},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    print(f"winter homes {len(winter):,} ({sum(h['same_before'] for h in winter):,} in class 4.1 both years); "
          f"unfinished {dict(unfinished_n)}; open vacant-building parcels {len(case_rows)} "
          f"({out['cases']['over_2y']} open 2+ years)")


if __name__ == "__main__":
    main()
