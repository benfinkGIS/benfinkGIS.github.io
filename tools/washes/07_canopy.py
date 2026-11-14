"""Step 2c: tree canopy over the whole study area, from the 2023 NAIP imagery.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/washes/07_canopy.py [--calibrate-only]

Project 1 mapped tree canopy from lidar in two neighborhoods and had it
checked by hand (tree canopy or not: 95% right). That map is the reference
here. A 1 m cell counts as canopy when it is green enough (NDVI), bright
enough in the near infrared to be sunlit foliage rather than shade, and rough
enough to be tree crowns rather than turf (spread of near-infrared brightness
in the 5 x 5 m around it). The three cut-offs are the ones that agree best
with Project 1's canopy across both neighborhoods; the script tries a grid of
them and reports the agreement of the winner.

Writes work/canopy/canopy_1m.tif (1 = canopy), canopy_share_10m.tif (share of
canopy within 10 m of each cell, in percent) and canopy.json.
"""
import json
import sys
import time

import arcpy
import numpy as np
from scipy import ndimage

from common import BBOX, EPSG, ROOT, WORK

OUT = WORK / "canopy"
NDVI_T = np.arange(0.02, 0.42, 0.02)
NIR_T = [0, 70, 90, 110, 130]
TEX_T = [0, 3, 5, 7, 9, 12]
SHARE_RADIUS_M = 10


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def features(img):
    """NDVI, near-infrared brightness and its 5 x 5 spread, from a 4-band tile."""
    red = img[0].astype("float32")
    nir = img[3].astype("float32")
    ndvi = (nir - red) / np.maximum(nir + red, 1)
    ndvi = ndimage.uniform_filter(ndvi, 3)
    mean = ndimage.uniform_filter(nir, 5)
    sq = ndimage.uniform_filter(nir * nir, 5)
    tex = np.sqrt(np.maximum(sq - mean * mean, 0))
    return ndvi, nir, tex


def rule(ndvi, nir, tex, cut):
    mask = (ndvi >= cut[0]) & (nir >= cut[1]) & (tex >= cut[2])
    # A cell stays canopy only if most of its 3 x 3 neighbours agree.
    return ndimage.uniform_filter(mask.astype("float32"), 3) >= 0.5


def read_box(folder, box):
    """Mosaic the NAIP tiles in a folder into one array over the box."""
    x0, y0, x1, y1 = box
    out = np.zeros((4, int(y1 - y0), int(x1 - x0)), "uint8")
    for path in sorted(folder.glob("naip_r*.tif")):
        e = arcpy.Raster(str(path)).extent
        a = arcpy.RasterToNumPyArray(str(path))
        r0 = int(round(y1 - e.YMax))
        c0 = int(round(e.XMin - x0))
        out[:, r0:r0 + a.shape[1], c0:c0 + a.shape[2]] = a
    return out


