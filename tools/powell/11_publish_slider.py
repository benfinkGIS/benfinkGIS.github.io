"""Turn the yearly Blender frames into the files the year-slider page loads.

Reads lake-powell/work/renders/<view>/<view>_<year>.png (made by
08_blender_scene.py --levels processed/levels_yearly.csv) and writes, into the
part of the project that is published with the site:

    lake-powell/frames/<year>.jpg     one picture per year, 1600 px wide
    lake-powell/data/years.json       the level, drop and capacity for each year

    py -I tools/powell/11_publish_slider.py [--view dam]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import datetime as dt
import json

import pandas as pd
from PIL import Image

from common import DEAD_POOL_FT, FULL_POOL_FT, MIN_POWER_POOL_FT, PROCESSED, PROJECT, RENDERS

WIDTH = 1600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default="dam")
    args = ap.parse_args()
    frames = PROJECT / "frames"
    frames.mkdir(exist_ok=True)
    (PROJECT / "data").mkdir(exist_ok=True)
    years = pd.read_csv(PROCESSED / "levels_yearly.csv")
    out, total = [], 0
    for row in years.itertuples():
        src = RENDERS / args.view / f"{args.view}_{row.label}.png"
        if not src.exists():
            raise SystemExit(f"missing frame {src}")
        img = Image.open(src).convert("RGB")
        img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
        dest = frames / f"{row.label}.jpg"
        img.save(dest, quality=84, optimize=True, progressive=True)
        total += dest.stat().st_size
        out.append({"year": int(row.label), "avg_ft": row.elevation_ft, "high_ft": row.high_ft, "high_day": row.high_day,
                    "low_ft": row.low_ft, "low_day": row.low_day, "below_full_ft": row.below_full_pool_ft,
                    "pct_capacity": row.pct_live_capacity, "surface_km2": row.surface_km2,
                    "complete": bool(row.complete_year), "last_day": row.last_day})
    meta = {"made": dt.date.today().isoformat(), "view": args.view, "frame_width": WIDTH, "frame_height": img.height,
            "full_pool_ft": FULL_POOL_FT, "min_power_pool_ft": MIN_POWER_POOL_FT, "dead_pool_ft": DEAD_POOL_FT,
            "years": out}
    (PROJECT / "data" / "years.json").write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out)} frames, {total / 1e6:.1f} MB, {out[0]['year']} to {out[-1]['year']}")


if __name__ == "__main__":
    main()
