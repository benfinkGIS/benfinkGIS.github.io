"""Step 1a: download the vector layers the study area needs.

Pima County GIS: washes, mapped riparian habitat, streets, railroads, parks, protected
lands, and the flood-map bridges and culverts. USGS: named NHD flowlines.
US DOT: National Bridge Inventory (bridges and culverts 20 ft and longer).

Only the fields listed below are requested. The protected-lands layer also
holds owner names; those stay on the server.

Run:  py tools/washes/01_get_context.py
"""
import json
import time

import requests

from common import BBOX, CONTEXT, EPSG, USER_AGENT

PIMA = "https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData"
LAYERS = {
    # name: (layer URL, fields)
    "washes": (f"{PIMA}/FloodControl/MapServer/3", "OBJECTID,WASHNAME,CFS_SHORT2,CFS_NUM2"),
    "riparian": (f"{PIMA}/Environmental/MapServer/4", "OBJECTID,CLASS,IRA,CHNGDATE"),
    "streets": (f"{PIMA}/Transportation/MapServer/11", "OBJECTID,STREET,ROADCAT_DS,STRLVL_CD"),
    "railroads": (f"{PIMA}/Transportation/MapServer/8", "OBJECTID"),
    "parks": (f"{PIMA}/Community2/MapServer/11", "OBJECTID,NAME,PARK_TYPE,ADMIN"),
    "protected": (f"{PIMA}/Environmental/MapServer/3", "OBJECTID,MANAGED,GAP,ACRES_GIS"),
    "structures": (f"{PIMA}/FloodControl/MapServer/7", "OBJECTID,STRUCT_TYP,STRUCT_NM,WTR_NM"),
    "firm_water_lines": (f"{PIMA}/FloodControl/MapServer/8", "OBJECTID,WATER_TYP,CHAN_REP,WTR_NM"),
    "nhd_named": ("https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3",
                  "OBJECTID,gnis_name,ftype,fcode"),
    "bridges_nbi": ("https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/"
                    "NTAD_National_Bridge_Inventory/FeatureServer/0", "*"),
}
WHERE = {"nhd_named": "gnis_name IS NOT NULL"}
PAGE = 1000


def query(url, fields, where):
    feats, offset = [], 0
    while True:
        params = dict(
            where=where, outFields=fields, outSR=EPSG, f="geojson",
            geometry=",".join(f"{v:.1f}" for v in BBOX), inSR=EPSG,
            geometryType="esriGeometryEnvelope",
            spatialRel="esriSpatialRelIntersects",
            resultOffset=offset, resultRecordCount=PAGE,
            orderByFields="OBJECTID")
        for i in range(6):
            try:
                gj = requests.get(f"{url}/query", params=params,
                                  headers=USER_AGENT, timeout=180).json()
                if "features" in gj:
                    break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(4 * (i + 1))
        else:
            raise SystemExit(f"gave up on {url}")
        feats += gj["features"]
        if len(gj["features"]) < PAGE:
            return feats
        offset += PAGE


def main():
    CONTEXT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, (url, fields) in LAYERS.items():
        feats = [f for f in query(url, fields, WHERE.get(name, "1=1")) if f.get("geometry")]
        counts[name] = len(feats)
        (CONTEXT / f"{name}.geojson").write_text(json.dumps(dict(
            type="FeatureCollection",
            crs=dict(type="name", properties=dict(name=f"EPSG:{EPSG}")),
            features=feats)))
        print(name, len(feats), flush=True)
    (CONTEXT / "manifest.json").write_text(json.dumps(dict(
        fetched=time.strftime("%Y-%m-%d"), bbox_utm12n=BBOX, counts=counts,
        sources={k: v[0] for k, v in LAYERS.items()}), indent=2))


if __name__ == "__main__":
    main()
