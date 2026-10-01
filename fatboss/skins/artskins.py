"""Illustrated skins (skins s8): art painted on the gun's side view, like CS2's finest.

Each design paints a canvas that is the gun seen from its left side (x along the gun, the muzzle on the left, y
down) and is baked into every texel of the weapon texture at the side-view point it sits on, the way gunspace.py
does it (both flanks share the texels). A Layout says where on the canvas the gun really is (its flank, and along
x the band of the receiver, slide and barrel, not the magazine or grip hanging below), so a dragon, a serpent or
a line of text runs along the gun as the player sees it and not across empty canvas.

Chosen by the user from round 18's proposal boards (2026-09-30): 28 finishes, 19 premium and 9 fun ones.
build_skins.py calls build(theme, tex, div) for the themes in ART_THEMES.
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import gunspace as gs
import textskins as ts

FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
CANVAS = 2048           # canvas width for a 4k texture: about a texel per canvas pixel on the flank (the proposal
                        # boards were drawn at 1600, and the designs' fixed line widths are in canvas pixels)


# ---------------------------------------------------------------------------------------------- canvas helpers
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), max(4, int(size)))

def grid(W, H):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    return x, y

def noise(W, H, seed, scale=1.0, octaves=5, sx=1.0, sy=1.0):
    """fbm 0..1 over the canvas; scale ~ features per canvas height."""
    x, y = grid(W, H)
    return gs.fbm2(x / H * scale * sx, y / H * scale * sy, seed, octaves, 1.0)

def ramp(t, stops):
    return ts.ramp(np.clip(t, 0, 1), stops).astype(np.float32)

def solid(W, H, c):
    return np.broadcast_to(np.array(c, np.float32), (H, W, 3)).copy()

def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)

def mix(a, b, t):
    t = np.asarray(t, np.float32)
    if t.ndim == 2:
        t = t[..., None]
    return a + (b - a) * t

class Layer:
    """An RGBA layer drawn with PIL at 2x and scaled down (anti-aliased)."""

    def __init__(self, W, H, ss=2):
        self.W, self.H, self.ss = W, H, ss
        self.img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def p(self, pts):
        return [(x * self.ss, y * self.ss) for x, y in pts]

    def poly(self, pts, fill, outline=None, width=0):
        self.d.polygon(self.p(pts), fill=fill, outline=outline, width=int(width * self.ss) if outline else 0)

    def line(self, pts, fill, width, joint="curve"):
        self.d.line(self.p(pts), fill=fill, width=max(1, int(width * self.ss)), joint=joint)

    def ellipse(self, box, fill, outline=None, width=0):
        x0, y0, x1, y1 = box
        self.d.ellipse((x0 * self.ss, y0 * self.ss, x1 * self.ss, y1 * self.ss), fill=fill, outline=outline,
                       width=int(width * self.ss) if outline else 0)

    def circle(self, cx, cy, r, fill, outline=None, width=0):
        self.ellipse((cx - r, cy - r, cx + r, cy + r), fill, outline, width)

    def text(self, xy, s, f, fill, stroke=0, stroke_fill=None, anchor="mm"):
        fnt = font(f[0], f[1] * self.ss)
        self.d.text((xy[0] * self.ss, xy[1] * self.ss), s, font=fnt, fill=fill, anchor=anchor,
                    stroke_width=int(stroke * self.ss), stroke_fill=stroke_fill)

    def rgba(self, blur=0):
        im = self.img.resize((self.W, self.H), Image.LANCZOS)
        if blur:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        return np.asarray(im, np.float32) / 255.0

def over(base, rgba, opacity=1.0):
    a = rgba[..., 3:4] * opacity
    return base * (1 - a) + rgba[..., :3] * a

def add(base, rgba, strength=1.0):
    return base + rgba[..., :3] * rgba[..., 3:4] * strength

def glow_of(rgba, radius, strength=1.0):
    im = Image.fromarray(np.clip(rgba * 255, 0, 255).astype(np.uint8), "RGBA").filter(ImageFilter.GaussianBlur(radius))
    g = np.asarray(im, np.float32) / 255.0
    return g[..., :3] * g[..., 3:4] * strength

def blurf(a, r):
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), np.float32) / 255.0

def voronoi(W, H, n, seed, jitter=1.0):
    """(F1, F2, cell id) of n random points over the canvas (distances in canvas px)."""
    rng = np.random.default_rng(seed)
    pts = rng.random((n, 2)) * [W, H]
    x, y = grid(W, H)
    f1 = np.full((H, W), 1e9, np.float32)
    f2 = np.full((H, W), 1e9, np.float32)
    idx = np.zeros((H, W), np.int32)
    for i, (px, py) in enumerate(pts):
        d = np.hypot(x - px, y - py)
        closer = d < f1
        f2 = np.where(closer, f1, np.minimum(f2, d))
        idx = np.where(closer, i, idx)
        f1 = np.where(closer, d, f1)
    return f1, f2, idx

def sparkle(W, H, n, seed, size=1.5, color=(1, 1, 1)):
    L = Layer(W, H)
    rng = np.random.default_rng(seed)
    for _ in range(n):
        x, y, r = rng.random() * W, rng.random() * H, size * (0.4 + rng.random())
        a = int(120 + 135 * rng.random())
        c = tuple(int(v * 255) for v in color) + (a,)
        L.line([(x - r * 3, y), (x + r * 3, y)], c, max(1, r * 0.5))
        L.line([(x, y - r * 3), (x, y + r * 3)], c, max(1, r * 0.5))
        L.circle(x, y, r * 0.8, c)
    return L.rgba()

def bezier(pts, n=60):
    """Points on a Catmull-Rom spline through pts."""
    pts = np.asarray(pts, np.float64)
    out = []
    P = np.vstack([pts[0], pts, pts[-1]])
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(P[-2])
    return [tuple(p) for p in out]

def outline_of(path, widths):
    """A ribbon polygon around a path with a width at each point."""
    path = np.asarray(path)
    d = np.gradient(path, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1), 1e-6)[:, None]
    nrm = np.stack([-d[:, 1], d[:, 0]], 1)
    w = np.asarray(widths)[:, None] / 2
    left, right = path + nrm * w, path - nrm * w
    return [tuple(p) for p in left] + [tuple(p) for p in right[::-1]], nrm

class Layout:
    """Where the gun is on the canvas: the mask of its side (the flank texels), and along x the top band of it (the
    receiver, slide and barrel, not the magazine or grip hanging below): top(x), bottom(x), mid(x), height(x)."""

    def __init__(self, M, W, H):
        sel = M.cov & (np.abs(M.side) > 0.25)
        cx = np.clip((M.u[sel] * (W - 1)).astype(int), 0, W - 1)
        cy = np.clip((M.v[sel] * (H - 1)).astype(int), 0, H - 1)
        m = np.zeros((H, W), np.float32)
        np.add.at(m, (cy, cx), 1.0)
        im = Image.fromarray(((m > 0) * 255).astype(np.uint8))
        k = max(3, int(W / 160) | 1)
        im = im.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
        self.mask = np.asarray(im) > 0
        self.W, self.H = W, H
        top = np.full(W, np.nan)
        bot = np.full(W, np.nan)
        for xx in range(W):
            col = np.nonzero(self.mask[:, xx])[0]
            if not len(col):
                continue
            t = col[0]
            gaps = np.nonzero(np.diff(col) > 2)[0]
            b = col[gaps[0]] if len(gaps) else col[-1]
            # a very tall first run is the grip or magazine under the receiver: keep its upper part
            b = min(b, t + H * 0.32)
            top[xx], bot[xx] = t, b
        xs = np.arange(W)
        ok = ~np.isnan(top)
        top = np.interp(xs, xs[ok], top[ok])
        bot = np.interp(xs, xs[ok], bot[ok])
        k = max(1, W // 60)
        ker = np.ones(k) / k
        self._top = np.convolve(np.pad(top, k, mode="edge"), ker, "same")[k:-k]
        self._bot = np.convolve(np.pad(bot, k, mode="edge"), ker, "same")[k:-k]
        self.x0, self.x1 = float(xs[ok].min()), float(xs[ok].max())

    def top(self, x):
        return np.interp(x, np.arange(self.W), self._top)

    def bottom(self, x):
        return np.interp(x, np.arange(self.W), self._bot)

    def mid(self, x):
        return (self.top(x) + self.bottom(x)) / 2

    def height(self, x):
        return np.maximum(self.bottom(x) - self.top(x), self.H * 0.04)


# ---------------------------------------------------------------------------------------------- designs
def body_field(W, H, x0, x1, yfun, wfun):
    """A creature's body along x0..x1: per pixel d (-1 top edge .. 1 bottom edge), s (0 at x0 .. 1 at x1), mask.
    wfun(xs, t) is its width at xs (t the same 0..1)."""
    x, y = grid(W, H)
    s = np.clip((x - x0) / (x1 - x0), 0, 1)
    xs = np.linspace(x0, x1, 400)
    yc = np.interp(x, xs, yfun(xs))
    slope = np.interp(x, xs, np.gradient(yfun(xs), xs))
    w = np.interp(x, xs, wfun(xs, (xs - x0) / (x1 - x0)))
    d = (y - yc) / np.sqrt(1 + slope * slope) / (w / 2)
    mask = (np.abs(d) < 1) & (x >= x0) & (x <= x1)
    return d, s, mask, w

def scales(x, d, w, rows=4.0):
    """Overlapping scales in body coordinates: (rim 0..1, inside shade 0..1)."""
    u = x / (w * 0.42)
    v = (d + 1) * rows / 2
    row = np.floor(v)
    uu = u + (row % 2) * 0.5
    fx, fy = (uu % 1.0) - 0.5, v % 1.0
    r = np.hypot(fx * 1.1, fy - 0.05)
    rim = smooth(0.12, 0.0, np.abs(r - 0.52))
    inner = np.clip(1 - fy, 0, 1)
    return rim, inner

def meander(L, x0, x1, y, h, color, width):
    """A Greek-key band."""
    step = h * 1.6
    x = x0
    while x < x1:
        pts = [(x, y + h), (x, y), (x + step * 0.75, y), (x + step * 0.75, y + h * 0.7), (x + step * 0.3, y + h * 0.7),
               (x + step * 0.3, y + h * 0.35), (x + step * 0.55, y + h * 0.35)]
        L.line(pts, color, width, joint=None)
        L.line([(x, y + h), (x + step, y + h)], color, width)
        x += step
    L.line([(x0, y - width), (x1, y - width)], color, width)

def bottom_flames(W, H, seed, strength=1.0):
    """Flames licking up from the bottom of the canvas (the magazine, the grip)."""
    x, y = grid(W, H)
    t = 1 - y / H
    turb = noise(W, H, seed, 7.0, 4, sx=0.7, sy=1.4)
    heat = np.clip((0.55 - t) * 2.6 * (0.45 + 0.9 * turb), 0, 1) * strength
    col = ramp(heat, [(0, (0, 0, 0)), (0.3, (0.5, 0.04, 0.0)), (0.6, (1.0, 0.35, 0.02)), (0.85, (1.0, 0.75, 0.2)), (1, (1, 1, 0.8))])
    return col * smooth(0.05, 0.35, heat)[..., None]

def dragon_head(L, hx, hy, hl, hh, body, belly, dark, horn_col):
    """A dragon's head at (hx, hy) looking right (+x), jaw open."""
    P = lambda px, py: (hx + px * hl, hy + py * hh)  # noqa: E731
    L.poly([P(0.15, -0.30), P(-0.15, -0.74), P(-0.3, -0.84), P(-0.05, -0.36), P(0.0, -0.22)], horn_col, dark, 2)
    L.poly([P(0.30, -0.28), P(0.12, -0.64), P(0.02, -0.68), P(0.16, -0.30)], horn_col, dark, 2)
    L.poly([P(0.15, 0.10), P(0.90, 0.32), P(0.86, 0.44), P(0.25, 0.42), P(-0.05, 0.32)], belly, dark, 2.5)
    for k in range(7):
        tx = 0.85 - k * 0.1
        L.poly([P(tx, 0.02), P(tx - 0.035, 0.13), P(tx - 0.07, 0.02)], (250, 245, 225, 255))
        L.poly([P(tx - 0.02, 0.33), P(tx - 0.05, 0.21), P(tx - 0.08, 0.33)], (250, 245, 225, 255))
    L.poly([P(-0.05, -0.35), P(0.35, -0.40), P(0.72, -0.26), P(1.0, -0.12), P(1.02, 0.0), P(0.55, 0.02), P(0.1, 0.18), P(-0.08, 0.32)],
           body, dark, 2.5)
    L.poly([P(0.0, -0.33), P(0.35, -0.37), P(0.72, -0.24), P(0.95, -0.12), P(0.6, -0.2), P(0.2, -0.22)], horn_col)
    L.circle(*P(0.93, -0.07), hh * 0.035, (20, 0, 0, 255))
    E = Layer(L.W, L.H)
    E.ellipse((*P(0.28, -0.24), *P(0.42, -0.16)), (255, 200, 40, 255))
    L.line([P(0.26, -0.27), P(0.44, -0.27)], dark, hh * 0.03)
    return E, P(1.0, 0.2)

