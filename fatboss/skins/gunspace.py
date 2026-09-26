"""Gun-space skins: art laid out on the weapon's side view and baked into the texture atlas, like a CS2 finish.

Every texel the first-person model uses gets the 3D point it sits on (hand space, see textskins.py).
A design is a function of that point in the gun's own side-view frame: u along the gun (0 muzzle,
1 rear), v down (0 top, 1 bottom), plus the surface normal. Colours run on across UV islands, so a
gradient, a line or a painting follows the gun as you see it, not the texture layout. Texels that
several faces share go to the face that looks biggest on screen in first person.

build_skins.py calls build() for the themes in GUN_THEMES; wear_mask() makes the scratch mask the
skin shaders reveal with the wear of each copy.

    python fatboss/skins/gunspace.py board <out.jpg> --paks legacy_v2.86.0.pk3 pak0.pk3 [--designs ...]
"""
import argparse
import io
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textskins as ts  # noqa: E402

WEAPS = ["colt", "luger", "thompson", "mp40", "knife", "kabar"]
_MAPS = {}


def screen_area(tri, W=1600.0, H=900.0, fov_x=90.0):
    """Area a triangle covers on a 16:9 screen from the first-person camera (0 when off-screen)."""
    f = (W / 2) / math.tan(math.radians(fov_x) / 2)
    x = tri[:, 0]
    if (x < 1.0).any():
        return 0.0
    sx = W / 2 - f * tri[:, 1] / x
    sy = H / 2 - f * tri[:, 2] / x
    cx, cy = sx.mean(), sy.mean()
    if not (0 <= cx <= W and 0 <= cy <= H):
        return 0.0
    return float(abs((sx[1] - sx[0]) * (sy[2] - sy[0]) - (sx[2] - sx[0]) * (sy[1] - sy[0])) / 2)


def side_frame(m):
    """right (screen right in the side view), up, left (towards the viewer) of the first-person side view."""
    F = m.F
    Z = np.array([0, 0, 1.0])
    up = Z
    if m.tex in ("knife", "kabar"):
        up = np.cross(np.cross(F, Z), F)
        up = up / np.linalg.norm(up) if np.linalg.norm(up) > 0.2 else Z
    return -F, up, np.cross(up, F)


class Maps:
    """Per-texel side-view coordinates and normal terms of one texture at one size."""

    def __init__(self, tex, W, H):
        m = ts.mesh_of(tex)
        self.tex, self.W, self.H = tex, W, H
        right, up, left = side_frame(m)
        allp = m.P.reshape(-1, 3)
        a_all, b_all = allp @ right, allp @ up
        a0, a1, b0, b1 = a_all.min(), a_all.max(), b_all.min(), b_all.max()
        d_all = allp @ left
        u = np.zeros((H, W), np.float32)
        v = np.zeros((H, W), np.float32)
        side = np.zeros((H, W), np.float32)
        top = np.zeros((H, W), np.float32)
        cov = np.zeros((H, W), bool)
        uvpx = m.UV * np.array([W, H])
        order = sorted(range(len(m.P)), key=lambda i: (bool(m.facing[i]), screen_area(m.P[i]), m.area3[i]))
        for i in order:
            sx, sy = uvpx[i, :, 0], uvpx[i, :, 1]
            x0, x1 = int(max(0, np.floor(sx.min()))), int(min(W - 1, np.ceil(sx.max())))
            y0, y1 = int(max(0, np.floor(sy.min()))), int(min(H - 1, np.ceil(sy.max())))
            if x1 < x0 or y1 < y0:
                continue
            ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float32) + 0.5
            ax, ay, bx, by, cx, cy = sx[0], sy[0], sx[1], sy[1], sx[2], sy[2]
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            w0 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / den
            w1 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / den
            w2 = 1 - w0 - w1
            e = -0.02
            inside = (w0 >= e) & (w1 >= e) & (w2 >= e)
            if not inside.any():
                continue
            pa, pb = m.P[i] @ right, m.P[i] @ up
            sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
            u[sl][inside] = ((w0 * pa[0] + w1 * pa[1] + w2 * pa[2] - a0) / (a1 - a0))[inside]
            v[sl][inside] = ((b1 - (w0 * pb[0] + w1 * pb[1] + w2 * pb[2])) / (b1 - b0))[inside]
            side[sl][inside] = float(m.N[i] @ left)
            top[sl][inside] = float(m.N[i] @ up)
            cov[sl][inside] = True
        self.u, self.v, self.side, self.top, self.cov = u, v, side, top, cov
        self.aspect = float((a1 - a0) / (b1 - b0))
        self.X, self.Y = u * self.aspect, v


