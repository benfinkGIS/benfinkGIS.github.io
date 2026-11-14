"""Step 9c (part 1): summer land surface temperature from Landsat, via Google Earth Engine.

Runs in the system Python (pip install earthengine-api), after a one-time
sign-in with ee_signin.py:

  py tools/canopy/13_surface_temperature.py [--years 2021 2022 2023] [site_id ...]

For each site it asks Earth Engine for every Landsat 8 and 9 scene (Collection
2, Level 2, Tier 1) from June to August of the chosen years, drops pixels that
the scene's own quality band flags as cloud, cloud shadow or cirrus, converts
the thermal band to degrees Celsius, and takes the median over the scenes.
The result is downloaded on Landsat's own 30 m grid, so nothing is resampled.

What this is and is not:
  * surface temperature, the temperature of roofs, pavement, soil and leaves,
    not of the air people feel
  * late morning: Landsat passes Tucson at about 11 a.m. local time, well
    before the afternoon peak
  * coarse: the thermal sensor sees 100 m, delivered on a 30 m grid, so a
    pixel blends everything around it

Writes work/<site>/lst/lst_summer.tif (degrees C), lst_count.tif (clear
scenes per pixel) and lst.json (scene list, dates, pass time).
"""
import argparse
import json

import ee
import requests

from common import EPSG, WORK, site_dir, sites, work_bbox

PIXEL = 30
PAD_M = 300          # context around the work area, for the block averages
BAD_BITS = (1, 2, 3, 4)      # dilated cloud, cirrus, cloud, cloud shadow


def clear_celsius(img):
    qa = img.select("QA_PIXEL")
    mask = ee.Image(1)
    for bit in BAD_BITS:
        mask = mask.And(qa.bitwiseAnd(1 << bit).eq(0))
    st = img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15)
    return (st.updateMask(mask).updateMask(img.select("ST_B10").gt(0))
            .rename("lst").copyProperties(img, ["system:time_start", "SPACECRAFT_ID"]))


def fetch(image, name, grid, out):
    url = image.getDownloadURL(dict(
        name=name, format="GEO_TIFF", crs=f"EPSG:{EPSG}",
        crs_transform=[PIXEL, 0, grid["x0"], 0, -PIXEL, grid["y1"]],
        dimensions=[grid["cols"], grid["rows"]]))
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    out.write_bytes(r.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2021, 2022, 2023])
    ap.add_argument("site", nargs="*")
    args = ap.parse_args()
    project = (WORK / "ee_project.txt").read_text().strip()
    ee.Initialize(project=project)

    for s in sites(args.site):
        x0, y0, x1, y1 = work_bbox(s)
        # Landsat's grid in this UTM zone has cell edges at 15 m past each 30 m
        snap = lambda v, up: ((v - 15) // PIXEL + (1 if up else 0)) * PIXEL + 15
        grid = dict(x0=snap(x0 - PAD_M, False), y1=snap(y1 + PAD_M, True))
        grid["cols"] = int((snap(x1 + PAD_M, True) - grid["x0"]) / PIXEL)
        grid["rows"] = int((grid["y1"] - snap(y0 - PAD_M, False)) / PIXEL)
        region = ee.Geometry.Rectangle(
            [grid["x0"], grid["y1"] - grid["rows"] * PIXEL,
             grid["x0"] + grid["cols"] * PIXEL, grid["y1"]],
            proj=f"EPSG:{EPSG}", geodesic=False)

        col = None
        for sat in ("LC08", "LC09"):
            for year in args.years:
                c = (ee.ImageCollection(f"LANDSAT/{sat}/C02/T1_L2")
                     .filterBounds(region)
                     .filterDate(f"{year}-06-01", f"{year}-09-01"))
                col = c if col is None else col.merge(c)
        scenes = col.aggregate_array("system:index").getInfo()
        times = col.aggregate_array("system:time_start").getInfo()
        lst = col.map(clear_celsius)
        out = site_dir(s) / "lst"
        out.mkdir(exist_ok=True)
        fetch(lst.median().toFloat(), "lst_summer", grid, out / "lst_summer.tif")
        fetch(lst.count().toInt16(), "lst_count", grid, out / "lst_count.tif")

        import datetime as dt
        local = [dt.datetime.fromtimestamp(t / 1000, dt.timezone(dt.timedelta(hours=-7)))
                 for t in times]
        info = dict(
            site=s["id"], source="Landsat 8 and 9, Collection 2 Level 2, band ST_B10, "
                                 "via Google Earth Engine",
            months="June to August", years=args.years, scenes=len(scenes),
            first=min(local).strftime("%Y-%m-%d") if local else None,
            last=max(local).strftime("%Y-%m-%d") if local else None,
            typical_pass_time_mst=sorted(l.strftime("%H:%M") for l in local)[len(local) // 2]
            if local else None,
            grid=grid, pixel_m=PIXEL, scene_ids=scenes)
        (out / "lst.json").write_text(json.dumps(info, indent=1))
        print(s["id"], len(scenes), "scenes,", info["first"], "to", info["last"],
              "| pass about", info["typical_pass_time_mst"], "MST", flush=True)


if __name__ == "__main__":
    main()
