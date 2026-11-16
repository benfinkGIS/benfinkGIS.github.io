"""Draw a quick check chart of Lake Powell's elevation history.

Reads processed/levels_daily.csv and levels_summary.json and writes
processed/levels_check.png: the daily elevation with the full pool, minimum
power pool and dead pool lines, and the record high, record low and latest
value marked.

    py -I tools/powell/02_plot_levels.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import PROCESSED

SURFACE, INK, MUTED, GRID, WATER = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6"


def main():
    df = pd.read_csv(PROCESSED / "levels_daily.csv", parse_dates=["date"]).set_index("date")
    s = json.loads((PROCESSED / "levels_summary.json").read_text(encoding="utf-8"))
    elev = df["elevation_ft"].dropna()

    fig, ax = plt.subplots(figsize=(12, 6), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.plot(elev.index, elev.values, color=WATER, lw=1.6)

    right = elev.index.max() + pd.Timedelta(days=250)
    for label, ft in (("Full pool", s["reference_ft"]["full_pool"]),
                      ("Minimum power pool", s["reference_ft"]["minimum_power_pool"]),
                      ("Dead pool", s["reference_ft"]["dead_pool"])):
        ax.axhline(ft, color=MUTED, lw=0.8, ls=(0, (4, 3)))
        ax.text(right, ft, f"{label}\n{ft:,.0f} ft", color=MUTED, fontsize=8.5, va="center", ha="left")

    def when(day):
        d = pd.Timestamp(day)
        return d, f"{d:%b} {d.day}, {d.year}"

    for label, day, ft, offset, ha in (
            ("Record high", s["record_high_day"], s["record_high_ft"], (0, 9), "center"),
            ("Record low", s["record_low_since_filling_day"], s["record_low_since_filling_ft"], (-6, -17), "right")):
        d, text = when(day)
        ax.plot([d], [ft], "o", ms=6, color=WATER, mec=SURFACE, mew=1.5, zorder=3)
        ax.annotate(f"{label}: {ft:,.2f} ft, {text}", (d, ft), xytext=offset,
                    textcoords="offset points", ha=ha, fontsize=8.5, color=INK)
    d, text = when(s["latest_day"])
    ax.plot([d], [s["latest_ft"]], "o", ms=6, color=WATER, mec=SURFACE, mew=1.5, zorder=3)
    ax.text(right, s["latest_ft"], f"Latest, {text}\n{s['latest_ft']:,.2f} ft", color=INK, fontsize=8.5,
            va="center", ha="left")

    ax.set_xlim(pd.Timestamp("1963-01-01"), right)
    ax.set_ylim(3340, 3735)
    ax.set_ylabel("Water surface elevation (feet)", color=MUTED, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    fig.suptitle("Lake Powell daily water surface elevation", x=0.065, ha="left", fontsize=13, color=INK)
    ax.set_title(f"{s['elevation_first_day']} to {s['latest_day']}. Bureau of Reclamation, Upper Colorado "
                 "Region HydroData (site 919).", loc="left", fontsize=9, color=MUTED, pad=10)
    fig.subplots_adjust(left=0.065, right=0.885, top=0.87, bottom=0.07)
    out = PROCESSED / "levels_check.png"
    fig.savefig(out, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main()
