"""Step 4b: what has been recorded living in and around each neighborhood.

Runs in the system Python:  py tools/canopy/17_species_records.py [site_id ...]

Asks the Global Biodiversity Information Facility (GBIF) for occurrence
records since 2015 inside each neighborhood boundary and within 1 km of it.
GBIF carries iNaturalist's research-grade observations and eBird's
observation dataset among thousands of others, so one query covers all three
sources named in most ecological desk studies.

For each area it reports, by group (birds, vascular plants, insects, bees,
butterflies and moths, reptiles, mammals):
  records    how many occurrence records
  species    how many distinct species those records name
  top        the most-recorded species
and, separately, whether the four trees in the planting palette have been
recorded there, and which datasets the records come from.

Read these as records, not as wildlife counts. They show where people have
looked: a park with a birding hotspot can have a hundred times the records of
the streets beside it. Comparing the two neighborhoods' totals says more
about observers than about animals. Only records with coordinates and no
flagged geospatial issue are counted.

This uses GBIF's search API, which has no citable DOI. A formal report should
repeat the query as a GBIF download (which needs a free account) and cite
that.

Writes species_records.json beside each site's geodatabase. No observer
names are requested or stored.
"""
import json
import sys
import time

import pyproj
import requests
from shapely.geometry import shape
from shapely.geometry.polygon import orient
from shapely.ops import transform

from common import EPSG, PROJECT, site_dir, sites

API = "https://api.gbif.org/v1"
SINCE = 2015
BUFFER_M = 1000
GROUPS = {
    "Birds": ["Aves"],
    "Vascular plants": ["Tracheophyta"],
    "Insects": ["Insecta"],
    "Bees": ["Apidae", "Halictidae", "Megachilidae", "Andrenidae", "Colletidae"],
    "Butterflies and moths": ["Lepidoptera"],
    "Reptiles": ["Squamata", "Testudines"],
    "Mammals": ["Mammalia"],
}
UA = {"User-Agent": "canopy-scenario/1.0"}
_names = {}


def get(path, params=None):
    for i in range(6):
        try:
            r = requests.get(API + path, params=params, headers=UA, timeout=90)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(3 * (i + 1))
    raise SystemExit(f"GBIF did not answer {path}")


def key_for(name):
    m = get("/species/match", dict(name=name, strict="true"))
    key = m.get("acceptedUsageKey") or m.get("usageKey")
    if not key:
        raise SystemExit(f"GBIF does not know {name}")
    return key


def species_name(key):
    if key not in _names:
        sp = get(f"/species/{key}")
        common = sp.get("vernacularName")
        if not common:
            v = get(f"/species/{key}/vernacularNames", dict(limit=50)).get("results", [])
            eng = [x["vernacularName"] for x in v if x.get("language") == "eng"]
            common = eng[0] if eng else None
        _names[key] = dict(latin=sp.get("canonicalName") or sp.get("scientificName"),
                           common=common)
    return _names[key]


def tally(wkt, taxon_keys=None, top=6):
    params = [("geometry", wkt), ("hasCoordinate", "true"), ("hasGeospatialIssue", "false"),
              ("year", f"{SINCE},2026"), ("limit", 0), ("facet", "speciesKey"),
              ("facetLimit", 20000)]
    for k in taxon_keys or []:
        params.append(("taxonKey", k))
    d = get("/occurrence/search", params)
    counts = d["facets"][0]["counts"] if d.get("facets") else []
    return dict(records=d["count"], species=len(counts),
                top=[dict(count=c["count"], **species_name(int(c["name"])))
                     for c in counts[:top]])


def main():
    to_ll = pyproj.Transformer.from_crs(EPSG, 4326, always_xy=True).transform
    group_keys = {g: [key_for(n) for n in names] for g, names in GROUPS.items()}
    palette = json.loads((PROJECT / "species.json").read_text(encoding="utf-8"))["species"]
    palette_keys = {sp["common"]: key_for(sp["latin"]) for sp in palette}

    for s in sites(sys.argv[1:]):
        d = site_dir(s)
        gj = json.loads((d / "boundary.geojson").read_text())["features"][0]["geometry"]
        boundary = shape(gj)
        areas = {"inside": boundary.simplify(2),
                 "within_1km": boundary.buffer(BUFFER_M).simplify(10)}
        out = dict(site=s["id"], since=SINCE, buffer_m=BUFFER_M,
                   source="GBIF occurrence search API, api.gbif.org/v1",
                   queried=time.strftime("%Y-%m-%d"), areas={})
        for label, geom in areas.items():
            wkt = orient(transform(to_ll, geom), 1.0).wkt
            block = dict(km2=round(geom.area / 1e6, 2), all=tally(wkt, top=0), groups={},
                         palette={}, datasets=[])
            for g, keys in group_keys.items():
                block["groups"][g] = tally(wkt, keys)
            for name, key in palette_keys.items():
                block["palette"][name] = get("/occurrence/search", [
                    ("geometry", wkt), ("hasCoordinate", "true"),
                    ("hasGeospatialIssue", "false"), ("year", f"{SINCE},2026"),
                    ("limit", 0), ("taxonKey", key)])["count"]
            ds = get("/occurrence/search", [
                ("geometry", wkt), ("hasCoordinate", "true"), ("hasGeospatialIssue", "false"),
                ("year", f"{SINCE},2026"), ("limit", 0), ("facet", "datasetKey"),
                ("facetLimit", 5)])
            for c in ds["facets"][0]["counts"]:
                block["datasets"].append(dict(
                    title=get(f"/dataset/{c['name']}").get("title"), records=c["count"]))
            out["areas"][label] = block
        (d / "species_records.json").write_text(json.dumps(out, indent=1))
        print("==", s["id"])
        for label, block in out["areas"].items():
            print(f"  {label} ({block['km2']} km2): {block['all']['records']:,} records, "
                  f"{block['all']['species']:,} species")
            for g, t in block["groups"].items():
                tops = "; ".join(f"{x['common'] or x['latin']} {x['count']}" for x in t["top"][:4])
                print(f"     {g:22s} {t['records']:7,} records {t['species']:5,} species | {tops}")
            print("     palette trees:", block["palette"])
            print("     datasets:", [(x["title"][:44], x["records"]) for x in block["datasets"]])


if __name__ == "__main__":
    main()
