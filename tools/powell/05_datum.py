"""Settle and record the vertical datum conversion for the water levels.

Reclamation's Lake Powell elevations are feet above NGVD29; the DEM is metres
above NAVD88. The conversion used everywhere is the USGS one in common.py
(add 2.913 ft). This script checks it against NOAA's conversion service at
four places along the lake, downloads the USGS elevation-area-capacity tables
that use the same conversion, and writes processed/datum.json with the
reference elevations in both systems.

    py -I tools/powell/05_datum.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json

import requests

from common import (DEAD_POOL_FT, EAC_FILE, EAC_ITEM, FT_TO_M, FULL_POOL_FT, MIN_POWER_POOL_FT, NCAT,
                    NGVD29_TO_NAVD88_FT, PROCESSED, RAW, SCIENCEBASE_FILE, USER_AGENT, reclamation_ft_to_dem_m)

# name, latitude, longitude (rough, for the comparison only)
PLACES = [("USGS gauge at Glen Canyon Dam", 36.9369326, -111.4837694),
          ("Bullfrog", 37.52, -110.72),
          ("Hite", 37.87, -110.39),
          ("San Juan arm, Piute Farms", 37.19, -110.42)]


def noaa_offset_m(lat, lon):
    r = requests.get(NCAT, params={"lat": lat, "lon": lon, "inDatum": "nad83(2011)", "outDatum": "nad83(2011)",
                                   "inVertDatum": "NGVD29", "outVertDatum": "NAVD88", "orthoHt": 1100.0},
                     headers=USER_AGENT, timeout=60).json()
    return round(float(r["destOrthoht"]) - float(r["srcOrthoht"]), 3), r.get("vertconVersion")


def main():
    used_m = NGVD29_TO_NAVD88_FT * FT_TO_M
    print(f"conversion used: NAVD88 = NGVD29 + {NGVD29_TO_NAVD88_FT} ft ({used_m:.3f} m)")
    checks = []
    for name, lat, lon in PLACES:
        off, version = noaa_offset_m(lat, lon)
        checks.append({"place": name, "lat": lat, "lon": lon, "noaa_offset_m": off,
                       "differs_from_used_m": round(off - used_m, 3)})
        print(f"  NOAA VERTCON {version} at {name}: +{off:.3f} m ({off / FT_TO_M:.3f} ft), "
              f"{off - used_m:+.3f} m from the value used")

    eac_dir = RAW / "capacity"
    eac_dir.mkdir(parents=True, exist_ok=True)
    r = requests.get(SCIENCEBASE_FILE.format(item=EAC_ITEM), params={"name": EAC_FILE}, headers=USER_AGENT, timeout=120)
    r.raise_for_status()
    (eac_dir / EAC_FILE).write_bytes(r.content)
    print(f"  saved {EAC_FILE} ({len(r.content) / 1e3:.0f} kB)")

    reference = {name: {"reclamation_ft_ngvd29": ft, "navd88_ft": round(ft + NGVD29_TO_NAVD88_FT, 3),
                        "dem_m_navd88": round(reclamation_ft_to_dem_m(ft), 3)}
                 for name, ft in (("full_pool", FULL_POOL_FT), ("minimum_power_pool", MIN_POWER_POOL_FT),
                                  ("dead_pool", DEAD_POOL_FT))}
    for name, v in reference.items():
        print(f"  {name}: {v['reclamation_ft_ngvd29']:,.0f} ft NGVD29 = {v['dem_m_navd88']:.3f} m NAVD88")
    (PROCESSED / "datum.json").write_text(json.dumps({
        "ngvd29_to_navd88_ft": NGVD29_TO_NAVD88_FT, "ngvd29_to_navd88_m": round(used_m, 4),
        "source": "Jones and Root, 2022, https://doi.org/10.5066/P9O3IPG3 (NOAA VERTCON at USGS gauge 09379901)",
        "noaa_checks": checks, "reference": reference}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
