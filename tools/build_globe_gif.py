"""Render the spinning-globe banner logo (assets/globe.gif).

A 90s-style animated GIF: a 64 px pixel-art Earth, tilted, dithered, looping
forever. The coastlines are rough hand-entered outlines (lon, lat), which is
all a globe this small needs. Run:  py tools/build_globe_gif.py
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "globe.gif"

SIZE = 64          # px, matches the banner's 64 x 64 slot
RADIUS = 30.0      # globe radius in px
FRAMES = 36        # 10 degrees of spin per frame
FRAME_MS = 70
TILT = np.radians(18)   # north pole tipped toward the viewer's upper right
SS = 4             # subsamples per pixel side, for the land/water vote

LAND = [
    # North America
    [(-168, 66), (-156, 71), (-130, 70), (-110, 68), (-95, 68), (-90, 64), (-94, 59),
     (-88, 56), (-82, 53), (-79, 52), (-78, 58), (-77, 62), (-70, 62), (-65, 59),
     (-60, 55), (-56, 52), (-60, 47), (-65, 44), (-70, 42), (-74, 40), (-76, 35),
     (-81, 31), (-80, 25), (-82, 28), (-84, 30), (-90, 29), (-97, 27), (-97, 22),
     (-95, 18), (-91, 18), (-90, 21), (-87, 21), (-88, 16), (-83, 15), (-83, 10),
     (-79, 9), (-77, 8), (-80, 7), (-85, 10), (-92, 15), (-97, 16), (-105, 20),
     (-110, 24), (-114, 30), (-117, 33), (-121, 35), (-124, 40), (-124, 48),
     (-130, 54), (-135, 58), (-145, 60), (-152, 59), (-158, 56), (-165, 54),
     (-162, 59), (-166, 62)],
    # Baffin and the Arctic islands
    [(-88, 72), (-80, 73), (-70, 70), (-62, 66), (-66, 62), (-75, 64), (-80, 68)],
    [(-120, 76), (-115, 73), (-95, 75), (-80, 76), (-65, 82), (-90, 81)],
    # Greenland
    [(-45, 60), (-52, 65), (-55, 70), (-60, 76), (-70, 78), (-60, 82), (-35, 83),
     (-20, 81), (-20, 74), (-25, 70), (-35, 66), (-42, 62)],
    # South America
    [(-77, 8), (-72, 12), (-62, 10), (-52, 5), (-50, 0), (-40, -3), (-35, -7),
     (-38, -13), (-40, -20), (-42, -23), (-48, -26), (-53, -33), (-58, -35),
     (-57, -38), (-62, -40), (-65, -45), (-68, -52), (-70, -55), (-74, -52),
     (-74, -45), (-73, -38), (-71, -30), (-70, -18), (-76, -14), (-81, -5),
     (-80, 0), (-78, 3)],
    # Africa
    [(-17, 15), (-16, 21), (-13, 27), (-9, 32), (-6, 36), (3, 37), (10, 37),
     (11, 33), (20, 31), (25, 32), (32, 31), (34, 28), (37, 22), (39, 15), (43, 12),
     (51, 12), (48, 5), (42, -1), (39, -6), (40, -15), (35, -20), (35, -24),
     (32, -28), (27, -34), (20, -35), (18, -32), (15, -25), (12, -17), (14, -10),
     (12, -5), (9, -1), (9, 4), (5, 6), (-2, 5), (-8, 4), (-13, 8), (-17, 12)],
    [(44, -25), (47, -25), (50, -16), (49, -12), (44, -17)],          # Madagascar
    # Eurasia (runs past 180 into Chukotka; drawn twice, shifted, below)
    [(-9, 37), (-9, 43), (-2, 43), (-1, 46), (-4, 48), (2, 51), (4, 52), (9, 54),
     (8, 57), (11, 57), (12, 54), (18, 54), (21, 55), (22, 58), (28, 60), (22, 60),
     (21, 64), (24, 66), (22, 66), (17, 62), (18, 60), (16, 56), (13, 55), (11, 59),
     (6, 58), (5, 62), (12, 66), (15, 69), (25, 71), (31, 70), (40, 67), (44, 68),
     (55, 69), (68, 69), (73, 72), (80, 73), (90, 75), (105, 77), (113, 74),
     (130, 71), (140, 72), (160, 70), (170, 69), (180, 69), (190, 66), (180, 65),
     (178, 62), (170, 60), (163, 60), (162, 56), (157, 51), (155, 57), (157, 61),
     (150, 59), (142, 59), (135, 55), (141, 52), (140, 48), (135, 44), (130, 42),
     (128, 39), (129, 36), (126, 34), (126, 38), (122, 40), (118, 39), (122, 37),
     (120, 34), (122, 30), (120, 26), (115, 22), (110, 21), (106, 17), (109, 13),
     (107, 10), (105, 9), (100, 13), (99, 9), (103, 2), (101, 3), (98, 8), (98, 16),
     (94, 16), (92, 21), (89, 22), (86, 20), (81, 16), (80, 12), (78, 8), (76, 10),
     (73, 17), (72, 21), (68, 24), (62, 25), (57, 26), (50, 30), (48, 30), (51, 25),
     (52, 24), (56, 25), (59, 22), (55, 17), (45, 13), (43, 13), (39, 21), (35, 28),
     (35, 32), (36, 36), (30, 36), (27, 37), (26, 40), (29, 41), (35, 42), (41, 41),
     (41, 43), (37, 45), (33, 46), (30, 46), (28, 43), (26, 41), (24, 40), (23, 38),
     (20, 40), (19, 42), (14, 45), (12, 44), (16, 41), (18, 40), (16, 38), (12, 42),
     (9, 44), (3, 43), (0, 39), (-2, 37), (-5, 36)],
    [(-5, 50), (1, 51), (1, 53), (-2, 56), (-2, 58), (-5, 58), (-6, 56), (-3, 54),
     (-5, 52)],                                                        # Great Britain
    [(-10, 52), (-6, 52), (-6, 55), (-10, 54)],                        # Ireland
    [(-24, 65), (-14, 66), (-14, 64), (-22, 63)],                      # Iceland
    [(12, 78), (25, 80), (20, 77)],                                    # Svalbard
    [(52, 71), (57, 71), (68, 77), (60, 76)],                          # Novaya Zemlya
    [(130, 31), (131, 34), (136, 34), (140, 35), (142, 39), (141, 41), (145, 43),
     (142, 45), (140, 42), (139, 38), (136, 36), (132, 35), (130, 33)],  # Japan
    [(120, 23), (122, 25), (121, 22)],                                 # Taiwan
    [(120, 18), (122, 18), (124, 12), (126, 7), (122, 7), (120, 13)],  # Philippines
    [(95, 5), (98, 3), (104, -2), (106, -6), (102, -4), (97, 2)],      # Sumatra
    [(106, -6), (114, -7), (114, -8.5), (106, -7.5)],                  # Java
    [(109, 1), (113, -3), (116, -4), (118, 1), (117, 7), (113, 3)],    # Borneo
    [(119, -5), (121, -3), (125, 1), (120, 1)],                        # Sulawesi
    [(131, -1), (138, -2), (145, -5), (150, -10), (142, -9), (138, -8), (133, -4)],
    # Australia
    [(114, -22), (114, -34), (118, -35), (124, -33), (129, -32), (134, -33),
     (138, -35), (141, -38), (147, -39), (150, -37), (153, -30), (153, -25),
     (149, -21), (146, -19), (145, -15), (142, -11), (141, -17), (136, -15),
     (136, -12), (131, -12), (127, -14), (122, -18)],
    [(145, -41), (148, -41), (147, -43.5), (146, -43.5)],              # Tasmania
    [(173, -35), (178, -38), (175, -41), (174, -39)],                  # NZ north
    [(172, -41), (174, -42), (170, -46), (167, -46), (168, -44)],      # NZ south
    [(80, 9), (82, 7), (80, 6)],                                       # Sri Lanka
    [(-85, 22), (-75, 20), (-74, 20.5), (-80, 23)],                    # Cuba
    [(-74, 19), (-68, 18.5), (-70, 20)],                               # Hispaniola
]
WATER = [
    [(50, 37), (54, 37), (53, 42), (51, 45), (53, 47), (49, 46), (47, 43), (49, 40)],  # Caspian
]
ICE = [
    # Antarctica
    [(-180, -78), (-150, -76), (-120, -74), (-100, -72), (-75, -72), (-62, -65),
     (-58, -64), (-62, -74), (-40, -78), (-20, -74), (0, -70), (30, -69), (60, -67),
     (90, -66), (120, -66), (150, -68), (170, -72), (180, -78), (180, -90), (-180, -90)],
    # Greenland interior
    [(-45, 63), (-50, 68), (-55, 76), (-45, 81), (-28, 79), (-27, 72), (-38, 67)],
]

# Palette index 0 is the transparent colour.
PALETTE = [
    (255, 0, 255),                                        # 0 transparent
    (0, 0, 0),                                            # 1 outline
    (0, 16, 96), (16, 64, 176), (43, 111, 214), (120, 176, 255),    # 2-5 ocean, dark to light
    (6, 70, 28), (24, 124, 48), (46, 168, 62), (136, 220, 104),     # 6-9 land, dark to light
    (96, 112, 144), (160, 176, 200), (224, 232, 244), (255, 255, 255),  # 10-13 ice
]
OCEAN0, LAND0, ICE0 = 2, 6, 10

BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16.0


def surface_map(w=1440, h=720):
    """Equirectangular class map: 0 ocean, 1 land, 2 ice."""
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)

    def poly(points, value):
        for shift in (-360, 0, 360):
            draw.polygon([((lon + shift + 180) / 360 * w, (90 - lat) / 180 * h)
                          for lon, lat in points], fill=value)

    for p in LAND:
        poly(p, 1)
    for p in WATER:
        poly(p, 0)
    for p in ICE:
        poly(p, 2)
    arr = np.array(img)
    arr[: int(h * 6 / 180)] = 2          # Arctic sea ice cap, north of 84 N
    return arr


def frame(surface, lon0):
    h, w = surface.shape
    n = SIZE * SS
    c = (np.arange(n) + 0.5) / SS - SIZE / 2
    x, y = np.meshgrid(c / RADIUS, -c / RADIUS)
    r2 = x * x + y * y
    inside = r2 <= 1.0
    z = np.sqrt(np.where(inside, 1.0 - r2, 0.0))

    # Undo the tilt (a roll about the view axis, then a nod toward the viewer).
    roll = np.radians(-14)
    xr = x * np.cos(roll) - y * np.sin(roll)
    yr = x * np.sin(roll) + y * np.cos(roll)
    yt = yr * np.cos(TILT) + z * np.sin(TILT)
    zt = -yr * np.sin(TILT) + z * np.cos(TILT)

    lat = np.degrees(np.arcsin(np.clip(yt, -1, 1)))
    lon = (np.degrees(np.arctan2(xr, zt)) + lon0 + 180) % 360 - 180
    col = np.clip(((lon + 180) / 360 * w).astype(int), 0, w - 1)
    row = np.clip(((90 - lat) / 180 * h).astype(int), 0, h - 1)
    cls = surface[row, col]

    # Fixed light from the upper left, so the terminator stays put as it spins.
    light = np.array([-0.55, 0.55, 0.63])
    light /= np.linalg.norm(light)
    shade = np.clip(x * light[0] + y * light[1] + z * light[2], 0, 1)

    def pool(a):
        return a.reshape(SIZE, SS, SIZE, SS).mean(axis=(1, 3))

    cover = pool(inside.astype(float))
    land = pool((cls == 1) & inside) / np.maximum(cover, 1e-6)
    ice = pool((cls == 2) & inside) / np.maximum(cover, 1e-6)
    shade = pool(shade * inside) / np.maximum(cover, 1e-6)

    # Four shade levels per surface, ordered-dithered between neighbours.
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    level = np.clip(np.floor(shade * 3.4 + BAYER[yy % 4, xx % 4]), 0, 3).astype(int)

    out = np.full((SIZE, SIZE), OCEAN0, dtype=np.uint8) + level.astype(np.uint8)
    out = np.where(land >= 0.5, LAND0 + level, out)
    out = np.where(ice >= 0.5, ICE0 + level, out)

    # Specular glint on open water.
    half = light + np.array([0, 0, 1.0])
    half /= np.linalg.norm(half)
    xs, ys = np.meshgrid((np.arange(SIZE) + 0.5 - SIZE / 2) / RADIUS,
                         -(np.arange(SIZE) + 0.5 - SIZE / 2) / RADIUS)
    zs = np.sqrt(np.clip(1 - xs * xs - ys * ys, 0, 1))
    glint = (xs * half[0] + ys * half[1] + zs * half[2]) > 0.992
    out = np.where(glint & (land < 0.5) & (ice < 0.5), 13, out)

    out = np.where(cover >= 0.5, out, 0)

    # One-pixel black outline around the disc.
    disc = cover >= 0.5
    grown = disc.copy()
    grown[1:] |= disc[:-1]
    grown[:-1] |= disc[1:]
    grown[:, 1:] |= disc[:, :-1]
    grown[:, :-1] |= disc[:, 1:]
    out = np.where(grown & ~disc, 1, out)

    img = Image.fromarray(out.astype(np.uint8), "P")
    flat = [v for rgb in PALETTE for v in rgb]
    img.putpalette(flat + [0] * (768 - len(flat)))
    return img


def main():
    surface = surface_map()
    # Earth turns west to east, so the centre longitude falls as time passes.
    frames = [frame(surface, -i * 360 / FRAMES) for i in range(FRAMES)]
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=FRAME_MS,
                   loop=0, transparency=0, disposal=2, optimize=False)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB, {FRAMES} frames)")

    # Contact sheet for checking the frames by eye.
    sheet = Image.new("RGB", (SIZE * 9 * 3, SIZE * 4 * 3), (0, 0, 128))
    for i, f in enumerate(frames):
        rgba = f.convert("RGBA")
        px = np.array(rgba)
        px[np.array(f) == 0] = (0, 0, 128, 255)
        tile = Image.fromarray(px).resize((SIZE * 3, SIZE * 3), Image.NEAREST)
        sheet.paste(tile, ((i % 9) * SIZE * 3, (i // 9) * SIZE * 3))
    return sheet


if __name__ == "__main__":
    import sys
    sheet = main()
    if len(sys.argv) > 1:
        sheet.save(sys.argv[1])