def doppler(W, H, seed, stops):
    x, y = grid(W, H)
    wx = x / H + 0.8 * noise(W, H, seed, 1.5)
    wy = y / H + 0.8 * noise(W, H, seed + 1, 1.5)
    fbm2 = gs.fbm2
    n = fbm2(wx * 1.3, wy * 1.3, seed + 2, 5, 1.0)
    n = np.clip((n - 0.32) / 0.38, 0, 1) ** 1.3
    c = ramp(n, stops)
    flake = noise(W, H, seed + 3, 60.0, 2)
    c = c * (0.85 + 0.3 * flake)[..., None]
    c = add(c, sparkle(W, H, int(W * H / 9000), seed + 4, H * 0.003), 0.8)
    return np.clip(c, 0, 1), 0.25, 0.12

HOWL = [(0.05, 0.02), (0.18, 0.06), (0.28, 0.12), (0.33, 0.03), (0.38, 0.16), (0.45, 0.24), (0.52, 0.36), (0.62, 0.45), (0.75, 0.55),
        (0.85, 0.66), (0.95, 0.7), (1.0, 0.84), (0.9, 0.88), (0.86, 0.98), (0.7, 1.0), (0.5, 1.0), (0.46, 0.97), (0.45, 0.72),
        (0.41, 0.97), (0.33, 1.0), (0.31, 0.6), (0.29, 0.45), (0.24, 0.32), (0.19, 0.21), (0.12, 0.15), (0.03, 0.12), (0.1, 0.08)]

def piece(L, kind, cx, by, h, fill, edge):
    w = h * 0.5
    L.poly([(cx - w * 0.55, by), (cx + w * 0.55, by), (cx + w * 0.45, by - h * 0.1), (cx - w * 0.45, by - h * 0.1)], fill, edge, 1.5)
    L.poly([(cx - w * 0.35, by - h * 0.1), (cx + w * 0.35, by - h * 0.1), (cx + w * 0.18, by - h * 0.62), (cx - w * 0.18, by - h * 0.62)], fill, edge, 1.5)
    L.poly([(cx - w * 0.32, by - h * 0.62), (cx + w * 0.32, by - h * 0.62), (cx + w * 0.26, by - h * 0.68), (cx - w * 0.26, by - h * 0.68)], fill, edge, 1.5)
    if kind == "pawn":
        L.circle(cx, by - h * 0.78, h * 0.13, fill, edge, 1.5)
    elif kind == "queen":
        pts = [(cx - w * 0.3, by - h * 0.68)]
        for k in range(5):
            px = cx - w * 0.3 + k * w * 0.15
            pts += [(px, by - h * 0.95), (px + w * 0.075, by - h * 0.8)]
        pts += [(cx + w * 0.3, by - h * 0.95), (cx + w * 0.3, by - h * 0.68)]
        L.poly(pts, fill, edge, 1.5)
    else:
        L.poly([(cx - w * 0.28, by - h * 0.68), (cx + w * 0.28, by - h * 0.68), (cx + w * 0.22, by - h * 0.86), (cx - w * 0.22, by - h * 0.86)], fill, edge, 1.5)
        L.line([(cx, by - h * 0.86), (cx, by - h * 1.02)], edge, h * 0.07)
        L.line([(cx - h * 0.07, by - h * 0.95), (cx + h * 0.07, by - h * 0.95)], edge, h * 0.07)
        L.line([(cx, by - h * 0.86), (cx, by - h * 1.02)], fill, h * 0.04)
        L.line([(cx - h * 0.07, by - h * 0.95), (cx + h * 0.07, by - h * 0.95)], fill, h * 0.04)

