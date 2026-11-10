"""Build the 3D model of the Santa Catalina Mountains in Blender and render it.

Run headless (after tools/build_catalinas.py):

  blender -b -P tools/blender_catalinas.py -- [options]

  --view NAME     south = from above Tucson looking north-north-east (default)
                  west  = from above Oro Valley looking east at Pusch Ridge
                  east  = from the San Pedro side looking west
                  top   = straight down, north up
                  front = low over Tucson, close on the front range
  --draft         quick look: coarser mesh, 1280 px wide, fewer samples
  --step N        use every Nth elevation cell (default 1, draft 3)
  --exag F        vertical exaggeration (default 1.0 = true scale)
  --sun-az DEG    compass direction the sun is in (default 268, just south of
                  west: golden hour, an evening in early spring or autumn)
  --sun-el DEG    sun height above the horizon (default 9)
  --exposure EV   film exposure in stops (default: set from the sun height,
                  about -3.4 at 9 degrees and -4.9 at 38)
  --haze KM       distance at which haze hides about two thirds of the view,
                  sky views only (default 120; 0 = none)
  --texture FILE  drape this image. Default: catalinas-3d/work/texture_flat.jpg
                  (imagery with the photo's own sunlight removed by
                  tools/deshade_catalinas.py), or texture.jpg if that is missing
  --out FILE      file name inside catalinas-3d/work/renders/
  --no-render     build and save the .blend only

Saves catalinas-3d/work/catalinas.blend (last scene built) so it can be opened
in Blender. 1 Blender unit = 1 km. Origin = south-west corner of the frame,
+X east, +Y north.
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "catalinas-3d", "work")
K = 0.001             # metres -> Blender units (km)
SLAB_M = 900.0        # thickness of the block under the lowest ground
FLOOR_COLOR = (0.012, 0.013, 0.015)
SIDE_COLOR = (0.045, 0.038, 0.033)
SKY_VIEWS = ("front",)    # views that show the sky rather than a studio backdrop
PLAIN_COLOR = (0.30, 0.27, 0.20)   # flat ground beyond the block in sky views

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(flag, default=None, kind=str):
    return kind(argv[argv.index(flag) + 1]) if flag in argv else default


DRAFT = "--draft" in argv
VIEW = arg("--view", "south")
STEP = arg("--step", 3 if DRAFT else 1, int)
Z_EXAG = arg("--exag", 1.0, float)
SUN_AZ = arg("--sun-az", 268.0, float)
SUN_EL = arg("--sun-el", 9.0, float)
# less light reaches the ground when the sun is low, so open up to match
EXPOSURE = arg("--exposure",
               float(np.interp(SUN_EL, [4, 9, 20, 38, 70], [-2.6, -3.4, -4.2, -4.9, -5.3])),
               float)
HAZE_KM = arg("--haze", 120.0, float)
OUT_NAME = arg("--out", f"{VIEW}{'_draft' if DRAFT else ''}.png")
RENDER = (1280, 720) if DRAFT else (3840, 2160)
SAMPLES = 64 if DRAFT else 256

with open(os.path.join(WORK, "scene.json"), encoding="utf-8") as fh:
    S = json.load(fh)
CELL = S["cell_m"]
W, H = S["width_m"], S["height_m"]
DEM = np.load(os.path.join(WORK, "dem.npy"))[::-1]    # row 0 = south edge now
Z0 = float(DEM.min())
BOTTOM = -SLAB_M * K


def new_mesh_object(name, verts, faces, uvs=None, smooth=False):
    """verts (n,3) float, faces (m,4) int, optional per-vertex uv (n,2)."""
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
        layer.data.foreach_set(
            "uv", np.ascontiguousarray(uvs[faces.ravel()], "float32").ravel())
    if smooth:
        mesh.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def matte(name, color=None, image=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 1.0
    for key in ("Specular IOR Level", "Specular"):    # name differs by version
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.0
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(image)
        tex.extension = "EXTEND"
        tex.interpolation = "Cubic"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    return mat


def default_texture():
    flat = os.path.join(WORK, "texture_flat.jpg")
    return flat if os.path.exists(flat) else os.path.join(WORK, "texture.jpg")


def build_terrain():
    """Elevation samples sit at cell centres, so the mesh starts half a cell in."""
    z = (DEM[::STEP, ::STEP] - Z0) * Z_EXAG * K
    rows, cols = z.shape
    x = (np.arange(cols) * STEP + 0.5) * CELL
    y = (np.arange(rows) * STEP + 0.5) * CELL
    xs, ys = np.meshgrid(x, y)
    verts = np.column_stack([xs.ravel() * K, ys.ravel() * K, z.ravel()])
    uvs = np.column_stack([xs.ravel() / W, ys.ravel() / H])
    idx = np.arange(rows * cols).reshape(rows, cols)
    faces = np.column_stack([idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(),
                             idx[1:, 1:].ravel(), idx[1:, :-1].ravel()])
    obj = new_mesh_object("Terrain", verts, faces, uvs, smooth=True)
    obj.data.materials.append(
        matte("Imagery", image=arg("--texture", default_texture())))
    print(f"terrain {cols} x {rows} = {rows * cols / 1e6:.1f} M vertices, "
          f"{CELL * STEP:g} m cells")

    # Sides and underside, so the terrain reads as a solid block
    ring = np.concatenate([idx[0, :-1], idx[:-1, -1], idx[-1, :0:-1], idx[:0:-1, 0]])
    top = verts[ring]
    low = top.copy()
    low[:, 2] = BOTTOM
    n = len(ring)
    i = np.arange(n)
    j = (i + 1) % n
    side_faces = np.column_stack([i, j, j + n, i + n])
    corners = np.array([[x[0], y[0]], [x[-1], y[0]], [x[-1], y[-1]], [x[0], y[-1]]]) * K
    under = np.column_stack([corners, np.full(4, BOTTOM)])
    block = new_mesh_object(
        "Block sides", np.vstack([top, low, under]),
        np.vstack([side_faces, [[2 * n, 2 * n + 3, 2 * n + 2, 2 * n + 1]]]))
    block.data.materials.append(matte("Block", color=SIDE_COLOR))
    return obj


def build_floor():
    bpy.ops.mesh.primitive_plane_add(size=4000, location=(W * K / 2, H * K / 2,
                                                          BOTTOM - 0.002))
    floor = bpy.context.object
    floor.name = "Floor"
    floor.data.materials.append(matte("Floor", color=FLOOR_COLOR))


def build_surroundings():
    """Sky views: flat ground out to the horizon and a layer of haze, so the
    block does not end against the lower half of the sky."""
    cx, cy = W * K / 2, H * K / 2
    # just under the lowest ground in the block, so it never covers terrain
    bpy.ops.mesh.primitive_plane_add(size=3000, location=(cx, cy, -0.02))
    plain = bpy.context.object
    plain.name = "Plain beyond the block"
    plain.data.materials.append(matte("Plain", color=PLAIN_COLOR))
    if HAZE_KM <= 0:
        return
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, 3.0 + BOTTOM / 2),
                                    scale=(3000, 3000, 6.0 - BOTTOM))
    air = bpy.context.object
    air.name = "Haze"
    mat = bpy.data.materials.new("Haze")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    vol = nt.nodes.new("ShaderNodeVolumeScatter")
    vol.inputs["Color"].default_value = (0.78, 0.88, 1.0, 1.0)   # blue scatters more
    vol.inputs["Density"].default_value = 1.0 / HAZE_KM
    vol.inputs["Anisotropy"].default_value = 0.35
    nt.links.new(vol.outputs[0], nt.nodes["Material Output"].inputs["Volume"])
    air.data.materials.append(mat)


def build_world():
    """Sky light with the sun in it. Sun rotation is a compass bearing
    (0 = north, 90 = east), checked with a test render in Blender 5.2."""
    scene = bpy.context.scene
    world = bpy.data.worlds.new("Sky")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = math.radians(SUN_EL)
    sky.sun_rotation = math.radians(SUN_AZ)
    sky.sun_size = math.radians(1.2)     # a little soft; the real sun is 0.53
    sky.altitude = 800                   # metres; Tucson basin
    if VIEW in SKY_VIEWS:    # a landscape view: the camera sees the sky too
        nt.links.new(sky.outputs[0], nt.nodes["Background"].inputs["Color"])
        return
    # The camera sees a plain dark backdrop; everything else sees the sky
    path = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color2"].default_value = (*[c * 8 for c in FLOOR_COLOR], 1.0)
    nt.links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(sky.outputs[0], mix.inputs["Color1"])
    nt.links.new(mix.outputs[0], nt.nodes["Background"].inputs["Color"])


def build_camera():
    scene = bpy.context.scene
    cx, cy = W * K / 2, H * K / 2
    top_z = (float(DEM.max()) - Z0) * Z_EXAG * K
    views = {
        # camera position, look-at point (km), lens (mm)
        "south": ((cx - 15, -44, 32), (cx + 0.5, cy - 4, 0), 50),
        "west": ((-38, cy - 24, 15), (cx - 2, cy - 2, 0), 45),
        "east": ((W * K + 40, cy - 16, 17), (cx, cy - 1, 0), 45),
        "top": ((cx, cy, 78), (cx, cy + 0.001, 0), 50),
        # low over Tucson, looking at the front range; crops the block
        "front": ((cx - 4, -4, 2.4), (cx + 1, cy - 4, top_z * 0.5), 35),
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
    if VIEW in SKY_VIEWS:
        build_surroundings()
    else:
        build_floor()
    build_world()
    build_camera()

    scene.render.engine = "CYCLES"
    scene.cycles.device = use_gpu()
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 4
    scene.cycles.volume_bounces = 2
    scene.view_settings.exposure = EXPOSURE
    try:    # keep the imagery's own colours rather than a film-style curve
        scene.view_settings.view_transform = arg("--transform", "Standard")
        scene.view_settings.look = arg("--look", "None")
    except Exception as exc:
        print("colour settings:", exc)
        vs = scene.view_settings
        print("looks:", [e.identifier for e in vs.bl_rna.properties["look"].enum_items])
    scene.render.resolution_x, scene.render.resolution_y = RENDER
    scene.render.image_settings.file_format = "PNG"
    os.makedirs(os.path.join(WORK, "renders"), exist_ok=True)
    scene.render.filepath = os.path.join(WORK, "renders", OUT_NAME)

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(WORK, "catalinas.blend"))
    print(f"scene built in {time.time() - t0:.0f} s")
    if "--no-render" not in argv:
        bpy.ops.render.render(write_still=True)
        print(f"wrote {scene.render.filepath} after {time.time() - t0:.0f} s")


main()
