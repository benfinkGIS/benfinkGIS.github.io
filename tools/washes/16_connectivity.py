"""Step 8d: read the Omniscape runs back, summarise them, and write what the
page and the validation need.

For each run:
  work/connectivity/arrays/<run>.npz   current, flow potential, normalized current
For each species (the main runs):
  reaches.flow_<species>               mean normalized current along each wash reach:
                                       how many times the movement that uniform
                                       ground would carry
  tucson-washes/data/funnel_<species>.png normalized current by class, in Web Mercator

The page shows normalized current, not current itself. Current piles up in
the large blocks of open desert at the corners of the box, where there are
most sources, and says little about a wash crossing the city; normalized
current shows where the ground gathers movement into a strip.
work/connectivity/summary.json         figures for the page and the README

Run:  propy tools/washes/16_connectivity.py
"""
import json
import time

import arcpy
import numpy as np
from PIL import Image
from scipy import ndimage

from common import BBOX, EPSG, PROJECT, SPECIES, WORK

OUT = WORK / "connectivity"
WEB = PROJECT / "data"
GDB = str(WORK / "washes.gdb")
CELL = 10
X0, Y0, X1, Y1 = BBOX
NX, NY = int((X1 - X0) / CELL), int((Y1 - Y0) / CELL)
SR = arcpy.SpatialReference(EPSG)
MAIN = [s["id"] for s in SPECIES]
EXTRA_RUNS = ["bobcat_closed", "bobcat_open"]
# Map classes of normalized current: nothing drawn below 1.3 (impeded and diffuse).
MAP_BREAKS = [1.3, 1.7, 2.5, 4.0]
MAP_RGBA = [(0, 0, 0, 0), (140, 41, 129, 150), (222, 73, 104, 185), (254, 159, 109, 215),
            (252, 253, 191, 240)]
# Normalized current (current / flow potential). Breaks attributed to Cameron et al. 2022
# (doi 10.1111/csp2.12698), read in a secondary source.
FUNNEL_BREAKS = [0.7, 1.3, 1.7]
FUNNEL_NAMES = ["impeded", "diffuse", "intensified", "channelled"]
NEAR_WASH_M = 30


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def read_run(name):
    folder = OUT / f"run_{name}"
    out = {}
    for key, file in (("current", "cum_currmap.tif"), ("potential", "flow_potential.tif"),
                      ("normalized", "normalized_cum_currmap.tif")):
        a = arcpy.RasterToNumPyArray(str(folder / file), arcpy.Point(X0, Y0), NX, NY,
                                     nodata_to_value=0).astype("float32")
        out[key] = a
    (OUT / "arrays").mkdir(exist_ok=True)
    np.savez_compressed(OUT / "arrays" / f"{name}.npz", **out)
    return out


def classes(a, breaks):
    return np.digitize(a, breaks).astype("uint8")


def overlay(cls, rgba, name):
    """Write a class grid as a transparent PNG in Web Mercator; return its corners."""
    arcpy.env.overwriteOutput = True
    src = str(OUT / f"cls_{name}.tif")
    r = arcpy.NumPyArrayToRaster(cls, arcpy.Point(X0, Y0), CELL, CELL)
    arcpy.management.CopyRaster(r, src, pixel_type="8_BIT_UNSIGNED")
    arcpy.management.DefineProjection(src, SR)
    merc = str(OUT / f"cls_{name}_3857.tif")
    arcpy.env.extent = arcpy.env.snapRaster = None
    arcpy.management.ProjectRaster(src, merc, arcpy.SpatialReference(3857), "NEAREST")
    m = arcpy.Raster(merc)
    a = arcpy.RasterToNumPyArray(m, nodata_to_value=0)
    lut = np.zeros((256, 4), "uint8")
    lut[:len(rgba)] = rgba          # one colour per class, class 0 first
    Image.fromarray(lut[a], "RGBA").save(WEB / f"{name}.png", optimize=True)
    e = m.extent
    wgs = arcpy.SpatialReference(4326)
    pts = [arcpy.PointGeometry(arcpy.Point(x, y), arcpy.SpatialReference(3857)).projectAs(wgs).firstPoint
           for x, y in ((e.XMin, e.YMax), (e.XMax, e.YMax), (e.XMax, e.YMin), (e.XMin, e.YMin))]
    return [[round(p.X, 6), round(p.Y, 6)] for p in pts]


def reach_grid():
    """Wash reaches as 10 m cells holding the reach's OBJECTID; the larger wash wins a cell."""
    arcpy.env.overwriteOutput = True
    arcpy.env.extent = arcpy.Extent(X0, Y0, X1, Y1)
    arcpy.env.snapRaster = str(OUT / "snap_10m.tif")
    arcpy.management.CreateFeatureclass("memory", "wash16", "POLYLINE", spatial_reference=SR)
    arcpy.management.AddField("memory/wash16", "rid", "LONG")
    arcpy.management.AddField("memory/wash16", "drain_ha", "DOUBLE")
    with arcpy.da.SearchCursor(f"{GDB}/reaches", ["OID@", "SHAPE@", "drain_ha"], "kind = 'wash'") as src,             arcpy.da.InsertCursor("memory/wash16", ["rid", "SHAPE@", "drain_ha"]) as dst:
        for row in src:
            dst.insertRow(row)
    tif = str(OUT / "reach_id_10m.tif")
    arcpy.conversion.PolylineToRaster("memory/wash16", "rid", tif, "MAXIMUM_LENGTH", "drain_ha", CELL)
    g = arcpy.RasterToNumPyArray(tif, arcpy.Point(X0, Y0), NX, NY, nodata_to_value=0)
    return g