def d_wyrmfire(W, H, lay):
    """a crimson dragon breathing fire, gold scales, smoke"""
    x, y = grid(W, H)
    n = noise(W, H, 11, 2.5)
    c = ramp(y / H, [(0, (0.04, 0.10, 0.10)), (1, (0.01, 0.02, 0.03))])
    c = mix(c, solid(W, H, (0.09, 0.2, 0.18)), smooth(0.5, 0.85, n) * 0.55)
    c = c + bottom_flames(W, H, 12, 0.9)
    x0, x1 = lay.x0, lay.x0 + (lay.x1 - lay.x0) * 0.72
    yfun = lambda xs: lay.mid(xs) + 0.22 * lay.height(xs) * np.sin(xs / W * 2 * np.pi * 2.3 + 0.4)  # noqa: E731
    wfun = lambda xs, t: lay.height(xs) * (0.18 + 0.62 * t ** 0.8)  # noqa: E731
    d, s, mask, w = body_field(W, H, x0, x1, yfun, wfun)
    rim, inner = scales(x, d, w)
    base = ramp(s, [(0, (0.35, 0.02, 0.03)), (1, (0.65, 0.06, 0.04))])
    body = base * (0.45 + 0.7 * inner)[..., None]
    body = mix(body, solid(W, H, (0.98, 0.74, 0.28)), rim * 0.95)
    belly = smooth(0.35, 0.55, d)
    ridge = 0.75 + 0.25 * np.abs(np.sin(x / (w * 0.18) * np.pi))
    body = mix(body, solid(W, H, (0.92, 0.8, 0.52)) * ridge[..., None], belly)
    light = np.sqrt(np.clip(1 - d * d, 0, 1)) * (0.85 - 0.25 * d)
    body = body * (0.25 + 0.95 * light)[..., None]
    sh = blurf(mask.astype(np.float32), H * 0.01)
    c = c * (1 - 0.5 * np.roll(sh, int(H * 0.012), 0))[..., None]
    c = np.where(mask[..., None], body, c)
    L = Layer(W, H)
    for xx in np.arange(x0 + 0.02 * W, x1 - 0.01 * W, 0.024 * W):
        t = (xx - x0) / (x1 - x0)
        yy = float(yfun(np.array([xx]))[0]) - float(wfun(np.array([xx]), t)[0]) / 2 * 0.92
        hgt = float(wfun(np.array([xx]), t)[0]) * 0.5
        L.poly([(xx + hgt * 0.35, yy + 2), (xx - hgt * 0.5, yy - hgt), (xx - hgt * 0.35, yy + 2)], (120, 10, 12, 255), (250, 190, 80, 255), 1.5)
    hx, hy = x1 - 0.005 * W, float(yfun(np.array([x1]))[0])
    bh = float(lay.height(np.array([x1]))[0])
    eye, mouth = dragon_head(L, hx, hy, bh * 1.35, bh * 1.05, (170, 20, 14, 255), (130, 12, 10, 255), (30, 5, 5, 255), (240, 190, 110, 255))
    c = over(c, L.rgba())
    er = eye.rgba()
    c = over(c, er) + glow_of(er, H * 0.015, 1.2)
    mx, my = mouth
    fl = np.clip((x - mx) / max(W - mx, 1), 0, 1)
    wob = (noise(W, H, 13, 5.0, 4) - 0.5) * bh * 0.8
    rad = bh * (0.12 + 0.9 * fl)
    core = np.clip(1 - np.abs(y - my - wob * fl) / np.maximum(rad, 1), 0, 1) * (x > mx)
    heat = np.clip(core * (0.55 + 0.9 * noise(W, H, 14, 9.0, 4, sx=0.6)) * (1 - fl * 0.3), 0, 1)
    fire = ramp(heat, [(0, (0, 0, 0)), (0.25, (0.55, 0.05, 0.0)), (0.5, (1.0, 0.35, 0.02)), (0.75, (1.0, 0.75, 0.2)), (1.0, (1.0, 1.0, 0.85))])
    c = c + fire * smooth(0.05, 0.3, heat)[..., None] * 1.1
    c = add(c, sparkle(W, H, 90, 15, H * 0.004, (1.0, 0.6, 0.2)), 0.9)
    return np.clip(c, 0, 1), 0.3, 0.15

def d_jade_serpent(W, H, lay):
    """a jade serpent with gold-rimmed scales on veined ivory"""
    x, y = grid(W, H)
    n = noise(W, H, 21, 3.0)
    c = ramp(n, [(0.2, (0.86, 0.82, 0.70)), (0.6, (0.93, 0.90, 0.80)), (0.9, (0.80, 0.74, 0.62))])
    veins = smooth(0.02, 0.0, np.abs(noise(W, H, 22, 2.0, 5) - 0.5)) * 0.3
    c = c * (1 - veins)[..., None]
    L = Layer(W, H)
    gold = (190, 145, 50, 255)
    xs = np.arange(0, W, 4.0)
    for off in (0.1, 0.16):
        L.line(list(zip(xs, lay.top(xs) + lay.height(xs) * off)), gold, H * 0.006)
        L.line(list(zip(xs, lay.bottom(xs) - lay.height(xs) * off)), gold, H * 0.006)
    ymax = float(lay.bottom(np.arange(W)).max())
    meander(L, 0, W, ymax + (H - ymax) * 0.35, (H - ymax) * 0.1, gold, H * 0.008)
    c = over(c, L.rgba())
    x0, x1 = lay.x0, lay.x0 + (lay.x1 - lay.x0) * 0.8
    yfun = lambda xs: lay.mid(xs) + 0.25 * lay.height(xs) * np.sin(xs / W * 2 * np.pi * 2.6 + 2.0)  # noqa: E731
    wfun = lambda xs, t: lay.height(xs) * (0.12 + 0.45 * t ** 0.6)  # noqa: E731
    d, s, mask, w = body_field(W, H, x0, x1, yfun, wfun)
    rim, inner = scales(x, d, w, 5)
    body = ramp(s + 0.15 * (noise(W, H, 23, 6.0) - 0.5), [(0, (0.02, 0.28, 0.2)), (0.5, (0.03, 0.42, 0.28)), (1, (0.05, 0.58, 0.36))])
    body = body * (0.5 + 0.6 * inner)[..., None]
    body = mix(body, solid(W, H, (0.95, 0.78, 0.3)), rim * 0.9)
    body = mix(body, solid(W, H, (0.92, 0.85, 0.55)), smooth(0.45, 0.65, d) * 0.85)
    light = np.sqrt(np.clip(1 - d * d, 0, 1)) * (0.85 - 0.25 * d)
    body = body * (0.3 + 0.9 * light)[..., None]
    sh = blurf(mask.astype(np.float32), H * 0.012)
    c = c * (1 - 0.4 * np.roll(np.roll(sh, int(H * 0.015), 0), int(H * 0.008), 1))[..., None]
    c = np.where(mask[..., None], body, c)
    L = Layer(W, H)
    hx, hy = x1 - 0.003 * W, float(yfun(np.array([x1]))[0])
    bh = float(lay.height(np.array([x1]))[0])
    hl, hh = bh * 0.9, bh * 0.6
    P = lambda px, py: (hx + px * hl, hy + py * hh)  # noqa: E731
    L.line([P(0.95, 0.05), P(1.3, 0.05), P(1.45, -0.1)], (200, 20, 30, 255), hh * 0.05)
    L.line([P(1.3, 0.05), P(1.45, 0.18)], (200, 20, 30, 255), hh * 0.05)
    L.poly([P(-0.05, -0.5), P(0.45, -0.55), P(0.85, -0.3), P(1.0, 0.0), P(0.85, 0.3), P(0.45, 0.5), P(-0.05, 0.45)], (20, 120, 80, 255),
           (170, 130, 40, 255), 2.5)
    L.poly([P(0.0, -0.45), P(0.45, -0.5), P(0.8, -0.25), P(0.5, -0.2), P(0.1, -0.2)], (60, 170, 110, 255))
    L.ellipse((*P(0.35, -0.28), *P(0.55, -0.08)), (230, 40, 30, 255), (20, 10, 10, 255), 1.5)
    L.line([P(0.45, -0.27), P(0.45, -0.1)], (10, 5, 5, 255), hh * 0.04)
    L.poly([P(0.78, 0.18), P(0.72, 0.45), P(0.66, 0.2)], (250, 250, 240, 255))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.12

def d_orbital(W, H, lay):
    """white, black and orange sci-fi panels"""
    x, y = grid(W, H)
    c = ramp(y / H, [(0, (0.97, 0.97, 0.96)), (1, (0.86, 0.87, 0.88))])
    span = lay.x1 - lay.x0
    cut = lay.mid(x) + lay.height(x) * 0.15 - (x - lay.x0 - span * 0.5) * (lay.height(x) * 0.9 / span)
    black = y > cut
    c = np.where(black[..., None], ramp(y / H, [(0, (0.12, 0.12, 0.13)), (1, (0.03, 0.03, 0.035))]), c)
    L = Layer(W, H)
    orange = (255, 105, 20, 255)
    xs = np.arange(0, W, 4.0)
    cutx = lay.mid(xs) + lay.height(xs) * 0.15 - (xs - lay.x0 - span * 0.5) * (lay.height(xs) * 0.9 / span)
    for off, wdt in ((-0.1, 0.05), (-0.2, 0.025)):
        L.line(list(zip(xs, cutx + lay.height(xs) * off)), orange, float(np.median(lay.height(xs))) * wdt)
    bh = float(np.median(lay.height(xs)))
    for i in range(9):
        bx = lay.x0 + span * 0.08 + i * bh * 0.22
        by = float(lay.top(np.array([bx]))[0]) + bh * 0.12
        L.poly([(bx, by), (bx + bh * 0.1, by), (bx + bh * 0.18, by + bh * 0.12), (bx + bh * 0.08, by + bh * 0.12)], (25, 25, 25, 255))
    cx = lay.x0 + span * 0.82
    cy = float(lay.mid(np.array([cx]))[0]) - bh * 0.1
    r = bh * 0.32
    L.circle(cx, cy, r, None, orange, bh * 0.04)
    L.circle(cx, cy, r * 0.55, None, (30, 30, 30, 255), bh * 0.025)
    L.line([(cx - r * 1.4, cy), (cx + r * 1.4, cy)], (30, 30, 30, 255), bh * 0.02)
    L.line([(cx, cy - r * 1.4), (cx, cy + r * 1.4)], (30, 30, 30, 255), bh * 0.02)
    tx = lay.x0 + span * 0.45
    L.text((tx, float(lay.top(np.array([tx]))[0]) + bh * 0.3), "ORB-7 // FATBOSS ARMS", ("consolab.ttf", bh * 0.13), (110, 110, 115, 255))
    L.text((tx, float(lay.bottom(np.array([tx]))[0]) - bh * 0.22), "ORBITAL", ("ariblk.ttf", bh * 0.28), (255, 105, 20, 255))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.55, 0.2

