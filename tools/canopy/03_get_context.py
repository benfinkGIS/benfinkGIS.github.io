"""Step 1c: download the vector layers each site needs from Pima County GIS.

Site layers (the working box): building footprints, parcels, streets.
Context layers (the working box plus 1 km): washes, mapped riparian habitat,
parks, protected lands.

Only the fields listed below are requested. The parcel and protected-lands
layers also hold owner names and mailing addresses; those stay on the server.

Run:  py tools/canopy/03_get_context.py [site_id ...]
"""
import json
import sys
import time

import requests

from common import EPSG, site_dir, sites, work_bbox

BASE = "https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData"
CONTEXT_M = 1000
LAYERS = {
    # name: (service path, fields, extra distance beyond the working box)
    "buildings": ("LandRecords/MapServer/3", "OBJECTID", 0),
    "parcels": ("LandRecords/MapServer/12", "PARCEL,PARCEL_USE,GISAREA", 0),
    "streets": ("Transportation/MapServer/11", "STREET,ROADCAT_DS,STRLVL_CD", 0),
    "washes": ("FloodControl/MapServer/3", "WASHNAME,CFS_SHORT2", CONTEXT_M),
    "riparian": ("Environmental/MapServer/4", "CLASS", CONTEXT_M),
    "parks": ("Community2/MapServer/11", "NAME,PARK_TYPE,ADMIN", CONTEXT_M),
    "protected": ("Environmental/MapServer/3", "MANAGED,GAP", CONTEXT_M),
}


def query(path, fields, bbox):
    feats, offset = [], 0
    while True:
        params = dict(
            where="1=1", outFields=fields, outSR=EPSG, f="geojson",
            geometry=",".join(f"{v:.1f}" for v in bbox), inSR=EPSG,
            geometryType="esriGeometryEnvelope",
            spatialRel="esriSpatialRelIntersects",
            resultOffset=offset, resultRecordCount=1000,
            orderByFields=fields.split(",")[0])
        for i in range(6):
            try:
                gj = requests.get(f"{BASE}/{path}/query", params=params, timeout=180).json()
                if "features" in gj:
                    break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(4 * (i + 1))
        else:
            raise SystemExit(f"gave up on {path}")
        feats += gj["features"]
        if len(gj["features"]) < 1000:
            return feats
        offset += 1000


def main():
    for s in sites(sys.argv[1:]):
        out = site_dir(s) / "context"
        out.mkdir(exist_ok=True)
        x0, y0, x1, y1 = work_bbox(s)
        counts = {}
        for name, (path, fields, extra) in LAYERS.items():
            feats = [f for f in query(path, fields, (x0 - extra, y0 - extra,
                                                     x1 + extra, y1 + extra))
                     if f.get("geometry")]
            counts[name] = len(feats)
            (out / f"{name}.geojson").write_text(json.dumps(dict(
                type="FeatureCollection",
                crs=dict(type="name", properties=dict(name=f"EPSG:{EPSG}")),
                features=feats)))
        print(s["id"], counts, flush=True)


if __name__ == "__main__":
    main()
