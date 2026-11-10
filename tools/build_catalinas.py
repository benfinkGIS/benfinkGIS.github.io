"""Prepare the inputs for the 3D model of the Santa Catalina Mountains.

Downloads USGS 3DEP elevation and NAIP imagery for one rectangle in tiles
(the servers cap the size of a single image), then writes what Blender needs
into catalinas-3d/work/:

  dem.npy       float32 elevation in metres, UTM 12N, row 0 is the north edge
  texture.jpg   NAIP imagery over the same rectangle
  scene.json    extent, cell size, elevation range, landmarks in scene metres
  preview.png   hillshade with the landmarks, to check the frame

Run:  py tools/build_catalinas.py [--cell 10] [--tex 4]
        --cell   elevation cell size in metres (default 10)
        --tex    imagery pixel size in metres (default 4)
"""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
from pyproj import Transformer

Image.MAX_IMAGE_PIXELS = None    # the stitched imagery is over PIL's default cap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "catalinas-3d", "work")
TILES = os.path.join(WORK, "tiles")

# Frame in UTM 12N metres (EPSG:26912): Oro Valley to the San Pedro side,
# the Rillito to Oracle. 46 km wide, 42 km tall.
X0, Y0 = 496000, 3568000
WIDTH_M, HEIGHT_M = 46000, 42000

DEM_URL = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
           "3DEPElevation/ImageServer/exportImage")
NAIP_URL = ("https://imagery.nationalmap.gov/arcgis/rest/services/"
            "USGSNAIPPlus/ImageServer/exportImage")
DEM_TILE_PX = 2000     # server limit is 8000; smaller tiles fail less often
TEX_TILE_PX = 2000     # server limit is 4000, but tiles that big time out

# name, lon, lat. Summits are from the USGS Geographic Names service
# (carto.nationalmap.gov geonames, Landforms layer, class Summit), read
# 2026-11-10. The last three are rough points for orientation only.
LANDMARKS = [
    ("Mount Lemmon", -110.78834, 32.44291),
    ("Mount Bigelow", -110.71454, 32.41547),
    ("Mount Kimball", -110.87917, 32.37697),
    ("Pusch Peak", -110.93899, 32.37202),
    ("Table Mountain", -110.90802, 32.38215),
    ("Thimble Peak", -110.77398, 32.33723),
    ("Samaniego Peak", -110.81732, 32.46941),
    ("Rice Peak", -110.74972, 32.51194),
    ("Apache Peak", -110.75177, 32.55182),
    ("Agua Caliente Hill", -110.66592, 32.29532),
    ("Sabino Canyon (approx.)", -110.8224, 32.3100),
    ("Oracle (approx.)", -110.7709, 32.6109),
    ("Redington Pass (approx.)", -110.6010, 32.3010),
]

to_utm = Transformer.from_crs(4326, 26912, always_xy=True).transform


def download(url, params, path):
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return "cached"
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "terrain-scene/0.1"})
    for attempt in range(8):    # the USGS servers return 500/502 now and then
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            if body[:1] == b"{":
                raise RuntimeError(body[:200].decode())
            break
        except Exception as exc:
            if attempt == 7:
                raise
            print(f"  retry {attempt + 1} {os.path.basename(path)}: {exc}")
            time.sleep(6 * (attempt + 1))
    with open(path + ".part", "wb") as fh:
        fh.write(body)
    os.replace(path + ".part", path)
    return f"{len(body) / 1e6:.1f} MB"


def tile_plan(cell, tile_px):
    """Yield (row, col, bbox, width_px, height_px); row 0 is the north strip."""
    cols, rows = round(WIDTH_M / cell), round(HEIGHT_M / cell)
    for r, top in enumerate(range(0, rows, tile_px)):
        h = min(tile_px, rows - top)
        for c, left in enumerate(range(0, cols, tile_px)):
            w = min(tile_px, cols - left)
            x1 = X0 + left * cell
            y2 = Y0 + HEIGHT_M - top * cell
            yield r, c, (x1, y2 - h * cell, x1 + w * cell, y2), w, h


def fetch(kind, cell, tile_px, url, extra, ext):
    jobs = []
    for r, c, bbox, w, h in tile_plan(cell, tile_px):
        path = os.path.join(TILES, f"{kind}_{cell:g}m_{tile_px}px_r{r}_c{c}.{ext}")
        params = dict(extra, bbox=",".join(str(v) for v in bbox), bboxSR=26912,
                      imageSR=26912, size=f"{w},{h}", f="image")
        jobs.append((r, c, path, params))

    def run(job):
        r, c, path, params = job
        print(f"  {kind} r{r} c{c}: {download(url, params, path)}", flush=True)
        return r, c, path

    with ThreadPoolExecutor(3) as pool:
        done = list(pool.map(run, jobs))
    grid = {}
    for r, c, path in done:
        grid.setdefault(r, {})[c] = path
    return [[grid[r][c] for c in sorted(grid[r])] for r in sorted(grid)]


