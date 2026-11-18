"""Check the modelled shoreline against what Landsat saw on real days.

For each test scene it reads the green and shortwave-infrared bands for the
lower lake straight from the public Landsat archive (Microsoft Planetary
Computer, no account needed), maps water where green is brighter than
shortwave infrared, and compares that with the terrain flooded to Reclamation's
elevation for the same day. This is the one check that does not depend on the
DEM: it tests the datum conversion and the terrain together.

Writes processed/landsat_check.json and one picture per scene,
processed/landsat_check_<date>.png (Landsat water in blue, the modelled
shoreline as a line).

    py -I tools/powell/10_check_landsat.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from scipy import ndimage

from common import (CELL, EPSG_DEM, FRAME_X0, FRAME_Y1, PROCESSED, USER_AGENT, dem_m_to_reclamation_ft,
                    reclamation_ft_to_dem_m)

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
# Lower lake: the dam, Wahweap, Warm Creek and Padre Bays (EPSG:6341 meters)
WINDOW = (448000, 4084000, 488000, 4112000)
# One day near full pool and one near the 2023 low
SCENES = ["LT05_L2SP_037034_19840704_02_T1", "LC08_L2SP_037034_20230411_02_T1"]


def signed(href):
    return requests.get(SIGN, params={"href": href}, headers=USER_AGENT, timeout=60).json()["href"]


def read_band(href, cols, rows, transform):
    with rasterio.open(signed(href)) as src, WarpedVRT(src, crs=f"EPSG:{EPSG_DEM}", transform=transform, width=cols,
                                                       height=rows, resampling=Resampling.bilinear) as vrt:
        return vrt.read(1).astype("float32")


def main():
    terrain = np.load(PROCESSED / "terrain_30m.npy")
    reservoir = np.load(PROCESSED / "reservoir_30m.npy")
    levels = pd.read_csv(PROCESSED / "levels_daily.csv", parse_dates=["date"]).set_index("date")["elevation_ft"]
    x0, y0, x1, y1 = WINDOW
    c0, c1 = int((x0 - FRAME_X0) // CELL), int((x1 - FRAME_X0) // CELL)
    r0, r1 = int((FRAME_Y1 - y1) // CELL), int((FRAME_Y1 - y0) // CELL)
    transform = from_origin(FRAME_X0 + c0 * CELL, FRAME_Y1 - r0 * CELL, CELL, CELL)
    rows, cols = r1 - r0, c1 - c0
    ground, lake = terrain[r0:r1, c0:c1], reservoir[r0:r1, c0:c1]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    results = []
    for scene_id in SCENES:
        item = requests.get(f"{STAC}/collections/landsat-c2-l2/items/{scene_id}", headers=USER_AGENT, timeout=60).json()
        if "assets" not in item:
            print(f"  {scene_id}: not in the archive, skipped")
            continue
        day = pd.Timestamp(item["properties"]["datetime"][:10])
        ft = float(levels[day])
        green = read_band(item["assets"]["green"]["href"], cols, rows, transform)
        swir = read_band(item["assets"]["swir16"]["href"], cols, rows, transform)
        seen = (green > 0) & (swir > 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            mndwi = (green - swir) / (green + swir)
        water = seen & (mndwi > 0) & lake                     # water inside the reservoir's possible extent
        model = seen & lake & (ground <= reclamation_ft_to_dem_m(ft))
        both, either = (water & model).sum(), (water | model).sum()
        km2 = CELL * CELL / 1e6
        # Areas are not a fair test: Landsat misses water in cliff shadow and in canyons
        # narrower than a pixel. The shoreline on gentle, open ground is. Read the terrain
        # height on both sides of Landsat's water edge there; the water level lies between.
        gy, gx = np.gradient(ground, CELL)
        gentle = np.degrees(np.arctan(np.hypot(gx, gy))) < 3.0
        gentle = ndimage.uniform_filter(gentle.astype("float32"), 5) > 0.99      # gentle all around, not one cell
        # Gaps in Landsat's water over flat lake bed (shadowed or silty water) make false
        # edges far below the surface, so only ground within 100 ft of the gauge reading
        # counts as shore. That is wide next to any datum error worth finding.
        near = np.abs(ground - reclamation_ft_to_dem_m(ft)) < 100 * 0.3048
        gentle &= near
        wet_edge = water & ~ndimage.binary_erosion(water) & gentle
        dry_edge = ndimage.binary_dilation(water) & ~water & seen & lake & gentle
        wet_ft = dem_m_to_reclamation_ft(float(np.median(ground[wet_edge])))
        dry_ft = dem_m_to_reclamation_ft(float(np.median(ground[dry_edge])))
        shore_ft = (wet_ft + dry_ft) / 2
        res = {"scene": scene_id, "date": f"{day:%Y-%m-%d}", "reclamation_ft": ft,
               "landsat_water_km2": round(float(water.sum() * km2), 1), "model_water_km2": round(float(model.sum() * km2), 1),
               "overlap_share": round(float(both / either), 3),
               "shoreline_cells_on_gentle_ground": int(wet_edge.sum() + dry_edge.sum()),
               "terrain_just_inside_landsat_shore_ft": round(wet_ft, 1),
               "terrain_just_outside_landsat_shore_ft": round(dry_ft, 1),
               "level_read_from_landsat_shore_ft": round(shore_ft, 1), "difference_ft": round(shore_ft - ft, 1)}
        results.append(res)
        print(" ", res)

        fig = plt.figure(figsize=(cols / 110, rows / 110), dpi=110)
        ax = fig.add_axes((0, 0, 1, 1))
        grey = np.clip(swir / np.nanpercentile(swir[seen], 99), 0, 1) if seen.any() else swir
        img = np.dstack([grey, grey, grey])
        img[water] = (0.16, 0.47, 0.84)
        ax.imshow(img)
        ax.contour(model.astype(float), levels=[0.5], colors="#eb6834", linewidths=0.6)
        ax.text(12, 26, f"{day:%Y-%m-%d}: Landsat water (blue), terrain flooded to {ft:,.2f} ft (orange line)",
                color="white", fontsize=10, bbox=dict(facecolor="black", alpha=0.6, lw=0))
        ax.set_axis_off()
        fig.savefig(PROCESSED / f"landsat_check_{day:%Y%m%d}.png")
        plt.close(fig)
    (PROCESSED / "landsat_check.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