def d_synthwave(W, H, lay=None):
    x, y = grid(W, H)
    hor = H * 0.58
    sky = ramp(y / hor, [(0, (0.08, 0.02, 0.2)), (0.45, (0.45, 0.05, 0.45)), (0.8, (0.95, 0.25, 0.45)), (1, (1.0, 0.55, 0.3))])
    c = sky
    st = sparkle(W, int(hor * 0.6), 60, 41, H * 0.003)
    c[:st.shape[0]] = add(c[:st.shape[0]], st, 0.8)
    sx, sy, sr = W * 0.62, hor, H * 0.36
    dsun = np.hypot(x - sx, y - sy)
    sun = (dsun < sr) & (y < hor)
    gap = (y > sy - sr * 0.6) & (((sy - y) / (sr * 0.6) * 5.5) % 1.0 < 0.35 + 0.35 * (1 - (sy - y) / (sr * 0.6)))
    sunc = ramp((y - (sy - sr)) / sr, [(0, (1.0, 0.95, 0.35)), (0.6, (1.0, 0.45, 0.35)), (1, (0.95, 0.15, 0.55))])
    c = np.where((sun & ~gap)[..., None], sunc, c)
    c = c + glow_of(np.dstack([sunc, (sun & ~gap).astype(np.float32)]), H * 0.06, 0.5)
    L = Layer(W, H)
    rng = np.random.default_rng(42)
    for layer, col in ((0, (60, 10, 90, 255)), (1, (30, 5, 50, 255))):
        pts = [(0, hor)]
        xx = 0
        while xx < W:
            xx += W * (0.04 + 0.06 * rng.random())
            pts.append((xx, hor - H * (0.08 + 0.2 * rng.random()) * (0.6 if layer else 1.0)))
        pts.append((W, hor))
        L.poly(pts, col, (255, 60, 200, 255) if layer else None, 2)
    c = over(c, L.rgba())
    ground = y > hor
    c = np.where(ground[..., None], solid(W, H, (0.03, 0.0, 0.07)), c)
    L = Layer(W, H)
    for k in range(1, 12):
        gy = hor + (H - hor) * (k / 11) ** 1.8
        L.line([(0, gy), (W, gy)], (0, 230, 255, 255), 1.6)
    for k in range(-14, 15):
        L.line([(sx, hor), (sx + k * W * 0.09, H * 1.2)], (0, 230, 255, 255), 1.6)
    for px in (W * 0.1, W * 0.93):
        L.line([(px, H), (px + H * 0.05, hor - H * 0.3)], (10, 0, 20, 255), H * 0.025)
        for a in range(7):
            ang = math.radians(200 + a * 22)
            L.line([(px + H * 0.05, hor - H * 0.3), (px + H * 0.05 + math.cos(ang) * H * 0.2, hor - H * 0.3 + math.sin(ang) * H * 0.12 + H * 0.05)],
                   (10, 0, 20, 255), H * 0.02)
    g = L.rgba()
    c = over(c, g)
    c = c + glow_of(g, 3, 0.6) * np.array([0.3, 1.0, 1.0])
    return np.clip(c, 0, 1), 0.3, 0.1

def d_kintsugi(W, H, lay=None):
    x, y = grid(W, H)
    n = noise(W, H, 51, 2.0)
    c = ramp(n, [(0.2, (0.02, 0.02, 0.025)), (0.8, (0.08, 0.08, 0.09))])
    f1, f2, _ = voronoi(W, H, 26, 52)
    thick = H * (0.006 + 0.012 * noise(W, H, 53, 4.0))
    crack = smooth(thick, thick * 0.3, f2 - f1)
    gold = ramp(noise(W, H, 54, 8.0), [(0, (0.7, 0.45, 0.1)), (0.5, (1.0, 0.8, 0.35)), (1, (1.0, 0.95, 0.7))])
    c = mix(c, gold, crack)
    c = c + glow_of(np.dstack([gold, crack]), H * 0.01, 0.35)
    return np.clip(c, 0, 1), 0.5, 0.08

def d_magma(W, H, lay=None):
    f1, f2, idx = voronoi(W, H, 60, 71)
    n = noise(W, H, 72, 6.0)
    crust = ramp(n, [(0, (0.05, 0.04, 0.04)), (1, (0.2, 0.17, 0.16))])
    bevel = smooth(0, H * 0.06, f2 - f1)
    crust = crust * (0.5 + 0.5 * bevel)[..., None]
    lava_w = H * (0.012 + 0.02 * noise(W, H, 73, 3.0))
    lava = smooth(lava_w, lava_w * 0.2, f2 - f1)
    hot = ramp(lava * (0.7 + 0.5 * noise(W, H, 74, 10.0)), [(0, (0.4, 0.02, 0.0)), (0.5, (1.0, 0.35, 0.0)), (0.8, (1.0, 0.75, 0.1)), (1, (1.0, 1.0, 0.7))])
    c = mix(crust, hot, lava)
    c = c + glow_of(np.dstack([hot, lava]), H * 0.03, 0.9)
    return np.clip(c, 0, 1), 0.45, 0.08

def d_sapphire(W, H, lay=None):
    return doppler(W, H, 81, [(0.0, (0.0, 0.0, 0.06)), (0.35, (0.0, 0.03, 0.32)), (0.62, (0.0, 0.15, 0.75)), (0.85, (0.05, 0.42, 1.0)), (1.0, (0.4, 0.78, 1.0))])

def d_ruby(W, H, lay=None):
    return doppler(W, H, 91, [(0.0, (0.04, 0.0, 0.0)), (0.35, (0.28, 0.0, 0.02)), (0.62, (0.75, 0.02, 0.07)), (0.85, (1.0, 0.2, 0.25)), (1.0, (1.0, 0.75, 0.75))])

def d_black_pearl(W, H, lay=None):
    return doppler(W, H, 101, [(0.0, (0.01, 0.0, 0.03)), (0.4, (0.15, 0.02, 0.28)), (0.65, (0.05, 0.25, 0.45)), (0.88, (0.4, 0.75, 0.85)), (1.0, (0.85, 0.95, 1.0))])

def d_crimson_web(W, H, lay=None):
    n = noise(W, H, 111, 3.0)
    c = ramp(n, [(0, (0.03, 0.01, 0.01)), (1, (0.12, 0.03, 0.03))])
    L = Layer(W, H)
    rng = np.random.default_rng(112)
    red = (215, 20, 25, 255)
    for cx, cy, R in ((W * 0.18, H * 0.25, H * 0.8), (W * 0.62, H * 0.8, H * 0.9), (W * 0.95, H * 0.15, H * 0.7)):
        spokes = 14
        angs = [2 * math.pi * k / spokes + rng.random() * 0.2 for k in range(spokes)]
        for a in angs:
            L.line([(cx, cy), (cx + math.cos(a) * R, cy + math.sin(a) * R)], red, H * 0.006)
        for r in np.arange(R * 0.1, R, R * 0.09):
            for k in range(spokes):
                a0, a1 = angs[k], angs[(k + 1) % spokes] + (2 * math.pi if k == spokes - 1 else 0)
                p0 = (cx + math.cos(a0) * r, cy + math.sin(a0) * r)
                p1 = (cx + math.cos(a1) * r, cy + math.sin(a1) * r)
                am = (a0 + a1) / 2
                m = (cx + math.cos(am) * r * 0.9, cy + math.sin(am) * r * 0.9)
                L.line(bezier([p0, m, p1], 8), red, H * 0.004)
    g = L.rgba()
    c = c + glow_of(g, H * 0.008, 0.6) * np.array([1.0, 0.1, 0.1])
    c = over(c, g)
    return np.clip(c, 0, 1), 0.45, 0.12

def d_filigree(W, H, lay=None):
    x, y = grid(W, H)
    brushed = noise(W, H, 121, 40.0, 3, sx=0.05, sy=1.0)
    c = ramp(brushed, [(0, (0.03, 0.05, 0.14)), (1, (0.1, 0.14, 0.3))])
    L = Layer(W, H)
    gold, dark = (225, 180, 80, 255), (90, 60, 15, 255)
    xl = np.arange(0, W, 4.0)
    for f in (0.06, 0.12, 0.88, 0.94):
        L.line(list(zip(xl, lay.top(xl) + lay.height(xl) * f)), gold, H * 0.006)
    xs = np.linspace(-0.05 * W, 1.05 * W, 400)
    ys = lay.mid(xs) + 0.2 * lay.height(xs) * np.sin(xs / W * 2 * np.pi * 3.0)
    vine = list(zip(xs, ys))
    L.line(vine, dark, H * 0.022)
    L.line(vine, gold, H * 0.014)
    for k in range(18):
        t = k / 17
        i = int(t * 399)
        px, py = xs[i], ys[i]
        side = -1 if k % 2 else 1
        rr = float(lay.height(np.array([px]))[0]) * 0.42
        pts = []
        for j in range(60):
            a = j / 59 * 4.2
            r = rr * (1 - j / 70)
            pts.append((px + side * math.sin(a) * r * 0.9 + j * rr * 0.004, py - side * (1 - math.cos(a)) * r * 0.55))
        L.line(pts, dark, H * 0.016)
        L.line(pts, gold, H * 0.01)
        lx, ly = pts[20]
        L.poly([(lx, ly), (lx + rr * 0.35, ly - side * rr * 0.12), (lx + rr * 0.5, ly), (lx + rr * 0.3, ly + side * rr * 0.1)], gold, dark, 1)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.5, 0.1

