"""Draft shortlist of kit fox release areas from the kit fox suitability model.

Reads the finished suitability surface from the ArcGIS Pro project (it does not
change the model or its weights), then does what the model's Locate step was set
up to do: find circular areas with the highest average suitability. Each area is
then tagged with who manages the land and how far the nearest highway is.

Inputs
  - KitFox raster, the center point, the search-area circle and the TIGER
    primary/secondary road layers in the project's Default.gdb (read only). The
    project's location and layer names come from tools/kitfox-review/project.json.
  - BLM Arizona Surface Management Agency polygons, plus wilderness (Forest
    Service, BLM), BLM national monuments and conservation areas, and BLM areas
    of critical environmental concern. All fetched with read-only queries and
    cached in the system temp folder.

Outputs (tools/kitfox-review/, a local working folder that is not published)
  - candidates.geojson  circles for both lists, with their figures
  - shortlist.json      settings, study-area summary and the two ranked lists
  - suitability.png, land.png and overlays.json for the review map
  - study_area.geojson  the 100-mile circle and the center point
  - designations.geojson  wilderness, monuments and other designations

Run:  py tools/build_kitfox_shortlist.py
Needs numpy, scipy, pyogrio, geopandas, pyproj, Pillow and rasterio. rasterio is
looked for in <temp>/finkgeo_pydeps if it is not installed.
"""
import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import warnings

import numpy as np

try:
    import rasterio
except ImportError:
    sys.path.insert(0, os.path.join(tempfile.gettempdir(), "finkgeo_pydeps"))
    import rasterio
from affine import Affine
from rasterio import features
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy import ndimage, signal

import geopandas as gpd
from shapely.geometry import Point, shape as geom_from
import pyogrio
from PIL import Image
from pyproj import Transformer

warnings.filterwarnings("ignore", message="Measured")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "kitfox-review")
CONFIG = os.path.join(OUT, "project.json")


def load_config():
    """Where the ArcGIS Pro project is and what its layers are called. Kept in the git-ignored
    review folder so that nothing in the repo names the project."""
    if not os.path.exists(CONFIG):
        raise SystemExit(
            f"Missing {CONFIG}. Create it with three entries: \"project\" (folder of the ArcGIS Pro "
            "project), \"center_layer\" (the point the search starts from) and \"area_layer\" (the search-area circle).")
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
GDB = os.path.join(CFG["project"], "Default.gdb")
CACHE = os.path.join(tempfile.gettempdir(), "finkgeo_kitfox_cache")
SMA_URL = "https://gis.blm.gov/azarcgis/rest/services/lands/BLM_AZ_SMA/MapServer/0/query"
CRS = "EPSG:5070"
HIGH = 7.0  # the cutoff used for KitFox_HighSuitability in the project
BLOCK = 3   # 30 m cells averaged into 90 m cells

# code, label, LAND_MNGR values, colour for the review map, counts as open public land
MANAGERS = [
    (1, "Private or undetermined", {"PVT", "UND", "", None}, (200, 200, 200), False),
    (2, "BLM", {"BLM"}, (254, 230, 121), True),
    (3, "Forest Service", {"USFS"}, (158, 204, 142), True),
    (4, "National Park Service", {"NPS"}, (190, 160, 210), True),
    (5, "Fish and Wildlife Service", {"USFWS"}, (120, 200, 190), True),
    (6, "Tribal land", {"BIA"}, (253, 174, 107), False),
    (7, "State Trust or other state land", {"ST", "STL"}, (158, 202, 225), True),
    (8, "State park or wildlife area", {"STP", "STW"}, (107, 174, 214), True),
    (9, "Local government", {"LG"}, (252, 197, 192), True),
    (10, "Military", {"DOD", "USA", "USACE", "USAF", "USMC", "USN"}, (222, 119, 174), False),
    (11, "Bureau of Reclamation", {"BOR"}, (140, 150, 198), True),
    (12, "Other federal", {"BOP", "FAA", "OTHFE"}, (150, 150, 150), False),
]
CODE_OF = {m: code for code, _, names, _, _ in MANAGERS for m in names}
LABEL = {code: label for code, label, _, _, _ in MANAGERS}
LABEL[0] = "No ownership data"
PUBLIC = [code for code, _, _, _, ok in MANAGERS if ok]


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- suitability

