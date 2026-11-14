"""Step 10b: build an ArcGIS Pro project and export slide-sized map layouts.

Runs in ArcGIS Pro's Python:

  <Pro python> tools/canopy/18_layouts.py

Everything is made by script, so the layouts can be rebuilt after any change
upstream: the project file, the maps, their symbology, the layouts and the
exports. It starts from the blank project that ships with ArcGIS Pro.

Writes
  tucson-canopy/work/tucson_canopy.aprx     the project (open it in Pro to
                                            restyle or re-export by hand)
  tucson-canopy/downloads/*.pdf, *.png      16:9 layouts for slides
and adds a few display layers to each geodatabase (show_cover, show_canopy,
show_shade_s0, show_shade_s1, tree_crowns), which are the analysis layers
cut to the boundary with empty cells left empty so they draw cleanly.

Layouts
  1 Land cover, both neighborhoods at one scale
  2 Tree canopy in the candidate neighborhood, today and with street trees
  3 Shade at 4 p.m. on 15 July, today and with street trees
  4 Tree canopy in the reference neighborhood, today and with street trees
"""
import json
import os
from pathlib import Path

import arcpy
import numpy as np

from common import BUFFER, EPSG, PROJECT, WORK, site_dir, sites, work_bbox

CELL = 0.5
PAGE_W, PAGE_H = 13.333, 7.5            # inches, a 16:9 slide
SCALE = 8000
FONT = "Arial"
OUT = PROJECT / "downloads"
APRX = WORK / "tucson_canopy.aprx"
SR = arcpy.SpatialReference(EPSG)
SPECIES = json.loads((PROJECT / "species.json").read_text(encoding="utf-8"))["species"]
COVER = [(1, "Tree canopy", (0, 131, 0)), (2, "Roof", (98, 80, 214)),
         (3, "Pavement", (107, 107, 102)), (4, "Open ground", (237, 161, 0)),
         (6, "Water", (42, 120, 214))]
CANOPY = (27, 175, 122)
SHADE = (16, 66, 129)
OUTLINE = (None, "Neighborhood boundary")


def rgb(c, alpha=100):
    return {"RGB": [c[0], c[1], c[2], alpha]}


def rect(x0, y0, x1, y1):
    return arcpy.Polygon(arcpy.Array([arcpy.Point(x0, y0), arcpy.Point(x0, y1),
                                      arcpy.Point(x1, y1), arcpy.Point(x1, y0)]))


def blank_project():
    install = arcpy.GetInstallInfo()["InstallDir"]
    for root, _, files in os.walk(os.path.join(install, "Resources")):
        if "Blank.aprx" in files:
            return os.path.join(root, "Blank.aprx")
    raise SystemExit("No blank project found in the ArcGIS Pro install")


def display_layers(site):
    """Boundary-clipped copies of the analysis rasters, empty where there is
    nothing to draw, plus crown polygons for the proposed trees."""
    d = site_dir(site)
    gdb = str(d / f"{site['id']}.gdb")
    x0, y0, x1, y1 = work_bbox(site)
    ll = arcpy.Point(x0, y0)
    rows, cols = round((y1 - y0) / CELL), round((x1 - x0) / CELL)
    grab = lambda p: arcpy.RasterToNumPyArray(p, ll, cols, rows, nodata_to_value=0)
    inside = grab(str(d / "tmp" / "inside.tif")) > 0
    lc = grab(f"{gdb}/land_cover")

    def put(arr, name, names=None):
        r = arcpy.NumPyArrayToRaster(arr.astype(np.uint8), ll, CELL, CELL, 0)
        arcpy.management.CopyRaster(r, f"{gdb}/{name}", nodata_value="0",
                                    pixel_type="8_BIT_UNSIGNED")
        arcpy.management.DefineProjection(f"{gdb}/{name}", SR)
        arcpy.management.BuildRasterAttributeTable(f"{gdb}/{name}", "Overwrite")
        if names:
            arcpy.management.AddField(f"{gdb}/{name}", "Class_name", "TEXT", field_length=40)
            with arcpy.da.UpdateCursor(f"{gdb}/{name}", ["Value", "Class_name"]) as cur:
                for v, _ in cur:
                    cur.updateRow((v, names[int(v)]))

    merged = np.where(lc == 5, 4, lc)
    put(np.where(inside, merged, 0), "show_cover", {k: n for k, n, _ in COVER})
    put(np.where(inside & (lc == 1), 1, 0), "show_canopy", {1: "Tree canopy today"})
    for n in (0, 1):
        sh = grab(f"{gdb}/shade_s{n}") == 1
        put(np.where(inside & sh & (lc != 2), 1, 0), f"show_shade_s{n}",
            {1: "Ground in shade"})

    crowns = f"{gdb}/tree_crowns"
    if arcpy.Exists(crowns):
        arcpy.management.Delete(crowns)
    arcpy.management.MakeFeatureLayer(f"{gdb}/trees", "inb", "InBoundary = 1")
    arcpy.management.CopyFeatures("inb", "memory/pts")
    arcpy.management.Delete("inb")
    arcpy.management.AddField("memory/pts", "Radius", "TEXT", field_length=20)
    with arcpy.da.UpdateCursor("memory/pts", ["Crown_m", "Radius"]) as cur:
        for crown, _ in cur:
            cur.updateRow((crown, f"{crown / 2:.2f} Meters"))
    arcpy.analysis.Buffer("memory/pts", crowns, "Radius")
    arcpy.management.Delete("memory/pts")
    return gdb


