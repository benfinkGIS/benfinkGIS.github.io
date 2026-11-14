"""Step 10f: write the 3D blocks in a form the browser viewer can load.

Runs in the system Python, after 21_blender_export.py:

  py tools/canopy/24_web3d_export.py

Reads the same block arrays the Blender render uses (work/<site>/blender/)
and writes tucson-canopy/data/3d/:

  <site>_heights.png   one image, three numbers per 0.5 m cell:
                       red and green hold the ground-plus-roof height above
                       the block's lowest point in centimetres (red x 256 +
                       green); blue holds today's canopy height above the
                       ground in tenths of a metre (0 = no canopy)
  <site>_photo.jpg     the 2023 aerial photo over the block
  <site>.json          block size, where it is, and every proposed tree
                       (metres east and north of the block centre, ground
                       height, species, scenario), plus each species' mature
                       size and colour

Images are used as number containers because browsers decode them fast and
they compress well. They must stay PNG: a JPEG would smear the heights.
"""
import json

import numpy as np
from PIL import Image

from common import PROJECT, site_dir, sites

OUT = PROJECT / "data" / "3d"
# foliage and bloom colours, as in the Blender render
COLOURS = {"Velvet mesquite": "#96b281", "Blue palo verde": "#e3d55b",
           "Foothill palo verde": "#c2d26f", "Desert willow": "#e6a6c3"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for s in sites():
        src = site_dir(s) / "blender"
        scene = json.loads((src / "scene.json").read_text())
        ground = np.load(src / "ground.npy") - scene["ground_min"]
        roof = np.load(src / "roof.npy")
        canopy = np.load(src / "canopy.npy")
        cm = np.clip(np.round((ground + roof) * 100), 0, 65535).astype(np.uint16)
        rgb = np.dstack([(cm >> 8).astype(np.uint8), (cm & 255).astype(np.uint8),
                         np.clip(np.round(canopy * 10), 0, 255).astype(np.uint8)])
        Image.fromarray(rgb, "RGB").save(OUT / f"{s['id']}_heights.png", optimize=True)
        photo = Image.open(src / "texture.png").convert("RGB").resize((1600, 1600), Image.LANCZOS)
        photo.save(OUT / f"{s['id']}_photo.jpg", quality=84, optimize=True, progressive=True)

        half = scene["size_m"] / 2
        species = []
        for i, sp in enumerate(scene["species"]):
            mine = [t for t in scene["trees"] if t[3] == i]
            species.append(dict(name=sp["name"], colour=COLOURS[sp["name"]],
                                radius=mine[0][4] if mine else 3.0,
                                height=mine[0][5] if mine else 6.0))
        doc = dict(
            id=s["id"], name=s["name"], size_m=scene["size_m"], cell_m=scene["cell_m"],
            cells=int(cm.shape[0]), lonlat=s["center_lonlat"],
            crown_base_m=scene["crown_base_m"], species=species,
            # east, north (metres from the block centre), ground height, species, scenario
            trees=[[round(t[0] - half, 1), round(t[1] - half, 1),
                    round(t[2] - scene["ground_min"], 1), t[3], t[6]] for t in scene["trees"]])
        (OUT / f"{s['id']}.json").write_text(json.dumps(doc, separators=(",", ":")))
        print(s["id"], {p.name: f"{p.stat().st_size // 1024} KB"
                        for p in sorted(OUT.glob(s["id"] + "*"))})


if __name__ == "__main__":
    main()
