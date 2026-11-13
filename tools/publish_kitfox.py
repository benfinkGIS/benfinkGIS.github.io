#!/usr/bin/env python3
"""Write the data the kit fox release page reads.

Usage (from the repo root, after build_kitfox_shortlist.py):
    py tools/publish_kitfox.py

The page at /kit-fox-release/ lets the reader change the model's weights, so it needs
the eight scored criteria, not just the finished surface. This script reads them from
the ArcGIS Pro project (read only), scores each one exactly as the Suitability Modeler
did, and averages them onto one coarse grid the browser can redraw quickly:

    kit-fox-release/data/crit1.png, crit2.png, crit3.png
        the eight criterion scores, one per colour channel (score x 25; 0 = no data),
        on a Web Mercator grid of 600 m cells (about 500 m on the ground)
    kit-fox-release/data/model.json
        weights from the model file, grid position, study-area figures and the shortlist

Averaging is linear, so the weighted sum of the coarse criteria equals the coarse
average of the model's own surface; the script checks that and prints the difference.

The shortlist comes from tools/kitfox-review/shortlist.json, and the wilderness and other
designation outlines from designations.geojson beside it. Candidate areas are
published only as rounded positions (0.1 degree, about 10 km), never as the circles
themselves: the page must not point at a spot where an animal could be found.
"""
import json
import math
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path

import numpy as np

try:
    import rasterio
except ImportError:
    sys.path.insert(0, os.path.join(tempfile.gettempdir(), "finkgeo_pydeps"))
    import rasterio
from affine import Affine
from rasterio.warp import Resampling, calculate_default_transform, reproject

import geopandas as gpd
import pyogrio
from PIL import Image
from pyproj import Transformer

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "kitfox-review" / "shortlist.json"
CONFIG = SRC.with_name("project.json")   # git-ignored: where the ArcGIS Pro project is, and its layer names
if not CONFIG.exists():
    raise SystemExit(f"Missing {CONFIG}; see tools/build_kitfox_shortlist.py")
CFG = json.loads(CONFIG.read_text(encoding="utf-8"))
PROJECT = Path(CFG["project"])
GDB = str(PROJECT / "Default.gdb")
SAM = sorted(PROJECT.glob("*.sam"))[0]   # the Suitability Modeler file
DST = ROOT / "kit-fox-release" / "data"
RES = 600          # Web Mercator metres per cell
SCALE = 25         # stored byte = score x 25
ROUND_DEG = 0.1    # candidate positions are rounded to this

# model criterion name -> (key used by the page, dataset in the gdb)
CRITERIA = {
    "Kit_Fox_EVT": ("vegtype", "Kit_Fox_EVT"),
    "Kit_Fox_EVC": ("vegcover", "Kit_Fox_EVC"),
    "SoilMapUnitPolygonsAZ_Clip_PolygonToRaster": ("soil", "SoilMapUnitPolygonsAZ_Clip_PolygonToRaster"),
    "Reclass_VNL_1": ("lights", "Reclass_VNL_1"),
    "Elev_Reclass_outp1_Clip": ("elevation", "Elev_Reclass_outp1_Clip"),
    "Reclass_DevelopedAg": ("developed", "Reclass_EucD1"),
    "Reclass_Slop1_Clip": ("slope", "Reclass_Slop1_Clip"),
    "water": ("water", "Reclass_EucD2"),
}


def gdb_raster(name):
    return rasterio.open(f'OpenFileGDB:"{GDB}":{name}')


def model():
    with open(SAM, encoding="utf-8-sig") as f:
        models = json.load(f)["SAModels"]
    s = models[models["Info"]["ModelNames"][0]]["Suitability"]
    out = []
    for name, weight, params in zip(s["CriteriaNames"], s["WeightValues"], s["TransformParameters"]):
        p = json.loads(params.replace("'", '"')) if isinstance(params, str) else params
        if "UniqueTransformParams" in p:      # category (as text) -> suitability
            u = p["UniqueTransformParams"]
            xform = {int(float(c)): int(v) for c, v in zip(u["UniqueCategoryValue"], u["UniqueSuitValue"])}
        else:                                  # ranges of the score -> suitability
            r = p["RangeTransformParams"]
            xform = list(zip(r["RangeFromValue"], r["RangeToValue"], r["RangeSuitValue"]))
        out.append({"name": name, "weight": float(weight), "xform": xform})
    return out


