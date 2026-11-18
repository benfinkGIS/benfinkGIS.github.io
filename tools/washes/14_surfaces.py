"""Step 8b: ground layers on a 10 m grid, then a resistance and a source
surface for each species.

Ground layers (cached in work/connectivity/layers_10m.npz; --layers rebuilds):
  imperv   percent of the ground that is built on (NLCD 2021, 30 m)
  canopy   share under tree canopy (the imagery rule from 07_canopy.py)
  green    share of green ground that is not tree canopy
  turf     share of smooth, strongly green ground: lawn, ballfield, fairway
  road     highest road class in the cell (0 none .. 7 interstate)
  wash     largest wash in the cell (0 none, 1 small, 2 medium, 3 large)
  rip      county riparian class (0 none, 1 D .. 5 H)
  water    1 where there is standing water (NHD ponds plus water seen in the imagery)
  xing     best wash crossing within reach of a road cell (0 none, 1 open span,
           2 culvert, 3 at-grade); inventoried bridges over water count as open spans

Water seen in the imagery is kept only on ground flatter than 5 degrees and
in patches of 300 m2 or more, which drops cliff shadow and swimming pools.

Species surfaces are worked out from those by the numbers in
tucson-washes/resistance.json and written as GeoTIFFs for Omniscape.

Run:  propy tools/washes/14_surfaces.py [--layers] [--look]
"""
import json
import sys
import time

import arcpy
import numpy as np
from scipy import ndimage

from common import BBOX, CONTEXT, EPSG, PROJECT, WORK

OUT = WORK / "connectivity"
CELL = 10
X0, Y0, X1, Y1 = BBOX
NX, NY = int((X1 - X0) / CELL), int((Y1 - Y0) / CELL)
SR = arcpy.SpatialReference(EPSG)
GDB = str(WORK / "washes.gdb")

ROAD_RANK = {"Minor local road": 1, "Railroad": 2, "Frontage road": 3, "Major local road": 4,
             "State route": 5, "State route ramp": 5, "Interstate ramp": 6, "Interstate highway": 7}
ROAD_NAME = {1: "minor", 2: "railroad", 3: "frontage", 4: "major", 5: "state_route",
             6: "interstate_ramp", 7: "interstate"}
HALF_WIDTH_M = {"Interstate highway": 12, "Interstate ramp": 6, "Frontage road": 7,
                "State route": 12, "State route ramp": 6, "Major local road": 10,
                "Minor local road": 6, "Railroad": 5}
WASH_SIZE_HA = (20, 1000)          # small under 20 ha, medium to 1,000 ha, large above
NDVI_GREEN, NDVI_TURF, TEX_SMOOTH = 0.16, 0.30, 7
NDWI_WATER, WATER_SHARE, WATER_MIN_CELLS = 0.20, 0.4, 3
WATER_MAX_SLOPE_DEG = 5     # cliff shadow in the Catalinas reads as water in the imagery
NHD_WET = (39004, 43600, 43612, 43618)   # perennial ponds, reservoirs, treatment ponds
XING_REACH_M = 25
XING_CODE = {"open span": 1, "culvert": 2, "at-grade": 3}
# National Bridge Inventory records that are bridges over water (not culverts):
# service under the bridge is a waterway, alone or with a road or railway.
NBI_OVER_WATER = ("5", "6", "7", "8", "9")
NBI_CULVERT = "19"
NBI_REACH_M = 30            # added to half the bridge's length
RIP_LETTER = {1: "D", 2: "C", 3: "B", 4: "A", 5: "H"}


