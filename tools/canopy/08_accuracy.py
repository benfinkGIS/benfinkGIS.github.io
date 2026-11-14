"""Step 3c: score the land cover against the hand-labelled points.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/08_accuracy.py [--labels path]

Reads work/accuracy/labels.json (written by the labelling page) and
key.json, writes each label into the GrndTruth field of that site's
accuracy_points layer, and reports, for each site and for both together:

  * the error matrix (rows: mapped class; columns: labelled class)
  * user's accuracy (of the cells mapped as X, the share that are X)
  * producer's accuracy (of the ground that is X, the share mapped as X)
  * overall accuracy with a 95% interval, and kappa
  * the same with low vegetation and bare ground merged into "open ground"
  * the same for two questions the scenario depends on: tree canopy or not,
    and impervious (roof or pavement) or not
  * each class's share of the neighborhood corrected for the map's errors

The sample put the same number of points in every mapped class, so common
classes are under-sampled. Every figure except the raw matrix and kappa
therefore weights each mapped class by its share of the map (Olofsson et al.
2014, "Good practices for estimating area and assessing accuracy of land
change"). Points labelled "can't tell" or not labelled are left out and
counted separately.

Also runs Esri's Compute Confusion Matrix on each site's points, as a
cross-check, into <site>.gdb/confusion_matrix.

Writes work/accuracy/accuracy.json and accuracy.csv.
"""
import argparse
import csv
import json
import math
from pathlib import Path

import arcpy
import numpy as np

from common import WORK, site_dir, sites, work_bbox

CELL = 0.5
NAMES = {1: "Tree canopy", 2: "Roof", 3: "Pavement", 4: "Low vegetation",
         5: "Bare ground", 6: "Water"}
GROUPINGS = {
    "all classes": {k: v for k, v in NAMES.items()},
    "open ground merged": {1: "Tree canopy", 2: "Roof", 3: "Pavement",
                           4: "Open ground", 5: "Open ground", 6: "Water"},
    "tree canopy or not": {1: "Tree canopy", 2: "Not tree", 3: "Not tree",
                           4: "Not tree", 5: "Not tree", 6: "Not tree"},
    "impervious or not": {1: "Pervious", 2: "Impervious", 3: "Impervious",
                          4: "Pervious", 5: "Pervious", 6: "Pervious"},
}


