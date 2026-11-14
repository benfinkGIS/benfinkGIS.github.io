"""Step 9e: afternoon surface temperature from ECOSTRESS, and the canopy fit redone on it.

Runs in the system Python, after 23_heat_citywide.py and a one-time
earthdata_signin.py (needs earthaccess, rasterio and scipy):

  py tools/canopy/25_ecostress.py [--years 2021 2022 2023 2024 2025]

Landsat passes Tucson at about 11 a.m. ECOSTRESS, NASA's thermal sensor on
the space station, sees 70 m and passes at varying hours, so it can show the
surface in mid-afternoon, when heat matters most to people.

What it does
  1. Finds every tiled ECOSTRESS land surface temperature scene (product
     ECO_L2T_LSTE, version 002) for June to August of the chosen years that
     was taken between 1 and 6 p.m. Mountain Standard Time. The city straddles
     two tiles, 12SWA and 12SVA, so both are used. Where NASA has processed
     a scene twice, the later processing is kept.
  2. Downloads each scene's temperature and cloud files (cached in
     work/ecostress/).
  3. Drops cloud and everything within 700 m of it, averages each scene onto
     the 90 m blocks of step 23, and keeps scenes that are still at least
     60% clear over the built-up city.
  4. Checks where each scene sits. ECOSTRESS scenes can be placed several
     hundred metres off. The fine detail of each scene (what is left after
     taking away the 1.9 km average around each block) is slid against the
     same detail in the Landsat map, and the scene is moved to where the two
     agree best. Scenes whose detail does not agree with Landsat anywhere
     (leftover cloud, cloud shadow, ground wet from a storm) are dropped.
  5. Turns each scene into a difference from its own citywide median.
     Scenes are taken on different days at different hours, so the absolute
     temperatures cannot be averaged, but the pattern across the city can.
     The median difference across scenes is the afternoon map.
  6. Fits that map to tree canopy, pavement and elevation exactly as step 23
     does for Landsat: same blocks, same canopy layer, same calibration.

The sensor looks up to about 28 degrees off straight down, so in some scenes
it sees more wall and less roof; that adds scatter.

Writes work/heat_ecostress.json, work/ecostress_blocks.npz and
work/ecostress_check.jpg.
"""
import argparse
import datetime as dt
import json
import os
import sys

for extra in (r"%TEMP%\finkgeo_pydeps_ea", r"%TEMP%\finkgeo_pydeps"):
    path = os.path.expandvars(extra)
    if os.path.isdir(path):
        sys.path.insert(0, path)

import earthaccess
import numpy as np
import rasterio
from affine import Affine
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from scipy import ndimage

from common import EPSG, WORK

TILES = ("12SWA", "12SVA")       # first one wins where they overlap
HOURS = (13, 18)                 # local time, inclusive start, exclusive end
CLOUD_GROW = 10                  # 70 m cells to step back from cloud
MIN_CLEAR = 0.60
MIN_DETAIL_R = 0.25              # fine-detail agreement with Landsat a scene needs
MIN_SCENES = 8                   # clear looks a block needs to be used
BLOCK = 90
DETAIL_CELLS = 21                # 1.9 km window for "fine detail"
SEARCH = 12                      # blocks each way when sliding a scene (1,080 m)
LOCAL_CELLS, BOOT_CELLS = 20, 30
MST = dt.timezone(dt.timedelta(hours=-7))
SCEN = ["Street trees", "Streets and homes", "Full build-out"]


def fit(y, X):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta, 1 - (y - X @ beta).var() / y.var()


def demean(v, groups):
    return v - (np.bincount(groups, weights=v) / np.bincount(groups))[groups]


def detail(a):
    """What is left of a block grid after taking away the local average."""
    ok = np.isfinite(a)
    total = ndimage.uniform_filter(np.where(ok, a, 0.0), DETAIL_CELLS, mode="constant")
    share = ndimage.uniform_filter(ok.astype(float), DETAIL_CELLS, mode="constant")
    return np.where(ok & (share > 0.3), a - total / np.maximum(share, 1e-6), np.nan)


def standardise(a):
    return np.nan_to_num((a - np.nanmean(a)) / np.nanstd(a))


