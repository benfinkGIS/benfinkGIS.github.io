"""Steps 6 to 8: place the trees, grow them to mature size, build the scenarios.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/10_scenarios.py [site_id ...]

Three scenarios, each containing the one before:
  1 Street trees        the public right-of-way only, as Dunbar Spring did
  2 Streets and homes   plus up to two trees on each home lot, and park edges
  3 Full build-out      every plantable spot; an upper bound, not a proposal

Placement
  Trunks go on plantable cells (step 09), tried on a 1 m lattice. Spots that
  collect the most roof and street runoff are tried first, so the trees that
  can be watered by a basin or curb cut go in before the ones that cannot.

  A species fits a spot if its mature crown stays clear of roofs and overhead
  lines, overlaps an existing crown by no more than a metre, and does not
  overlap another new crown. New trunks are at least 8 m apart, so gaps
  between crowns are left open and not packed with the smallest tree.
  Crowns may reach over pavement: shading it is the
  point. Among the species that fit, the one furthest below its target share
  of the mix (species.json) is planted, which keeps the palette mixed instead
  of filling every large gap with the largest tree. Desert willow, the one
  species rated above "very low" water use, goes only where runoff collects.

Canopy
  Each new tree becomes a dome at its published mature height and width. The
  domes are merged with the existing canopy for cover, and with the heights
  of today's crowns and roofs for the shade step that follows.

Writes to <site>.gdb: trees (points, one row per tree with its scenario),
canopy_s1..s3 (0/1) and height_s0..s3 (metres above ground of tree crowns
and roofs; s0 is today). Beside it:
scenarios.json and ql_scenario.jpg.
"""
import json
import sys

import arcpy
import numpy as np
from scipy import ndimage

from common import EPSG, PROJECT, site_dir, sites, work_bbox

CELL = 0.5
LATTICE = 2                 # try every second cell: a 1 m lattice
RUNOFF_FED_M2 = 50          # roof and pavement draining to the spot
SPACING_M = 8.0             # least distance between new trunks (about 26 ft)
CROWN_OVERLAP_M = 1.0       # allowed overlap with an existing crown
PER_LOT = 2                 # scenario 2: trees per home lot
SCENARIOS = {1: "Street trees", 2: "Streets and homes", 3: "Full build-out"}
PALETTE = json.loads((PROJECT / "species.json").read_text(encoding="utf-8"))
SPECIES = PALETTE["species"]
BASE_M = PALETTE["crown_base_m"]
R_MAX = max(s["radius_m"] for s in SPECIES)


def place(zone, runoff, room, lot, d_pave):
    """Greedy placement. Returns rows of (r, c, species index, scenario)."""
    F = np.full(zone.shape, np.inf, np.float32)     # room left by new crowns
    G = np.full(zone.shape, np.inf, np.float32)     # distance to nearest new trunk
    placed, counts, per_lot = [], np.zeros(len(SPECIES)), {}
    target = np.array([s["share"] for s in SPECIES])
    radius = np.array([s["radius_m"] for s in SPECIES])
    thirsty = np.array([s["needs_runoff"] for s in SPECIES])

    lat = np.zeros(zone.shape, bool)
    lat[::LATTICE, ::LATTICE] = True

    def run(mask, scenario, cap=None):
        rr, cc = np.nonzero(mask & lat)
        order = np.lexsort((d_pave[rr, cc], -runoff[rr, cc]))
        for r, c in zip(rr[order], cc[order]):
            if cap is not None and per_lot.get(int(lot[r, c]), 0) >= cap:
                continue
            if G[r, c] < SPACING_M:
                continue
            limit = min(room[r, c], F[r, c])
            ok = (radius <= limit) & (~thirsty | (runoff[r, c] >= RUNOFF_FED_M2))
            if not ok.any():
                continue
            share = counts / max(counts.sum(), 1)
            k = int(np.argmax(np.where(ok, target - share, -np.inf)))
            placed.append((int(r), int(c), k, scenario))
            counts[k] += 1
            if cap is not None:
                per_lot[int(lot[r, c])] = per_lot.get(int(lot[r, c]), 0) + 1
            w = int(np.ceil(max(radius[k] + R_MAX, SPACING_M) / CELL)) + 1
            r0, r1 = max(r - w, 0), min(r + w + 1, zone.shape[0])
            c0, c1 = max(c - w, 0), min(c + w + 1, zone.shape[1])
            yy, xx = np.ogrid[r0 - r:r1 - r, c0 - c:c1 - c]
            away = np.hypot(yy, xx) * CELL
            F[r0:r1, c0:c1] = np.minimum(F[r0:r1, c0:c1], away - radius[k])
            G[r0:r1, c0:c1] = np.minimum(G[r0:r1, c0:c1], away)

    run(zone == 1, 1)
    run(zone == 2, 2, cap=PER_LOT)
    run(zone == 3, 2)
    run(zone == 2, 3)
    return placed


