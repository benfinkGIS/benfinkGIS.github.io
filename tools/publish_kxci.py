#!/usr/bin/env python3
"""KXCI 91.3 FM signal reach, step 4: write the site page's data and the static map.

Usage (from the repo root, after build_kxci.py and model_kxci_terrain.py):
    py tools/publish_kxci.py

Writes
------
kxci-signal/data/kxci.json   licence, counts, the town table, both contours, map bounds
kxci-signal/data/field.png   the modelled field as a data image in Web Mercator:
                               red   = field at 9.1 m, dBu x 2 (0 = no value)
                               green = field at 1.5 m, dBu x 2
                               blue  = 255 inside the FCC 60 dBu contour
                             The page colours it in the browser and reads it on hover.
kxci-signal/kxci-reach.png   static map (rooftop height)
"""
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from PIL import Image
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_kxci_terrain as model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "kxci-signal" / "work"
SITE = ROOT / "kxci-signal"
DATA = SITE / "data"
PX = 1000                      # width of the data image
PLACE_MIN_POP = 5000

BANDS = [(40, "#cde2fb"), (50, "#86b6ef"), (60, "#3987e5"), (70, "#1c5cab"), (80, "#0d366b")]
SHADOW = "#eb6834"


def merc_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    summary = json.loads((WORK / "summary.json").read_text())
    if "terrain" not in summary:
        sys.exit("run tools/model_kxci_terrain.py first")
    lic, terrain = summary["licence"], summary["terrain"]
    f = np.load(WORK / "field.npz")
    field, rx_d, (tx_x, tx_y) = f["field"], f["d"], f["tx"]
    contours = gpd.read_file(WORK / "kxci.gpkg", layer="contours")
    cur = contours[contours.name == "current"].geometry.iloc[0]
    to_ll = Transformer.from_crs(26912, 4326, always_xy=True).transform
    to_utm = Transformer.from_crs(4326, 26912, always_xy=True).transform

    # ---- the data image, in Web Mercator so Leaflet can lay it straight on the map
    r = model.R_MAX
    ring = [to_ll(tx_x + r * math.sin(a), tx_y + r * math.cos(a))
            for a in np.radians(np.arange(0, 360, 2))]
    west, east = min(p[0] for p in ring), max(p[0] for p in ring)
    south, north = min(p[1] for p in ring), max(p[1] for p in ring)
    h = round(PX * (merc_y(north) - merc_y(south)) / math.radians(east - west))
    lon = west + (np.arange(PX) + 0.5) / PX * (east - west)
    my = merc_y(north) - (np.arange(h) + 0.5) / h * (merc_y(north) - merc_y(south))
    lat = np.degrees(2 * np.arctan(np.exp(my)) - np.pi / 2)
    LON, LAT = np.meshgrid(lon, lat)
    X, Y = to_utm(LON.ravel(), LAT.ravel())
    dist = np.hypot(X - tx_x, Y - tx_y)
    img = np.zeros((h * PX, 4), dtype="uint8")
    img[:, 3] = 255
    vals = []
    for ch in (0, 1):
        v = model.field_at(field[ch], rx_d, tx_x, tx_y, X, Y)
        v[dist < model.R_MIN] = 120.0          # the tower is in plain sight here
        vals.append(v.reshape(h, PX))
        img[:, ch] = np.where(np.isnan(v), 0, np.clip(np.round(v * 2), 1, 255)).astype("uint8")
    inside = shapely.contains_xy(cur, X, Y)
    img[:, 2] = np.where(inside, 255, 0)
    Image.fromarray(img.reshape(h, PX, 4), "RGBA").save(DATA / "field.png", optimize=True)
    print(f"field.png {PX} x {h}, {(DATA / 'field.png').stat().st_size / 1e6:.2f} MB")

    # ---- the numbers
    def ring_ll(geom):
        return [[round(x, 5), round(y, 5)] for x, y in
                (to_ll(*c) for c in geom.exterior.coords)]

    old = contours[contours.name == "callsign_lookup"].geometry.iloc[0]
    lookup = summary["callsign_lookup"]
    places = [p for p in terrain["by_place"] if p["population"] >= PLACE_MIN_POP]
    out = dict(
        licence=lic,
        auxiliary=[dict(lat=o["lat"], lon=o["lon"], erp_kw=o["erp_kw"], service=o["service"])
                   for o in summary["other_records"]],
        lookup=dict(file_number=lookup["file_number"], erp_kw=lookup["erp"],
                    lat=round(lookup["antenna_lat"], 5), lon=round(lookup["antenna_lon"], 5),
                    rcamsl_m=lookup["rcamsl"], stale=lookup["stale"]),
        antenna_agl_m=terrain["antenna_agl_m"],
        threshold_dbu=terrain["threshold_dbu"],
        radius_km=terrain["radius_km"],
        study=summary["study_area"],
        fcc=dict(summary["inside_fcc"], area_sqkm=summary["contour_area_sqkm"],
                 km_min=summary["contour_km_min"], km_max=summary["contour_km_max"]),
        fcc_1991=summary["inside_1991"],
        rooftop=terrain["dbu_9m"], car=terrain["dbu_1p5m"],
        warn_share=terrain["warn_share"],
        places=places, place_min_pop=PLACE_MIN_POP,
        contour=ring_ll(cur), contour_1991=ring_ll(old),
        bounds=[[round(south, 5), round(west, 5)], [round(north, 5), round(east, 5)]],
        bands=BANDS, shadow=SHADOW)
    (DATA / "kxci.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"kxci.json {(DATA / 'kxci.json').stat().st_size / 1e3:.0f} kB, {len(places)} towns")

    static_map(vals[0], inside.reshape(h, PX), (west, east, south, north), lon, lat,
               cur, lic, to_ll, summary, terrain)


def static_map(v, inside, extent, lon, lat, cur, lic, to_ll, summary, terrain):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap, to_rgba
    from matplotlib.patches import Patch

    west, east, south, north = extent
    z = np.load(WORK / "dem.npy")
    meta = json.loads((WORK / "dem.json").read_text())
    to_utm = Transformer.from_crs(4326, 26912, always_xy=True).transform
    LON, LAT = np.meshgrid(lon, lat)
    X, Y = to_utm(LON.ravel(), LAT.ravel())
    elev = model.sample_dem(z, meta, X, Y).reshape(v.shape)
    gy, gx = np.gradient(elev, 150.0)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy) * 2)
    aspect = np.arctan2(-gx, gy)
    shade = (np.sin(np.radians(45)) * np.sin(slope)
             + np.cos(np.radians(45)) * np.cos(slope) * np.cos(np.radians(135) - aspect))

    my = [model_y for model_y in (math.log(math.tan(math.pi / 4 + math.radians(a) / 2))
                                  for a in (south, north))]
    ext = (west, east, my[0], my[1])

    def y_of(latitude):
        return math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2))

    fig = plt.figure(figsize=(9, 10.2), dpi=130, facecolor="#c0c0c0")
    ax = fig.add_axes([0.03, 0.12, 0.94, 0.80])
    ax.imshow(shade, cmap="gray", vmin=-0.2, vmax=1.1, extent=ext, aspect="auto")
    cmap = ListedColormap([c for _, c in BANDS])
    norm = BoundaryNorm([b for b, _ in BANDS] + [200], cmap.N)
    ax.imshow(np.ma.masked_where(np.isnan(v) | (v < BANDS[0][0]), v), cmap=cmap, norm=norm,
              extent=ext, aspect="auto", alpha=0.72)
    shadow = np.zeros(v.shape + (4,))
    shadow[inside & (v < terrain["threshold_dbu"])] = to_rgba(SHADOW, 0.9)
    ax.imshow(shadow, extent=ext, aspect="auto")
    cx, cy = zip(*[to_ll(*c) for c in cur.exterior.coords])
    ax.plot(cx, [y_of(a) for a in cy], color="#fff", lw=3.2)
    ax.plot(cx, [y_of(a) for a in cy], color="#000", lw=1.4)
    ax.plot(lic["lon"], y_of(lic["lat"]), marker="^", ms=11, mfc="#ffff00", mec="#000", mew=1.2)
    ax.annotate("KXCI tower", (lic["lon"], y_of(lic["lat"])), xytext=(8, -4),
                textcoords="offset points", fontsize=9, fontweight="bold",
                bbox=dict(fc="#ffffe1", ec="#000", lw=0.6, pad=1.5))
    blocks = gpd.read_file(WORK / "kxci.gpkg", layer="blocks", ignore_geometry=True)
    for name in ("Tucson", "Oro Valley", "Marana", "Green Valley", "Sahuarita", "Vail",
                 "Benson", "Catalina Foothills", "Picture Rocks", "Saddlebrooke"):
        sub = blocks[(blocks.place == name) & (blocks["pop"] > 0)]
        if sub.empty:
            continue
        px = np.average(sub.px, weights=sub["pop"])
        py = np.average(sub.py, weights=sub["pop"])
        lo, la = to_ll(px, py)
        ax.annotate("SaddleBrooke" if name == "Saddlebrooke" else name, (lo, y_of(la)),
                    ha="center", va="center", fontsize=8.5,
                    bbox=dict(fc="#ffffff", ec="none", alpha=0.75, pad=1))
    ax.set_xlim(west, east)
    ax.set_ylim(my[0], my[1])
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#000")
    fig.text(0.03, 0.955, "KXCI 91.3 FM: predicted reach, with and without the mountains",
             fontsize=14, fontweight="bold")
    fig.text(0.03, 0.93, f"{summary['inside_fcc']['population']:,} people live inside the FCC "
             f"service contour. The terrain model puts "
             f"{terrain['dbu_9m']['inside_fcc_shadowed']:,} of them in a shadow.", fontsize=10)
    labels = ["40 to 50 dBu", "50 to 60", "60 to 70", "70 to 80", "80 or more"]
    handles = [Patch(fc=c, ec="#000", lw=0.5, label=t) for (_, c), t in zip(BANDS, labels)]
    handles.append(Patch(fc=SHADOW, ec="#000", lw=0.5,
                         label="Inside the contour, modelled under 60 dBu"))
    handles.append(plt.Line2D([], [], color="#000", lw=1.6, label="FCC 60 dBu service contour"))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.03, 0.025), ncol=4,
               fontsize=8.5, frameon=False, title="Modelled field strength at a rooftop antenna",
               title_fontsize=9, alignment="left")
    fig.text(0.97, 0.012, "Fink Geospatial | FCC licence data, USGS 3DEP elevation, "
             "2020 Census | Longley-Rice terrain model", ha="right", fontsize=7.5)
    fig.savefig(SITE / "kxci-reach.png", facecolor=fig.get_facecolor())
    print("kxci-reach.png")


if __name__ == "__main__":
    main()