def best_shift(ref_z, scene_z):
    """Slide the scene over the reference; return (rows down, columns right, agreement)."""
    rows, cols = ref_z.shape
    score = np.full((2 * SEARCH + 1, 2 * SEARCH + 1), -1.0)
    for dy in range(-SEARCH, SEARCH + 1):
        for dx in range(-SEARCH, SEARCH + 1):
            a = ref_z[max(dy, 0):rows + min(dy, 0), max(dx, 0):cols + min(dx, 0)]
            b = scene_z[max(-dy, 0):rows + min(-dy, 0), max(-dx, 0):cols + min(-dx, 0)]
            n = np.count_nonzero(a * b)
            if n > 5000:
                score[dy + SEARCH, dx + SEARCH] = (a * b).sum() / n
    iy, ix = np.unravel_index(np.argmax(score), score.shape)

    def refine(lo, mid, hi):
        d = lo - 2 * mid + hi
        return 0.0 if d >= 0 else 0.5 * (lo - hi) / d

    fy = refine(score[iy - 1, ix], score[iy, ix], score[iy + 1, ix]) if 0 < iy < 2 * SEARCH else 0.0
    fx = refine(score[iy, ix - 1], score[iy, ix], score[iy, ix + 1]) if 0 < ix < 2 * SEARCH else 0.0
    return iy - SEARCH + fy, ix - SEARCH + fx, float(score[iy, ix]), float(score[SEARCH, SEARCH])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2021, 2022, 2023, 2024, 2025])
    args = ap.parse_args()
    if not earthaccess.login(strategy="netrc").authenticated:
        raise SystemExit("Not signed in to NASA Earthdata. Run tools/canopy/earthdata_signin.py first.")
    city = dict(np.load(WORK / "citywide_blocks.npz"))
    x0, y1 = float(city["x0"]), float(city["y1"])
    rows, cols = city["lst"].shape
    bounds = (x0, y1 - rows * BLOCK, x0 + cols * BLOCK, y1)
    block_grid = rasterio.transform.from_origin(x0, y1, BLOCK, BLOCK)
    lonlat = (-111.08, 32.07, -110.72, 32.35)
    developed = (city["developed"] >= 0.5) & np.isfinite(city["lst"])

    # ---- 1. find the afternoon scenes -------------------------------------
    scenes = {}
    for year in args.years:
        for g in earthaccess.search_data(short_name="ECO_L2T_LSTE", version="002",
                                         bounding_box=lonlat, count=4000,
                                         temporal=(f"{year}-06-01", f"{year}-09-01")):
            name = g["umm"]["GranuleUR"]
            part = name.split("_")       # ECOv002 L2T LSTE orbit scene tile time build iteration
            if len(part) != 9 or part[5] not in TILES:
                continue
            start = g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
            local = dt.datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(MST)
            if not HOURS[0] <= local.hour < HOURS[1]:
                continue
            links = {l.rsplit("_", 1)[-1]: l for l in g.data_links()}
            scene = scenes.setdefault((part[3], part[4]), dict(local=local, tiles={}))
            processing = (part[7], part[8])
            if part[5] not in scene["tiles"] or processing > scene["tiles"][part[5]]["processing"]:
                scene["tiles"][part[5]] = dict(processing=processing, lst=links["LST.tif"],
                                               cloud=links["cloud.tif"])
    scenes = sorted(scenes.values(), key=lambda s: s["local"])
    print(len(scenes), "afternoon scenes found", flush=True)

    # ---- 2. download --------------------------------------------------------
    store = WORK / "ecostress"
    store.mkdir(exist_ok=True)
    want = [u for s in scenes for t in s["tiles"].values() for u in (t["lst"], t["cloud"])
            if not (store / u.rsplit("/", 1)[-1]).exists()]
    for i in range(0, len(want), 40):
        earthaccess.download(want[i:i + 40], str(store), threads=8)
        print(f"  downloaded {min(i + 40, len(want))} of {len(want)} files", flush=True)

    # ---- 3. each scene onto the blocks, clear of cloud ----------------------
    def to_blocks(scene, move=(0.0, 0.0)):
        """Scene on the 90 m blocks in degrees C; move = (metres east, metres north)."""
        out = np.full((rows, cols), np.nan, np.float32)
        for tile in TILES:
            if tile not in scene["tiles"]:
                continue
            f_lst = store / scene["tiles"][tile]["lst"].rsplit("/", 1)[-1]
            f_cloud = store / scene["tiles"][tile]["cloud"].rsplit("/", 1)[-1]
            if not (f_lst.exists() and f_cloud.exists()):
                continue
            with rasterio.open(f_lst) as src:
                pad = 2000
                win = from_bounds(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad,
                                  src.transform).round_offsets().round_lengths()
                lst = src.read(1, window=win, boundless=True, fill_value=np.nan).astype(np.float32)
                placed, crs = src.window_transform(win), src.crs
            with rasterio.open(f_cloud) as src:
                cloud = src.read(1, window=win, boundless=True, fill_value=1)
            bad = ndimage.binary_dilation(cloud != 0, iterations=CLOUD_GROW)
            lst = np.where(np.isfinite(lst) & (lst > 250) & ~bad, lst - 273.15, np.nan)
            part = np.full((rows, cols), np.nan, np.float32)
            reproject(lst, part, src_transform=Affine.translation(*move) * placed, src_crs=crs,
                      dst_transform=block_grid, dst_crs=f"EPSG:{EPSG}", resampling=Resampling.average,
                      src_nodata=np.nan, dst_nodata=np.nan)
            out = np.where(np.isfinite(out), out, part)
        return out

    # ---- 4. where each scene sits, against Landsat's fine detail ------------
    ref_detail = detail(city["lst"].astype(float))
    ref_z = standardise(ref_detail)
    stack, used, dropped = [], [], []
    for s in scenes:
        blocks = to_blocks(s)
        clear = float(np.isfinite(blocks[developed]).mean())
        when = s["local"].strftime("%Y-%m-%d %H:%M")
        if clear < MIN_CLEAR:
            dropped.append(dict(local=when, clear=round(clear, 2), why="cloud"))
            continue
        down, right, agree, agree_as_placed = best_shift(ref_z, standardise(detail(blocks.astype(float))))
        east, north = right * BLOCK, -down * BLOCK
        if agree < MIN_DETAIL_R:
            dropped.append(dict(local=when, clear=round(clear, 2), why="detail does not match",
                                agreement=round(agree, 2)))
            continue
        if abs(east) > 20 or abs(north) > 20:
            blocks = to_blocks(s, (east, north))
        med = float(np.nanmedian(blocks[developed]))
        stack.append(blocks - med)
        used.append(dict(local=when, clear=round(clear, 2), median_degC=round(med, 1),
                         moved_east_m=round(east), moved_north_m=round(north),
                         agreement_as_placed=round(agree_as_placed, 2), agreement=round(agree, 2),
                         spread_degC=round(float(np.nanstd(blocks[developed])), 2)))
        print("  ", used[-1], flush=True)
    for d in dropped:
        print("   dropped", d, flush=True)
    print(len(used), "scenes kept", flush=True)
    cube = np.stack(stack)
    looks = np.isfinite(cube).sum(0)
    pattern = np.where(looks >= MIN_SCENES, np.nanmedian(cube, 0), np.nan).astype(np.float32)
    np.savez_compressed(WORK / "ecostress_blocks.npz", x0=x0, y1=y1, anomaly=pattern, looks=looks)

    both = developed & np.isfinite(pattern)
    landsat_r = float(np.corrcoef(pattern[both], city["lst"][both])[0, 1])
    pd_ = detail(pattern.astype(float))
    m = both & np.isfinite(pd_) & np.isfinite(ref_detail)
    landsat_detail_r = float(np.corrcoef(pd_[m], ref_detail[m])[0, 1])

    # a picture to look at: Landsat beside ECOSTRESS
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(15, 7))
        a = np.where(developed, city["lst"] - np.nanmedian(city["lst"][developed]), np.nan)
        for axis, grid, title in ((ax[0], a, "Landsat, about 11 a.m."), (ax[1], pattern, "ECOSTRESS, afternoon")):
            lo, hi = np.nanpercentile(grid, [2, 98])
            axis.imshow(grid, cmap="inferno", vmin=lo, vmax=hi)
            axis.set_title(title)
            axis.axis("off")
        fig.tight_layout()
        fig.savefig(WORK / "ecostress_check.jpg", dpi=110)
    except Exception as exc:                      # the picture is a convenience
        print("no picture:", exc)

    # ---- 6. the same fits as step 23 ---------------------------------------
    ok = (np.isfinite(pattern) & np.isfinite(city["canopy"]) & np.isfinite(city["pavement"]) &
          np.isfinite(city["elevation"]) & developed)
    rr, cc = np.nonzero(ok)
    canopy, pave = city["canopy"][ok].astype(float), city["pavement"][ok].astype(float)
    elev = city["elevation"][ok].astype(float)
    _, local_id = np.unique((rr // LOCAL_CELLS) * 10000 + cc // LOCAL_CELLS, return_inverse=True)
    uniq, boot_id = np.unique((rr // BOOT_CELLS) * 10000 + cc // BOOT_CELLS, return_inverse=True)
    members = [np.nonzero(boot_id == k)[0] for k in range(len(uniq))]
    X = np.column_stack([np.ones(len(canopy)), canopy, pave, elev - elev.mean()])
    Xl = np.column_stack([demean(v, local_id) for v in (canopy, pave, elev)])
    landsat = json.loads((WORK / "heat_citywide.json").read_text())
    slope = landsat["calibration"]["slope"]

    def fits(grid, seed):
        y = grid[ok].astype(float)
        yl = demean(y, local_id)
        plain, r2_plain = fit(y, X)
        local, r2_local = fit(yl, Xl)
        rng = np.random.default_rng(seed)
        draws = {"plain": [], "local": []}
        for _ in range(400):
            pick = np.concatenate([members[k] for k in rng.integers(0, len(uniq), len(uniq))])
            draws["plain"].append(fit(y[pick], X[pick])[0][1])
            draws["local"].append(fit(yl[pick], Xl[pick])[0][0])

        def summary(beta_canopy, beta_pave, r2, key):
            lo, hi = np.percentile(draws[key], [2.5, 97.5])
            return dict(canopy_degC_per_full_block=round(float(beta_canopy), 2),
                        pavement_degC_per_full_block=round(float(beta_pave), 2), r2=round(float(r2), 2),
                        canopy_lidar_units=round(float(beta_canopy * slope), 2),
                        interval_lidar_units=[round(float(lo * slope), 2), round(float(hi * slope), 2)])
        return dict(plain=summary(plain[1], plain[2], r2_plain, "plain"),
                    local=summary(local[0], local[1], r2_local, "local"),
                    elevation_degC_per_100m=round(float(plain[3] * 100), 2))

    # scene by scene, so the answer does not rest on how the scenes were combined
    by_scene = []
    for grid, u in zip(cube, used):
        seen = np.isfinite(grid[ok])
        if seen.mean() < 0.5:
            continue
        g = local_id[seen]
        _, g = np.unique(g, return_inverse=True)
        cols_l = [demean(v[seen], g) for v in (canopy, pave, elev)]
        beta = fit(demean(grid[ok][seen].astype(float), g), np.column_stack(cols_l))[0]
        u["canopy_local_lidar_units"] = round(float(beta[0] * slope), 2)
        by_scene.append(u["canopy_local_lidar_units"])
    by_scene = np.array(by_scene)

    afternoon = fits(pattern, 20261114)
    # Landsat again on exactly these blocks, so the two hours are compared like for like
    morning = fits(city["lst"], 20261114)

    hours = sorted(dt.datetime.strptime(u["local"], "%Y-%m-%d %H:%M").hour +
                   dt.datetime.strptime(u["local"], "%Y-%m-%d %H:%M").minute / 60 for u in used)
    moved = [float(np.hypot(u["moved_east_m"], u["moved_north_m"])) for u in used]
    out = dict(
        product="ECOSTRESS ECO_L2T_LSTE v002, tiles " + " and ".join(TILES), years=args.years,
        scenes_found=len(scenes), scenes_used=len(used),
        dropped_for_cloud=sum(d["why"] == "cloud" for d in dropped),
        dropped_for_detail=sum(d["why"] != "cloud" for d in dropped),
        median_local_hour=round(float(np.median(hours)), 1),
        hour_range=[round(hours[0], 1), round(hours[-1], 1)],
        median_citywide_degC=round(float(np.median([u["median_degC"] for u in used])), 1),
        median_moved_m=round(float(np.median(moved))), largest_moved_m=round(max(moved)),
        blocks=int(ok.sum()), median_clear_looks=int(np.median(looks[ok])),
        spread_degC=round(float(pattern[ok].std()), 2),
        agreement_with_landsat=round(landsat_r, 2), detail_agreement_with_landsat=round(landsat_detail_r, 2),
        plain=afternoon["plain"], local=afternoon["local"],
        scene_by_scene_local=dict(scenes=int(len(by_scene)), median=round(float(np.median(by_scene)), 2),
                                  quartiles=[round(float(q), 2) for q in np.percentile(by_scene, [25, 75])],
                                  range=[round(float(by_scene.min()), 2), round(float(by_scene.max()), 2)]),
        elevation_degC_per_100m=afternoon["elevation_degC_per_100m"],
        landsat_same_blocks=morning, sites={}, scenes=used, dropped=dropped)
    for site, plans in landsat["sites"].items():
        out["sites"][site] = {}
        for name in SCEN:
            added = plans[name]["canopy_added_share"]
            out["sites"][site][name] = {
                key: dict(change_degC=round(added * out[key]["canopy_lidar_units"], 2),
                          interval_95=[round(added * out[key]["interval_lidar_units"][0], 2),
                                       round(added * out[key]["interval_lidar_units"][1], 2)])
                for key in ("plain", "local")}
    (WORK / "heat_ecostress.json").write_text(json.dumps(out, indent=1))
    brief = {k: v for k, v in out.items() if k not in ("scenes", "dropped", "sites")}
    print(json.dumps(brief, indent=1))
    print(json.dumps(out["sites"]["western_hills_ii"], indent=1))


if __name__ == "__main__":
    main()
