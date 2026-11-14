"""Step 9c (part 2): what the scenarios might do to summer surface temperature.

Runs in ArcGIS Pro's Python, after 13_surface_temperature.py:

  <Pro python> tools/canopy/14_heat.py

Method
  1. The 0.5 m land cover is summed into 90 m blocks (3 x 3 Landsat pixels,
     close to what the thermal sensor really resolves): the share of each
     block that is tree canopy, roof, pavement and open ground.
  2. Across the blocks of both sites, summer surface temperature is regressed
     on those shares, with open ground as the baseline and a separate
     starting level for each site. Each coefficient is the temperature
     difference, in degrees C, between a block fully covered by that class
     and a block of open ground.
  3. For each scenario the new crowns change the shares (they cover pavement
     or open ground as seen from above), and the fitted coefficients turn
     that into a temperature change per block and for the neighborhood.

Read the result as an estimate of direction and rough size, no more:
  * it is surface temperature at about 11 a.m., not afternoon air temperature
  * the relationship comes from two neighborhoods, not the whole city. The
    original plan was a citywide fit, but canopy at this detail exists only
    where the lidar has been processed
  * neighbouring blocks share blurred pixels, so the coefficients are pulled
    toward zero and their standard errors are too small
  * new trees are at mature size and treated like today's canopy

Writes work/heat.json and work/heat_blocks.csv (one row per block).
"""
import csv
import json

import arcpy
import numpy as np

from common import WORK, site_dir, sites, work_bbox

CELL = 0.5
BLOCK = 3                    # Landsat pixels per side
PIX = 30
N = int(PIX * BLOCK / CELL)  # land cover cells per block side
CLASSES = {"tree": (1,), "roof": (2,), "pavement": (3,), "open": (4, 5, 6)}
SCENARIOS = {1: "Street trees", 2: "Streets and homes", 3: "Full build-out"}


