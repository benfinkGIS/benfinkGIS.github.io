"""Step 1c: a first-look map and a few counts from the downloaded layers.

Draws the draft study area with the county washes, mapped riparian habitat,
parks, protected lands, main roads and the iNaturalist records, and writes
work/first_look.jpg and work/first_look.json. Nothing here is modelled; it is
a check on the extent and on whether the records have anything to say.

Run:  py tools/washes/03_first_look.py
"""
import json

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import box

from common import BBOX, CONTEXT, EPSG, SIGHTINGS, SPECIES, WORK

NEAR_M = 50          # "along a wash" for the count below
FLOW_WIDTH = {"UNDER 500 CFS": 0.5, "500-1000 CFS": 0.9, "1000-2000 CFS": 1.3,
              "2000-5000 CFS": 1.9, "5000-10000 CFS": 2.6, "OVER 10000 CFS": 3.4}
RIP_COLOUR = {"H": "#1b7837", "A": "#5aae61", "B": "#a6dba0", "C": "#d9f0d3", "D": "#f1f7e8"}
SP_COLOUR = {"bobcat": "#d95f02", "flycatcher": "#e7298a", "queen": "#7570b3"}


def layer(name):
    g = gpd.read_file(CONTEXT / f"{name}.geojson")
    return g.set_crs(EPSG, allow_override=True)


def main():
    area = box(*BBOX)
    washes, riparian = layer("washes"), layer("riparian")
    streets, parks, protected = layer("streets"), layer("parks"), layer("protected")
    structures, nbi = layer("structures"), layer("bridges_nbi")
    washes = washes.clip(area)
    riparian["base"] = riparian["CLASS"].str.replace("IRA-", "", regex=False)

    fig, ax = plt.subplots(figsize=(15, 12), dpi=130)
    ax.set_facecolor("#f4efe6")
    protected.plot(ax=ax, color="#dfe8cf", edgecolor="none")
    parks.plot(ax=ax, color="#c3dba6", edgecolor="none")
    for cls, colour in RIP_COLOUR.items():
        riparian[riparian["base"] == cls].plot(ax=ax, color=colour, edgecolor="none")
    big = streets[streets["ROADCAT_DS"] != "Minor local road"]
    streets[streets["ROADCAT_DS"] == "Minor local road"].plot(ax=ax, color="#d8d2c6", linewidth=0.2)
    big.plot(ax=ax, color="#9a948a", linewidth=0.7)
    for cls, width in FLOW_WIDTH.items():
        washes[washes["CFS_SHORT2"] == cls].plot(ax=ax, color="#2b6cb0", linewidth=width)
    washes[~washes["CFS_SHORT2"].isin(FLOW_WIDTH)].plot(ax=ax, color="#2b6cb0", linewidth=0.5)

    stats = dict(near_m=NEAR_M, species={})
    near = washes.buffer(NEAR_M).union_all().intersection(area)
    stats["share_of_area_near_a_wash"] = round(near.area / area.area, 3)
    rip_all = riparian.union_all().intersection(area)
    stats["share_of_area_mapped_riparian"] = round(rip_all.area / area.area, 3)
    for sp in SPECIES:
        pts = gpd.read_file(SIGHTINGS / f"{sp['id']}.geojson").to_crs(EPSG)
        pts = pts[pts.within(area)]
        good = pts[pts["accuracy_m"].fillna(0) <= 100]
        stats["species"][sp["id"]] = dict(
            records=len(pts), accuracy_100m_or_better=len(good),
            near_a_wash=round(float(good.within(near).mean()), 3),
            in_mapped_riparian=round(float(good.within(rip_all).mean()), 3))
        good.plot(ax=ax, color=SP_COLOUR[sp["id"]], markersize=7, alpha=0.75,
                  edgecolor="white", linewidth=0.2, zorder=5)

    # Name the washes that carry the most water, once each, at their midpoint.
    named = washes[washes["WASHNAME"].notna()
                   & washes["CFS_SHORT2"].isin(list(FLOW_WIDTH)[2:])]
    for name, grp in named.dissolve("WASHNAME").iterrows():
        if name.strip() in ("", "UNKNOWN"):
            continue
        p = grp.geometry.representative_point()
        ax.annotate(name.title(), (p.x, p.y), fontsize=6.5, color="#123a63", ha="center",
                    zorder=6, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))

    ax.plot(*area.exterior.xy, color="black", linewidth=1.2, linestyle="--")
    ax.set_xlim(BBOX[0] - 600, BBOX[2] + 600)
    ax.set_ylim(BBOX[1] - 600, BBOX[3] + 600)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Draft study area: county washes, mapped riparian habitat and "
                 "iNaturalist records (first look, nothing modelled)", fontsize=12)
    handles = [
        Line2D([], [], color="black", linestyle="--",
               label=f"Draft study area, {(BBOX[2] - BBOX[0]) / 1000:.0f} x "
                     f"{(BBOX[3] - BBOX[1]) / 1000:.0f} km"),
        Line2D([], [], color="#2b6cb0", linewidth=2.6, label="County wash network (wider = more flow)"),
        Patch(color="#1b7837", label="Riparian class H"),
        Patch(color="#5aae61", label="Riparian class A"),
        Patch(color="#a6dba0", label="Riparian class B"),
        Patch(color="#d9f0d3", label="Riparian class C and D"),
        Patch(color="#c3dba6", label="Parks"),
        Patch(color="#dfe8cf", label="Protected lands"),
        Line2D([], [], color="#9a948a", linewidth=1, label="Main roads"),
    ] + [Line2D([], [], marker="o", linestyle="", color=SP_COLOUR[s["id"]],
                label=f"{s['common']} ({stats['species'][s['id']]['accuracy_100m_or_better']})")
         for s in SPECIES]
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.92)
    fig.tight_layout()
    fig.savefig(WORK / "first_look.jpg", pil_kwargs=dict(quality=88))

    stats["wash_segments"] = len(washes)
    stats["wash_km"] = round(float(washes.length.sum()) / 1000, 1)
    stats["wash_names"] = int(washes["WASHNAME"].dropna().str.strip()
                              .loc[lambda s: ~s.isin(["", "UNKNOWN"])].nunique())
    stats["named_km"] = round(float(washes[washes["WASHNAME"].notna()
                                           & ~washes["WASHNAME"].isin(["", " ", "UNKNOWN"])]
                                    .length.sum()) / 1000, 1)
    stats["flood_map_structures"] = structures["STRUCT_TYP"].value_counts().to_dict()
    stats["nbi_bridges"] = len(nbi)
    stats["riparian_classes_ha"] = (riparian.assign(ha=riparian.intersection(area).area / 1e4)
                                    .groupby("CLASS")["ha"].sum().round(1).to_dict())
    stats["riparian_change_dates"] = sorted(riparian["CHNGDATE"].dropna().astype(str).unique())[:12]
    (WORK / "first_look.json").write_text(json.dumps(stats, indent=2, default=str))
    print(json.dumps(stats, indent=2, default=str))


if __name__ == "__main__":
    main()