def rank_pct(values):
    """Percentile rank (0 to 100) of each value among the values."""
    order = np.argsort(np.argsort(values))
    return 100.0 * order / max(len(values) - 1, 1)


def main():
    L = dict(np.load(OUT / "layers_10m.npz"))
    near_wash = ndimage.distance_transform_edt(L["wash"] == 0) * CELL <= NEAR_WASH_M
    summary = dict(built=time.strftime("%Y-%m-%d"), cell_m=CELL, near_wash_m=NEAR_WASH_M,
                   map_breaks=MAP_BREAKS, funnel_breaks=FUNNEL_BREAKS,
                   funnel_names=FUNNEL_NAMES, near_wash_share_of_area=round(float(near_wash.mean()), 4),
                   species={}, overlays={})
    runs_log = json.loads((OUT / "runs.json").read_text())
    grid = reach_grid()
    cells = grid > 0
    flow = {}
    arrays = {}
    for name in MAIN + EXTRA_RUNS:
        if not (OUT / f"run_{name}" / "normalized_cum_currmap.tif").exists():
            continue        # not run yet
        arrays[name] = read_run(name)
        msg("read", name)
    done = [sp for sp in MAIN if sp in arrays]
    for sp in done:
        a = arrays[sp]
        cur, norm = a["current"], a["normalized"]
        top = cur >= np.percentile(cur, 90)
        fun = classes(norm, FUNNEL_BREAKS)
        info = dict(
            run=runs_log.get(sp),
            top_tenth_near_wash=round(float(near_wash[top].mean()), 4),
            top_tenth_in_riparian=round(float((L["rip"][top] > 0).mean()), 4),
            riparian_share_of_area=round(float((L["rip"] > 0).mean()), 4),
            funnel_share_of_area={n: round(float((fun == i).mean()), 4) for i, n in enumerate(FUNNEL_NAMES)},
            channelled_near_wash=round(float(near_wash[fun == 3].mean()), 4) if (fun == 3).any() else None,
            funnelled_near_wash=round(float(near_wash[fun >= 2].mean()), 4) if (fun >= 2).any() else None,
            wash_cells_funnelled=round(float((fun[L["wash"] > 0] >= 2).mean()), 4),
            normalized_on_wash_cells=round(float(np.median(norm[L["wash"] > 0])), 3),
            current_on_wash_cells_vs_all=round(float(cur[L["wash"] > 0].mean() / cur.mean()), 3))
        if sp == "bobcat":
            # Where the modelled movement gets across the interstate.
            hw = L["road"] == 7
            info["interstate"] = dict(
                cells=int(hw.sum()), open_span_cells=int((hw & (L["xing"] == 1)).sum()),
                share_of_current_at_open_spans=round(float(cur[hw & (L["xing"] == 1)].sum() / cur[hw].sum()), 4),
                mean_current_vs_area=round(float(cur[hw & (L["xing"] != 1)].mean() / cur.mean()), 4),
                open_span_current_vs_area=round(float(cur[hw & (L["xing"] == 1)].mean() / cur.mean()), 3))
        summary["species"][sp] = info
        summary["overlays"][f"funnel_{sp}"] = overlay(classes(norm, MAP_BREAKS), MAP_RGBA, f"funnel_{sp}")
        # mean normalized current along each wash reach
        rid = np.unique(grid[cells])
        flow[sp] = {int(r): float(v) for r, v in zip(rid, ndimage.mean(norm, grid, rid))}
        msg(sp, json.dumps(info))
    # how much the bobcat result depends on what the typed culverts really are
    if all(k in arrays for k in ("bobcat", "bobcat_closed", "bobcat_open")):
        lo, hi = arrays["bobcat_closed"]["normalized"], arrays["bobcat_open"]["normalized"]
        base = arrays["bobcat"]["normalized"]
        change = (hi - lo) / np.maximum((hi + lo) / 2, 1e-9)
        rid = np.unique(grid[cells])
        r_lo, r_hi = rank_pct(ndimage.mean(lo, grid, rid)), rank_pct(ndimage.mean(hi, grid, rid))
        r_base = rank_pct(ndimage.mean(base, grid, rid))
        top = r_base >= 90
        summary["bobcat_culverts"] = dict(
            cells_changing_over_10pct=round(float((np.abs(change) > 0.10).mean()), 4),
            cells_changing_over_25pct=round(float((np.abs(change) > 0.25).mean()), 4),
            wash_cells_changing_over_25pct=round(float((np.abs(change[L["wash"] > 0]) > 0.25).mean()), 4),
            reach_rank_correlation_closed_open=round(float(np.corrcoef(r_lo, r_hi)[0, 1]), 4),
            top_tenth_reaches_kept_closed=round(float((r_lo[top] >= 90).mean()), 4),
            top_tenth_reaches_kept_open=round(float((r_hi[top] >= 90).mean()), 4))
        msg("culverts", json.dumps(summary["bobcat_culverts"]))
    # write the ranks onto the reaches
    have = [f.name for f in arcpy.ListFields(f"{GDB}/reaches")]
    for sp in done:
        if f"flow_{sp}" not in have:
            arcpy.management.AddField(f"{GDB}/reaches", f"flow_{sp}", "FLOAT")
    with arcpy.da.UpdateCursor(f"{GDB}/reaches", ["OID@"] + [f"flow_{sp}" for sp in done]) as cur:
        for row in cur:
            for i, sp in enumerate(done):
                v = flow[sp].get(row[0])
                row[i + 1] = None if v is None else round(v, 2)
            cur.updateRow(row)
    summary["reaches_ranked"] = len(flow[done[0]])
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    msg("done; run 17_validate.py, then 08_reaches.py --export")


if __name__ == "__main__":
    main()