def score_lookup(dataset, xform):
    """Raster value -> suitability 1-10, the way the model's transformation did it."""
    vat = pyogrio.read_dataframe(GDB, layer=f"VAT_{dataset}", LIST_ALL_TABLES="YES", read_geometry=False)
    field = "Score" if "Score" in vat.columns else "Value"
    lut = np.zeros(int(vat["Value"].max()) + 1, dtype=np.uint8)
    for value, score in zip(vat["Value"].astype(int), vat[field].astype(float)):
        if value < 0:
            continue
        if isinstance(xform, dict):
            suit = xform.get(int(score), 0)
        else:
            suit = next((s for lo, hi, s in xform if lo <= score < hi or (score == hi == xform[-1][1])), 0)
        lut[value] = suit
    return lut


def describe(d):
    """A designation as the page may show it. An area is only tied to a named place when it lies
    mostly inside it; a small overlap with a small wilderness would pin the area down too closely."""
    level = "in" if d["share"] >= 0.9 else "mostly" if d["share"] >= 0.5 else "partly"
    return {"kind": d["kind"], "label": d["label"], "level": level, "name": d["name"] if level != "partly" else None}


def outlines(ring):
    """Designation outlines inside or touching the search area, thinned for a small-scale map."""
    g = gpd.read_file(SRC.with_name("designations.geojson"))
    g = g[g.intersects(ring)].copy()
    g["geometry"] = g.geometry.simplify(0.002)
    out = []
    for d in g.itertuples():
        parts = list(d.geometry.geoms) if hasattr(d.geometry, "geoms") else [d.geometry]
        polys = [[[round(y, 3), round(x, 3)] for x, y in part.exterior.coords]
                 for part in parts if part.geom_type == "Polygon" and not part.is_empty]
        if polys:
            out.append({"kind": d.kind, "label": d.label, "name": d.name, "polys": polys})
    return out


def compass(dx, dy):
    names = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
    return names[int(round(math.degrees(math.atan2(dy, dx)) / 45)) % 8]


