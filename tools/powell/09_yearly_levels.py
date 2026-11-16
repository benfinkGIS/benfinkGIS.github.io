"""Make the one-row-per-year table that the year slider steps through.

For each calendar year from 1964 it gives the average daily elevation (the
level the slider shows), the year's highest and lowest days, how far the
average sits below full pool, and the share of live capacity that level holds.
1963 is left out because the elevation record only begins on 28 December. The
current year is a year to date and is marked as such.

Share of capacity uses the USGS 2018 elevation-capacity table for every year
(water above dead pool, as a share of the same at full pool). It describes
today's lake bed, so it reads a little low for early years, before sediment
took up part of the basin.

Writes processed/levels_yearly.csv.

    py -I tools/powell/09_yearly_levels.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from common import DEAD_POOL_FT, EAC_FILE, FULL_POOL_FT, PROCESSED, RAW


def main():
    df = pd.read_csv(PROCESSED / "levels_daily.csv", parse_dates=["date"]).set_index("date")
    elev = df["elevation_ft"].dropna()
    eac = pd.read_csv(RAW / "capacity" / EAC_FILE)

    def capacity(ft):
        return np.interp(ft, eac["Elevation_ft_NGVD29"], eac["Capacity_acrefeet"])

    def area_km2(ft):
        return np.interp(ft, eac["Elevation_ft_NGVD29"], eac["Area_acres"]) * 0.0040468564

    live_full = capacity(FULL_POOL_FT) - capacity(DEAD_POOL_FT)
    rows = []
    for year, s in elev.groupby(elev.index.year):
        if year < 1964:
            continue
        mean = float(s.mean())
        rows.append({
            "label": year,
            "elevation_ft": round(mean, 2),
            "high_ft": round(float(s.max()), 2), "high_day": f"{s.idxmax():%Y-%m-%d}",
            "low_ft": round(float(s.min()), 2), "low_day": f"{s.idxmin():%Y-%m-%d}",
            "below_full_pool_ft": round(FULL_POOL_FT - mean, 2),
            "pct_live_capacity": round(float((capacity(mean) - capacity(DEAD_POOL_FT)) / live_full * 100), 1),
            "surface_km2": round(float(area_km2(mean)), 1),
            "days": int(s.size),
            "complete_year": bool(s.index.max().month == 12 and s.index.max().day == 31),
            "last_day": f"{s.index.max():%Y-%m-%d}",
        })
    out = pd.DataFrame(rows)
    out.to_csv(PROCESSED / "levels_yearly.csv", index=False)
    print(out[["label", "elevation_ft", "high_ft", "low_ft", "below_full_pool_ft", "pct_live_capacity",
               "surface_km2", "days"]].to_string(index=False))


if __name__ == "__main__":
    main()