def get_maps(tex, div):
    key = (tex, div)
    if key not in _MAPS:
        _MAPS.clear()           # one texture at a time: 4k maps are big
        W, H = ts.SIZES[tex]
        _MAPS[key] = Maps(tex, W // div, H // div)
    return _MAPS[key]


def blur(a, radius):
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0


def edges(l, scale):
    """Panel lines of the stock texture: gradient magnitude of the smoothed luminance."""
    s = blur(l, scale * 1.5)
    gx = np.zeros_like(s)
    gy = np.zeros_like(s)
    gx[:, 1:-1] = s[:, 2:] - s[:, :-2]
    gy[1:-1, :] = s[2:, :] - s[:-2, :]
    g = np.sqrt(gx * gx + gy * gy)
    return np.clip(g / (np.percentile(g, 99.3) + 1e-6), 0, 1)


def stock_shade(tex, W, H):
    stock = Image.open(io.BytesIO(ts.read_file(ts.STOCK[tex]))).convert("RGB").resize((W, H), Image.LANCZOS)
    base = np.asarray(stock, np.float32) / 255.0
    l = ts.luminance(base)
    shade = np.clip(0.35 + 0.95 * (l / (np.percentile(l, 98) + 1e-6)), 0.25, 1.25)
    return shade, edges(l, W / 1024.0)


def dilate(rgb, cov, passes=12):
    """Push colours from covered texels into the empty ones around them (no seams in mipmaps)."""
    out, have = rgb.copy(), cov.copy()
    for _ in range(passes):
        acc = np.zeros_like(out)
        cnt = np.zeros(have.shape, np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sh = np.roll(np.roll(have, dy, 0), dx, 1)
            acc += np.roll(np.roll(out * have[..., None], dy, 0), dx, 1)
            cnt += sh
        grow = (~have) & (cnt > 0)
        out[grow] = acc[grow] / cnt[grow][:, None]
        have = have | grow
    out[~have] = rgb[cov].mean(0) if cov.any() else 0.5
    return out


# ---------------------------------------------------------------------------
# helpers for designs (all take the maps' arrays)

def ramp(t, stops):
    return ts.ramp(np.clip(t, 0, 1), stops)


def fbm2(x, y, seed, octaves=5, scale=1.0):
    """Smooth 2D noise at arbitrary points (value noise on a lattice, bilinear), 0..1."""
    rng = np.random.default_rng(seed)
    out = np.zeros_like(x, dtype=np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        f = scale * (2 ** o)
        n = 64
        g = rng.random((n + 1, n + 1)).astype(np.float32)
        xs, ys = (x * f) % n, (y * f) % n
        x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
        fx, fy = xs - x0, ys - y0
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        x1, y1 = (x0 + 1) % (n + 1), (y0 + 1) % (n + 1)
        v = (g[y0, x0] * (1 - fx) + g[y0, x1] * fx) * (1 - fy) + (g[y1, x0] * (1 - fx) + g[y1, x1] * fx) * fy
        out += amp * v
        tot += amp
        amp *= 0.5
    return out / tot


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    t = np.asarray(t, np.float32)
    return a + (b - a) * t[..., None]


def col(c, shape):
    return np.broadcast_to(np.array(c, np.float32), shape + (3,)).copy()


# ---------------------------------------------------------------------------
# designs: f(M) -> (rgb (H, W, 3) for covered texels, gloss 0..1 how much stock shading to keep, wear)

def d_fade(M):
    """Anodized fade: yellow at the muzzle through pink to violet at the back, polished."""
    t = M.u * 0.9 + 0.1 * (1 - M.v) + 0.05 * (fbm2(M.X, M.Y, 3, 3, 1.5) - 0.5)
    c = ramp(t, [(0.0, (1.0, 0.86, 0.2)), (0.35, (1.0, 0.45, 0.55)), (0.62, (0.85, 0.3, 0.8)), (1.0, (0.35, 0.25, 0.9))])
    return c, 0.35, 0.15


def d_nebula(M):
    """Deep space: black-violet candy with magenta and cyan nebula clouds and stars."""
    wx = M.X + 0.35 * fbm2(M.X, M.Y, 11, 4, 1.2)
    wy = M.Y + 0.35 * fbm2(M.X + 7, M.Y + 3, 12, 4, 1.2)
    n = fbm2(wx, wy, 13, 6, 1.8)
    n2 = fbm2(wx + 4, wy - 2, 14, 5, 2.4)
    base = col((0.06, 0.02, 0.15), M.u.shape)
    c = mix(base, col((0.7, 0.1, 0.75), M.u.shape), smooth(0.36, 0.68, n))
    c = mix(c, col((0.15, 0.8, 1.0), M.u.shape), smooth(0.48, 0.78, n2) * 0.85)
    c = mix(c, col((1.0, 0.9, 1.0), M.u.shape), smooth(0.66, 0.86, n) * 0.6)
    rng = np.random.default_rng(15)
    stars = rng.random(M.u.shape) > 0.9975
    c[stars] = (1, 1, 1)
    return c, 0.25, 0.1


def d_case(M):
    """Case hardened: blue, violet and gold heat patina on steel."""
    wx = M.X + 0.5 * fbm2(M.X, M.Y, 21, 3, 0.8)
    wy = M.Y + 0.5 * fbm2(M.X, M.Y, 22, 3, 0.8)
    n = fbm2(wx, wy, 23, 5, 1.6)
    c = ramp(n, [(0.25, (0.08, 0.14, 0.45)), (0.42, (0.25, 0.35, 0.8)), (0.5, (0.55, 0.45, 0.6)), (0.58, (0.85, 0.65, 0.3)),
                 (0.7, (0.55, 0.5, 0.45)), (0.85, (0.75, 0.75, 0.78))])
    return c, 0.55, 0.3


def d_redline(M):
    """Black carbon weave with one clean red line along the gun and a thin white pinstripe."""
    k = 60.0
    wx, wy = (M.X * k) % 2, (M.Y * k * 1.0) % 2
    weave = ((np.floor(wx) + np.floor(wy)) % 2)
    sx = np.abs(((M.X * k) % 1) - 0.5)
    sy = np.abs(((M.Y * k) % 1) - 0.5)
    band = np.where(weave > 0, sx, sy)
    carbon = 0.07 + 0.06 * (1 - band * 2)
    c = np.stack([carbon, carbon, carbon * 1.08], -1)
    line_v = 0.42 + 0.06 * np.sin(M.u * math.pi * 1.2)
    red = smooth(0.012, 0.0, np.abs(M.v - line_v) - 0.02)
    c = mix(c, col((0.85, 0.05, 0.05), M.u.shape), red)
    pin = smooth(0.004, 0.0, np.abs(M.v - line_v - 0.07) - 0.004)
    c = mix(c, col((0.92, 0.92, 0.92), M.u.shape), pin)
    tip = smooth(0.1, 0.06, M.u) * smooth(0.0, 0.02, 1 - M.v)
    c = mix(c, col((0.85, 0.05, 0.05), M.u.shape), tip * 0.9)
    return c, 0.45, 0.2


def d_frontier(M):
    """White armour, black belly split by a clean diagonal, orange blocks at the back and the muzzle."""
    c = col((0.93, 0.93, 0.92), M.u.shape)
    split = M.v > 0.55 - 0.2 * (M.u - 0.5)
    c[split] = (0.07, 0.07, 0.08)
    edge = smooth(0.006, 0.0, np.abs(M.v - (0.55 - 0.2 * (M.u - 0.5))) - 0.004)
    c = mix(c, col((1.0, 0.45, 0.05), M.u.shape), edge)
    rear = (M.u > 0.78) & (M.v < 0.5)
    c[rear] = (1.0, 0.45, 0.05)
    front = (M.u < 0.12) & (M.v < 0.5)
    c[front] = (1.0, 0.45, 0.05)
    chev = ((M.X * 14 + M.Y * 14) % 1 < 0.5) & (M.u > 0.8) & (M.u < 0.86) & (M.v < 0.5)
    c[chev] = (0.07, 0.07, 0.08)
    seam = (np.abs(((M.u * 7) % 1) - 0.5) > 0.495) & (M.v < 0.5)
    c[seam] *= 0.75
    return c, 0.6, 0.35


def d_glacier(M):
    """Ice shards: white, ice blue and navy facets with dark seams."""
    pts = np.random.default_rng(31).random((70, 2)) * np.array([M.aspect, 1.0])
    d1 = np.full(M.u.shape, 9.0, np.float32)
    d2 = np.full(M.u.shape, 9.0, np.float32)
    idx = np.zeros(M.u.shape, int)
    for k, (px, py) in enumerate(pts):
        d = np.hypot(M.X - px, M.Y - py)
        closer = d < d1
        d2 = np.where(closer, d1, np.minimum(d2, d))
        idx = np.where(closer, k, idx)
        d1 = np.where(closer, d, d1)
    palette = np.array([(0.95, 0.97, 1.0), (0.6, 0.82, 0.98), (0.12, 0.2, 0.42), (0.82, 0.9, 1.0), (0.3, 0.55, 0.85)], np.float32)
    rng = np.random.default_rng(32)
    choice = rng.integers(0, len(palette), len(pts))
    c = palette[choice[idx]]
    c = c * (0.9 + 0.2 * (1 - M.v))[..., None]
    seam = smooth(0.01, 0.0, d2 - d1)
    c = mix(c, col((0.03, 0.05, 0.1), M.u.shape), seam)
    return c, 0.45, 0.2


def d_pearl(M):
    """Pearl ink: iridescent white with flowing black strokes and a gold edge."""
    n = fbm2(M.X, M.Y, 41, 3, 0.8)
    irid = ramp((M.u + n * 0.6) % 1.0, [(0.0, (0.96, 0.95, 0.99)), (0.33, (0.93, 0.98, 0.96)), (0.66, (0.99, 0.94, 0.96)), (1.0, (0.96, 0.95, 0.99))])
    c = irid
    ink = np.zeros(M.u.shape, np.float32)
    for k, (amp, freq, off, w) in enumerate(((0.12, 2.1, 0.35, 0.012), (0.1, 3.3, 0.6, 0.008), (0.16, 1.4, 0.2, 0.006), (0.08, 4.2, 0.78, 0.005))):
        curve = off + amp * np.sin(M.u * math.pi * freq + k * 1.7) + 0.03 * fbm2(M.X, M.Y, 42 + k, 2, 2)
        ink = np.maximum(ink, smooth(w * 2.8, w * 0.9, np.abs(M.v - curve)))
    c = mix(c, col((0.04, 0.04, 0.05), M.u.shape), ink)
    gold = smooth(0.012, 0.0, np.abs(M.v - (0.35 + 0.12 * np.sin(M.u * math.pi * 2.1))) - 0.018) - ink
    c = mix(c, col((0.85, 0.65, 0.25), M.u.shape), np.clip(gold, 0, 1) * 0.9)
    return c, 0.5, 0.12


def d_inferno(M):
    """Flames licking up from the belly toward the muzzle, on matte black."""
    base = col((0.04, 0.035, 0.035), M.u.shape)
    n = fbm2(M.X * 1.3 + M.Y * 0.5, M.Y * 2.6, 51, 5, 2.4)
    height = 1 - M.v
    reach = 0.55 + 0.35 * M.u + 0.45 * (n - 0.5)
    flame = smooth(reach + 0.04, reach - 0.12, height)
    heat = np.clip(flame * (0.55 + 0.9 * np.clip(reach - height, 0, 1)), 0, 1)
    c = mix(base, ramp(heat, [(0.0, (0.3, 0.02, 0.0)), (0.4, (0.9, 0.2, 0.0)), (0.75, (1.0, 0.6, 0.05)), (1.0, (1.0, 0.95, 0.6))]), flame)
    rng = np.random.default_rng(55)
    embers = (rng.random(M.u.shape) > 0.999) & (flame < 0.2)
    c[embers] = (1.0, 0.6, 0.1)
    return c, 0.4, 0.25


def d_emerald(M):
    """Emerald: deep green candy with bright marbling and sparkle."""
    wx = M.X + 0.4 * fbm2(M.X, M.Y, 61, 4, 1.4)
    wy = M.Y + 0.4 * fbm2(M.X, M.Y, 62, 4, 1.4)
    n = fbm2(wx, wy, 63, 6, 2.0)
    c = ramp(n, [(0.2, (0.0, 0.12, 0.05)), (0.45, (0.02, 0.45, 0.18)), (0.6, (0.1, 0.8, 0.35)), (0.72, (0.7, 1.0, 0.8)), (0.8, (0.05, 0.5, 0.2))])
    rng = np.random.default_rng(65)
    sp = rng.random(M.u.shape) > 0.998
    c[sp] = (0.85, 1.0, 0.9)
    return c, 0.3, 0.1


def d_scales(M):
    """Dragon scale: rows of gold-edged scales on deep red, darker toward the back."""
    k = 13.0
    x, y = M.X * k, M.Y * k * 0.9
    row = np.floor(y)
    xx = x + (row % 2) * 0.5
    fx, fy = (xx % 1.0) - 0.5, (y % 1.0)
    d = np.hypot(fx, fy - 0.1)
    scale = smooth(0.5, 0.42, d)
    body = ramp(M.u, [(0.0, (0.75, 0.08, 0.05)), (1.0, (0.3, 0.02, 0.05))])
    c = body * (0.45 + 0.8 * (1 - fy) ** 1.5)[..., None]
    rim = smooth(0.08, 0.0, np.abs(d - 0.46))
    c = mix(c, col((0.95, 0.72, 0.25), M.u.shape), rim * scale)
    return c, 0.45, 0.2


def d_tiger(M):
    """Tiger gold: bright polished gold with dark amber tiger stripes."""
    n = fbm2(M.X * 0.5, M.Y * 3, 71, 3, 1.5)
    stripes = np.sin((M.X * 9 + n * 3.0) * math.pi)
    band = smooth(0.35, 0.8, stripes) * smooth(0.0, 0.1, 1 - M.v)
    gold = ramp(1 - M.v, [(0.0, (0.75, 0.5, 0.12)), (0.5, (1.0, 0.78, 0.3)), (1.0, (1.0, 0.9, 0.55))])
    c = mix(gold, col((0.35, 0.15, 0.03), M.u.shape), band * 0.9)
    return c, 0.35, 0.1


def d_marble(M):
    """Marble fire: red, orange and yellow swirl with a few blue streaks."""
    wx = M.X + 0.6 * fbm2(M.X, M.Y, 81, 4, 1.1)
    wy = M.Y + 0.6 * fbm2(M.X + 2, M.Y, 82, 4, 1.1)
    n = fbm2(wx, wy, 83, 5, 1.7)
    c = ramp(n, [(0.25, (0.55, 0.02, 0.02)), (0.45, (0.95, 0.2, 0.05)), (0.58, (1.0, 0.62, 0.1)), (0.68, (1.0, 0.9, 0.35)),
                 (0.72, (0.2, 0.35, 0.9)), (0.78, (0.9, 0.25, 0.05))])
    return c, 0.3, 0.1


DESIGNS = [("fade", "Fade", d_fade, 0.55), ("nebula", "Nebula", d_nebula, 0.5), ("case", "Case Hardened", d_case, 0.7),
           ("redline", "Red Line", d_redline, 0.45), ("frontier", "Frontier", d_frontier, 0.45), ("glacier", "Glacier", d_glacier, 0.5),
           ("pearl", "Pearl Ink", d_pearl, 0.55), ("inferno", "Inferno", d_inferno, 0.4), ("emerald", "Emerald", d_emerald, 0.6),
           ("scales", "Dragon Scale", d_scales, 0.5), ("tiger", "Tiger Gold", d_tiger, 0.7), ("marble", "Marble Fire", d_marble, 0.55)]



GUN_THEMES = tuple(k for k, _l, _f, _e in DESIGNS)
ENV = {k: e for k, _l, _f, e in DESIGNS}


def build(design, tex, div=1):
    """The finished texture of a gun-space theme: float RGB, 4k size / div."""
    M = get_maps(tex, div)
    fn = next(d for d in DESIGNS if d[0] == design)[2]
    rgb, keep, wear = fn(M)
    shade, e = stock_shade(tex, M.W, M.H)
    panel = 1 + keep * (np.clip(shade, 0.4, 1.2) - 1)       # keep the stock panel detail, less on bold designs
    out = rgb * panel[..., None]
    edge = np.clip((e - 0.35) / 0.4, 0, 1) * wear           # a little bright metal on sharp edges
    out = mix(out, col((0.72, 0.72, 0.74), M.u.shape), edge * 0.6)
    return np.clip(dilate(np.clip(out, 0, 1).astype(np.float32), M.cov), 0, 1)


REVEAL_MAX = 0.40    # share of the gun's surface bare at wear 1.0
REVEAL_POW = 1.6     # FN 0.03: ~0.2%, FT 0.26: ~5%, WW 0.41: ~10%, BS 0.72: ~24%


def wear_mask(tex, W, H, seed=7):
    """The scratch mask every skin of a texture shares (RGBA): bare steel where paint wears off.
    Alpha codes when a texel shows: 0 never, 254 first (the slightest wear) down to 128 (only at 1.0).
    The skin shader tests alpha x the copy's wear (alphaGen entity) against 128, so a Factory New
    copy shows next to nothing and a Battle-Scarred one every scratch."""
    rng = np.random.default_rng(seed + sum(map(ord, tex)))
    shade, e = stock_shade(tex, W, H)
    side = max(W, H)
    n1 = ts.fbm(side, rng, base=6, octaves=5)[:H, :W]
    n2 = ts.fbm(side, rng, base=24, octaves=3)[:H, :W]
    edge = blur(e, W / 1024.0 * 2.0)
    score = 0.65 * np.clip(edge * 1.6, 0, 1) ** 1.2 + 0.35 * np.clip((n1 - 0.45) * 3.0, 0, 1)
    score = score * (0.7 + 0.6 * n2)
    # scratches: thin strokes of random length and angle, some of them deep
    strokes = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(strokes)
    for _ in range(int(900 * W * H / (2048 * 2048))):
        x, y = rng.random() * W, rng.random() * H
        ang = rng.random() * math.pi
        ln = W * (0.004 + rng.random() ** 2 * 0.05)
        depth = int(90 + rng.random() ** 2 * 165)
        d.line((x, y, x + math.cos(ang) * ln, y + math.sin(ang) * ln), fill=depth, width=max(1, int(W / 1400)))
    s = np.asarray(strokes, np.float32) / 255.0
    score = np.maximum(score, s * (0.55 + 0.45 * n2))
    # the most worn texels first: rank them (smooth noise breaks ties, so no raster-order stripes) and give
    # each the float it shows at, so the bare area grows like CS2's: REVEAL_MAX * wear ** REVEAL_POW
    # only over the texels the model uses, so every weapon loses the same share of what you see
    cov = get_maps(tex, max(1, ts.SIZES[tex][0] // W)).cov
    if cov.shape != score.shape or not cov.any():
        cov = np.ones(score.shape, bool)
    flat = (score + 1e-3 * n2)[cov]
    r = np.empty(flat.size, np.float64)
    r[np.argsort(-flat, kind="stable")] = (np.arange(flat.size) + 0.5) / flat.size
    rank = np.ones(score.shape, np.float64)
    rank[cov] = r
    appear = (rank / REVEAL_MAX) ** (1.0 / REVEAL_POW)
    # the cgame sets the entity alpha to 127 + 128 * wear; the stage shows a texel where alpha x that >= 128 x 255
    alpha = np.where((rank < REVEAL_MAX) & (score > 0.02), np.ceil(128 * 255 / (127 + 128 * appear) + 1e-6), 0)
    alpha = np.where(alpha > 0, np.clip(alpha, 128, 254), 0)
    steel = np.clip(0.44 + 0.14 * n2 + 0.10 * (shade - 1), 0.28, 0.66)
    rgb = np.stack([steel * 0.95, steel * 0.97, steel], -1)
    out = np.dstack([np.clip(rgb * 255, 0, 255), alpha]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def board(out, designs, first=47):
    sw, sh, fw, fh = 400, 185, 300, 225
    left = 250
    rowh = max(sh, fh) + 12
    Wb = left + sw * len(WEAPS) + fw * 2
    b = Image.new("RGB", (Wb, 50 + rowh * len(designs)), (30, 32, 36))
    dr = ImageDraw.Draw(b)
    fb = ts.font("arialbd.ttf", 26)
    fs = ts.font("arial.ttf", 18)
    for j, name in enumerate(WEAPS):
        dr.text((left + j * sw + 12, 12), name, font=fb, fill=(255, 210, 60))
    dr.text((left + len(WEAPS) * sw + 12, 12), "FP colt", font=fb, fill=(255, 210, 60))
    dr.text((left + len(WEAPS) * sw + fw + 12, 12), "FP thompson", font=fb, fill=(255, 210, 60))
    labels = {k: v for k, v, _, _ in DESIGNS}
    for i, design in enumerate(designs):
        y = 50 + i * rowh
        if i % 2:
            dr.rectangle((0, y, Wb, y + rowh), fill=(36, 38, 43))
        dr.text((14, y + rowh // 2 - 26), f"{first + i}.", font=fb, fill=(255, 210, 60))
        dr.text((64, y + rowh // 2 - 26), labels.get(design, design), font=fb, fill=(255, 255, 255))
        dr.text((64, y + rowh // 2 + 8), design, font=fs, fill=(150, 155, 165))
        t0 = time.time()
        for j, tex in enumerate(WEAPS):
            arr = build(design, tex, div=4)
            m = ts.mesh_of(tex)
            s = ts.render_side(m, arr, +1, sw, sh)
            b.paste(s, (left + j * sw, y + (rowh - sh) // 2), s)
            if tex in ("colt", "thompson"):
                fp = ts.render_fp(m, arr, fw, fh)
                b.paste(fp, (left + len(WEAPS) * sw + (0 if tex == "colt" else fw), y + (rowh - fh) // 2), fp)
        print(design, round(time.time() - t0, 1), "s", flush=True)
    b.save(out, quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["board"])
    ap.add_argument("out")
    ap.add_argument("--paks", nargs="+", required=True)
    ap.add_argument("--designs", nargs="*")
    args = ap.parse_args()
    import build_skins
    ts.set_reader(build_skins.Paks(args.paks).read)
    board(args.out, args.designs or list(GUN_THEMES))


if __name__ == "__main__":
    main()