def load_suitability():
    with rasterio.open(f'OpenFileGDB:"{GDB}":KitFox') as ds:
        s = ds.read(1)
        t = ds.transform
        assert ds.crs.to_epsg() == 5070, ds.crs
    valid = np.isfinite(s) & (s < 1e30)
    h = (s.shape[0] // BLOCK) * BLOCK
    w = (s.shape[1] // BLOCK) * BLOCK
    shp = (h // BLOCK, BLOCK, w // BLOCK, BLOCK)
    total = np.where(valid, s, 0)[:h, :w].astype(np.float64).reshape(shp).sum(axis=(1, 3))
    count = valid[:h, :w].reshape(shp).sum(axis=(1, 3)).astype(np.float64)
    high = (valid & (s >= HIGH))[:h, :w].reshape(shp).sum(axis=(1, 3)).astype(np.float64)
    hist_edges = np.arange(2.0, 10.01, 1.0)
    hist = np.histogram(s[valid], bins=hist_edges)[0]
    cell_km2 = abs(t.a * t.e) / 1e6
    bands = [{"from": float(a), "to": float(b), "km2": round(float(c) * cell_km2)}
             for a, b, c in zip(hist_edges[:-1], hist_edges[1:], hist)]
    grid_t = Affine(t.a * BLOCK, 0, t.c, 0, t.e * BLOCK, t.f)
    mean = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    return {
        "mean": mean, "count": count / BLOCK ** 2, "high": high / BLOCK ** 2, "transform": grid_t,
        "bands": bands, "study_km2": float(valid.sum()) * cell_km2,
        "high_km2": float((valid & (s >= HIGH)).sum()) * cell_km2,
    }


# ------------------------------------------------------------- land ownership

def fetch_layer(url, prefix, fields, bounds, order="OBJECTID", what="polygons"):
    """Read-only, paged query of a public ArcGIS layer, returned in the grid's projection. Cached."""
    os.makedirs(CACHE, exist_ok=True)
    env = {"xmin": bounds[0], "ymin": bounds[1], "xmax": bounds[2], "ymax": bounds[3],
           "spatialReference": {"wkid": 5070}}
    feats, offset, page = [], 0, 1000
    while True:
        path = os.path.join(CACHE, f"{prefix}_{offset}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                r = json.load(f)
        else:
            params = dict(where="1=1", geometry=json.dumps(env), geometryType="esriGeometryEnvelope",
                          inSR=5070, spatialRel="esriSpatialRelIntersects",
                          outFields=fields, outSR=5070, maxAllowableOffset=30,
                          geometryPrecision=0, orderByFields=order, resultOffset=offset,
                          resultRecordCount=page, f="geojson")
            for attempt in range(5):
                try:
                    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                                 headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=180) as resp:
                        r = json.loads(resp.read())
                    if "features" not in r:
                        raise RuntimeError(str(r)[:200])
                    break
                except Exception as e:  # noqa: BLE001
                    log(f"  page at {offset} failed ({e}); retrying")
                    time.sleep(5 * (attempt + 1))
            else:
                raise SystemExit(f"The query for {what} kept failing")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(r, f)
        got = r["features"]
        feats += got
        log(f"  {what}: {len(feats)}")
        if len(got) < page and not r.get("exceededTransferLimit"):
            break
        if not got:
            break
        offset += len(got)
    return feats


def fetch_sma(bounds):
    return fetch_layer(SMA_URL, "sma", "OBJECTID,LAND_MNGR,NATL_SYM", bounds, what="ownership polygons")


# --------------------------------------------------------------- designations

BLM_LANDS = "https://gis.blm.gov/arcgis/rest/services/lands/"
# kind, label, layer, name field, cache prefix, object id field, text added to the name
# The BLM layer gives these four by short name only
FULL_NAME = {"Sonoran Desert": "Sonoran Desert National Monument", "Ironwood Forest": "Ironwood Forest National Monument",
             "Agua Fria": "Agua Fria National Monument", "San Pedro Riparian": "San Pedro Riparian National Conservation Area"}
DESIGNATIONS = [
    ("wilderness", "Wilderness", "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_Wilderness_01/MapServer/0",
     "wildernessname", "wild_fs", "objectid", ""),
    ("wilderness", "Wilderness", BLM_LANDS + "BLM_Natl_NLCS_WLD_WSA/MapServer/0", "NLCS_NAME", "wild_blm", "OBJECTID", " Wilderness"),
    ("wsa", "Wilderness study area", BLM_LANDS + "BLM_Natl_NLCS_WLD_WSA/MapServer/1", "NLCS_NAME", "wsa_blm", "OBJECTID",
     " Wilderness Study Area"),
    ("monument", "National monument or conservation area", BLM_LANDS + "BLM_Natl_NLCS_NM_NCA_poly/MapServer/0",
     "NCA_NAME", "nm_nca_name", "OBJECTID", ""),
    ("acec", "Area of critical environmental concern", BLM_LANDS + "BLM_Natl_ACEC/MapServer/0", "ACEC_NAME", "acec", "OBJECTID", " ACEC"),
]


def load_designations(bounds):
    """Wilderness (Forest Service and BLM), BLM national monuments and conservation areas, and BLM
    areas of critical environmental concern. Park Service and Fish and Wildlife wilderness is not
    in these layers."""
    rows = []
    for kind, label, url, field, prefix, oid, suffix in DESIGNATIONS:
        for f in fetch_layer(url + "/query", prefix, f"{oid},{field}", bounds, order=oid, what=f"{prefix} polygons"):
            if not f.get("geometry"):
                continue
            name = " ".join(str(f["properties"].get(field) or "Unnamed").split())
            name = FULL_NAME.get(name, name)
            if suffix and not name.lower().endswith(suffix.strip().lower()):
                name += suffix
            rows.append({"kind": kind, "label": label, "name": name, "geometry": geom_from(f["geometry"])})
    g = gpd.GeoDataFrame(rows, crs=CRS)
    g["geometry"] = g.geometry.make_valid()
    return g.dissolve(by=["kind", "label", "name"]).reset_index()


def rasterize_sma(feats, shape, transform):
    def code(f):
        p = f["properties"]
        m = p.get("LAND_MNGR")
        m = m.strip() if isinstance(m, str) else m
        if m in CODE_OF and m not in ("", None):
            return CODE_OF[m]
        sym = (p.get("NATL_SYM") or "").strip()
        return {"PVT": 1, "BLM": 2, "USFS": 3, "NPS": 4, "USFWS": 5, "BIA": 6, "ST": 7, "LG": 9,
                "DOD": 10, "BOR": 11, "OF": 12}.get(sym, 1)

    shapes = [(f["geometry"], code(f)) for f in feats if f.get("geometry")]
    shapes.sort(key=lambda gc: gc[1] != 1)  # private first so mapped public land wins an overlap
    return features.rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="uint8")


def overlaps(desig, circle):
    """Designations that cover at least 1% of a candidate circle, largest share first."""
    out = []
    for d in desig[desig.intersects(circle)].itertuples():
        share = d.geometry.intersection(circle).area / circle.area
        if share >= 0.01:
            out.append({"kind": d.kind, "label": d.label, "name": d.name, "share": round(share, 3)})
    return sorted(out, key=lambda h: -h["share"])


# ---------------------------------------------------------------------- roads

def road_distance(shape, transform):
    """Metres from each cell to the nearest primary or secondary road (TIGER S1100, S1200)."""
    geoms = []
    for layer in ("PrimaryRoad_s1100_P", "secondary_s1200_P"):
        g = pyogrio.read_dataframe(GDB, layer=layer, columns=[]).to_crs(CRS)
        geoms += [geom for geom in g.geometry if geom is not None and not geom.is_empty]
    burned = features.rasterize(((g, 1) for g in geoms), out_shape=shape, transform=transform,
                                fill=0, dtype="uint8", all_touched=True)
    return ndimage.distance_transform_edt(burned == 0) * transform.a


# ---------------------------------------------------------------------- slope

def slope_grid(shape, transform):
    """The project's slope raster (degrees, 1 arc-second) averaged onto the 90 m grid. Cached."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"slope_{shape[0]}x{shape[1]}.npy")
    if os.path.exists(path):
        return np.load(path)
    out = np.full(shape, np.nan, dtype=np.float32)
    with rasterio.open(f'OpenFileGDB:"{GDB}":Slope_output1') as ds:
        reproject(rasterio.band(ds, 1), out, src_nodata=ds.nodata, dst_transform=transform, dst_crs=CRS,
                  dst_nodata=np.nan, resampling=Resampling.average)
    np.save(path, out)
    return out


# ---------------------------------------------------------------- focal stats

def disc(radius_m, cell):
    r = int(math.ceil(radius_m / cell))
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    return (((xx * cell) ** 2 + (yy * cell) ** 2) <= radius_m ** 2).astype(np.float64)


def focal_sum(a, k):
    return signal.fftconvolve(a, k, mode="same")


def pick(score, eligible, n, spacing_cells):
    """Best cell, then the best cell at least `spacing` away from every earlier pick, and so on."""
    work = np.where(eligible, score, -np.inf)
    yy, xx = np.ogrid[:work.shape[0], :work.shape[1]]
    out = []
    for _ in range(n):
        i = int(np.argmax(work))
        r, c = divmod(i, work.shape[1])
        if not np.isfinite(work[r, c]):
            break
        out.append((r, c))
        work[((yy - r) ** 2 + (xx - c) ** 2) <= spacing_cells ** 2] = -np.inf
    return out


# -------------------------------------------------------------------- overlays

VIRIDIS = [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]


def ramp(v, lo, hi):
    x = np.clip((v - lo) / (hi - lo), 0, 1) * (len(VIRIDIS) - 1)
    i = np.minimum(x.astype(int), len(VIRIDIS) - 2)
    f = (x - i)[..., None]
    stops = np.array(VIRIDIS, dtype=np.float64)
    return (stops[i] * (1 - f) + stops[i + 1] * f).astype(np.uint8)


def to_mercator(a, transform, nodata, resampling, res=200):
    left, top = transform.c, transform.f
    right = left + transform.a * a.shape[1]
    bottom = top + transform.e * a.shape[0]
    dt, dw, dh = calculate_default_transform(CRS, "EPSG:3857", a.shape[1], a.shape[0],
                                             left, bottom, right, top, resolution=res)
    dst = np.full((dh, dw), nodata, dtype=a.dtype)
    reproject(a, dst, src_transform=transform, src_crs=CRS, src_nodata=nodata,
              dst_transform=dt, dst_crs="EPSG:3857", dst_nodata=nodata, resampling=resampling)
    tr = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    w, n = tr.transform(dt.c, dt.f)
    e, s = tr.transform(dt.c + dt.a * dw, dt.f + dt.e * dh)
    return dst, [[s, w], [n, e]]


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--radius-km", type=float, default=3.0, help="radius of a candidate area")
    ap.add_argument("--spacing-km", type=float, default=10.0, help="least distance between two candidates")
    ap.add_argument("--top", type=int, default=15, help="candidates per list")
    ap.add_argument("--min-public", type=float, default=0.9,
                    help="screened list: least share of the area on open public land")
    ap.add_argument("--road-gap-km", type=float, default=1.0,
                    help="screened list: least gap between the edge of the area and a primary or secondary road")
    ap.add_argument("--max-slope", type=float, default=5.0,
                    help="screened list: greatest average slope of the area, in degrees")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    log("Reading the suitability surface")
    S = load_suitability()
    T, shape = S["transform"], S["mean"].shape
    cell = T.a
    cell_km2 = cell * cell / 1e6
    bounds = (T.c, T.f + T.e * shape[0], T.c + T.a * shape[1], T.f)
    valid = S["count"]                      # share of each 90 m cell that has a score
    mean0 = np.nan_to_num(S["mean"])

    log("Fetching land ownership (BLM Arizona surface management)")
    land = rasterize_sma(fetch_sma(bounds), shape, T)

    log("Fetching wilderness and other designations")
    desig = load_designations(bounds)

    log("Measuring distance to primary and secondary roads")
    road_m = road_distance(shape, T)

    log("Averaging the project's slope raster onto the grid")
    slope = slope_grid(shape, T)
    has_slope = np.isfinite(slope).astype(np.float64)

    log("Averaging over candidate circles")
    k = disc(a.radius_km * 1000, cell)
    n_valid = focal_sum(valid, k)
    cover = n_valid / k.sum()
    n_slope = focal_sum(has_slope, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        f_mean = np.where(n_valid > 0.5, focal_sum(mean0 * valid, k) / n_valid, np.nan)
        f_high = np.where(n_valid > 0.5, focal_sum(S["high"], k) / n_valid, np.nan)
        f_slope = np.where(n_slope > 0.5 * k.sum(), focal_sum(np.nan_to_num(slope).astype(np.float64), k) / n_slope, np.nan)
    share = {c: np.clip(focal_sum((land == c).astype(np.float64), k) / k.sum(), 0, 1) for c in LABEL}
    public = sum(share[c] for c in PUBLIC)

    whole = cover >= 0.999                  # the circle lies wholly inside the scored study area
    spacing = a.spacing_km * 1000 / cell
    screen = (whole & (public >= a.min_public) & (road_m >= (a.radius_km + a.road_gap_km) * 1000)
              & (f_slope <= a.max_slope))
    lists = {
        "score": pick(f_mean, whole, a.top, spacing),
        "screened": pick(f_mean, screen, a.top, spacing),
    }

    center = gpd.read_file(GDB, layer=CFG["center_layer"]).to_crs(CRS).geometry.iloc[0]
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    feats, tables = [], {}
    for name, picks in lists.items():
        rows = []
        for rank, (r, c) in enumerate(picks, 1):
            x, y = T * (c + 0.5, r + 0.5)
            lon, lat = to_ll.transform(x, y)
            mix = sorted(((float(share[code][r, c]), LABEL[code]) for code in LABEL), reverse=True)
            props = {
                "list": name, "rank": rank, "lat": round(lat, 4), "lon": round(lon, 4),
                "mean_score": round(float(f_mean[r, c]), 2),
                "high_share": round(float(f_high[r, c]), 3),
                "public_share": round(float(public[r, c]), 3),
                "manager": mix[0][1], "manager_share": round(mix[0][0], 3),
                "managers": [{"name": n, "share": round(s, 3)} for s, n in mix if s >= 0.005],
                "designations": overlaps(desig, Point(x, y).buffer(a.radius_km * 1000, 32)),
                "road_km": round(float(road_m[r, c]) / 1000, 1),
                "slope_deg": None if not np.isfinite(f_slope[r, c]) else round(float(f_slope[r, c]), 1),
                "center_km": round(math.hypot(x - center.x, y - center.y) / 1000, 1),
                "area_km2": round(float(k.sum()) * cell_km2, 1),
            }
            rows.append(props)
            ring = [to_ll.transform(x + a.radius_km * 1000 * math.cos(t), y + a.radius_km * 1000 * math.sin(t))
                    for t in np.linspace(0, 2 * math.pi, 73)]
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": "Polygon", "coordinates": [[[round(px, 5), round(py, 5)] for px, py in ring]]}})
        tables[name] = rows

    # study-area summary: who manages the high-suitability land
    scored = valid > 0
    high_km2 = S["high"] * cell_km2
    by_manager = []
    for code in LABEL:
        m = (land == code) & scored
        by_manager.append({"name": LABEL[code], "km2": round(float((valid * m).sum()) * cell_km2),
                           "high_km2": round(float(high_km2[m].sum()))})
    by_manager.sort(key=lambda d: -d["high_km2"])

    designated = []
    for (kind, label), part in desig.groupby(["kind", "label"]):
        m = features.rasterize(((g, 1) for g in part.geometry), out_shape=shape, transform=T, fill=0, dtype="uint8").astype(bool) & scored
        designated.append({"kind": kind, "label": label, "areas": int(len(part)),
                           "km2": round(float((valid * m).sum()) * cell_km2), "high_km2": round(float(high_km2[m].sum()))})
    designated.sort(key=lambda d: -d["high_km2"])

    summary = {
        "built": time.strftime("%Y-%m-%d"),
        "settings": {"radius_km": a.radius_km, "spacing_km": a.spacing_km, "top": a.top,
                     "min_public": a.min_public, "road_gap_km": a.road_gap_km,
                     "max_slope_deg": a.max_slope, "high_cutoff": HIGH,
                     "grid_m": cell, "public_managers": [LABEL[c] for c in PUBLIC]},
        "study_km2": round(S["study_km2"]), "high_km2": round(S["high_km2"]),
        "score_bands": S["bands"], "by_manager": by_manager, "designated": designated,
        "eligible_km2": {
            "whole_circle": round(float(whole.sum()) * cell_km2),
            "screened": round(float(screen.sum()) * cell_km2)},
        "lists": tables,
    }
    with open(os.path.join(OUT, "shortlist.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    with open(os.path.join(OUT, "candidates.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)

    log("Writing review-map overlays")
    score = np.where(scored, S["mean"], -1).astype(np.float32)
    m, b1 = to_mercator(score, T, -1, Resampling.average)
    rgba = np.zeros(m.shape + (4,), np.uint8)
    rgba[..., :3] = ramp(m, 3, 9)
    rgba[..., 3] = np.where(m > 0, 255, 0)
    Image.fromarray(rgba).save(os.path.join(OUT, "suitability.png"), optimize=True)
    lm, b2 = to_mercator(np.where(scored, land, 255).astype(np.uint8), T, 255, Resampling.nearest)
    pal = np.zeros((256, 4), np.uint8)
    for code, _, _, rgb, _ in MANAGERS:
        pal[code] = (*rgb, 255)
    Image.fromarray(pal[lm]).save(os.path.join(OUT, "land.png"), optimize=True)
    with open(os.path.join(OUT, "overlays.json"), "w", encoding="utf-8") as f:
        json.dump({"suitability": {"bounds": b1, "min": 3, "max": 9, "ramp": VIRIDIS},
                   "land": {"bounds": b2, "legend": [{"name": l, "rgb": rgb} for _, l, _, rgb, _ in MANAGERS]}}, f)

    dz = desig.to_crs("EPSG:4326")
    dz["geometry"] = dz.geometry.simplify(0.0003)
    dz.to_file(os.path.join(OUT, "designations.geojson"), driver="GeoJSON")

    area = gpd.read_file(GDB, layer=CFG["area_layer"]).to_crs("EPSG:4326")
    area["geometry"] = area.geometry.simplify(0.002)
    pt = gpd.read_file(GDB, layer=CFG["center_layer"]).to_crs("EPSG:4326")
    study = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"kind": "study_area"}, "geometry": area.geometry.iloc[0].__geo_interface__},
        {"type": "Feature", "properties": {"kind": "center"}, "geometry": pt.geometry.iloc[0].__geo_interface__}]}
    with open(os.path.join(OUT, "study_area.geojson"), "w", encoding="utf-8") as f:
        json.dump(study, f)

    log(f"\nStudy area {summary['study_km2']:,} km2; score {HIGH:g}+ on {summary['high_km2']:,} km2")
    log("High-suitability land by manager:")
    for d in by_manager:
        if d["high_km2"]:
            log(f"  {d['name']:34s}{d['high_km2']:>8,} km2  ({d['high_km2'] / summary['high_km2']:.0%})")
    for name, rows in tables.items():
        log(f"\n{name.upper()} list ({len(rows)})")
        log("  #   lat       lon        score  7+    public  road km  slope  ctr km   manager")
        for p in rows:
            log(f"  {p['rank']:<3d} {p['lat']:<9} {p['lon']:<10} {p['mean_score']:<6} {p['high_share']:<5.0%} "
                f"{p['public_share']:<7.0%} {p['road_km']:<8} {str(p['slope_deg']):<6} {p['center_km']:<8} "
                f"{p['manager']} {p['manager_share']:.0%}"
                + "".join(f"; {d['name']} {d['share']:.0%}" for d in p["designations"]))
    log("\nDesignated land in the search area:")
    for d in designated:
        log(f"  {d['label']:42s}{d['areas']:>3} areas {d['km2']:>7,} km2, of which {d['high_km2']:>6,} km2 scores {HIGH:g}+")


if __name__ == "__main__":
    main()
