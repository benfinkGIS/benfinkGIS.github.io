"""Step 9a: shade on a summer afternoon, today and under each scenario.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/11_shade.py [--date 2026-07-15] [--time 16:00] [site_id ...]

For the chosen date and clock time (Mountain Standard Time; Arizona keeps no
daylight time) it works out where the sun is, then casts shadows from the
height model: a ground cell is in shade if anything between it and the sun
stands above the line of sight. The same is done on each scenario's height
model, which is the lidar surface with the proposed crowns added.

What is measured, inside each neighborhood boundary:
  street edge   the 2 m band just outside street pavement, both sides. There
                is no sidewalk layer for these neighborhoods, and on many
                Tucson streets this band is where people walk. Its area
                divided by its width gives a length of street edge
  pavement      mapped pavement, which is the pavement exposed to the sky today
  open ground   everything that is not a roof

Only tree crowns and roofs cast shade here (height_s0..s3 from step 10).
Wires, poles, cars and walls are left out.

Check against the photo (--check-photo): the 2023 NAIP image has shadows of
its own, but its time of day is not published. The script casts shadows from
today's surface for every quarter hour of the flight date and reports the
time at which they best match where bare ground is dark in the photo,
and how well they match. A good match at a plausible flying time is evidence
the shadow caster and the height model are right.

Limits: every tree and building is treated as solid from the ground to its
top. Real desert trees cast filtered shade and let low sun in under the crown,
so this is the footprint of shade, not its quality. New trees are at mature
size.

Writes shade_s0 (today) and shade_s1..s3 to <site>.gdb (1 = shaded), and
shade.json and ql_shade.jpg beside it.
"""
import argparse
import json
import math
import datetime as dt

import arcpy
import numpy as np
from scipy import ndimage

from common import EPSG, site_dir, sites, work_bbox

CELL = 0.5
MST = dt.timezone(dt.timedelta(hours=-7))
EDGE_M = 2.0
SCENARIOS = {0: "Today", 1: "Street trees", 2: "Streets and homes", 3: "Full build-out"}


def sun_position(when, lat, lon):
    """Solar azimuth (degrees clockwise from north) and elevation, by the
    NOAA Solar Calculator's equations. Good to a fraction of a degree."""
    utc = when.astimezone(dt.timezone.utc)
    jd = utc.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545.0) / 36525
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t)) +
         math.sin(2 * mr) * (0.019993 - 0.000101 * t) + math.sin(3 * mr) * 0.000289)
    omega = 125.04 - 1934.136 * t
    lam = l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam)))
    y = math.tan(math.radians(eps / 2)) ** 2
    l0r = math.radians(l0)
    eqt = 4 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr) +
        4 * e * y * math.sin(mr) * math.cos(2 * l0r) -
        0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    minutes = utc.hour * 60 + utc.minute + utc.second / 60
    hour_angle = math.radians(((minutes + eqt + 4 * lon) % 1440) / 4 - 180)
    latr = math.radians(lat)
    cos_zen = (math.sin(latr) * math.sin(decl) +
               math.cos(latr) * math.cos(decl) * math.cos(hour_angle))
    zen = math.acos(max(-1, min(1, cos_zen)))
    az = math.degrees(math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(latr) - math.tan(decl) * math.cos(latr))) + 180
    return az % 360, 90 - math.degrees(zen)


def cast(top, ground, az, el):
    """True where the ground is in shadow. `top` and `ground` are elevations."""
    dx, dy = math.sin(math.radians(az)), -math.cos(math.radians(az))   # toward the sun; rows run south
    rise = math.tan(math.radians(el)) * CELL
    reach = float(np.nanmax(top - ground)) / math.tan(math.radians(el)) / CELL
    shade = np.zeros(ground.shape, bool)
    rows, cols = ground.shape
    for k in range(1, int(reach) + 2):
        oc, orow = int(round(k * dx)), int(round(k * dy))
        if abs(oc) >= cols or abs(orow) >= rows:
            break
        # compare each cell with the surface k steps toward the sun
        dst_r = slice(max(0, -orow), rows - max(0, orow))
        src_r = slice(max(0, orow), rows - max(0, -orow))
        dst_c = slice(max(0, -oc), cols - max(0, oc))
        src_c = slice(max(0, oc), cols - max(0, -oc))
        shade[dst_r, dst_c] |= top[src_r, src_c] - k * rise > ground[dst_r, dst_c]
    return shade