def blocks_for(site):
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    info = json.loads((d / "lst" / "lst.json").read_text())
    g = info["grid"]
    x0, y0, x1, y1 = work_bbox(site)
    # whole blocks of the Landsat grid that fall inside the work area
    c0 = int(np.ceil((x0 - g["x0"]) / PIX))
    r0 = int(np.ceil((g["y1"] - y1) / PIX))
    nbx = int((x1 - (g["x0"] + c0 * PIX)) // (PIX * BLOCK))
    nby = int(((g["y1"] - r0 * PIX) - y0) // (PIX * BLOCK))
    bx0, by1 = g["x0"] + c0 * PIX, g["y1"] - r0 * PIX
    ll = arcpy.Point(bx0, by1 - nby * PIX * BLOCK)
    rows, cols = nby * N, nbx * N

    def grab(path):
        return arcpy.RasterToNumPyArray(path, ll, cols, rows, nodata_to_value=0)

    def share(mask):
        return mask.reshape(nby, N, nbx, N).mean((1, 3))

    lst = arcpy.RasterToNumPyArray(str(d / "lst" / "lst_summer.tif"),
                                   nodata_to_value=np.nan).astype(float)
    cnt = arcpy.RasterToNumPyArray(str(d / "lst" / "lst_count.tif"), nodata_to_value=0)
    lst = lst[r0:r0 + nby * BLOCK, c0:c0 + nbx * BLOCK]
    cnt = cnt[r0:r0 + nby * BLOCK, c0:c0 + nbx * BLOCK]
    lst_b = np.nanmean(lst.reshape(nby, BLOCK, nbx, BLOCK), (1, 3))
    cnt_b = cnt.reshape(nby, BLOCK, nbx, BLOCK).min((1, 3))

    lc = grab(f"{gdb}/land_cover")
    inside = share(grab(str(d / "tmp" / "inside.tif")) > 0)
    f = {k: share(np.isin(lc, v)) for k, v in CLASSES.items()}
    tree = lc == 1
    change = {}
    for s in SCENARIOS:
        new = (grab(f"{gdb}/canopy_s{s}") == 1) & ~tree
        change[s] = dict(tree=share(new), pavement=-share(new & (lc == 3)),
                         roof=-share(new & (lc == 2)))
    return dict(site=site["id"], lst=lst_b, count=cnt_b, inside=inside, f=f,
                change=change, x0=bx0, y1=by1)


def main():
    arcpy.CheckOutExtension("Spatial")
    data = [blocks_for(s) for s in sites()]
    rows = []
    for i, b in enumerate(data):
        ok = np.isfinite(b["lst"]) & (b["count"] >= 5)
        for r, c in zip(*np.nonzero(ok)):
            rows.append((i, r, c))
    y = np.array([data[i]["lst"][r, c] for i, r, c in rows])
    X = np.column_stack(
        [[1.0 if i == k else 0.0 for i, _, _ in rows] for k in range(len(data))] +
        [[data[i]["f"][name][r, c] for i, r, c in rows]
         for name in ("tree", "roof", "pavement")])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    cov = np.linalg.inv(X.T @ X) * (resid @ resid / dof)
    se = np.sqrt(np.diag(cov))
    k = len(data)
    coef = {name: dict(degC=round(float(beta[k + j]), 2), se=round(float(se[k + j]), 2))
            for j, name in enumerate(("tree", "roof", "pavement"))}
    # R2 within sites: how much of the variation the land cover explains once
    # each site's own level is taken out
    within = y - X[:, :k] @ np.linalg.lstsq(X[:, :k], y, rcond=None)[0]
    r2 = 1 - float(resid @ resid) / float(within @ within)

    out = dict(
        blocks=len(y), block_m=PIX * BLOCK, r2_within_sites=round(r2, 2),
        residual_sd_degC=round(float(np.sqrt(resid @ resid / dof)), 2),
        baseline="open ground (bare ground and low vegetation)",
        coefficients_vs_open_ground=coef, sites={})
    table = []
    for i, b in enumerate(data):
        w = b["inside"]
        ok = np.isfinite(b["lst"])
        site_out = dict(
            mean_lst_degC=round(float(np.average(b["lst"][ok], weights=w[ok] + 1e-9)), 1),
            lst_range_degC=[round(float(np.nanmin(b["lst"])), 1),
                            round(float(np.nanmax(b["lst"])), 1)],
            scenarios={})
        for s, name in SCENARIOS.items():
            ch = b["change"][s]
            d_lst = (beta[k] * ch["tree"] + beta[k + 1] * ch["roof"] +
                     beta[k + 2] * ch["pavement"])
            # variance of the mean change from the coefficient covariance
            g = np.array([np.average(ch[n], weights=w + 1e-9)
                          for n in ("tree", "roof", "pavement")])
            mean = float(np.average(d_lst, weights=w + 1e-9))
            sd = float(np.sqrt(g @ cov[k:, k:] @ g))
            site_out["scenarios"][name] = dict(
                mean_change_degC=round(mean, 2),
                interval_95=[round(mean - 1.96 * sd, 2), round(mean + 1.96 * sd, 2)],
                largest_block_change_degC=round(float(d_lst[w > 0.5].min()), 2)
                if (w > 0.5).any() else None)
            b[f"d{s}"] = d_lst
        out["sites"][b["site"]] = site_out
        for r in range(b["lst"].shape[0]):
            for c in range(b["lst"].shape[1]):
                table.append(dict(
                    site=b["site"], x=b["x0"] + (c + 0.5) * PIX * BLOCK,
                    y=b["y1"] - (r + 0.5) * PIX * BLOCK,
                    inside_share=round(float(b["inside"][r, c]), 3),
                    lst_degC=round(float(b["lst"][r, c]), 2),
                    clear_scenes=int(b["count"][r, c]),
                    **{f"share_{n}": round(float(b["f"][n][r, c]), 3) for n in CLASSES},
                    **{f"change_s{s}_degC": round(float(b[f"d{s}"][r, c]), 3)
                       for s in SCENARIOS}))
    (WORK / "heat.json").write_text(json.dumps(out, indent=1))
    with open(WORK / "heat_blocks.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(table[0]))
        wr.writeheader()
        wr.writerows(table)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