def calibrate():
    cfg = json.loads((ROOT / "tucson-canopy" / "sites.json").read_text(encoding="utf-8"))
    sites = []
    for s in cfg["sites"]:
        x0, y0, x1, y1 = s["bbox_utm12n"]
        b = cfg["buffer_m"]
        box = (x0 - b, y0 - b, x1 + b, y1 + b)
        img = read_box(WORK / "naip_cal" / s["id"], box)
        gdb = ROOT / "tucson-canopy" / "work" / s["id"] / f"{s['id']}.gdb"
        lc = arcpy.RasterToNumPyArray(str(gdb / "land_cover"), nodata_to_value=0)
        h, w = img.shape[1], img.shape[2]
        lc = lc[:h * 2, :w * 2]
        tree = (lc == 1).reshape(h, 2, w, 2).mean(axis=(1, 3)) >= 0.5
        major = np.zeros((h, w), "uint8")
        best = np.zeros((h, w), "float32")
        for cls in range(1, 7):
            share = (lc == cls).reshape(h, 2, w, 2).mean(axis=(1, 3))
            major[share > best] = cls
            best = np.maximum(best, share)
        known = lc.reshape(h, 2, w, 2).min(axis=(1, 3)) > 0
        sites.append(dict(id=s["id"], feats=features(img), tree=tree, major=major, known=known))

    best_cut, best_iou = None, -1
    for a in NDVI_T:
        for b in NIR_T:
            for c in TEX_T:
                tp = fp = fn = 0
                for s in sites:
                    m = rule(*s["feats"], (a, b, c)) & s["known"]
                    t = s["tree"] & s["known"]
                    tp += int((m & t).sum())
                    fp += int((m & ~t).sum())
                    fn += int((~m & t).sum())
                iou = tp / max(tp + fp + fn, 1)
                if iou > best_iou:
                    best_cut, best_iou = (float(a), float(b), float(c)), iou

    names = {1: "tree canopy", 2: "roof", 3: "pavement", 4: "low vegetation",
             5: "bare ground", 6: "water"}
    report = dict(cut=dict(ndvi=round(best_cut[0], 2), nir=best_cut[1], spread=best_cut[2]),
                  iou=round(best_iou, 3), sites={})
    for s in sites:
        m = rule(*s["feats"], best_cut)
        k = s["known"]
        t = s["tree"]
        tp, fp = int((m & t & k).sum()), int((m & ~t & k).sum())
        fn, tn = int((~m & t & k).sum()), int((~m & ~t & k).sum())
        report["sites"][s["id"]] = dict(
            agreement=round((tp + tn) / (tp + tn + fp + fn), 3),
            share_of_mapped_canopy_that_is_lidar_canopy=round(tp / max(tp + fp, 1), 3),
            share_of_lidar_canopy_found=round(tp / max(tp + fn, 1), 3),
            lidar_canopy_pct=round(100 * (t & k).sum() / k.sum(), 1),
            imagery_canopy_pct=round(100 * (m & k).sum() / k.sum(), 1),
            false_canopy_is_really={names[c]: int((m & ~t & k & (s["major"] == c)).sum())
                                    for c in range(2, 7)})
    return best_cut, report


def apply(cut):
    tiles_dir = OUT / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    sr = arcpy.SpatialReference(EPSG)
    done = []
    for path in sorted((WORK / "naip").glob("naip_r*.tif")):
        out = tiles_dir / path.name.replace("naip_", "canopy_")
        if not out.exists():
            r = arcpy.Raster(str(path))
            a = arcpy.RasterToNumPyArray(str(path))
            m = rule(*features(a), cut).astype("uint8")
            res = arcpy.NumPyArrayToRaster(m, arcpy.Point(r.extent.XMin, r.extent.YMin), 1, 1)
            arcpy.management.CopyRaster(res, str(out), pixel_type="8_BIT_UNSIGNED")
            arcpy.management.DefineProjection(str(out), sr)
        done.append(str(out))
    msg(len(done), "canopy tiles")
    arcpy.env.overwriteOutput = True
    arcpy.management.MosaicToNewRaster(done, str(OUT), "canopy_1m.tif", sr,
                                       "8_BIT_UNSIGNED", 1, 1, "FIRST", "FIRST")
    msg("canopy share within", SHARE_RADIUS_M, "m")
    arcpy.CheckOutExtension("Spatial")
    from arcpy.sa import FocalStatistics, Int, NbrCircle, Raster
    arcpy.env.extent = arcpy.Extent(*BBOX)
    arcpy.env.snapRaster = str(OUT / "canopy_1m.tif")
    arcpy.env.parallelProcessingFactor = "50%"
    share = FocalStatistics(Raster(str(OUT / "canopy_1m.tif")) * 100,
                            NbrCircle(SHARE_RADIUS_M, "CELL"), "MEAN", "DATA")
    arcpy.management.CopyRaster(Int(share + 0.5), str(OUT / "canopy_share_10m.tif"),
                                pixel_type="8_BIT_UNSIGNED")
    a = arcpy.RasterToNumPyArray(str(OUT / "canopy_1m.tif"), nodata_to_value=0)
    return round(100 * float(a.mean()), 2)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    msg("calibrating against Project 1")
    cut, report = calibrate()
    msg(json.dumps(report, indent=1))
    if "--calibrate-only" not in sys.argv:
        report["study_area_canopy_pct"] = apply(cut)
        msg("study area canopy", report["study_area_canopy_pct"], "%")
    (OUT / "canopy.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
