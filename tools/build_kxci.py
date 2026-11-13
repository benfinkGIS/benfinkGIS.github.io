#!/usr/bin/env python3
"""KXCI 91.3 FM signal reach, step 1: licence, FCC contour and who lives inside it.

Usage (from the repo root):
    py tools/build_kxci.py              # uses cached downloads where it has them
    py tools/build_kxci.py --refresh    # ask the FCC again

Needs Python 3 with requests, pandas, geopandas and shapely.
Run tools/model_kxci_terrain.py next.

Sources (all public, no key needed)
-----------------------------------
FM Query   transition.fcc.gov/fcc-bin/fmq, the FCC's licence database (LMS). This is
           where the current transmitter site, power and antenna height come from.
Contours   geo.fcc.gov/api/contours. Two calls:
             coverage.json  the 60 dBu F(50,50) contour computed from the CURRENT
                            licence figures, 360 radials, 1 arc-second terrain.
             entity.json    what the API returns for call sign KXCI. As of November
                            2026 that is still the 1991 Mt. Bigelow licence (0.34 kW),
                            which the station left in April 2024. Kept for comparison,
                            never used as the service contour.
Census     TIGER/Line 2020 tabulation blocks for Arizona (population and housing
           units) and the 2020 PL 94-171 redistricting file (table H1, occupied
           housing units = households). TIGER/Line 2020 places for the town table.

Method
------
Everything is analysed in NAD83 / UTM 12N (EPSG:26912). A block wholly inside the
contour counts in full; a block the contour cuts counts by the share of its area
inside (areal weighting).

Output
------
kxci-signal/work/kxci.gpkg       layers transmitters, contour_60dbu, contour_1991,
                                 blocks (every block within 75 km, with the share
                                 inside each contour)
kxci-signal/work/summary.json    the counts
"""
import argparse
import io
import json
import math
import sys
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "kxci-signal" / "work"
RAW = WORK / "raw"

CALL = "KXCI"
FIELD_DBU = 60            # FM primary service contour
STUDY_KM = 75             # blocks are kept out to this distance from the tower
UTM = 26912
UA = {"User-Agent": "signal-reach-study/0.1"}

FMQ_URL = "https://transition.fcc.gov/fcc-bin/fmq"
CONTOUR_URL = "https://geo.fcc.gov/api/contours/{kind}.json"
BLOCKS_URL = "https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_04_tabblock20.zip"
PLACES_URL = "https://www2.census.gov/geo/tiger/TIGER2020/PLACE/tl_2020_04_place.zip"
PL_URL = ("https://www2.census.gov/programs-surveys/decennial/2020/data/"
          "01-Redistricting_File--PL_94-171/Arizona/az2020.pl.zip")
COUNTIES = {"019": "Pima", "021": "Pinal", "003": "Cochise", "023": "Santa Cruz",
            "009": "Graham"}


def get(url, params=None, tries=5, timeout=180):
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as exc:
            if attempt == tries - 1:
                raise
            print(f"  retry {attempt + 1}: {exc}")
            time.sleep(5 * (attempt + 1))


def cached(path, fetch, refresh=False):
    if path.exists() and path.stat().st_size > 0 and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    body = fetch()
    path.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
    return path


def licence_records(refresh):
    """Current licence records for the call sign, from FM Query's pipe-delimited list."""
    path = cached(RAW / "fmq_kxci.txt",
                  lambda: get(FMQ_URL, dict(call=CALL, list=4, size=9)).content, refresh)
    out = []
    for line in path.read_text("latin-1").splitlines():
        f = [x.strip() for x in line.split("|")]
        if len(f) < 38 or f[1] != CALL:
            continue
        lat = (float(f[20]) + float(f[21]) / 60 + float(f[22]) / 3600) * (1 if f[19] == "N" else -1)
        lon = (float(f[24]) + float(f[25]) / 60 + float(f[26]) / 3600) * (-1 if f[23] == "W" else 1)
        out.append(dict(
            callsign=f[1], service=f[3], channel=int(f[4]), frequency_mhz=float(f[2].split()[0]),
            directional=f[5] == "DA", station_class=f[7], status=f[9], city=f[10], state=f[11],
            file_number=f[13], erp_kw=float(f[14].split()[0]), haat_m=float(f[16]),
            facility_id=int(f[18]), lat=round(lat, 6), lon=round(lon, 6),
            rcamsl_m=float(f[31].split()[0]), licensee=f[27]))
    main = [r for r in out if r["service"] == "FM" and r["status"] == "LIC"]
    if len(main) != 1:
        sys.exit(f"expected one licensed FM record for {CALL}, found {len(main)}")
    return main[0], [r for r in out if r is not main[0]]


def contour_polygon(feature):
    pts = [(p["x"], p["y"]) for p in feature["properties"]["contourData"]]
    return Polygon(pts)


