"""Write the small files the web viewer at /catalinas-3d/ loads.

Reads catalinas-3d/work/ (dem.npy, texture_flat.jpg, scene.json) and writes
catalinas-3d/data/:

  height.png       elevation above the lowest point in steps of 0.1 m, as a
                   16-bit number packed into the red (high byte) and green
                   (low byte) channels; row 0 is the north edge
  texture_4k.jpg   imagery with the photo's sunlight removed, 4096 px wide
  texture_8k.jpg   the same, 8192 px wide (loaded only on request)
  meta.json        frame size, elevation range, grid size, summits

Run:  py tools/export_catalinas_web.py
      (after build_catalinas.py and deshade_catalinas.py)
"""
import json
import os

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "catalinas-3d", "work")
OUT = os.path.join(ROOT, "catalinas-3d", "data")
HEIGHT_COLS = 2048
STEP_M = 0.1    # elevation step; finer makes the file bigger, coarser shows as banding


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(WORK, "scene.json"), encoding="utf-8") as fh:
        scene = json.load(fh)
    z = np.load(os.path.join(WORK, "dem.npy"))
    rows, cols = z.shape
    h_rows = round(HEIGHT_COLS * rows / cols)
    zmin, zmax = float(z.min()), float(z.max())

    # Resample with area averaging (PIL works on 32-bit float images)
    small = np.asarray(Image.fromarray(z, mode="F").resize((HEIGHT_COLS, h_rows), Image.BOX))
    h16 = np.round((small - zmin) / STEP_M).clip(0, 65535).astype("uint16")
    packed = np.zeros((h_rows, HEIGHT_COLS, 3), dtype="uint8")
    packed[..., 0] = h16 >> 8
    packed[..., 1] = h16 & 255
    path = os.path.join(OUT, "height.png")
    Image.fromarray(packed).save(path, optimize=True)
    print(f"height.png {HEIGHT_COLS} x {h_rows}, {os.path.getsize(path) / 1e6:.1f} MB, "
          f"{scene['width_m'] / HEIGHT_COLS:.1f} m cells")

    tex = Image.open(os.path.join(WORK, "texture_flat.jpg"))
    for name, width, quality in (("texture_4k.jpg", 4096, 84), ("texture_8k.jpg", 8192, 80)):
        size = (width, round(width * tex.height / tex.width))
        path = os.path.join(OUT, name)
        tex.resize(size, Image.LANCZOS).save(path, quality=quality, progressive=True,
                                             optimize=True)
        print(f"{name} {size[0]} x {size[1]}, {os.path.getsize(path) / 1e6:.1f} MB")

    meta = {
        "width_m": scene["width_m"], "height_m": scene["height_m"],
        "elev_min_m": round(zmin, 1), "elev_max_m": round(zmax, 1),
        "height_cols": HEIGHT_COLS, "height_rows": h_rows, "height_step_m": STEP_M,
        "origin_utm_12n": scene["origin_utm"],
        "summits": [m for m in scene["landmarks"] if "approx" not in m["name"]],
    }
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    print("wrote meta.json")


if __name__ == "__main__":
    main()