def d_carbon(W, H, lay=None):
    x, y = grid(W, H)
    s = H * 0.022
    i, j = np.floor(x / s), np.floor(y / s)
    fx, fy = x / s - i, y / s - j
    twill = ((i + j) % 4) < 2
    tow = np.where(twill, np.sin(fy * np.pi), np.sin(fx * np.pi))
    c = solid(W, H, (0.05, 0.05, 0.055)) + (0.03 + 0.1 * tow ** 3)[..., None] * np.where(twill, 1.0, 0.7)[..., None]
    mid, hh = lay.mid(x), lay.height(x)
    band = np.abs(y - mid) < hh * 0.14
    c = np.where(band[..., None], solid(W, H, (0.78, 0.04, 0.05)) * (0.8 + 0.25 * tow)[..., None], c)
    pin = np.abs(np.abs(y - mid) - hh * 0.2) < hh * 0.025
    c = np.where(pin[..., None], solid(W, H, (0.92, 0.92, 0.92)), c)
    return np.clip(c, 0, 1), 0.4, 0.1

def d_aurora(W, H, lay=None):
    x, y = grid(W, H)
    c = ramp(y / H, [(0, (0.0, 0.01, 0.05)), (0.7, (0.02, 0.06, 0.15)), (1, (0.03, 0.08, 0.18))])
    c = add(c, sparkle(W, H, 120, 151, H * 0.002), 0.7)
    band_y = H * (0.3 + 0.12 * np.sin(x / W * 2 * np.pi * 1.4) + 0.08 * noise(W, H, 152, 1.5))
    streak = noise(W, H, 153, 14.0, 3, sx=1.0, sy=0.05)
    shape = np.exp(-((y - band_y) / (H * 0.18)) ** 2) * (y < band_y + H * 0.05)
    shape = shape + np.exp(-((y - band_y) / (H * 0.06)) ** 2) * 0.6
    inten = np.clip(shape * (0.3 + streak * 1.2), 0, 1.3)
    col = ramp((band_y - y) / (H * 0.3) + 0.3, [(0, (0.1, 1.0, 0.5)), (0.5, (0.1, 0.8, 0.8)), (1, (0.6, 0.2, 0.9))])
    c = c + col * inten[..., None] * 0.8
    L = Layer(W, H)
    L.poly([(0, H * 0.82), (W * 0.2, H * 0.62), (W * 0.35, H * 0.78), (W * 0.55, H * 0.58), (W * 0.75, H * 0.8), (W * 0.9, H * 0.66), (W, H * 0.75), (W, H), (0, H)],
           (190, 205, 225, 255))
    rng = np.random.default_rng(154)
    xx = 0.0
    while xx < W:
        th = H * (0.12 + 0.12 * rng.random())
        L.poly([(xx, H), (xx + th * 0.22, H - th), (xx + th * 0.44, H)], (5, 12, 18, 255))
        xx += th * 0.25
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.08

def d_sakura(W, H, lay=None):
    x, y = grid(W, H)
    c = ramp(noise(W, H, 161, 2.0), [(0, (0.02, 0.01, 0.01)), (1, (0.1, 0.03, 0.03))])
    mxp = lay.x0 + (lay.x1 - lay.x0) * 0.8
    moon = np.hypot(x - mxp, y - lay.mid(mxp)) < float(lay.height(np.array([mxp]))[0]) * 0.45
    c = np.where(moon[..., None], solid(W, H, (0.95, 0.9, 0.78)), c)
    c = c + glow_of(np.dstack([solid(W, H, (1.0, 0.9, 0.7)), moon.astype(np.float32)]), H * 0.05, 0.3)
    rng = np.random.default_rng(162)
    L = Layer(W, H)
    flowers = []

    def branch(px, py, ang, ln, wdt, depth):
        pts = [(px, py)]
        for _ in range(8):
            ang += (rng.random() - 0.5) * 0.5
            px, py = px + math.cos(ang) * ln / 8, py + math.sin(ang) * ln / 8
            pts.append((px, py))
        L.line(pts, (40, 20, 15, 255), wdt)
        flowers.extend(pts[3:])
        if depth:
            for _ in range(2):
                branch(*pts[int(4 + rng.random() * 4)], ang + (rng.random() - 0.5) * 1.6, ln * 0.6, wdt * 0.6, depth - 1)
    bh = float(np.median(lay.height(np.arange(W))))
    branch(lay.x1 + 0.02 * W, float(lay.top(np.array([lay.x1]))[0]) + bh * 0.3, math.pi + 0.05, (lay.x1 - lay.x0) * 0.8, bh * 0.12, 3)
    branch(lay.x0 + (lay.x1 - lay.x0) * 0.4, float(lay.bottom(np.array([lay.x0 + (lay.x1 - lay.x0) * 0.4]))[0]), -0.6, W * 0.25, bh * 0.08, 2)
    for fx, fy in flowers:
        for _ in range(4):
            ox, oy = fx + (rng.random() - 0.5) * bh * 0.45, fy + (rng.random() - 0.5) * bh * 0.45
            r = bh * (0.07 + rng.random() * 0.06)
            for k in range(5):
                a = k / 5 * 2 * math.pi + rng.random()
                L.circle(ox + math.cos(a) * r, oy + math.sin(a) * r, r * 0.75, (255, 170 + int(40 * rng.random()), 200, 255))
            L.circle(ox, oy, r * 0.35, (255, 235, 150, 255))
    for _ in range(40):
        px, py = rng.random() * W, rng.random() * H
        L.ellipse((px, py, px + H * 0.018, py + H * 0.01), (255, 190, 215, 220))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.35, 0.08

def d_hex(W, H, lay=None):
    x, y = grid(W, H)
    s = H * 0.07
    q = (x * math.sqrt(3) / 3 - y / 3) / s
    r = y * 2 / 3 / s
    cx, cz = q, r
    cy = -cx - cz
    rx, ry, rz = np.round(cx), np.round(cy), np.round(cz)
    dx, dy, dz = np.abs(rx - cx), np.abs(ry - cy), np.abs(rz - cz)
    fixx = (dx > dy) & (dx > dz)
    fixy = ~fixx & (dy > dz)
    rx = np.where(fixx, -ry - rz, rx)
    ry = np.where(fixy, -rx - rz, ry)
    rz = np.where(~fixx & ~fixy, -rx - ry, rz)
    px = s * math.sqrt(3) * (rx + rz / 2)
    py = s * 1.5 * rz
    dx, dy = x - px, y - py
    edge = np.maximum.reduce([np.abs(dx), np.abs(dx * 0.5 + dy * math.sqrt(3) / 2), np.abs(dx * 0.5 - dy * math.sqrt(3) / 2)]) / (s * math.sqrt(3) / 2)
    seam = smooth(0.86, 0.97, edge)
    cell = (rx * 7 + rz * 13) % 11
    lit = cell < 0.8
    base = ramp(noise(W, H, 171, 5.0), [(0, (0.06, 0.07, 0.08)), (1, (0.16, 0.17, 0.19))]) * (1.15 - 0.45 * edge)[..., None]
    c = np.where(lit[..., None], mix(base, solid(W, H, (0.2, 0.9, 1.0)), 0.55 * (1 - edge)), base)
    pulse = 0.5 + 0.5 * noise(W, H, 172, 3.0)
    glowc = solid(W, H, (0.2, 0.95, 1.0))
    c = mix(c, glowc, seam * pulse)
    c = c + glow_of(np.dstack([glowc, seam * pulse]), H * 0.012, 0.6)
    return np.clip(c, 0, 1), 0.45, 0.12

def d_holo(W, H, lay=None):
    x, y = grid(W, H)
    t = (x / W * 1.3 + y / H * 0.6 + 0.35 * noise(W, H, 181, 1.5)) % 1.0
    import colorsys
    hue = np.stack(np.vectorize(colorsys.hsv_to_rgb)(t, 0.45, 1.0), -1).astype(np.float32)
    lines = 0.94 + 0.06 * np.sin((x + y) / H * 90)
    c = hue * lines[..., None] * (0.75 + 0.3 * noise(W, H, 182, 3.0))[..., None]
    c = add(c, sparkle(W, H, 160, 183, H * 0.003), 0.9)
    return np.clip(c, 0, 1), 0.3, 0.1

def d_howl(W, H, lay):
    """a black wolf howling at a blood moon, flames below"""
    x, y = grid(W, H)
    c = ramp(y / H, [(0, (0.45, 0.02, 0.02)), (0.5, (0.85, 0.2, 0.03)), (1, (0.95, 0.45, 0.05))])
    c = c * (0.8 + 0.3 * noise(W, H, 191, 3.0))[..., None]
    span = lay.x1 - lay.x0
    mx = lay.x0 + span * 0.55
    bh = float(lay.height(np.array([mx]))[0])
    my = float(lay.mid(np.array([mx]))[0]) - bh * 0.1
    moon = np.hypot(x - mx, y - my)
    mr = bh * 0.75
    c = mix(c, ramp(moon / mr, [(0, (1.0, 0.9, 0.7)), (1, (1.0, 0.6, 0.35))]), (moon < mr).astype(np.float32))
    c = c + ramp(np.clip(1 - (moon - mr) / (bh * 0.8), 0, 1), [(0, (0, 0, 0)), (1, (0.6, 0.3, 0.1))]) * (moon >= mr)[..., None]
    L = Layer(W, H)
    rng = np.random.default_rng(192)
    xx = -0.02 * W
    while xx < W:
        fw = W * (0.02 + 0.03 * rng.random())
        top = H * (0.55 + 0.35 * rng.random())
        L.poly([(xx, H), (xx + fw * 0.3, top + H * 0.1), (xx + fw * 0.5, top), (xx + fw * 0.6, top + H * 0.12), (xx + fw, H)], (15, 0, 0, 255))
        xx += fw * 0.7
    wh = bh * 0.9
    wx0 = mx - wh * 0.45
    wy1 = float(lay.bottom(np.array([mx]))[0]) - bh * 0.04
    L.poly([(wx0 + px * wh * 1.1, wy1 - wh + py * wh) for px, py in HOWL], (10, 5, 5, 255))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.35, 0.12

