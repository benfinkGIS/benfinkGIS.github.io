"""Take the sunlight out of the aerial imagery of the Santa Catalinas, so the
3D model can be lit from any direction without two sets of shading.

The photos were flown at different times, so the sun direction changes from
strip to strip. Instead of assuming one sun, this fits the brightness of the
photo against the direction each slope faces, separately around every spot
(a smooth moving window), and divides that pattern out:

    brightness = ground colour x (c0 + c1*nx + c2*ny + c3*(1 - nz))

where (nx, ny, nz) is the surface normal from the elevation grid. That is
what sunlight plus skylight on a matte surface looks like, whatever the sun
direction was. Red, green and blue are fitted separately, because shaded
slopes are lit by blue sky and would turn teal if simply brightened. Flat
ground is left as it is.

Slopes in full shadow do not follow that pattern (they get no sun at all), so
they are handled separately: pixels on sloping ground that are both darker
and bluer than their surroundings are marked as shadow, left out of the fit,
and then given the colour of the sunlit ground around them, keeping only
their own light-and-dark detail. Flat ground is never treated as shadow, so
streets and roofs keep their colour.

Limits: slopes that are darker because more grows on them (north-facing
ones) are lightened along with the shading, detail inside deep shadow stays
soft and noisy, and the seam between two flight strips is still faintly
visible.

Reads  catalinas-3d/work/dem.npy and texture.jpg
Writes catalinas-3d/work/texture_flat.jpg and deshade_check.jpg

Run:  py tools/deshade_catalinas.py      (after tools/build_catalinas.py)
"""
import json
import os

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, zoom

Image.MAX_IMAGE_PIXELS = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "catalinas-3d", "work")

FIT_STEP = 4            # fit on every 4th elevation cell (40 m)
WINDOW_M = 2500.0       # radius (sigma) of the moving window
RIDGE = 2e-4            # keeps the fit steady where the ground is flat
GAIN = (0.45, 2.6)      # most a pixel may be darkened / brightened
REF_M = 1200.0          # "surroundings" for spotting shadow (sigma)
SHADOW_WIN_M = 300.0    # window for matching shadow to nearby sunlit ground
DARKER = (0.12, 0.35)   # log brightness below surroundings: start, full shadow
BLUER = (0.02, 0.12)    # log blue/red above surroundings: start, full shadow
SLOPE_DEG = (6.0, 14.0)  # shadow is only looked for on ground steeper than this
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype="float32")


def normals(z, cell):
    """Unit normals, x east, y north, z up. Row 0 of z is the north edge."""
    gy, gx = np.gradient(z, cell)
    nx, ny, nz = -gx, gy, np.ones_like(z)
    n = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    return nx / n, ny / n, nz / n


def ramp(x, lo_hi):
    return np.clip((x - lo_hi[0]) / (lo_hi[1] - lo_hi[0]), 0, 1)


def log_lum_blue(rgb):
    """Log brightness and log blue/red of linear rgb."""
    safe = np.clip(rgb, 2e-3, None)
    return np.log(safe @ LUMA), np.log(safe[..., 2] / safe[..., 0])


def fit_coefficients(rgb, nx, ny, nz, cell, weight):
    """Moving-window weighted least squares of each colour band on
    (1, nx, ny, 1 - nz). Returns an array (rows, cols, 4 terms, 3 bands)."""
    feats = [np.ones_like(nx), nx, ny, 1.0 - nz]
    sigma = WINDOW_M / cell
    smooth = lambda a: gaussian_filter(a, sigma, mode="nearest")
    A = np.empty(nx.shape + (4, 4), dtype="float64")
    b = np.empty(nx.shape + (4, 3), dtype="float64")
    for i in range(4):
        for c in range(3):
            b[..., i, c] = smooth(weight * feats[i] * rgb[..., c])
        for j in range(i, 4):
            A[..., i, j] = A[..., j, i] = smooth(weight * feats[i] * feats[j])
    A[..., 0, 0] += 1e-6
    for i in range(1, 4):
        A[..., i, i] += RIDGE
    return np.linalg.solve(A, b).astype("float32")


def correlation(lum, nx, ny, mask):
    """How strongly brightness still follows slope direction (0 = not at all)."""
    l = np.log(np.clip(lum[mask], 1e-3, None))
    X = np.column_stack([np.ones(l.size), nx[mask], ny[mask]])
    coef, *_ = np.linalg.lstsq(X, l, rcond=None)
    return float(np.sqrt(1 - ((l - X @ coef) ** 2).sum() / ((l - l.mean()) ** 2).sum()))