def fetch_contours(lic, refresh):
    cur = cached(RAW / "fcc_coverage_current.json", lambda: get(
        CONTOUR_URL.format(kind="coverage"),
        dict(serviceType="fm", lat=lic["lat"], lon=lic["lon"], nradial=360, field=FIELD_DBU,
             erp=lic["erp_kw"], rcamsl=lic["rcamsl_m"], curve=0, src="ned_1", unit="m")
    ).content, refresh)
    old = cached(RAW / "fcc_entity_callsign.json", lambda: get(
        CONTOUR_URL.format(kind="entity"), dict(callsign=CALL, serviceType="fm")).content, refresh)
    cur = json.loads(cur.read_text())["features"][0]
    old = json.loads(old.read_text())["features"][0]
    return cur, old


def households_by_block(refresh):
    """Occupied housing units (H1_002N) per block from the PL 94-171 file."""
    path = cached(RAW / "az2020.pl.zip", lambda: get(PL_URL, timeout=900).content, refresh)
    with zipfile.ZipFile(path) as z:
        names = {n.lower(): n for n in z.namelist()}
        geo = pd.read_csv(z.open(names["azgeo2020.pl"]), sep="|", header=None, dtype=str,
                          encoding="latin-1", usecols=[2, 7, 9])
        geo.columns = ["sumlev", "logrecno", "geocode"]
        geo = geo[geo.sumlev == "750"]
        seg = pd.read_csv(z.open(names["az000022020.pl"]), sep="|", header=None, dtype=str,
                          encoding="latin-1")
    ncol = seg.shape[1]
    seg = seg[[4, ncol - 3, ncol - 2]]
    seg.columns = ["logrecno", "units", "households"]
    out = geo.merge(seg, on="logrecno")
    out["households"] = out.households.astype(int)
    out["units"] = out.units.astype(int)
    return out.set_index("geocode")[["units", "households"]]


