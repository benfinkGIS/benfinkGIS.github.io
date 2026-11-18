"""Step 11: the static map for slides and the top of the write-up.

One 16:9 picture: the 2023 imagery in gray, the ground that gathers the
modeled movement of one, two or all three animals, the interstate and the
state route, and the listed gaps with their tags; beside it the gap list.

Writes downloads/wash_corridors_gaps.jpg (3840 x 2160) and a 1600-pixel copy
for the page. Needs work/gaps/naip_5m.npy (the imagery averaged to 5 m; made here from the
1 m tiles the first time, which needs ArcGIS Pro's Python), the composite from
16_connectivity.py and data/gaps.json from 18_gaps.py.

Run:  propy tools/washes/19_hero_map.py
"""
import json
import textwrap

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patheffects
from matplotlib.patches import Rectangle

from common import BBOX, PROJECT, WORK

X0, Y0, X1, Y1 = BBOX
OUT = PROJECT / "downloads"
BASE = WORK / "gaps" / "naip_5m.npy"
INK, PAPER, MUTED = "#f2efe6", "#14171a", "#a9b0b3"
COUNT_RGBA = [(0, 0, 0, 0), (140, 41, 129, 150), (254, 159, 109, 225), (252, 253, 191, 255)]
SPECIES = [("bobcat", "Bobcat", "road crossings to rebuild as open spans"),
           ("flycatcher", "Vermilion flycatcher", "stretches of wash to plant with trees"),
           ("queen", "Queen butterfly", "breaks in a wash to plant as a strip")]
PLACES = [("Tucson Mountains", 490300, 3570200, 0), ("Santa Catalina\nMountains", 509000, 3582600, 0),
          ("Oro Valley", 503300, 3587000, 0), ("Casas Adobes", 499300, 3578900, 0),
          ("Flowing Wells", 500300, 3571300, 0), ("Catalina Foothills", 508000, 3575600, 0),
          ("Marana", 489400, 3587000, 0)]
LINES = [("Interstate 10", 493900, 3576500, -53), ("Oracle Road", 501650, 3570300, 90),
         ("Rillito River", 505000, 3572650, -8), ("Cañada del Oro", 500250, 3582950, 42),
         ("Santa Cruz River", 494050, 3574600, -55)]
# where each tag sits relative to its gap, in meters, so that neighbors do not collide
NUDGE = {"F3": (-750, 300), "Q5": (450, -520), "B2": (350, 450), "B4": (500, 350), "B3": (500, 350)}


