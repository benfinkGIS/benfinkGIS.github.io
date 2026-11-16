"""Build the Lake Powell scene in Blender and render stills at chosen water levels.

Run headless (after 07_build_terrain.py):

  blender -b --factory-startup -P tools/powell/08_blender_scene.py -- [options]

  --view NAME      lake  = the whole reservoir from the south (default)
                   dam   = the lower lake from above Glen Canyon Dam, looking up-lake
                   top   = straight down, north up
  --level-ft F     water surface in feet, Reclamation's datum (default 3700, full pool)
  --levels FILE    CSV with columns label,elevation_ft: render one still per row
                   from the same scene (used for the yearly slider frames)
  --draft          quick look: every third cell, 1280 px wide, fewer samples
  --step N         use every Nth 30 m cell (default 1, draft 3)
  --exag F         vertical exaggeration (default 2.5)
  --sun-az DEG     compass direction the sun is in (default 235)
  --sun-el DEG     sun height above the horizon (default 28)
  --exposure EV    film exposure in stops (default: set from the sun height)
  --size WxH       picture size (default 1920x1080, draft 1280x720)
  --out NAME       file name inside lake-powell/work/renders/ (single still)
  --no-render      build and save the .blend only

Saves lake-powell/work/blender/powell.blend (the last scene built). One Blender
unit is 1 km. The origin is the frame's south-west corner, +X east, +Y north.
Ground between the water and the full pool line, inside the reservoir, is
drawn pale: the "bathtub ring".
"""
import csv
import json
import math
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BLENDER, FULL_POOL_FT, PROCESSED, RENDERS, reclamation_ft_to_dem_m  # noqa: E402

K = 0.001             # metres -> Blender units (km)
SLAB_M = 600.0        # thickness of the block under the lowest ground
FLOOR_COLOR = (0.012, 0.013, 0.015)
SIDE_COLOR = (0.050, 0.036, 0.028)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(flag, default=None, kind=str):
    return kind(argv[argv.index(flag) + 1]) if flag in argv else default


DRAFT = "--draft" in argv
VIEW = arg("--view", "lake")
STEP = arg("--step", 3 if DRAFT else 1, int)
Z_EXAG = arg("--exag", 2.5, float)
SUN_AZ = arg("--sun-az", 235.0, float)
SUN_EL = arg("--sun-el", 28.0, float)
EXPOSURE = arg("--exposure", float(np.interp(SUN_EL, [4, 9, 20, 38, 70], [-3.0, -3.8, -4.6, -5.3, -5.7])), float)
LEVEL_FT = arg("--level-ft", FULL_POOL_FT, float)
LEVELS_FILE = arg("--levels")
SIZE = tuple(int(v) for v in arg("--size", "1280x720" if DRAFT else "1920x1080").split("x"))
SAMPLES = arg("--samples", 48 if DRAFT else 160, int)
OUT_NAME = arg("--out", f"{VIEW}_{LEVEL_FT:.0f}ft{'_draft' if DRAFT else ''}.png")

S = json.loads((PROCESSED / "terrain.json").read_text(encoding="utf-8"))
CELL = S["cell_m"]
W, H = S["cols"] * CELL, S["rows"] * CELL
DEM = np.load(PROCESSED / "terrain_30m.npy")[::-1]                # row 0 = south edge now
RESERVOIR = np.load(PROCESSED / "reservoir_30m.npy")[::-1]
Z0 = float(np.nanmin(DEM))
BOTTOM = -SLAB_M * K
FULL_POOL_M = reclamation_ft_to_dem_m(FULL_POOL_FT)


def to_z(elev_m):
    return (elev_m - Z0) * Z_EXAG * K