def share_inside(blocks, poly):
    """Share of each block's area inside the polygon (0 to 1)."""
    geom = blocks.geometry.values
    share = pd.Series(0.0, index=blocks.index)
    inside = shapely.contains_properly(poly, geom)
    crosses = shapely.intersects(poly, geom) & ~inside
    share[inside] = 1.0
    part = shapely.area(shapely.intersection(geom[crosses], poly)) / shapely.area(geom[crosses])
    share[crosses] = part
    return share


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)

    print("licence")
    lic, others = licence_records(args.refresh)
    print(f"  {lic['callsign']} {lic['frequency_mhz']} MHz class {lic['station_class']}: "
          f"{lic['erp_kw']} kW, HAAT {lic['haat_m']} m, centre {lic['rcamsl_m']} m AMSL, "
          f"{lic['lat']}, {lic['lon']} (file {lic['file_number']})")

    print("contours")
    cur, old = fetch_contours(lic, args.refresh)
    oldp = {k: v for k, v in old["properties"].items() if k != "contourData"}
    stale = (abs(oldp["antenna_lat"] - lic["lat"]) > 0.01
             or abs(oldp["erp"] - lic["erp_kw"]) > 0.01)
    print(f"  call-sign lookup returns file {oldp['file_number']}: {oldp['erp']} kW at "
          f"{oldp['antenna_lat']:.4f}, {oldp['antenna_lon']:.4f}"
          + ("  <-- NOT the current licence" if stale else ""))
    contours = gpd.GeoDataFrame(
        dict(name=["current", "callsign_lookup"],
             file_number=[lic["file_number"], oldp["file_number"]],
             erp_kw=[lic["erp_kw"], oldp["erp"]],
             rcamsl_m=[lic["rcamsl_m"], oldp["rcamsl"]],
             field_dbu=[FIELD_DBU, oldp["field"]]),
        geometry=[contour_polygon(cur), contour_polygon(old)], crs=4326).to_crs(UTM)
    cur_poly, old_poly = contours.geometry.iloc[0], contours.geometry.iloc[1]
    radials = pd.DataFrame(cur["properties"]["contourData"])[
        ["azimuth", "distance", "haat", "erp"]]
    radials.to_csv(WORK / "fcc_radials.csv", index=False)
    print(f"  current 60 dBu contour: {cur_poly.area / 1e6:,.0f} sq km, "
          f"{radials.distance.min():.1f} to {radials.distance.max():.1f} km from the tower")

    tx = gpd.GeoDataFrame(
        [dict(lic, role="main")] + [dict(r, role="auxiliary") for r in others],
        geometry=[Point(r["lon"], r["lat"]) for r in [lic] + others], crs=4269).to_crs(UTM)
    site = tx.geometry.iloc[0]

    print("census blocks")
    cached(RAW / "tl_2020_04_tabblock20.zip", lambda: get(BLOCKS_URL, timeout=900).content)
    ring = gpd.GeoSeries([site.buffer(STUDY_KM * 1000)], crs=UTM).to_crs(4269)
    blocks = gpd.read_file(RAW / "tl_2020_04_tabblock20.zip", bbox=tuple(ring.total_bounds),
                           columns=["GEOID20", "COUNTYFP20", "POP20", "HOUSING20",
                                    "INTPTLAT20", "INTPTLON20"])
    blocks = blocks.to_crs(UTM)
    blocks = blocks[blocks.intersects(site.buffer(STUDY_KM * 1000))].reset_index(drop=True)
    hh = households_by_block(args.refresh)
    blocks = blocks.join(hh, on="GEOID20")
    if blocks.households.isna().any() or (blocks.units != blocks.HOUSING20).any():
        sys.exit("PL 94-171 housing counts do not line up with the TIGER blocks")
    blocks = blocks.rename(columns={"GEOID20": "geoid", "COUNTYFP20": "county",
                                    "POP20": "pop", "HOUSING20": "housing"})
    blocks["households"] = blocks.households.astype(int)
    blocks = blocks.drop(columns="units")
    pts = gpd.GeoSeries(gpd.points_from_xy(blocks.INTPTLON20.astype(float),
                                           blocks.INTPTLAT20.astype(float)), crs=4269).to_crs(UTM)
    blocks["px"], blocks["py"] = pts.x.values, pts.y.values
    blocks = blocks.drop(columns=["INTPTLAT20", "INTPTLON20"])
    blocks["dist_km"] = [math.hypot(x - site.x, y - site.y) / 1000
                         for x, y in zip(blocks.px, blocks.py)]
    print(f"  {len(blocks):,} blocks within {STUDY_KM} km, {blocks['pop'].sum():,} residents")

    blocks["in_fcc"] = share_inside(blocks, cur_poly)
    blocks["in_1991"] = share_inside(blocks, old_poly)

    print("places")
    cached(RAW / "tl_2020_04_place.zip", lambda: get(PLACES_URL, timeout=600).content)
    places = gpd.read_file(RAW / "tl_2020_04_place.zip",
                           columns=["NAME", "GEOID"]).to_crs(UTM)
    hit = gpd.sjoin(gpd.GeoDataFrame(blocks[["geoid"]], geometry=gpd.points_from_xy(
        blocks.px, blocks.py), crs=UTM), places, how="left", predicate="within")
    hit = hit[~hit.index.duplicated()]
    blocks["place"] = hit.NAME.fillna("").values

    def tally(share):
        w = blocks[share]
        return dict(population=round(float((blocks["pop"] * w).sum())),
                    housing_units=round(float((blocks.housing * w).sum())),
                    households=round(float((blocks.households * w).sum())))

    by_county = {}
    for fp, name in COUNTIES.items():
        sub = blocks[blocks.county == fp]
        if len(sub):
            by_county[name] = dict(
                population=int(sub["pop"].sum()),
                inside_fcc=round(float((sub["pop"] * sub.in_fcc).sum())),
                inside_1991=round(float((sub["pop"] * sub.in_1991).sum())))
    by_place = []
    for name, sub in blocks[blocks.place != ""].groupby("place"):
        total = int(sub["pop"].sum())
        if total >= 1000:
            by_place.append(dict(place=name, population=total,
                                 inside_fcc=round(float((sub["pop"] * sub.in_fcc).sum())),
                                 inside_1991=round(float((sub["pop"] * sub.in_1991).sum()))))
    by_place.sort(key=lambda r: -r["population"])

    summary = dict(
        licence=lic, other_records=others,
        callsign_lookup=dict(oldp, stale=bool(stale)),
        contour_field_dbu=FIELD_DBU,
        contour_area_sqkm=round(cur_poly.area / 1e6),
        contour_1991_area_sqkm=round(old_poly.area / 1e6),
        contour_km_min=round(float(radials.distance.min()), 1),
        contour_km_max=round(float(radials.distance.max()), 1),
        study_radius_km=STUDY_KM,
        study_area=dict(blocks=int(len(blocks)), population=int(blocks["pop"].sum()),
                        housing_units=int(blocks.housing.sum()),
                        households=int(blocks.households.sum())),
        inside_fcc=tally("in_fcc"), inside_1991=tally("in_1991"),
        blocks_cut_by_contour=int(((blocks.in_fcc > 0) & (blocks.in_fcc < 1)).sum()),
        by_county=by_county, by_place=by_place)
    (WORK / "summary.json").write_text(json.dumps(summary, indent=1))

    gpkg = WORK / "kxci.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    tx.to_file(gpkg, layer="transmitters", driver="GPKG")
    contours.to_file(gpkg, layer="contours", driver="GPKG")
    blocks.to_file(gpkg, layer="blocks", driver="GPKG")

    s = summary
    print(f"\ninside the current 60 dBu contour: {s['inside_fcc']['population']:,} residents, "
          f"{s['inside_fcc']['households']:,} households, "
          f"{s['inside_fcc']['housing_units']:,} housing units")
    print(f"inside the 1991 Mt. Bigelow contour: {s['inside_1991']['population']:,} residents")
    print(f"blocks cut by the contour: {s['blocks_cut_by_contour']:,}")
    for name, c in by_county.items():
        print(f"  {name:11s} {c['inside_fcc']:>9,} of {c['population']:>9,} within {STUDY_KM} km")
    for p in by_place[:14]:
        print(f"  {p['place']:28s} {p['inside_fcc']:>8,} of {p['population']:>8,}  "
              f"(1991: {p['inside_1991']:,})")


if __name__ == "__main__":
    main()
