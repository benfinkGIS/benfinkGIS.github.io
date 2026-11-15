"""Step 8a: the extra layers the connectivity model needs.

- NLCD 2021 percent impervious (30 m) from the MRLC web coverage service:
  how built-up each piece of ground is.
- NHDPlus HR water bodies, water areas and perennial flowlines: where there
  is standing or flowing water.
- Every research-grade iNaturalist record of a mammal, a bird and a butterfly
  in the box (id, position, stated accuracy, taxon id only). These are the
  measure of where observers have been, used to correct the sighting check.
  No observer names, dates or photos are kept.

Run:  py tools/washes/13_get_landcover.py
"""
import json
import time

import requests
from pyproj import Transformer

from common import BBOX, CONTEXT, EPSG, SIGHTINGS, USER_AGENT, WORK, bbox_lonlat

LAND = WORK / "landcover"
MRLC = "https://www.mrlc.gov/geoserver/ows"
COVERAGE = "mrlc_download__NLCD_2021_Impervious_L48"
NHD = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer"
WATER = {
    # name: (layer, fields, where)
    "nhd_waterbody": (9, "OBJECTID,gnis_name,ftype,fcode,areasqkm", "1=1"),
    "nhd_area": (8, "OBJECTID,gnis_name,ftype,fcode,areasqkm", "1=1"),
    "nhd_perennial": (3, "OBJECTID,gnis_name,ftype,fcode", "fcode = 46006"),
}
INAT = "https://api.inaturalist.org/v2/observations"
GROUPS = {"mammals": 40151, "birds": 3, "butterflies": 47224}
FIELDS = "(id:!t,location:!t,positional_accuracy:!t,obscured:!t,taxon:(id:!t))"
PAD_M = 600


def get(url, **params):
    for i in range(6):
        try:
            r = requests.get(url, params=params, headers=USER_AGENT, timeout=180)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(5 * (i + 1))
    raise SystemExit(f"gave up on {url}")


def impervious():
    t = Transformer.from_crs(EPSG, 5070, always_xy=True)
    x0, y0, x1, y1 = BBOX
    xs, ys = zip(*(t.transform(x, y) for x in (x0, x1) for y in (y0, y1)))
    r = get(MRLC, service="WCS", version="2.0.1", request="GetCoverage",
            coverageId=COVERAGE, format="image/tiff",
            subset=[f"X({min(xs) - PAD_M:.0f},{max(xs) + PAD_M:.0f})",
                    f"Y({min(ys) - PAD_M:.0f},{max(ys) + PAD_M:.0f})"])
    if not r.content[:4] in (b"II*\x00", b"MM\x00*"):
        raise SystemExit("impervious: the server did not send a GeoTIFF: " + r.text[:300])
    out = LAND / "nlcd_2021_impervious.tif"
    out.write_bytes(r.content)
    return dict(file=out.name, bytes=len(r.content), coverage=COVERAGE, source=MRLC)


def water(name, layer, fields, where):
    feats, offset = [], 0
    while True:
        gj = get(f"{NHD}/{layer}/query", where=where, outFields=fields, outSR=EPSG,
                 f="geojson", geometry=",".join(f"{v:.1f}" for v in BBOX), inSR=EPSG,
                 geometryType="esriGeometryEnvelope", spatialRel="esriSpatialRelIntersects",
                 resultOffset=offset, resultRecordCount=1000, orderByFields="OBJECTID").json()
        feats += [f for f in gj.get("features", []) if f.get("geometry")]
        if len(gj.get("features", [])) < 1000:
            break
        offset += 1000
    (CONTEXT / f"{name}.geojson").write_text(json.dumps(dict(
        type="FeatureCollection", crs=dict(type="name", properties=dict(name=f"EPSG:{EPSG}")),
        features=feats)))
    return len(feats)


def effort(taxon_id, box):
    w, s, e, n = box
    out, above = [], 0
    while True:
        page = get(INAT, taxon_id=taxon_id, quality_grade="research", swlng=w, swlat=s,
                   nelng=e, nelat=n, geoprivacy="open", taxon_geoprivacy="open",
                   per_page=200, order_by="id", order="asc", id_above=above,
                   fields=FIELDS).json()["results"]
        for o in page:
            if o.get("obscured") or not o.get("location"):
                continue
            lat, lon = (float(v) for v in o["location"].split(","))
            out.append([o["id"], round(lon, 6), round(lat, 6), o.get("positional_accuracy"),
                        (o.get("taxon") or {}).get("id")])
        if len(page) < 200:
            return out
        above = page[-1]["id"]
        time.sleep(1.1)


def main():
    LAND.mkdir(parents=True, exist_ok=True)
    done = dict(fetched=time.strftime("%Y-%m-%d"))
    done["impervious"] = impervious()
    print("impervious", done["impervious"]["bytes"], flush=True)
    done["water"] = {}
    for name, (layer, fields, where) in WATER.items():
        done["water"][name] = water(name, layer, fields, where)
        print(name, done["water"][name], flush=True)
    box = bbox_lonlat()
    done["effort"] = {}
    for name, taxon_id in GROUPS.items():
        rows = effort(taxon_id, box)
        (SIGHTINGS / f"effort_{name}.json").write_text(json.dumps(dict(
            columns=["id", "lon", "lat", "accuracy_m", "taxon_id"], rows=rows)))
        done["effort"][name] = dict(inat_taxon_id=taxon_id, records=len(rows))
        print(name, len(rows), flush=True)
    (LAND / "manifest.json").write_text(json.dumps(done, indent=2))


if __name__ == "__main__":
    main()
