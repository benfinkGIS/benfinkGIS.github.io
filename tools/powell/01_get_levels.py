"""Download Lake Powell's daily elevation and storage from Reclamation.

Saves the files exactly as served in lake-powell/work/raw/levels/, then writes
a cleaned daily table (processed/levels_daily.csv) and a short summary
(processed/levels_summary.json) with the dates and values the animation and
its labels use. Elevations stay in feet on Reclamation's datum here; the datum
and unit conversion happens in a later step.

    py -I tools/powell/01_get_levels.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import datetime as dt
import json

import pandas as pd
import requests

from common import (DEAD_POOL_FT, FULL_POOL_FT, HYDRODATA, MIN_POWER_POOL_FT,
                    PROCESSED, RAW_LEVELS, SERIES, USER_AGENT)


def fetch(name, code):
    url = HYDRODATA.format(code=code)
    r = requests.get(url, headers=USER_AGENT, timeout=120)
    r.raise_for_status()
    path = RAW_LEVELS / f"powell_{name}.csv"
    path.write_bytes(r.content)
    return url, path


def main():
    RAW_LEVELS.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    sources, frames = {}, []
    for name, code in SERIES.items():
        url, path = fetch(name, code)
        sources[name] = url
        s = pd.read_csv(path, parse_dates=["datetime"]).set_index("datetime").iloc[:, 0].rename(name)
        print(f"{name}: {len(s)} rows, {s.index.min():%Y-%m-%d} to {s.index.max():%Y-%m-%d}")
        frames.append(s)
    (RAW_LEVELS / "source.json").write_text(json.dumps(
        {"fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "urls": sources},
        indent=1), encoding="utf-8")

    df = pd.concat(frames, axis=1, sort=True)
    df = df[~df.index.duplicated()]
    df.index.name = "date"

    # Checks: one row per day, values inside the possible range, no wild day-to-day jumps
    elev = df["elevation_ft"].dropna()
    days = pd.date_range(elev.index.min(), elev.index.max(), freq="D")
    missing = days.difference(elev.index)
    out_of_range = elev[(elev < 3100) | (elev > 3710)]
    jumps = elev.diff().abs()
    print(f"elevation: {len(missing)} missing days, {len(out_of_range)} values outside 3,100 to 3,710 ft, "
          f"largest one-day change {jumps.max():.2f} ft on {jumps.idxmax():%Y-%m-%d}")

    df.to_csv(PROCESSED / "levels_daily.csv", float_format="%.2f")

    peak = elev.idxmax()
    after_peak = elev[elev.index > peak]
    first_full = elev[elev >= FULL_POOL_FT].index.min()
    low = after_peak.idxmin()
    summary = {
        "elevation_first_day": f"{elev.index.min():%Y-%m-%d}",
        "elevation_first_ft": float(elev.iloc[0]),
        "storage_first_day": f"{df['storage_af'].dropna().index.min():%Y-%m-%d}",
        "first_reached_full_pool": f"{first_full:%Y-%m-%d}",
        "record_high_day": f"{peak:%Y-%m-%d}",
        "record_high_ft": float(elev[peak]),
        "record_low_since_filling_day": f"{low:%Y-%m-%d}",
        "record_low_since_filling_ft": float(elev[low]),
        "latest_day": f"{elev.index.max():%Y-%m-%d}",
        "latest_ft": float(elev.iloc[-1]),
        "missing_days": [f"{d:%Y-%m-%d}" for d in missing],
        "reference_ft": {"full_pool": FULL_POOL_FT, "minimum_power_pool": MIN_POWER_POOL_FT,
                         "dead_pool": DEAD_POOL_FT},
    }
    (PROCESSED / "levels_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    for k, v in summary.items():
        if k != "reference_ft":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