def main():
    with open(os.path.join(WORK, "scene.json"), encoding="utf-8") as fh:
        cell = json.load(fh)["cell_m"]
    z = np.load(os.path.join(WORK, "dem.npy"))
    rows, cols = z.shape
    nx, ny, nz = normals(z, cell)
    tex = Image.open(os.path.join(WORK, "texture.jpg")).convert("RGB")

    # Photo brightness on the elevation grid (linear light)
    small = (np.asarray(tex.resize((cols, rows), Image.BOX), dtype="float32") / 255) ** 2.2
    lum = small @ LUMA

    # Shadow: darker and bluer than the surroundings
    blur = lambda a, metres: gaussian_filter(a, metres / cell, mode="nearest")
    loglum, blue = log_lum_blue(small)
    ref_lum, ref_blue = blur(loglum, REF_M), blur(blue, REF_M)
    sloping = ramp(np.degrees(np.arccos(nz)), SLOPE_DEG)
    mask = ramp(ref_lum - loglum, DARKER) * ramp(blue - ref_blue, BLUER) * sloping
    sunlit = 1.0 - mask
    print(f"marked as shadow: {float((mask > 0.5).mean()) * 100:.1f}% of the frame")

    s = FIT_STEP
    coef = fit_coefficients(small[::s, ::s], nx[::s, ::s], ny[::s, ::s], nz[::s, ::s],
                            cell * s, sunlit[::s, ::s])
    c0 = np.maximum(coef[:, :, 0, :], 1e-3)
    rel = coef[:, :, 1:, :] / c0[:, :, None, :]    # pattern relative to flat ground

    def shade_at(shape):
        """Fitted lighting pattern (per band) on a grid; flat ground = 1."""
        def up(a):
            return zoom(a, (shape[0] / a.shape[0], shape[1] / a.shape[1]), order=1)
        unx, uny, unz = up(nx), up(ny), up(nz)
        shade = np.stack([1.0 + up(rel[:, :, 0, c]) * unx + up(rel[:, :, 1, c]) * uny
                          + up(rel[:, :, 2, c]) * (1.0 - unz) for c in range(3)], -1)
        return np.clip(shade, 1 / GAIN[1], 1 / GAIN[0])

    # Inside shadow: the colour of sunlit ground nearby (after flattening),
    # plus the pixel's own brightness relative to the shadow around it
    flat10 = small / shade_at(lum.shape)
    sun_w = np.maximum(blur(sunlit, SHADOW_WIN_M), 1e-3)
    mu_sun = np.stack([blur(np.log(np.clip(flat10[..., c], 2e-3, None)) * sunlit,
                            SHADOW_WIN_M) / sun_w for c in range(3)], -1)
    mu_shadow = blur(loglum * mask, SHADOW_WIN_M) / np.maximum(blur(mask, SHADOW_WIN_M), 1e-3)

    def relit(ll, mu_sun_c, mu_sh):
        return mu_sun_c + np.clip(ll - mu_sh, -1.0, 1.0)

    result10 = np.exp(np.stack(
        [mask * relit(loglum, mu_sun[..., c], mu_shadow)
         + sunlit * np.log(np.clip(flat10[..., c], 2e-3, None)) for c in range(3)], -1))

    steep = np.degrees(np.arccos(nz)) > 15
    before = correlation(lum, nx, ny, steep)
    after = correlation(result10 @ LUMA, nx, ny, steep)
    print(f"brightness explained by slope direction on steep ground: "
          f"r = {before:.2f} before, {after:.2f} after")

    # Apply to the full-size imagery in strips to keep memory down
    out = Image.new("RGB", tex.size)
    tw, th = tex.size
    strip = 1500
    for top in range(0, th, strip):
        h = min(strip, th - top)
        # matching rows of the elevation grid, with a margin for interpolation
        r0 = max(int(top / th * rows) - 2, 0)
        r1 = min(int((top + h) / th * rows) + 3, rows)
        sub = slice(r0, r1)
        fy = (th / rows)
        def up(a):
            big = zoom(a, (fy, tw / a.shape[1]), order=1)
            off = int(round(top - r0 * fy))
            return big[off:off + h]
        rs = slice(r0 // s, max(r1 // s, r0 // s + 2))
        def up_coef(a):
            block = a[rs]
            big = zoom(block, ((r1 - r0) * fy / block.shape[0], tw / block.shape[1]),
                       order=1)
            off = int(round(top - r0 * fy))
            return big[off:off + h]
        unx, uny, unz = up(nx[sub]), up(ny[sub]), up(nz[sub])
        px = (np.asarray(tex.crop((0, top, tw, top + h)), dtype="float32") / 255) ** 2.2
        # shadow mask at full detail, against the same surroundings
        ll, bl = log_lum_blue(gaussian_filter(px, (0.7, 0.7, 0)))
        m = (ramp(up(ref_lum[sub]) - ll, DARKER) * ramp(bl - up(ref_blue[sub]), BLUER)
             * up(sloping[sub]))
        mu_sh = up(mu_shadow[sub])
        flat = np.empty_like(px)
        for c in range(3):
            shade = (1.0 + up_coef(rel[:, :, 0, c]) * unx + up_coef(rel[:, :, 1, c]) * uny
                     + up_coef(rel[:, :, 2, c]) * (1.0 - unz))
            shade = np.clip(shade, 1 / GAIN[1], 1 / GAIN[0])
            logv = (m * relit(ll, up(mu_sun[sub][..., c]), mu_sh)
                    + (1.0 - m) * (np.log(np.clip(px[..., c], 2e-3, None)) - np.log(shade)))
            flat[..., c] = np.clip(np.exp(logv), 0, 1) ** (1 / 2.2)
        out.paste(Image.fromarray((flat * 255 + 0.5).astype("uint8")), (0, top))
        print(f"  rows {top}-{top + h}", flush=True)
    out.save(os.path.join(WORK, "texture_flat.jpg"), quality=93, subsampling=0)

    # Side-by-side check image of the front range
    box = (int(tw * 0.22), int(th * 0.55), int(tw * 0.62), int(th * 0.80))
    a, b = tex.crop(box), out.crop(box)
    both = Image.new("RGB", (a.width, a.height * 2))
    both.paste(a, (0, 0))
    both.paste(b, (0, a.height))
    both.thumbnail((1600, 2000))
    both.save(os.path.join(WORK, "deshade_check.jpg"), quality=88)
    print("wrote texture_flat.jpg and deshade_check.jpg (top: before, bottom: after)")


if __name__ == "__main__":
    main()
