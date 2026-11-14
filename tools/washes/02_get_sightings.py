"""Step 1b: research-grade iNaturalist records of the focal species.

Keeps the observation id (which links back to the record and its observer on
iNaturalist), date, position, stated accuracy and licence. Observer names are
not kept. Records whose position the observer or iNaturalist has obscured are
left out, since an obscured point can be 20 km off.

Also asks GBIF how many records it holds per species and from which
datasets, so the write-up can say what eBird adds. GBIF records are not
downloaded here.

Run:  py tools/washes/02_get_sightings.py
"""
import json
import time

import requests

from common import SIGHTINGS, SPECIES, USER_AGENT, bbox_lonlat

INAT = "https://api.inaturalist.org/v1"
GBIF = "https://api.gbif.org/v1"


def get(url, **params):
    for i in range(6):
        try:
            r = requests.get(url, params=params, headers=USER_AGENT, timeout=120)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(5 * (i + 1))
    raise SystemExit(f"gave up on {url}")


def inat_taxon(name):
    res = get(f"{INAT}/taxa", q=name, rank="species", is_active="true")["results"]
    for t in res:
        if t["name"] == name or name in [n for n in (t.get("matched_term"),) if n]:
            return t
    return res[0]


def inat_records(taxon_id, box):
    w, s, e, n = box
    out, above = [], 0
    while True:
        page = get(f"{INAT}/observations", taxon_id=taxon_id, quality_grade="research",
                   swlng=w, swlat=s, nelng=e, nelat=n, geoprivacy="open",
                   taxon_geoprivacy="open", per_page=200, order_by="id", order="asc",
                   id_above=above)["results"]
        for o in page:
            if o.get("obscured") or not o.get("geojson"):
                continue
            lon, lat = o["geojson"]["coordinates"]
            out.append(dict(
                type="Feature",
                geometry=dict(type="Point", coordinates=[float(lon), float(lat)]),
                properties=dict(id=o["id"], date=o.get("observed_on"),
                                accuracy_m=o.get("positional_accuracy"),
                                licence=o.get("license_code"))))
        if len(page) < 200:
            return out
        above = page[-1]["id"]
        time.sleep(1.2)


def gbif_summary(name, box):
    w, s, e, n = box
    wkt = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
    key = get(f"{GBIF}/species/match", name=name)["usageKey"]
    r = get(f"{GBIF}/occurrence/search", taxonKey=key, geometry=wkt, limit=0,
            hasCoordinate="true", facet="datasetKey", facetLimit=8)
    sets = []
    for c in r["facets"][0]["counts"]:
        title = get(f"{GBIF}/dataset/{c['name']}")["title"]
        sets.append(dict(dataset=title, records=c["count"]))
    return dict(taxon_key=key, records=r["count"], datasets=sets)


def main():
    SIGHTINGS.mkdir(parents=True, exist_ok=True)
    box = bbox_lonlat()
    summary = dict(fetched=time.strftime("%Y-%m-%d"), bbox_lonlat=box, species={})
    for sp in SPECIES:
        taxon = inat_taxon(sp["scientific"])
        feats = inat_records(taxon["id"], box)
        (SIGHTINGS / f"{sp['id']}.geojson").write_text(json.dumps(dict(
            type="FeatureCollection", features=feats)))
        summary["species"][sp["id"]] = dict(
            inat_taxon_id=taxon["id"], inat_name=taxon["name"],
            inat_records=len(feats), gbif=gbif_summary(sp["scientific"], box))
        print(sp["id"], taxon["name"], len(feats), flush=True)
        time.sleep(1.2)
    (SIGHTINGS / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
