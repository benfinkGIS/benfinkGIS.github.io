"""Step 10e (part 2): render a block of a neighborhood in 3D, today or planted.

Runs inside Blender (5.2), headless:

  blender -b --factory-startup -P tools/canopy/22_blender_render.py -- \
      --site western_hills_ii --scenario 1 [--draft] [--view south]

  --scenario   0 today, 1 street trees, 2 streets and homes, 3 full build-out
  --draft      1280 px wide and few samples, for checking the framing

The scene is built from the arrays 21_blender_export.py wrote, in metres with
no vertical exaggeration:
  * ground and buildings: one surface, the lidar ground plus roof heights,
    with the 2023 aerial photo draped over it and walls tinted plain
  * today's trees: the lidar canopy surface itself, as green masses, so every
    crown has the size and shape the laser measured
  * proposed trees: one simple tree per planting spot, at its published
    mature height and width, in each species' own foliage or bloom colour
  * light: a physical sky with the sun where it is at 4 p.m. on 15 July, the
    same position the shade analysis uses, so the shadows here are the ones
    counted there

Writes work/<site>/blender/renders/<site>_s<scenario>.png.
"""
import json
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(flag, default=None, kind=str):
    return kind(argv[argv.index(flag) + 1]) if flag in argv else default


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITE = arg("--site", "western_hills_ii")
SCENARIO = arg("--scenario", 0, int)
DRAFT = "--draft" in argv
VIEW = arg("--view", "south")
WORK = os.path.join(ROOT, "tucson-canopy", "work", SITE, "blender")
with open(os.path.join(WORK, "scene.json"), encoding="utf-8") as fh:
    S = json.load(fh)
CELL, SIZE = S["cell_m"], S["size_m"]
SUN_AZ = arg("--sun-az", S["sun_azimuth"], float)
SUN_EL = arg("--sun-el", S["sun_elevation"], float)
EXPOSURE = arg("--exposure",
               float(np.interp(SUN_EL, [4, 9, 20, 38, 70], [-2.6, -3.4, -4.2, -4.9, -5.3])), float)
RENDER = (1280, 720) if DRAFT else (2560, 1440)
SAMPLES = 48 if DRAFT else 256
BASE_Z = -5.0                       # underside of the block
BACKDROP = (0.80, 0.80, 0.78)
EXISTING_GREEN = ((0.07, 0.17, 0.05), (0.13, 0.26, 0.08))
# Proposed trees in the colours the plants themselves show, lighter than
# today's canopy so they stand apart: grey-green mesquite, yellow and
# yellow-green palo verdes in bloom, pink desert willow. (The maps use the
# site's chart colours instead; a blue tree looks wrong in a rendered scene.)
RENDER_COLOURS = {
    "Velvet mesquite": (0.33, 0.47, 0.24),
    "Blue palo verde": (0.78, 0.68, 0.10),
    "Foothill palo verde": (0.55, 0.66, 0.17),
    "Desert willow": (0.80, 0.40, 0.55),
}

# row 0 = south edge after the flip
GROUND = np.load(os.path.join(WORK, "ground.npy"))[::-1] - S["ground_min"]
ROOF = np.load(os.path.join(WORK, "roof.npy"))[::-1]
CANOPY = np.load(os.path.join(WORK, "canopy.npy"))[::-1]
N = GROUND.shape[0]


def blur(a, passes=2):
    """Small box blur with numpy alone (Blender's Python has no scipy)."""
    for _ in range(passes):
        p = np.pad(a, 1, mode="edge")
        a = sum(p[i:i + a.shape[0], j:j + a.shape[1]] for i in range(3) for j in range(3)) / 9
    return a