def build(site, when):
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    tmp = d / "tmp"
    sr = arcpy.SpatialReference(EPSG)
    x0, y0, x1, y1 = work_bbox(site)
    ll = arcpy.Point(x0, y0)
    rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
    arcpy.env.overwriteOutput = True

    def grab(path, nodata=0):
        return arcpy.RasterToNumPyArray(path, ll, cols, rows, nodata_to_value=nodata)

    lon, lat = site["center_lonlat"]
    az, el = sun_position(when, lat, lon)
    dtm = grab(f"{gdb}/dtm").astype(np.float32)
    lc = grab(f"{gdb}/land_cover")
    inside = grab(str(tmp / "inside.tif")) > 0
    parcel = grab(str(tmp / "parcel.tif")) > 0
    roof, pave = lc == 2, lc == 3
    street_pave = pave & ~parcel
    edge = (~parcel & ~pave & ~roof &
            (ndimage.distance_transform_edt(~street_pave) * CELL <= EDGE_M))
    targets = {"street edge": edge & inside, "pavement": pave & inside,
               "open ground": ~roof & inside}
    edge_km = float(targets["street edge"].sum()) * CELL * CELL / EDGE_M / 1000

    out = dict(site=site["id"], when=when.isoformat(), sun_azimuth=round(az, 1),
               sun_elevation=round(el, 1), street_edge_km=round(edge_km, 2),
               scenarios={})
    shades = {}
    for s, name in SCENARIOS.items():
        h = grab(f"{gdb}/height_s{s}").astype(np.float32)
        shade = cast(dtm + h, dtm, az, el)
        # a cell under a crown or other cover is shaded by what stands on it
        shade |= h > 2.0
        shades[s] = shade
        r = arcpy.NumPyArrayToRaster(shade.astype(np.uint8), ll, CELL, CELL)
        arcpy.management.CopyRaster(r, f"{gdb}/shade_s{s}")
        arcpy.management.DefineProjection(f"{gdb}/shade_s{s}", sr)
        row = {k: round(float(shade[m].mean() * 100), 1) for k, m in targets.items()}
        row["street_edge_shaded_km"] = round(edge_km * row["street edge"] / 100, 2)
        out["scenarios"][name] = row
    (d / "shade.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1), flush=True)

    # Quick look: today and scenario 2 side by side over the muted photo
    from PIL import Image
    rgb = np.moveaxis(arcpy.RasterToNumPyArray(f"{gdb}/naip_2023", nodata_to_value=0)[:3], 0, -1)
    base = np.asarray(Image.fromarray(rgb).resize((cols, rows), Image.LANCZOS)).astype(np.float32)
    base = base * 0.35 + base.mean(-1, keepdims=True) * 0.65 + 25
    panes = []
    for s in (0, 2):
        img = base.copy()
        img[shades[s]] = img[shades[s]] * 0.35 + np.array([20, 40, 90]) * 0.65
        panes.append(img.clip(0, 255).astype(np.uint8))
    gap = np.full((rows, 20, 3), 255, np.uint8)
    Image.fromarray(np.concatenate([panes[0], gap, panes[1]], 1)).save(
        str(d / "ql_shade.jpg"), quality=88)


def check_photo(site, date):
    """Find the time of day at which modelled shadows best match the photo."""
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    x0, y0, x1, y1 = work_bbox(site)
    ll = arcpy.Point(x0, y0)
    rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
    grab = lambda path: arcpy.RasterToNumPyArray(path, ll, cols, rows, nodata_to_value=0)
    dtm = grab(f"{gdb}/dtm").astype(np.float32)
    h = grab(f"{gdb}/height_s0").astype(np.float32)
    lc = grab(f"{gdb}/land_cover")
    bright = grab(str(d / "tmp" / "naip05.tif"))[:3].astype(np.float32).mean(0)
    # judge on bare ground only, away from crowns that lean in the photo.
    # Pavement is left out: asphalt is dark in sun or shade, which hides the
    # shadows and swamps the comparison
    ground = (lc == 5) & (ndimage.distance_transform_edt(lc != 1) * CELL > 1.5)
    lon, lat = site["center_lonlat"]
    best = None
    for minute in range(9 * 60, 15 * 60 + 1, 15):
        when = dt.datetime.fromisoformat(date).replace(
            hour=minute // 60, minute=minute % 60, tzinfo=MST)
        az, el = sun_position(when, lat, lon)
        shade = cast(dtm + h, dtm, az, el)[ground]
        if shade.mean() in (0, 1):
            continue
        r = float(np.corrcoef(shade, -bright[ground])[0, 1])
        if best is None or r > best["correlation"]:
            lit, dark = np.median(bright[ground][~shade]), np.median(bright[ground][shade])
            cut = (lit + dark) / 2
            best = dict(time=when.strftime("%H:%M"), sun_azimuth=round(az, 1),
                        sun_elevation=round(el, 1), correlation=round(r, 3),
                        median_brightness_lit=round(float(lit)),
                        median_brightness_shaded=round(float(dark)),
                        agreement=round(float(((bright[ground] < cut) == shade).mean()), 3),
                        shaded_share=round(float(shade.mean()), 3))
    best["site"], best["photo_date"] = site["id"], date
    (d / "shade_photo_check.json").write_text(json.dumps(best, indent=1))
    print(json.dumps(best, indent=1), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-07-15")
    ap.add_argument("--time", default="16:00")
    ap.add_argument("--check-photo", metavar="FLIGHT_DATE",
                    help="match modelled shadows to the photo, e.g. 2023-10-18")
    ap.add_argument("site", nargs="*")
    args = ap.parse_args()
    if args.check_photo:
        arcpy.CheckOutExtension("Spatial")
        for s in sites(args.site):
            check_photo(s, args.check_photo)
        return
    when = dt.datetime.fromisoformat(f"{args.date}T{args.time}").replace(tzinfo=MST)
    arcpy.CheckOutExtension("Spatial")
    for s in sites(args.site):
        build(s, when)


if __name__ == "__main__":
    main()