def build(site):
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

    def put(arr, name):
        r = arcpy.NumPyArrayToRaster(arr, ll, CELL, CELL)
        arcpy.management.CopyRaster(r, f"{gdb}/{name}")
        arcpy.management.DefineProjection(f"{gdb}/{name}", sr)

    lc = grab(f"{gdb}/land_cover")
    zone = grab(f"{gdb}/plantable")
    runoff = grab(f"{gdb}/runoff_m2")
    chm = grab(f"{gdb}/chm")
    veg = grab(f"{gdb}/veg_height")
    overhead = grab(f"{gdb}/overhead") == 1
    lot = grab(str(tmp / "parcel.tif"))
    inside = grab(str(tmp / "inside.tif")) > 0
    tree, roof, pave = lc == 1, lc == 2, lc == 3

    def dist(mask):
        return (ndimage.distance_transform_edt(~mask) * CELL if mask.any()
                else np.full(mask.shape, 1e6))

    room = np.minimum(np.minimum(dist(roof), dist(tree) + CROWN_OVERLAP_M),
                      dist(overhead)).astype(np.float32)
    placed = place(zone, runoff, room, lot, dist(pave))

    pts = f"{gdb}/trees"
    if arcpy.Exists(pts):
        arcpy.management.Delete(pts)
    arcpy.management.CreateFeatureclass(gdb, "trees", "POINT", spatial_reference=sr)
    for name, kind, length in (("Species", "TEXT", 40), ("Latin", "TEXT", 40),
                               ("Scenario", "SHORT", None), ("Zone", "TEXT", 12),
                               ("Crown_m", "FLOAT", None), ("Height_m", "FLOAT", None),
                               ("Runoff_m2", "FLOAT", None), ("RunoffFed", "SHORT", None),
                               ("InBoundary", "SHORT", None)):
        arcpy.management.AddField(pts, name, kind, field_length=length)
    zone_name = {1: "street", 2: "yard", 3: "park edge"}
    canopy = {k: tree.copy() for k in SCENARIOS}
    # Height of things that cast real shade: tree crowns and roofs. Wires,
    # poles, cars and walls are left out; a wire is not a wall of shadow
    solid = np.where(tree, veg, np.where(roof, chm, 0)).astype(np.float32)
    put(solid, "height_s0")
    height = {k: solid.copy() for k in SCENARIOS}
    tally = {k: {} for k in SCENARIOS}
    fed = {k: 0 for k in SCENARIOS}
    with arcpy.da.InsertCursor(pts, ["SHAPE@XY", "Species", "Latin", "Scenario", "Zone",
                                     "Crown_m", "Height_m", "Runoff_m2", "RunoffFed",
                                     "InBoundary"]) as cur:
        for r, c, k, scen in placed:
            sp = SPECIES[k]
            R, H = sp["radius_m"], sp["height_m"]
            is_fed = int(runoff[r, c] >= RUNOFF_FED_M2)
            cur.insertRow(((x0 + (c + 0.5) * CELL, y1 - (r + 0.5) * CELL),
                           sp["common"], sp["latin"], scen, zone_name[int(zone[r, c])],
                           2 * R, H, float(runoff[r, c]), is_fed, int(inside[r, c])))
            w = int(np.ceil(R / CELL))
            r0, r1 = max(r - w, 0), min(r + w + 1, rows)
            c0, c1 = max(c - w, 0), min(c + w + 1, cols)
            yy, xx = np.ogrid[r0 - r:r1 - r, c0 - c:c1 - c]
            dd = np.hypot(yy, xx) * CELL
            crown = dd <= R
            dome = np.where(crown, BASE_M + (H - BASE_M) * np.sqrt(
                np.clip(1 - (dd / R) ** 2, 0, 1)), 0).astype(np.float32)
            for s in SCENARIOS:
                if s >= scen:
                    canopy[s][r0:r1, c0:c1] |= crown
                    height[s][r0:r1, c0:c1] = np.maximum(height[s][r0:r1, c0:c1], dome)
                    if inside[r, c]:
                        tally[s][sp["common"]] = tally[s].get(sp["common"], 0) + 1
                        fed[s] += is_fed
    for s in SCENARIOS:
        put(canopy[s].astype(np.uint8), f"canopy_s{s}")
        put(height[s], f"height_s{s}")

    n = inside.sum()
    pave_in = pave & inside
    summary = dict(
        site=site["id"],
        existing=dict(canopy_pct=round(float(tree[inside].mean() * 100), 1)),
        scenarios={})
    for s, name in SCENARIOS.items():
        trees = sum(tally[s].values())
        summary["scenarios"][name] = dict(
            trees=trees, by_species=dict(sorted(tally[s].items())),
            runoff_fed=fed[s],
            runoff_fed_share=round(fed[s] / trees, 2) if trees else None,
            canopy_pct=round(float(canopy[s][inside].mean() * 100), 1),
            canopy_added_ha=round(float((canopy[s] & ~tree)[inside].sum() * CELL * CELL / 1e4), 2),
            # mapped pavement is what shows from above today, so this is the
            # share of now-exposed pavement that the new crowns would cover
            exposed_pavement_covered_pct=round(float(canopy[s][pave_in].mean() * 100), 1),
            trees_per_ha=round(trees / (n * CELL * CELL / 1e4), 1))
    summary["rules"] = dict(runoff_fed_m2=RUNOFF_FED_M2, per_lot=PER_LOT,
                            spacing_m=SPACING_M,
                            crown_overlap_m=CROWN_OVERLAP_M, lattice_m=LATTICE * CELL,
                            crown_base_m=BASE_M)
    (d / "scenarios.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1), flush=True)

    # Quick look: scenario 2 over the muted photo, new crowns by species
    from PIL import Image
    rgb = np.moveaxis(arcpy.RasterToNumPyArray(f"{gdb}/naip_2023", nodata_to_value=0)[:3], 0, -1)
    base = np.asarray(Image.fromarray(rgb).resize((cols, rows), Image.LANCZOS)).astype(np.float32)
    base = (base * 0.4 + base.mean(-1, keepdims=True) * 0.6) * 0.85
    base[tree] = base[tree] * 0.45 + np.array([30, 110, 40]) * 0.55
    for r, c, k, scen in placed:
        if scen > 2:
            continue
        R = SPECIES[k]["radius_m"]
        w = int(np.ceil(R / CELL))
        r0, r1 = max(r - w, 0), min(r + w + 1, rows)
        c0, c1 = max(c - w, 0), min(c + w + 1, cols)
        yy, xx = np.ogrid[r0 - r:r1 - r, c0 - c:c1 - c]
        crown = np.hypot(yy, xx) * CELL <= R
        base[r0:r1, c0:c1][crown] = (base[r0:r1, c0:c1][crown] * 0.25 +
                                     np.array(SPECIES[k]["colour"]) * 0.75)
    Image.fromarray(base.clip(0, 255).astype(np.uint8)).save(str(d / "ql_scenario.jpg"),
                                                             quality=90)


def main():
    arcpy.CheckOutExtension("Spatial")
    for s in sites(sys.argv[1:]):
        build(s)


if __name__ == "__main__":
    main()