def new_mesh_object(name, verts, faces, uvs=None, smooth=False):
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", np.ascontiguousarray(verts, "float32").ravel())
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set("vertex_index", np.ascontiguousarray(faces, "int32").ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", np.arange(0, faces.size, 4, dtype="int32"))
    mesh.polygons.foreach_set("loop_total", np.full(len(faces), 4, dtype="int32"))
    if uvs is not None:
        layer = mesh.uv_layers.new(name="UVMap")
        layer.data.foreach_set("uv", np.ascontiguousarray(uvs[faces.ravel()], "float32").ravel())
    if smooth:
        mesh.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def grid(z):
    """Vertices at cell centres and the quads between them."""
    yy, xx = np.mgrid[0:N, 0:N]
    verts = np.stack([(xx + 0.5) * CELL, (yy + 0.5) * CELL, z], -1).reshape(-1, 3)
    i = (yy[:-1, :-1] * N + xx[:-1, :-1]).ravel()
    faces = np.stack([i, i + 1, i + N + 1, i + N], -1)
    return verts, faces


def matte(name, color=(0.5, 0.5, 0.5)):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 1.0
    for key in ("Specular IOR Level", "Specular"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.0
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    return mat


def build_ground():
    z = GROUND + ROOF
    verts, faces = grid(z)
    uvs = verts[:, :2] / SIZE
    obj = new_mesh_object("Ground and buildings", verts, faces, uvs)
    mat = matte("Photo")
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(os.path.join(WORK, "texture.png"))
    tex.extension = "EXTEND"
    # the photo's own shadows fight the rendered ones: lift it toward its mean
    lift = nt.nodes.new("ShaderNodeMixRGB")
    lift.inputs["Fac"].default_value = 0.30
    lift.inputs["Color2"].default_value = (0.62, 0.55, 0.47, 1)
    nt.links.new(tex.outputs["Color"], lift.inputs["Color1"])
    # walls are steep faces with the roof's pixels smeared down them: paint them plain
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    steep = nt.nodes.new("ShaderNodeMath")
    steep.operation = "LESS_THAN"
    steep.inputs[1].default_value = 0.55
    wall = nt.nodes.new("ShaderNodeMixRGB")
    wall.inputs["Color2"].default_value = (0.78, 0.72, 0.64, 1)
    nt.links.new(geo.outputs["True Normal"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], steep.inputs[0])
    nt.links.new(steep.outputs[0], wall.inputs["Fac"])
    nt.links.new(lift.outputs[0], wall.inputs["Color1"])
    nt.links.new(wall.outputs[0], bsdf.inputs["Base Color"])
    obj.data.materials.append(mat)

    # sides and underside, so the block reads as a cut piece of ground
    edge = np.concatenate([np.arange(N), np.arange(1, N) * N + N - 1,
                           (N - 1) * N + np.arange(N - 2, -1, -1), np.arange(N - 2, 0, -1) * N])
    top = verts[edge]
    bottom = top.copy()
    bottom[:, 2] = BASE_Z
    k = len(edge)
    sv = np.concatenate([top, bottom])
    j = np.arange(k)
    sf = np.stack([j, (j + 1) % k, (j + 1) % k + k, j + k], -1)
    side = new_mesh_object("Block sides", sv, sf)
    side.data.materials.append(matte("Earth", (0.42, 0.34, 0.27)))
    floor_v = np.array([[-6000, -6000, BASE_Z], [6000, -6000, BASE_Z],
                        [6000, 6000, BASE_Z], [-6000, 6000, BASE_Z]], "float32")
    floor = new_mesh_object("Floor", floor_v, np.array([[0, 1, 2, 3]]))
    floor.data.materials.append(matte("Backdrop", BACKDROP))


def build_canopy():
    has = CANOPY > 0
    if not has.any():
        return
    smooth = blur(np.where(has, CANOPY, 0), passes=3)
    z = np.where(has, GROUND + np.maximum(smooth, 1.2), GROUND - 1.5)
    verts, faces = grid(z)
    keep = has.ravel()[faces].any(1)
    obj = new_mesh_object("Canopy today", verts, faces[keep], smooth=True)
    mat = matte("Foliage")
    nt = mat.node_tree
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.6
    noise.inputs["Detail"].default_value = 4
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*EXISTING_GREEN[0], 1)
    ramp.color_ramp.elements[1].color = (*EXISTING_GREEN[1], 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    obj.data.materials.append(mat)


def tree_mesh(index, radius, height):
    """A lumpy ellipsoid crown on a short trunk, origin at the ground."""
    base = S["crown_base_m"]
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
    half = (height - base) / 2
    for v in bm.verts:
        lump = 1 + 0.10 * math.sin(4.1 * v.co.x + index) * math.sin(3.7 * v.co.y + 1.3) \
                 + 0.06 * math.sin(7.3 * v.co.z + 2 * index)
        v.co.x *= radius * lump
        v.co.y *= radius * lump
        v.co.z = v.co.z * half * lump + base + half
    for f in bm.faces:
        f.material_index = 0
        f.smooth = True
    trunk = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.16, radius2=0.12,
                                  depth=base + half * 0.6)
    for v in trunk["verts"]:
        v.co.z += (base + half * 0.6) / 2
        for f in v.link_faces:
            f.material_index = 1
    mesh = bpy.data.meshes.new(f"Tree {index}")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def build_new_trees():
    if SCENARIO == 0:
        return 0
    bark = matte("Bark", (0.22, 0.15, 0.10))
    meshes = []
    for i, sp in enumerate(S["species"]):
        radius = next((t[4] for t in S["trees"] if t[3] == i), 3.0)
        height = next((t[5] for t in S["trees"] if t[3] == i), 6.0)
        mesh = tree_mesh(i, radius, height)
        mesh.materials.append(matte(sp["name"], RENDER_COLOURS.get(sp["name"], (0.30, 0.45, 0.18))))
        mesh.materials.append(bark)
        meshes.append(mesh)
    rng = np.random.default_rng(7)
    count = 0
    for x, y, ground, sp, radius, height, scen in S["trees"]:
        if scen > SCENARIO:
            continue
        obj = bpy.data.objects.new("Tree", meshes[sp])
        obj.location = (x, y, ground - S["ground_min"])
        obj.rotation_euler[2] = float(rng.uniform(0, 2 * math.pi))
        s = float(rng.uniform(0.92, 1.06))
        obj.scale = (s, s, float(rng.uniform(0.94, 1.05)))
        bpy.context.scene.collection.objects.link(obj)
        count += 1
    return count


def build_world():
    """Sky light with the sun in it. Sun rotation is a compass bearing
    (0 = north, 90 = east) in Blender 5.2."""
    world = bpy.data.worlds.new("Sky")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = math.radians(SUN_EL)
    sky.sun_rotation = math.radians(SUN_AZ)
    sky.sun_size = math.radians(0.8)
    sky.altitude = 750
    path = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color2"].default_value = (*[c * 60 for c in BACKDROP], 1.0)
    nt.links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(sky.outputs[0], mix.inputs["Color1"])
    nt.links.new(mix.outputs[0], nt.nodes["Background"].inputs["Color"])


def build_camera():
    scene = bpy.context.scene
    c = SIZE / 2
    views = {   # camera position, look-at point, lens
        "south": ((c - 0.20 * SIZE, -0.98 * SIZE, 0.80 * SIZE), (c, 0.42 * SIZE, 0), 50),
        "close": ((c - 0.10 * SIZE, -0.20 * SIZE, 0.34 * SIZE), (c, 0.40 * SIZE, 0), 40),
        "top": ((c, c, 1.9 * SIZE), (c, c + 0.01, 0), 50),
    }
    pos, look, lens = views[VIEW]
    target = bpy.data.objects.new("Target", None)
    target.location = look
    scene.collection.objects.link(target)
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = lens
    cam.data.sensor_width = 36
    cam.data.clip_start = 1
    cam.data.clip_end = 20000
    cam.location = pos
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.collection.objects.link(cam)
    scene.camera = cam


def use_gpu():
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
    build_ground()
    build_canopy()
    planted = build_new_trees()
    build_world()
    build_camera()
    scene.render.engine = "CYCLES"
    scene.cycles.device = use_gpu()
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 4
    scene.view_settings.exposure = EXPOSURE
    try:
        scene.view_settings.view_transform = arg("--transform", "Standard")
        scene.view_settings.look = "None"
    except Exception as exc:
        print("colour settings:", exc)
    scene.render.resolution_x, scene.render.resolution_y = RENDER
    scene.render.image_settings.file_format = "PNG"
    out = os.path.join(WORK, "renders")
    os.makedirs(out, exist_ok=True)
    name = arg("--out", f"{SITE}_s{SCENARIO}{'_' + VIEW if VIEW != 'south' else ''}{'_draft' if DRAFT else ''}.png")
    scene.render.filepath = os.path.join(out, name)
    print(f"scene built in {time.time() - t0:.0f} s: {planted} proposed trees, sun az {SUN_AZ} el {SUN_EL}")
    if "--no-render" not in argv:
        bpy.ops.render.render(write_still=True)
        print(f"wrote {scene.render.filepath} after {time.time() - t0:.0f} s")


main()