def style_raster(lyr, colours):
    """Unique-value colours for a raster with a Class_name field."""
    sym = lyr.symbology
    sym.updateColorizer("RasterUniqueValueColorizer")
    sym.colorizer.field = "Class_name"
    lyr.symbology = sym
    sym = lyr.symbology
    for grp in sym.colorizer.groups:
        for item in grp.items:
            if item.label in colours:
                item.color = rgb(colours[item.label])
    lyr.symbology = sym


def style_crowns(lyr):
    sym = lyr.symbology
    sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = ["Species"]
    lyr.symbology = sym
    sym = lyr.symbology
    look = {s["common"]: tuple(s["colour"]) for s in SPECIES}
    for grp in sym.renderer.groups:
        for item in grp.items:
            item.symbol.color = rgb(look[item.label])
            item.symbol.outlineColor = rgb((255, 255, 255))
            item.symbol.outlineWidth = 0.3
    lyr.symbology = sym


def style_boundary(lyr):
    sym = lyr.symbology
    sym.renderer.symbol.color = rgb((0, 0, 0), 0)
    sym.renderer.symbol.outlineColor = rgb((0, 0, 0))
    sym.renderer.symbol.outlineWidth = 1.6
    lyr.symbology = sym


def make_map(aprx, name, gdb, layers):
    """layers: list of (dataset, layer name, styler, definition query)."""
    m = aprx.createMap(name)
    m.spatialReference = SR
    for lyr in m.listLayers():          # a new map arrives with Esri's basemap
        m.removeLayer(lyr)
    photo = m.addDataFromPath(f"{gdb}/naip_2023")
    photo.name = "Aerial photo, 2023"
    photo.transparency = 50
    for dataset, title, styler, query in layers:
        lyr = m.addDataFromPath(f"{gdb}/{dataset}")
        lyr.name = title
        if query:
            lyr.definitionQuery = query
        if styler:
            styler(lyr)
    b = m.addDataFromPath(f"{gdb}/boundary")
    b.name = "Neighborhood boundary"
    style_boundary(b)
    return m


def text(aprx, lyt, x, y, words, size, style="Regular", name=None):
    t = aprx.createTextElement(lyt, arcpy.Point(x, y), "POINT", words, size, FONT, style,
                               None, name)
    t.elementPositionX, t.elementPositionY = x, y
    return t


def box(aprx, lyt, x, y, w, h, fill, stroke, stroke_width):
    """A rectangle on the page. fill None leaves it hollow."""
    g = aprx.createGraphicElement(lyt, rect(x, y, x + w, y + h))
    cim = g.getDefinition("V3")
    for layer in cim.graphic.symbol.symbol.symbolLayers:
        kind = type(layer).__name__
        if kind == "CIMSolidFill":
            c = fill if fill is not None else (255, 255, 255)
            layer.color.values = [c[0], c[1], c[2], 0 if fill is None else 100]
        elif kind == "CIMSolidStroke":
            layer.color.values = [stroke[0], stroke[1], stroke[2], 100]
            layer.width = stroke_width
    g.setDefinition(cim)
    return g