def d_checkmate(W, H, lay):
    """marble chess board, gold king and queen"""
    x, y = grid(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    sq = max(bh * 0.34, H * 0.05)
    chk = ((np.floor(x / sq) + np.floor(y / sq)) % 2) == 0
    veins = smooth(0.03, 0.0, np.abs(noise(W, H, 201, 2.5, 5) - 0.5))
    white = ramp(noise(W, H, 202, 4.0), [(0, (0.82, 0.8, 0.76)), (1, (0.97, 0.96, 0.93))]) * (1 - 0.35 * veins)[..., None]
    black = ramp(noise(W, H, 203, 4.0), [(0, (0.03, 0.03, 0.035)), (1, (0.12, 0.12, 0.13))]) + (0.25 * veins)[..., None]
    c = np.where(chk[..., None], white, black)
    L = Layer(W, H)
    span = lay.x1 - lay.x0
    gold, edge = (235, 185, 70, 255), (80, 50, 10, 255)
    for f, kind, hf in ((0.8, "king", 1.0), (0.55, "queen", 0.95), (0.3, "pawn", 0.7), (0.12, "pawn", 0.7)):
        cx = lay.x0 + span * f
        piece(L, kind, cx, float(lay.bottom(np.array([cx]))[0]) - bh * 0.05, bh * 0.9 * hf, gold, edge)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.45, 0.12

def d_neon_oni(W, H, lay):
    """a neon oni mask on black, cyan and hot pink"""
    x, y = grid(W, H)
    c = ramp(y / H, [(0, (0.02, 0.01, 0.05)), (1, (0.05, 0.0, 0.08))])
    streak = smooth(0.8, 1.0, noise(W, H, 211, 10.0, 3, sx=0.1, sy=3.0))
    c = c + streak[..., None] * np.array([0.15, 0.0, 0.25])
    L = Layer(W, H)
    span = lay.x1 - lay.x0
    cx = lay.x0 + span * 0.72
    bh = float(lay.height(np.array([cx]))[0])
    cy = float(lay.mid(np.array([cx]))[0])
    r = bh * 0.5
    pink, cyan = (255, 40, 170, 255), (40, 240, 255, 255)
    face = [(cx + math.cos(a) * r * 0.85, cy + math.sin(a) * r) for a in np.linspace(0, 2 * math.pi, 50)]
    L.line(face, pink, bh * 0.04)
    for sgn in (-1, 1):
        L.line(bezier([(cx + sgn * r * 0.45, cy - r * 0.75), (cx + sgn * r * 0.75, cy - r * 1.2), (cx + sgn * r * 0.55, cy - r * 1.6)], 20), cyan, bh * 0.04)
        L.poly([(cx + sgn * r * 0.15, cy - r * 0.25), (cx + sgn * r * 0.62, cy - r * 0.45), (cx + sgn * r * 0.55, cy - r * 0.15)], None, cyan, bh * 0.03)
        L.line([(cx + sgn * r * 0.1, cy - r * 0.5), (cx + sgn * r * 0.7, cy - r * 0.72)], pink, bh * 0.045)
        L.line([(cx + sgn * r * 0.35, cy + r * 0.35), (cx + sgn * r * 0.28, cy + r * 0.7)], cyan, bh * 0.035)
    L.line([(cx - r * 0.5, cy + r * 0.4), (cx + r * 0.5, cy + r * 0.4)], pink, bh * 0.035)
    for k in range(-3, 4):
        L.poly([(cx + k * r * 0.12 - r * 0.05, cy + r * 0.4), (cx + k * r * 0.12, cy + r * 0.55), (cx + k * r * 0.12 + r * 0.05, cy + r * 0.4)], None, pink, bh * 0.02)
    for f in (0.1, 0.3, 0.45):
        px = lay.x0 + span * f
        L.circle(px, float(lay.mid(np.array([px]))[0]), bh * 0.3, None, cyan if f != 0.3 else pink, bh * 0.025)
    g = L.rgba()
    c = c + glow_of(g, bh * 0.08, 1.4) + glow_of(g, bh * 0.02, 1.0)
    c = over(c, g)
    return np.clip(c, 0, 1), 0.3, 0.1

def d_carpet(W, H, lay):
    """Grandma's PRL wall carpet"""
    x, y = grid(W, H)
    fib = noise(W, H, 301, 90.0, 2)
    c = solid(W, H, (0.45, 0.05, 0.07)) * (0.85 + 0.25 * fib)[..., None]
    L = Layer(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    cream, navy, black, gold = (225, 200, 150, 255), (25, 35, 80, 255), (20, 10, 10, 255), (200, 150, 60, 255)
    xs = np.arange(0, W, 4.0)
    for f, col in ((0.08, black), (0.14, cream), (0.86, cream), (0.92, black)):
        L.line(list(zip(xs, lay.top(xs) + lay.height(xs) * f)), col, bh * 0.045)
    step = bh * 0.55
    for i in range(int(W / step) + 2):
        px = i * step
        m = float(lay.mid(np.array([px]))[0])
        hh = float(lay.height(np.array([px]))[0]) * 0.32
        L.poly([(px, m - hh), (px + step * 0.45, m), (px, m + hh), (px - step * 0.45, m)], navy if i % 2 else gold, black, 2)
        L.poly([(px, m - hh * 0.55), (px + step * 0.25, m), (px, m + hh * 0.55), (px - step * 0.25, m)], cream, black, 1.5)
        L.circle(px, m, hh * 0.18, (180, 20, 30, 255), black, 1)
    for i in range(int(W / (step * 0.5))):
        px = i * step * 0.5
        yb = float(lay.bottom(np.array([px]))[0])
        for yy in np.arange(yb + bh * 0.3, H, bh * 0.45):
            L.poly([(px, yy - bh * 0.1), (px + bh * 0.1, yy), (px, yy + bh * 0.1), (px - bh * 0.1, yy)], cream if (i + int(yy)) % 2 else navy)
    c = over(c, L.rgba())
    return np.clip(c * (0.85 + 0.25 * fib)[..., None], 0, 1), 0.4, 0.05

def d_googly(W, H, lay):
    """googly eyes stuck all over it"""
    x, y = grid(W, H)
    c = ramp(noise(W, H, 321, 4.0), [(0, (0.18, 0.19, 0.21)), (1, (0.3, 0.31, 0.33))])
    rng = np.random.default_rng(322)
    sh = Layer(W, H)
    L = Layer(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    placed = []
    tries = 0
    while len(placed) < 70 and tries < 20000:
        tries += 1
        px, py = rng.random() * W, rng.random() * H
        r = max(bh, H * 0.14) * (0.12 + 0.3 * rng.random() ** 2)
        if not lay.mask[int(py) % H, int(px) % W]:
            continue
        if any(math.hypot(px - qx, py - qy) < r + qr for qx, qy, qr in placed):
            continue
        placed.append((px, py, r))
        sh.circle(px + r * 0.12, py + r * 0.15, r, (0, 0, 0, 200))
        L.circle(px, py, r, (250, 250, 250, 255), (40, 40, 40, 255), max(1.0, r * 0.06))
        a = rng.random() * 2 * math.pi
        L.circle(px + math.cos(a) * r * 0.35, py + math.sin(a) * r * 0.35 + r * 0.1, r * 0.55, (10, 10, 10, 255))
        L.circle(px - r * 0.35, py - r * 0.4, r * 0.18, (255, 255, 255, 220))
    c = over(c, sh.rgba(blur=bh * 0.04), 0.6)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.05

def d_duct_tape(W, H, lay):
    """held together with duct tape and zip ties"""
    x, y = grid(W, H)
    c = ramp(noise(W, H, 331, 6.0), [(0, (0.2, 0.2, 0.21)), (1, (0.38, 0.38, 0.4))])
    rng = np.random.default_rng(332)
    L = Layer(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    for _ in range(9):
        cx, cy = lay.x0 + rng.random() * (lay.x1 - lay.x0), 0
        cy = float(lay.mid(np.array([cx]))[0]) + (rng.random() - 0.5) * bh * 0.4
        ang = math.pi / 2 + (rng.random() - 0.5) * 0.9
        ln, wd = bh * (1.4 + rng.random()), bh * 0.42
        ca, sa = math.cos(ang), math.sin(ang)
        pts = []
        for t in np.linspace(-1, 1, 12):
            pts.append((cx + ca * ln / 2 * t - sa * wd / 2 * (1 + 0.08 * math.sin(t * 9)), cy + sa * ln / 2 * t + ca * wd / 2))
        for t in np.linspace(1, -1, 12):
            pts.append((cx + ca * ln / 2 * t + sa * wd / 2 * (1 + 0.08 * math.cos(t * 7)), cy + sa * ln / 2 * t - ca * wd / 2))
        g = int(165 + 30 * rng.random())
        L.poly(pts, (g, g, g + 5, 255), (110, 110, 115, 255), 1.5)
        for k in range(5):
            t = rng.random() * 2 - 1
            L.line([(cx + ca * ln / 2 * t - sa * wd * 0.45, cy + sa * ln / 2 * t + ca * wd * 0.45), (cx + ca * ln / 2 * (t + 0.15) + sa * wd * 0.45, cy + sa * ln / 2 * (t + 0.15) - ca * wd * 0.45)],
                   (g - 40, g - 40, g - 35, 255), 1.5)
    for f in (0.25, 0.6):
        px = lay.x0 + (lay.x1 - lay.x0) * f
        L.line([(px, float(lay.top(np.array([px]))[0]) - 5), (px + bh * 0.1, float(lay.bottom(np.array([px]))[0]) + 5)], (15, 15, 15, 255), bh * 0.06)
        L.poly([(px - bh * 0.06, float(lay.top(np.array([px]))[0]) + bh * 0.1), (px + bh * 0.1, float(lay.top(np.array([px]))[0]) + bh * 0.1),
                (px + bh * 0.1, float(lay.top(np.array([px]))[0]) + bh * 0.25), (px - bh * 0.06, float(lay.top(np.array([px]))[0]) + bh * 0.25)], (15, 15, 15, 255))
    tx = lay.x0 + (lay.x1 - lay.x0) * 0.45
    L.text((tx, float(lay.mid(np.array([tx]))[0])), "FIXED IT", ("impact.ttf", bh * 0.33), (15, 15, 15, 255))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.35, 0.15

def d_crayon(W, H, lay):
    """a kid drew on it with crayons"""
    x, y = grid(W, H)
    c = ramp(noise(W, H, 341, 20.0, 2), [(0, (0.9, 0.88, 0.82)), (1, (0.99, 0.98, 0.95))])
    rng = np.random.default_rng(342)
    L = Layer(W, H)
    bh = max(float(np.median(lay.height(np.arange(W)))), H * 0.14)

    def crayon(pts, col, w):
        for k in range(3):
            j = [(px + (rng.random() - 0.5) * w * 0.6, py + (rng.random() - 0.5) * w * 0.6) for px, py in pts]
            L.line(j, col + (170 + int(60 * rng.random()),), w * 0.55)
    span = lay.x1 - lay.x0
    sx = lay.x0 + span * 0.85
    sy = float(lay.top(np.array([sx]))[0]) + bh * 0.35
    crayon([(sx + math.cos(a) * bh * 0.22, sy + math.sin(a) * bh * 0.22) for a in np.linspace(0, 2 * math.pi, 20)], (250, 200, 0), bh * 0.06)
    for a in np.linspace(0, 2 * math.pi, 10, endpoint=False):
        crayon([(sx + math.cos(a) * bh * 0.3, sy + math.sin(a) * bh * 0.3), (sx + math.cos(a) * bh * 0.45, sy + math.sin(a) * bh * 0.45)], (250, 200, 0), bh * 0.05)
    hx = lay.x0 + span * 0.55
    hb = float(lay.bottom(np.array([hx]))[0]) - bh * 0.1
    crayon([(hx, hb), (hx + bh * 0.5, hb), (hx + bh * 0.5, hb - bh * 0.4), (hx, hb - bh * 0.4), (hx, hb)], (220, 30, 30), bh * 0.05)
    crayon([(hx - bh * 0.05, hb - bh * 0.4), (hx + bh * 0.25, hb - bh * 0.72), (hx + bh * 0.55, hb - bh * 0.4)], (120, 60, 20), bh * 0.05)
    for f in (0.2, 0.33):
        px = lay.x0 + span * f
        pb = float(lay.bottom(np.array([px]))[0]) - bh * 0.08
        crayon([(px, pb), (px + bh * 0.08, pb - bh * 0.25), (px + bh * 0.16, pb)], (30, 60, 220), bh * 0.04)
        crayon([(px + bh * 0.08, pb - bh * 0.25), (px + bh * 0.08, pb - bh * 0.5)], (30, 60, 220), bh * 0.04)
        crayon([(px - bh * 0.05, pb - bh * 0.4), (px + bh * 0.21, pb - bh * 0.4)], (30, 60, 220), bh * 0.04)
        crayon([(px + bh * 0.08 + math.cos(a) * bh * 0.08, pb - bh * 0.58 + math.sin(a) * bh * 0.08) for a in np.linspace(0, 2 * math.pi, 12)], (30, 60, 220), bh * 0.04)
    gx = np.arange(0, W, bh * 0.06)
    for px in gx:
        yb = float(lay.bottom(np.array([px]))[0])
        crayon([(px, yb + 2), (px + bh * 0.03, yb - bh * 0.12)], (40, 170, 40), bh * 0.035)
    L.text((lay.x0 + span * 0.2, float(lay.top(np.array([lay.x0 + span * 0.2]))[0]) + bh * 0.3), "MY GUN :)", ("comicbd.ttf", bh * 0.26), (230, 40, 160, 230))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.05

def d_ducky(W, H, lay):
    """rubber duckies and bubbles on bath tiles"""
    x, y = grid(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    t = bh * 0.3
    grout = (np.abs((x % t) - t / 2) > t * 0.46) | (np.abs((y % t) - t / 2) > t * 0.46)
    c = np.where(grout[..., None], solid(W, H, (0.95, 0.97, 0.98)), ramp(noise(W, H, 351, 3.0), [(0, (0.45, 0.72, 0.85)), (1, (0.6, 0.85, 0.95))]))
    rng = np.random.default_rng(352)
    L = Layer(W, H)
    u = max(bh, H * 0.16)
    for _ in range(int(W / (u * 0.9))):
        px, py = rng.random() * W, rng.random() * H
        r = u * (0.42 + 0.14 * rng.random())
        flip = 1 if rng.random() < 0.5 else -1
        L.ellipse((px - r, py - r * 0.55, px + r, py + r * 0.55), (255, 215, 0, 255), (200, 140, 0, 255), 1.5)
        hx = px + flip * r * 0.55
        L.circle(hx, py - r * 0.6, r * 0.42, (255, 215, 0, 255), (200, 140, 0, 255), 1.5)
        L.poly([(hx + flip * r * 0.35, py - r * 0.62), (hx + flip * r * 0.75, py - r * 0.55), (hx + flip * r * 0.35, py - r * 0.45)], (255, 120, 0, 255))
        L.circle(hx + flip * r * 0.12, py - r * 0.72, r * 0.07, (10, 10, 10, 255))
        L.ellipse((px - flip * r * 0.1 - r * 0.35, py - r * 0.15, px - flip * r * 0.1 + r * 0.35, py + r * 0.2), (240, 190, 0, 255))
    for _ in range(int(W / 12)):
        px, py, r = rng.random() * W, rng.random() * H, bh * (0.02 + 0.06 * rng.random())
        L.circle(px, py, r, (255, 255, 255, 60), (255, 255, 255, 200), 1.2)
        L.circle(px - r * 0.35, py - r * 0.35, r * 0.2, (255, 255, 255, 230))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.05

def d_hot_dog(W, H, lay):
    """Hot Dog Stand colours, hot dogs and mustard"""
    x, y = grid(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    stripe = ((x + y * 0.5) // (max(bh, H * 0.16) * 0.5)) % 2 == 0
    c = np.where(stripe[..., None], solid(W, H, (0.95, 0.05, 0.05)), solid(W, H, (1.0, 0.9, 0.0)))
    rng = np.random.default_rng(361)
    L = Layer(W, H)
    u = max(bh, H * 0.16)
    for _ in range(int(W / (u * 0.8))):
        px, py = rng.random() * W, rng.random() * H
        ln = u * (1.1 + 0.3 * rng.random())
        ang = (rng.random() - 0.5) * 1.2
        ca, sa = math.cos(ang), math.sin(ang)
        bun = outline_of([(px - ca * ln / 2, py - sa * ln / 2), (px + ca * ln / 2, py + sa * ln / 2)], [ln * 0.34, ln * 0.34])[0]
        L.poly(bun, (230, 170, 90, 255), (140, 80, 30, 255), 1.5)
        sau = outline_of([(px - ca * ln * 0.6, py - sa * ln * 0.6), (px + ca * ln * 0.6, py + sa * ln * 0.6)], [ln * 0.17, ln * 0.17])[0]
        L.poly(sau, (170, 50, 30, 255), (90, 20, 10, 255), 1.5)
        L.line([(px - ca * ln * 0.45 + sa * ((k % 2) - 0.5) * ln * 0.1, py - sa * ln * 0.45 - ca * ((k % 2) - 0.5) * ln * 0.1)
                if False else (px + ca * ln * (k / 7 - 0.45) - sa * ((k % 2) - 0.5) * ln * 0.08, py + sa * ln * (k / 7 - 0.45) + ca * ((k % 2) - 0.5) * ln * 0.08)
                for k in range(8)], (255, 230, 0, 255), ln * 0.04)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.05

def d_princess(W, H, lay):
    """pink glitter, rainbows and PRINCESS"""
    x, y = grid(W, H)
    c = ramp(x / W + 0.2 * noise(W, H, 371, 2.0), [(0, (1.0, 0.6, 0.85)), (0.5, (0.85, 0.6, 1.0)), (1, (1.0, 0.7, 0.8))])
    c = add(c, sparkle(W, H, int(W * H / 500), 372, H * 0.002), 0.9)
    L = Layer(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    cols = [(255, 60, 60, 255), (255, 160, 40, 255), (255, 235, 60, 255), (80, 210, 90, 255), (60, 140, 255, 255), (170, 90, 255, 255)]
    for f in (0.15, 0.7):
        cx = lay.x0 + (lay.x1 - lay.x0) * f
        cy = float(lay.bottom(np.array([cx]))[0])
        for k, col in enumerate(cols):
            r = bh * (0.75 - k * 0.07)
            L.line([(cx + math.cos(a) * r, cy - math.sin(a) * r) for a in np.linspace(0, math.pi, 40)], col, bh * 0.07)
    rng = np.random.default_rng(373)
    for _ in range(int(W / (bh * 0.4))):
        px, py, r = rng.random() * W, rng.random() * H, bh * (0.05 + 0.06 * rng.random())
        L.poly([(px, py + r), (px - r, py), (px - r * 0.5, py - r * 0.6), (px, py - r * 0.2), (px + r * 0.5, py - r * 0.6), (px + r, py)], (255, 255, 255, 230))
    tx = lay.x0 + (lay.x1 - lay.x0) * 0.45
    L.text((tx, float(lay.mid(np.array([tx]))[0])), "PRINCESS", ("BAUHS93.TTF", bh * 0.42), (255, 255, 255, 255), bh * 0.04, (230, 60, 160, 255))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.05

def d_laser_cats(W, H, lay):
    """cats with laser eyes in space"""
    x, y = grid(W, H)
    c = ramp(noise(W, H, 381, 2.0), [(0, (0.02, 0.01, 0.08)), (1, (0.15, 0.05, 0.3))])
    c = add(c, sparkle(W, H, 150, 382, H * 0.002), 0.8)
    L = Layer(W, H)
    B = Layer(W, H)
    rng = np.random.default_rng(383)
    bh = max(float(np.median(lay.height(np.arange(W)))), H * 0.15)
    for f in (0.12, 0.42, 0.75):
        cx = lay.x0 + (lay.x1 - lay.x0) * f
        cy = float(lay.mid(np.array([cx]))[0])
        r = bh * 0.38
        col = [(255, 150, 60, 255), (200, 200, 210, 255), (60, 60, 70, 255)][int(f * 3) % 3]
        L.poly([(cx - r * 0.9, cy - r * 0.2), (cx - r * 0.7, cy - r * 1.15), (cx - r * 0.2, cy - r * 0.8)], col, (10, 10, 10, 255), 2)
        L.poly([(cx + r * 0.9, cy - r * 0.2), (cx + r * 0.7, cy - r * 1.15), (cx + r * 0.2, cy - r * 0.8)], col, (10, 10, 10, 255), 2)
        L.ellipse((cx - r, cy - r * 0.85, cx + r, cy + r * 0.8), col, (10, 10, 10, 255), 2)
        for sgn in (-1, 1):
            ex, ey = cx + sgn * r * 0.38, cy - r * 0.1
            L.circle(ex, ey, r * 0.16, (255, 40, 40, 255))
            B.line([(ex, ey), (ex - W * 0.35, ey + (rng.random() - 0.3) * bh * 0.8)], (255, 30, 30, 255), bh * 0.03)
        L.poly([(cx - r * 0.08, cy + r * 0.15), (cx + r * 0.08, cy + r * 0.15), (cx, cy + r * 0.25)], (255, 120, 150, 255))
        for sgn in (-1, 1):
            for k in (-1, 1):
                L.line([(cx + sgn * r * 0.2, cy + r * 0.25), (cx + sgn * r * 1.1, cy + r * 0.25 + k * r * 0.12)], (10, 10, 10, 255), 1.5)
    beams = B.rgba()
    c = c + glow_of(beams, bh * 0.05, 1.5)
    c = over(c, beams)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.05

def d_honk(W, H, lay):
    """clown: polka dots, rainbow ruffle, HONK HONK"""
    x, y = grid(W, H)
    c = solid(W, H, (0.98, 0.97, 0.95))
    L = Layer(W, H)
    bh = float(np.median(lay.height(np.arange(W))))
    cols = [(240, 40, 40, 255), (40, 120, 240, 255), (250, 200, 0, 255), (60, 190, 80, 255), (170, 70, 220, 255)]
    step = bh * 0.3
    for i in range(int(W / step) + 1):
        for j in range(int(H / step) + 1):
            L.circle(i * step + (j % 2) * step / 2, j * step, bh * 0.08, cols[(i * 3 + j) % 5])
    xs = np.arange(0, W, 4.0)
    for k, col in enumerate(cols):
        L.line(list(zip(xs, lay.top(xs) + bh * (0.06 + 0.05 * k) + np.sin(xs / (bh * 0.12)) * bh * 0.03)), col, bh * 0.05)
    tx = lay.x0 + (lay.x1 - lay.x0) * 0.4
    L.text((tx, float(lay.mid(np.array([tx]))[0]) + bh * 0.12), "HONK HONK", ("comicbd.ttf", bh * 0.34), (240, 30, 30, 255), bh * 0.035, (20, 20, 20, 255))
    nx = lay.x0 + (lay.x1 - lay.x0) * 0.85
    L.circle(nx, float(lay.mid(np.array([nx]))[0]), bh * 0.28, (230, 20, 20, 255), (120, 0, 0, 255), 2)
    L.circle(nx - bh * 0.08, float(lay.mid(np.array([nx]))[0]) - bh * 0.1, bh * 0.07, (255, 180, 180, 255))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.3, 0.05


# theme: (name in the Arsenal, design, how glossy (0..1), how metallic)
ART_THEMES = {
    "wyrmfire": ("Wyrmfire", d_wyrmfire, 0.55, 0.4),
    "jade_serpent": ("Jade Serpent", d_jade_serpent, 0.55, 0.3),
    "orbital": ("Orbital", d_orbital, 0.5, 0.1),
    "synthwave": ("Synthwave Sunset", d_synthwave, 0.45, 0.1),
    "kintsugi": ("Kintsugi", d_kintsugi, 0.75, 0.6),
    "magma": ("Magma Core", d_magma, 0.4, 0.3),
    "sapphire": ("Doppler Sapphire", d_sapphire, 0.9, 0.75),
    "ruby": ("Doppler Ruby", d_ruby, 0.9, 0.75),
    "black_pearl": ("Doppler Black Pearl", d_black_pearl, 0.9, 0.7),
    "crimson_web": ("Crimson Web", d_crimson_web, 0.55, 0.3),
    "filigree": ("Royal Filigree", d_filigree, 0.8, 0.7),
    "carbon": ("Carbon Strike", d_carbon, 0.55, 0.15),
    "aurora": ("Aurora", d_aurora, 0.45, 0.2),
    "sakura": ("Sakura Night", d_sakura, 0.55, 0.15),
    "hex_reactor": ("Hex Reactor", d_hex, 0.6, 0.4),
    "holo_prism": ("Holo Prism", d_holo, 0.85, 0.6),
    "blood_moon": ("Blood Moon Howl", d_howl, 0.4, 0.2),
    "checkmate": ("Checkmate", d_checkmate, 0.65, 0.2),
    "neon_oni": ("Neon Oni", d_neon_oni, 0.4, 0.2),
    "grandma_carpet": ("Grandma's Carpet", d_carpet, 0.1, 0.0),
    "googly_eyes": ("Googly Eyes", d_googly, 0.4, 0.05),
    "duct_tape": ("Duct Tape Special", d_duct_tape, 0.35, 0.3),
    "crayon_kid": ("Crayon Kid", d_crayon, 0.2, 0.0),
    "rubber_ducky": ("Rubber Ducky", d_ducky, 0.5, 0.05),
    "hot_dog_stand": ("Hot Dog Stand", d_hot_dog, 0.35, 0.05),
    "princess_mode": ("Princess Mode", d_princess, 0.55, 0.2),
    "laser_cats": ("Laser Cats", d_laser_cats, 0.35, 0.1),
    "honk_honk": ("Honk Honk", d_honk, 0.3, 0.05),
}


def build(theme, tex, div=1):
    """The finished texture (float RGB, 4k size / div) of an illustrated theme for one texture."""
    _name, design, _gloss, _metal = ART_THEMES[theme]
    M = gs.get_maps(tex, div)
    CW = max(1600, CANVAS // div)
    CH = max(64, int(round(CW / M.aspect)))
    canvas, keep, wear = design(CW, CH, Layout(M, CW, CH))
    cx = np.clip(M.u * (CW - 1), 0, CW - 1)
    cy = np.clip(M.v * (CH - 1), 0, CH - 1)
    x0, y0 = np.floor(cx).astype(int), np.floor(cy).astype(int)
    x1, y1 = np.minimum(x0 + 1, CW - 1), np.minimum(y0 + 1, CH - 1)
    fx, fy = (cx - x0)[..., None], (cy - y0)[..., None]
    rgb = ((canvas[y0, x0] * (1 - fx) + canvas[y0, x1] * fx) * (1 - fy) + (canvas[y1, x0] * (1 - fx) + canvas[y1, x1] * fx) * fy)
    shade, e = gs.stock_shade(tex, M.W, M.H)
    panel = 1 + keep * (np.clip(shade, 0.4, 1.2) - 1)
    out = rgb * panel[..., None]
    edge = np.clip((e - 0.35) / 0.4, 0, 1) * wear
    out = gs.mix(out, gs.col((0.72, 0.72, 0.74), M.u.shape), edge * 0.6)
    return np.clip(gs.dilate(np.clip(out, 0, 1).astype(np.float32), M.cov), 0, 1)
