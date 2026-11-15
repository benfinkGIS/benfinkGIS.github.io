"""Step 8e: check each species' current map against where it has been seen.

Sightings follow observers, so a species' records are not compared with the
map as a whole but with every other research-grade iNaturalist record of the
same group (mammals for the bobcat, birds for the flycatcher, butterflies for
the queen). The question is: among places where someone was recording that
kind of animal, did the focal species turn up where the model puts more
current?

- Records placed to 100 m or better, thinned to one per 100 m square.
- Each surface is averaged over 50 m before it is read at a record.
- AUC: the chance that a focal record sits on a higher value than a
  background record. 0.5 is no better than a coin toss.
- 95% ranges from resampling 1 km squares, records and all, 1,000 times.
- The same score is given for the model's inputs (source strength and
  conductance), to show what the circuit model adds to them, and against
  random points, to show what the effort correction takes away.

Run:  py tools/washes/17_validate.py
"""
import json

import numpy as np
from pyproj import Transformer
from scipy import ndimage

from common import BBOX, EPSG, SIGHTINGS, SPECIES, WORK

OUT = WORK / "connectivity"
CELL = 10
X0, Y0, X1, Y1 = BBOX
NX, NY = int((X1 - X0) / CELL), int((Y1 - Y0) / CELL)
GROUP = {"bobcat": "mammals", "flycatcher": "birds", "queen": "butterflies"}
MAX_ACCURACY_M = 100
THIN_M = 100
BLOCK_M = 1000
SMOOTH_CELLS = 5
REPS = 1000
SEED = 20261115
TO_UTM = Transformer.from_crs(4326, EPSG, always_xy=True)


def thin(lon, lat):
    """Project, keep points in the box, one per THIN_M square. Returns x, y."""
    x, y = TO_UTM.transform(np.asarray(lon), np.asarray(lat))
    ok = (x >= X0) & (x < X1) & (y >= Y0) & (y < Y1)
    x, y = x[ok], y[ok]
    key = (np.floor(x / THIN_M).astype("int64") << 32) + np.floor(y / THIN_M).astype("int64")
    _, first = np.unique(key, return_index=True)
    return x[first], y[first]


def focal(species):
    gj = json.loads((SIGHTINGS / f"{species}.geojson").read_text())
    rows = [(f["properties"]["id"], *f["geometry"]["coordinates"]) for f in gj["features"]
            if (f["properties"].get("accuracy_m") or 1e9) <= MAX_ACCURACY_M]
    ids, lon, lat = zip(*rows)
    return set(ids), thin(lon, lat), len(rows)


def background(group, skip):
    d = json.loads((SIGHTINGS / f"effort_{group}.json").read_text())
    rows = [r for r in d["rows"] if r[0] not in skip and (r[3] or 1e9) <= MAX_ACCURACY_M]
    return thin([r[1] for r in rows], [r[2] for r in rows]), len(rows)


def at(surface, x, y):
    return surface[((Y1 - y) / CELL).astype(int), ((x - X0) / CELL).astype(int)]


def auc(pos, neg):
    """Mann-Whitney: chance a value from pos exceeds one from neg, ties counted half."""
    v = np.concatenate([pos, neg])
    _, inv, counts = np.unique(v, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    rank = (ends - (counts - 1) / 2.0)[inv]
    return float((rank[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def blocks(x, y):
    return (np.floor((x - X0) / BLOCK_M) * 1000 + np.floor((y - Y0) / BLOCK_M)).astype(int)


def score(surface, fx, fy, bx, by, rng):
    fv, bv = at(surface, fx, fy), at(surface, bx, by)
    fb, bb = blocks(fx, fy), blocks(bx, by)
    ids = np.unique(np.concatenate([fb, bb]))
    f_by = {i: fv[fb == i] for i in ids}
    b_by = {i: bv[bb == i] for i in ids}
    out = []
    for _ in range(REPS):
        pick = rng.choice(ids, len(ids))
        p = np.concatenate([f_by[i] for i in pick])
        n = np.concatenate([b_by[i] for i in pick])
        if len(p) and len(n):
            out.append(auc(p, n))
    low, high = np.percentile(out, [2.5, 97.5])
    return dict(auc=round(auc(fv, bv), 3), low=round(float(low), 3), high=round(float(high), 3))


def fifths(surface, fx, fy, bx, by):
    """Focal records per background record, by fifth of the area ranked by the surface."""
    cuts = np.percentile(surface, [20, 40, 60, 80])
    f = np.bincount(np.digitize(at(surface, fx, fy), cuts), minlength=5)
    b = np.bincount(np.digitize(at(surface, bx, by), cuts), minlength=5)
    overall = f.sum() / b.sum()
    return dict(focal=f.tolist(), background=b.tolist(),
                ratio_to_overall=[round(float(fi / bi / overall), 2) if bi else None for fi, bi in zip(f, b)])


def main():
    rng = np.random.default_rng(SEED)
    surf = dict(np.load(OUT / "surfaces.npz"))
    smooth = lambda a: ndimage.uniform_filter(a.astype("float32"), SMOOTH_CELLS, mode="nearest")
    result = dict(max_accuracy_m=MAX_ACCURACY_M, thin_m=THIN_M, block_m=BLOCK_M,
                  smooth_m=SMOOTH_CELLS * CELL, reps=REPS, species={})
    for sp in (s["id"] for s in SPECIES):
        if not (OUT / "arrays" / f"{sp}.npz").exists():
            continue        # not run yet
        skip, (fx, fy), n_f = focal(sp)
        (bx, by), n_b = background(GROUP[sp], skip)
        rx, ry = rng.uniform(X0, X1, 20000), rng.uniform(Y0, Y1, 20000)
        run = dict(np.load(OUT / "arrays" / f"{sp}.npz"))
        surfaces = {"current": run["current"], "normalized current": run["normalized"],
                    "source strength": surf[f"{sp}_source"],
                    "conductance": 1 / surf[f"{sp}_resistance"]}
        if sp == "bobcat":
            for extra in ("bobcat_closed", "bobcat_open"):
                if (OUT / "arrays" / f"{extra}.npz").exists():
                    surfaces[f"current, culverts {extra.split('_')[1]}"] = np.load(
                        OUT / "arrays" / f"{extra}.npz")["current"]
        res = dict(group=GROUP[sp], records=n_f, records_thinned=len(fx),
                   background_records=n_b, background_thinned=len(bx), against_group={},
                   against_random={})
        for name, a in surfaces.items():
            s = smooth(a)
            res["against_group"][name] = score(s, fx, fy, bx, by, rng)
            res["against_random"][name] = dict(auc=round(auc(at(s, fx, fy), at(s, rx, ry)), 3))
        res["fifths_of_current"] = fifths(smooth(run["current"]), fx, fy, bx, by)
        result["species"][sp] = res
        print(sp, json.dumps(res), flush=True)
    (OUT / "validation.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