def score(points, weights, group):
    """points: (stratum, mapped, labelled). weights: stratum -> share of map.
    Strata are the mapped classes the sample was drawn from (per site)."""
    cats = list(dict.fromkeys(group.values()))
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    counts = np.zeros((k, k))
    prop = np.zeros((k, k))          # area-weighted share of the map
    var_oa = 0.0
    by = {}
    for stratum, mapped, lab in points:
        by.setdefault(stratum, []).append((idx[group[mapped]], idx[group[lab]]))
    for stratum, rows in by.items():
        n = len(rows)
        w = weights[stratum]
        hit = 0
        for i, j in rows:
            counts[i, j] += 1
            prop[i, j] += w / n
            hit += i == j
        if n > 1:
            p = hit / n
            var_oa += w * w * p * (1 - p) / (n - 1)
    used = sum(weights[s] for s in by)
    prop /= used                     # strata with no usable points drop out
    oa = float(np.trace(prop))
    se = math.sqrt(var_oa) / used
    n = counts.sum()
    po = np.trace(counts) / n
    pe = float((counts.sum(0) * counts.sum(1)).sum()) / (n * n)
    out = dict(
        classes=cats, points=int(n),
        matrix=counts.astype(int).tolist(),
        overall_accuracy=round(oa, 3),
        overall_95=[round(max(0, oa - 1.96 * se), 3), round(min(1, oa + 1.96 * se), 3)],
        unweighted_accuracy=round(float(po), 3),
        kappa=round(float((po - pe) / (1 - pe)), 3) if pe < 1 else None,
        users={}, producers={}, mapped_share={}, corrected_share={})
    for c, i in idx.items():
        row, col = prop[i].sum(), prop[:, i].sum()
        out["users"][c] = round(float(prop[i, i] / row), 3) if row else None
        out["producers"][c] = round(float(prop[i, i] / col), 3) if col else None
        out["mapped_share"][c] = round(float(row), 4)
        out["corrected_share"][c] = round(float(col), 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(WORK / "accuracy" / "labels.json"))
    args = ap.parse_args()
    arcpy.CheckOutExtension("Spatial")
    arcpy.env.overwriteOutput = True
    acc = WORK / "accuracy"
    key = json.loads((acc / "key.json").read_text())
    labels = {k: v["label"] for k, v in json.loads(Path(args.labels).read_text()).items()}

    cells, pts = {}, {}
    skipped = dict(not_labelled=0, cant_tell=0)
    for s in sites():
        d = site_dir(s)
        gdb = str(d / f"{s['id']}.gdb")
        x0, y0, x1, y1 = work_bbox(s)
        ll = arcpy.Point(x0, y0)
        rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
        lc = arcpy.RasterToNumPyArray(f"{gdb}/land_cover", ll, cols, rows, nodata_to_value=0)
        inside = arcpy.RasterToNumPyArray(str(d / "tmp" / "inside.tif"), ll, cols, rows,
                                          nodata_to_value=0) > 0
        # The map may have been improved since the sample was drawn. Strata
        # stay as drawn; the class being scored is the map as it is now
        mine = [k for k in key if k["site"] == s["id"]]
        strata_cells = {}
        for k in mine:
            strata_cells.setdefault(k["classified"], 0)
        now = {}
        for k in mine:
            r, c = int((y1 - k["y"]) / CELL), int((k["x"] - x0) / CELL)
            now[k["id"]] = int(lc[r, c])
        drawn = json.loads((acc / "strata.json").read_text())[s["id"]] \
            if (acc / "strata.json").exists() else None
        for code in strata_cells:
            cells[(s["id"], code)] = (drawn[str(code)] if drawn else
                                      int((inside & (lc == code)).sum()))
        with arcpy.da.UpdateCursor(f"{gdb}/accuracy_points",
                                   ["PointID", "Classified", "GrndTruth"]) as cur:
            for pid, cls, _ in cur:
                lab = labels.get(pid)
                cur.updateRow((pid, now[pid], lab if lab else -1))
        for k in mine:
            lab = labels.get(k["id"])
            if lab is None:
                skipped["not_labelled"] += 1
            elif lab == 0:
                skipped["cant_tell"] += 1
            else:
                pts.setdefault(s["id"], []).append(
                    ((s["id"], k["classified"]), now[k["id"]], lab))
        arcpy.management.MakeFeatureLayer(f"{gdb}/accuracy_points", "scored",
                                          "GrndTruth > 0")
        if int(arcpy.management.GetCount("scored")[0]) > 1:
            arcpy.sa.ComputeConfusionMatrix("scored", f"{gdb}/confusion_matrix")
        arcpy.management.Delete("scored")

    report = dict(skipped=skipped, sites={})
    table = []
    groups = [(s["id"], pts.get(s["id"], [])) for s in sites()]
    groups.append(("both sites", [p for _, g in groups for p in g]))
    for name, group_pts in groups:
        if len(group_pts) < 2:
            continue
        strata = {p[0] for p in group_pts}
        total = sum(v for (site, _), v in cells.items()
                    if name == "both sites" or site == name)
        weights = {st: cells[st] / total for st in strata}
        report["sites"][name] = {}
        for gname, group in GROUPINGS.items():
            r = score(group_pts, weights, group)
            report["sites"][name][gname] = r
            for c in r["classes"]:
                table.append(dict(site=name, question=gname, class_name=c,
                                  users=r["users"][c], producers=r["producers"][c],
                                  mapped_share=r["mapped_share"][c],
                                  corrected_share=r["corrected_share"][c],
                                  overall=r["overall_accuracy"],
                                  overall_low=r["overall_95"][0],
                                  overall_high=r["overall_95"][1],
                                  kappa=r["kappa"], points=r["points"]))
    (acc / "accuracy.json").write_text(json.dumps(report, indent=1))
    if table:
        with open(acc / "accuracy.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(table[0]))
            w.writeheader()
            w.writerows(table)
    print("left out:", skipped)
    for name, res in report["sites"].items():
        for gname, r in res.items():
            print(f"\n{name} | {gname} | {r['points']} points | overall "
                  f"{r['overall_accuracy']:.1%} ({r['overall_95'][0]:.1%} to "
                  f"{r['overall_95'][1]:.1%}) | kappa {r['kappa']}")
            for c in r["classes"]:
                pct = lambda v: "  n/a" if v is None else f"{v:>5.0%}"
                print(f"   {c:15s} user's {pct(r['users'][c])} "
                      f" producer's {pct(r['producers'][c])} "
                      f" mapped {r['mapped_share'][c]:.1%}  corrected {r['corrected_share'][c]:.1%}")

if __name__ == "__main__":
    main()