def base_image():
    if not BASE.exists():
        import arcpy
        out = np.zeros((int((Y1 - Y0) / 5), int((X1 - X0) / 5), 3), "uint8")
        for path in sorted((WORK / "naip").glob("naip_r*.tif")):
            e = arcpy.Raster(str(path)).extent
            a = arcpy.RasterToNumPyArray(str(path))[:3].astype("float32")
            r0, c0 = int(round(Y1 - e.YMax)), int(round(e.XMin - X0))
            h, w = a.shape[1] // 5 * 5, a.shape[2] // 5 * 5
            b = a[:, :h, :w].reshape(3, h // 5, 5, w // 5, 5).mean(axis=(2, 4))
            out[r0 // 5:(r0 + h) // 5, c0 // 5:(c0 + w) // 5] = np.moveaxis(b, 0, 2).clip(0, 255)
        BASE.parent.mkdir(exist_ok=True)
        np.save(BASE, out)
    a = np.load(BASE).astype("float32")
    gray = a @ np.array([0.30, 0.59, 0.11], "float32")
    bad = a[..., 2] == 0                      # two small squares with no blue band in the source tiles
    gray[bad] = np.median(gray)
    gray = np.clip((gray - 40) / 170, 0, 1) ** 1.15
    tint = np.array([0.50, 0.52, 0.50], "float32")          # dark, slightly cool, so the colors carry
    return (gray[..., None] * tint * 255).astype("uint8")


def halo(width=2.2, color=PAPER):
    return [patheffects.withStroke(linewidth=width, foreground=color)]


def main():
    OUT.mkdir(exist_ok=True)
    doc = json.loads((PROJECT / "data" / "gaps.json").read_text(encoding="utf-8"))
    where = {c["id"]: (c["x"], c["y"]) for c in json.loads((WORK / "gaps" / "candidates.json").read_text())}
    L = np.load(WORK / "connectivity" / "layers_10m.npz")
    count = np.load(WORK / "connectivity" / "arrays" / "count.npy")
    valid = json.loads((WORK / "connectivity" / "validation.json").read_text())["species"]

    fig = plt.figure(figsize=(16, 9), dpi=240, facecolor=PAPER)
    map_h = 8.5
    map_w = map_h * (X1 - X0) / (Y1 - Y0)
    ax = fig.add_axes([0.25 / 16, 0.25 / 9, map_w / 16, map_h / 9])
    extent = [X0, X1, Y0, Y1]
    ax.imshow(base_image(), extent=extent, interpolation="bilinear")
    ax.imshow(np.array(COUNT_RGBA, "uint8")[count], extent=extent, interpolation="nearest")
    road = np.zeros(L["road"].shape + (4,), "uint8")
    road[L["road"] == 7] = (255, 255, 255, 230)
    road[L["road"] == 5] = (255, 255, 255, 150)
    ax.imshow(road, extent=extent, interpolation="nearest")
    ax.set_xlim(X0, X1)
    ax.set_ylim(Y0, Y1)
    ax.set_axis_off()
    ax.add_patch(Rectangle((X0, Y0), X1 - X0, Y1 - Y0, fill=False, ec=MUTED, lw=0.8))
    for name, x, y, rot in PLACES:
        ax.text(x, y, name.upper(), color=INK, fontsize=8.5, ha="center", va="center", rotation=rot,
                alpha=0.85, linespacing=1.1, path_effects=halo(2.5), fontweight="bold")
    for name, x, y, rot in LINES:
        ax.text(x, y, name, color=INK, fontsize=7.5, ha="center", va="center", rotation=rot,
                style="italic", path_effects=halo(2.2))
    for g in doc["gaps"]:
        x, y = where[g["id"]]
        dx, dy = NUDGE.get(g["label"], (0, 420))
        ax.plot([x, x + dx], [y, y + dy], color="#00e5ff", lw=1.0, solid_capstyle="round")
        ax.plot(x, y, "o", ms=5.5, mfc="#00e5ff", mec=PAPER, mew=0.9)
        ax.text(x + dx, y + dy, g["label"], color="#000", fontsize=8, fontweight="bold", ha="center", va="center",
                bbox=dict(boxstyle="square,pad=0.22", fc="#ffffe1", ec="#000", lw=0.9))
    # scale bar and north
    sx, sy = X1 - 6400, Y0 + 700
    ax.plot([sx, sx + 5000], [sy, sy], color=INK, lw=2.2, solid_capstyle="butt", path_effects=halo(4))
    ax.text(sx + 2500, sy + 260, "5 km", color=INK, fontsize=8, ha="center", path_effects=halo())
    ax.annotate("N", xy=(X1 - 800, Y0 + 1900), xytext=(X1 - 800, Y0 + 800), color=INK, fontsize=9,
                ha="center", va="center", fontweight="bold", path_effects=halo(),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4))

    # the panel
    px = (0.25 + map_w + 0.35) / 16
    pw = 1 - px - 0.3 / 16
    panel = fig.add_axes([px, 0.25 / 9, pw, map_h / 9])
    panel.set_xlim(0, 1)
    panel.set_ylim(0, 1)
    panel.set_axis_off()
    y = 1.0
    panel.text(0, y, "Where northwest Tucson’s washes\ncarry wildlife, and where they break", color=INK,
               fontsize=17.5, fontweight="bold", va="top", linespacing=1.15)
    y -= 0.105
    panel.text(0, y, "Modeled movement of bobcat, vermilion flycatcher and queen butterfly\n"
                     "between the Tucson Mountains and the Catalinas, Grant Road to Tangerine Road",
               color=MUTED, fontsize=8.6, va="top", linespacing=1.35)
    y -= 0.075
    for i, label in ((1, "one animal"), (2, "two"), (3, "all three")):
        x = (i - 1) * 0.2
        panel.add_patch(Rectangle((x, y - 0.018), 0.035, 0.018, fc=np.array(COUNT_RGBA[i][:3]) / 255, ec=INK, lw=0.4))
        panel.text(x + 0.045, y - 0.009, label, color=INK, fontsize=8.6, va="center")
    panel.text(0.62, y - 0.009, "Ground that gathers\nmodeled movement", color=MUTED, fontsize=7.6, va="center",
               linespacing=1.2)
    y -= 0.05
    for sp, name, what in SPECIES:
        rows = [g for g in doc["gaps"] if g["species"] == sp]
        panel.plot([0, 1], [y, y], color=MUTED, lw=0.5)
        y -= 0.014
        panel.text(0, y, name, color=INK, fontsize=10.5, fontweight="bold", va="top")
        panel.text(1, y - 0.004, what, color=MUTED, fontsize=8, va="top", ha="right")
        y -= 0.036
        for g in rows:
            panel.text(0.0, y, g["label"], color="#000", fontsize=7.6, fontweight="bold", va="top",
                       bbox=dict(boxstyle="square,pad=0.2", fc="#ffffe1", ec="#000", lw=0.7))
            text = textwrap.fill(g.get("short") or g["where"], 66)
            panel.text(0.075, y + 0.002, text, color=INK, fontsize=8, va="top", linespacing=1.2)
            panel.text(1, y + 0.002, f"{g['before']:.1f} → {g['after']:.1f}", color=INK, fontsize=8, va="top", ha="right")
            y -= 0.019 * (text.count("\n") + 1) + 0.0085
        y -= 0.008
    panel.plot([0, 1], [y, y], color=MUTED, lw=0.5)
    y -= 0.014
    auc = {sp: valid[sp]["against_group"]["current"] for sp, _, _ in SPECIES}
    note = ("Figures at right: modeled movement through the gap now and with the repair, as a multiple of what "
            "uniform open ground would carry. Each gap was found by rerunning the model with that one repair made. "
            f"Checked against iNaturalist records, only the flycatcher model beats chance ({100 * auc['flycatcher']['auc']:.0f}% "
            f"against {100 * auc['bobcat']['auc']:.0f}% for the bobcat and {100 * auc['queen']['auc']:.0f}% for the queen, "
            "where 50% is a coin toss), so the bobcat and queen gaps show what the chosen costs imply. A shortlist for "
            "a site visit, not a design.")
    panel.text(0, y, textwrap.fill(note, 96), color=MUTED, fontsize=7.3, va="top", linespacing=1.35)
    panel.text(0, 0.0, "Omniscape on a 10 m grid. USGS 3DEP lidar 2021, NAIP 2023, NLCD 2021, Pima County GIS, "
                       "iNaturalist.\nfinkgeo.com/tucson-washes  ·  " + doc["built"], color=MUTED, fontsize=7,
               va="bottom", linespacing=1.4)
    from PIL import Image
    png = WORK / "gaps" / "wash_corridors_gaps.png"       # lossless copy, kept out of the repository
    fig.savefig(png, facecolor=PAPER)
    full, small = OUT / "wash_corridors_gaps.jpg", OUT / "wash_corridors_gaps_1600.jpg"
    img = Image.open(png).convert("RGB")
    img.save(full, quality=90, optimize=True)
    img.resize((1600, 900), Image.LANCZOS).save(small, quality=86, optimize=True)
    print("wrote", full.name, full.stat().st_size, small.name, small.stat().st_size)


if __name__ == "__main__":
    main()