def make_layout(aprx, name, title, subtitle, panels, legend, note):
    """panels: two (map, heading, site) tuples, drawn left and right.
    legend: (fill colour or None for an outline, label) pairs."""
    lyt = aprx.createLayout(PAGE_W, PAGE_H, "INCH", name)
    text(aprx, lyt, 0.45, PAGE_H - 0.62, title, 24, "Bold")
    text(aprx, lyt, 0.45, PAGE_H - 0.98, subtitle, 12.5)
    top, bottom, gap, left = PAGE_H - 1.55, 0.72, 0.25, 0.45
    width = (PAGE_W - 2.75 - left - gap) / 2          # room on the right for the legend
    # never wider or taller than the photo underneath, or the frame shows white
    data_w = min(site["bbox_utm12n"][2] - site["bbox_utm12n"][0] + 2 * BUFFER for _, _, site in panels)
    data_h = min(site["bbox_utm12n"][3] - site["bbox_utm12n"][1] + 2 * BUFFER for _, _, site in panels)
    width = min(width, data_w * 0.985 / SCALE / 0.0254)
    bottom = max(bottom, top - data_h * 0.985 / SCALE / 0.0254)
    frames = []
    for i, (m, heading, site) in enumerate(panels):
        x0 = left + i * (width + gap)
        text(aprx, lyt, x0, top + 0.08, heading, 13, "Bold")
        mf = lyt.createMapFrame(rect(x0, bottom, x0 + width, top), m, f"{name} frame {i + 1}")
        bx0, by0, bx1, by1 = site["bbox_utm12n"]
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        half_w = width * 0.0254 * SCALE / 2
        half_h = (top - bottom) * 0.0254 * SCALE / 2
        mf.camera.setExtent(arcpy.Extent(cx - half_w, cy - half_h, cx + half_w, cy + half_h))
        mf.camera.scale = SCALE
        frames.append(mf)
    lx = left + 2 * width + gap + 0.3
    y = top - 0.05
    text(aprx, lyt, lx, y - 0.05, "Legend", 11, "Bold")
    y -= 0.42
    for fill, label in legend:
        box(aprx, lyt, lx, y, 0.2, 0.2, fill, (0, 0, 0), 1.6 if fill is None else 0.5)
        text(aprx, lyt, lx + 0.3, y + 0.035, label, 10.5)
        y -= 0.32
    text(aprx, lyt, lx, y - 0.02, "Over the 2023 aerial photo,", 8.5)
    text(aprx, lyt, lx, y - 0.19, "faded.", 8.5)

    # scale bar: 200 m at the map scale, drawn to length
    bar_in = 200 / SCALE / 0.0254
    box(aprx, lyt, lx, 1.42, bar_in, 0.06, (0, 0, 0), (0, 0, 0), 0.5)
    text(aprx, lyt, lx, 1.55, "0", 9)
    text(aprx, lyt, lx + bar_in - 0.18, 1.55, "200 m", 9)
    arrow = aprx.listStyleItems("ArcGIS 2D", "NORTH_ARROW", "ArcGIS North 1")
    na = lyt.createMapSurroundElement(arcpy.Point(lx + 1.75, 1.42), "NORTH_ARROW", frames[0],
                                      arrow[0] if arrow else None, f"{name} north")
    na.elementHeight = 0.5
    na.elementPositionX, na.elementPositionY = lx + 1.75, 1.36
    text(aprx, lyt, lx, 1.12, f"Both maps 1:{SCALE:,}", 9)
    text(aprx, lyt, 0.45, 0.42, note, 8.5)
    text(aprx, lyt, 0.45, 0.22,
         "Lidar: USGS 3DEP, autumn 2021. Imagery: USDA NAIP, 18 October 2023. "
         "Boundaries: City of Tucson. finkgeo.com/tucson-canopy", 8.5)
    return lyt