def main():
    DST.mkdir(parents=True, exist_ok=True)
    crit = model()
    assert abs(sum(c["weight"] for c in crit) - 100) < 1e-6, "weights no longer sum to 100"

    with gdb_raster("KitFox") as ds:
        surface = ds.read(1)
        src_t, src_crs = ds.transform, ds.crs
        b = ds.bounds
    ok = np.isfinite(surface) & (surface < 1e30)
    dt, w, h = calculate_default_transform(src_crs, "EPSG:3857", surface.shape[1], surface.shape[0],
                                           b.left, b.bottom, b.right, b.top, resolution=RES)

    def to_grid(a, crs, transform, nodata):
        out = np.full((h, w), np.nan, dtype=np.float32)
        reproject(a, out, src_transform=transform, src_crs=crs, src_nodata=nodata, dst_transform=dt,
                  dst_crs="EPSG:3857", dst_nodata=np.nan, resampling=Resampling.average)
        return out

    truth = to_grid(np.where(ok, surface, -1).astype(np.float32), src_crs, src_t, -1)
    cover = to_grid(ok.astype(np.float32), src_crs, src_t, None)
    del surface

    layers = []
    for c in crit:
        key, dataset = CRITERIA[c["name"]]
        lut = score_lookup(dataset, c["xform"])
        with gdb_raster(dataset) as ds:
            a = ds.read(1)
            scored = lut[np.clip(a, 0, len(lut) - 1)]
            scored[a < 0] = 0
            g = to_grid(scored, ds.crs, ds.transform, 0)
        layers.append(g)
        print(f"  {key:10s} weight {c['weight']:4.0f}  mean score {np.nanmean(g):.2f}")

    inside = (cover >= 0.5) & np.isfinite(truth) & np.all(np.isfinite(layers), axis=0)
    packed = [np.where(inside, np.clip(np.rint(g * SCALE), 1, 255), 0).astype(np.uint8) for g in layers]

    # check: the page's arithmetic on the stored bytes against the model's own surface
    recon = sum(c["weight"] * p.astype(np.float64) for c, p in zip(crit, packed)) / (100 * SCALE)
    diff = np.abs(recon - truth)[inside]
    print(f"  rebuilt surface vs the model's: mean difference {diff.mean():.3f}, "
          f"99th percentile {np.percentile(diff, 99):.3f}, largest {diff.max():.2f} (on a 1-10 scale)")

    # area share scoring 7+ as the page will compute it (cells weighted by true ground area)
    to_ll = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    ys = dt.f + dt.e * (np.arange(h) + 0.5)
    lat = np.array([to_ll.transform(dt.c, y)[1] for y in ys])
    wrow = np.cos(np.radians(lat)) ** 2
    area = (inside * wrow[:, None])
    coarse_share = float((area * (recon >= 7)).sum() / area.sum())

    for i in range(3):
        chans = packed[i * 3:i * 3 + 3]
        while len(chans) < 3:
            chans.append(np.zeros((h, w), np.uint8))
        Image.fromarray(np.dstack(chans), "RGB").save(DST / f"crit{i + 1}.png", optimize=True)
        print(f"  crit{i + 1}.png {(DST / f'crit{i + 1}.png').stat().st_size / 1024:6.0f} KB")

    short = json.loads(SRC.read_text(encoding="utf-8"))
    center = gpd.read_file(GDB, layer=CFG["center_layer"]).to_crs("EPSG:4326").geometry.iloc[0]
    ring = gpd.read_file(GDB, layer=CFG["area_layer"]).to_crs("EPSG:4326").geometry.simplify(0.005).iloc[0]
    to_m = Transformer.from_crs("EPSG:4326", "EPSG:26912", always_xy=True)
    sx, sy = to_m.transform(center.x, center.y)

    rows, seen = [], set()
    for p in short["lists"]["screened"]:
        px, py = to_m.transform(p["lon"], p["lat"])
        pos = (round(round(p["lat"] / ROUND_DEG) * ROUND_DEG, 1), round(round(p["lon"] / ROUND_DEG) * ROUND_DEG, 1))
        if pos in seen:
            print(f"  note: areas share the rounded position {pos}")
        seen.add(pos)
        rows.append({"rank": p["rank"], "manager": p["manager"], "manager_share": p["manager_share"],
                     "score": p["mean_score"], "high_share": p["high_share"], "slope": p["slope_deg"],
                     "road_km": p["road_km"], "center_km": int(round(p["center_km"] / 5) * 5),
                     "dir": compass(px - sx, py - sy), "lat": pos[0], "lon": pos[1],
                     "designations": [describe(d) for d in p.get("designations", [])]})

    alone = short["lists"]["score"]
    managers = {}
    for p in alone:
        managers[p["manager"]] = managers.get(p["manager"], 0) + 1
    open_names = set(short["settings"]["public_managers"])
    s, wst = to_ll.transform(dt.c, dt.f + dt.e * h)[::-1], None
    n_e = to_ll.transform(dt.c + dt.a * w, dt.f)
    data = {
        "built": time.strftime("%Y-%m-%d"),
        "grid": {"w": w, "h": h, "scale": SCALE,
                 "bounds": [[round(s[0], 5), round(s[1], 5)], [round(n_e[1], 5), round(n_e[0], 5)]]},
        "criteria": [{"key": CRITERIA[c["name"]][0], "weight": c["weight"]} for c in crit],
        "study_km2": short["study_km2"], "high_km2": short["high_km2"],
        "high_cutoff": short["settings"]["high_cutoff"], "coarse_high_share": round(coarse_share, 4),
        "by_manager": [{"name": m["name"], "km2": m["km2"], "high_km2": m["high_km2"], "open": m["name"] in open_names}
                       for m in short["by_manager"] if m["high_km2"] >= 1],
        "settings": {k: short["settings"][k] for k in ("radius_km", "spacing_km", "top", "min_public",
                                                       "road_gap_km", "max_slope_deg")},
        "screened_km2": short["eligible_km2"]["screened"],
        "shortlist": rows,
        "score_alone": {"top": len(alone), "managers": managers,
                        "steep": sum(1 for p in alone if p["slope_deg"] is not None and p["slope_deg"] > short["settings"]["max_slope_deg"]),
                        "not_open": sum(1 for p in alone if p["public_share"] < short["settings"]["min_public"])},
        "designated": short.get("designated", []),
        "designations": outlines(ring),
        "round_deg": ROUND_DEG,
        "center": [round(center.y, 3), round(center.x, 3)],
        "study_area": [[round(y, 3), round(x, 3)] for x, y in ring.exterior.coords],
    }
    (DST / "model.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"  model.json {(DST / 'model.json').stat().st_size / 1024:6.1f} KB")
    print(f"  grid {w} x {h}; share scoring {data['high_cutoff']:g}+ on the coarse grid {coarse_share:.1%} "
          f"(30 m surface: {short['high_km2'] / short['study_km2']:.1%})")


if __name__ == "__main__":
    main()
