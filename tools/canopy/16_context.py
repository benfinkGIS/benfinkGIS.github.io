"""Step 4: landscape context and how well the canopy hangs together.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/16_context.py [site_id ...]

Context, from the county layers already in each geodatabase:
  washes      named washes in or within 1 km of the neighborhood, with distance
              and the county's flow class
  riparian    mapped riparian habitat (Pima County's riparian classification)
              within 1 km: nearest distance and area by class
  parks       parks, greenways and school grounds within 1 km

Canopy structure, today and under each scenario, inside the boundary:
  distance to canopy   from every spot that is not a roof to the nearest tree
                       crown: the mean, and the share within 5 m
  patches              separate canopy patches of at least 4 m2
  linked canopy        crowns no more than 10 m apart are treated as one
                       cluster. Reported: the share of the neighborhood's
                       canopy in its largest cluster, and the share in
                       clusters that reach mapped riparian habitat

The 10 m gap is a round number for illustration. It is not a measured
crossing distance for any animal, and the result should be read as "how
broken up is the canopy", not as habitat for a named species.

Writes context.json beside each site's geodatabase.
"""
import json
import re
import sys

import arcpy
import numpy as np
from scipy import ndimage

from common import EPSG, site_dir, sites, work_bbox

CELL = 0.5
REACH_M = 1000
NEAR_M = 5
GAP_M = 10
PATCH_MIN_M2 = 4
KEEP_UPPER = {"Tcc": "TCC", "Ii": "II", "And": "and"}
SCENARIOS = {0: "Today", 1: "Street trees", 2: "Streets and homes", 3: "Full build-out"}


def tidy(name):
    """County names are in capitals. Title-case them without breaking
    ordinals (18TH) or the few initialisms that turn up."""
    out = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), name.title())
    return " ".join(KEEP_UPPER.get(w, w) for w in out.split())


def nearby(gdb, layer, boundary, fields, measure):
    """Features of a layer within REACH_M of the boundary, nearest first."""
    path = f"{gdb}/{layer}"
    out = []
    if not arcpy.Exists(path):
        return out
    for row in arcpy.da.SearchCursor(path, ["SHAPE@"] + fields):
        d = boundary.distanceTo(row[0])
        if d <= REACH_M:
            out.append((round(d), getattr(row[0], measure), *row[1:]))
    return sorted(out, key=lambda r: r[0])


def build(site):
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    tmp = d / "tmp"
    x0, y0, x1, y1 = work_bbox(site)
    ll = arcpy.Point(x0, y0)
    rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
    arcpy.env.overwriteOutput = True
    arcpy.env.extent = arcpy.Extent(x0, y0, x1, y1)
    arcpy.env.cellSize = CELL
    arcpy.env.snapRaster = f"{gdb}/chm"
    arcpy.env.outputCoordinateSystem = arcpy.SpatialReference(EPSG)
    grab = lambda p: arcpy.RasterToNumPyArray(p, ll, cols, rows, nodata_to_value=0)
    boundary = [r[0] for r in arcpy.da.SearchCursor(f"{gdb}/boundary", ["SHAPE@"])][0]

    # ---- context ----
    washes = {}
    for dist, length, name, flow in nearby(gdb, "washes", boundary,
                                           ["WASHNAME", "CFS_SHORT2"], "length"):
        if not name or name.upper() == "UNKNOWN":
            continue
        w = washes.setdefault(tidy(name), dict(distance_m=dist, flow=flow, length_m=0))
        w["length_m"] += round(length)
    rip = nearby(gdb, "riparian", boundary, ["CLASS"], "area")
    rip_by = {}
    for dist, area, cls in rip:
        rip_by[cls] = round(rip_by.get(cls, 0) + area / 1e4, 1)
    parks = {}
    for dist, area, name, kind in nearby(gdb, "parks", boundary, ["NAME", "PARK_TYPE"], "area"):
        if name and tidy(name) not in parks:
            parks[tidy(name)] = dict(distance_m=dist, kind=(kind or "").title(),
                                       ha=round(area / 1e4, 1))
    context = dict(
        washes=[dict(name=k, **v) for k, v in washes.items()],
        unnamed_washes_within_1km=sum(
            1 for r in nearby(gdb, "washes", boundary, ["WASHNAME"], "length")
            if not r[2] or r[2].upper() == "UNKNOWN"),
        riparian=dict(nearest_m=rip[0][0] if rip else None,
                      nearest_class=rip[0][2] if rip else None, ha_by_class=rip_by,
                      total_ha=round(sum(rip_by.values()), 1)),
        parks=[dict(name=k, **v) for k, v in parks.items()])

    # ---- canopy structure ----
    lc = grab(f"{gdb}/land_cover")
    inside = grab(str(tmp / "inside.tif")) > 0
    ground = inside & (lc != 2)
    riparian = np.zeros(lc.shape, bool)
    if arcpy.Exists(f"{gdb}/riparian"):
        arcpy.conversion.PolygonToRaster(f"{gdb}/riparian", "OBJECTID",
                                         str(tmp / "riparian.tif"), cellsize=CELL)
        riparian = grab(str(tmp / "riparian.tif")) > 0
    structure = {}
    for s, name in SCENARIOS.items():
        canopy = (lc == 1) if s == 0 else grab(f"{gdb}/canopy_s{s}") == 1
        away = ndimage.distance_transform_edt(~canopy) * CELL
        lab, n = ndimage.label(canopy & inside, structure=np.ones((3, 3)))
        sizes = np.bincount(lab.ravel())[1:] * CELL * CELL
        big = sizes[sizes >= PATCH_MIN_M2]
        # crowns within GAP_M of each other form one cluster
        cl, _ = ndimage.label(away <= GAP_M / 2, structure=np.ones((3, 3)))
        mine = canopy & inside
        counts = np.bincount(cl[mine], minlength=int(cl.max()) + 1)
        counts[0] = 0
        touching = np.unique(cl[riparian & (cl > 0)])
        linked = float(counts[touching].sum() / max(mine.sum(), 1)) if riparian.any() else None
        structure[name] = dict(
            mean_distance_to_canopy_m=round(float(away[ground].mean()), 1),
            within_5m_pct=round(float((away[ground] <= NEAR_M).mean() * 100), 1),
            patches=int(big.size),
            median_patch_m2=round(float(np.median(big)), 1) if big.size else None,
            largest_patch_m2=round(float(big.max())) if big.size else None,
            largest_cluster_share=round(float(counts.max() / max(mine.sum(), 1)), 2),
            linked_to_riparian_share=None if linked is None else round(linked, 2))
    out = dict(site=site["id"], context=context, structure=structure,
               riparian_in_work_area=bool(riparian.any()),
               rules=dict(reach_m=REACH_M, near_m=NEAR_M, gap_m=GAP_M,
                          patch_min_m2=PATCH_MIN_M2))
    (d / "context.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1), flush=True)


def main():
    arcpy.CheckOutExtension("Spatial")
    for s in sites(sys.argv[1:]):
        build(s)


if __name__ == "__main__":
    main()