def hillshade(z, cell, az=315, alt=45):
    gy, gx = np.gradient(z, cell)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    a, h = np.radians(360 - az + 90), np.radians(alt)
    return (np.sin(h) * np.sin(slope)
            + np.cos(h) * np.cos(slope) * np.cos(a - aspect))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=float, default=10.0)
    ap.add_argument("--tex", type=float, default=4.0)
    args = ap.parse_args()
    os.makedirs(TILES, exist_ok=True)

    print("elevation tiles")
    dem_tiles = fetch("dem", args.cell, DEM_TILE_PX, DEM_URL,
                      dict(format="tiff", pixelType="F32", noData=-9999,
                           interpolation="RSP_BilinearInterpolation"), "tif")
    z = np.vstack([np.hstack([np.array(Image.open(p), dtype="float32") for p in row])
                   for row in dem_tiles])
    z[z < -1000] = np.nan
    empty = float(np.isnan(z).mean())
    print(f"dem {z.shape}, {np.nanmin(z):.0f} to {np.nanmax(z):.0f} m, "
          f"{empty * 100:.2f}% empty")
    z = np.where(np.isnan(z), np.nanmin(z), z).astype("float32")
    np.save(os.path.join(WORK, "dem.npy"), z)

    print("imagery tiles")
    tex_tiles = fetch("naip", args.tex, TEX_TILE_PX, NAIP_URL,
                      dict(format="png", bandIds="0,1,2"), "png")
    cols, rows = round(WIDTH_M / args.tex), round(HEIGHT_M / args.tex)
    texture = Image.new("RGB", (cols, rows))
    y = 0
    for row in tex_tiles:
        x = 0
        for p in row:
            tile = Image.open(p).convert("RGB")
            texture.paste(tile, (x, y))
            x += tile.width
        y += tile.height
    texture.save(os.path.join(WORK, "texture.jpg"), quality=93, subsampling=0)
    print(f"texture {texture.size}")

    marks = []
    for name, lon, lat in LANDMARKS:
        x, y = to_utm(lon, lat)
        col = int((x - X0) / args.cell)
        row = int((Y0 + HEIGHT_M - y) / args.cell)
        inside = 0 <= row < z.shape[0] and 0 <= col < z.shape[1]
        marks.append({"name": name, "x": round(x - X0, 1), "y": round(y - Y0, 1),
                      "elev_m": round(float(z[row, col]), 1) if inside else None})
    scene = {"crs": "EPSG:26912", "origin_utm": [X0, Y0],
             "width_m": WIDTH_M, "height_m": HEIGHT_M,
             "cell_m": args.cell, "texture_m": args.tex,
             "elev_min_m": float(z.min()), "elev_max_m": float(z.max()),
             "landmarks": marks}
    with open(os.path.join(WORK, "scene.json"), "w", encoding="utf-8") as fh:
        json.dump(scene, fh, indent=1)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 10), dpi=110)
    ext = (0, WIDTH_M / 1000, 0, HEIGHT_M / 1000)
    step = max(1, z.shape[1] // 2300)
    zs = z[::step, ::step]
    ax.imshow(hillshade(zs, args.cell * step), cmap="gray", extent=ext)
    ax.imshow(zs, cmap="terrain", alpha=0.35, extent=ext)
    for m in marks:
        ax.plot(m["x"] / 1000, m["y"] / 1000, "r^", ms=6)
        ax.annotate(f"{m['name']} {m['elev_m']:.0f} m" if m["elev_m"] else m["name"],
                    (m["x"] / 1000, m["y"] / 1000), xytext=(4, 4),
                    textcoords="offset points", fontsize=8, color="white",
                    bbox=dict(fc="black", ec="none", alpha=0.5, pad=1))
    ax.set_xlabel("km east of the frame's west edge")
    ax.set_ylabel("km north of the frame's south edge")
    ax.set_title("Santa Catalina Mountains frame (3DEP elevation)")
    fig.savefig(os.path.join(WORK, "preview.png"), bbox_inches="tight")
    print("wrote preview.png")


if __name__ == "__main__":
    main()
