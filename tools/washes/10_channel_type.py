"""Step 5: what each channel bed is made of, from the 2023 imagery.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/washes/10_channel_type.py

Looks at the 3 m strip along every reach in the 1 m NAIP imagery and counts
the cells that look like concrete: gray (little difference between red,
green and blue), bright, and not green. A reach is typed

  concrete   when at least CONCRETE_SHARE of the strip looks like concrete
  earthen    otherwise: sand, soil, rock or vegetation

Tree canopy over a channel hides the bed, so cells under mapped canopy are
left out, and a reach with under SEEN_MIN of its strip in view is typed
"hidden".

This is a first pass for the hand check in step 6, and a weak one: the
washes off the Catalinas run on pale granite sand, which is as gray and as
bright as concrete, so the color rule calls stretches of Pima, Finger Rock
and Sutherland washes concrete. It also cannot see bank protection (soil
cement, riprap, walls) beside an earthen bed. Three more measures are
therefore stored for each reach, for a rule to be fitted to the hand labels:

  img_texture    how much brightness varies from one meter to the next
  bed_rough_cm   how far the lidar ground along the channel line departs
                 from the 3 x 3 m around it (a poured floor is flat)
  straightness   straight-line distance between the ends over the length

Adds bed_rule, concrete_share, seen_share and those three to the reaches and
writes work/channel_type.json.
"""
import json
import time
from collections import Counter

import arcpy
import numpy as np
from scipy import ndimage

from common import BBOX, WORK

GRAY_MAX = 0.10          # (max - min) / max of red, green, blue
BRIGHT_MIN = 115         # mean of red, green, blue, out of 255
NDVI_MAX = 0.08
CONCRETE_SHARE = 0.5
SEEN_MIN = 0.3


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    gdb = str(WORK / "washes.gdb")
    msg("reach ids as a grid")
    links = arcpy.RasterToNumPyArray(str(WORK / "dem" / "stream_link.tif"), nodata_to_value=0)
    top = int(links.max()) + 1
    strip = np.zeros(top)
    seen = np.zeros(top)
    conc = np.zeros(top)
    tex_sum = np.zeros(top)
    line_n = np.zeros(top)
    rough_sum = np.zeros(top)
    msg("lidar ground")
    dem = arcpy.RasterToNumPyArray(str(WORK / "dem" / "dem_1m.tif"), nodata_to_value=np.nan)

    msg("imagery tiles")
    for path in sorted((WORK / "naip").glob("naip_r*.tif")):
        e = arcpy.Raster(str(path)).extent
        a = arcpy.RasterToNumPyArray(str(path)).astype("float32")
        can = arcpy.RasterToNumPyArray(str(WORK / "canopy" / "tiles" / path.name.replace("naip_", "canopy_")))
        r0, c0 = int(round(BBOX[3] - e.YMax)), int(round(e.XMin - BBOX[0]))
        ids = ndimage.maximum_filter(links[r0:r0 + a.shape[1], c0:c0 + a.shape[2]], 3)
        on = ids > 0
        if not on.any():
            continue
        rgb = a[:3]
        hi, lo = rgb.max(axis=0), rgb.min(axis=0)
        gray = (hi - lo) / np.maximum(hi, 1)
        bright = rgb.mean(axis=0)
        ndvi = (a[3] - a[0]) / np.maximum(a[3] + a[0], 1)
        view = on & (can == 0)
        like = view & (gray <= GRAY_MAX) & (bright >= BRIGHT_MIN) & (ndvi <= NDVI_MAX)
        strip += np.bincount(ids[on], minlength=top)
        seen += np.bincount(ids[view], minlength=top)
        conc += np.bincount(ids[like], minlength=top)
        mean = ndimage.uniform_filter(bright, 3)
        tex = np.sqrt(np.maximum(ndimage.uniform_filter(bright * bright, 3) - mean * mean, 0))
        tex_sum += np.bincount(ids[view], weights=tex[view], minlength=top)
        z = dem[r0:r0 + a.shape[1], c0:c0 + a.shape[2]]
        line = links[r0:r0 + a.shape[1], c0:c0 + a.shape[2]]
        dev = np.abs(z - ndimage.uniform_filter(np.nan_to_num(z, nan=0.0), 3))
        ok = (line > 0) & np.isfinite(dev) & (dev < 2)
        line_n += np.bincount(line[ok], minlength=top)
        rough_sum += np.bincount(line[ok], weights=dev[ok], minlength=top)

    msg("typing reaches")
    for name, kind in (("bed_rule", "TEXT"), ("concrete_share", "FLOAT"), ("seen_share", "FLOAT"),
                       ("img_texture", "FLOAT"), ("bed_rough_cm", "FLOAT"), ("straightness", "FLOAT")):
        if name not in [f.name for f in arcpy.ListFields(f"{gdb}/reaches")]:
            arcpy.management.AddField(f"{gdb}/reaches", name, kind, field_length=10 if kind == "TEXT" else None)
    km = Counter()
    by_name = {}
    spread = {"concrete": [], "earthen": []}
    with arcpy.da.UpdateCursor(f"{gdb}/reaches", ["grid_code", "kind", "bed_rule", "concrete_share",
                                                  "seen_share", "SHAPE@LENGTH", "name", "img_texture",
                                                  "bed_rough_cm", "straightness", "SHAPE@"]) as cur:
        for row in cur:
            g = row[0]
            row[7] = round(float(tex_sum[g] / max(seen[g], 1)), 2)
            row[8] = round(float(100 * rough_sum[g] / max(line_n[g], 1)), 2)
            a0, a1 = row[10].firstPoint, row[10].lastPoint
            row[9] = round(float(np.hypot(a1.X - a0.X, a1.Y - a0.Y) / max(row[5], 1)), 3)
            n = max(strip[g], 1)
            row[4] = round(float(seen[g] / n), 3)
            row[3] = round(float(conc[g] / max(seen[g], 1)), 3)
            if row[4] < SEEN_MIN:
                row[2] = "hidden"
            elif row[3] >= CONCRETE_SHARE:
                row[2] = "concrete"
            else:
                row[2] = "earthen"
            cur.updateRow(row)
            if row[1] == "wash":
                if row[2] in spread:
                    spread[row[2]].append((row[7], row[8], row[9]))
                km[row[2]] += row[5] / 1000
                if row[6]:
                    w = by_name.setdefault(row[6], Counter())
                    w[row[2]] += row[5] / 1000
    quart = {k: {n: [round(float(q), 2) for q in np.percentile([r[i] for r in v], [25, 50, 75])]
                 for i, n in enumerate(("img_texture", "bed_rough_cm", "straightness"))}
             for k, v in spread.items() if v}
    stats = dict(
        quartiles_by_first_pass=quart,
        wash_km_by_bed={k: round(v, 1) for k, v in km.items()},
        named_washes_most_concrete=sorted(
            ({"name": n, "km": round(sum(c.values()), 1),
              "concrete_pct": round(100 * c["concrete"] / sum(c.values()))}
             for n, c in by_name.items() if sum(c.values()) >= 1),
            key=lambda d: -d["concrete_pct"])[:20],
        settings=dict(grey_max=GRAY_MAX, bright_min=BRIGHT_MIN, ndvi_max=NDVI_MAX,
                      concrete_share=CONCRETE_SHARE, seen_min=SEEN_MIN))
    (WORK / "channel_type.json").write_text(json.dumps(stats, indent=2))
    msg(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