def new_mesh_object(name, verts, faces, attributes=None, smooth=False):
    """verts (n,3) float, faces (m,4) int, optional {name: per-vertex float array}."""
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", np.ascontiguousarray(verts, "float32").ravel())
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set("vertex_index", np.ascontiguousarray(faces, "int32").ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", np.arange(0, faces.size, 4, dtype="int32"))
    mesh.polygons.foreach_set("loop_total", np.full(len(faces), 4, dtype="int32"))
    for key, values in (attributes or {}).items():
        layer = mesh.attributes.new(key, "FLOAT", "POINT")
        layer.data.foreach_set("value", np.ascontiguousarray(values, "float32").ravel())
    if smooth:
        mesh.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def grid():
    z = DEM[::STEP, ::STEP]
    rows, cols = z.shape
    x = (np.arange(cols) * STEP + 0.5) * CELL
    y = (np.arange(rows) * STEP + 0.5) * CELL
    xs, ys = np.meshgrid(x, y)
    return z, xs, ys


def matte(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Specular IOR Level"].default_value = 0.0
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    return mat


def ramp(nt, stops):
    node = nt.nodes.new("ShaderNodeValToRGB")
    cr = node.color_ramp
    cr.interpolation = "LINEAR"
    while len(cr.elements) < len(stops):
        cr.elements.new(0.5)
    for el, (pos, color) in zip(cr.elements, stops):
        el.position = pos
        el.color = (*color, 1.0)
    return node


def math_node(nt, op, a, b=None, clamp=False):
    node = nt.nodes.new("ShaderNodeMath")
    node.operation = op
    node.use_clamp = clamp
    for socket, value in zip(node.inputs, (a, b)):
        if value is None:
            continue
        if isinstance(value, (int, float)):
            socket.default_value = value
        else:
            nt.links.new(value, socket)
    return node.outputs[0]


def level_node(nt):
    node = nt.nodes.new("ShaderNodeValue")
    node.name = node.label = "water_level_m"
    node.outputs[0].default_value = FULL_POOL_M
    return node


def terrain_material():
    """Rock colour by height and steepness, with a pale ring between the water and full pool."""
    mat = bpy.data.materials.new("Ground")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Specular IOR Level"].default_value = 0.0

    elev = nt.nodes.new("ShaderNodeAttribute")
    elev.attribute_name = "elev_m"
    lake = nt.nodes.new("ShaderNodeAttribute")
    lake.attribute_name = "reservoir"
    level = level_node(nt)

    lo, hi = 900.0, 3200.0
    t = math_node(nt, "DIVIDE", math_node(nt, "SUBTRACT", elev.outputs["Fac"], lo), hi - lo, clamp=True)
    def pos(m):
        return (m - lo) / (hi - lo)
    rock = ramp(nt, [(pos(950), (0.36, 0.17, 0.10)), (pos(1130), (0.52, 0.28, 0.16)),
                     (pos(1400), (0.60, 0.37, 0.22)), (pos(1750), (0.50, 0.36, 0.24)),
                     (pos(2200), (0.27, 0.25, 0.16)), (pos(3000), (0.16, 0.19, 0.12))])
    nt.links.new(t, rock.inputs["Fac"])

    # cliffs a little darker and redder than flats
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geom.outputs["Normal"], sep.inputs[0])
    steep = math_node(nt, "SUBTRACT", 1.0, math_node(nt, "POWER", sep.outputs["Z"], 3.0), clamp=True)
    cliff = nt.nodes.new("ShaderNodeMixRGB")
    cliff.blend_type = "MULTIPLY"
    cliff.inputs["Color2"].default_value = (0.62, 0.50, 0.46, 1.0)
    nt.links.new(steep, cliff.inputs["Fac"])
    nt.links.new(rock.outputs["Color"], cliff.inputs["Color1"])

    # bathtub ring: inside the reservoir, above the water, at or below full pool
    above = math_node(nt, "GREATER_THAN", elev.outputs["Fac"], level.outputs[0])
    below = math_node(nt, "LESS_THAN", elev.outputs["Fac"], FULL_POOL_M)
    inside = math_node(nt, "GREATER_THAN", lake.outputs["Fac"], 0.5)
    ring = math_node(nt, "MULTIPLY", math_node(nt, "MULTIPLY", above, below), inside)
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color2"].default_value = (0.60, 0.55, 0.47, 1.0)
    nt.links.new(ring, mix.inputs["Fac"])
    nt.links.new(cliff.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def water_material():
    """Colour by depth: turquoise in the shallows, dark blue over the old river channel."""
    mat = bpy.data.materials.new("Water")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.16
    bed = nt.nodes.new("ShaderNodeAttribute")
    bed.attribute_name = "bed_m"
    level = level_node(nt)
    depth = math_node(nt, "SUBTRACT", level.outputs[0], bed.outputs["Fac"])
    t = math_node(nt, "DIVIDE", depth, 150.0, clamp=True)
    colour = ramp(nt, [(0.0, (0.10, 0.36, 0.38)), (0.03, (0.035, 0.20, 0.27)), (0.2, (0.012, 0.085, 0.17)),
                       (1.0, (0.004, 0.030, 0.085))])
    nt.links.new(t, colour.inputs["Fac"])
    nt.links.new(colour.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def build_terrain():
    """Elevation samples sit at cell centres, so the mesh starts half a cell in."""
    z, xs, ys = grid()
    rows, cols = z.shape
    verts = np.column_stack([xs.ravel() * K, ys.ravel() * K, to_z(z).ravel()])
    idx = np.arange(rows * cols).reshape(rows, cols)
    faces = np.column_stack([idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()])
    obj = new_mesh_object("Terrain", verts, faces, smooth=True,
                          attributes={"elev_m": z, "reservoir": RESERVOIR[::STEP, ::STEP].astype("float32")})
    obj.data.materials.append(terrain_material())
    print(f"terrain {cols} x {rows} = {rows * cols / 1e6:.1f} M vertices, {CELL * STEP:g} m cells")

    # Sides and underside, so the terrain reads as a solid block
    ring = np.concatenate([idx[0, :-1], idx[:-1, -1], idx[-1, :0:-1], idx[:0:-1, 0]])
    top = verts[ring]
    low = top.copy()
    low[:, 2] = BOTTOM
    n = len(ring)
    i = np.arange(n)
    j = (i + 1) % n
    side_faces = np.column_stack([i, j, j + n, i + n])
    x, y = xs[0], ys[:, 0]
    corners = np.array([[x[0], y[0]], [x[-1], y[0]], [x[-1], y[-1]], [x[0], y[-1]]]) * K
    under = np.column_stack([corners, np.full(4, BOTTOM)])
    block = new_mesh_object("Block sides", np.vstack([top, low, under]),
                            np.vstack([side_faces, [[2 * n, 2 * n + 3, 2 * n + 2, 2 * n + 1]]]))
    block.data.materials.append(matte("Block", SIDE_COLOR))
    return obj


def build_water():
    """A flat sheet over the reservoir only, so nothing below the dam floods.

    It shares the terrain's grid; the ground hides it wherever the ground is
    higher. Its height is set by set_level().
    """
    from numpy.lib.stride_tricks import sliding_window_view
    z, xs, ys = grid()
    mask = RESERVOIR.copy()
    pad = np.pad(mask, 2 * STEP)                        # grow by two drawn cells so the sheet reaches the shore
    mask = sliding_window_view(pad, (4 * STEP + 1, 4 * STEP + 1)).any(axis=(2, 3))[::STEP, ::STEP]
    rows, cols = z.shape
    quad = mask[:-1, :-1] | mask[:-1, 1:] | mask[1:, 1:] | mask[1:, :-1]
    r, c = np.nonzero(quad)
    idx = np.arange(rows * cols).reshape(rows, cols)
    faces_full = np.column_stack([idx[r, c], idx[r, c + 1], idx[r + 1, c + 1], idx[r + 1, c]])
    used, faces = np.unique(faces_full, return_inverse=True)
    faces = faces.reshape(-1, 4)
    verts = np.column_stack([xs.ravel()[used] * K, ys.ravel()[used] * K, np.zeros(len(used))])
    obj = new_mesh_object("Water", verts, faces, attributes={"bed_m": z.ravel()[used]}, smooth=True)
    obj.data.materials.append(water_material())
    print(f"water sheet {len(faces) / 1e6:.2f} M faces")
    return obj


def set_level(water, level_ft):
    level_m = reclamation_ft_to_dem_m(level_ft)
    water.location.z = to_z(level_m)
    for mat in (bpy.data.materials["Ground"], bpy.data.materials["Water"]):
        mat.node_tree.nodes["water_level_m"].outputs[0].default_value = level_m
    return level_m


def build_floor():
    bpy.ops.mesh.primitive_plane_add(size=6000, location=(W * K / 2, H * K / 2, BOTTOM - 0.002))
    floor = bpy.context.object
    floor.name = "Floor"
    floor.data.materials.append(matte("Floor", FLOOR_COLOR))


def build_world():
    """Sky light with the sun in it; the camera itself sees a plain dark backdrop.
    Sun rotation is a compass bearing (0 = north, 90 = east) in Blender 5.2."""
    scene = bpy.context.scene
    world = bpy.data.worlds.new("Sky")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = math.radians(SUN_EL)
    sky.sun_rotation = math.radians(SUN_AZ)
    sky.sun_size = math.radians(1.2)
    sky.altitude = 1200
    path = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color2"].default_value = (*[c * 8 for c in FLOOR_COLOR], 1.0)
    nt.links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(sky.outputs[0], mix.inputs["Color1"])
    nt.links.new(mix.outputs[0], nt.nodes["Background"].inputs["Color"])


def build_camera():
    scene = bpy.context.scene
    cx, cy = W * K / 2, H * K / 2
    dam = ((456900 - S["x0"]) * K, (4087990 - S["y0"]) * K)
    lake_z = to_z(FULL_POOL_M)
    views = {
        # camera position, look-at point (km), lens (mm)
        "lake": ((cx + 6, -112, 118), (cx + 3, cy - 9, lake_z), 50),
        "dam": ((dam[0] - 15, dam[1] - 19, lake_z + 17), (dam[0] + 11, dam[1] + 10.5, lake_z), 40),
        "top": ((cx, cy, 235), (cx, cy + 0.001, 0), 50),
    }
    pos, look, lens = views[VIEW]
    target = bpy.data.objects.new("Target", None)
    target.location = look
    scene.collection.objects.link(target)
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = lens
    cam.data.sensor_width = 36
    cam.data.clip_start = 0.05
    cam.data.clip_end = 5000
    cam.location = pos
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.collection.objects.link(cam)
    scene.camera = cam


def use_gpu():
    """Turn on every graphics card Cycles can use; fall back to the CPU."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = backend
            except Exception:
                continue
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == backend
                print("rendering on", backend, [d.name for d in gpus])
                return "GPU"
    except Exception as exc:
        print("gpu setup failed:", exc)
    print("rendering on CPU")
    return "CPU"


def main():
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1000.0
    scene.unit_settings.length_unit = "KILOMETERS"
    build_terrain()
    water = build_water()
    build_floor()
    build_world()
    build_camera()

    scene.render.engine = "CYCLES"
    scene.cycles.device = use_gpu()
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 4
    scene.view_settings.exposure = EXPOSURE
    scene.view_settings.view_transform = arg("--transform", "Standard")
    scene.view_settings.look = arg("--look", "None")
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.image_settings.file_format = "PNG"
    RENDERS.mkdir(parents=True, exist_ok=True)
    BLENDER.mkdir(parents=True, exist_ok=True)

    jobs = [(OUT_NAME, LEVEL_FT)]
    if LEVELS_FILE:
        with open(LEVELS_FILE, newline="", encoding="utf-8") as fh:
            jobs = [(f"{VIEW}_{row['label']}.png", float(row["elevation_ft"])) for row in csv.DictReader(fh)]
        (RENDERS / VIEW).mkdir(exist_ok=True)
        jobs = [(os.path.join(VIEW, name), ft) for name, ft in jobs]

    set_level(water, jobs[0][1])
    bpy.ops.wm.save_as_mainfile(filepath=str(BLENDER / "powell.blend"))
    print(f"scene built in {time.time() - t0:.0f} s")
    if "--no-render" in argv:
        return
    for name, ft in jobs:
        level_m = set_level(water, ft)
        scene.render.filepath = str(RENDERS / name)
        bpy.ops.render.render(write_still=True)
        print(f"wrote {scene.render.filepath}: {ft:,.2f} ft = {level_m:.2f} m NAVD88, {time.time() - t0:.0f} s", flush=True)


main()