def main():
    arcpy.env.overwriteOutput = True
    arcpy.CheckOutExtension("Spatial")
    OUT.mkdir(exist_ok=True)
    if APRX.exists():
        APRX.unlink()
    arcpy.mp.ArcGISProject(blank_project()).saveACopy(str(APRX))
    aprx = arcpy.mp.ArcGISProject(str(APRX))

    all_sites = sites()
    gdbs = {s["id"]: display_layers(s) for s in all_sites}
    ref = [s for s in all_sites if s["role"] == "reference"][0]
    cand = [s for s in all_sites if s["role"] == "candidate"][0]
    cover = lambda l: style_raster(l, {n: c for _, n, c in COVER})
    canopy = lambda l: style_raster(l, {"Tree canopy today": CANOPY})
    shade = lambda l: style_raster(l, {"Ground in shade": SHADE})
    acc = json.loads((WORK / "accuracy" / "accuracy.json").read_text())["sites"]["both sites"]
    scen = {s["id"]: json.loads((site_dir(s) / "scenarios.json").read_text()) for s in all_sites}
    shd = {s["id"]: json.loads((site_dir(s) / "shade.json").read_text()) for s in all_sites}

    layouts = []
    maps = {s["id"]: make_map(aprx, f"Land cover, {s['name']}", gdbs[s["id"]],
                              [("show_cover", "Land cover", cover, None)]) for s in all_sites}
    layouts.append(("1_land_cover", make_layout(
        aprx, "Land cover", "Land cover from lidar and aerial imagery",
        "Trees and roofs come from lidar structure; a Random Trees classifier sorts the ground.",
        [(maps[ref["id"]], ref["name"], ref), (maps[cand["id"]], cand["name"], cand)],
        [(c, n) for _, n, c in COVER] + [OUTLINE],
        f"Checked against {acc['all classes']['points']} hand-labelled points: tree canopy or "
        f"not {acc['tree canopy or not']['overall_accuracy']:.0%} right, roof or pavement or not "
        f"{acc['impervious or not']['overall_accuracy']:.0%}, five classes "
        f"{acc['open ground merged']['overall_accuracy']:.0%}. Open ground is bare ground and low plants together.")))

    def canopy_pair(site, n):
        g = gdbs[site["id"]]
        today = make_map(aprx, f"Canopy today, {site['name']}", g,
                         [("show_canopy", "Tree canopy today", canopy, None)])
        planted = make_map(aprx, f"Canopy with street trees, {site['name']}", g,
                           [("show_canopy", "Tree canopy today", canopy, None),
                            ("tree_crowns", "Proposed street trees", style_crowns, "Scenario = 1")])
        sc = scen[site["id"]]
        st = sc["scenarios"]["Street trees"]
        return (f"{n}_canopy_{site['id']}", make_layout(
            aprx, f"Canopy, {site['name']}", f"Tree canopy in {site['name']}, today and with street trees",
            f"{st['trees']:,} native trees in the strip beside the street, drawn at mature size.",
            [(today, f"Today: {sc['existing']['canopy_pct']}% canopy", site),
             (planted, f"With street trees: {st['canopy_pct']}% canopy", site)],
            [(CANOPY, "Tree canopy today")] +
            [(tuple(sp["colour"]), sp["common"]) for sp in SPECIES] + [OUTLINE],
            "A planning sketch, not a planting plan: no check of buried utilities, ownership or "
            "irrigation. Tree sizes are published mature sizes."))

    layouts.append(canopy_pair(cand, 2))
    g = gdbs[cand["id"]]
    s0 = make_map(aprx, f"Shade today, {cand['name']}", g,
                  [("show_shade_s0", "Ground in shade", shade, None)])
    s1 = make_map(aprx, f"Shade with street trees, {cand['name']}", g,
                  [("show_shade_s1", "Ground in shade", shade, None)])
    sh = shd[cand["id"]]["scenarios"]
    layouts.append(("3_shade_" + cand["id"], make_layout(
        aprx, f"Shade, {cand['name']}", f"Shade in {cand['name']} at 4 p.m. on 15 July",
        "Shadows cast from tree crowns and roofs with the sun 42 degrees up, due west. Roofs are left clear.",
        [(s0, f"Today: {sh['Today']['street edge']:.0f}% of the street edge shaded", cand),
         (s1, f"With street trees: {sh['Street trees']['street edge']:.0f}% shaded", cand)],
        [(SHADE, "Ground in shade"), OUTLINE],
        "Trees are treated as solid, so this shows where shade falls, not how deep it is. "
        "Street edge is the 2 m beside the pavement on both sides.")))
    layouts.append(canopy_pair(ref, 4))

    aprx.save()
    for stem, lyt in layouts:
        lyt.exportToPDF(str(OUT / f"{stem}.pdf"), resolution=200, image_compression="JPEG",
                        jpeg_compression_quality=85)
        lyt.exportToPNG(str(OUT / f"{stem}.png"), resolution=144, color_mode="24-BIT_TRUE_COLOR")
        print("exported", stem, flush=True)
    aprx.save()


if __name__ == "__main__":
    main()