def msg(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def block(a, f, how="mean"):
    v = a.reshape(a.shape[0] // f, f, a.shape[1] // f, f)
    return v.mean(axis=(1, 3), dtype="float32") if how == "mean" else v.max(axis=(1, 3))


def grid_env(cell):
    arcpy.env.overwriteOutput = True
    arcpy.env.extent = arcpy.Extent(X0, Y0, X1, Y1)
    arcpy.env.outputCoordinateSystem = SR
    arcpy.env.cellSize = cell
    snap = OUT / f"snap_{cell}m.tif"
    if not snap.exists():
        r = arcpy.NumPyArrayToRaster(np.zeros((4, 4), "uint8"), arcpy.Point(X0, Y0), cell, cell)
        arcpy.management.CopyRaster(r, str(snap))
        arcpy.management.DefineProjection(str(snap), SR)
    arcpy.env.snapRaster = str(snap)


def read(path, cell):
    return arcpy.RasterToNumPyArray(str(path), arcpy.Point(X0, Y0), int((X1 - X0) / cell),
                                    int((Y1 - Y0) / cell), nodata_to_value=0)


def imagery(canopy1):
    """Green ground, turf and water shares from the 1 m imagery, tile by tile."""
    green = np.zeros((NY, NX), "float32")
    turf = np.zeros((NY, NX), "float32")
    wet = np.zeros((NY, NX), "float32")
    for path in sorted((WORK / "naip").glob("naip_r*.tif")):
        e = arcpy.Raster(str(path)).extent
        a = arcpy.RasterToNumPyArray(str(path)).astype("float32")
        r0, c0 = int(round(Y1 - e.YMax)), int(round(e.XMin - X0))
        h, w = a.shape[1] // CELL * CELL, a.shape[2] // CELL * CELL
        red, grn, nir = a[0, :h, :w], a[1, :h, :w], a[3, :h, :w]
        ndvi = ndimage.uniform_filter((nir - red) / np.maximum(nir + red, 1), 3)
        mean = ndimage.uniform_filter(nir, 5)
        tex = np.sqrt(np.maximum(ndimage.uniform_filter(nir * nir, 5) - mean * mean, 0))
        tree = canopy1[r0:r0 + h, c0:c0 + w] > 0
        g = (ndvi >= NDVI_GREEN) & ~tree
        t = (ndvi >= NDVI_TURF) & (tex < TEX_SMOOTH) & ~tree
        ndwi = ndimage.uniform_filter((grn - nir) / np.maximum(grn + nir, 1), 3)
        sl = (slice(r0 // CELL, (r0 + h) // CELL), slice(c0 // CELL, (c0 + w) // CELL))
        green[sl] = block(g, CELL)
        turf[sl] = block(t, CELL)
        wet[sl] = block(ndwi >= NDWI_WATER, CELL)
    return green, turf, wet


def roads():
    grid_env(2)
    arcpy.management.CopyFeatures(f"{GDB}/streets", "memory/st")
    arcpy.management.CopyFeatures(f"{GDB}/railroads", "memory/rr")
    for fc, src in (("memory/st", "ROADCAT_DS"), ("memory/rr", None)):
        arcpy.management.AddField(fc, "rank", "SHORT")
        arcpy.management.AddField(fc, "half", "SHORT")
        with arcpy.da.UpdateCursor(fc, ["rank", "half"] + ([src] if src else [])) as cur:
            for row in cur:
                cls = row[2] if src else "Railroad"
                row[0], row[1] = ROAD_RANK.get(cls, 1), HALF_WIDTH_M.get(cls, 6)
                cur.updateRow(row)
    arcpy.management.Merge(["memory/st", "memory/rr"], "memory/ways")
    arcpy.analysis.PairwiseBuffer("memory/ways", "memory/ways_buf", "half", "LIST", "rank")
    tif = str(OUT / "road_rank_2m.tif")
    arcpy.conversion.PolygonToRaster("memory/ways_buf", "rank", tif, "CELL_CENTER", "rank", 2)
    a = read(tif, 2)
    a[a > 7] = 0
    return block(a, CELL // 2, "max").astype("uint8")


def washes():
    grid_env(CELL)
    lyr = arcpy.management.MakeFeatureLayer(f"{GDB}/reaches", "wash_lyr", "kind = 'wash'")
    arcpy.management.CopyFeatures(lyr, "memory/wash")
    arcpy.management.AddField("memory/wash", "size", "SHORT")
    with arcpy.da.UpdateCursor("memory/wash", ["drain_ha", "size"]) as cur:
        for ha, _ in cur:
            cur.updateRow([ha, 1 + (ha >= WASH_SIZE_HA[0]) + (ha >= WASH_SIZE_HA[1])])
    tif = str(OUT / "wash_size_10m.tif")
    arcpy.conversion.PolylineToRaster("memory/wash", "size", tif, "MAXIMUM_LENGTH", "size", CELL)
    a = read(tif, CELL)
    a[a > 3] = 0
    return a.astype("uint8")


def impervious():
    grid_env(CELL)
    tif = str(OUT / "imperv_10m.tif")
    arcpy.management.ProjectRaster(str(WORK / "landcover" / "nlcd_2021_impervious.tif"), tif, SR,
                                   "BILINEAR", CELL)
    a = read(tif, CELL).astype("float32")
    a[a > 100] = 0
    return a


def flat_ground():
    dem = block(read(WORK / "dem" / "dem_1m.tif", 1), CELL)
    dy, dx = np.gradient(dem, CELL)
    return np.degrees(np.arctan(np.hypot(dx, dy))) <= WATER_MAX_SLOPE_DEG


def water(wet_share):
    grid_env(CELL)
    gj = json.loads((CONTEXT / "nhd_waterbody.geojson").read_text())
    polys = []
    for f in gj["features"]:
        if f["properties"]["fcode"] in NHD_WET:
            g = f["geometry"]
            polys += [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    arcpy.management.CreateFeatureclass("memory", "ponds", "POLYGON", spatial_reference=SR)
    arcpy.management.AddField("memory/ponds", "one", "SHORT")
    with arcpy.da.InsertCursor("memory/ponds", ["SHAPE@", "one"]) as cur:
        for rings in polys:      # the coordinates are already in the study projection
            parts = arcpy.Array([arcpy.Array([arcpy.Point(x, y) for x, y, *_ in ring])
                                 for ring in rings])
            cur.insertRow([arcpy.Polygon(parts, SR), 1])
    tif = str(OUT / "ponds_10m.tif")
    arcpy.conversion.PolygonToRaster("memory/ponds", "one", tif, "MAXIMUM_AREA", None, CELL)
    nhd = read(tif, CELL) == 1
    seen = (wet_share >= WATER_SHARE) & flat_ground()
    lab, n = ndimage.label(seen, structure=np.ones((3, 3)))
    size = ndimage.sum(seen, lab, np.arange(n + 1))
    seen &= size[lab] >= WATER_MIN_CELLS
    return (nhd | seen).astype("uint8"), int(nhd.sum()), int(seen.sum())


def crossings(road):
    """Road cells within reach of a typed wash crossing; the most open type wins."""
    out = np.zeros((NY, NX), "uint8")

    def mark(x, y, reach, code):
        k = int(np.ceil(reach / CELL))
        c, r = int((x - X0) / CELL), int((Y1 - y) / CELL)
        for rr in range(max(r - k, 0), min(r + k + 1, NY)):
            for cc in range(max(c - k, 0), min(c + k + 1, NX)):
                cx, cy = X0 + (cc + 0.5) * CELL, Y1 - (rr + 0.5) * CELL
                if road[rr, cc] and (cx - x) ** 2 + (cy - y) ** 2 <= reach ** 2:
                    out[rr, cc] = code

    rows = list(arcpy.da.SearchCursor(f"{GDB}/crossings", ["SHAPE@XY", "rule_type"]))
    for (x, y), kind in sorted(rows, key=lambda r: -XING_CODE[r[1]]):
        mark(x, y, XING_REACH_M, XING_CODE[kind])
    # Inventoried bridges over water are open spans whatever the lidar rule made of
    # them, across the full width of the road: the rule works one centerline at a
    # time and missed the interstate's river bridges.
    bridges = 0
    for f in json.loads((CONTEXT / "bridges_nbi.geojson").read_text())["features"]:
        p = f["properties"]
        if str(p.get("SERVICE_UND_042B")) in NBI_OVER_WATER and str(p.get("STRUCTURE_TYPE_043B")) != NBI_CULVERT:
            x, y = f["geometry"]["coordinates"][:2]
            if X0 <= x < X1 and Y0 <= y < Y1:
                mark(x, y, float(p.get("STRUCTURE_LEN_MT_049") or 0) / 2 + NBI_REACH_M, 1)
                bridges += 1
    return out, bridges


def layers():
    arcpy.CheckOutExtension("Spatial")
    msg("canopy")
    canopy1 = read(WORK / "canopy" / "canopy_1m.tif", 1)
    L = dict(canopy=block(canopy1 > 0, CELL))
    msg("imagery: green ground, turf, water")
    L["green"], L["turf"], wet = imagery(canopy1)
    del canopy1
    msg("impervious")
    L["imperv"] = impervious()
    msg("roads")
    L["road"] = roads()
    msg("washes")
    L["wash"] = washes()
    msg("riparian")
    rip = read(WORK / "dem" / "rip_code.tif", 1)
    rip[rip > 5] = 0
    L["rip"] = block(rip, CELL, "max").astype("uint8")
    del rip
    msg("water")
    L["water"], nhd_cells, seen_cells = water(wet)
    msg("crossings")
    L["xing"], nbi_bridges = crossings(L["road"])
    np.savez_compressed(OUT / "layers_10m.npz", **L)
    report = dict(cell_m=CELL, shape=[NY, NX],
                  mean={k: round(float(L[k].mean()), 4) for k in ("canopy", "green", "turf", "imperv")},
                  road_cells={ROAD_NAME[i]: int((L["road"] == i).sum()) for i in ROAD_NAME},
                  wash_cells={n: int((L["wash"] == i).sum()) for i, n in ((1, "small"), (2, "medium"), (3, "large"))},
                  riparian_cells=int((L["rip"] > 0).sum()),
                  water_cells=dict(nhd=nhd_cells, imagery=seen_cells, either=int(L["water"].sum())),
                  crossing_cells={n: int((L["xing"] == i).sum()) for n, i in XING_CODE.items()},
                  inventoried_bridges_over_water=nbi_bridges)
    (OUT / "layers.json").write_text(json.dumps(report, indent=2))
    msg(json.dumps(report))
    return L


def near_mean(a, meters):
    """Mean within a circle of the given radius."""
    k = int(round(meters / CELL))
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    disc = (yy * yy + xx * xx <= k * k).astype("float32")
    return ndimage.convolve(a.astype("float32"), disc / disc.sum(), mode="nearest")


def road_cost(L, table):
    cost = np.zeros((NY, NX), "float32")
    for rank, name in ROAD_NAME.items():
        cost[L["road"] == rank] = table.get(name, 0)
    return cost


def bobcat(L, p, culverts="as typed"):
    """Resistance for a cat on foot. `culverts` sets how typed culverts are
    treated: "as typed", "closed" (no help) or "open" (as good as a bridge)."""
    built = 1 + (p["built"]["max"] - 1) * (L["imperv"] / 100) ** p["built"]["power"]
    cover = np.minimum(L["canopy"] + L["green"], 1)
    r = np.maximum(built * (1 - p["cover_relief"] * cover), 1)
    for code, letter in RIP_LETTER.items():
        r = np.where(L["rip"] == code, np.minimum(r, p["riparian"][letter]), r)
    for code, name in ((1, "small"), (2, "medium"), (3, "large")):
        r = np.where(L["wash"] == code, np.minimum(r, p["wash"][name]), r)
    way = road_cost(L, p["road"])
    r = np.maximum(r, way)
    x = p["crossing"]
    pipe = np.maximum(x["culvert_min"], x["culvert_share_of_road"] * way)
    kind = L["xing"]
    if culverts == "open":
        kind = np.where(kind == 2, 1, kind)
    elif culverts == "closed":
        kind = np.where(kind == 2, 3, kind)
    r = np.where((kind == 1) & (way > 0), np.minimum(r, x["open_span"]), r)
    r = np.where((kind == 2) & (way > 0), np.minimum(r, pipe), r)
    s = p["source"]
    src = np.clip(1 - near_mean(L["imperv"], s["built_within_m"]) / s["zero_at_pct"], 0, 1)
    return r.astype("float32"), src.astype("float32")


def flycatcher(L, p):
    perch = np.minimum((L["canopy"] + L["turf"]) / p["cover_full_at"], 1)
    r = 1 + p["bare_cost"] * (1 - perch) + p["built_cost"] * L["imperv"] / 100
    dist = ndimage.distance_transform_edt(L["water"] == 0) * CELL
    r = np.where(dist <= p["water_within_m"], np.maximum(r * p["water_relief"], 1), r)
    s = p["source"]
    turf = near_mean(L["turf"], s["within_m"])
    tree = near_mean(L["canopy"], s["within_m"])
    src = np.minimum(turf / s["turf_full_at"], 1) * np.minimum(tree / s["tree_full_at"], 1)
    src = np.where(dist <= s["water_within_m"], src, src * s["away_from_water"])
    src = np.where(src < s["floor"], 0, src)
    return r.astype("float32"), src.astype("float32")


def queen(L, p):
    plants = np.minimum((L["canopy"] + L["green"]) / p["cover_full_at"], 1)
    r = 1 + p["bare_cost"] * (1 - plants) + p["built_cost"] * L["imperv"] / 100
    r = np.where((L["wash"] > 0) | (L["rip"] > 0), np.minimum(r, p["wash_or_riparian"]), r)
    s = p["source"]
    cover = near_mean(L["canopy"] + L["green"], s["within_m"])
    built = near_mean(L["imperv"], s["within_m"])
    src = np.minimum(cover / s["cover_full_at"], 1) * (1 - s["built_penalty"] * built / 100)
    by_wash = near_mean((L["wash"] > 0) | (L["rip"] > 0), s["wash_within_m"]) > 0
    src = np.where(by_wash, np.maximum(src, s["by_wash_floor"]), src)
    src = np.where(src < s["floor"], 0, src)
    return r.astype("float32"), src.astype("float32")


def write(a, name):
    grid_env(CELL)
    r = arcpy.NumPyArrayToRaster(a, arcpy.Point(X0, Y0), CELL, CELL)
    path = str(OUT / name)
    arcpy.management.CopyRaster(r, path, pixel_type="32_BIT_FLOAT")
    arcpy.management.DefineProjection(path, SR)


def look(L, made):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for name, a in list(L.items()) + list(made.items()):
        fig = plt.figure(figsize=(12.5, 10.5), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        log = name.endswith("resistance")
        ax.imshow(np.log10(a) if log else a, cmap="viridis", interpolation="nearest")
        ax.set_axis_off()
        ax.text(20, 60, name, color="w", fontsize=16, backgroundcolor="k")
        fig.savefig(OUT / f"look_{name}.jpg", pil_kwargs=dict(quality=80))
        plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "layers_10m.npz"
    if "--layers" in sys.argv or not cache.exists():
        L = layers()
    else:
        L = dict(np.load(cache))
    P = json.loads((PROJECT / "resistance.json").read_text(encoding="utf-8"))
    made, stats = {}, {}
    r, s = bobcat(L, P["bobcat"])
    made["bobcat_resistance"], made["bobcat_source"] = r, s
    made["bobcat_closed_resistance"] = bobcat(L, P["bobcat"], "closed")[0]
    made["bobcat_open_resistance"] = bobcat(L, P["bobcat"], "open")[0]
    made["flycatcher_resistance"], made["flycatcher_source"] = flycatcher(L, P["flycatcher"])
    made["queen_resistance"], made["queen_source"] = queen(L, P["queen"])
    for name, a in made.items():
        write(a, f"{name}.tif")
        q = np.percentile(a, [5, 25, 50, 75, 95])
        stats[name] = dict(min=float(a.min()), max=float(a.max()), mean=round(float(a.mean()), 3),
                           pct_5_25_50_75_95=[round(float(v), 2) for v in q],
                           share_zero=round(float((a == 0).mean()), 4))
        msg(name, stats[name])
    (OUT / "surfaces.json").write_text(json.dumps(stats, indent=2))
    np.savez_compressed(OUT / "surfaces.npz", **made)      # for 17_validate.py
    if "--look" in sys.argv:
        look(L, made)


if __name__ == "__main__":
    main()
