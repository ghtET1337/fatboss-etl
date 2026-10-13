"""Illustrated skins s9: 36 more finishes painted on the gun's side view, made the way artskins.py makes s8.

Each design paints a canvas that is the gun seen from its left side (x along the gun, the muzzle on the left, y
down); build() bakes it into every texel of the weapon texture at the side-view point it sits on, exactly like
artskins.build (both flanks share the texels). artskins.Layout says where on the canvas the gun really is, so the
hero art sits on the receiver, slide and barrel and not on empty canvas.

Chosen by the owner from round 20's proposal boards (2026-10-12): 36 of 48, from neon comic beasts and engine
cutaways to cardboard, knitwear and an oil-painted landscape. They go into their own pk3, zzz_fatboss_skins_s9.pk3
(tree fatboss/pk3-skins-s9, see fatboss/skins/PACKS); build_skins.py calls build(theme, tex, div) for the themes in
ART_THEMES_S9.

The boards were drawn on a 1600 px wide canvas and the 4k build draws on CANVAS (2048) px. The designs size their art
from the band (the receiver's height), so a 2048 canvas looks like the board's 1600 one, checked side by side; only
where random things land differs a little. The few fixed pixel sizes left are hairline outlines and anti-alias blurs.

What changed against the boards (everything else is the design as picked): Hot Rod's pale barrel and thin rear
tongues, Baltic Amber (deep resin now; it read as orange plastic), Neon Riot's stamp-like splashes, Bullet Rain's gold
mush on the Thompson, Bubblegum and Disco Ball in first person, Wycinanki's flower off the KA-BAR's blade and Street
Wildstyle's tags over the letters.
"""
import math
from types import SimpleNamespace

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as _swv
from PIL import Image, ImageDraw, ImageFilter

import gunspace as gs
from artskins import (CANVAS, Layer, Layout, add, bezier, blurf, font, glow_of, grid, mix, noise, outline_of, over,
                      ramp, scales, smooth, solid, sparkle)

BOARD = 1600            # canvas width the proposal boards were drawn at


# ---------------------------------------------------------------------------------------------- set A helpers
# (round 20's set A: motifs sized from the receiver band, Env.RH, so they read on the MP 40, the Colt and the
# small Thompson alike)


def at(f, v):
    return float(np.asarray(f(np.array([float(v)])))[0])


def _box(a, r, axis):
    r = int(max(1, r))
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    p = np.pad(a, pad, mode="edge")
    cs = np.cumsum(p, axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(cs, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(cs, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def fblur(a, s):
    """Float gaussian-ish blur (three box passes), any number of channels."""
    a = np.asarray(a, np.float32)
    b = max(1, int(round(s * 0.95)))
    for _ in range(3):
        a = _box(_box(a, b, 0), b, 1)
    return a


def relief(h, k=1.0, light=(-0.55, -0.7, 0.45)):
    """Lambert shade of a height field, 1.0 on flat ground."""
    gy, gx = np.gradient(np.asarray(h, np.float32))
    nx, ny = -gx * k, -gy * k
    lv = np.array(light, np.float64)
    lv /= np.linalg.norm(lv)
    lam = (nx * lv[0] + ny * lv[1] + lv[2]) / np.sqrt(nx * nx + ny * ny + 1)
    return (lam / lv[2]).astype(np.float32)


def emboss(alpha, r, k=1.0):
    return relief(fblur(alpha, r), k * r * 2.2)


def shift(a, dx, dy):
    return np.roll(np.roll(a, int(dy), 0), int(dx), 1)


def gild(c, a, field, r, k=1.0, shadow=0.5, sh_off=1.2):
    """Paint field where alpha a is, raised (embossed light) with a drop shadow."""
    if shadow:
        s = fblur(shift(a, r * sh_off * 0.6, r * sh_off), r * 1.3)
        c = c * (1 - shadow * np.clip(s, 0, 1))[..., None]
    sh = np.clip(emboss(a, r, k), 0.2, 2.2)
    return mix(c, field * sh[..., None], a)


def goldf(W, H, seed, sc=5.0):
    n = noise(W, H, seed, sc, 3)
    return ramp(n, [(0, (0.42, 0.26, 0.05)), (0.4, (0.8, 0.58, 0.18)), (0.7, (1.0, 0.82, 0.4)), (1, (1.0, 0.96, 0.75))])


def alpha(L, blur=0):
    return L.rgba(blur)[..., 3]


class Env:
    """The band envelope: the receiver's real height where the band runs into gaps (MP 40 rear), a receiver range
    rx0..rx1 where the gun is tall, RH its typical height and cx its centre."""

    def __init__(self, lay, W, H):
        xs = np.arange(W, dtype=float)
        top, bot = lay.top(xs), lay.bottom(xs)
        ok = (top < 0.42 * H) & (xs >= lay.x0) & (xs <= lay.x1)
        top = np.interp(xs, xs[ok], top[ok])
        hh = np.interp(xs, xs[ok], np.clip(bot - top, H * 0.04, H * 0.4)[ok])
        k = max(2, int(W * 0.05))
        hmx = _swv(np.pad(hh, k, mode="edge"), 2 * k + 1).max(1)
        k2 = max(1, k // 3)
        tmin = _swv(np.pad(top, k2, mode="edge"), 2 * k2 + 1).min(1)
        m = max(2, int(W * 0.02))
        ker = np.ones(m) / m
        self.top = np.convolve(np.pad(tmin, m, mode="edge"), ker, "same")[m:-m]
        self.bot = self.top + np.convolve(np.pad(hmx, m, mode="edge"), ker, "same")[m:-m]
        self.h = self.bot - self.top
        self.mid = (self.top + self.bot) / 2
        self.x0, self.x1 = lay.x0, lay.x1
        self.span = lay.x1 - lay.x0
        i0, i1 = int(lay.x0), int(lay.x1)
        hmax = self.h[i0:i1 + 1].max()
        big = np.nonzero(self.h > 0.6 * hmax)[0]
        big = big[(big >= i0) & (big <= i1)]
        self.rx0, self.rx1 = float(big.min()), float(big.max())
        self.RH = float(np.median(self.h[int(self.rx0):int(self.rx1) + 1]))
        self.cx = (self.rx0 + self.rx1) / 2
        self.W, self.H = W, H
        self.lay = lay

    def T(self, x):
        return np.interp(x, np.arange(self.W), self.top)

    def B(self, x):
        return np.interp(x, np.arange(self.W), self.bot)

    def M(self, x):
        return np.interp(x, np.arange(self.W), self.mid)

    def Hh(self, x):
        return np.interp(x, np.arange(self.W), self.h)

    def maps(self, x):
        xi = np.clip(x.astype(int), 0, self.W - 1)
        return self.top[xi], self.bot[xi]


class Tube:
    pass


def tube(W, H, ctrl, wfun, n=24, step=1.5):
    """A round body along a Catmull-Rom spline through ctrl, width wfun(t) (t 0..1 from the first point).
    Later parts of the path lie over earlier ones (coils and knots cross correctly). Returns a Tube with
    mask, S (arc length), D (-1..1 across, + on the right of travel), WD (width), and the path."""
    P = np.array(bezier(ctrl, n), np.float64)
    seg = np.hypot(*np.diff(P, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    m = max(2, int(s[-1] / step))
    si = np.linspace(0, s[-1], m)
    P = np.stack([np.interp(si, s, P[:, 0]), np.interp(si, s, P[:, 1])], 1)
    t = si / max(si[-1], 1e-6)
    w = np.broadcast_to(np.asarray(wfun(t), np.float64), t.shape).copy()
    tan = np.gradient(P, axis=0)
    tan /= np.maximum(np.hypot(tan[:, 0], tan[:, 1]), 1e-9)[:, None]
    S = np.full((H, W), -1.0, np.float32)
    D = np.zeros((H, W), np.float32)
    WD = np.zeros((H, W), np.float32)
    last = -1e9
    for i in range(m):
        if not (si[i] - last >= max(1.0, w[i] / 10) or i == m - 1):
            continue
        last = si[i]
        cx, cy = P[i]
        r = w[i] / 2
        if r < 0.5:
            continue
        xa, xb = max(0, int(cx - r)), min(W, int(cx + r) + 2)
        ya, yb = max(0, int(cy - r)), min(H, int(cy + r) + 2)
        if xa >= xb or ya >= yb:
            continue
        dx = np.arange(xa, xb, dtype=np.float32)[None, :] - cx
        dy = np.arange(ya, yb, dtype=np.float32)[:, None] - cy
        ins = dx * dx + dy * dy <= r * r
        dn = np.broadcast_to((dx * -tan[i, 1] + dy * tan[i, 0]) / r, ins.shape)
        S[ya:yb, xa:xb][ins] = si[i]
        D[ya:yb, xa:xb][ins] = dn[ins]
        WD[ya:yb, xa:xb][ins] = w[i]
    tb = Tube()
    tb.mask = S >= 0
    tb.S, tb.D, tb.WD, tb.P, tb.s, tb.w, tb.tan, tb.t = S, np.clip(D, -1, 1), WD, P, si, w, tan, t
    return tb


def tube_ink(tb, px):
    """Outline of a tube and the seams where one part crosses over another."""
    m = tb.mask
    S, WD = tb.S, np.maximum(tb.WD, 1)
    e = np.zeros(m.shape, bool)
    for ax in (0, 1):
        for sh_ in (1, -1):
            mr = np.roll(m, sh_, ax)
            Sr = np.roll(S, sh_, ax)
            e |= m & (~mr)
            e |= m & mr & (np.abs(S - Sr) > WD * 0.9)
    return np.clip(fblur(e.astype(np.float32), max(1, px * 0.5)) * 2.2, 0, 1)


def tube_light(tb):
    d = tb.D
    return np.sqrt(np.clip(1 - d * d, 0, 1))


def spiral(cx, cy, r0, a0, turns, sgn=1, n=60, shrink=0.85):
    """Points of a spiral from angle a0 (radians, y down) turning sgn-wise, its radius shrinking toward the end."""
    t = np.linspace(0, 1, n)
    a = a0 + sgn * t * turns * 2 * np.pi
    r = r0 * (1 - shrink * t)
    return list(zip(cx + np.cos(a) * r, cy + np.sin(a) * r))


def closed_spline(pts, n=10):
    """A smooth closed outline (Catmull-Rom) through pts."""
    P = np.asarray(pts, np.float64)
    ext = np.vstack([P[-1], P, P[0], P[1]])
    out = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)))
    return out


def frame_pts(P, pts):
    return [P(px, py) for px, py in pts]


def splat(L, cx, cy, r, col, rng, drops=9):
    """An ink splatter: a ragged blob, droplets and a couple of streaks."""
    k = 26
    ang = np.linspace(0, 2 * np.pi, k, endpoint=False)
    rad = r * (0.7 + 0.5 * rng.random(k))
    rad[rng.random(k) < 0.25] *= 1.45
    L.poly([(cx + math.cos(a) * q, cy + math.sin(a) * q) for a, q in zip(ang, rad)], col)
    for _ in range(drops):
        a = rng.random() * 2 * np.pi
        d = r * (1.3 + 1.6 * rng.random())
        L.circle(cx + math.cos(a) * d, cy + math.sin(a) * d, r * (0.06 + 0.14 * rng.random()), col)
    for _ in range(3):
        a = rng.random() * 2 * np.pi
        L.line([(cx + math.cos(a) * r * 0.8, cy + math.sin(a) * r * 0.8), (cx + math.cos(a) * r * 2.2, cy + math.sin(a) * r * 2.2)],
               col, r * 0.12)


def d_rabid_beast(W, H, lay):
    """a manic neon comic beast: jaws open toward the muzzle, drool, a wild eye, ink splatter"""
    x, y = grid(W, H)
    E = Env(lay, W, H)
    RH, span = E.RH, E.span
    T, B = E.maps(x)
    rng = np.random.default_rng(7001)
    BLACK = (8, 6, 12, 255)
    lw = RH * 0.022
    # background: teal with magenta halftone and splatter
    c = ramp(y / H + 0.25 * noise(W, H, 7002, 2.0), [(0, (0.0, 0.75, 0.75)), (0.6, (0.0, 0.45, 0.6)), (1.1, (0.05, 0.12, 0.35))])
    cell = RH * 0.07
    gx, gy = (x / cell) % 1.0 - 0.5, (y / cell) % 1.0 - 0.5
    dens = smooth(0.45, 0.8, noise(W, H, 7003, 2.5))
    dots = np.hypot(gx, gy) < 0.45 * np.sqrt(dens)
    c = np.where(dots[..., None], solid(W, H, (1.0, 0.15, 0.6)), c)
    S = Layer(W, H)
    for _ in range(int(span / RH * 1.6)):
        sx, sy = lay.x0 + rng.random() * span, rng.random() * H
        col = [(255, 230, 30, 255), BLACK, (255, 40, 160, 255)][int(rng.random() * 3)]
        splat(S, sx, sy, RH * (0.08 + 0.12 * rng.random()), col, rng)
    c = over(c, S.rgba())
    # the head geometry
    jx0 = E.rx0 + RH * 0.12
    xh = jx0 + (E.rx1 - jx0) * 0.6
    xs = np.arange(jx0, xh + 1, 2.0)
    t = np.clip((xs - jx0) / (xh - jx0), 0, 1)
    yc = E.T(xs) + E.Hh(xs) * 0.55
    op = RH * 0.52 * (1 - t) ** 0.75
    yu, yl = yc - op / 2, yc + op / 2
    xr = E.rx1 + RH * 0.3
    L = Layer(W, H)
    # mouth interior and the tongue lolling out along the barrel
    L.poly([(jx0, yu[0])] + list(zip(xs, yu)) + list(zip(xs[::-1], yl[::-1])), (60, 0, 50, 255))
    tx = np.arange(lay.x0 + span * 0.01, xh - RH * 0.3, 3.0)
    ty = np.where(tx > jx0, np.interp(tx, xs, yc) + RH * 0.06, E.M(tx) + 0.15 * E.Hh(tx) * np.sin(tx / RH * 2.5))
    ty = np.convolve(np.pad(ty, 12, mode="edge"), np.ones(25) / 25, "same")[12:-12]
    tw = np.where(tx > jx0, RH * 0.2, np.minimum(RH * 0.2, E.Hh(tx) * 0.55))
    tw = np.convolve(np.pad(tw, 12, mode="edge"), np.ones(25) / 25, "same")[12:-12]
    poly, nrm = outline_of(list(zip(tx, ty)), tw)
    L.poly(poly, (255, 90, 150, 255), BLACK, lw)
    L.line(list(zip(tx[5:-int(RH * 0.1)], ty[5:-int(RH * 0.1)] - tw[5:-int(RH * 0.1)] * 0.05)), (170, 20, 80, 255), lw * 0.7)
    L.circle(tx[0], ty[0], tw[0] * 0.5, (255, 90, 150, 255), BLACK, lw)
    L.line(list(zip(tx[::6], ty[::6] - tw[::6] * 0.28)), (255, 200, 220, 200), lw * 0.6)
    # teeth
    def tooth(bx, by, ln, wd, down, col=(255, 248, 215, 255)):
        s = 1 if down else -1
        L.poly([(bx - wd / 2, by - s * lw), (bx + wd / 2, by - s * lw), (bx + wd * 0.18, by + s * ln * 0.7), (bx - wd * 0.05, by + s * ln)], col, BLACK, lw * 0.7)
    xx = jx0 + RH * 0.06
    while xx < xh - RH * 0.12:
        tt = (xx - jx0) / (xh - jx0)
        ln = RH * (0.26 - 0.17 * tt) * (0.75 + 0.5 * rng.random())
        wd = RH * (0.1 + 0.05 * rng.random())
        tooth(xx, float(np.interp(xx, xs, yu)), ln, wd, True)
        tooth(xx + wd * 0.5, float(np.interp(xx + wd * 0.5, xs, yl)), ln * 0.85, wd * 0.95, False)
        xx += wd * 1.05
    # drool strings
    for k in range(4):
        dx_ = jx0 + (xh - jx0) * (0.15 + 0.2 * k)
        y0, y1 = float(np.interp(dx_, xs, yu)), float(np.interp(dx_ + RH * 0.1, xs, yl))
        L.line(bezier([(dx_, y0), (dx_ + RH * 0.04, (y0 + y1) / 2 + RH * 0.05), (dx_ + RH * 0.1, y1)], 12), (190, 255, 120, 230), lw * 0.6)
    c = over(c, L.rgba())
    # jaws and head
    J = Layer(W, H)
    magenta, purple = (230, 30, 140, 255), (120, 20, 150, 255)
    tn = float(E.T(np.array([jx0]))[0])
    upper = [(jx0 - RH * 0.14, yu[0] - RH * 0.04), (jx0 - RH * 0.1, tn + RH * 0.12), (jx0 + RH * 0.05, tn + RH * 0.02)]
    xt = np.arange(jx0 + RH * 0.1, xr, 4.0)
    upper += list(zip(xt, E.T(xt) - RH * 0.02)) + [(xr, at(E.B, E.rx1) + RH * 0.05), (xh + RH * 0.25, at(E.B, xh) + RH * 0.05)]
    upper += [(xh + RH * 0.05, float(yc[-1]) + RH * 0.05)] + list(zip(xs[::-1], yu[::-1]))
    lower = [(jx0 - RH * 0.02, yl[0] + RH * 0.02)] + list(zip(xs, yl)) + [(xh + RH * 0.2, at(E.B, xh) + RH * 0.06), (jx0 + RH * 0.2, at(E.B, jx0) + RH * 0.06),
                                                                       (jx0, yl[0] + RH * 0.12)]
    J.poly(lower, purple, BLACK, lw)
    J.poly(upper, magenta, BLACK, lw)
    jr = J.rgba()
    ja = jr[..., 3]
    shade = ramp((y - T) / np.maximum(B - T, 1), [(0, (1.15, 1.1, 1.1)), (0.5, (1.0, 1.0, 1.0)), (1, (0.6, 0.6, 0.75))])
    hatch = (np.sin((x - y) / (RH * 0.03) * np.pi) > 0.55) & ((y - T) / np.maximum(B - T, 1) > 0.62)
    fur = jr[..., :3] * shade
    fur = np.where(hatch[..., None], fur * 0.55, fur)
    c = mix(c, fur, ja)
    # stripes, highlights, nose, wrinkles, brow, eye, ear, mane
    D = Layer(W, H)
    teal, yellow = (20, 235, 220, 255), (255, 230, 40, 255)
    for k in range(6):
        sx_ = xh - RH * 0.1 + k * RH * 0.26
        if sx_ > E.rx1 - RH * 0.05:
            break
        ty_ = at(E.T, sx_)
        D.poly([(sx_, ty_ - RH * 0.02), (sx_ + RH * 0.13, ty_ - RH * 0.02), (sx_ + RH * 0.02, ty_ + RH * 0.42), (sx_ - RH * 0.04, ty_ + RH * 0.2)], teal, BLACK, lw * 0.7)
    for k in range(3):
        sx_ = jx0 + (xh - jx0) * (0.3 + 0.22 * k)
        ty_ = at(E.T, sx_)
        D.poly([(sx_, ty_ - RH * 0.02), (sx_ + RH * 0.1, ty_ - RH * 0.02), (sx_ + RH * 0.05, ty_ + RH * 0.16)], teal, BLACK, lw * 0.6)
    nx_, ny_ = jx0 - RH * 0.04, tn + RH * 0.13
    D.ellipse((nx_ - RH * 0.1, ny_ - RH * 0.07, nx_ + RH * 0.07, ny_ + RH * 0.08), BLACK)
    D.ellipse((nx_ - RH * 0.06, ny_ - RH * 0.045, nx_ - RH * 0.0, ny_ - RH * 0.01), (255, 255, 255, 230))
    for k in range(3):
        wx_ = jx0 + RH * (0.12 + 0.09 * k)
        D.line(bezier([(wx_, tn + RH * 0.06), (wx_ + RH * 0.05, tn + RH * 0.13), (wx_ + RH * 0.02, tn + RH * 0.2)], 10), BLACK, lw * 0.8)
    ex, ey = xh + RH * 0.12, at(E.T, xh) + at(E.Hh, xh) * 0.3
    er_ = RH * 0.17
    D.ellipse((ex - er_ * 1.2, ey - er_, ex + er_ * 1.2, ey + er_), (255, 250, 200, 255), BLACK, lw * 1.2)
    for k in range(5):
        a = k * 1.25 + 0.3
        D.line([(ex + math.cos(a) * er_ * 1.1, ey + math.sin(a) * er_ * 0.9), (ex + math.cos(a + 0.2) * er_ * 0.55, ey + math.sin(a + 0.2) * er_ * 0.5)],
               (230, 30, 40, 255), lw * 0.45)
    D.circle(ex - er_ * 0.25, ey + er_ * 0.05, er_ * 0.48, yellow, BLACK, lw * 0.7)
    D.circle(ex - er_ * 0.25, ey + er_ * 0.05, er_ * 0.13, BLACK)
    D.circle(ex - er_ * 0.4, ey - er_ * 0.15, er_ * 0.12, (255, 255, 255, 255))
    D.poly([(ex - er_ * 1.6, ey - er_ * 0.55), (ex + er_ * 1.3, ey - er_ * 1.35), (ex + er_ * 1.4, ey - er_ * 0.95), (ex - er_ * 1.2, ey - er_ * 0.3)], BLACK)
    ax = min(E.rx1 - RH * 0.4, ex + RH * 0.55)
    at_ = at(E.T, ax)
    D.poly([(ax - RH * 0.15, at_ + RH * 0.15), (ax + RH * 0.45, at_ - RH * 0.12), (ax + RH * 0.2, at_ + RH * 0.3)], magenta, BLACK, lw)
    D.poly([(ax - RH * 0.05, at_ + RH * 0.15), (ax + RH * 0.32, at_ - RH * 0.04), (ax + RH * 0.17, at_ + RH * 0.22)], (255, 150, 200, 255))
    xm = xh + RH * 0.15
    while xm < E.rx1 + RH * 0.3:
        by_ = at(E.B, xm)
        for k, col in enumerate((yellow, teal)):
            ln = RH * (0.55 + 0.35 * rng.random()) * (1 - 0.35 * k)
            D.poly([(xm - RH * 0.08, by_ - RH * 0.08), (xm + RH * 0.12, by_ - RH * 0.04), (xm + RH * 0.3 + ln * 0.3, by_ + ln)], col, BLACK, lw * 0.8)
        xm += RH * 0.24
    dr = D.rgba()
    c = over(c, dr)
    # slime drips under the jaw and the tongue
    Dr = Layer(W, H)
    for k in range(7):
        px = jx0 + (xh - jx0) * rng.random() * 0.8
        py = at(E.B, px) + RH * 0.04
        ln = RH * (0.25 + 0.6 * rng.random())
        Dr.line([(px, py), (px, py + ln)], (150, 255, 90, 255), lw * 0.9)
        Dr.circle(px, py + ln, lw * 1.4, (150, 255, 90, 255))
    for k in range(5):
        px = tx[0] + (jx0 - tx[0]) * rng.random()
        if px >= jx0:
            continue
        py = float(np.interp(px, tx, ty + tw * 0.45))
        ln = RH * (0.12 + 0.3 * rng.random())
        Dr.line([(px, py), (px, py + ln)], (150, 255, 90, 255), lw * 0.8)
        Dr.circle(px, py + ln, lw * 1.2, (150, 255, 90, 255))
    drr = Dr.rgba()
    c = over(c, drr) + glow_of(drr, RH * 0.02, 0.5)
    c = c + glow_of(dr, RH * 0.04, 0.15)
    return np.clip(c, 0, 1), 0.25, 0.08


def d_golden_coil(W, H, lay):
    """a gold king cobra wrapped around black lacquer, hood flared at the muzzle, ruby eyes"""
    x, y = grid(W, H)
    E = Env(lay, W, H)
    RH, span = E.RH, E.span
    T, B = E.maps(x)
    hh = np.maximum(B - T, 1)
    yn = (y - T) / hh
    # glossy black lacquer: deep black with soft long reflections
    c = ramp(noise(W, H, 8001, 1.5), [(0, (0.006, 0.005, 0.006)), (1, (0.03, 0.022, 0.02))])
    refl = np.exp(-((yn - 0.16) / 0.07) ** 2) * (0.55 + 0.45 * noise(W, H, 8002, 2.0, 3, sx=0.2, sy=1.0))
    c = c + (refl * 0.22)[..., None] * np.array([0.9, 0.9, 1.0])
    diag = np.exp(-(((x + y * 1.6) % (H * 2.4) - H * 1.2) / (H * 0.25)) ** 2) * (y > B)
    c = c + (diag * 0.07)[..., None]
    gold = goldf(W, H, 8003, 5.0)
    # gold pinstripes: double lines along the band, long coachlines down the lower parts
    G = Layer(W, H)
    wht = (255, 255, 255, 255)
    xs = np.arange(lay.x0, lay.x1 + 1, 3.0)
    for off, wd in ((0.05, 0.012), (0.085, 0.006)):
        G.line(list(zip(xs, E.T(xs) + E.Hh(xs) * off)), wht, RH * wd)
        G.line(list(zip(xs, E.B(xs) - E.Hh(xs) * off)), wht, RH * wd)
    G.line(list(zip(xs, E.B(xs) + RH * 0.14)), wht, RH * 0.01)
    G.line(list(zip(xs, E.B(xs) + RH * 0.18)), wht, RH * 0.005)
    c = gild(c, alpha(G), gold, RH * 0.006, 1.0, 0.0)
    # the cobra wrapped around the gun: diagonal coils from the tail at the rear, the neck rising with the hood at the front
    hx = max(E.rx0 + (E.rx1 - E.rx0) * 0.12, lay.x0 + RH * 0.75)
    hy = at(E.T, hx) + at(E.Hh, hx) * 0.5
    xs_, xe_ = hx + RH * 0.55, E.rx1 - RH * 0.04
    pitch, slant = RH * 0.62, RH * 0.38
    tt_ = np.clip((y - T) / hh, 0, 1)
    q = (x - xs_ - (1 - tt_) * slant) / pitch
    wi = np.floor(q)
    nwr = max(1.0, (xe_ - xs_) / pitch)
    wfrac = np.clip(wi / nwr, 0, 1)
    wd_ = RH * (0.27 - 0.13 * wfrac ** 1.5)
    d = ((q - wi) - 0.5) * pitch / (wd_ / 2)
    inside = (y >= T) & (y <= B) & (q >= 0) & (x <= xe_ + slant * (1 - tt_))
    coil = inside & (np.abs(d) < 1)
    occl = inside & (np.abs(d) < 1.7) & ~coil
    c = c * (1 - 0.65 * occl * smooth(1.7, 1.0, np.abs(d)))[..., None]
    lit = np.sqrt(np.clip(1 - d * d, 0, 1)) * np.sin(np.pi * np.clip(tt_ * 0.9 + 0.05, 0, 1)) ** 0.6
    along = (y - T) * 1.15
    rim, inner = scales(along, d, wd_ * 1.1, 5)
    gl = ramp(lit * (0.8 + 0.2 * inner) - 0.15 * d, [(0, (0.22, 0.12, 0.02)), (0.45, (0.65, 0.42, 0.1)), (0.75, (0.95, 0.75, 0.32)),
                                                      (0.95, (1.0, 0.93, 0.65)), (1.1, (1.0, 1.0, 0.9))])
    body = mix(gl, gl * 0.45, rim * 0.85)
    belly = smooth(0.5, 0.62, d)
    plates = 0.75 + 0.25 * (np.sin(along / (wd_ * 0.3) * np.pi) > -0.5)
    body = mix(body, solid(W, H, (0.98, 0.86, 0.5)) * (plates * (0.45 + 0.55 * lit))[..., None], belly)
    body = body + (smooth(0.2, 0.0, np.abs(d + 0.4)) * 0.3 * lit)[..., None]
    c = np.where(coil[..., None], body, c)
    edge = coil & (np.abs(d) > 0.9)
    c = np.where(edge[..., None], c * 0.35, c)
    # the neck from the first coil up to the hood
    ctrl = [(xs_ + RH * 0.05, at(E.B, xs_) - RH * 0.08), (xs_ - RH * 0.2, at(E.B, xs_) - RH * 0.2), (hx + RH * 0.2, hy + RH * 0.2), (hx, hy)]
    tb = tube(W, H, ctrl, lambda t: RH * np.interp(t, [0, 1.0], [0.24, 0.17]))
    lit = tube_light(tb)
    wd = np.maximum(tb.WD, 1)
    rim, inner = scales(tb.S, tb.D, wd, 5)
    gl = ramp(lit * (0.8 + 0.2 * inner) - 0.2 * tb.D, [(0, (0.25, 0.13, 0.02)), (0.45, (0.65, 0.42, 0.1)), (0.75, (0.95, 0.75, 0.32)),
                                                         (0.95, (1.0, 0.93, 0.65)), (1.1, (1.0, 1.0, 0.9))])
    body = mix(gl, gl * 0.45, rim * 0.85)
    body = mix(body, solid(W, H, (0.98, 0.86, 0.5)) * (0.5 + 0.5 * lit)[..., None], smooth(0.45, 0.6, tb.D))
    sh = np.clip(fblur(shift(tb.mask.astype(np.float32), RH * 0.02, RH * 0.04), RH * 0.035), 0, 1)
    c = c * (1 - 0.7 * sh)[..., None]
    c = np.where(tb.mask[..., None], body, c)
    c = mix(c, solid(W, H, (0.12, 0.06, 0.0)), tube_ink(tb, RH * 0.01))
    # the hood (front view, flared) and the head on top of it, facing the muzzle
    dk = (60, 30, 0, 255)
    hw_, hh_ = RH * 0.4, min(RH * 0.45, at(E.Hh, hx) * 0.44)
    hcy = hy + RH * 0.1
    hood = closed_spline([(hx + px * hw_, hcy + py * hh_) for px, py in
                          [(0, -1.0), (0.72, -0.78), (1.0, -0.25), (0.75, 0.42), (0.32, 1.0), (-0.32, 1.0), (-0.75, 0.42), (-1.0, -0.25),
                           (-0.72, -0.78)]], 12)
    Hd = Layer(W, H)
    Hd.poly(hood, (255, 255, 255, 255))
    ha = alpha(Hd)
    hu, hv = (x - hx) / hw_, (y - hcy) / hh_
    rdist = np.hypot(hu, hv * 0.9)
    hood_c = ramp(1 - rdist, [(0, (0.4, 0.24, 0.04)), (0.25, (0.78, 0.55, 0.16)), (0.7, (1.0, 0.85, 0.45)), (1, (1.0, 0.95, 0.7))])
    hs_rim, hs_in = scales(x - hx, np.clip(hv, -1, 1), np.full_like(hv, hw_ * 0.5), 7)
    hood_c = mix(hood_c * (0.75 + 0.3 * hs_in)[..., None], hood_c * 0.45, hs_rim * 0.7)
    throat = (np.abs(hu) < 0.3 * (1 - 0.3 * np.clip(hv, 0, 1))) & (hv > -0.55)
    plates = 0.8 + 0.2 * (np.sin(hv * 14) > -0.6)
    hood_c = np.where(throat[..., None], solid(W, H, (1.0, 0.9, 0.58)) * plates[..., None], hood_c)
    edge = smooth(0.78, 0.92, rdist) * (1 - smooth(0.95, 1.0, rdist))
    hood_c = mix(hood_c, solid(W, H, (0.35, 0.18, 0.02)), edge * 0.8)
    hood_c = hood_c * np.clip(emboss(ha, RH * 0.025, 1.0), 0.4, 1.6)[..., None]
    sh = np.clip(fblur(shift(ha, RH * 0.025, RH * 0.04), RH * 0.04), 0, 1)
    c = c * (1 - 0.75 * sh)[..., None]
    c = mix(c, hood_c, ha)
    Rb = Layer(W, H)
    for a in np.linspace(-0.9, 0.9, 9):
        q = hood[int((a + 1.0) / 2.0 * (len(hood) - 1)) % len(hood)]
        Rb.circle(hx + (q[0] - hx) * 0.88, hcy + (q[1] - hcy) * 0.88, RH * 0.024, (200, 10, 35, 255), (255, 210, 120, 255), RH * 0.006)
    s = RH * 0.52
    P = lambda px, py: (hx - px * s, hcy - hh_ * 0.62 + py * s)  # noqa: E731
    Hh_ = Layer(W, H)
    Hh_.poly(frame_pts(P, [(0.25, 0.02), (0.92, -0.0), (0.88, 0.2), (0.3, 0.16)]), (70, 5, 15, 255))
    Hh_.poly(closed_spline(frame_pts(P, [(-0.25, -0.08), (0.05, -0.22), (0.45, -0.24), (0.78, -0.14), (0.98, -0.04), (0.95, 0.03), (0.5, 0.04),
                                         (0.1, 0.1), (-0.22, 0.12)]), 8), (245, 195, 85, 255), dk, RH * 0.012)
    Hh_.poly(closed_spline(frame_pts(P, [(0.2, 0.12), (0.55, 0.14), (0.9, 0.22), (0.86, 0.28), (0.45, 0.26), (0.15, 0.22)]), 6),
             (230, 175, 70, 255), dk, RH * 0.01)
    Hh_.poly(frame_pts(P, [(0.86, 0.02), (0.83, 0.17), (0.8, 0.03)]), (255, 250, 235, 255), dk, RH * 0.004)
    Hh_.poly(frame_pts(P, [(0.7, 0.02), (0.68, 0.12), (0.65, 0.03)]), (255, 250, 235, 255), dk, RH * 0.004)
    Hh_.line([P(0.9, 0.12), P(1.18, 0.14), P(1.32, 0.06)], (210, 20, 35, 255), RH * 0.012)
    Hh_.line([P(1.18, 0.14), P(1.32, 0.22)], (210, 20, 35, 255), RH * 0.012)
    for k in range(4):
        Hh_.line([P(0.08 + k * 0.17, -0.2 + k * 0.01), P(0.14 + k * 0.17, 0.06)], (165, 115, 30, 255), RH * 0.006)
    hr = Hh_.rgba()
    hsh = np.clip(emboss(hr[..., 3], RH * 0.015, 1.0), 0.5, 1.5)
    sh = np.clip(fblur(shift(hr[..., 3], RH * 0.02, RH * 0.03), RH * 0.03), 0, 1)
    c = c * (1 - 0.5 * sh)[..., None]
    c = mix(c, hr[..., :3] * hsh[..., None], hr[..., 3])
    eye = Layer(W, H)
    ex_, ey_ = P(0.55, -0.1)
    eye.ellipse((ex_ - s * 0.075, ey_ - s * 0.055, ex_ + s * 0.075, ey_ + s * 0.055), (230, 10, 40, 255), (40, 0, 0, 255), RH * 0.006)
    eye.circle(ex_ - s * 0.025, ey_ - s * 0.018, s * 0.02, (255, 210, 220, 255))
    eye.line([P(0.4, -0.2), P(0.68, -0.17)], dk, RH * 0.012)
    er = eye.rgba()
    rbr = Rb.rgba()
    c = over(c, rbr) + glow_of(rbr, RH * 0.02, 0.4)
    c = over(c, er) + glow_of(er, RH * 0.05, 1.2)
    # maki-e gold dust thickening toward the bottom of the magazine and the grip
    t_ = np.clip((y - B) / (RH * 2.2), 0, 1) * (y > B + RH * 0.15)
    flake = noise(W, H, 8006, 220.0, 1)
    dust = (flake > 0.87 - 0.24 * t_ ** 1.3) & (t_ > 0)
    c = np.where(dust[..., None], gold * (0.75 + 0.5 * noise(W, H, 8007, 120.0, 1))[..., None], c)
    c = c + (smooth(0.3, 1.0, t_) * 0.12)[..., None] * np.array([1.0, 0.75, 0.3])
    c = add(c, sparkle(W, H, int(W / 30), 8004, RH * 0.006, (1.0, 0.9, 0.6)), 0.6)
    return np.clip(c, 0, 1), 0.3, 0.1


def lower_spots(E, lay, x, y):
    """Centres (and a usable radius) of the gun's lower parts (magazine, grip) in the front and the rear half."""
    out = []
    B = np.interp(x, np.arange(E.W), E.bot)
    below = lay.mask & (y > B + E.RH * 0.15)
    for sel in (x < E.cx, x >= E.cx):
        m = below & sel
        if m.sum() < 50:
            continue
        cx_, cy_ = float(x[m].mean()), float(y[m].mean())
        cols = np.nonzero(m.any(0))[0]
        wdt = (cols.max() - cols.min()) if len(cols) else E.RH
        cy_ = min(cy_, float(np.interp(cx_, np.arange(E.W), E.bot)) + E.RH * 0.9)
        out.append((cx_, cy_, wdt))
    return out


def flower(L, cx, cy, r, rot, cols, ink, lw, n_out=7, n_mid=6, wavy=0.12, rng=None):
    """A layered flower (peony or rose): rings of rounded petals, outer first; cols = (outer, mid, inner, centre)."""
    def petal(ang, dist, ln, wd, col):
        pts = []
        for t in np.linspace(-1, 1, 21):
            a = ang + t * wd
            rr = dist + ln * max(0.0, 1 - t ** 4) ** 0.5 * (1 + wavy * math.sin(t * 7 + ang * 3))
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        pts.append((cx + math.cos(ang + wd * 0.5) * dist * 0.3, cy + math.sin(ang + wd * 0.5) * dist * 0.3))
        pts.append((cx + math.cos(ang - wd * 0.5) * dist * 0.3, cy + math.sin(ang - wd * 0.5) * dist * 0.3))
        L.poly(pts, col, ink, lw)
    for k in range(n_out):
        petal(rot + k * 2 * math.pi / n_out, r * 0.25, r * 0.75, math.pi / n_out * 1.25, cols[0])
    for k in range(n_mid):
        petal(rot + 0.5 + k * 2 * math.pi / n_mid, r * 0.15, r * 0.5, math.pi / n_mid * 1.2, cols[1])
    for k in range(4):
        petal(rot + 1.1 + k * math.pi / 2, r * 0.05, r * 0.3, math.pi / 4 * 1.1, cols[2])
    L.circle(cx, cy, r * 0.13, cols[3], ink, lw * 0.8)
    L.line(spiral(cx, cy, r * 0.22, rot, 1.2, 1, 30, 0.8), ink, lw * 0.8)


def leaf(L, base, ang, ln, wd, col, ink, lw):
    n = 16
    t = np.linspace(0, 1, n)
    sx, sy = base[0] + np.cos(ang) * ln * t, base[1] + np.sin(ang) * ln * t
    nx, ny = -math.sin(ang), math.cos(ang)
    hw = wd / 2 * np.sin(np.pi * t) ** 0.8
    pts = list(zip(sx + nx * hw, sy + ny * hw)) + list(zip(sx - nx * hw, sy - ny * hw))[::-1]
    L.poly(pts, col, ink, lw)
    L.line([(sx[1], sy[1]), (sx[-3], sy[-3])], ink, lw * 0.7)


def d_empress(W, H, lay):
    """purple velvet, a jewelled crown in a gold rococo frame, roses and pearl strings"""
    x, y = grid(W, H)
    E = Env(lay, W, H)
    RH, span = E.RH, E.span
    T, B = E.maps(x)
    hh = np.maximum(B - T, 1)
    yn = (y - T) / hh
    rng = np.random.default_rng(12001)
    # velvet with soft folds
    fold = 0.5 + 0.5 * np.sin(x / RH * 1.3 + y / RH * 0.4 + 2.5 * noise(W, H, 12002, 1.0, 3))
    pile = noise(W, H, 12003, 70.0, 2)
    c = ramp(fold * 0.8 + 0.2 * noise(W, H, 12004, 3.0, 3), [(0, (0.08, 0.0, 0.13)), (0.45, (0.24, 0.03, 0.36)), (0.85, (0.42, 0.1, 0.58)),
                                                               (1, (0.6, 0.3, 0.75))])
    c = c * (0.9 + 0.18 * pile)[..., None]
    gold = goldf(W, H, 12005, 5.0)
    wht = (255, 255, 255, 255)
    # gold moulding along the band with C-scroll curls
    G = Layer(W, H)
    xs = np.arange(lay.x0, lay.x1 + 1, 3.0)
    G.line(list(zip(xs, E.T(xs) + RH * 0.025)), wht, RH * 0.03)
    yb_ = E.B(xs) - RH * 0.06
    G.line(list(zip(xs, yb_)), wht, RH * 0.035)
    G.line(list(zip(xs, yb_ + RH * 0.045)), wht, RH * 0.012)
    k = 0
    xx = lay.x0 + RH * 0.4
    while xx < lay.x1 - RH * 0.3:
        by = at(E.B, xx) - RH * 0.06
        sg = 1 if k % 2 else -1
        G.line(spiral(xx, by - RH * 0.1, RH * 0.1, math.pi / 2, 0.9, sg, 30, 0.75), wht, RH * 0.022)
        G.line(bezier([(xx - RH * 0.3, by), (xx - RH * 0.12, by - RH * 0.02), (xx, by - RH * 0.0)], 10), wht, RH * 0.018)
        xx += RH * 0.75
        k += 1
    c = gild(c, alpha(G), gold, RH * 0.01, 1.2, 0.5)
    # the cartouche and the crown
    fx = E.rx0 + (E.rx1 - E.rx0) * 0.55
    fy = at(E.M, fx)
    rx_, ry_ = RH * 0.62, min(RH * 0.44, at(E.Hh, fx) * 0.46)
    th = np.linspace(0, 2 * np.pi, 160)
    rr = 1 + 0.1 * np.cos(4 * th) + 0.05 * np.sin(6 * th)
    cart = list(zip(fx + np.cos(th) * rx_ * rr, fy + np.sin(th) * ry_ * rr))
    Cf = Layer(W, H)
    Cf.poly(cart, wht)
    cfa = alpha(Cf)
    inside = ramp(np.hypot((x - fx) / rx_, (y - fy) / ry_), [(0, (0.4, 0.1, 0.55)), (1, (0.12, 0.0, 0.2))])
    q = ((x - fx) + (y - fy)) / (RH * 0.12)
    q2 = ((x - fx) - (y - fy)) / (RH * 0.12)
    tuft = (np.abs(q - np.round(q)) < 0.06) | (np.abs(q2 - np.round(q2)) < 0.06)
    inside = np.where(tuft[..., None], inside * 0.6, inside)
    c = mix(c, inside, cfa)
    G2 = Layer(W, H)
    G2.line(cart + [cart[0]], wht, RH * 0.04)
    for a in (math.radians(35), math.radians(145), math.radians(215), math.radians(325)):
        px, py = fx + math.cos(a) * rx_ * 1.02, fy + math.sin(a) * ry_ * 1.02
        G2.line(spiral(px + math.cos(a) * RH * 0.08, py + math.sin(a) * RH * 0.06, RH * 0.11, a + math.pi, 1.0, 1 if a < math.pi else -1, 30, 0.8),
                wht, RH * 0.028)
    for sgn in (-1, 1):
        px = fx + sgn * rx_ * 1.02
        ln_ = RH * 1.0
        pts = bezier([(px, fy + RH * 0.05), (px + sgn * ln_ * 0.3, fy - RH * 0.2), (px + sgn * ln_ * 0.65, fy + RH * 0.12),
                      (px + sgn * ln_ * 0.95, fy - RH * 0.05)], 16)
        G2.line(pts, wht, RH * 0.035)
        ex, ey = pts[-1]
        G2.line(spiral(ex, ey + RH * 0.09, RH * 0.1, -math.pi / 2, 0.85, -sgn, 30, 0.75), wht, RH * 0.03)
        G2.line(spiral(px + sgn * RH * 0.08, fy + RH * 0.15, RH * 0.08, -math.pi / 2, 0.8, sgn, 24, 0.7), wht, RH * 0.024)
        for j in (4, 9, 14, 20, 26, 32):
            qx, qy = pts[j]
            up = -1 if j % 2 else 1
            leaf(G2, (qx, qy), -math.pi / 2 * up + sgn * 0.6 * up - (0 if sgn > 0 else math.pi) * 0, RH * 0.2, RH * 0.08, wht, wht, 1)
    c = gild(c, alpha(G2), gold, RH * 0.012, 1.3, 0.55)
    # crown
    Cr = Layer(W, H)
    cw, chh = RH * 0.36, RH * 0.6
    cb = fy + chh * 0.42
    ink = (70, 40, 5, 255)
    pts = [(fx - cw, cb - chh * 0.18)]
    for k3 in range(5):
        px = fx - cw + k3 * cw / 2
        tip = chh * (0.75 if k3 == 2 else (0.6 if k3 % 2 == 0 else 0.5))
        pts.append((px, cb - tip))
        if k3 < 4:
            pts.append((px + cw / 4, cb - chh * 0.3))
    pts.append((fx + cw, cb - chh * 0.18))
    Cr.poly([(fx - cw * 0.92, cb - chh * 0.2)] + [(fx - cw * 0.7, cb - chh * 0.55), (fx, cb - chh * 0.72), (fx + cw * 0.7, cb - chh * 0.55)] +
            [(fx + cw * 0.92, cb - chh * 0.2)], (150, 15, 35, 255))
    Cr.poly(pts, wht, ink, RH * 0.008)
    Cr.poly([(fx - cw * 1.02, cb - chh * 0.2), (fx + cw * 1.02, cb - chh * 0.2), (fx + cw * 1.02, cb), (fx - cw * 1.02, cb)], wht, ink, RH * 0.008)
    cra = alpha(Cr)
    crr = Cr.rgba()
    is_gold = crr[..., 1] > 0.5
    col = np.where(is_gold[..., None], gold, crr[..., :3])
    sh = np.clip(emboss(cra, RH * 0.012, 1.2), 0.3, 1.8)
    sd = np.clip(fblur(shift(cra, RH * 0.02, RH * 0.03), RH * 0.03), 0, 1)
    c = c * (1 - 0.5 * sd)[..., None]
    c = mix(c, col * sh[..., None], cra)
    J = Layer(W, H)
    erm_y0, erm_y1 = cb, cb + chh * 0.16
    J.poly([(fx - cw * 1.08, erm_y0), (fx + cw * 1.08, erm_y0), (fx + cw * 1.08, erm_y1), (fx - cw * 1.08, erm_y1)], (250, 248, 240, 255), ink, RH * 0.006)
    for k4 in range(7):
        ex_ = fx - cw * 0.9 + k4 * cw * 0.3
        J.poly([(ex_, erm_y0 + chh * 0.03), (ex_ + RH * 0.012, erm_y0 + chh * 0.1), (ex_ - RH * 0.012, erm_y0 + chh * 0.1)], (20, 20, 20, 255))
    for k4, gc in enumerate(((210, 20, 40), (30, 170, 80), (40, 90, 220), (30, 170, 80), (210, 20, 40))):
        gx = fx - cw * 0.75 + k4 * cw * 0.375
        J.ellipse((gx - RH * 0.035, cb - chh * 0.15, gx + RH * 0.035, cb - chh * 0.04), gc + (255,), ink, RH * 0.005)
        J.circle(gx - RH * 0.012, cb - chh * 0.12, RH * 0.008, (255, 255, 255, 220))
    for k3 in range(5):
        px = fx - cw + k3 * cw / 2
        tip = chh * (0.75 if k3 == 2 else (0.6 if k3 % 2 == 0 else 0.5))
        J.circle(px, cb - tip - RH * 0.02, RH * 0.032, (245, 240, 230, 255), (120, 110, 100, 255), RH * 0.004)
        J.circle(px - RH * 0.01, cb - tip - RH * 0.03, RH * 0.01, (255, 255, 255, 255))
    c = over(c, J.rgba())
    # tufted (capitonne) velvet with pearl buttons on the lower parts
    tq = RH * 0.42
    du_, dv_ = (x + y) / tq, (x - y) / tq
    fu, fv = du_ - np.floor(du_) - 0.5, dv_ - np.floor(dv_) - 0.5
    puff = np.clip(1 - 2 * np.maximum(np.abs(fu), np.abs(fv)), 0, 1)
    below = smooth(B + RH * 0.12, B + RH * 0.3, y)
    c = c * (1 - below * (0.45 - 0.55 * puff ** 0.6))[..., None]
    Bt = Layer(W, H)
    i0, i1 = int(np.floor((0 + 0) / tq)) - 2, int((W + H) / tq) + 2
    for i in range(i0, i1):
        for j in range(int(-H / tq) - 2, int(W / tq) + 2):
            bx, by = (i + j) * tq / 2, (i - j) * tq / 2
            if 0 <= bx < W and 0 <= by < H and by > at(E.B, bx) + RH * 0.3:
                Bt.circle(bx, by, RH * 0.03, (238, 232, 225, 255), (120, 90, 120, 255), RH * 0.004)
                Bt.circle(bx - RH * 0.01, by - RH * 0.01, RH * 0.01, (255, 255, 255, 255))
    c = over(c, Bt.rgba())
    # pearl strings swagging along the top of the band
    Pr = Layer(W, H)
    pin_x = []
    xx = lay.x0 + RH * 0.2
    while xx < lay.x1:
        if abs(xx - fx) > rx_ * 1.15:
            pin_x.append(xx)
        xx += RH * 0.9
    pr = RH * 0.028
    for a_, b_ in zip(pin_x[:-1], pin_x[1:]):
        if b_ - a_ > RH * 1.2:
            continue
        for depth, rad in ((0.2, pr), (0.32, pr * 0.85)):
            n_p = int((b_ - a_) / (rad * 2.1))
            for i in range(n_p + 1):
                t = i / max(n_p, 1)
                px = a_ + (b_ - a_) * t
                sag = min(at(E.Hh, px) * depth, RH * depth)
                py = at(E.T, px) + RH * 0.06 + sag * 4 * t * (1 - t)
                Pr.circle(px + rad * 0.2, py + rad * 0.3, rad, (40, 0, 50, 150))
                Pr.circle(px, py, rad, (238, 232, 225, 255))
                Pr.circle(px - rad * 0.3, py - rad * 0.3, rad * 0.35, (255, 255, 255, 255))
    for px in pin_x:
        py = at(E.T, px) + RH * 0.06
        Pr.circle(px, py, RH * 0.05, (230, 180, 70, 255), (100, 60, 10, 255), RH * 0.006)
        Pr.circle(px, py, RH * 0.022, (200, 20, 50, 255))
        dy = py + RH * 0.12
        Pr.line([(px, py + RH * 0.04), (px, dy)], (230, 180, 70, 255), RH * 0.008)
        Pr.ellipse((px - pr * 1.1, dy, px + pr * 1.1, dy + pr * 3.0), (240, 235, 228, 255), (150, 140, 130, 255), RH * 0.003)
        Pr.circle(px - pr * 0.35, dy + pr * 0.9, pr * 0.35, (255, 255, 255, 255))
    c = over(c, Pr.rgba())
    # roses beside the cartouche and on the lower parts
    Ro = Layer(W, H)
    rose_cols = [(150, 10, 30, 255), (200, 25, 45, 255), (120, 5, 25, 255), (90, 5, 20, 255)]
    rk = (60, 0, 15, 255)
    spots = [(fx - rx_ * 1.15 - RH * 0.75, fy + RH * 0.05, RH * 0.24), (fx + rx_ * 1.15 + RH * 0.75, fy + RH * 0.05, RH * 0.24)]
    for (px, py, wdt) in lower_spots(E, lay, x, y):
        spots.append((px, py, min(RH * 0.38, wdt * 0.4)))
    for k5, (px, py, r) in enumerate(spots):
        if px < lay.x0 + r or px > lay.x1 - r * 0.5:
            continue
        for a in (0.4 + k5, 2.6 + k5, 4.4 + k5):
            leaf(Ro, (px, py), a, r * 1.6, r * 0.6, (40, 95, 45, 255), (15, 40, 15, 255), RH * 0.008)
        flower(Ro, px, py, r, 0.7 * k5, rose_cols, rk, RH * 0.008, 5, 5, 0.04)
    rr_ = Ro.rgba()
    sd = np.clip(fblur(shift(rr_[..., 3], RH * 0.02, RH * 0.03), RH * 0.03), 0, 1)
    c = c * (1 - 0.45 * sd)[..., None]
    c = over(c, rr_)
    return np.clip(c, 0, 1), 0.3, 0.08


# ---------------------------------------------------------------------------------------------- set B helpers
# (band coordinates: _X(f) along the gun, _v / _P across it, _env the receiver's real depth)


def _s(fn, x):
    """A scalar of one of lay's band functions."""
    return float(fn(np.array([float(x)]))[0])


def _X(lay, f):
    """Canvas x at fraction f along the gun (0 = muzzle, 1 = butt)."""
    return lay.x0 + (lay.x1 - lay.x0) * f


def _prof(lay):
    """(env, hero): env[x] is a smooth upper envelope of the band height (the receiver's real height even where the
    band has holes), hero the receiver's height (the size unit of the hero art)."""
    if getattr(lay, "_b_env", None) is None:
        W = lay.W
        h = lay.height(np.arange(W))
        k = max(4, W // 10)
        hp = np.pad(h, k, mode="edge")
        mx = np.lib.stride_tricks.sliding_window_view(hp, 2 * k + 1).max(1)
        kk = max(2, W // 20)
        env = np.convolve(np.pad(mx, kk, mode="edge"), np.ones(kk) / kk, "same")[kk:-kk]
        xs = np.arange(int(lay.x0), int(lay.x1) + 1)
        hero = float(np.percentile(h[xs], 80))
        lay._b_env, lay._b_hero = np.minimum(env, hero * 1.05), hero
    return lay._b_env, lay._b_hero


def _env(lay, x):
    return np.interp(x, np.arange(lay.W), _prof(lay)[0])


def _hero(lay):
    return _prof(lay)[1]


def _v(lay, x, y):
    """Band coordinate: 0 at the top of the gun, 1 at the bottom of the receiver envelope, >1 below (magazine, grip)."""
    return (y - lay.top(x)) / _env(lay, x)


def _P(lay, f, v):
    X = _X(lay, f)
    return (X, _s(lay.top, X) + v * float(_env(lay, X)))


def _bpoly(lay, fv, n=10, closed=True):
    """Points of a shape given in band coordinates (f, v), edges densified so the shape follows the band."""
    pts = []
    segs = list(zip(fv, fv[1:] + fv[:1])) if closed else list(zip(fv[:-1], fv[1:]))
    for (f0, v0), (f1, v1) in segs:
        for t in np.linspace(0, 1, n, endpoint=False):
            pts.append(_P(lay, f0 + (f1 - f0) * t, v0 + (v1 - v0) * t))
    if not closed:
        pts.append(_P(lay, *fv[-1]))
    return pts


def _below(lay):
    """Boxes (xa, xb, ya, yb) of the parts hanging well below the receiver: magazine, grip, foregrip."""
    if getattr(lay, "_b_below", None) is None:
        W, H = lay.W, lay.H
        xs = np.arange(W)
        lim = lay.top(xs) + _env(lay, xs)
        m = lay.mask & (np.arange(H)[:, None] > lim[None, :])
        anyc = m.any(0)
        lo = np.where(anyc, H - 1 - np.argmax(m[::-1], 0), 0)
        tall = (lo - lim) > H * 0.15
        boxes = []
        x = 0
        while x < W:
            if tall[x]:
                x2 = x
                while x2 < W and tall[x2]:
                    x2 += 1
                if x2 - x > W * 0.03:
                    boxes.append((float(x), float(x2), float(lim[x:x2].mean()), float(lo[x:x2].max())))
                x = x2
            else:
                x += 1
        lay._b_below = boxes
    return lay._b_below


def _rgba_of(rgb, a):
    return np.dstack([rgb, np.clip(a, 0, 1)]).astype(np.float32)


def _tube(L, pts, w, dark, light, outline=(10, 10, 12, 255), steps=6):
    """A shaded chrome/metal tube along pts (concentric strokes, lit from above)."""
    L.line(pts, outline, w * 1.15)
    for k in range(steps):
        t = k / (steps - 1)
        col = tuple(int(dark[i] + (light[i] - dark[i]) * t) for i in range(3)) + (255,)
        off = -w * 0.18 * t
        L.line([(px, py + off) for px, py in pts], col, max(1.0, w * (1 - 0.82 * t)))


def d_mecha_unit(W, H, lay):
    """white mech armour plates, hazard stripes, black joints, unit 07"""
    x, y = grid(W, H)
    hero = _hero(lay)
    env = _env(lay, x)
    v = (y - lay.top(x)) / env
    rib = ((y / max(hero * 0.05, 5)) % 1.0 < 0.5).astype(np.float32)
    dark = ramp(noise(W, H, 1301, 5.0), [(0, (0.05, 0.055, 0.065)), (1, (0.13, 0.135, 0.15))]) * (0.82 + 0.18 * rib)[..., None]
    fr = [0.035, 0.13, 0.24, 0.36, 0.47, 0.58, 0.69, 0.8, 0.9, 0.97]
    pid = np.zeros((H, W), np.float32)
    dmin = np.full((H, W), 1e9, np.float32)
    dsg = np.zeros((H, W), np.float32)
    for i, f in enumerate(fr):
        X = _X(lay, f)
        s = 0.55 if i % 2 else -0.4
        my = _s(lay.top, X) + 0.5 * float(_env(lay, X))
        d = x - (X + (y - my) * s)
        pid += (d > 0)
        ad = np.abs(d)
        cl = ad < dmin
        dmin = np.where(cl, ad, dmin)
        dsg = np.where(cl, np.sign(d), dsg)
    hs = 0.6
    dh = (v - hs) * env
    lower = v > hs
    shade = 0.92 + 0.08 * (((pid * 2 + lower) * 0.618) % 1.0)
    grad = (1.05 - 0.14 * np.clip(v, 0, 1))
    arm = solid(W, H, (0.94, 0.94, 0.92)) * (shade * grad)[..., None]
    arm = np.where(lower[..., None], solid(W, H, (0.8, 0.81, 0.82)) * (shade * grad)[..., None], arm)
    stripes = (((x + y) / (hero * 0.17)) % 1.0) < 0.5
    haz = np.where(stripes[..., None], solid(W, H, (1.0, 0.78, 0.05)), solid(W, H, (0.05, 0.05, 0.06)))
    arm = np.where((lower & (pid >= 4) & (pid <= 6))[..., None], haz, arm)
    orange = solid(W, H, (1.0, 0.4, 0.04)) * grad[..., None]
    arm = np.where((((pid == 1) & ~lower) | ((pid == 8) & lower) | ((pid == 2) & lower))[..., None], orange, arm)
    ew = max(4.0, hero * 0.03)
    bev = (dmin < ew) & (dmin >= ew * 0.3)
    arm = np.where((bev & (dsg > 0))[..., None], arm * 1.12, arm)
    arm = np.where((bev & (dsg < 0))[..., None], arm * 0.72, arm)
    hb = (np.abs(dh) < ew) & (np.abs(dh) >= ew * 0.3)
    arm = np.where((hb & (dh > 0))[..., None], arm * 1.1, arm)
    arm = np.where((hb & (dh < 0))[..., None], arm * 0.75, arm)
    seam = (dmin < ew * 0.3) | (np.abs(dh) < ew * 0.3)
    arm = np.where(seam[..., None], solid(W, H, (0.06, 0.06, 0.07)), arm)
    c = np.where((v <= 1.0)[..., None], arm, dark)
    edge = np.abs(v - 1.0) * env < ew * 0.6
    c = np.where(edge[..., None], solid(W, H, (0.02, 0.02, 0.025)), c)
    L = Layer(W, H)
    for f in fr:
        X = _X(lay, f)
        for vv in (0.12, 0.45, 0.78):
            px, py = _P(lay, f, vv)
            px += (py - (_s(lay.top, X) + 0.5 * float(_env(lay, X)))) * (0.55 if fr.index(f) % 2 else -0.4) + hero * 0.04
            r = hero * 0.022
            L.circle(px, py, r * 1.3, (40, 40, 45, 255))
            L.circle(px, py, r * 0.8, (175, 178, 185, 255))
    for xa, xb, ya, yb in _below(lay):
        hgt = yb - ya
        y0 = yb - hgt * 0.16
        pts = []
        P = hero * 0.17
        k = math.floor((xa - (yb - y0)) / P) * P
        while k < xb + hgt:
            L.poly([(k, yb + 4), (k + P / 2, yb + 4), (k + P / 2 + (yb - y0), y0), (k + (yb - y0), y0)], (255, 200, 15, 255))
            k += P
        L.poly([(xa - 50, y0 - hero * 0.035), (xb + 50, y0 - hero * 0.035), (xb + 50, y0), (xa - 50, y0)], (255, 100, 10, 255))
        L.line([(xa - 50, ya + hgt * 0.1), (xb + 50, ya + hgt * 0.1)], (255, 100, 10, 255), max(3, hero * 0.02))
    X = _X(lay, 0.75)
    e = float(_env(lay, X))
    tx, ty = X, _s(lay.top, X) + e * 0.31
    fs = e * 0.56
    L.text((tx + fs * 0.05, ty + fs * 0.05), "07", ("AGENCYB.TTF", fs), (255, 100, 10, 255))
    L.text((tx, ty), "07", ("AGENCYB.TTF", fs), (18, 18, 20, 255))
    lx, ly = tx - fs * 0.62, ty - fs * 0.22
    L.poly([(lx - fs * 0.2, ly - fs * 0.09), (lx + fs * 0.2, ly - fs * 0.09), (lx + fs * 0.2, ly + fs * 0.09), (lx - fs * 0.2, ly + fs * 0.09)], (18, 18, 20, 255))
    L.text((lx, ly), "UNIT", ("bahnschrift.ttf", fs * 0.13), (240, 240, 235, 255))
    X2 = _X(lay, 0.6)
    e2 = min(float(_env(lay, X2)), hero)
    wx, wy, ws = X2, _s(lay.top, X2) + e2 * 0.2, e2 * 0.13
    L.poly([(wx - ws * 1.5, wy - ws), (wx + ws * 1.5, wy - ws), (wx + ws * 1.5, wy + ws), (wx - ws * 1.5, wy + ws)], (255, 200, 15, 255), (18, 18, 20, 255), max(1.5, ws * 0.12))
    L.poly([(wx - ws * 1.2, wy + ws * 0.7), (wx - ws * 0.55, wy - ws * 0.7), (wx + ws * 0.1, wy + ws * 0.7)], (18, 18, 20, 255))
    L.text((wx - ws * 0.55, wy + ws * 0.25), "!", ("ariblk.ttf", ws * 0.9), (255, 200, 15, 255))
    for k in range(5):
        bx = wx + ws * (0.35 + k * 0.22)
        L.line([(bx, wy - ws * 0.6), (bx, wy + ws * 0.6)], (18, 18, 20, 255), ws * (0.08 if k % 2 else 0.14))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.45, 0.25


def d_red_vector(W, H, lay):
    """red, white and black techno shards over carbon"""
    x, y = grid(W, H)
    hero = _hero(lay)
    v = _v(lay, x, y)
    s = max(hero * 0.045, 6)
    i, j = np.floor(x / s), np.floor(y / s)
    fx, fy = x / s - i, y / s - j
    tw = ((i + j) % 4) < 2
    tow = np.where(tw, np.sin(fy * np.pi), np.sin(fx * np.pi))
    c = solid(W, H, (0.04, 0.04, 0.045)) + (0.025 + 0.09 * tow ** 3)[..., None] * np.where(tw, 1.0, 0.65)[..., None]
    # red slashes across what hangs below
    P = hero * 1.5
    u = (x * 0.6 + y) % P
    low = v > 1.02
    c = np.where((low & (np.abs(u - P * 0.5) < hero * 0.16))[..., None], solid(W, H, (0.78, 0.03, 0.05)), c)
    c = np.where((low & (np.abs(u - P * 0.5 - hero * 0.24) < hero * 0.025))[..., None], solid(W, H, (0.92, 0.92, 0.92)), c)
    # the red mass with an angular lower edge
    bot = [(1.05, 0.78), (0.93, 0.78), (0.88, 0.5), (0.8, 0.5), (0.76, 0.88), (0.6, 0.88), (0.55, 0.6), (0.44, 0.6), (0.4, 0.9),
           (0.27, 0.9), (0.23, 0.62), (0.12, 0.62), (0.08, 0.85), (-0.05, 0.85)]
    shape = [(-0.05, -0.5), (1.05, -0.5)] + bot
    Lr = Layer(W, H)
    Lr.poly(_bpoly(lay, shape, 14), (255, 255, 255, 255))
    a = Lr.rgba()[..., 3]
    red = ramp(np.clip(v, 0, 1), [(0, (0.95, 0.08, 0.1)), (0.5, (0.78, 0.03, 0.06)), (1, (0.5, 0.01, 0.03))])
    red = red * (0.92 + 0.12 * noise(W, H, 1401, 3.0))[..., None]
    sheen = np.exp(-((v - 0.12) / 0.06) ** 2) * 0.35
    red = red + sheen[..., None] * np.array([1.0, 0.6, 0.6])
    c = mix(c, red, a)
    L = Layer(W, H)
    black, white = (14, 14, 16, 255), (238, 238, 240, 255)
    for poly in ([(0.36, 1.3), (0.445, 0.3), (0.47, 0.3), (0.43, 1.3)], [(0.84, 1.3), (0.9, 0.28), (0.935, 0.28), (0.9, 1.3)],
                 [(0.66, 1.3), (0.72, 0.42), (0.78, 1.3)], [(0.15, 1.3), (0.2, 0.35), (0.22, 0.35), (0.2, 1.3)]):
        L.poly(_bpoly(lay, poly, 8), black)
    for poly in ([(0.62, -0.5), (0.66, -0.5), (0.585, 0.45), (0.555, 0.45)], [(0.69, -0.5), (0.705, -0.5), (0.625, 0.45), (0.61, 0.45)],
                 [(0.5, 0.66), (0.78, 0.66), (0.8, 0.72), (0.52, 0.72)]):
        L.poly(_bpoly(lay, poly, 8), white)
    for k, f in enumerate((0.07, 0.115)):
        L.poly(_bpoly(lay, [(f + 0.04, 0.1), (f + 0.065, 0.1), (f + 0.025, 0.45), (f + 0.065, 0.8), (f + 0.04, 0.8), (f, 0.45)], 6),
               white if k == 0 else black)
    # the arrowhead emblem at the back
    L.poly(_bpoly(lay, [(0.8, 0.27), (0.97, 0.06), (0.95, 0.27), (0.97, 0.48)], 8), white)
    L.poly(_bpoly(lay, [(0.835, 0.27), (0.945, 0.13), (0.93, 0.27), (0.945, 0.41)], 8), black)
    L.poly(_bpoly(lay, [(0.87, 0.27), (0.93, 0.2), (0.92, 0.27), (0.93, 0.34)], 8), (230, 20, 30, 255))
    wl = max(3.0, hero * 0.014)
    L.line(_bpoly(lay, [(0.02, 0.06), (0.38, 0.06), (0.42, 0.2), (0.52, 0.2)], 12, closed=False), white, wl)
    px, py = _P(lay, 0.52, 0.2)
    L.circle(px, py, wl * 1.8, white)
    L.line(_bpoly(lay, [(0.98, 0.9), (0.62, 0.95)], 12, closed=False), (150, 150, 155, 255), wl)
    L.line(_bpoly(lay, bot[1:-1], 6, closed=False), white, wl * 0.8)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.4, 0.12


def d_black_ice(W, H, lay):
    """glossy black lacquer, frost ferns creeping from the muzzle, a glowing ice-blue impact crack"""
    x, y = grid(W, H)
    hero = _hero(lay)
    span = lay.x1 - lay.x0
    v = _v(lay, x, y)
    fpos = np.clip((x - lay.x0) / span, 0, 1)
    rng = np.random.default_rng(1503)
    # glossy black lacquer: blue-black, a hard specular streak along the top, two diagonal sheens
    c = ramp(noise(W, H, 1501, 2.0), [(0, (0.006, 0.008, 0.016)), (1, (0.03, 0.04, 0.065))])
    spec = np.exp(-((v - 0.14) / 0.045) ** 2) * (0.6 + 0.4 * noise(W, H, 1502, 2.0))
    c = c + spec[..., None] * np.array([0.32, 0.4, 0.5])
    for fx in (0.5, 0.88):
        X = _X(lay, fx)
        sh = np.exp(-((x - X - (y - lay.top(x)) * 0.7) / (hero * 0.13)) ** 2)
        c = c + sh[..., None] * np.array([0.05, 0.08, 0.12])
    # frosted haze where the frost grows: the muzzle end and the bottom of the magazine / grip
    hz = smooth(0.36, 0.04, fpos + 0.1 * (noise(W, H, 1504, 3.0) - 0.5))
    for xa, xb, ya, yb in _below(lay):
        hz = np.maximum(hz, smooth(ya + (yb - ya) * 0.45, yb, y) * ((x > xa - 40) & (x < xb + 40)))
    grain = noise(W, H, 1505, 24.0, 3)
    c = mix(c, solid(W, H, (0.62, 0.76, 0.9)) * (0.8 + 0.3 * grain)[..., None], hz * 0.5)
    # frost ferns: crystalline feathers, a stem with side branches that carry their own
    F = Layer(W, H)
    ice = (232, 247, 255, 235)

    def fern(px, py, ang, length, w, depth):
        n = max(3, int(length / max(hero * 0.035, length / 11)))
        st = length / n
        for k in range(n):
            ang += (rng.random() - 0.5) * 0.2
            nx, ny = px + math.cos(ang) * st, py + math.sin(ang) * st
            F.line([(px, py), (nx, ny)], ice, max(1.1, w * (1 - 0.7 * k / n)))
            if depth > 0:
                rem = length * (1 - k / n)
                for sgn in (-1, 1):
                    sub = rem * 0.4 * (0.55 + 0.6 * rng.random())
                    if sub > hero * 0.03:
                        fern(nx, ny, ang + sgn * (0.9 + 0.3 * rng.random()), sub, w * 0.55, depth - 1)
            px, py = nx, ny

    for k in range(7):
        X = lay.x0 - hero * 0.05
        e = float(_env(lay, lay.x0 + 5))
        py = _s(lay.top, lay.x0 + 5) + e * (0.05 + 0.9 * k / 6)
        fern(X, py, (rng.random() - 0.5) * 0.5, span * (0.16 + 0.16 * rng.random()), hero * 0.022, 2)
    for k in range(4):
        X = _X(lay, 0.06 + 0.07 * k)
        fern(X, _s(lay.top, X) + float(_env(lay, X)) * 1.05, -0.7 - 0.3 * rng.random(), hero * (0.6 + 0.5 * rng.random()), hero * 0.016, 2)
    for xa, xb, ya, yb in _below(lay):
        for k in range(9):
            fern(xa + (xb - xa) * rng.random(), yb + hero * 0.05, -math.pi / 2 + (rng.random() - 0.5) * 2.2, (yb - ya) * (0.15 + 0.2 * rng.random()),
                 hero * 0.015, 2)
    fg = F.rgba()
    c = c + glow_of(fg, hero * 0.05, 0.55) * np.array([0.6, 0.85, 1.0])
    c = over(c, fg, 0.9)
    # the impact: a crushed white star at the back with glowing angular cracks running out of it
    L = Layer(W, H)
    C = Layer(W, H)
    blue, core = (70, 190, 255, 255), (235, 250, 255, 255)

    def crack(px, py, ang, length, w, depth, bias=None, jit=0.7):
        dist = 0.0
        while dist < length:
            st = hero * (0.07 + 0.16 * rng.random())
            a = ang + (rng.random() - 0.5) * jit
            if bias is not None:
                e = float(_env(lay, px))
                mid = _s(lay.top, px) + bias * e
                a += 0.5 * float(np.clip((mid - py) / max(e * 0.4, 1), -1, 1)) * (1 if math.cos(a) > 0 else -1)
            nx, ny = px + math.cos(a) * st, py + math.sin(a) * st
            ww = max(1.4, w * (1 - 0.6 * dist / length))
            L.line([(px, py), (nx, ny)], blue, ww)
            C.line([(px, py), (nx, ny)], core, max(1.0, ww * 0.4))
            if depth and rng.random() < 0.28:
                crack(nx, ny, a + (1 if rng.random() < 0.5 else -1) * (0.6 + 0.6 * rng.random()), length * (0.12 + 0.15 * rng.random()), ww * 0.6,
                      depth - 1)
            px, py = nx, ny
            dist += st

    X = _X(lay, 0.8)
    e = min(float(_env(lay, X)), hero)
    ix, iy = X, _s(lay.top, X) + e * 0.45
    rays = sorted(k / 10 * 2 * math.pi + rng.random() * 0.35 for k in range(10))
    for a in rays:
        crack(ix, iy, a, hero * (0.4 + 0.8 * rng.random()), hero * 0.02, 1, jit=0.35)
    for rr in (0.22, 0.42, 0.66):
        for k in range(len(rays)):
            if rng.random() < 0.3:
                continue
            a0, a1 = rays[k], rays[(k + 1) % len(rays)] + (2 * math.pi if k == len(rays) - 1 else 0)
            r0, r1 = e * rr * (0.85 + 0.3 * rng.random()), e * rr * (0.85 + 0.3 * rng.random())
            p0 = (ix + math.cos(a0) * r0, iy + math.sin(a0) * r0)
            p1 = (ix + math.cos(a1) * r1, iy + math.sin(a1) * r1)
            ww = hero * 0.014 * (1 - rr * 0.6)
            L.line([p0, p1], blue, ww)
            C.line([p0, p1], core, max(1.0, ww * 0.45))
    for vv in (0.3, 0.7):
        crack(ix, iy, math.pi + (rng.random() - 0.5) * 0.3, span * 0.5, hero * 0.02, 1, bias=vv, jit=0.45)
    for xa, xb, ya, yb in _below(lay):
        crack((xa + xb) / 2, ya - hero * 0.15, math.pi / 2, (yb - ya) * 0.55, hero * 0.016, 1)
    g = L.rgba()
    c = c + blurf(g[..., 3], hero * 0.1)[..., None] * np.array([0.03, 0.14, 0.26])
    c = c + glow_of(g, hero * 0.03, 0.8) + glow_of(g, hero * 0.008, 0.6)
    c = over(c, g)
    c = over(c, C.rgba())
    d = np.hypot(x - ix, y - iy)
    c = mix(c, solid(W, H, (0.9, 0.96, 1.0)) * (0.8 + 0.3 * grain)[..., None], smooth(e * 0.13, e * 0.06, d))
    c = c + (np.exp(-(d / (e * 0.12)) ** 2) * 0.6)[..., None] * np.array([0.85, 0.95, 1.0])
    c = c + (np.exp(-(d / (e * 0.35)) ** 2) * 0.25)[..., None] * np.array([0.2, 0.55, 1.0])
    c = add(c, sparkle(W, H, 40, 1506, hero * 0.012, (0.8, 0.95, 1.0)), 0.6)
    return np.clip(c, 0, 1), 0.35, 0.1


def _skull(L, cx, cy, sh, bone, hole):
    L.ellipse((cx - 0.42 * sh, cy - 0.5 * sh, cx + 0.42 * sh, cy + 0.2 * sh), bone)
    L.poly([(cx - 0.36 * sh, cy), (cx + 0.36 * sh, cy), (cx + 0.27 * sh, cy + 0.3 * sh), (cx - 0.27 * sh, cy + 0.3 * sh)], bone)
    L.poly([(cx - 0.24 * sh, cy + 0.26 * sh), (cx + 0.24 * sh, cy + 0.26 * sh), (cx + 0.2 * sh, cy + 0.48 * sh), (cx - 0.2 * sh, cy + 0.48 * sh)], bone)
    for sgn in (-1, 1):
        L.poly([(cx + sgn * 0.05 * sh, cy - 0.12 * sh), (cx + sgn * 0.3 * sh, cy - 0.2 * sh), (cx + sgn * 0.33 * sh, cy + 0.0 * sh),
                (cx + sgn * 0.24 * sh, cy + 0.1 * sh), (cx + sgn * 0.08 * sh, cy + 0.08 * sh)], hole)
    L.poly([(cx, cy + 0.08 * sh), (cx - 0.07 * sh, cy + 0.22 * sh), (cx, cy + 0.2 * sh), (cx + 0.07 * sh, cy + 0.22 * sh)], hole)
    L.line([(cx - 0.22 * sh, cy + 0.36 * sh), (cx + 0.22 * sh, cy + 0.36 * sh)], hole, sh * 0.025)
    for k in range(-3, 4):
        L.line([(cx + k * 0.06 * sh, cy + 0.28 * sh), (cx + k * 0.06 * sh, cy + 0.46 * sh)], hole, sh * 0.018)
    L.line([(cx + 0.1 * sh, cy - 0.5 * sh), (cx + 0.05 * sh, cy - 0.38 * sh), (cx + 0.13 * sh, cy - 0.3 * sh), (cx + 0.08 * sh, cy - 0.2 * sh)], hole, sh * 0.018)


def d_corrupted(W, H, lay):
    """a glitched skull: RGB split, pixel-sorted streaks, data melting down the magazine"""
    x, y = grid(W, H)
    hero = _hero(lay)
    rng = np.random.default_rng(1601)
    c = ramp(y / H, [(0, (0.05, 0.0, 0.08)), (1, (0.0, 0.01, 0.04))])
    c = mix(c, solid(W, H, (0.6, 0.0, 0.5)), smooth(0.55, 0.78, noise(W, H, 1602, 1.6)) * 0.7)
    c = mix(c, solid(W, H, (0.0, 0.5, 0.65)), smooth(0.58, 0.8, noise(W, H, 1603, 1.9)) * 0.7)
    L = Layer(W, H)
    L.poly(_bpoly(lay, [(-0.05, 0.04), (0.58, 0.04), (0.56, 0.2), (-0.05, 0.2)], 10), (255, 20, 200, 255))
    L.poly(_bpoly(lay, [(0.25, 0.76), (1.05, 0.76), (1.05, 0.86), (0.27, 0.86)], 10), (0, 240, 255, 255))
    L.poly(_bpoly(lay, [(0.05, 0.62), (0.4, 0.62), (0.4, 0.66), (0.05, 0.66)], 10), (255, 255, 255, 255))
    c = over(c, L.rgba())
    # data melting down what hangs below: bright bars that fade as they run down
    D = Layer(W, H)
    pal8 = [(255, 30, 200), (0, 235, 255), (255, 255, 255), (255, 230, 30)]
    for xa, xb, ya, yb in _below(lay):
        xx = xa - hero * 0.05
        while xx < xb + hero * 0.05:
            bw = hero * (0.025 + 0.07 * rng.random())
            if rng.random() < 0.8:
                col = pal8[int(rng.random() * 3.4)]
                y0 = ya - hero * (0.1 + 0.2 * rng.random())
                ln = (yb - ya) * (0.25 + 0.85 * rng.random())
                for k in range(10):
                    a = int(255 * (1 - k / 10) ** 1.4)
                    D.poly([(xx, y0 + ln * k / 10), (xx + bw, y0 + ln * k / 10), (xx + bw, y0 + ln * (k + 1) / 10), (xx, y0 + ln * (k + 1) / 10)], col + (a,))
            xx += bw * (1.0 + 0.5 * rng.random())
    c = over(c, D.rgba(), 0.85)
    # horizontal slices shifted
    yy = 0
    while yy < H:
        h = int(max(3, hero * (0.015 + 0.14 * rng.random() ** 2)))
        if rng.random() > 0.45:
            big = hero * (0.04 + 0.8 * rng.random() ** 1.5)
            dx = int(big * (1 if rng.random() < 0.5 else -1))
            c[yy:yy + h] = np.roll(c[yy:yy + h], dx, axis=1)
        yy += h
    d = max(2, int(hero * 0.035))
    c = np.dstack([np.roll(c[..., 0], d, axis=1), c[..., 1], np.roll(c[..., 2], -d, axis=1)])
    # broken data blocks, in clusters
    B = max(6, int(hero * 0.07))
    pal = [(1.0, 0.0, 0.8), (0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.95, 0.1)]
    for _ in range(45):
        X = rng.random() * W
        bx = int(X / B) * B
        by = int((_s(lay.top, X) + float(_env(lay, X)) * (rng.random() * 2.2 - 0.2)) / B) * B
        if by < 0 or by >= H:
            continue
        n = 1 + int(rng.random() * 7)
        for k in range(n):
            x0b = bx + k * B
            if x0b >= W:
                break
            if rng.random() < 0.55:
                c[by:by + B, x0b:x0b + B] = pal[int(rng.random() * len(pal))]
            else:
                sx, sy = int(rng.random() * (W - B)), int(rng.random() * (H - B))
                blk = c[sy:sy + B, sx:sx + B]
                hh, ww = c[by:by + B, x0b:x0b + B].shape[:2]
                c[by:by + hh, x0b:x0b + ww] = blk[:hh, :ww]
    # pixel sorting: horizontal streaks in the band
    for _ in range(150):
        X = rng.random() * W
        e = float(_env(lay, X))
        y0 = int(_s(lay.top, X) + e * (rng.random() * 1.1 - 0.05))
        h = int(max(2, hero * (0.006 + 0.03 * rng.random())))
        xa = int(X)
        xb = int(min(W, xa + hero * (0.3 + 2.5 * rng.random())))
        if y0 < 0 or y0 + h >= H or xb - xa < 4:
            continue
        seg = c[y0:y0 + h, xa:xb]
        idx = np.argsort(seg.sum(2), axis=1)
        c[y0:y0 + h, xa:xb] = np.take_along_axis(seg, idx[..., None], axis=1)
    # the skull on top, readable, with its own RGB ghosts and a few torn slices
    X = _X(lay, 0.76)
    sh = min(float(_env(lay, X)), hero * 1.05) * 1.0
    cx, cy = X, _s(lay.top, X) + sh * 0.5
    S = Layer(W, H)
    _skull(S, cx, cy, sh, (245, 245, 250, 255), (8, 0, 12, 255))
    for sgn in (-1, 1):
        S.circle(cx + sgn * 0.19 * sh, cy - 0.04 * sh, sh * 0.04, (0, 255, 240, 255))
    sk = S.rgba()
    a = sk[..., 3]
    o = max(2, int(sh * 0.05))
    c = c * (1 - 0.6 * np.roll(blurf(a, sh * 0.04), o, 0))[..., None]
    c = c + np.roll(a, -o, 1)[..., None] * np.array([0.9, 0.0, 0.7]) * 0.9
    c = c + np.roll(a, o, 1)[..., None] * np.array([0.0, 0.8, 0.9]) * 0.9
    c = over(c, sk)
    ys = cy - 0.5 * sh
    for k in range(5):
        y0 = int(ys + sh * (0.1 + 0.85 * rng.random()))
        h = int(max(2, sh * (0.02 + 0.05 * rng.random())))
        dx = int(sh * (0.06 + 0.12 * rng.random()) * (1 if k % 2 else -1))
        x0s, x1s = int(cx - sh * 0.9), int(cx + sh * 0.9)
        if 0 <= y0 < H - h and x0s > 0 and x1s < W:
            c[y0:y0 + h, x0s:x1s] = np.roll(c[y0:y0 + h, x0s:x1s], dx, axis=1)
    per = max(4.0, hero * 0.022)
    c = c * (0.86 + 0.14 * ((y / per) % 1.0 < 0.5))[..., None]
    c = c + (noise(W, H, 1604, 300.0, 1) - 0.5)[..., None] * 0.08
    return np.clip(c, 0, 1), 0.3, 0.08


def d_neon_tokyo(W, H, lay):
    """a rain-wet Tokyo night street, neon signs and reflections"""
    x, y = grid(W, H)
    hero = _hero(lay)
    rng = np.random.default_rng(1701)
    c = ramp(y / H, [(0, (0.03, 0.02, 0.09)), (0.5, (0.02, 0.01, 0.06)), (1, (0.01, 0.01, 0.03))])
    # far buildings with a few lit windows
    Bk = Layer(W, H)
    xx = -20.0
    while xx < W:
        bw = hero * (0.4 + 0.8 * rng.random())
        top = H * (0.0 + 0.25 * rng.random())
        Bk.poly([(xx, top), (xx + bw, top), (xx + bw, H), (xx, H)], (12 + int(10 * rng.random()), 10, 28 + int(15 * rng.random()), 255))
        wy = top + hero * 0.08
        while wy < H:
            wx = xx + hero * 0.06
            while wx < xx + bw - hero * 0.08:
                if rng.random() < 0.18:
                    col = (255, 200, 120, 150) if rng.random() < 0.6 else (120, 200, 255, 150)
                    Bk.poly([(wx, wy), (wx + hero * 0.05, wy), (wx + hero * 0.05, wy + hero * 0.07), (wx, wy + hero * 0.07)], col)
                wx += hero * 0.1
            wy += hero * 0.13
        xx += bw
    c = over(c, Bk.rgba(), 0.8)
    Bo = Layer(W, H)
    for _ in range(45):
        px, py, r = rng.random() * W, rng.random() * H, hero * (0.04 + 0.12 * rng.random())
        col = [(255, 40, 170), (40, 230, 255), (255, 220, 40)][int(rng.random() * 3)]
        Bo.circle(px, py, r, col + (90,))
    c = add(c, Bo.rgba(blur=hero * 0.03), 0.6)
    pink, cyan, yellow = (255, 45, 170), (40, 235, 255), (255, 215, 40)
    G = Layer(W, H)
    S = Layer(W, H)
    jp = "YuGothB.ttc"
    signs = [(0.02, 0.16, 0.12, 0.55, "ラーメン", pink), (0.19, 0.31, 0.45, 0.88, "ゲーム", yellow), (0.34, 0.5, 0.1, 0.5, "カラオケ", cyan),
             (0.53, 0.69, 0.5, 0.93, "居酒屋", pink), (0.72, 0.97, 0.08, 0.62, "東京", cyan)]
    for f0, f1, v0, v1, txt, col in signs:
        box = _bpoly(lay, [(f0, v0), (f1, v0), (f1, v1), (f0, v1)], 8)
        S.poly(box, (14, 6, 24, 245))
        bw = max(2.5, hero * 0.022)
        G.line(box + box[:1], col + (255,), bw)
        G.line(box + box[:1], (255, 240, 250, 255), bw * 0.35)
        Xc = _X(lay, (f0 + f1) / 2)
        e = float(_env(lay, Xc))
        hb = (v1 - v0) * e
        wb = _X(lay, f1) - _X(lay, f0)
        fs = min(hb * 0.62, wb * 0.86 / max(1, len(txt)))
        G.text((Xc, _s(lay.top, Xc) + (v0 + v1) / 2 * e), txt, (jp, fs), (255, 235, 250, 255), fs * 0.09, col + (255,))
    vt = [("電気街", yellow), ("ホテル", pink), ("寿司", cyan)]
    for k, (xa, xb, ya, yb) in enumerate(_below(lay)):
        txt, col = vt[k % len(vt)]
        bw_ = xb - xa
        fs = min(bw_ * 0.5, (yb - ya) * 0.85 / len(txt))
        x0b, x1b = (xa + xb) / 2 - fs * 0.7, (xa + xb) / 2 + fs * 0.7
        y0b = ya + hero * 0.1
        y1b = y0b + fs * (len(txt) + 0.6)
        box = [(x0b, y0b), (x1b, y0b), (x1b, y1b), (x0b, y1b)]
        S.poly(box, (14, 6, 24, 245))
        G.line(box + box[:1], col + (255,), max(2.5, fs * 0.06))
        for i, ch in enumerate(txt):
            G.text(((x0b + x1b) / 2, y0b + fs * (0.8 + i)), ch, (jp, fs * 0.8), (255, 235, 250, 255), fs * 0.07, col + (255,))
    c = over(c, S.rgba())
    g = G.rgba()
    glow = glow_of(g, hero * 0.06, 1.4) + glow_of(g, hero * 0.015, 0.9)
    # wet street: the neon mirrored below the receiver, smeared down
    xs = np.arange(W)
    ym = float(np.median((lay.top(xs) + _env(lay, xs))[int(lay.x0):int(lay.x1)]))
    src = glow + g[..., :3] * g[..., 3:4]
    idx = np.clip((2 * ym - np.arange(H)).astype(int), 0, H - 1)
    refl = src[idx]
    im = Image.fromarray((np.clip(refl, 0, 1) * 255).astype(np.uint8)).resize((W, max(8, H // 14)), Image.BILINEAR).resize((W, H), Image.BICUBIC)
    refl = np.asarray(im, np.float32) / 255.0
    ripple = (np.sin(y / max(3.0, hero * 0.03)) * hero * 0.015).astype(int)
    refl = np.take_along_axis(refl, np.clip(x.astype(int) + ripple, 0, W - 1)[..., None].repeat(3, 2), axis=1)
    fade = smooth(ym - hero * 0.05, ym + hero * 0.2, y) * (1 - 0.6 * smooth(ym, H, y))
    c = c + refl * fade[..., None] * 0.9
    c = c + glow
    c = over(c, g)
    R = Layer(W, H)
    for _ in range(int(W * H / 2500)):
        px, py = rng.random() * W, rng.random() * H
        ln = hero * (0.06 + 0.14 * rng.random())
        R.line([(px, py), (px - ln * 0.18, py + ln)], (190, 210, 255, int(50 + 70 * rng.random())), max(1.2, hero * 0.005))
    c = add(c, R.rgba(), 0.7)
    return np.clip(c, 0, 1), 0.3, 0.08


def d_lost_in_space(W, H, lay):
    """an astronaut adrift on a tether, ringed planet, orange-purple nebula"""
    x, y = grid(W, H)
    hero = _hero(lay)
    c = ramp(y / H, [(0, (0.012, 0.004, 0.035)), (1, (0.0, 0.0, 0.015))])
    wx = x / H + 0.7 * noise(W, H, 1801, 1.2)
    wy = y / H + 0.7 * noise(W, H, 1802, 1.2)
    n = gs.fbm2(wx * 1.8, wy * 1.8, 1803, 5, 1.0)
    neb = smooth(0.38, 0.85, n) ** 1.3
    hue = noise(W, H, 1804, 1.1)
    col = ramp(hue, [(0.3, (0.4, 0.07, 0.6)), (0.5, (0.8, 0.15, 0.45)), (0.7, (1.0, 0.5, 0.12))])
    dust = smooth(0.55, 0.78, noise(W, H, 1805, 5.0))
    bias = 0.55 + 0.6 * np.exp(-((x - _X(lay, 0.62)) / (W * 0.35)) ** 2)
    c = c + col * (neb * (1 - 0.75 * dust) * bias)[..., None] * 1.0
    c = add(c, sparkle(W, H, int(W * H / 3000), 1806, H * 0.0012), 0.8)
    c = add(c, sparkle(W, H, 14, 1807, hero * 0.03, (1.0, 0.9, 0.8)), 1.0)
    # big banded planet low on the left
    pcx, pcy, pr = _X(lay, 0.3), H * 1.12, H * 0.62
    d = np.hypot(x - pcx, y - pcy) / pr
    inside = d < 1
    nz = np.sqrt(np.clip(1 - d * d, 0, 1))
    lam = np.clip(((x - pcx) / pr * 0.55 - (y - pcy) / pr * 0.6 + nz * 0.55), 0, 1)
    bands = noise(W, H, 1808, 14.0, 3, sx=0.08, sy=1.0)
    surf = ramp(bands, [(0.3, (0.12, 0.08, 0.35)), (0.55, (0.35, 0.22, 0.65)), (0.75, (0.25, 0.5, 0.8))])
    surf = surf * (0.08 + 1.0 * lam)[..., None]
    c = np.where(inside[..., None], surf, c)
    rim = np.exp(-((d - 1) / 0.025) ** 2) * (0.3 + lam)
    c = c + rim[..., None] * np.array([0.5, 0.45, 1.0]) * 0.8
    # ringed planet at the front of the receiver
    X = _X(lay, 0.47)
    e = min(float(_env(lay, X)), hero)
    rx, ry, rr = X, _s(lay.top, X) + e * 0.55, e * 0.3
    Rg = Layer(W, H)
    Rf = Layer(W, H)
    for k, cc in enumerate([(255, 200, 140), (230, 150, 90), (255, 225, 180)]):
        a, b = rr * (2.1 - k * 0.25), rr * (0.52 - k * 0.06)
        back = [(rx + math.cos(t) * a, ry + math.sin(t) * b) for t in np.linspace(math.pi, 2 * math.pi, 40)]
        front = [(rx + math.cos(t) * a, ry + math.sin(t) * b) for t in np.linspace(0, math.pi, 40)]
        Rg.line(back, cc + (200,), rr * 0.07)
        Rf.line(front, cc + (230,), rr * 0.07)
    c = over(c, Rg.rgba())
    d2 = np.hypot(x - rx, y - ry) / rr
    nz2 = np.sqrt(np.clip(1 - d2 * d2, 0, 1))
    lam2 = np.clip((x - rx) / rr * 0.5 - (y - ry) / rr * 0.5 + nz2 * 0.6, 0, 1)
    ps = ramp(noise(W, H, 1809, 30.0, 3, sx=0.1, sy=1.0), [(0.3, (0.75, 0.3, 0.08)), (0.7, (1.0, 0.65, 0.3))]) * (0.1 + 1.0 * lam2)[..., None]
    c = np.where((d2 < 1)[..., None], ps, c)
    c = over(c, Rf.rgba())
    # the astronaut and its tether
    X = _X(lay, 0.78)
    e = min(float(_env(lay, X)), hero)
    A = e * 0.92
    acx, acy = X, _s(lay.top, X) + e * 0.52
    ang = math.radians(-28)
    ca, sa = math.cos(ang), math.sin(ang)

    def T(u, w):
        return (acx + (u * ca - w * sa) * A, acy + (u * sa + w * ca) * A)
    Lt = Layer(W, H)
    wpt = T(0.12, 0.12)
    tpts = [wpt, (wpt[0] + A * 0.3, wpt[1] + A * 0.25), (wpt[0] - A * 0.1, wpt[1] + A * 0.4), (wpt[0] - A * 0.5, wpt[1] + A * 0.15)]
    fs = np.linspace(0.68, -0.02, 9)
    for k, f in enumerate(fs):
        Xk = _X(lay, f)
        tpts.append((Xk, _s(lay.top, Xk) + float(_env(lay, Xk)) * (0.5 + 0.22 * math.sin(k * 1.3))))
    tp = bezier(tpts, 16)
    tw = max(3.0, hero * 0.02)
    Lt.line(tp, (25, 25, 35, 255), tw * 1.6)
    Lt.line(tp, (205, 205, 215, 255), tw)
    Lt.line([(px, py - tw * 0.25) for px, py in tp], (250, 250, 255, 255), tw * 0.35)
    c = over(c, Lt.rgba())
    La = Layer(W, H)
    ol, wh, gr = (30, 30, 45, 255), (238, 238, 244, 255), (175, 178, 192, 255)
    La.poly([T(0.06, -0.36), T(0.34, -0.36), T(0.34, 0.08), T(0.06, 0.08)], gr, ol, A * 0.02)
    for limb in ([(-0.1, 0.16), (-0.22, 0.42), (-0.12, 0.64)], [(0.1, 0.16), (0.24, 0.38), (0.38, 0.55)],
                 [(-0.16, -0.2), (-0.38, -0.06), (-0.44, -0.3)], [(0.16, -0.2), (0.34, 0.0), (0.3, 0.17)]):
        pts = [T(*p) for p in limb]
        La.line(pts, ol, A * 0.17)
        for p in pts:
            La.circle(p[0], p[1], A * 0.085, ol)
        La.line(pts, wh, A * 0.13)
        for p in pts[:2]:
            La.circle(p[0], p[1], A * 0.065, wh)
        La.circle(pts[-1][0], pts[-1][1], A * 0.075, gr, ol, A * 0.015)
    La.poly([T(-0.2, -0.3), T(0.2, -0.3), T(0.22, 0.12), T(0.13, 0.22), T(-0.13, 0.22), T(-0.22, 0.12)], wh, ol, A * 0.02)
    La.poly([T(-0.11, -0.16), T(0.08, -0.16), T(0.08, -0.02), T(-0.11, -0.02)], (60, 62, 75, 255))
    for k, cc in enumerate([(255, 120, 30, 255), (40, 220, 255, 255), (255, 50, 60, 255)]):
        p = T(-0.07 + k * 0.06, -0.09)
        La.circle(p[0], p[1], A * 0.018, cc)
    La.line([T(-0.2, 0.0), T(0.2, 0.0)], (255, 120, 30, 255), A * 0.025)
    hc = T(0.0, -0.45)
    La.circle(hc[0], hc[1], A * 0.21, wh, ol, A * 0.02)
    vc = T(-0.05, -0.45)
    La.circle(vc[0], vc[1], A * 0.15, (205, 125, 30, 255), ol, A * 0.015)
    hl = T(-0.1, -0.5)
    La.circle(hl[0], hl[1], A * 0.06, (255, 225, 150, 255))
    hl2 = T(0.0, -0.38)
    La.circle(hl2[0], hl2[1], A * 0.025, (255, 240, 200, 255))
    ag = La.rgba()
    c = c + glow_of(ag, A * 0.12, 0.6) * np.array([1.0, 0.55, 0.3])
    c = over(c, ag)
    return np.clip(c, 0, 1), 0.3, 0.08


def _biohazard(W, H, cx, cy, R):
    """Mask (H, W) of the biohazard symbol of radius R at (cx, cy)."""
    x, y = grid(W, H)
    dx, dy = (x - cx) / R, (y - cy) / R
    m = np.zeros((H, W), bool)
    cut = np.zeros((H, W), bool)
    for k in range(3):
        a = -math.pi / 2 + k * 2 * math.pi / 3
        ox, oy = math.cos(a), math.sin(a)
        m |= np.hypot(dx - ox * 0.5, dy - oy * 0.5) < 0.5
        cut |= np.hypot(dx - ox * 0.64, dy - oy * 0.64) < 0.38
    r = np.hypot(dx, dy)
    ring = (np.abs(r - 0.6) < 0.065) & ~cut
    sym = (m & ~cut) | ring
    sym &= r > 0.15
    for k in range(3):
        a = -math.pi / 2 + k * 2 * math.pi / 3 + math.pi / 3
        ox, oy = math.cos(a), math.sin(a)
        along = dx * ox + dy * oy
        across = np.abs(-dx * oy + dy * ox)
        sym &= ~((along > 0) & (along < 0.4) & (across < 0.035))
    return sym


def d_containment_breach(W, H, lay):
    """toxic green slime oozing from cracked steel, biohazard"""
    x, y = grid(W, H)
    hero = _hero(lay)
    rng = np.random.default_rng(1901)
    v = _v(lay, x, y)
    brushed = noise(W, H, 1902, 30.0, 3, sx=0.05, sy=1.0)
    c = ramp(brushed, [(0, (0.08, 0.09, 0.1)), (1, (0.19, 0.2, 0.22))])
    c = c * (0.7 + 0.4 * noise(W, H, 1903, 3.0))[..., None]
    L = Layer(W, H)
    for f in (0.2, 0.42, 0.66, 0.88):
        pts = _bpoly(lay, [(f, -0.3), (f, 1.3)], 12, closed=False)
        L.line(pts, (10, 10, 12, 255), max(3, hero * 0.012))
        L.line([(px + max(3, hero * 0.012), py) for px, py in pts], (90, 92, 98, 255), max(1.5, hero * 0.005))
        for vv in (0.12, 0.88):
            px, py = _P(lay, f, vv)
            L.circle(px + hero * 0.035, py, hero * 0.02, (60, 62, 68, 255), (15, 15, 18, 255), 1.5)
    stripes = (((x + y) / (hero * 0.16)) % 1.0) < 0.5
    haz = np.where(stripes[..., None], solid(W, H, (1.0, 0.8, 0.05)), solid(W, H, (0.04, 0.04, 0.04)))
    hz = (x < _X(lay, 0.06)) & (v < 1.1)
    for xa, xb, ya, yb in _below(lay):
        hz |= (x > xa - 30) & (x < xb + 30) & (y > yb - (yb - ya) * 0.16)
    c = np.where(hz[..., None], haz, c)
    c = over(c, L.rgba())
    # the biohazard badge
    X = _X(lay, 0.58)
    e = min(float(_env(lay, X)), hero)
    bx, by, R = X, _s(lay.top, X) + e * 0.5, e * 0.38
    dd = np.hypot(x - bx, y - by)
    c = np.where((dd < R * 1.18)[..., None], solid(W, H, (0.04, 0.04, 0.04)), c)
    c = np.where((dd < R * 1.08)[..., None], solid(W, H, (1.0, 0.8, 0.06)) * (0.9 + 0.15 * noise(W, H, 1904, 8.0))[..., None], c)
    c = np.where(_biohazard(W, H, bx, by, R * 0.95)[..., None], solid(W, H, (0.03, 0.03, 0.03)), c)
    # a sample canister on the magazine (or the grip): a glass tube of glowing ooze, bubbles, a steel frame
    bxs = _below(lay)
    if bxs:
        xa, xb, ya, yb = max(bxs, key=lambda b: (b[3] - b[2]) * (b[1] - b[0]))
        bw, bh = xb - xa, yb - ya
        wx0, wx1, wy0, wy1 = xa + bw * 0.2, xb - bw * 0.2, ya + bh * 0.1, yb - bh * 0.24
        level = wy0 + (wy1 - wy0) * 0.28
        ins = (x > wx0) & (x < wx1) & (y > wy0) & (y < wy1)
        u = np.clip((x - wx0) / max(wx1 - wx0, 1), 0, 1)
        cyl = np.sin(u * np.pi)
        liq = ramp(np.clip((y - level) / max(wy1 - level, 1), 0, 1), [(0, (0.6, 1.0, 0.25)), (1, (0.12, 0.5, 0.02))])
        liq = liq * (0.5 + 0.7 * cyl)[..., None] * (0.85 + 0.3 * noise(W, H, 1906, 10.0))[..., None]
        glass = solid(W, H, (0.03, 0.07, 0.04)) * (0.6 + 0.8 * cyl)[..., None]
        win = np.where((y > level)[..., None], liq, glass) + (np.exp(-((u - 0.27) / 0.07) ** 2) * 0.45)[..., None]
        c = c + glow_of(_rgba_of(solid(W, H, (0.3, 1.0, 0.1)), (ins & (y > level)).astype(np.float32)), hero * 0.08, 0.7)
        c = np.where(ins[..., None], win, c)
        Lw = Layer(W, H)
        Lw.line([(wx0, level), (wx1, level)], (215, 255, 170, 255), max(2.0, hero * 0.012))
        for _ in range(int(14 + (wy1 - level) / hero * 10)):
            r = (wx1 - wx0) * (0.04 + 0.1 * rng.random())
            px, py = wx0 + r + (wx1 - wx0 - 2 * r) * rng.random(), level + r + (wy1 - level - 2 * r) * rng.random() ** 1.5
            Lw.circle(px, py, r, (220, 255, 170, 70), (230, 255, 190, 230), max(1.0, r * 0.2))
        fw = max(4.0, hero * 0.045)
        fr = [(wx0, wy0), (wx1, wy0), (wx1, wy1), (wx0, wy1)]
        Lw.line(fr + fr[:2], (20, 21, 24, 255), fw * 1.5)
        Lw.line(fr + fr[:2], (150, 152, 160, 255), fw * 0.9)
        Lw.line(fr + fr[:2], (215, 218, 225, 255), fw * 0.3)
        for k in range(1, 6):
            ty = wy0 + (wy1 - wy0) * k / 6
            Lw.line([(wx1 - (wx1 - wx0) * 0.18, ty), (wx1, ty)], (230, 240, 230, 200), max(1.2, hero * 0.008))
        for px, py in ((wx0, wy0), (wx1, wy0), (wx0, wy1), (wx1, wy1)):
            Lw.circle(px, py, fw * 0.55, (190, 192, 200, 255), (20, 20, 22, 255), max(1.0, fw * 0.12))
        c = over(c, Lw.rgba())
    # cracks and slime
    S = Layer(W, H)
    K = Layer(W, H)
    white = (255, 255, 255, 255)
    cracks = [[(0.27, 0.05), (0.3, 0.3), (0.27, 0.5), (0.33, 0.72), (0.31, 1.05)], [(0.76, 0.05), (0.79, 0.3), (0.75, 0.55), (0.81, 0.8), (0.79, 1.1)]]
    drips = []
    # the ooze running along the top edge (around the badge), drips hanging from it
    for f0, f1 in ((-0.04, 0.47), (0.69, 1.04)):
        fs = np.linspace(f0, f1, 40)
        lo = [(f, 0.1 + 0.05 * math.sin(f * 60 + 1.3) + 0.03 * rng.random()) for f in fs]
        S.poly([_P(lay, f0, -0.4)] + [_P(lay, f, vv) for f, vv in lo] + [_P(lay, f1, -0.4)], white)
        f = f0 + 0.02
        while f < f1 - 0.02:
            px, py = _P(lay, f, 0.1)
            drips.append((px, py))
            f += 0.04 + 0.05 * rng.random()
    for cr in cracks:
        pts = _bpoly(lay, cr, 10, closed=False)
        jag = [(px + (rng.random() - 0.5) * hero * 0.05, py + (rng.random() - 0.5) * hero * 0.03) for px, py in pts]
        K.line(jag, (5, 5, 5, 255), max(3, hero * 0.03))
        for k in range(len(jag) - 1):
            S.line([jag[k], jag[k + 1]], white, hero * (0.035 + 0.03 * rng.random()))
        for px, py in jag[::3]:
            S.circle(px, py, hero * (0.04 + 0.04 * rng.random()), white)
        drips += [p for p in jag[2::4]]
    for xa, xb, ya, yb in _below(lay):
        for k in range(3):
            px = xa + (xb - xa) * (0.2 + 0.3 * k)
            drips.append((px, ya - hero * 0.05))
            S.circle(px, ya - hero * 0.05, hero * 0.06, white)
            S.line([(xa + (xb - xa) * 0.1, ya - hero * 0.05), (xb - (xb - xa) * 0.1, ya - hero * 0.04)], white, hero * 0.05)
    for px, py in drips:
        ln = hero * (0.12 + 0.9 * rng.random() ** 1.5)
        w = hero * (0.03 + 0.035 * rng.random())
        S.poly([(px - w * 1.1, py - w), (px + w * 1.1, py - w), (px + w * 0.4, py + ln), (px - w * 0.4, py + ln)], white)
        S.circle(px, py + ln, w * 0.8, white)
    c = over(c, K.rgba())
    raw = S.rgba()[..., 3]
    m = smooth(0.3, 0.6, blurf(raw, hero * 0.012))
    hgt = blurf(m, hero * 0.02)
    gy, gx = np.gradient(hgt)
    lit = np.clip(-(gx + gy) * hero * 0.25, -1, 1)
    slime = ramp(hgt, [(0, (0.06, 0.3, 0.0)), (0.6, (0.3, 0.85, 0.05)), (1, (0.6, 1.0, 0.2))])
    slime = slime * (0.75 + 0.35 * noise(W, H, 1905, 14.0))[..., None]
    slime = slime + smooth(0.25, 0.8, lit)[..., None] * np.array([0.6, 0.7, 0.4]) - smooth(0.0, -0.8, lit)[..., None] * 0.25
    halo = np.clip(blurf(m, hero * 0.04) * 1.6, 0, 1) * (1 - m)
    c = c * (1 - 0.65 * halo)[..., None]
    c = c + glow_of(_rgba_of(solid(W, H, (0.3, 1.0, 0.1)), m), hero * 0.07, 0.8)
    c = mix(c, slime, m)
    B = Layer(W, H)
    tries = 0
    nb = 0
    while nb < 70 and tries < 4000:
        tries += 1
        px, py = rng.random() * W, rng.random() * H
        if m[int(py), int(px)] < 0.9:
            continue
        r = hero * (0.008 + 0.02 * rng.random())
        B.circle(px, py, r, (200, 255, 150, 60), (210, 255, 160, 220), max(1.2, r * 0.18))
        B.circle(px - r * 0.35, py - r * 0.35, r * 0.25, (255, 255, 230, 240))
        nb += 1
    c = over(c, B.rgba())
    return np.clip(c, 0, 1), 0.4, 0.2


def d_nitro(W, H, lay):
    """hot-rod orange and black, engine cutaway, chrome pipes, turbo, gauge"""
    x, y = grid(W, H)
    hero = _hero(lay)
    span = lay.x1 - lay.x0
    v = _v(lay, x, y)
    fpos = (x - lay.x0) / span
    split = 0.62 + 0.18 * (fpos - 0.5)
    orange = ramp(np.clip(v / split, 0, 1), [(0, (1.0, 0.62, 0.12)), (0.5, (1.0, 0.45, 0.04)), (1, (0.75, 0.22, 0.01))])
    orange = orange + (np.exp(-((v - 0.12) / 0.05) ** 2) * 0.45)[..., None] * np.array([1.0, 0.9, 0.7])
    orange = orange * (1 - 0.25 * np.exp(-((v - 0.36) / 0.05) ** 2))[..., None]
    # diamond plate below
    P = max(hero * 0.12, 10)
    u, w = (x + y) / P, (x - y) / P
    iu, iw = np.floor(u), np.floor(w)
    fu, fw = u - iu, w - iw
    alt = ((iu + iw) % 2) == 0
    e1 = ((fu - 0.5) / 0.38) ** 2 + ((fw - 0.5) / 0.11) ** 2
    e2 = ((fu - 0.5) / 0.11) ** 2 + ((fw - 0.5) / 0.38) ** 2
    bump = np.where(alt, e1, e2) < 1
    dark = ramp(noise(W, H, 2001, 6.0), [(0, (0.05, 0.05, 0.055)), (1, (0.11, 0.11, 0.12))])
    dark = np.where(bump[..., None], dark * 1.9 + 0.04, dark)
    black = solid(W, H, (0.03, 0.03, 0.035)) + (np.exp(-((v - split - 0.1) / 0.04) ** 2) * 0.18)[..., None]
    c = np.where((v < split)[..., None], orange, np.where((v < 1.0)[..., None], black, dark))
    L = Layer(W, H)
    chrome_d, chrome_l = (55, 55, 62), (250, 250, 255)
    sp =[_P(lay, f, 0.62 + 0.18 * (f - 0.5)) for f in np.linspace(-0.02, 1.02, 60)]
    _tube(L, sp, max(4, hero * 0.03), chrome_d, chrome_l)
    # chrome pipes along the barrel
    for vv in (0.3, 0.75):
        pts = _bpoly(lay, [(0.44, vv), (0.3, vv), (0.2, vv - 0.06), (-0.03, vv - 0.06)], 10, closed=False)
        _tube(L, pts, max(5, hero * 0.07), chrome_d, chrome_l)
    c = over(c, L.rgba())
    # engine cutaway
    fa, fb, va, vb = 0.44, 0.67, 0.1, 0.9
    win = _bpoly(lay, [(fa, va), (fb, va), (fb, vb), (fa, vb)], 10)
    Wm = Layer(W, H)
    Wm.poly(win, (255, 255, 255, 255))
    wm = Wm.rgba()[..., 3]
    inner = ramp(noise(W, H, 2002, 8.0), [(0, (0.06, 0.06, 0.07)), (1, (0.14, 0.14, 0.16))])
    M = Layer(W, H)
    Xa, Xb = _X(lay, fa), _X(lay, fb)
    e = min(float(_env(lay, (Xa + Xb) / 2)), hero)
    ty = _s(lay.top, (Xa + Xb) / 2)
    gcx, gcy, gr = Xb - (Xb - Xa) * 0.15, ty + e * 0.72, e * 0.32
    teeth = []
    for k in range(48):
        a = k / 48 * 2 * math.pi
        rr = gr * (1.0 if k % 2 else 0.86)
        teeth.append((gcx + math.cos(a) * rr, gcy + math.sin(a) * rr))
    M.poly(teeth, (70, 70, 78, 255), (20, 20, 22, 255), 2)
    M.circle(gcx, gcy, gr * 0.35, (35, 35, 40, 255))
    npist = 4
    for k in range(npist):
        px = Xa + (Xb - Xa) * (0.15 + 0.7 * k / (npist - 1))
        top = ty + e * (0.32 + 0.1 * (k % 2))
        pw = (Xb - Xa) * 0.11
        _tube(M, [(px, ty + e * 0.92), (px, top)], pw, (40, 40, 45), (235, 235, 240), steps=5)
        M.poly([(px - pw * 0.6, top - e * 0.05), (px + pw * 0.6, top - e * 0.05), (px + pw * 0.6, top + e * 0.06), (px - pw * 0.6, top + e * 0.06)],
               (210, 210, 218, 255), (20, 20, 22, 255), 2)
        for rk in range(3):
            M.line([(px - pw * 0.6, top + e * (0.08 + rk * 0.04)), (px + pw * 0.6, top + e * (0.08 + rk * 0.04))], (30, 30, 34, 255), max(1.5, e * 0.01))
        M.line([(px, ty + e * 0.2), (px, top - e * 0.05)], (60, 60, 66, 255), pw * 0.4)
    _tube(M, [(Xa - 10, ty + e * 0.2), (Xb + 10, ty + e * 0.2)], e * 0.09, (60, 30, 5), (255, 200, 120))
    mr = M.rgba()
    mr[..., 3] *= wm
    c = mix(c, inner, wm)
    c = over(c, mr)
    F = Layer(W, H)
    F.line(win + win[:1], (15, 15, 18, 255), max(5, hero * 0.05))
    F.line(win + win[:1], (235, 235, 240, 255), max(3, hero * 0.03))
    F.line(win + win[:1], (120, 120, 128, 255), max(1.5, hero * 0.01))
    for (f, vv) in ((fa, va), (fb, va), (fa, vb), (fb, vb)):
        px, py = _P(lay, f, vv)
        F.circle(px, py, hero * 0.03, (220, 220, 228, 255), (20, 20, 22, 255), 1.5)
    # turbo at the back
    X = _X(lay, 0.82)
    e2 = min(float(_env(lay, X)), hero)
    tcx, tcy, R = X, _s(lay.top, X) + e2 * 0.45, e2 * 0.36
    _tube(F, [(tcx - R * 0.6, tcy + R * 0.5), (Xb + 5, tcy + R * 0.5)], R * 0.45, chrome_d, chrome_l)
    for k in range(7):
        t = k / 6
        col = tuple(int(chrome_d[i] + (chrome_l[i] - chrome_d[i]) * t) for i in range(3)) + (255,)
        F.circle(tcx - R * 0.06 * t, tcy - R * 0.06 * t, R * (1.12 - 0.5 * t), col)
    spiral = [(tcx + math.cos(a) * R * (0.45 + 0.55 * a / (2 * math.pi)), tcy + math.sin(a) * R * (0.45 + 0.55 * a / (2 * math.pi)))
              for a in np.linspace(0, 2 * math.pi, 60)]
    F.line(spiral, (25, 25, 30, 255), max(2, R * 0.05))
    F.circle(tcx, tcy, R * 0.48, (22, 22, 26, 255), (210, 210, 220, 255), max(2, R * 0.06))
    for k in range(11):
        a = k / 11 * 2 * math.pi
        F.line(bezier([(tcx + math.cos(a) * R * 0.1, tcy + math.sin(a) * R * 0.1), (tcx + math.cos(a + 0.35) * R * 0.3, tcy + math.sin(a + 0.35) * R * 0.3),
                       (tcx + math.cos(a + 0.8) * R * 0.44, tcy + math.sin(a + 0.8) * R * 0.44)], 6), (190, 190, 200, 255), max(1.5, R * 0.04))
    F.circle(tcx, tcy, R * 0.1, (240, 240, 245, 255), (20, 20, 22, 255), 1.5)
    for k in range(8):
        a = k / 8 * 2 * math.pi
        F.circle(tcx + math.cos(a) * R * 1.0, tcy + math.sin(a) * R * 1.0, R * 0.05, (40, 40, 45, 255))
    # boost gauge on the magazine (or the grip)
    bx = _below(lay)
    if bx:
        xa, xb, ya, yb = max(bx, key=lambda b: (b[3] - b[2]) * (b[1] - b[0]))
        gR = min((xb - xa) * 0.42, (yb - ya) * 0.3)
        gx_, gy_ = (xa + xb) / 2, ya + gR * 1.4
    else:
        gR = hero * 0.3
        gx_, gy_ = _P(lay, 0.95, 0.5)
    for k in range(6):
        t = k / 5
        col = tuple(int(chrome_d[i] + (chrome_l[i] - chrome_d[i]) * t) for i in range(3)) + (255,)
        F.circle(gx_, gy_ - gR * 0.03 * t, gR * (1.15 - 0.1 * t), col)
    F.circle(gx_, gy_, gR, (12, 12, 14, 255))
    for k in range(11):
        a = math.radians(135 + k * 27)
        col = (255, 40, 30, 255) if k >= 8 else (240, 240, 240, 255)
        F.line([(gx_ + math.cos(a) * gR * 0.72, gy_ + math.sin(a) * gR * 0.72), (gx_ + math.cos(a) * gR * 0.92, gy_ + math.sin(a) * gR * 0.92)], col,
               max(1.5, gR * 0.06))
    F.line([(gx_ + math.cos(math.radians(135 + t)) * gR * 0.92, gy_ + math.sin(math.radians(135 + t)) * gR * 0.92) for t in np.linspace(216, 270, 12)],
           (255, 40, 30, 255), max(2, gR * 0.08))
    a = math.radians(135 + 236)
    F.line([(gx_ - math.cos(a) * gR * 0.15, gy_ - math.sin(a) * gR * 0.15), (gx_ + math.cos(a) * gR * 0.85, gy_ + math.sin(a) * gR * 0.85)],
           (255, 110, 20, 255), max(2, gR * 0.06))
    F.circle(gx_, gy_, gR * 0.1, (200, 200, 205, 255))
    F.text((gx_, gy_ + gR * 0.45), "BOOST", ("bahnschrift.ttf", gR * 0.2), (240, 240, 240, 255))
    c = over(c, F.rgba())
    return np.clip(c, 0, 1), 0.4, 0.2


def d_quantum(W, H, lay):
    """bubble-chamber particle tracks and spirals, collision burst"""
    x, y = grid(W, H)
    hero = _hero(lay)
    rng = np.random.default_rng(2101)
    c = ramp(y / H, [(0, (0.012, 0.03, 0.1)), (1, (0.004, 0.012, 0.05))])
    c = c * (0.8 + 0.35 * noise(W, H, 2102, 2.5))[..., None]
    P = hero * 0.2
    gl = (np.abs((x % P) - P / 2) > P / 2 - 1.0) | (np.abs((y % P) - P / 2) > P / 2 - 1.0)
    c = c + gl[..., None] * np.array([0.02, 0.06, 0.1])
    F = Layer(W, H)
    for gx_ in np.arange(P * 2, W, P * 4):
        for gy_ in np.arange(P * 2, H, P * 4):
            F.line([(gx_ - P * 0.25, gy_), (gx_ + P * 0.25, gy_)], (120, 200, 255, 110), 1.5)
            F.line([(gx_, gy_ - P * 0.25), (gx_, gy_ + P * 0.25)], (120, 200, 255, 110), 1.5)
    c = over(c, F.rgba())
    T = Layer(W, H)
    Tc = Layer(W, H)

    def track(px, py, ang, k0, loss, length, w, col):
        k = k0
        sgn = 1 if rng.random() < 0.5 else -1
        pts = [(px, py)]
        ds = max(2.0, hero * 0.012)
        dist = 0.0
        while dist < length and abs(k) < 1 / max(2.0, hero * 0.012):
            ang += sgn * k * ds
            px += math.cos(ang) * ds
            py += math.sin(ang) * ds
            pts.append((px, py))
            k *= 1 + loss * ds
            dist += ds
            if px < -50 or px > W + 50 or py < -50 or py > H + 50:
                break
        if len(pts) > 2:
            T.line(pts, col, w)
            Tc.line(pts, (255, 255, 255, 255), max(1.0, w * 0.4))

    thin = max(1.8, hero * 0.009)
    heavy = max(3.0, hero * 0.018)
    cyan, wht, vio = (90, 220, 255, 255), (230, 245, 255, 255), (190, 150, 255, 255)
    vx = [_P(lay, 0.72, 0.5), _P(lay, 0.33, 0.5)]
    bxs = _below(lay)
    if bxs:
        xa, xb, ya, yb = bxs[0]
        vx.append(((xa + xb) / 2, ya + (yb - ya) * 0.45))
    for n, (px, py) in enumerate(vx):
        scale = 1.0 if n == 0 else 0.6
        for _ in range(int(7 * scale)):
            a = math.pi + (rng.random() - 0.5) * 0.25 if rng.random() < 0.6 else (rng.random() - 0.5) * 0.3
            track(px, py, a, 1 / (hero * (8 + 20 * rng.random())), 0.0, W * 0.8, heavy, wht)
        for _ in range(int(14 * scale)):
            track(px, py, rng.random() * 2 * math.pi, 1 / (hero * (0.6 + 2.0 * rng.random())), 0.002 + 0.004 * rng.random(), hero * 6, thin,
                  cyan if rng.random() < 0.7 else vio)
        for _ in range(int(9 * scale)):
            track(px, py, rng.random() * 2 * math.pi, 1 / (hero * (0.3 + 0.5 * rng.random())), 0.01 + 0.012 * rng.random(), hero * 5, thin, wht)
    for _ in range(10):
        X = _X(lay, rng.random())
        e = float(_env(lay, X))
        track(X, _s(lay.top, X) + e * rng.random(), rng.random() * 2 * math.pi, 1 / (hero * (0.25 + 0.3 * rng.random())), 0.015, hero * 3, thin, cyan)
    for _ in range(12):
        px, py = rng.random() * W, rng.random() * H
        a = rng.random() * 2 * math.pi
        ln = hero * (0.1 + 0.25 * rng.random())
        T.line([(px, py), (px + math.cos(a) * ln, py + math.sin(a) * ln)], cyan, thin)
    g = T.rgba()
    c = c + glow_of(g, hero * 0.035, 1.2) + glow_of(g, hero * 0.01, 0.6)
    c = over(c, g)
    c = over(c, Tc.rgba(), 0.8)
    R = Layer(W, H)
    for n, (px, py) in enumerate(vx):
        s = 1.0 if n == 0 else 0.55
        d = np.hypot(x - px, y - py)
        c = c + (np.exp(-(d / (hero * 0.08 * s)) ** 2) * 1.2)[..., None] * np.array([1.0, 1.0, 1.0])
        c = c + (np.exp(-(d / (hero * 0.45 * s)) ** 2) * 0.35)[..., None] * np.array([0.3, 0.7, 1.0])
        for rr in (0.35, 0.6):
            R.circle(px, py, hero * rr * s, None, (140, 220, 255, 90), max(1.5, hero * 0.006))
        for k in range(16):
            a = k / 16 * 2 * math.pi + 0.1
            R.line([(px + math.cos(a) * hero * 0.05 * s, py + math.sin(a) * hero * 0.05 * s),
                    (px + math.cos(a) * hero * (0.12 + 0.08 * (k % 2)) * s, py + math.sin(a) * hero * (0.12 + 0.08 * (k % 2)) * s)],
                   (255, 255, 255, 200), max(1.5, hero * 0.008))
    c = add(c, R.rgba(), 1.0)
    return np.clip(c, 0, 1), 0.3, 0.08


def _cartridge(length, ss=2):
    """RGBA sprite (uint8) of a brass rifle cartridge lying along +x (base left, bullet right), cylinder-shaded."""
    Lp = max(8, int(length * ss))
    Wp = max(4, int(length * 0.27 * ss))
    s = (np.arange(Lp) + 0.5) / Lp
    w = (np.arange(Wp) + 0.5) / Wp * 2 - 1
    S, Wv = np.meshgrid(s, w)
    rad = np.interp(S, [0, 0.045, 0.046, 0.085, 0.086, 0.62, 0.7, 0.78, 0.8, 0.9, 1.0],
                    [0.98, 0.98, 0.8, 0.8, 0.96, 0.92, 0.62, 0.62, 0.6, 0.45, 0.0])
    tip = S > 0.78
    rad = np.where(tip, 0.6 * np.sqrt(np.clip(1 - ((S - 0.78) / 0.22) ** 2, 0, 1)), rad)
    inside = np.abs(Wv) <= rad
    nrm = np.clip(Wv / np.maximum(rad, 1e-3), -1, 1)
    lam = np.sqrt(1 - nrm ** 2)
    brass = np.array([0.85, 0.62, 0.22])
    copper = np.array([0.78, 0.38, 0.18])
    base = np.where(tip[..., None], copper, brass)
    shade = (0.16 + 0.85 * lam ** 1.4)[..., None]
    hl = np.exp(-((nrm + 0.42) / 0.11) ** 2)[..., None]
    rim = np.clip((np.abs(nrm) - 0.8) / 0.2, 0, 1)[..., None]
    col = (base * shade + hl * np.array([1.0, 0.92, 0.75]) * 0.85) * (1 - 0.6 * rim)
    groove = (S > 0.046) & (S < 0.085)
    col = np.where(groove[..., None], col * 0.45, col)
    col = np.where((S < 0.02)[..., None], col * 0.6, col)
    edge = np.clip((rad - np.abs(Wv)) * Wp * 0.5, 0, 1)
    a = inside * edge
    rgba = np.dstack([np.clip(col, 0, 1), a])
    im = Image.fromarray((rgba * 255).astype(np.uint8), "RGBA")
    return im


def d_bullet_rain(W, H, lay):
    """falling brass cartridges with motion streaks on amber to black"""
    x, y = grid(W, H)
    hero = _hero(lay)
    rng = np.random.default_rng(2201)
    v = _v(lay, x, y)
    t = np.clip(v / 2.6, 0, 1)
    c = ramp(t, [(0, (0.16, 0.065, 0.012)), (0.25, (0.07, 0.03, 0.008)), (0.5, (0.02, 0.009, 0.003)), (1, (0.006, 0.003, 0.001))])
    for f, s in ((0.72, 1.4), (0.3, 0.9)):
        X = _X(lay, f)
        d = np.hypot((x - X) / (hero * s * 1.6), (y - _s(lay.top, X) - _env(lay, X) * 0.5) / (hero * s))
        c = c + (np.exp(-d * d) * 0.13)[..., None] * np.array([1.0, 0.5, 0.1])
    c = c * (0.78 + 0.35 * noise(W, H, 2202, 4.0))[..., None]
    shafts = smooth(0.6, 0.95, noise(W, H, 2203, 8.0, 3, sx=1.0, sy=0.06))
    c = c + shafts[..., None] * np.array([0.08, 0.045, 0.01]) * (1 - t)[..., None]
    mvx, mvy = -0.28, 1.0
    nm = math.hypot(mvx, mvy)
    mvx, mvy = mvx / nm, mvy / nm
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("L", (W, H), 0)
    St = Layer(W, H)

    def drop(px, py, ln, bright, blur):
        ang = rng.random() * 360
        sp = _cartridge(ln)
        sp = sp.rotate(ang, resample=Image.BICUBIC, expand=True)
        sp = sp.resize((max(2, sp.width // 2), max(2, sp.height // 2)), Image.LANCZOS)
        sa = sp.getchannel("A").point(lambda q: int(q * 0.75 * bright))
        so = (int(px - sp.width / 2 + hero * 0.035), int(py - sp.height / 2 + hero * 0.055))
        shadow.paste(Image.new("L", sa.size, 255), so, sa)
        if bright < 1:
            arr = np.asarray(sp, np.float32)
            arr[..., :3] *= bright
            sp = Image.fromarray(arr.astype(np.uint8), "RGBA")
        if blur:
            sp = sp.filter(ImageFilter.GaussianBlur(blur))
        else:
            # a dark outline, so the cartridges stay apart and do not melt into one gold mass on small guns
            ol = sp.getchannel("A").filter(ImageFilter.MaxFilter(5))
            canvas.alpha_composite(Image.merge("RGBA", (ol.point(lambda q: 18), ol.point(lambda q: 9), ol.point(lambda q: 2), ol)),
                                   (int(px - sp.width / 2), int(py - sp.height / 2)))
        canvas.alpha_composite(sp, (int(px - sp.width / 2), int(py - sp.height / 2)))
        tl = ln * (1.4 + 1.6 * rng.random())
        wd = ln * 0.14
        for k in range(8):
            f0, f1 = k / 8, (k + 1) / 8
            a = int(85 * bright * (1 - f0) ** 1.5)
            p0 = (px - mvx * tl * f0, py - mvy * tl * f0)
            p1 = (px - mvx * tl * f1, py - mvy * tl * f1)
            St.line([p0, p1], (255, 210, 140, a), wd * (1 - 0.6 * f0))

    def onmask(px, py):
        return 0 <= px < W and 0 <= py < H and lay.mask[int(py), int(px)]

    far = []
    tries = 0
    while len(far) < 11 and tries < 5000:
        tries += 1
        px, py = rng.random() * W, rng.random() * H
        if onmask(px, py):
            far.append((px, py))
    for px, py in far:
        drop(px, py, hero * (0.28 + 0.15 * rng.random()), 0.42, hero * 0.02)
    mids = []
    tries = 0
    while len(mids) < 7 and tries < 5000:
        tries += 1
        px, py = rng.random() * W, rng.random() * H
        if onmask(px, py) and all(math.hypot(px - qx, py - qy) > hero * 0.75 for qx, qy in mids):
            mids.append((px, py))
    for px, py in mids:
        drop(px, py, hero * (0.55 + 0.2 * rng.random()), 0.85, 0)
    for f, vv, s in ((0.5, 0.45, 1.05), (0.68, 0.55, 1.25), (0.86, 0.45, 1.3), (0.97, 0.6, 0.9), (0.2, 0.5, 0.75)):
        X = _X(lay, f)
        e = min(float(_env(lay, X)), hero)
        drop(X, _s(lay.top, X) + e * vv, hero * s, 1.0, 0)
    for xa, xb, ya, yb in _below(lay):
        drop((xa + xb) / 2, ya + (yb - ya) * 0.55, min(hero * 0.9, (yb - ya) * 0.5), 0.95, 0)
    sha = np.asarray(shadow.filter(ImageFilter.GaussianBlur(hero * 0.025)), np.float32) / 255.0
    c = c * (1 - 0.8 * sha)[..., None]
    st = St.rgba(blur=hero * 0.025)
    c = add(c, st, 0.8)
    cart = np.asarray(canvas, np.float32) / 255.0
    c = c + glow_of(cart, hero * 0.06, 0.25) * np.array([1.0, 0.55, 0.15])
    c = over(c, cart)
    c = add(c, sparkle(W, H, 40, 2204, hero * 0.015, (1.0, 0.9, 0.6)), 0.8)
    return np.clip(c, 0, 1), 0.35, 0.12


def _splat(L, rng, cx, cy, R, col, drips=True):
    """A thrown splash of paint: a lumpy blob stretched along the throw, fingers and droplets flung the same way
    (thinning out with distance), and a few drips running down. Not the board's round stamp with a ring of dots."""
    throw = rng.random() * 2 * math.pi
    n = 48
    angs = np.linspace(0, 2 * math.pi, n, endpoint=False)
    ph = rng.random(3) * 6.283
    rr = R * (0.82 + 0.12 * np.sin(2 * angs + ph[0]) + 0.08 * np.sin(5 * angs + ph[1]) + 0.1 * rng.random(n))
    along = np.cos(angs - throw)
    rr *= 1 + 0.32 * np.clip(along, 0, 1) ** 2
    pts = [(cx + math.cos(a) * r, cy + math.sin(a) * r) for a, r in zip(angs, rr)]
    L.poly(bezier(pts + pts[:3], 6), col)
    # fingers: tapering spikes thrown out of the rim, mostly forward
    for _ in range(3 + int(rng.random() * 3)):
        a = throw + rng.normal() * 0.55
        r0 = R * 0.7
        ln = R * (0.45 + 0.75 * rng.random())
        w = R * (0.12 + 0.1 * rng.random())
        bx, by = cx + math.cos(a) * r0, cy + math.sin(a) * r0
        nx, ny = -math.sin(a), math.cos(a)
        tx, ty = bx + math.cos(a) * ln, by + math.sin(a) * ln
        L.poly([(bx + nx * w, by + ny * w), (tx, ty), (bx - nx * w, by - ny * w)], col)
        L.circle(tx + math.cos(a) * w * 0.9, ty + math.sin(a) * w * 0.9, w * 0.55, col)
    # droplets flung forward in a cone, smaller the further they flew
    for _ in range(9):
        a = throw + rng.normal() * 0.4
        d = R * (1.25 + 1.5 * rng.random() ** 0.8)
        r = R * 0.13 * (1.3 - (d / R - 1.25) / 1.6) * (0.5 + 0.6 * rng.random())
        L.ellipse((cx + math.cos(a) * d - r * 1.25, cy + math.sin(a) * d - r, cx + math.cos(a) * d + r * 1.25, cy + math.sin(a) * d + r), col)
    if drips:
        for _ in range(2 + int(rng.random() * 3)):
            a = math.pi / 2 + (rng.random() - 0.5) * 1.4
            sx, sy = cx + math.cos(a) * R * 0.7, cy + math.sin(a) * R * 0.7
            ln = R * (0.8 + 2.6 * rng.random() ** 1.5)
            w = R * (0.09 + 0.1 * rng.random())
            L.poly([(sx - w, sy), (sx + w, sy), (sx + w * 0.8, sy + ln), (sx - w * 0.8, sy + ln)], col)
            L.circle(sx, sy + ln, w * 1.05, col)


def d_neon_riot(W, H, lay):
    """thick neon paint splashes and drips on black"""
    x, y = grid(W, H)
    hero = _hero(lay)
    rng = np.random.default_rng(2301)
    c = ramp(noise(W, H, 2302, 4.0), [(0, (0.01, 0.01, 0.015)), (1, (0.05, 0.05, 0.06))])
    v = _v(lay, x, y)
    c = c + (np.exp(-((v - 0.12) / 0.06) ** 2) * 0.08)[..., None]
    pink, green, yellow = (255, 30, 150, 255), (50, 255, 80, 255), (255, 235, 25, 255)
    # fewer, bolder splashes than the board's eight (busy on the small Thompson)
    plan = [(0.13, 0.5, 0.8, green), (0.45, 0.45, 0.88, pink), (0.8, 0.5, 0.92, yellow), (0.63, 0.25, 0.42, green), (0.98, 0.35, 0.45, pink)]
    layers = {pink: Layer(W, H), green: Layer(W, H), yellow: Layer(W, H)}
    for f, vv, s, col in plan:
        X = _X(lay, f)
        e = min(float(_env(lay, X)), hero)
        R = e * s * 0.62 * (0.85 + 0.3 * rng.random())
        _splat(layers[col], rng, X, _s(lay.top, X) + e * vv, R, col)
    cols = [pink, green, yellow]
    for k, (xa, xb, ya, yb) in enumerate(_below(lay)):
        for j in range(2):
            col = cols[(k + j + 1) % 3]
            if j == 0:
                _splat(layers[col], rng, (xa + xb) / 2, ya + (yb - ya) * 0.55, min(hero * 0.34, (xb - xa) * 0.42), col)
    Ls = layers[green]
    sw = _bpoly(lay, [(0.52, 0.95), (0.6, 0.55), (0.7, 0.25), (0.8, 0.1)], 8, closed=False)
    Ls.line(sw, green, hero * 0.09)
    for col in (pink, green, yellow):
        g = layers[col].rgba()
        sh = g[..., 3]
        c = c * (1 - 0.5 * np.roll(np.roll(blurf(sh, hero * 0.02), int(hero * 0.02), 0), int(hero * 0.01), 1))[..., None]
        c = c + glow_of(g, hero * 0.05, 0.55)
        tint = g[..., :3] * (0.85 + 0.25 * noise(W, H, 2303 + col[0], 5.0))[..., None]
        c = mix(c, tint, sh)
        edge = np.clip(sh - blurf(sh, hero * 0.012), 0, 1)
        c = c + edge[..., None] * 0.3
        o = max(1, int(hero * 0.012))
        gloss = np.clip(sh - np.roll(np.roll(blurf(sh, hero * 0.015), o, 0), o, 1), 0, 1)
        c = c + gloss[..., None] * 0.7 + (np.exp(-((v - 0.15) / 0.05) ** 2) * 0.22 * sh)[..., None]
        c = c * (1 - 0.35 * np.clip(sh - np.roll(np.roll(blurf(sh, hero * 0.015), -o, 0), -o, 1), 0, 1))[..., None]
    hl = smooth(0.75, 0.95, noise(W, H, 2310, 12.0, 3)) * 0.18
    c = c + hl[..., None]
    return np.clip(c, 0, 1), 0.3, 0.08


# ---------------------------------------------------------------------------------------------- set C helpers
# (geo(lay): the band geometry shared by the finishes, cached on the layout)


def fblur_c(a, s, axes=(0, 1)):
    """Float gaussian-ish blur (three box passes)."""
    a = np.asarray(a, np.float32)
    b = max(1, int(round(s * 0.95)))
    for _ in range(3):
        for ax in axes:
            a = _box(a, b, ax)
    return a


def fbm(X, Y, seed, octaves=4):
    return gs.fbm2(X, Y, seed, octaves, 1.0)


def hashf(ix, iy, seed):
    return (np.sin(ix * 12.9898 + iy * 78.233 + seed * 37.719) * 43758.5453) % 1.0


def cells(x, y, s, seed, jit=0.8):
    """Jittered-grid F1 distance (px) and the winning cell's random value."""
    ix0, iy0 = np.floor(x / s), np.floor(y / s)
    f1 = np.full(x.shape, 1e9, np.float32)
    rid = np.zeros(x.shape, np.float32)
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            ix, iy = ix0 + di, iy0 + dj
            cx = (ix + 0.5 + (hashf(ix, iy, seed) - 0.5) * jit) * s
            cy = (iy + 0.5 + (hashf(ix, iy, seed + 1) - 0.5) * jit) * s
            d = np.hypot(x - cx, y - cy)
            closer = d < f1
            f1 = np.where(closer, d, f1)
            rid = np.where(closer, hashf(ix, iy, seed + 2), rid)
    return f1, rid


def geo(lay):
    """Band geometry shared by the designs (cached on the layout): RH the receiver height, env the smooth band
    envelope height, rf/rb where the tall receiver starts/ends, 2D fields x, y, f (0 muzzle .. 1 butt) and
    v (0 top of the gun, 1 bottom of the receiver envelope, >1 magazine and grip)."""
    g = getattr(lay, "_c_geo", None)
    if g is not None:
        return g
    W, H = lay.W, lay.H
    xs = np.arange(W, dtype=float)
    h = lay.height(xs)
    i0, i1 = int(lay.x0), int(lay.x1)
    RH = float(np.percentile(h[i0:i1 + 1], 80))
    k = max(4, W // 10)
    mx = np.lib.stride_tricks.sliding_window_view(np.pad(h, k, mode="edge"), 2 * k + 1).max(1)
    kk = max(2, W // 20)
    env = np.convolve(np.pad(mx, kk, mode="edge"), np.ones(kk) / kk, "same")[kk:-kk]
    env = np.minimum(env, RH * 1.05)
    top = lay.top(xs)
    tall = np.nonzero(h[i0:i1 + 1] > 0.6 * RH)[0] + i0
    runs, s0 = [], tall[0]
    for a, b in zip(tall[:-1], tall[1:]):
        if b - a > RH * 0.15:
            runs.append((s0, a))
            s0 = b
    runs.append((s0, tall[-1]))
    long_ = [r for r in runs if r[1] - r[0] >= 0.6 * RH] or [max(runs, key=lambda r: r[1] - r[0])]
    rf = float(long_[0][0])
    rb = float(max(r[1] for r in runs if r[1] - r[0] >= 0.3 * RH) if any(r[1] - r[0] >= 0.3 * RH for r in runs) else long_[-1][1])
    x, y = grid(W, H)
    span = lay.x1 - lay.x0
    g = SimpleNamespace(W=W, H=H, RH=RH, env=env, top=top, xs=xs, x0=lay.x0, x1=lay.x1, span=span,
                        rf=rf, rb=rb, x=x, y=y)
    g.T = np.broadcast_to(top[None, :], (H, W)).astype(np.float32)
    g.E = np.broadcast_to(env[None, :], (H, W)).astype(np.float32)
    g.v = (y - g.T) / g.E
    g.f = np.clip((x - lay.x0) / span, 0, 1)
    g.inb = ((g.v >= 0) & (g.v <= 1)).astype(np.float32)
    lay._c_geo = g
    return g


def T1(g, X):
    return float(np.interp(X, g.xs, g.top))


def E1(g, X):
    return float(np.interp(X, g.xs, g.env))


def PX(g, X, v):
    return (float(X), T1(g, X) + v * E1(g, X))


def FX(g, f):
    return g.x0 + g.span * f


def band_pts(g, Xs, v):
    Xs = np.asarray(Xs, float)
    return list(zip(Xs, np.interp(Xs, g.xs, g.top) + v * np.interp(Xs, g.xs, g.env)))


def best_spot(lay, g, wpx, v0=0.15, v1=0.85, bias=0.25, lo=0.0, hi=1.0):
    """Canvas x of the centre of the best-covered box wpx wide (between band v0..v1), preferring the rear."""
    sel = (g.v >= v0) & (g.v <= v1)
    cov = (lay.mask & sel).sum(0) / np.maximum(sel.sum(0), 1)
    w = max(3, int(wpx))
    box = np.convolve(np.pad(cov, w, mode="constant"), np.ones(w) / w, "same")[w:-w]
    xs = g.xs
    fx = (xs - g.x0) / g.span
    ok = (xs >= g.x0 + wpx / 2) & (xs <= g.x1 - wpx / 2) & (fx >= lo) & (fx <= hi)
    if not ok.any():
        ok = (xs >= g.x0) & (xs <= g.x1)
    score = np.where(ok, box + bias * fx, -1e9)
    return float(np.argmax(score))


def below_boxes(lay, g):
    """Boxes (xa, xb, ya, yb) of the parts hanging well below the receiver: magazine, grip, foregrip."""
    W, H = g.W, g.H
    lim = g.top + g.env
    m = lay.mask & (np.arange(H)[:, None] > lim[None, :])
    anyc = m.any(0)
    lo = np.where(anyc, H - 1 - np.argmax(m[::-1], 0), 0)
    tall = (lo - lim) > H * 0.15
    boxes = []
    x = 0
    while x < W:
        if tall[x]:
            x2 = x
            while x2 < W and tall[x2]:
                x2 += 1
            if x2 - x > W * 0.03:
                boxes.append((float(x), float(x2), float(lim[x:x2].mean()), float(lo[x:x2].max())))
            x = x2
        else:
            x += 1
    return boxes


def wob(pts, amp, seed, step=None):
    """A hand-drawn version of a polyline: resampled and wobbled sideways."""
    pts = np.asarray(pts, float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    n = max(3, int(s[-1] / max(step or amp * 2.0, 1.0)))
    ss = np.linspace(0, s[-1], n)
    px, py = np.interp(ss, s, pts[:, 0]), np.interp(ss, s, pts[:, 1])
    rng = np.random.default_rng(seed)
    o = rng.normal(size=(n + 10, 2))
    ker = np.ones(7) / 7
    o = np.stack([np.convolve(o[:, 0], ker, "same"), np.convolve(o[:, 1], ker, "same")], 1)[5:5 + n] * 2.2
    return list(zip(px + o[:, 0] * amp, py + o[:, 1] * amp))


def spiral_c(cx, cy, r0, turns, ang0, sense, n=60):
    pts = []
    for k in range(n):
        t = k / (n - 1)
        a = ang0 + sense * t * turns * 2 * math.pi
        r = r0 * (1 - 0.88 * t)
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def leaf_poly(px, py, ang, ln, wd, n=14, tip=0.0):
    """A pointed leaf from (px, py) along angle ang."""
    ca, sa = math.cos(ang), math.sin(ang)
    side = []
    for k in range(n + 1):
        t = k / n
        w = wd * math.sin(math.pi * t) ** 0.8 * (1 - 0.25 * t)
        side.append((t * ln, w / 2 + tip * t * t * ln * 0.15))
    pts = side + [(t, -w + tip * (t / ln) ** 2 * ln * 0.3) for t, w in side[::-1]]
    return [(px + ca * u - sa * w, py + sa * u + ca * w) for u, w in pts]


def scallop(cx, cy, r, n, depth=0.12, m=72):
    pts = []
    for k in range(m * max(1, n // 6)):
        a = k / (m * max(1, n // 6)) * 2 * math.pi
        rr = r * (1 - depth + depth * abs(math.cos(n * a / 2))) if n else r
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    return pts


def ellipse_pts(cx, cy, rx, ry, ang=0.0, n=48):
    ca, sa = math.cos(ang), math.sin(ang)
    out = []
    for k in range(n):
        a = k / n * 2 * math.pi
        px, py = math.cos(a) * rx, math.sin(a) * ry
        out.append((cx + ca * px - sa * py, cy + sa * px + ca * py))
    return out


def tube_c(L, pts, w, dark, light, outline=(8, 6, 6, 255), steps=6):
    """A shaded round cable along pts (concentric strokes lit from above)."""
    L.line(pts, outline, w * 1.18)
    for k in range(steps):
        t = k / (steps - 1)
        col = tuple(int(dark[i] + (light[i] - dark[i]) * t) for i in range(3)) + (255,)
        L.line([(px, py - w * 0.17 * t) for px, py in pts], col, max(1.0, w * (1 - 0.8 * t)))


def gloss(g, c, at=0.18, wd=0.07, s=0.18, broad=0.06):
    """Clear-coat highlight along the band."""
    hl = np.exp(-((g.v - at) / wd) ** 2) * s + np.exp(-((g.v - at - 0.05) / (wd * 3.5)) ** 2) * broad
    return c + (hl * g.inb)[..., None]


TI = [(0.0, (0.58, 0.59, 0.62)), (0.12, (0.80, 0.74, 0.52)), (0.24, (0.92, 0.70, 0.26)), (0.36, (0.74, 0.42, 0.15)),
      (0.47, (0.55, 0.20, 0.28)), (0.57, (0.42, 0.14, 0.55)), (0.67, (0.20, 0.18, 0.72)), (0.78, (0.16, 0.42, 0.88)),
      (0.89, (0.40, 0.70, 0.92)), (1.0, (0.80, 0.84, 0.86))]


def d_titanium_burn(W, H, lay):
    """heat-tinted titanium in gold, bronze, purple and blue, weld seams and perlage"""
    g = geo(lay)
    x, y, v, f, RH = g.x, g.y, g.v, g.f, g.RH
    warp = noise(W, H, 2502, 2.2, 4) - 0.5
    grain = noise(W, H, 2501, 90.0, 3, sx=0.015, sy=1.0)
    heat = 0.93 - 0.70 * f ** 0.85 + 0.20 * warp + 0.045 * np.sin(x / RH * 2.4 + warp * 7)
    welds = [g.rf + RH * 0.1, g.rf + (g.rb - g.rf) * 0.6]
    for wx in welds:
        d = (x - wx - warp * RH * 0.5) / (RH * 0.8)
        heat = np.maximum(heat, np.exp(-d * d) * (1.0 - 0.15 * smooth(0.0, 1.0, np.abs(v - 0.5))))
    depth = np.clip((y - g.T - g.E) / (H * 0.45), 0, 1)
    hb = 0.16 + 0.72 * depth ** 0.9 + 0.12 * warp
    wb = smooth(0.98, 1.12, v)
    heat = heat * (1 - wb) + hb * wb
    c = ramp(heat, TI)
    c = c * (0.80 + 0.34 * grain)[..., None]
    # fly-cutter arcs on the receiver flank
    xc, yc = (g.rf + g.rb) / 2, float(np.median(g.top)) + RH * 5
    arcs = 0.5 + 0.5 * np.cos(np.hypot(x - xc, y - yc) / (RH * 0.045) * 2 * np.pi)
    c = c * (1 + 0.06 * (arcs - 0.5) * g.inb)[..., None]
    # perlage (engine turning) on the magazine and grip
    s = RH * 0.2
    R = s * 0.72
    ix0, iy0 = np.floor(x / s), np.floor(y / s)
    pb = np.ones_like(x)
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            cx, cy = (ix0 + di + 0.5) * s, (iy0 + dj + 0.5) * s
            dx, dy = x - cx, y - cy
            r = np.hypot(dx, dy)
            inside = r < R
            th = np.arctan2(dy, dx)
            b = (0.80 + 0.30 * np.cos(2 * (th + 0.7)) * np.clip(r / R, 0, 1) ** 0.6) * (1 - 0.22 * smooth(0.86 * R, R, r))
            pb = np.where(inside, b, pb)
    c = c * (1 + (pb - 1) * wb)[..., None]
    # weld beads
    L = Layer(W, H)
    bead = np.zeros((H, W), np.float32)
    shade = np.ones((H, W), np.float32)
    for wx in welds:
        hw = RH * 0.06
        bx = wx + (noise(W, H, 2503, 6.0, 2) - 0.5) * RH * 0.03
        dx = (x - bx) / hw
        m = (np.abs(dx) < 1) & (v > -0.05) & (v < 1.03)
        rip = ((y - g.T) / (RH * 0.05) + np.abs(dx) * 0.9) % 1.0
        dome = np.sqrt(np.clip(1 - dx * dx, 0, 1))
        sh = (0.55 + 0.55 * rip) * (0.55 + 0.55 * dome)
        bead = np.maximum(bead, m.astype(np.float32))
        shade = np.where(m, sh, shade)
        toe = (np.abs(np.abs(dx) - 1) < 0.12) & (v > -0.05) & (v < 1.03)
        c = c * (1 - 0.45 * toe)[..., None]
    beadc = solid(W, H, (0.80, 0.79, 0.74)) * shade[..., None]
    c = mix(c, beadc, bead)
    # a few tool scratches
    rng = np.random.default_rng(2504)
    for _ in range(9):
        X = g.x0 + rng.random() * g.span
        vv = 0.1 + 0.8 * rng.random()
        ln = RH * (0.8 + 1.6 * rng.random())
        a = (rng.random() - 0.5) * 0.25
        p0 = PX(g, X, vv)
        L.line([p0, (p0[0] + math.cos(a) * ln, p0[1] + math.sin(a) * ln)], (255, 255, 250, 70), max(1.0, RH * 0.005))
    c = over(c, L.rgba())
    c = gloss(g, c, 0.2, 0.08, 0.14, 0.05)
    return np.clip(c, 0, 1), 0.35, 0.18


def d_black_laminate(W, H, lay):
    """black, charcoal and red plywood laminate, wood grain flowing along the gun, lacquer gloss"""
    g = geo(lay)
    x, y, v, RH = g.x, g.y, g.v, g.RH
    n1 = noise(W, H, 2601, 1.0, 3) - 0.5
    n2 = noise(W, H, 2602, 3.2, 3) - 0.5
    phi = y + n1 * RH * 1.3 + n2 * RH * 0.28 + 0.32 * RH * np.sin(x / (RH * 1.9))
    rng = np.random.default_rng(2603)
    eyes = [(g.rf + (g.rb - g.rf) * 0.3, 0.5, 0.42), (g.rf + (g.rb - g.rf) * 0.78, 0.45, 0.5), (g.x0 + g.span * 0.12, 0.5, 0.3)]
    for bx in below_boxes(lay, g):
        eyes.append(((bx[0] + bx[1]) / 2, None, min(0.45, (bx[1] - bx[0]) / RH * 0.45)))
    for k, (ex, ev, er) in enumerate(eyes):
        ey = T1(g, ex) + ev * E1(g, ex) if ev is not None else T1(g, ex) + E1(g, ex) + RH * 0.9
        r = RH * er
        sgn = 1 if k % 2 else -1
        phi = phi + sgn * r * 1.45 * np.exp(-((x - ex) ** 2 + (y - ey) ** 2) / (r * r))
    th = RH * (0.035 + 0.085 * rng.random(400) ** 1.4)
    bounds = np.concatenate([[-4 * RH], -4 * RH + np.cumsum(th)])
    idx = np.clip(np.searchsorted(bounds, phi) - 1, 0, len(th) - 1)
    pos = phi - bounds[idx]
    tk = th[idx]
    BLK, CHR, GRY, LGR, RED, DRD = (0.022, 0.022, 0.025), (0.10, 0.10, 0.11), (0.27, 0.27, 0.28), (0.50, 0.50, 0.49),\
        (0.70, 0.04, 0.05), (0.36, 0.02, 0.03)
    seq = []
    choices = [BLK, BLK, BLK, BLK, BLK, CHR, CHR, GRY, RED, RED, DRD, LGR]
    last = None
    for _ in range(len(th)):
        cc = choices[rng.integers(len(choices))]
        while cc is last:
            cc = choices[rng.integers(len(choices))]
        seq.append(cc)
        last = cc
    pal = np.array(seq, np.float32)
    c = pal[idx]
    gr = fbm(x / RH * 0.22, phi / RH * 16, 2604, 4)
    c = c * (0.74 + 0.48 * gr)[..., None] + (0.03 * gr)[..., None]
    pores = fbm(x / RH * 1.6, phi / RH * 70, 2605, 2)
    c = c * (1 - 0.35 * smooth(0.66, 0.74, pores))[..., None]
    dist = np.minimum(pos, tk - pos)
    c = c * (1 - 0.55 * smooth(1.8, 0.4, dist))[..., None]
    c = gloss(g, c, 0.17, 0.06, 0.16, 0.06)
    c = c + (0.05 * np.exp(-((v - 1.35) / 0.25) ** 2) * (v > 1))[..., None]
    return np.clip(c, 0, 1), 0.3, 0.08


def d_rust_coat(W, H, lay):
    """flaking dark paint over heavy rust: pitting, blisters, rust tears and bare steel scuffs"""
    g = geo(lay)
    x, y, v, RH = g.x, g.y, g.v, g.RH
    paint = ramp(noise(W, H, 2701, 4.0, 4), [(0, (0.06, 0.07, 0.065)), (1, (0.16, 0.17, 0.155))])
    rn = noise(W, H, 2702, 7.0, 5)
    fine = noise(W, H, 2703, 55.0, 3)
    rn = np.clip((rn - 0.5) * 1.7 + 0.5, 0, 1)
    rust = ramp(rn * 0.6 + fine * 0.4, [(0, (0.08, 0.03, 0.015)), (0.3, (0.22, 0.075, 0.025)), (0.5, (0.40, 0.15, 0.04)),
                                       (0.68, (0.60, 0.26, 0.06)), (0.85, (0.78, 0.42, 0.12)), (1, (0.88, 0.6, 0.28))])
    rust = rust * (0.75 + 0.5 * noise(W, H, 2711, 14.0, 3))[..., None]
    a = noise(W, H, 2704, 2.4, 5) - 0.03
    a = a + 0.10 * smooth(0.95, 1.6, v) + 0.12 * smooth(0.12, 0.0, np.abs(v - 0.0)) + 0.06 * smooth(0.15, 0.0, np.abs(v - 1.0))
    rm = smooth(0.505, 0.525, a)
    # rust tears running down from the patches
    streak = noise(W, H, 2705, 16.0, 3, sx=1.0, sy=0.05)
    tear = _box(shift(rm, 0, int(RH * 0.35)), RH * 0.35, 0) * smooth(0.45, 0.75, streak)
    c = mix(paint, rust * 0.8, np.clip(tear * 1.4, 0, 0.75))
    # paint edges: lifted and lit
    hgt = fblur_c(1 - rm, RH * 0.008)
    c = c * np.clip(relief(hgt * RH * 0.04, 1.0), 0.4, 1.8)[..., None]
    blis = smooth(0.62, 0.68, noise(W, H, 2706, 22.0, 2)) * smooth(0.38, 0.47, a) * (1 - rm)
    c = c * np.clip(relief(fblur_c(blis, RH * 0.01) * RH * 0.05, 1.0), 0.5, 1.6)[..., None]
    deep = smooth(0.62, 0.8, a)
    rust = rust * (1 - 0.35 * deep)[..., None]
    pits = smooth(0.70, 0.76, noise(W, H, 2707, 70.0, 2)) * smooth(0.55, 0.65, a)
    rust = rust * (1 - 0.75 * pits)[..., None]
    c = mix(c, rust, rm)
    # bare steel: worn top edges and scratches
    steel = ramp(noise(W, H, 2708, 60.0, 2, sx=0.03, sy=1.0), [(0, (0.42, 0.42, 0.44)), (1, (0.78, 0.78, 0.8))])
    worn = smooth(0.06, 0.0, v) * (v > -0.05) * smooth(0.45, 0.6, noise(W, H, 2709, 9.0, 3))
    c = mix(c, steel, worn * 0.9)
    L = Layer(W, H)
    rng = np.random.default_rng(2710)
    for _ in range(16):
        X = g.x0 + rng.random() * g.span
        p0 = PX(g, X, 0.1 + 0.85 * rng.random())
        ln = RH * (0.3 + 1.1 * rng.random())
        an = (rng.random() - 0.5) * 0.5
        pts = wob([p0, (p0[0] + math.cos(an) * ln, p0[1] + math.sin(an) * ln)], RH * 0.004, int(rng.integers(1e6)))
        L.line(pts, (205, 205, 210, 170), max(1.0, RH * 0.006))
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.4, 0.28


def d_trench_art(W, H, lay):
    """polished brass engraved like WWI trench art: poppies, scrolls, a 1944 cartouche, hammered magazine"""
    g = geo(lay)
    x, y, v, RH = g.x, g.y, g.v, g.RH
    refl = 0.5 + 0.38 * np.cos((v - 0.2) * np.pi * 1.7) + 0.12 * (noise(W, H, 2901, 2.0, 3) - 0.5)
    below = smooth(1.0, 1.1, v)
    refl = refl * (1 - below) + below * (0.45 + 0.3 * np.cos(x / RH * 1.3 + noise(W, H, 2902, 2.0, 2) * 3))
    BR = [(0, (0.28, 0.17, 0.04)), (0.45, (0.66, 0.46, 0.13)), (0.75, (0.90, 0.72, 0.33)), (0.92, (1.0, 0.90, 0.60)), (1, (1.0, 0.97, 0.85))]
    c = ramp(refl, BR)
    c = c * (0.93 + 0.1 * noise(W, H, 2903, 70.0, 2, sx=0.05, sy=1.0))[..., None]
    # hammered magazine and grip
    f1, rid = cells(x, y, RH * 0.13, 2904)
    dim = relief(-(f1 / (RH * 0.13)) ** 2 * RH * 0.05, 1.0)
    c = c * (1 + (np.clip(dim, 0.6, 1.5) - 1) * below)[..., None]
    lw = max(1.0, RH * 0.012)
    cutA = Layer(W, H)
    mot = Layer(W, H)
    cutB = Layer(W, H)
    Xs = np.linspace(g.x0, g.x1, 400)
    for vv in (0.06, 0.11, 0.89, 0.94):
        cutB.line(band_pts(g, Xs, vv), (255, 255, 255, 255), lw)
    for v0, v1 in ((0.06, 0.11), (0.89, 0.94)):
        zz = []
        for k, X in enumerate(np.arange(g.x0, g.x1, RH * 0.05)):
            zz.append(PX(g, X, v0 if k % 2 else v1))
        cutB.line(zz, (255, 255, 255, 255), lw * 0.8)
    # cartouche
    cw = RH * 0.95
    cx = best_spot(lay, g, cw * 1.1, 0.2, 0.8, 0.3, lo=0.3)
    cy = T1(g, cx) + 0.5 * E1(g, cx)
    ch = E1(g, cx) * 0.56
    oval = ellipse_pts(cx, cy, cw / 2, ch / 2, 0, 64)
    mot.poly(oval, (255, 255, 255, 255))
    cutA.line(oval + [oval[0]], (255, 255, 255, 255), lw * 2.4)
    inner = ellipse_pts(cx, cy, cw / 2 * 0.86, ch / 2 * 0.8, 0, 64)
    cutB.line(inner + [inner[0]], (255, 255, 255, 255), lw)
    cutB.text((cx, cy), "1944", ("ENGR.TTF", ch * 0.42), (255, 255, 255, 255))
    # the scroll stems: from the cartouche to the muzzle and to the butt
    rng = np.random.default_rng(2905)
    flowers = []

    def vine(Xa, Xb, sgn):
        n = 160
        XX = np.linspace(Xa, Xb, n)
        hloc = np.minimum(np.interp(XX, g.xs, lay.height(g.xs)), np.interp(XX, g.xs, g.env))
        hloc = np.convolve(np.pad(hloc, 8, mode="edge"), np.ones(8) / 8, "same")[8:-8]
        mid = np.interp(XX, g.xs, g.top) + hloc * 0.5
        amp = hloc * 0.16
        per = RH * 1.3
        yy = mid + amp * np.sin((XX - Xa) / per * 2 * np.pi * sgn)
        pts = list(zip(XX, yy))
        ws = np.maximum(hloc * 0.05, 2.0)
        for k in range(n - 1):
            cutA.line([pts[k], pts[k + 1]], (255, 255, 255, 255), ws[k] + lw * 2)
        for k in range(n - 1):
            mot.line([pts[k], pts[k + 1]], (255, 255, 255, 255), ws[k])
        dist = 0.0
        k = 0
        side = 1
        while k < n - 2:
            hl = float(hloc[k])
            step = max(hl * 0.42, RH * 0.12)
            dist = 0.0
            k0 = k
            while k < n - 2 and dist < step:
                dist += math.hypot(XX[k + 1] - XX[k], yy[k + 1] - yy[k])
                k += 1
            px, py = XX[k], yy[k]
            ang = math.atan2(yy[k + 1] - yy[k], XX[k + 1] - XX[k]) * 0 + (0 if sgn > 0 else math.pi)
            big = hl > RH * 0.6
            kind = (k0 // 3) % 3
            if big and rng.random() < 0.34 and (not flowers or abs(flowers[-1][0] - px) > RH * 0.9):
                fr = hl * 0.2
                fy = py - side * hl * 0.2
                flowers.append((px, fy, fr))
                cutA.line([(px, py), (px + 0.2 * fr, fy)], (255, 255, 255, 255), lw * 3)
                mot.line([(px, py), (px + 0.2 * fr, fy)], (255, 255, 255, 255), lw * 1.2)
            elif big and kind == 1:
                sp = spiral_c(px + side * 0 + hl * 0.1, py - side * hl * 0.17, hl * 0.16, 1.4, math.pi / 2 * side, side)
                cutA.line([(px, py)] + sp, (255, 255, 255, 255), hl * 0.035 + lw * 2)
                mot.line([(px, py)] + sp, (255, 255, 255, 255), hl * 0.035)
            else:
                la = ang - side * (0.9 + 0.3 * rng.random())
                lp = leaf_poly(px, py, la, hl * 0.36, hl * 0.15)
                mot.poly(lp, (255, 255, 255, 255))
                cutA.line(lp + [lp[0]], (255, 255, 255, 255), lw * 2)
                tip = (px + math.cos(la) * hl * 0.3, py + math.sin(la) * hl * 0.3)
                cutB.line([(px, py), tip], (255, 255, 255, 255), lw * 0.8)
            side = -side

    vine(cx - cw / 2, g.x0 + g.span * 0.02, -1)
    vine(cx + cw / 2, g.x1 - g.span * 0.01, 1)
    for (fx, fy, fr) in flowers:
        for k in range(5):
            a = k / 5 * 2 * math.pi - math.pi / 2
            pp = ellipse_pts(fx + math.cos(a) * fr * 0.55, fy + math.sin(a) * fr * 0.55, fr * 0.55, fr * 0.42, a, 30)
            mot.poly(pp, (255, 255, 255, 255))
            cutA.line(pp + [pp[0]], (255, 255, 255, 255), lw * 2)
            cutB.line([(fx + math.cos(a) * fr * 0.3, fy + math.sin(a) * fr * 0.3), (fx + math.cos(a) * fr * 0.85, fy + math.sin(a) * fr * 0.85)],
                      (255, 255, 255, 255), lw * 0.7)
        cutB.circle(fx, fy, fr * 0.26, None, (255, 255, 255, 255), lw)
        for k in range(8):
            a = k / 8 * 2 * math.pi
            cutB.circle(fx + math.cos(a) * fr * 0.15, fy + math.sin(a) * fr * 0.15, lw * 0.9, (255, 255, 255, 255))
    # below: an engraved stem with leaves on the magazine and grip
    for (xa, xb, ya, yb) in below_boxes(lay, g):
        bw = xb - xa
        mxp = (xa + xb) / 2
        pts = [(mxp + math.sin(t * 5) * bw * 0.12, ya + (yb - ya) * (0.1 + 0.75 * t)) for t in np.linspace(0, 1, 40)]
        cutB.line(pts, (255, 255, 255, 255), lw * 1.2)
        for k, t in enumerate(np.linspace(0.1, 0.9, 6)):
            px, py = pts[int(t * 39)]
            sd = 1 if k % 2 else -1
            lp = leaf_poly(px, py, -math.pi / 2 + sd * 0.9, bw * 0.3, bw * 0.12)
            cutB.line(lp + [lp[0]], (255, 255, 255, 255), lw)
    am = alpha(mot)
    panel = ((v > 0.11) & (v < 0.89)).astype(np.float32) * lay.mask
    stip = smooth(0.45, 0.6, noise(W, H, 2906, 120.0, 2))
    matte = panel * (1 - am)
    c = c * (1 - matte * (0.42 + 0.22 * stip))[..., None]
    for a_, k, dk in ((alpha(cutA), 2.6, 0.72), (None, 0, 0)):
        if a_ is None:
            continue
        sh = np.clip(relief(-fblur_c(a_, lw * 0.5) * lw * 1.5, 1.0), 0.3, 1.8)
        c = c * (1 + (sh - 1) * np.clip(a_ * 2, 0, 1))[..., None]
        c = mix(c, c * 0.25, a_ * dk)
    polish = ramp(refl * 0.6 + 0.4, BR)
    c = mix(c, polish * (0.95 + 0.08 * noise(W, H, 2907, 50.0, 2, sx=0.05))[..., None], am * 0.85)
    ab = alpha(cutB)
    sh = np.clip(relief(-fblur_c(ab, lw * 0.4) * lw * 1.5, 1.0), 0.3, 1.8)
    c = c * (1 + (sh - 1) * np.clip(ab * 2, 0, 1))[..., None]
    c = mix(c, c * 0.22, ab * 0.8)
    return np.clip(c, 0, 1), 0.35, 0.12


def d_butcher(W, H, lay):
    """red, pink and white smears dragged along polished steel, glossy and thick like wet paint"""
    g = geo(lay)
    x, y, v, RH = g.x, g.y, g.v, g.RH
    q1 = noise(W, H, 3001, 0.9, 3) - 0.5
    q2 = noise(W, H, 3002, 0.9, 3) - 0.5
    xw, yw = x + q1 * RH * 3.0, y + q2 * RH * 1.2
    r1 = fbm(xw / RH * 0.2, yw / RH * 0.7, 3003, 3)
    q3 = fbm(xw / RH * 0.25 + r1 * 1.8, yw / RH * 0.35, 3004, 3) - 0.5
    t = fbm(xw / RH * 0.16 + q3 * 1.4, yw / RH * 0.8 + r1 * 1.2, 3005, 4)
    lo, hi = np.percentile(t, 2), np.percentile(t, 98)
    t = np.clip((t - lo) / (hi - lo), 0, 1)
    tt = (t * 1.8 + 0.1) % 1.0
    edges = np.array([0.15, 0.33, 0.43, 0.5, 0.57, 0.66, 0.85])
    cols = np.array([(0.30, 0.0, 0.03), (0.76, 0.02, 0.08), (0.96, 0.30, 0.44), (1.0, 0.80, 0.84), (1.0, 0.97, 0.96),
                     (0.97, 0.52, 0.62), (0.86, 0.05, 0.12), (0.44, 0.0, 0.04)], np.float32)
    idx = np.digitize(tt, edges)
    lo_e = np.concatenate([[0.0], edges])[idx]
    hi_e = np.concatenate([edges, [1.0]])[idx]
    fr = np.clip((tt - lo_e) / (hi_e - lo_e), 0, 1)
    c = cols[idx] * (0.84 + 0.3 * fr)[..., None]
    # the smear's edges: a thin dark lip, like paint dragged by a blade
    ch = ((idx != np.roll(idx, 1, 0)) | (idx != np.roll(idx, 1, 1))).astype(np.float32)
    c = c * (1 - 0.45 * np.clip(fblur_c(ch, 0.8) * 2.2, 0, 1))[..., None]
    c = fblur_c(c, 0.7)
    sh = np.clip(relief(fblur_c(t, RH * 0.02) * RH * 0.5, 1.0), 0.78, 1.25)
    c = c * sh[..., None]
    steel = ramp(noise(W, H, 3006, 80.0, 2, sx=0.02, sy=1.0), [(0, (0.62, 0.62, 0.66)), (1, (0.9, 0.9, 0.93))])
    c = mix(c, steel, 0.12)
    c = gloss(g, c, 0.18, 0.05, 0.28, 0.1)
    c = c + (0.1 * np.exp(-((v - 1.3) / 0.12) ** 2) * (v > 1))[..., None]
    return np.clip(c, 0, 1), 0.3, 0.12


def d_pinstripe(W, H, lay):
    """green suit cloth, gold pinstripes, a gold FB monogram plate, a red rose, black satin"""
    g = geo(lay)
    x, y, v, RH = g.x, g.y, g.v, g.RH
    folds = noise(W, H, 3101, 2.2, 3, sx=0.35, sy=1.0)
    c = ramp(folds, [(0, (0.015, 0.075, 0.045)), (0.5, (0.035, 0.15, 0.085)), (1, (0.07, 0.24, 0.14))])
    twill = 0.5 + 0.5 * np.sin((x + y) / (RH * 0.022) * 2 * np.pi)
    fuzz = noise(W, H, 3102, 90.0, 2)
    c = c * (0.9 + 0.08 * twill + 0.1 * fuzz)[..., None]
    p = RH * 0.17
    d = np.abs((x % p) - p / 2)
    line = smooth(RH * 0.011, RH * 0.004, d) * (0.75 + 0.25 * np.sin(y / (RH * 0.03) * 2 * np.pi))
    gold = solid(W, H, (0.88, 0.68, 0.28)) * (0.75 + 0.35 * folds)[..., None]
    c = mix(c, gold, line * 0.92)
    sat = 0.5 + 0.5 * np.sin(y / (RH * 0.45) + (noise(W, H, 3103, 1.5, 3) - 0.5) * 7 + x / (RH * 2.0))
    satin = ramp(sat ** 3, [(0, (0.008, 0.008, 0.01)), (0.6, (0.07, 0.07, 0.08)), (1, (0.42, 0.43, 0.47))])
    wb = smooth(1.03, 1.07, v)
    c = mix(c, satin, wb)
    L = Layer(W, H)
    Xs = np.linspace(g.x0, g.x1, 300)
    L.line(band_pts(g, Xs, 1.035), (60, 40, 10, 255), RH * 0.05)
    L.line(band_pts(g, Xs, 1.035), (225, 175, 75, 255), RH * 0.032)
    L.line(band_pts(g, Xs, 1.025), (255, 235, 160, 200), RH * 0.008)
    c = over(c, L.rgba())
    # monogram plate
    pw = RH * 0.92
    px = best_spot(lay, g, pw * 1.05, 0.2, 0.8, 0.35, lo=0.35)
    py = T1(g, px) + 0.5 * E1(g, px)
    ph = E1(g, px) * 0.5
    M = Layer(W, H)
    M.poly(ellipse_pts(px, py, pw / 2, ph / 2, 0, 80), (255, 255, 255, 255))
    pm = alpha(M)
    sh = Layer(W, H)
    sh.poly(ellipse_pts(px + RH * 0.02, py + RH * 0.03, pw / 2, ph / 2, 0, 80), (0, 0, 0, 255))
    c = c * (1 - 0.6 * alpha(sh, RH * 0.02))[..., None]
    rr = np.hypot((x - px) / (pw / 2), (y - py) / (ph / 2))
    th = np.arctan2(y - py, x - px)
    gl = 0.55 + 0.3 * np.cos(2 * (th + 0.9)) * rr + 0.15 * (1 - rr)
    plate = ramp(gl, [(0, (0.4, 0.26, 0.06)), (0.5, (0.8, 0.6, 0.22)), (0.8, (1.0, 0.85, 0.45)), (1, (1.0, 0.97, 0.8))])
    bev = np.clip(relief(fblur_c(pm, RH * 0.015) * RH * 0.08, 1.0), 0.4, 1.8)
    plate = plate * bev[..., None]
    c = mix(c, plate, pm)
    E = Layer(W, H)
    ring = ellipse_pts(px, py, pw / 2 * 0.86, ph / 2 * 0.8, 0, 80)
    E.line(ring + [ring[0]], (255, 255, 255, 255), RH * 0.01)
    E.text((px, py + ph * 0.02), "FB", ("OLDENGL.TTF", ph * 0.66), (255, 255, 255, 255))
    ea = alpha(E)
    esh = np.clip(relief(-fblur_c(ea, 1.2) * RH * 0.02, 1.0), 0.3, 1.8)
    c = c * (1 + (esh - 1) * np.clip(ea * 2, 0, 1) * pm)[..., None]
    c = mix(c, solid(W, H, (0.22, 0.12, 0.02)), ea * 0.85 * pm)
    S = Layer(W, H)
    for sx in (-1, 1):
        cxs = px + sx * pw / 2 * 0.93
        S.circle(cxs, py, RH * 0.022, (120, 90, 30, 255), (60, 40, 10, 255), 1.5)
        S.line([(cxs - RH * 0.016, py - RH * 0.01), (cxs + RH * 0.016, py + RH * 0.01)], (40, 25, 5, 255), RH * 0.008)
    c = over(c, S.rgba())
    # a red rose boutonniere at the front of the receiver
    rx = min(g.rf + RH * 0.5, px - pw * 0.95)
    rx = max(rx, g.x0 + RH * 0.4)
    ry = T1(g, rx) + 0.45 * E1(g, rx)
    R = min(RH * 0.27, E1(g, rx) * 0.3)
    Rr = Layer(W, H)
    for la in (2.5, 3.6):
        lp = leaf_poly(rx, ry, la, R * 2.0, R * 0.8)
        Rr.poly(lp, (30, 95, 45, 255), (10, 40, 15, 255), 1.5)
        Rr.line([(rx, ry), (rx + math.cos(la) * R * 1.7, ry + math.sin(la) * R * 1.7)], (15, 60, 25, 255), max(1.0, R * 0.05))
    for k in range(6):
        a = k / 6 * 2 * math.pi + 0.3
        Rr.poly(ellipse_pts(rx + math.cos(a) * R * 0.48, ry + math.sin(a) * R * 0.48, R * 0.55, R * 0.42, a, 30), (150, 8, 22, 255), (70, 0, 8, 255), 1.5)
    for k in range(5):
        a = k / 5 * 2 * math.pi + 0.9
        Rr.poly(ellipse_pts(rx + math.cos(a) * R * 0.25, ry + math.sin(a) * R * 0.25, R * 0.42, R * 0.32, a, 30), (200, 20, 38, 255), (90, 0, 12, 255), 1.5)
    Rr.circle(rx, ry, R * 0.36, (215, 30, 48, 255))
    Rr.line(spiral_c(rx, ry, R * 0.34, 1.6, 0.0, 1), (100, 0, 14, 255), max(1.0, R * 0.07))
    ra = Rr.rgba()
    c = over(c, ra)
    c = c + (np.exp(-((v - 0.16) / 0.06) ** 2) * 0.03 * g.inb)[..., None]
    return np.clip(c, 0, 1), 0.3, 0.06


def d_hot_rod(W, H, lay):
    """candy-apple red, yellow-to-red flames from the muzzle, blue pinstripe outlines"""
    g = geo(lay)
    x, y, v, f, RH = g.x, g.y, g.v, g.f, g.RH
    refl = 0.22 + 0.62 * np.exp(-((v - 0.22) / 0.42) ** 2) + 0.16 * (noise(W, H, 3201, 2.0, 3) - 0.5)
    refl = np.where(v > 1.05, 0.3 + 0.25 * np.cos(x / RH * 1.4) + 0.1 * (noise(W, H, 3202, 2.0, 3) - 0.5), refl)
    c = ramp(refl, [(0, (0.16, 0.0, 0.01)), (0.45, (0.50, 0.01, 0.03)), (0.75, (0.80, 0.04, 0.06)), (1, (1.0, 0.30, 0.26))])
    rf_f, rb_f = (g.rf - g.x0) / g.span, (g.rb - g.x0) / g.span
    F = Layer(W, H)
    # a solid flame mass over the barrel up to the receiver front, then four fat tongues licking back
    fn = rf_f + 0.02
    nose = band_pts(g, np.linspace(g.x0 - 10, FX(g, fn), 40), -0.25) + band_pts(g, np.linspace(FX(g, fn), g.x0 - 10, 40), 1.3)
    F.poly(nose, (255, 255, 255, 255))
    tongues = [(0.10, 0.38, 0.72, 0.07, 0.0, -1), (0.40, 0.42, 1.0, 0.09, 1.6, 1), (0.70, 0.42, 0.84, 0.08, 3.0, -1),
               (0.98, 0.38, 0.58, 0.07, 4.2, 1), (1.22, 0.32, 0.3, 0.05, 5.0, -1)]
    fs = max(0.0, rf_f - 0.03)
    fmax = 0.0
    for vc, wv, e, amp, ph, hook in tongues:
        fe = rf_f + (rb_f - rf_f) * e if rf_f > 0.08 else 0.06 + 0.86 * e
        fmax = max(fmax, fe)
        ts = np.linspace(0, 1, 160)
        Xs = FX(g, fs + (fe - fs) * ts)
        vs = vc + amp * np.sin(ts * np.pi * 2.0 + ph) * smooth(0.0, 0.6, ts) + hook * 0.22 * smooth(0.65, 1.0, ts) ** 2
        env = np.interp(Xs, g.xs, g.env)
        path = np.stack([Xs, np.interp(Xs, g.xs, g.top) + vs * env], 1)
        # the board's tongues went thin over their whole rear half: these keep their body almost to the tip
        widths = wv * env * (1 - ts ** 4) ** 0.6 + 1.0
        poly, _ = outline_of(path, widths)
        F.poly(poly, (255, 255, 255, 255))
    fa = alpha(F)
    # inner licks of orange flame along the solid mass over the barrel, so it is no flat block of yellow
    F2 = Layer(W, H)
    for vc, ph, ln in ((0.3, 0.4, 1.0), (0.58, 2.1, 0.8), (0.82, 4.0, 0.62)):
        ts = np.linspace(0, 1, 120)
        Xs = FX(g, -0.03 + (fn + 0.06) * ln * ts)
        env = np.interp(Xs, g.xs, g.env)
        vs = vc + 0.06 * np.sin(ts * np.pi * 3.0 + ph)
        path = np.stack([Xs, np.interp(Xs, g.xs, g.top) + vs * env], 1)
        poly, _ = outline_of(path, 0.22 * env * np.sin(np.pi * np.clip(ts, 0.02, 1)) ** 0.6 * (1 - ts ** 3) + 1.0)
        F2.poly(poly, (255, 255, 255, 255))
    fa2 = alpha(F2) * fa
    k = 2 * int(max(1, RH * 0.014)) + 1
    im = Image.fromarray((fa * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(k))
    dil = np.asarray(im, np.float32) / 255.0
    stripe = np.clip(dil - fa, 0, 1)
    shadow = fblur_c(shift(dil, RH * 0.02, RH * 0.035), RH * 0.02)
    c = c * (1 - 0.55 * shadow * (1 - dil))[..., None]
    f0 = max(0.0, rf_f - 0.2)
    ff = np.clip((f - f0) / max(fmax - f0, 1e-3), 0, 1)
    # a deeper yellow at the muzzle than the board's pale cream, then orange and red
    fc = ramp(ff, [(0, (1.0, 0.88, 0.3)), (0.25, (1.0, 0.8, 0.12)), (0.55, (1.0, 0.55, 0.04)), (0.85, (0.96, 0.27, 0.04)),
                   (1, (0.85, 0.12, 0.04))])
    # the round of the barrel and receiver, lit from above, and faint licks along the flame
    lick = noise(W, H, 3204, 3.0, 3, sx=0.25, sy=2.5)
    round_ = 0.74 + 0.36 * np.exp(-((v - 0.28) / 0.42) ** 2)
    inner = fblur_c(fa, RH * 0.04)
    fc = fc * ((0.72 + 0.3 * inner) * (0.9 + 0.2 * lick) * round_)[..., None]
    fc2 = np.array([1.0, 0.44, 0.04], np.float32) * ((0.85 + 0.25 * lick) * round_)[..., None]
    c = mix(c, fc, fa)
    c = mix(c, fc2, fblur_c(fa2, RH * 0.008) * 0.95)
    c = mix(c, solid(W, H, (0.12, 0.55, 1.0)), stripe)
    # Kustom pinstripe flourish on the magazine and grip
    P = Layer(W, H)
    lw = max(1.2, RH * 0.013)
    for (xa, xb, ya, yb) in below_boxes(lay, g):
        bw, h = xb - xa, yb - ya
        cx = (xa + xb) / 2
        s = min(bw * 0.42, h * 0.22)
        y0 = ya + h * 0.2
        for sd in (-1, 1):
            pts = bezier([(cx, y0), (cx + sd * s * 0.9, y0 - s * 0.3), (cx + sd * s * 1.0, y0 + s * 0.5), (cx + sd * s * 0.3, y0 + s * 0.6),
                          (cx + sd * s * 0.5, y0 + s * 1.05), (cx, y0 + s * 1.7)], 14)
            P.line(pts, (245, 245, 255, 255), lw)
            inn = [(cx + (px - cx) * 0.55, y0 + s * 0.35 + (py - y0) * 0.55) for px, py in pts]
            P.line(inn, (30, 140, 255, 255), lw)
            P.line(spiral_c(cx + sd * s * 0.62, y0 + s * 0.12, s * 0.22, 1.1, math.pi, sd), (245, 245, 255, 255), lw)
        P.poly([(cx, y0 + s * 0.6), (cx + s * 0.12, y0 + s * 0.8), (cx, y0 + s), (cx - s * 0.12, y0 + s * 0.8)], (30, 140, 255, 255))
    c = over(c, P.rgba())
    flake = smooth(0.74, 0.8, noise(W, H, 3203, 160.0, 1))
    c = c + (flake * 0.22)[..., None] * np.array([1.0, 0.7, 0.6])
    c = gloss(g, c, 0.15, 0.035, 0.38, 0.1)
    return np.clip(c, 0, 1), 0.3, 0.1


WY = {"r": (232, 32, 52, 255), "g": (40, 172, 74, 255), "y": (255, 206, 32, 255), "b": (40, 112, 226, 255),
      "p": (250, 112, 172, 255), "v": (146, 72, 206, 255), "o": (255, 132, 30, 255), "k": (10, 10, 12, 255)}


def rooster(L, ox, oy, s, fl):
    """A Lowicz paper-cut rooster standing at (ox, oy), facing right (fl=1) or left (fl=-1), about s tall."""
    def P(px, py):
        return (ox + fl * px * s, oy + py * s)

    def poly(pts, col):
        L.poly([P(*p) for p in pts], col)

    base = (-0.12, -0.42)
    tips = [(-0.28, -1.02), (-0.46, -0.96), (-0.60, -0.82), (-0.68, -0.62), (-0.66, -0.40)]
    cols = ["g", "b", "y", "p", "v"]
    inn = ["y", "p", "r", "g", "y"]
    for (tx, ty), cc, ic in zip(tips, cols, inn):
        dx, dy = tx - base[0], ty - base[1]
        ln = math.hypot(dx, dy)
        nx, ny = dy / ln, -dx / ln
        path = bezier([base, ((base[0] + tx) / 2 - nx * 0.12, (base[1] + ty) / 2 - ny * 0.12), (tx, ty)], 24)
        t = np.linspace(0, 1, len(path))
        w = 0.17 * np.sin(np.pi * np.clip(t * 0.92 + 0.06, 0, 1)) ** 0.8
        pp, _ = outline_of(path, w)
        poly(pp, WY[cc])
        pp, _ = outline_of(path, w * 0.42)
        poly(pp, WY[ic])
    body = bezier([(0.30, -0.62), (0.41, -0.47), (0.34, -0.28), (0.12, -0.18), (-0.12, -0.2), (-0.28, -0.32), (-0.30, -0.46),
                   (-0.15, -0.55), (0.05, -0.58), (0.30, -0.62)], 10)
    poly(body, WY["r"])
    for bx, by in ((-0.06, -0.26), (0.05, -0.25), (0.16, -0.27)):
        L.circle(*P(bx, by), 0.024 * s, WY["k"])
    wing = bezier([(-0.2, -0.45), (0.0, -0.53), (0.2, -0.48), (0.22, -0.38), (0.05, -0.31), (-0.12, -0.34), (-0.2, -0.45)], 10)
    poly(wing, WY["b"])
    poly([(0.0 + (px - 0.0) * 0.66, -0.42 + (py + 0.42) * 0.62) for px, py in wing], WY["g"])
    for k in range(3):
        poly([(-0.1 + k * 0.09, -0.36), (0.02 + k * 0.09, -0.46), (0.0 + k * 0.09, -0.36)], WY["y"])
    for bx, by in ((0.31, -0.52), (0.35, -0.42), (0.31, -0.32)):
        L.circle(*P(bx, by), 0.045 * s, WY["y"])
        L.circle(*P(bx, by), 0.02 * s, WY["r"])
    poly([(0.15, -0.57), (0.24, -0.86), (0.41, -0.87), (0.44, -0.55), (0.39, -0.49), (0.34, -0.56), (0.29, -0.49), (0.24, -0.57), (0.19, -0.51)], WY["y"])
    poly([(0.27, -0.93), (0.30, -1.0), (0.33, -0.95), (0.37, -1.01), (0.39, -0.94), (0.43, -0.97), (0.42, -0.88)], WY["p"])
    L.circle(*P(0.345, -0.86), 0.085 * s, WY["r"])
    poly([(0.42, -0.89), (0.54, -0.85), (0.42, -0.81)], WY["o"])
    poly(ellipse_pts(0.405, -0.765, 0.028, 0.055, 0, 20), WY["p"])
    L.circle(*P(0.36, -0.875), 0.027 * s, (255, 255, 255, 255))
    L.circle(*P(0.365, -0.875), 0.013 * s, WY["k"])
    for lx in (0.0, 0.13):
        L.line([P(lx + 0.02, -0.2), P(lx, -0.02)], WY["o"], 0.03 * s)
        L.line([P(lx - 0.07, 0.0), P(lx + 0.09, 0.0)], WY["o"], 0.025 * s)


def rosette(L, cx, cy, R, cols=("g", "y", "r", "b", "p", "y")):
    for k, (fr, n) in enumerate(((1.0, 12), (0.8, 10), (0.62, 10), (0.46, 8), (0.3, 6), (0.15, 0))):
        L.poly(scallop(cx, cy, R * fr, n, 0.16), WY[cols[k % len(cols)]])
    for k in range(8):
        a = k / 8 * 2 * math.pi
        L.circle(cx + math.cos(a) * R * 0.71, cy + math.sin(a) * R * 0.71, R * 0.045, WY["k"])


def tulip(L, cx, cy, s, col="r", inner="y"):
    pts = [(-0.1, 0), (-0.13, -0.13), (-0.05, -0.07), (0, -0.17), (0.05, -0.07), (0.13, -0.13), (0.1, 0), (0, 0.04)]
    L.poly([(cx + px * s, cy + py * s) for px, py in pts], WY[col])
    L.poly([(cx + px * s * 0.5, cy + py * s * 0.55 - s * 0.01) for px, py in pts], WY[inner])


def d_wycinanki(W, H, lay):
    """Polish folk paper-cut: two roosters around a tree of life, rosettes on black"""
    g = geo(lay)
    RH = g.RH
    c = ramp(noise(W, H, 3301, 40.0, 3), [(0, (0.025, 0.025, 0.03)), (1, (0.07, 0.07, 0.08))])
    L = Layer(W, H)
    s = min(RH * 0.9, (g.rb - g.rf) / 3.15)
    cx = best_spot(lay, g, s * 3.1, 0.1, 0.9, 0.15, lo=0.25)
    cx = min(max(cx, g.rf + s * 1.55), g.rb - s * 1.5)
    oy = T1(g, cx) + E1(g, cx) * 0.95
    # tree of life
    L.line([(cx, oy), (cx, oy - s * 0.72)], WY["g"], s * 0.045)
    for k, (hy, ln) in enumerate(((0.12, 0.34), (0.32, 0.3))):
        for sd in (-1, 1):
            a = -math.pi / 2 + sd * (1.05 - k * 0.2)
            L.poly(leaf_poly(cx, oy - s * hy, a, s * ln, s * 0.13), WY["g"])
            L.poly(leaf_poly(cx, oy - s * hy, a, s * ln * 0.75, s * 0.05), WY["y"])
    for sd in (-1, 1):
        br = bezier([(cx, oy - s * 0.45), (cx + sd * s * 0.2, oy - s * 0.5), (cx + sd * s * 0.3, oy - s * 0.62)], 12)
        L.line(br, WY["g"], s * 0.03)
        tulip(L, cx + sd * s * 0.3, oy - s * 0.62, s * 0.9, "b" if sd < 0 else "v", "p")
    rosette(L, cx, oy - s * 0.74, s * 0.26)
    rooster(L, cx - s * 1.05, oy, s, 1)
    rooster(L, cx + s * 1.05, oy, s, -1)

    def vine(Xa, Xb):
        if Xb - Xa < RH * 0.3:
            return
        XX = np.linspace(Xa, Xb, 200)
        hl = np.minimum(np.interp(XX, g.xs, lay.height(g.xs)), np.interp(XX, g.xs, g.env))
        hl = np.convolve(np.pad(hl, 10, mode="edge"), np.ones(10) / 10, "same")[10:-10]
        mid = np.interp(XX, g.xs, g.top) + hl * 0.5
        yy = mid + hl * 0.12 * np.sin((XX - Xa) / (RH * 0.5) * np.pi)
        L.line(list(zip(XX, yy)), WY["g"], max(2.0, float(hl.min()) * 0.06))
        k, n, side = 6, 0, 1
        cyc = ["leaf", "tulip", "leaf", "ros"]
        while k < 194:
            h = float(hl[k])
            px, py = XX[k], yy[k]
            kind = cyc[n % 4]
            if kind == "leaf":
                a = -math.pi / 2 * side + 0.5
                L.poly(leaf_poly(px, py, a, h * 0.42, h * 0.2), WY["g" if n % 8 < 4 else "y"])
                L.poly(leaf_poly(px, py, a, h * 0.3, h * 0.07), WY["p"])
            elif kind == "tulip":
                tulip(L, px, py - side * h * 0.1, h * 1.3, "r", "y")
            else:
                rosette(L, px, py, h * 0.3, ("p", "y", "b", "r", "g", "y"))
            side = -side
            n += 1
            step = max(h * 0.48, 6.0)
            kk = k
            while kk < 199 and abs(XX[kk] - XX[k]) < step:
                kk += 1
            k = kk

    vine(g.x0 + g.span * 0.015, cx - s * 1.78)
    vine(cx + s * 1.8, g.x1 - g.span * 0.01)
    for (xa, xb, ya, yb) in below_boxes(lay, g):
        bw, h = xb - xa, yb - ya
        if h < bw * 0.35:
            continue        # a long flat part (the KA-BAR's blade belly): a flower sized to its length would leave the blade
        mx = (xa + xb) / 2
        R = min(bw * 0.4, h * 0.2)
        L.line([(mx, ya + R * 1.2), (mx, yb - h * 0.04)], WY["g"], max(2.0, bw * 0.05))
        for k, t in enumerate(np.linspace(0.3, 0.85, 4)):
            sd = 1 if k % 2 else -1
            py = ya + h * t
            L.poly(leaf_poly(mx, py, -math.pi / 2 + sd * 0.8, bw * 0.42, bw * 0.17), WY["g" if k % 2 else "y"])
            L.poly(leaf_poly(mx, py, -math.pi / 2 + sd * 0.8, bw * 0.3, bw * 0.06), WY["r"])
        rosette(L, mx, ya + R * 1.15, R, ("r", "y", "g", "p", "b", "y"))
        tulip(L, mx, yb - h * 0.05, bw * 1.1, "v", "p")
    la = L.rgba()
    a = la[..., 3]
    sh = fblur_c(shift(a, RH * 0.012, RH * 0.018), RH * 0.008)
    c = c * (1 - 0.7 * sh * (1 - a))[..., None]
    paper = 0.9 + 0.14 * noise(W, H, 3302, 70.0, 2)
    c = over(c, np.dstack([la[..., :3] * paper[..., None], a]))
    return np.clip(c, 0, 1), 0.3, 0.06


def mosquito(L, cx, cy, s, ang, body, wing, vein):
    ca, sa = math.cos(ang), math.sin(ang)

    def P(px, py):
        return (cx + (ca * px - sa * py) * s, cy + (sa * px + ca * py) * s)

    for wa, wl in ((-0.42, 0.62), (-0.2, 0.66)):
        wx, wy = math.cos(wa) * wl / 2, -0.03 + math.sin(wa) * wl / 2
        L.poly([P(*p) for p in ellipse_pts(wx, wy, wl / 2, 0.075, wa, 36)], wing, vein, max(1.0, s * 0.006))
        for off in (-0.03, 0.0, 0.03):
            L.line([P(0.02, -0.03 + off * 0.3), P(wx + math.cos(wa) * wl * 0.45, wy + math.sin(wa) * wl * 0.45 + off)], vein, max(1.0, s * 0.004))
    lw = max(1.0, s * 0.012)
    for st, kn, ft in (((-0.04, 0.05), (-0.2, -0.06), (-0.46, 0.36)), ((0.0, 0.06), (0.03, -0.1), (0.1, 0.48)),
                       ((0.04, 0.05), (0.26, -0.06), (0.58, 0.34)), ((0.05, 0.04), (0.32, -0.14), (0.66, -0.06))):
        L.line([P(*st), P(*kn), P(*ft)], body, lw)
        L.line([P(*ft), P(ft[0] + 0.04, ft[1] + 0.02)], body, lw * 0.7)
    for k in range(8):
        t = k / 7
        L.circle(*P(0.1 + 0.42 * t, 0.01 + 0.07 * t), 0.058 * (1 - 0.5 * t) * s, body)
    L.poly([P(*p) for p in ellipse_pts(0.0, -0.01, 0.1, 0.08, 0.0, 30)], body)
    L.circle(*P(-0.12, 0.02), 0.045 * s, body)
    L.line([P(-0.15, 0.04), P(-0.4, 0.17)], body, lw * 0.9)
    for sd in (-1, 1):
        L.line([P(-0.14, 0.0), P(-0.25, -0.08 + sd * 0.03)], body, lw * 0.6)


def ant(L, cx, cy, s, ang, body):
    ca, sa = math.cos(ang), math.sin(ang)

    def P(px, py):
        return (cx + (ca * px - sa * py) * s, cy + (sa * px + ca * py) * s)

    lw = max(1.0, s * 0.025)
    for st, kn, ft in (((-0.05, 0.03), (-0.2, 0.15), (-0.32, 0.3)), ((0.0, 0.04), (0.05, 0.2), (0.0, 0.35)), ((0.05, 0.03), (0.25, 0.15), (0.4, 0.3)),
                       ((-0.05, 0.0), (-0.18, -0.14), (-0.3, -0.25)), ((0.0, 0.0), (0.06, -0.16), (0.02, -0.3)), ((0.05, 0.0), (0.24, -0.13), (0.4, -0.22))):
        L.line([P(*st), P(*kn), P(*ft)], body, lw)
    L.poly([P(*p) for p in ellipse_pts(0.0, 0.0, 0.11, 0.06, 0.0, 24)], body)
    L.poly([P(*p) for p in ellipse_pts(-0.2, 0.0, 0.08, 0.07, 0.0, 24)], body)
    L.poly([P(*p) for p in ellipse_pts(0.27, 0.01, 0.16, 0.11, 0.1, 30)], body)
    L.circle(*P(0.12, 0.0), 0.03 * s, body)
    for sd in (-1, 1):
        L.line([P(-0.26, sd * 0.03), P(-0.36, sd * 0.13), P(-0.48, sd * 0.1)], body, lw * 0.8)


def d_baltic_amber(W, H, lay):
    """honey Baltic amber with a trapped mosquito and ant, sun spangles, bubbles and a warm inner glow"""
    g = geo(lay)
    x, y, v, RH = g.x, g.y, g.v, g.RH
    warp = noise(W, H, 3401, 1.5, 4) - 0.5
    flow = fbm(x / RH * 0.3 + warp * 1.5, (y + 0.35 * RH * np.sin(x / (RH * 1.6)) + warp * RH * 0.6) / RH * 4.5, 3402, 4)
    cxg = (g.rf + g.rb) / 2
    # Deep resin, not orange plastic (the board's weak spot): what shows is the colour of the light that went through
    # it. Thick, dark cognac where the band is deep and at its edges; a warm glow scattered inside, brightest in lumps
    # around the middle; the far (lower) edge lit up by the light focused through the piece; pour layers inside.
    band = (v <= 1.02).astype(np.float32)
    lumps = smooth(0.3, 0.8, noise(W, H, 3407, 2.2, 4))
    lumps2 = smooth(0.28, 0.85, noise(W, H, 3409, 1.4, 4))
    edge = np.clip(np.abs(v - 0.48) / 0.52, 0, 1) * band
    glow = band * np.exp(-((v - 0.5) / 0.32) ** 2) * (0.25 + 0.95 * lumps) * (0.6 + 0.4 * np.exp(-((x - cxg) / (RH * 2.4)) ** 2))
    glow = glow + (1 - band) * (0.05 + 1.05 * lumps2 ** 1.4) * (0.75 + 0.25 * lumps)
    deep = ramp(0.35 + 0.5 * (flow - 0.5) + 0.25 * (noise(W, H, 3403, 5.0, 3) - 0.5),
                [(0, (0.05, 0.01, 0.0)), (0.5, (0.16, 0.04, 0.0)), (1, (0.32, 0.1, 0.005))])
    deep = deep * (1 - 0.5 * edge ** 2)[..., None]
    lit = ramp(np.clip(glow, 0, 1) ** 1.2, [(0, (0.0, 0.0, 0.0)), (0.35, (0.55, 0.2, 0.02)), (0.7, (0.98, 0.55, 0.09)),
                                             (1, (1.0, 0.84, 0.4))])
    caustic = band * np.exp(-((v - 0.9) / 0.07) ** 2) * (0.35 + 0.65 * lumps)
    c = deep + lit + (caustic * 0.55)[..., None] * np.array([1.0, 0.62, 0.16])
    layers = np.exp(-((flow - 0.5) / 0.018) ** 2) + 0.6 * np.exp(-((flow - 0.32) / 0.012) ** 2)
    c = c + (layers * (0.1 + 0.25 * glow))[..., None] * np.array([1.0, 0.7, 0.3])
    milky = smooth(0.66, 0.82, fbm(x / RH * 0.5, y / RH * 2.5, 3404, 4)) * 0.16 * glow
    c = mix(c, solid(W, H, (1.0, 0.85, 0.55)), milky)
    # specks of debris: some sharp near the surface, more of them deep down and out of focus
    deb = smooth(0.78, 0.84, noise(W, H, 3405, 90.0, 2)) * 0.35
    deb_deep = blurf(smooth(0.74, 0.8, noise(W, H, 3408, 45.0, 2)), RH * 0.012) * 0.45
    c = c * (1 - deb * 0.6 - deb_deep * 0.5)[..., None]
    rng = np.random.default_rng(3406)
    I = Layer(W, H)
    mx = best_spot(lay, g, RH * 1.1, 0.12, 0.88, 0.3, lo=0.35)
    my = T1(g, mx) + E1(g, mx) * 0.46
    ms = min(RH * 1.2, E1(g, mx) * 1.2)
    mosquito(I, mx - ms * 0.08, my, ms, -0.12, (40, 14, 2, 240), (130, 80, 25, 80), (50, 20, 4, 170))
    ax = g.rf + RH * 0.5
    if abs(ax - mx) < RH * 1.1:
        ax = mx - RH * 1.15
    ax = max(ax, g.x0 + RH * 0.4)
    ant(I, ax, T1(g, ax) + E1(g, ax) * 0.55, min(RH * 0.8, E1(g, ax) * 0.95), 0.35, (35, 12, 2, 235))
    boxes = below_boxes(lay, g)
    if boxes:
        xa, xb, ya, yb = max(boxes, key=lambda b: (b[1] - b[0]) * (b[3] - b[2]))
        bw, h = xb - xa, yb - ya
        stem = [((xa + xb) / 2 + math.sin(tt * 3) * bw * 0.1, ya + h * (0.25 + 0.6 * tt)) for tt in np.linspace(0, 1, 20)]
        I.line(stem, (60, 35, 5, 200), max(1.0, bw * 0.03))
        for k in range(9):
            px, py = stem[2 + k * 2]
            for sd in (-1, 1):
                I.poly(leaf_poly(px, py, -math.pi / 2 + sd * 1.1, bw * 0.3 * (1 - k * 0.07), bw * 0.08), (70, 45, 8, 190))
    ia = I.rgba(blur=max(0.6, RH * 0.004))
    # the inclusions sit inside: a soft shadow cast deeper into the resin, and the resin's colour over them
    c = c * (1 - 0.4 * fblur_c(shift(ia[..., 3], RH * 0.05, RH * 0.07), RH * 0.04))[..., None]
    c = over(c, ia, 0.9)
    # sun spangles and bubbles
    S = Layer(W, H)
    for _ in range(18):
        X = g.x0 + rng.random() * g.span
        vv = rng.random() * 1.6 - 0.05
        px, py = X, T1(g, X) + vv * E1(g, X)
        if not lay.mask[int(min(max(py, 0), H - 1)), int(min(max(px, 0), W - 1))] or abs(px - mx) < ms * 0.5:
            continue
        r = RH * (0.06 + 0.1 * rng.random())
        a = rng.random() * math.pi
        S.poly(ellipse_pts(px, py, r, r * 0.45, a, 40), (255, 190, 60, 150), (255, 248, 200, 255), max(1.0, RH * 0.008))
        for k in range(9):
            aa = k / 9 * 2 * math.pi
            S.line([(px, py), (px + math.cos(aa) * math.cos(a) * r * 0.85 - math.sin(aa) * math.sin(a) * r * 0.38,
                               py + math.cos(aa) * math.sin(a) * r * 0.85 + math.sin(aa) * math.cos(a) * r * 0.38)],
                   (255, 235, 160, 170), max(1.0, RH * 0.004))
    for _ in range(40):
        X = g.x0 + rng.random() * g.span
        px, py = X, T1(g, X) + (rng.random() * 1.7 - 0.05) * E1(g, X)
        r = RH * (0.008 + 0.03 * rng.random() ** 2)
        S.circle(px, py, r, (255, 220, 150, 60), (90, 40, 5, 200), max(1.0, r * 0.18))
        S.circle(px - r * 0.35, py - r * 0.35, r * 0.25, (255, 255, 240, 230))
    sa_ = S.rgba()
    c = over(c, sa_, 0.85) + glow_of(sa_, RH * 0.025, 0.5)
    # a hard, wet clear-coat on top
    c = gloss(g, c, 0.14, 0.025, 0.4, 0.06)
    c = c + (0.18 * np.exp(-((v - 1.3) / 0.05) ** 2) * (v > 1))[..., None]
    return np.clip(c, 0, 1), 0.2, 0.04


def star_path(cx, cy, r, rot=0.0):
    pts = []
    for k in range(6):
        a = rot - math.pi / 2 + k * 4 * math.pi / 5
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def d_freehand(W, H, lay):
    """marker doodles on white: skull, BANG burst, arrow, stars, tally marks, red accents"""
    g = geo(lay)
    RH = g.RH
    c = ramp(noise(W, H, 3501, 30.0, 3), [(0, (0.88, 0.88, 0.86)), (1, (0.98, 0.98, 0.97))])
    ink, red = (18, 18, 22, 255), (222, 28, 38, 255)
    mw, pw = RH * 0.03, RH * 0.016
    rng = np.random.default_rng(3502)
    sd = [3510]
    L = Layer(W, H)

    def mk(pts, col, w, amp=None):
        sd[0] += 1
        L.line(wob(pts, amp if amp is not None else RH * 0.006, sd[0]), col, w)

    Xs = np.linspace(g.x0 + g.span * 0.01, g.x1 - g.span * 0.01, 200)
    for vv in (0.07, 0.93):
        mk(band_pts(g, Xs, vv), ink, pw, RH * 0.008)
    # pen hatching along the bottom of the band, in a few hand-drawn runs
    for fa_, fb_ in ((0.06, 0.3), (0.42, 0.6), (0.72, 0.97)):
        X = FX(g, fa_)
        while X < FX(g, fb_):
            mk([PX(g, X, 0.79), PX(g, X + RH * 0.09, 0.92)], ink, pw * 0.6, RH * 0.002)
            X += RH * 0.05
    # the skull
    sx = best_spot(lay, g, RH, 0.12, 0.88, 0.35, lo=0.42)
    S = E1(g, sx) * 0.42
    sx = best_spot(lay, g, S * 2.4, 0.12, 0.88, 0.35, lo=0.42)
    sy = T1(g, sx) + E1(g, sx) * 0.5
    S = E1(g, sx) * 0.42
    for a in (0.6, -0.6):
        p0 = (sx - math.cos(a) * S * 1.15, sy + S * 0.2 - math.sin(a) * S * 0.85)
        p1 = (sx + math.cos(a) * S * 1.15, sy + S * 0.2 + math.sin(a) * S * 0.85)
        L.line([p0, p1], ink, S * 0.22)
        L.line([p0, p1], (250, 250, 248, 255), S * 0.13)
        for p in (p0, p1):
            for o in (-1, 1):
                q = (p[0] + o * S * 0.08 * math.sin(a), p[1] - o * S * 0.08 * math.cos(a))
                L.circle(q[0], q[1], S * 0.11, (250, 250, 248, 255), ink, mw * 0.6)
    skull = ellipse_pts(sx, sy - S * 0.18, S * 0.72, S * 0.66, 0, 40)
    jaw = [(sx - S * 0.42, sy + S * 0.25), (sx - S * 0.38, sy + S * 0.7), (sx + S * 0.38, sy + S * 0.7), (sx + S * 0.42, sy + S * 0.25)]
    L.poly(jaw, (250, 250, 248, 255))
    L.poly(skull, (250, 250, 248, 255))
    mk(skull + [skull[0]], ink, mw)
    mk([jaw[0], jaw[1], jaw[2], jaw[3]], ink, mw)
    for k in range(5):
        tx = sx - S * 0.3 + k * S * 0.15
        mk([(tx, sy + S * 0.42), (tx, sy + S * 0.68)], ink, pw)
    mk([(sx - S * 0.4, sy + S * 0.45), (sx + S * 0.4, sy + S * 0.45)], ink, pw)
    for o in (-1, 1):
        L.poly(ellipse_pts(sx + o * S * 0.29, sy - S * 0.1, S * 0.2, S * 0.17, o * 0.25, 24), ink)
        L.circle(sx + o * S * 0.27, sy - S * 0.08, S * 0.055, red)
    L.poly([(sx, sy + S * 0.12), (sx - S * 0.09, sy + S * 0.3), (sx + S * 0.09, sy + S * 0.3)], ink)
    mk([(sx + S * 0.15, sy - S * 0.82), (sx + S * 0.22, sy - S * 0.6), (sx + S * 0.12, sy - S * 0.5), (sx + S * 0.2, sy - S * 0.38)], ink, pw)
    for k in range(7):
        hx = sx + S * 0.25 + k * S * 0.07
        mk([(hx, sy - S * 0.62 + k * S * 0.03), (hx + S * 0.2, sy - S * 0.3 + k * S * 0.02)], ink, pw * 0.7, RH * 0.003)
    # BANG burst at the front of the receiver
    bx = g.rf + E1(g, g.rf + RH * 0.5) * 0.55
    if sx - bx < S * 2.6:
        bx = sx - S * 2.6
    bx = max(bx, g.x0 + RH * 0.35)
    by = T1(g, bx) + E1(g, bx) * 0.5
    R = E1(g, bx) * 0.44
    burst = []
    for k in range(24):
        a = k / 24 * 2 * math.pi
        rr = R * (1.0 if k % 2 == 0 else 0.68) * (0.9 + 0.2 * rng.random())
        burst.append((bx + math.cos(a) * rr * 1.25, by + math.sin(a) * rr))
    L.poly(burst, (255, 236, 80, 255))
    mk(burst + [burst[0]], red, mw)
    L.text((bx, by), "BANG!", ("Inkfree.ttf", R * 0.62), ink, stroke=max(1, int(R * 0.025)), stroke_fill=ink)
    # arrow pointing at the muzzle
    xa_, xb_ = g.x0 + g.span * 0.03, bx - R * 1.35
    if xb_ - xa_ > RH * 0.5:
        XX = np.linspace(xb_, xa_, 30)
        hl = np.interp(XX, g.xs, lay.height(g.xs))
        yy = np.interp(XX, g.xs, g.top) + np.minimum(hl, np.interp(XX, g.xs, g.env)) * 0.5
        pts = list(zip(XX, yy))
        mk(pts, ink, mw)
        ah = max(float(hl.min()) * 0.5, RH * 0.08)
        tip = pts[-1]
        mk([(tip[0] + ah, tip[1] - ah * 0.6), tip, (tip[0] + ah, tip[1] + ah * 0.6)], ink, mw)
    # stars and a spiral
    for (X, vv, r, col) in ((sx + S * 1.6, 0.3, 0.17, ink), ((bx + sx) / 2, 0.28, 0.13, red), (sx + S * 2.5, 0.7, 0.12, ink)):
        if X > g.x1 - RH * 0.1:
            continue
        mk(star_path(X, T1(g, X) + E1(g, X) * vv, E1(g, X) * r, rng.random() * 0.3), col, mw * 0.9)
    X = (bx + sx) / 2
    mk(spiral_c(X, T1(g, X) + E1(g, X) * 0.72, E1(g, X) * 0.12, 2.3, 0, 1), ink, pw)
    # below: lightning bolt, tally marks, heart
    items = ["bolt", "tally", "heart"]
    for i, (xa, xb, ya, yb) in enumerate(sorted(below_boxes(lay, g))):
        bw, h = xb - xa, yb - ya
        mx = (xa + xb) / 2
        kind = items[i % 3]
        if kind == "bolt":
            s = min(bw * 0.8, h * 0.35)
            y0 = ya + h * 0.2
            bolt = [(mx + s * 0.2, y0), (mx - s * 0.3, y0 + s * 0.55), (mx + s * 0.02, y0 + s * 0.55), (mx - s * 0.22, y0 + s * 1.15),
                    (mx + s * 0.32, y0 + s * 0.42), (mx + s * 0.0, y0 + s * 0.42), (mx + s * 0.28, y0)]
            L.poly(bolt, red)
            mk(bolt + [bolt[0]], ink, mw * 0.9)
        elif kind == "tally":
            s = min(bw * 0.12, h * 0.07)
            for grp in range(2):
                y0 = ya + h * (0.22 + grp * 0.3)
                for k in range(4):
                    tx = mx - s * 1.8 + k * s * 1.1
                    mk([(tx, y0), (tx + s * 0.1, y0 + s * 3.2)], ink, mw * 0.8)
                mk([(mx - s * 2.4, y0 + s * 2.6), (mx + s * 2.3, y0 + s * 0.5)], red if grp else ink, mw * 0.8)
        else:
            s = min(bw * 0.38, h * 0.18)
            y0 = ya + h * 0.35
            heart = [(mx + s * math.sin(t) ** 3, y0 - s * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 16)
                     for t in np.linspace(0, 2 * math.pi, 40)]
            L.poly(heart, red)
            mk(heart, ink, mw * 0.8)
    la = L.rgba()
    c = over(c, la)
    c = c * (1 - 0.06 * smooth(0.6, 0.8, noise(W, H, 3503, 6.0, 3)))[..., None]
    c = gloss(g, c, 0.16, 0.05, 0.06, 0.03)
    return np.clip(c, 0, 1), 0.4, 0.1


BRS = [(0, (0.28, 0.18, 0.04)), (0.5, (0.70, 0.52, 0.18)), (0.8, (0.94, 0.79, 0.42)), (1, (1.0, 0.95, 0.75))]


def d_enigma(W, H, lay):
    """black Bakelite cipher machine: brass letter rotors, keys, cloth wiring"""
    g = geo(lay)
    x, y, v, RH = g.x, g.y, g.v, g.RH
    c = ramp(noise(W, H, 3601, 3.0, 4), [(0, (0.015, 0.012, 0.01)), (1, (0.075, 0.052, 0.036))])
    c = c * (0.85 + 0.25 * noise(W, H, 3602, 14.0, 3))[..., None]
    c = gloss(g, c, 0.12, 0.035, 0.32, 0.09)
    c = c + (0.08 * np.exp(-((v - 1.25) / 0.08) ** 2) * (v > 1))[..., None]
    L = Layer(W, H)
    Xs = np.linspace(g.x0, g.x1, 300)
    for vv in (0.035, 0.965):
        L.line(band_pts(g, Xs, vv), (70, 50, 15, 255), RH * 0.03)
        L.line(band_pts(g, Xs, vv), (215, 170, 80, 255), RH * 0.018)
    c = over(c, L.rgba())
    D = min(0.86 * RH, (g.rb - g.rf) / 3.25)
    rcx = best_spot(lay, g, D * 3.2, 0.1, 0.9, 0.25, lo=0.3)
    R = D / 2
    centres = [(rcx + (k - 1) * D * 1.04) for k in range(3)]
    centres = [(X, T1(g, X) + E1(g, X) * 0.5) for X in centres]
    # cloth wiring along the barrel
    Wl = Layer(W, H)
    x_end = g.x0 + g.span * 0.03
    x_st = centres[0][0] - R * 0.9
    if x_st - x_end > RH * 0.6:
        XX = np.linspace(x_st, x_end, 60)
        hl = np.minimum(np.interp(XX, g.xs, lay.height(g.xs)), np.interp(XX, g.xs, g.env))
        hl = np.convolve(np.pad(hl, 6, mode="edge"), np.ones(6) / 6, "same")[6:-6]
        mid = np.interp(XX, g.xs, g.top) + hl * 0.5
        cw = max(3.0, min(RH * 0.075, float(hl.min()) * 0.28))
        ph = (XX - x_st) / (RH * 0.9) * 2 * np.pi
        for sgn, dark, light in ((1, (70, 6, 6), (205, 60, 45)), (-1, (8, 8, 8), (110, 105, 100))):
            pts = list(zip(XX, mid + sgn * hl * 0.17 * np.sin(ph)))
            tube_c(Wl, pts, cw, dark, light)
            ex, ey = pts[-1]
            Wl.poly([(ex - cw * 0.2, ey - cw * 0.6), (ex - cw * 1.6, ey - cw * 0.6), (ex - cw * 1.6, ey + cw * 0.6), (ex - cw * 0.2, ey + cw * 0.6)],
                    (225, 180, 85, 255), (80, 55, 15, 255), 1)
    c = over(c, Wl.rgba())
    # rotors
    for k, (cx, cy) in enumerate(centres):
        r = np.hypot(x - cx, y - cy)
        th = np.arctan2(y - cy, x - cx)
        sh = fblur_c((r < R * 1.0).astype(np.float32), R * 0.06)
        c = c * (1 - 0.65 * shift(sh, R * 0.06, R * 0.1))[..., None]
        edge = R * (0.965 + 0.035 * np.sign(np.sin(th * 40)))
        m = smooth(edge + 1.0, edge - 1.0, r)
        brushed = 0.55 + 0.32 * np.cos(2 * (th + 0.8 + k * 0.4)) * np.clip(r / R, 0, 1) + 0.1 * noise(W, H, 3603 + k, 60.0, 2)
        knurl = 0.5 + 0.35 * np.cos(th * 80)
        tone = np.where(r > R * 0.86, 0.35 + knurl * 0.6, brushed)
        col = ramp(tone, BRS)
        ring = (r > R * 0.6) & (r < R * 0.84)
        ivory = ramp(0.5 + 0.3 * np.cos(2 * (th + 0.8)), [(0, (0.62, 0.58, 0.48)), (1, (0.95, 0.92, 0.82))])
        col = np.where(ring[..., None], ivory, col)
        hub = r < R * 0.2
        col = np.where(hub[..., None], ramp(0.4 + 0.4 * np.cos(2 * (th + 0.3)), BRS) * 0.8, col)
        rim = smooth(R * 0.8, R * 0.98, r)
        bev = 1 - 0.35 * rim * (np.sin(th) > 0) + 0.25 * rim * (np.sin(th) <= 0)
        ringline = 1 - 0.6 * (np.abs(r - R * 0.6) < R * 0.012) - 0.6 * (np.abs(r - R * 0.84) < R * 0.012) - 0.5 * (np.abs(r - R * 0.2) < R * 0.012)
        col = col * (bev * ringline)[..., None]
        c = mix(c, col, m)
        T = Layer(W, H)
        start = k * 7
        for j in range(26):
            a = j / 26 * 2 * math.pi - math.pi / 2
            T.text((cx + math.cos(a) * R * 0.72, cy + math.sin(a) * R * 0.72), chr(65 + (j + start) % 26), ("consolab.ttf", R * 0.14), (35, 25, 15, 255))
        for j in range(5):
            a = j / 5 * 2 * math.pi + k
            px, py = cx + math.cos(a) * R * 0.42, cy + math.sin(a) * R * 0.42
            T.circle(px, py, R * 0.055, (200, 160, 70, 255), (60, 40, 10, 255), 1.2)
            T.line([(px - math.cos(a + 1) * R * 0.045, py - math.sin(a + 1) * R * 0.045), (px + math.cos(a + 1) * R * 0.045, py + math.sin(a + 1) * R * 0.045)],
                   (50, 35, 10, 255), max(1.0, R * 0.015))
        T.line([(cx - R * 0.12, cy), (cx + R * 0.12, cy)], (40, 28, 8, 255), max(1.0, R * 0.04))
        c = over(c, T.rgba())
    # keys on the magazine and grip
    K = Layer(W, H)
    letters = "QWERTZUIOASDFGHJKPYXCVBNML"
    li = 0
    for (xa, xb, ya, yb) in below_boxes(lay, g):
        bw, h = xb - xa, yb - ya
        kr = min(bw * 0.2, RH * 0.11)
        nc = max(1, int(bw * 0.85 / (kr * 2.5)))
        x0k = (xa + xb) / 2 - (nc - 1) * kr * 1.25
        yk = ya + kr * 1.8
        while yk < yb - kr * 1.6:
            for i in range(nc):
                kx = x0k + i * kr * 2.5
                K.circle(kx + kr * 0.12, yk + kr * 0.18, kr, (0, 0, 0, 160))
                K.circle(kx, yk, kr, (205, 205, 210, 255), (60, 60, 65, 255), max(1.0, kr * 0.06))
                K.circle(kx, yk, kr * 0.8, (18, 16, 15, 255))
                K.ellipse((kx - kr * 0.55, yk - kr * 0.7, kx + kr * 0.25, yk - kr * 0.35), (255, 255, 255, 40))
                K.text((kx, yk + kr * 0.02), letters[li % 26], ("consolab.ttf", kr * 0.95), (240, 236, 220, 255))
                li += 1
            yk += kr * 2.5
    c = over(c, K.rgba())
    return np.clip(c, 0, 1), 0.3, 0.12


# ---------------------------------------------------------------------------------------------- set D helpers
# (ctx(): x, y, band top and bottom, v across the band, bh the size unit)


def at_d(fn, x):
    """A scalar of one of lay's band functions."""
    return float(fn(np.array([float(x)]))[0])


def fx(lay, f):
    """Canvas x at fraction f along the gun (0 = muzzle, 1 = butt)."""
    return lay.x0 + (lay.x1 - lay.x0) * f


def envelope(lay):
    """A smooth upper envelope of the band height (the receiver's real depth even where the band has holes)."""
    if getattr(lay, "_d_env", None) is None:
        W = lay.W
        h = lay.height(np.arange(W, dtype=np.float32))
        k = max(4, W // 12)
        mx = np.lib.stride_tricks.sliding_window_view(np.pad(h, k, mode="edge"), 2 * k + 1).max(1)
        kk = max(2, W // 24)
        env = np.convolve(np.pad(mx, kk, mode="edge"), np.ones(kk) / kk, "same")[kk:-kk]
        xs = np.arange(int(lay.x0), int(lay.x1) + 1)
        cap = float(np.percentile(h[xs], 85)) * 1.05
        lay._d_env = np.minimum(env, cap).astype(np.float32)
    return lay._d_env


def ctx(W, H, lay):
    """x, y, T (top of band per column), B (bottom of the band envelope), v (0 top .. 1 bottom, > 1 below), span,
    bh (the typical band height: the size unit)."""
    x, y = grid(W, H)
    cols = np.arange(W, dtype=np.float32)
    T = lay.top(cols).astype(np.float32)[None, :]
    B = T + envelope(lay)[None, :]
    v = (y - T) / np.maximum(B - T, 1.0)
    span = lay.x1 - lay.x0
    xs = np.arange(int(lay.x0), int(lay.x1) + 1)
    bh = max(float(np.median(lay.height(xs))), H * 0.09)
    return x, y, T, B, v, span, bh


def eb(lay, xx):
    """Band bottom of the envelope at x (scalar or array)."""
    return lay.top(xx) + np.interp(xx, np.arange(lay.W), envelope(lay))


def eh(lay, xx):
    return np.interp(xx, np.arange(lay.W), envelope(lay))


def deep_run(lay, frac=0.55):
    """(xa, xb): the longest stretch of the gun where the band envelope is at least frac of its deepest."""
    e = envelope(lay)
    xs = np.arange(int(lay.x0), int(lay.x1) + 1)
    ok = e[xs] >= frac * e[xs].max()
    best, cur = (xs[0], xs[-1], 0), None
    for i, o in enumerate(ok):
        if o and cur is None:
            cur = i
        if (not o or i == len(ok) - 1) and cur is not None:
            j = i if o else i - 1
            if j - cur > best[2]:
                best = (xs[cur], xs[j], j - cur)
            cur = None
    return float(best[0]), float(best[1])


def lnoise(W, H, seed, scale=1.0, octaves=4, sx=1.0, sy=1.0, div=4):
    """noise() computed at 1/div resolution and scaled up (cheap, smooth)."""
    w, h = max(8, W // div), max(8, H // div)
    n = noise(w, h, seed, scale, octaves, sx, sy)
    return np.asarray(Image.fromarray(n.astype(np.float32), "F").resize((W, H), Image.BILINEAR), np.float32)


def lbump(W, H, seed, scale, octaves=4, div=4, sx=1.0, sy=1.0):
    """(height, light) of a noise relief lit from the top left, both 0..1-ish, computed small and scaled up."""
    w, h = max(8, W // div), max(8, H // div)
    n = noise(w, h, seed, scale, octaves, sx, sy)
    k = np.exp(-np.arange(-4, 5) ** 2 / (2 * 1.6 ** 2))
    k /= k.sum()
    n = np.apply_along_axis(lambda r: np.convolve(np.pad(r, 4, mode="edge"), k, "valid"), 1, n)
    n = np.apply_along_axis(lambda r: np.convolve(np.pad(r, 4, mode="edge"), k, "valid"), 0, n)
    gy, gx = np.gradient(n)
    lit = 0.5 - (gx + gy) * h / scale * 0.9
    up = lambda a: np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((W, H), Image.BICUBIC), np.float32)  # noqa: E731
    return up(n), up(lit)


def spots(W, H, lay, n=2, f=8):
    """(cx, cy, r) of the n roomiest places of the flank below the band (magazine, grip), biggest first."""
    yy = np.arange(H, dtype=np.float32)[:, None]
    B = eb(lay, np.arange(W, dtype=np.float32))[None, :]
    m = lay.mask & (yy > B + H * 0.01)
    w, h = W // f, H // f
    a = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((w, h), Image.BOX)) > 128
    a = np.pad(a, 1)
    dist = np.zeros(a.shape, np.float32)
    cur = Image.fromarray((a * 255).astype(np.uint8))
    for _ in range(300):
        arr = np.asarray(cur) > 0
        if not arr.any():
            break
        dist += arr
        cur = cur.filter(ImageFilter.MinFilter(3))
    dist = dist[1:-1, 1:-1]
    gy, gx = np.mgrid[0:h, 0:w]
    out = []
    for _ in range(n):
        i = int(np.argmax(dist))
        r = float(dist.flat[i])
        if r <= 0:
            break
        cy, cx = divmod(i, w)
        out.append(((cx + 0.5) * f, (cy + 0.5) * f, r * f))
        dist[np.hypot(gx - cx, gy - cy) < r * 2.2] = 0
    while len(out) < n:
        out.append((fx(lay, 0.45 + 0.25 * len(out)), H * 0.75, H * 0.08))
    return out


def shade_under(c, rgba, dx, dy, blur, op=0.5):
    """Darken c under a layer's alpha, shifted by (dx, dy) and blurred: a drop shadow."""
    a = np.roll(np.roll(rgba[..., 3], int(round(dy)), 0), int(round(dx)), 1)
    if blur > 0.5:
        a = blurf(a, blur)
    return c * (1 - op * a)[..., None]


def text_im(s, fname, size, fill, stroke=0, stroke_fill=None):
    """An RGBA image of a string, cropped to its ink."""
    f = font(fname, size)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    x0, y0, x1, y1 = d.textbbox((0, 0), s, font=f, stroke_width=int(stroke))
    pad = int(size * 0.1) + 2
    im = Image.new("RGBA", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - x0, pad - y0), s, font=f, fill=fill, stroke_width=int(stroke), stroke_fill=stroke_fill)
    bb = im.getbbox()
    return im.crop(bb) if bb else im


def warp(im, shear=0.0, ang=0.0):
    if shear:
        s = abs(shear)
        coef = (1, s, -s * im.height, 0, 1, 0) if shear > 0 else (1, -s, 0, 0, 1, 0)
        im = im.transform((int(im.width + s * im.height), im.height), Image.AFFINE, coef, Image.BICUBIC)
    if ang:
        im = im.rotate(ang, Image.BICUBIC, expand=True)
    return im


def paste_c(L, im, cx, cy):
    """Alpha-composite an RGBA image (already at the layer's scale) centred at canvas (cx, cy)."""
    X, Y = int(round(cx * L.ss - im.width / 2)), int(round(cy * L.ss - im.height / 2))
    x0, y0 = max(0, X), max(0, Y)
    x1, y1 = min(L.img.width, X + im.width), min(L.img.height, Y + im.height)
    if x1 <= x0 or y1 <= y0:
        return
    L.img.alpha_composite(im.crop((x0 - X, y0 - Y, x1 - X, y1 - Y)), (x0, y0))


def fit_paste(L, im, cx, cy, wmax, hmax, shear=0.0, ang=0.0, stretch=False):
    """Paste an image scaled to fit wmax x hmax canvas px (or stretched to exactly that), sheared, rotated."""
    if stretch:
        nw, nh = wmax * L.ss, hmax * L.ss
    else:
        s = min(wmax * L.ss / im.width, hmax * L.ss / im.height)
        nw, nh = im.width * s, im.height * s
    im = im.resize((max(1, int(nw)), max(1, int(nh))), Image.LANCZOS)
    paste_c(L, warp(im, shear, ang), cx, cy)


def band_poly(lay, xa, xb, va, vb, caps=True, n=60, env=True):
    """A ribbon polygon along the band from xa to xb between band fractions va and vb, with round caps."""
    xs = np.linspace(xa, xb, n)
    t = lay.top(xs)
    h = eh(lay, xs) if env else lay.height(xs)
    ya, yb = t + h * va, t + h * vb
    pts = list(zip(xs, ya))
    if caps:
        r, ym = (yb[-1] - ya[-1]) / 2, (yb[-1] + ya[-1]) / 2
        pts += [(xb + math.sin(a) * r, ym - math.cos(a) * r) for a in np.linspace(0, math.pi, 14)]
    pts += list(zip(xs[::-1], yb[::-1]))
    if caps:
        r, ym = (yb[0] - ya[0]) / 2, (yb[0] + ya[0]) / 2
        pts += [(xa - math.sin(a) * r, ym + math.cos(a) * r) for a in np.linspace(0, math.pi, 14)]
    return pts


def ellpts(cx, cy, rx, ry, ang=0.0, n=28):
    ca, sa = math.cos(ang), math.sin(ang)
    return [(cx + ca * rx * math.cos(t) - sa * ry * math.sin(t), cy + sa * rx * math.cos(t) + ca * ry * math.sin(t))
            for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def blob(cx, cy, r, rng, n=22, jit=0.22, sx=1.0, sy=1.0, ang=0.0):
    """A smooth irregular blob polygon."""
    p1, p2, p3 = rng.random(3) * 6.283
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for t in np.linspace(0, 2 * math.pi, n, endpoint=False):
        rr = r * (1 + jit * (0.6 * math.sin(2 * t + p1) + 0.3 * math.sin(3 * t + p2) + 0.25 * math.sin(5 * t + p3)))
        X, Y = math.cos(t) * rr * sx, math.sin(t) * rr * sy
        pts.append((cx + ca * X - sa * Y, cy + sa * X + ca * Y))
    return pts


def wob_d(pts, amp, rng):
    """A hand-drawn version of a polyline: resampled, with a slow wobble of amplitude amp."""
    p = np.asarray(pts, np.float64)
    seg = np.hypot(*np.diff(p, axis=0).T)
    cum = np.concatenate([[0], np.cumsum(seg)])
    tot = max(cum[-1], 1e-3)
    n = max(8, int(tot / max(amp * 2.5, 2.0)))
    t = np.linspace(0, tot, n)
    q = np.stack([np.interp(t, cum, p[:, 0]), np.interp(t, cum, p[:, 1])], 1)
    ph = rng.random(4) * 6.283
    k1, k2 = amp * 14 + 1, amp * 5 + 1
    q[:, 0] += amp * (0.6 * np.sin(t / k1 + ph[0]) + 0.4 * np.sin(t / k2 + ph[1]))
    q[:, 1] += amp * (0.6 * np.sin(t / k1 + ph[2]) + 0.4 * np.sin(t / k2 + ph[3]))
    return [tuple(a) for a in q]


def mline(L, pts, w, col, rng, amp=None, alpha=235):
    """A felt-marker stroke."""
    q = wob_d(pts, w * 0.45 if amp is None else amp, rng)
    L.line(q, col + (alpha,), w)
    for px, py in (q[0], q[-1]):
        L.circle(px, py, w / 2, col + (alpha,))


def circ(cx, cy, r, n=40):
    return [(cx + math.cos(a) * r, cy + math.sin(a) * r) for a in np.linspace(0, 2 * math.pi, n)]


def poly_mask(W, H, pts):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return np.asarray(m, np.float32) / 255.0


def screw(L, cx, cy, r, ang):
    """A chunky Phillips screw head, domed and shiny."""
    L.circle(cx + r * 0.15, cy + r * 0.22, r * 1.32, (0, 0, 0, 80))
    L.circle(cx, cy, r * 1.16, (60, 30, 10, 170))
    for k in range(7):
        t = k / 6
        g = int(105 + 145 * t)
        L.circle(cx - r * 0.22 * t, cy - r * 0.26 * t, r * (1 - 0.8 * t), (g, g, min(255, g + 10), 255))
    for a in (ang, ang + math.pi / 2):
        ca, sa = math.cos(a) * r * 0.62, math.sin(a) * r * 0.62
        L.line([(cx - ca, cy - sa), (cx + ca, cy + sa)], (30, 30, 36, 255), r * 0.26)


def staple(L, cx, cy, ln, ang, w):
    ca, sa = math.cos(ang), math.sin(ang)
    a, b = (cx - ca * ln / 2, cy - sa * ln / 2), (cx + ca * ln / 2, cy + sa * ln / 2)
    L.line([(a[0] + w * 0.4, a[1] + w * 0.7), (b[0] + w * 0.4, b[1] + w * 0.7)], (40, 28, 15, 110), w * 1.3)
    L.line([a, b], (165, 168, 176, 255), w)
    L.line([(a[0] - sa * w * 0.2, a[1] + ca * w * -0.2), (b[0] - sa * w * 0.2, b[1] + ca * w * -0.2)], (245, 246, 250, 255), w * 0.35)
    for px, py in (a, b):
        L.circle(px, py, w * 0.6, (70, 70, 76, 255))


def halftone(x, y, s, tone, ang=0.785):
    """1 inside the Ben-Day dots of a halftone screen of pitch s for a tone 0..1."""
    ca, sa = math.cos(ang), math.sin(ang)
    u = (x * ca + y * sa) / s
    w = (-x * sa + y * ca) / s
    d = np.hypot(u - np.round(u), w - np.round(w))
    r = 0.72 * np.sqrt(np.clip(tone, 0, 1))
    return smooth(r + 0.06, r - 0.06, d) * (tone > 0.02)


def burst(L, cx, cy, rx, ry, n, rng, fill, ink, wd, sharp=0.6):
    pts = []
    for k in range(2 * n):
        a = k / (2 * n) * 2 * math.pi + (rng.random() - 0.5) * 0.15
        r = (0.86 + 0.28 * rng.random()) if k % 2 == 0 else sharp * (0.85 + 0.25 * rng.random())
        pts.append((cx + math.cos(a) * rx * r, cy + math.sin(a) * ry * r))
    L.poly(pts, fill, ink, wd)
    return pts


def star4(L, cx, cy, s, col, thin=0.07):
    """A four-point glint: long spikes up/down/left/right, short diagonal ones."""
    for a, ln in ((0, 1.0), (math.pi / 2, 1.0), (math.pi / 4, 0.42), (3 * math.pi / 4, 0.42)):
        ca, sa = math.cos(a), math.sin(a)
        w = s * thin * (1 if ln == 1.0 else 0.8)
        L.poly([(cx + ca * s * ln, cy + sa * s * ln), (cx - sa * w, cy + ca * w), (cx - ca * s * ln, cy - sa * s * ln),
                (cx + sa * w, cy - ca * w)], col)
    L.circle(cx, cy, s * 0.11, col)


def d_toy_blaster(W, H, lay):
    """foam-dart toy blaster: orange, yellow and blue plastic, chunky screws, a loaded dart window"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(3700)
    band = v <= 1.0
    vv = np.clip(v, 0, 1)
    mold = lnoise(W, H, 3701, 24.0, 2, div=2)
    body = solid(W, H, (1.0, 0.40, 0.03)) * (0.64 + 0.44 * np.clip(np.sin(vv * np.pi), 0, 1) ** 0.5)[..., None]
    body = body + (np.exp(-((vv - 0.25) / 0.07) ** 2) * 0.30)[..., None]
    notch = ((x / max(bh * 0.18, 6.0)) % 1.0) < 0.5
    rail = v < 0.13
    railc = solid(W, H, (0.80, 0.82, 0.86)) * (np.where(notch, 0.72, 1.0) * (0.8 + 0.25 * np.sin(np.clip(v / 0.13, 0, 1) * np.pi)))[..., None]
    body = np.where(rail[..., None], railc, body)
    k = max(bh * 0.1, H * 0.011)
    kn = np.abs(((x + y) / k) % 1 - 0.5) + np.abs(((x - y) / k) % 1 - 0.5)
    low = solid(W, H, (1.0, 0.76, 0.02)) * ((0.84 + 0.14 * mold) * (0.9 + 0.12 * smooth(0.25, 0.55, kn)))[..., None]
    gw = bh * 0.36
    win = (y - B > gw) & (y < H * 0.975)
    winbg = ramp(y / H, [(0, (0.14, 0.14, 0.22)), (1, (0.04, 0.04, 0.08))])
    c = np.where(band[..., None], body, np.where(win[..., None], winbg, low))
    c = c * (0.96 + 0.06 * mold)[..., None]
    # the dart window: foam darts stacked behind smoked plastic
    D = Layer(W, H)
    dh = max(bh * 0.25, H * 0.032)
    dl = dh * 4.2
    row, yy = 0, float(B.min()) + gw + dh * 0.6
    while yy < H + dh:
        xx = -dl * ((row * 0.618) % 1.0)
        while xx < W + dl:
            tip = dh * 0.9
            D.poly([(xx + tip * 0.6, yy - dh * 0.40), (xx + dl, yy - dh * 0.40), (xx + dl, yy + dh * 0.40), (xx + tip * 0.6, yy + dh * 0.40)],
                   (30, 110, 250, 255), (5, 30, 100, 255), dh * 0.07)
            D.line([(xx + tip * 0.9, yy - dh * 0.18), (xx + dl - dh * 0.2, yy - dh * 0.18)], (150, 205, 255, 210), dh * 0.12)
            D.ellipse((xx + dl - dh * 0.16, yy - dh * 0.34, xx + dl + dh * 0.16, yy + dh * 0.34), (8, 40, 120, 255))
            D.ellipse((xx, yy - dh * 0.43, xx + tip * 1.25, yy + dh * 0.43), (255, 105, 10, 255), (110, 35, 0, 255), dh * 0.07)
            D.ellipse((xx + tip * 0.22, yy - dh * 0.3, xx + tip * 0.75, yy - dh * 0.06), (255, 210, 150, 230))
            xx += dl * 1.12
        yy += dh * 1.1
        row += 1
    d = D.rgba()
    d[..., 3] *= win
    c = shade_under(c, d, dh * 0.08, dh * 0.12, dh * 0.1, 0.6)
    c = over(c, d)
    glare = ((x * 0.7 + y) / (W * 0.09)) % 1.0
    c = c + ((smooth(0.0, 0.02, glare) * smooth(0.12, 0.07, glare)) * win * 0.16)[..., None]
    # blue panel, window frame
    P = Layer(W, H)
    xs = np.arange(0, W + 4, 4.0)
    wy = eb(lay, xs) + gw
    P.line(list(zip(xs, wy)), (0, 45, 150, 255), dh * 0.45)
    P.line(list(zip(xs, wy - dh * 0.1)), (50, 150, 255, 255), dh * 0.16)
    P.line([(0, H * 0.975), (W, H * 0.975)], (0, 45, 150, 255), dh * 0.3)
    pa, pb = fx(lay, 0.04), fx(lay, 0.50)
    P.poly(band_poly(lay, pa, pb, 0.33, 0.83), (0, 32, 115, 255))
    P.poly(band_poly(lay, pa, pb, 0.37, 0.79), (10, 95, 255, 255))
    P.poly(band_poly(lay, pa + bh * 0.08, pb - bh * 0.08, 0.40, 0.50), (110, 185, 255, 255))
    for i in range(6):
        xk = fx(lay, 0.075) + i * bh * 0.13
        t0, h0 = at_d(lay.top, xk), at_d(lambda q: eh(lay, q), xk)
        P.line([(xk, t0 + h0 * 0.52), (xk, t0 + h0 * 0.72)], (0, 40, 140, 255), bh * 0.045)
    p = P.rgba()
    c = shade_under(c, p, bh * 0.02, bh * 0.04, bh * 0.03, 0.4)
    c = over(c, p)
    # warning label
    la, lb = fx(lay, 0.60), fx(lay, 0.86)
    xl = np.linspace(la, lb, 40)
    tl, hl = float(np.median(lay.top(xl))), max(float(np.median(eh(lay, xl))), bh * 0.8)
    y0, y1 = tl + hl * 0.2, tl + hl * 0.8
    lh = y1 - y0
    S = Layer(W, H)
    ss = S.ss
    S.d.rounded_rectangle([la * ss, y0 * ss, lb * ss, y1 * ss], radius=int(lh * 0.12 * ss), fill=(250, 250, 244, 255),
                          outline=(15, 15, 15, 255), width=max(1, int(lh * 0.05 * ss)))
    q0 = la + lh * 0.1
    S.d.rounded_rectangle([q0 * ss, (y0 + lh * 0.12) * ss, (q0 + lh * 0.76) * ss, (y1 - lh * 0.12) * ss], radius=int(lh * 0.06 * ss),
                          fill=(255, 205, 0, 255))
    tcx = q0 + lh * 0.38
    S.poly([(tcx, y0 + lh * 0.2), (tcx - lh * 0.31, y1 - lh * 0.22), (tcx + lh * 0.31, y1 - lh * 0.22)], (15, 15, 15, 255))
    S.poly([(tcx, y0 + lh * 0.33), (tcx - lh * 0.2, y1 - lh * 0.28), (tcx + lh * 0.2, y1 - lh * 0.28)], (255, 205, 0, 255))
    fit_paste(S, text_im("!", "ariblk.ttf", 200, (15, 15, 15, 255)), tcx, y0 + lh * 0.6, lh * 0.2, lh * 0.32)
    tx0, tx1 = q0 + lh * 0.9, lb - lh * 0.1
    fit_paste(S, text_im("WARNING", "ariblk.ttf", 200, (225, 20, 20, 255)), (tx0 + tx1) / 2, y0 + lh * 0.25, tx1 - tx0, lh * 0.26)
    fit_paste(S, text_im("DO NOT AIM", "ariblk.ttf", 200, (15, 15, 15, 255)), (tx0 + tx1) / 2, y0 + lh * 0.55, tx1 - tx0, lh * 0.2)
    fit_paste(S, text_im("AT FACE", "ariblk.ttf", 200, (15, 15, 15, 255)), (tx0 + tx1) / 2, y0 + lh * 0.79, tx1 - tx0, lh * 0.2)
    cc = lh * 0.24
    S.poly([(lb - cc, y0 - 1), (lb + 1, y0 - 1), (lb + 1, y0 + cc)], (240, 100, 12, 255))
    S.poly([(lb - cc, y0), (lb, y0 + cc), (lb - cc * 0.8, y0 + cc * 0.8)], (205, 205, 198, 255), (120, 120, 118, 255), 1)
    s = S.rgba()
    c = shade_under(c, s, lh * 0.04, lh * 0.07, lh * 0.05, 0.45)
    c = over(c, s)
    # screws
    Q = Layer(W, H)
    for f, vq in ((0.555, 0.5), (0.915, 0.5), (0.02, 0.55)):
        xq = fx(lay, f)
        hq = max(at_d(lambda q: eh(lay, q), xq), bh * 0.7)
        screw(Q, xq, at_d(lay.top, xq) + hq * vq, max(hq * 0.1, H * 0.013), rng.random() * 3)
    for f in (0.12, 0.42, 0.7, 0.97):
        xq = fx(lay, f)
        screw(Q, xq, at_d(lambda q: eb(lay, q), xq) + gw * 0.5, max(gw * 0.3, H * 0.011), rng.random() * 3)
    c = over(c, Q.rgba())
    return np.clip(c, 0, 1), 0.3, 0.06


def d_cardboard(W, H, lay):
    """a cardboard prop gun: marker-drawn parts, a PEW PEW scrawl, paper tape and staples"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    band = v <= 1.0
    rng = np.random.default_rng(3801)
    n = lnoise(W, H, 3802, 3.0, 4)
    c = ramp(n, [(0, (0.57, 0.40, 0.23)), (1, (0.73, 0.55, 0.34))])
    fib = noise(W, H, 3803, 160.0, 2, sx=0.25)
    c = c * (0.94 + 0.09 * fib)[..., None]
    p = max(H * 0.0125, 5.0)
    flute = np.where(band, np.cos(2 * np.pi * x / p), np.cos(2 * np.pi * y / p))
    c = c * (1 + 0.045 * flute)[..., None]
    c = np.where(band[..., None], c, c * np.array([1.04, 0.97, 0.90], np.float32))
    sp = (rng.random((H, W)) > 0.9982).astype(np.float32)
    c = c * (1 - np.clip(blurf(sp, 1.2) * 4, 0, 0.6))[..., None]
    # the cut edges show the corrugation
    ehh = max(bh * 0.13, H * 0.015)
    lam = ehh * 1.6
    wave = 0.5 + 0.3 * np.sin(2 * np.pi * x / lam)
    for s_ in ((y - T) / ehh, (B - y) / ehh):
        inside = band & (s_ >= 0) & (s_ <= 1)
        dd = np.abs(s_ - wave)
        hol = solid(W, H, (0.24, 0.15, 0.08)) * np.clip(1.1 - 1.5 * dd, 0.35, 1.1)[..., None]
        col = np.where((dd < 0.1)[..., None], solid(W, H, (0.80, 0.63, 0.40)), hol)
        col = np.where(((s_ < 0.15) | (s_ > 0.85))[..., None], c * 1.1, col)
        c = np.where(inside[..., None], col, c)
    # a red-marker muzzle tip
    tipm = band & (x < fx(lay, 0.035))
    hat = smooth(0.55, 0.75, (((x + y) / max(bh * 0.05, 3)) % 1.0)) * 0.25 + 0.75
    c = np.where(tipm[..., None], mix(c, solid(W, H, (0.80, 0.08, 0.08)), hat * 0.92), c)
    # marker drawing
    M = Layer(W, H)
    INK = (25, 22, 28)
    w = max(bh * 0.05, H * 0.0065)
    xs = np.linspace(lay.x0 + span * 0.005, lay.x1 - span * 0.02, 70)
    mline(M, list(zip(xs, lay.top(xs) + ehh * 1.5)), w, INK, rng)
    mline(M, list(zip(xs, eb(lay, xs) - ehh * 1.5)), w, INK, rng)
    for f in (0.05, 0.095, 0.14):
        cx = fx(lay, f)
        h0 = max(at_d(lambda q: eh(lay, q), cx), bh * 0.6)
        mline(M, circ(cx, at_d(lay.top, cx) + h0 * 0.52, h0 * 0.16), w * 0.9, INK, rng)
    # ejection port with hatching
    pa, pb = fx(lay, 0.56), fx(lay, 0.69)
    port = band_poly(lay, pa, pb, 0.3, 0.66, caps=False, n=12)
    mline(M, port + [port[0]], w, INK, rng)
    Hh = Layer(W, H)
    for k in range(-30, 60):
        x0_ = pa + k * bh * 0.07
        Hh.line([(x0_, 0), (x0_ + H * 0.6, H)], INK + (210,), w * 0.55)
    hm = Hh.rgba()
    hm[..., 3] *= poly_mask(W, H, port)
    for f in (0.52, 0.74, 0.95):
        cx = fx(lay, f)
        h0 = max(at_d(lambda q: eh(lay, q), cx), bh * 0.6)
        cy, r = at_d(lay.top, cx) + h0 * 0.5, h0 * 0.1
        mline(M, circ(cx, cy, r), w * 0.8, INK, rng)
        mline(M, [(cx - r * 0.6, cy - r * 0.6), (cx + r * 0.6, cy + r * 0.6)], w * 0.7, INK, rng)
        mline(M, [(cx - r * 0.6, cy + r * 0.6), (cx + r * 0.6, cy - r * 0.6)], w * 0.7, INK, rng)
    # PEW PEW in red marker, with speed marks
    tx = fx(lay, 0.345)
    xr = np.linspace(fx(lay, 0.2), fx(lay, 0.47), 20)
    th = max(float(np.median(eh(lay, xr))), bh * 0.8)
    ty = float(np.median(lay.top(xr))) + th * 0.5
    pew = text_im("PEW PEW", "Inkfree.ttf", 220, (205, 22, 28, 255), stroke=17, stroke_fill=(205, 22, 28, 255))
    fit_paste(M, pew, tx, ty, span * 0.3, th * 0.72, ang=4)
    for k in range(3):
        yk = ty + (k - 1) * th * 0.16
        mline(M, [(fx(lay, 0.175) - k * bh * 0.05, yk), (fx(lay, 0.205), yk)], w * 0.9, (205, 22, 28), rng)
    # a red-marker lightning bolt decal on the back (what the player sees in hand)
    lx = fx(lay, 0.875)
    lh_ = max(at_d(lambda q: eh(lay, q), lx), bh * 0.8)
    lt = at_d(lay.top, lx)
    bolt = [(lx + lh_ * 0.10, lt + lh_ * 0.12), (lx - lh_ * 0.22, lt + lh_ * 0.55), (lx - lh_ * 0.02, lt + lh_ * 0.52),
            (lx - lh_ * 0.12, lt + lh_ * 0.9), (lx + lh_ * 0.24, lt + lh_ * 0.4), (lx + lh_ * 0.03, lt + lh_ * 0.43)]
    BL = Layer(W, H)
    BL.poly(bolt, (210, 25, 30, 235))
    for k in range(14):
        yk = lt + lh_ * (0.14 + 0.055 * k)
        BL.line([(lx - lh_ * 0.3, yk + lh_ * 0.05), (lx + lh_ * 0.3, yk - lh_ * 0.05)], (150, 10, 15, 120), w * 0.5)
    bl = BL.rgba()
    bl[..., 3] *= poly_mask(W, H, bolt)
    mline(M, bolt + [bolt[0]], w * 1.1, INK, rng)
    m = M.rgba()
    c = over(c, hm)
    c = over(c, bl)
    c = over(c, m)
    # box print below: THIS SIDE UP arrows and a fragile glass
    (ax, ay, ar), (gx_, gy_, gr) = spots(W, H, lay, 2)
    PR = Layer(W, H)
    INKP = (38, 30, 24, 230)
    s_ = ar * 0.75
    for kk in (-1, 1):
        cx = ax + kk * s_ * 0.4
        PR.poly([(cx, ay - s_ * 0.8), (cx + s_ * 0.33, ay - s_ * 0.32), (cx + s_ * 0.12, ay - s_ * 0.32), (cx + s_ * 0.12, ay + s_ * 0.45),
                 (cx - s_ * 0.12, ay + s_ * 0.45), (cx - s_ * 0.12, ay - s_ * 0.32), (cx - s_ * 0.33, ay - s_ * 0.32)], INKP)
    PR.line([(ax - s_ * 0.85, ay + s_ * 0.62), (ax + s_ * 0.85, ay + s_ * 0.62)], INKP, s_ * 0.06)
    fit_paste(PR, text_im("THIS SIDE UP", "ariblk.ttf", 160, INKP), ax, ay + s_ * 0.85, s_ * 1.7, s_ * 0.24)
    s2 = gr * 0.75
    bowl = [(gx_ - s2 * 0.38, gy_ - s2 * 0.8)] + [(gx_ + math.cos(a) * s2 * 0.38, gy_ - s2 * 0.8 + math.sin(a) * s2 * 0.62) for a in np.linspace(math.pi, 0, 20)[::-1]]
    PR.line(bowl + [bowl[0]], INKP, s2 * 0.08)
    PR.line([(gx_, gy_ - s2 * 0.18), (gx_, gy_ + s2 * 0.55)], INKP, s2 * 0.08)
    PR.line([(gx_ - s2 * 0.3, gy_ + s2 * 0.58), (gx_ + s2 * 0.3, gy_ + s2 * 0.58)], INKP, s2 * 0.08)
    PR.line([(gx_ - s2 * 0.05, gy_ - s2 * 0.8), (gx_ + s2 * 0.06, gy_ - s2 * 0.6), (gx_ - s2 * 0.06, gy_ - s2 * 0.45), (gx_ + s2 * 0.05, gy_ - s2 * 0.3)], INKP, s2 * 0.05)
    pr = PR.rgba()
    pr[..., 3] *= 0.55 + 0.45 * smooth(0.35, 0.6, lnoise(W, H, 3804, 30.0, 3, div=2))
    c = over(c, pr)
    # paper tape and staples
    TP = Layer(W, H)
    ST = Layer(W, H)
    for f in (0.11, 0.79):
        cx = fx(lay, f)
        t0, b0 = at_d(lay.top, cx), at_d(lambda q: eb(lay, q), cx)
        hw = min(max(b0 - t0, bh) * 0.24, span * 0.035)
        ya, yb2 = t0 - bh * 0.15, b0 + bh * 0.45
        sk = lambda px, py: (px + (py - ya) * 0.07, py)  # noqa: E731
        top_e = [sk(cx - hw + 2 * hw * k / 8, ya + (rng.random() - 0.5) * hw * 0.18) for k in range(9)]
        bot_e = [sk(cx + hw - 2 * hw * k / 8, yb2 + (rng.random() - 0.5) * hw * 0.18) for k in range(9)]
        TP.poly(top_e + bot_e, (234, 218, 170, 232))
        for vq in (0.28, 0.74):
            sx_, sy_ = sk(cx, t0 + (b0 - t0) * vq)
            staple(ST, sx_, sy_, hw * 1.25, (rng.random() - 0.5) * 0.25, max(hw * 0.07, 2.0))
    for f in (0.42, 0.63, 0.9):
        cx = fx(lay, f)
        staple(ST, cx, at_d(lambda q: eb(lay, q), cx), bh * 0.36, math.pi / 2 + (rng.random() - 0.5) * 0.3, max(bh * 0.03, 2.0))
    tp = TP.rgba()
    crepe = 0.93 + 0.1 * lnoise(W, H, 3805, 40.0, 2, sx=0.12, sy=1.0, div=2)
    c = shade_under(c, tp, bh * 0.015, bh * 0.025, bh * 0.02, 0.35)
    c = over(c, np.dstack([tp[..., :3] * crepe[..., None], tp[..., 3:]]))
    c = over(c, ST.rgba())
    return np.clip(c, 0, 1), 0.3, 0.03


def d_comic_pow(W, H, lay):
    """comic-book panels: a BANG! burst, a POW! burst, halftone dots and a speech balloon"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(3901)
    s = max(bh * 0.1, H * 0.012)
    gw = max(bh * 0.07, H * 0.009)
    gB = B + bh * 0.15
    g1 = fx(lay, 0.36) + (y - H * 0.15) * 0.25
    g2 = fx(lay, 0.67) - (y - H * 0.15) * 0.2
    g3 = fx(lay, 0.50) + (y - H * 0.6) * 0.35
    top = y < gB
    pid = np.where(top, np.where(x < g1, 0, np.where(x < g2, 1, 2)), np.where(x < g3, 3, 4))
    dgut = np.where(top, np.minimum(np.abs(x - g1), np.abs(x - g2)), np.abs(x - g3))
    dgut = np.minimum(dgut, np.abs(y - gB))
    # POW panel: yellow, red speed lines from the hit
    px0 = fx(lay, 0.17)
    py0 = at_d(lay.top, px0) + at_d(lambda q: eh(lay, q), px0) * 0.5
    a0 = np.arctan2(y - py0, x - px0)
    r0 = np.hypot(x - px0, (y - py0) * 1.8)
    sp0 = smooth(0.72, 0.9, np.sin(a0 * 26 + 2.0 * np.sin(a0 * 5))) * smooth(bh * 0.5, bh * 1.1, r0)
    p0 = mix(solid(W, H, (1.0, 0.86, 0.12)), solid(W, H, (0.95, 0.30, 0.05)), np.maximum(sp0, halftone(x, y, s, np.clip(r0 / (span * 0.3), 0, 1) * 0.5)))
    # balloon panel: sky blue, darker dots toward the bottom
    p1 = mix(solid(W, H, (0.32, 0.74, 0.98)), solid(W, H, (0.06, 0.32, 0.78)), halftone(x, y, s, np.clip(v, 0, 1) ** 1.4 * 0.75))
    # BANG panel: red, yellow dots dense around the bang
    px2 = fx(lay, 0.83)
    py2 = at_d(lay.top, px2) + at_d(lambda q: eh(lay, q), px2) * 0.48
    r2 = np.hypot(x - px2, (y - py2) * 1.6)
    a2 = np.arctan2(y - py2, x - px2)
    sp2 = smooth(0.8, 0.92, np.sin(a2 * 22 + 1.5 * np.sin(a2 * 4))) * smooth(bh * 0.6, bh * 1.3, r2)
    p2 = mix(solid(W, H, (0.92, 0.10, 0.12)), solid(W, H, (1.0, 0.85, 0.12)), halftone(x, y, s, np.clip(1 - r2 / (span * 0.35), 0, 1) * 0.8))
    p2 = mix(p2, solid(W, H, (0.55, 0.0, 0.05)), sp2 * 0.8)
    # lower panels: night blue with magenta dots; orange with red dots and a burst of lines
    p3 = mix(solid(W, H, (0.10, 0.12, 0.45)), solid(W, H, (0.95, 0.20, 0.62)), halftone(x, y, s * 1.2, np.clip((y - B) / (H * 0.7), 0, 1) * 0.7))
    (sx1, sy1, sr1), = spots(W, H, lay, 1)
    a4 = np.arctan2(y - sy1, x - sx1)
    r4 = np.hypot(x - sx1, y - sy1)
    sp4 = smooth(0.7, 0.88, np.sin(a4 * 18)) * smooth(sr1 * 0.25, sr1 * 0.6, r4)
    p4 = mix(solid(W, H, (1.0, 0.58, 0.10)), solid(W, H, (0.85, 0.08, 0.10)), np.maximum(halftone(x, y, s * 1.2, np.clip(r4 / (sr1 * 2.5), 0, 1) * 0.65), sp4 * 0.9))
    c = p0
    for k, pk in ((1, p1), (2, p2), (3, p3), (4, p4)):
        c = np.where((pid == k)[..., None], pk, c)
    gut = dgut < gw / 2
    ink = (dgut >= gw / 2) & (dgut < gw / 2 + gw * 0.5)
    c = np.where(gut[..., None], solid(W, H, (0.98, 0.96, 0.88)), c)
    c = np.where(ink[..., None], solid(W, H, (0.04, 0.03, 0.05)), c)
    # bursts, balloon, lettering
    L = Layer(W, H)
    INK = (12, 10, 14, 255)
    h0 = max(at_d(lambda q: eh(lay, q), px0), bh)
    ry, rx = h0 * 0.62, min(h0 * 0.62 * 1.8, span * 0.16)
    burst(L, px0 + rx * 0.06, py0 + ry * 0.08, rx, ry, 11, np.random.default_rng(3902), INK, None, 0)
    burst(L, px0, py0, rx, ry, 11, np.random.default_rng(3902), (255, 250, 235, 255), INK, ry * 0.05)
    burst(L, px0, py0, rx * 0.72, ry * 0.72, 9, rng, (235, 30, 35, 255), None, 0, 0.7)
    pow_ = text_im("POW!", "impact.ttf", 220, (255, 222, 0, 255), stroke=14, stroke_fill=INK)
    fit_paste(L, text_im("POW!", "impact.ttf", 220, INK, stroke=14, stroke_fill=INK), px0 + rx * 0.05, py0 + ry * 0.07, rx * 1.15, ry * 0.95, shear=0.25, ang=6)
    fit_paste(L, pow_, px0, py0, rx * 1.15, ry * 0.95, shear=0.25, ang=6)
    h2 = max(at_d(lambda q: eh(lay, q), px2), bh)
    ry2, rx2 = h2 * 0.62, min(h2 * 0.62 * 1.75, span * 0.17)
    burst(L, px2 + rx2 * 0.06, py2 + ry2 * 0.08, rx2, ry2, 13, np.random.default_rng(3903), INK, None, 0)
    burst(L, px2, py2, rx2, ry2, 13, np.random.default_rng(3903), (255, 222, 0, 255), INK, ry2 * 0.05)
    burst(L, px2, py2, rx2 * 0.74, ry2 * 0.74, 11, rng, (255, 130, 0, 255), None, 0, 0.72)
    fit_paste(L, text_im("BANG!", "impact.ttf", 220, INK, stroke=14, stroke_fill=INK), px2 + rx2 * 0.05, py2 + ry2 * 0.07, rx2 * 1.3, ry2 * 0.95, shear=0.25, ang=-5)
    fit_paste(L, text_im("BANG!", "impact.ttf", 220, (255, 255, 255, 255), stroke=14, stroke_fill=INK), px2, py2, rx2 * 1.3, ry2 * 0.95, shear=0.25, ang=-5)
    # speech balloon
    bx = fx(lay, 0.515)
    hb = max(at_d(lambda q: eh(lay, q), bx), bh)
    by = at_d(lay.top, bx) + hb * 0.42
    bry, brx = hb * 0.3, min(hb * 1.25, span * 0.12)
    L.poly([(bx - brx * 0.45, by + bry * 0.6), (bx - brx * 0.95, by + bry * 1.7), (bx - brx * 0.1, by + bry * 0.75)], (255, 255, 255, 255), INK, bry * 0.08)
    L.ellipse((bx - brx, by - bry, bx + brx, by + bry), (255, 255, 255, 255), INK, bry * 0.08)
    L.poly([(bx - brx * 0.42, by + bry * 0.55), (bx - brx * 0.8, by + bry * 1.45), (bx - brx * 0.14, by + bry * 0.72)], (255, 255, 255, 255))
    fit_paste(L, text_im("TAKE THAT!", "comicbd.ttf", 200, INK), bx, by, brx * 1.5, bry * 1.0)
    g = L.rgba()
    c = over(c, g)
    return np.clip(c, 0, 1), 0.3, 0.04


REIN = ["......X.X..X.X..",
        ".......XX..XX...",
        "........XXXX....",
        ".........XX.....",
        ".........XXX....",
        ".........XXXXXR.",
        ".........XXX....",
        "X.......XXX.....",
        ".XXXXXXXXXX.....",
        ".XXXXXXXXXX.....",
        ".XXXXXXXXX......",
        ".X.X....X.X.....",
        ".X..X..X...X....",
        "X....X.X....X..."]


FLAKE = [".....X.....",
         "..X..X..X..",
         "...X.X.X...",
         "....XXX....",
         ".X..X.X..X.",
         "XXXXX.XXXXX",
         ".X..X.X..X.",
         "....XXX....",
         "...X.X.X...",
         "..X..X..X..",
         ".....X....."]


TREE = [".....X.....",
        "....XXX....",
        "...XXXXX...",
        "....XXX....",
        "...XXXXX...",
        "..XXXXXXX..",
        "....XXX....",
        "..XXXXXXX..",
        ".XXXXXXXXX.",
        "XXXXXXXXXXX",
        ".....T.....",
        ".....T.....",
        "....TTT...."]


def d_ugly_sweater(W, H, lay):
    """a Christmas jumper: knitted reindeer, snowflakes, trees and zigzags in red, green and white"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    sh = max(bh / 18, H * 0.011)
    sw = sh * 1.25
    nc, nr = int(W / sw) + 2, int(H / sh) + 2
    RED, GRN, WHT, BRN = 0, 1, 2, 3
    P = np.full((nr, nc), RED, np.int8)
    xs = np.arange(int(lay.x0), int(lay.x1) + 1)
    r0 = int(round(float(np.median(lay.top(xs))) / sh))

    def put(bm, r, c0, cmap, flip=False):
        for i, row in enumerate(bm):
            if flip:
                row = row[::-1]
            for j, ch in enumerate(row):
                if ch != "." and 0 <= r + i < nr and 0 <= c0 + j < nc:
                    P[r + i, c0 + j] = cmap[ch]

    def zig(r, fg):
        for cc in range(nc):
            k = cc % 4
            if 0 <= r < nr and k == 0:
                P[r, cc] = fg
            if 0 <= r + 1 < nr and k in (1, 3):
                P[r + 1, cc] = fg
            if 0 <= r + 2 < nr and k == 2:
                P[r + 2, cc] = fg

    def dots(r, fg, ph=0):
        if 0 <= r < nr:
            P[r, (np.arange(nc) + ph) % 2 == 0] = fg

    R = r0
    dots(R + 1, WHT)
    zig(R + 3, WHT)
    P[R + 6:R + 21, :] = GRN
    c0 = int(lay.x0 / sw) + 1
    k = 0
    cc = c0
    while cc < nc:
        put(REIN, R + 6, cc, {"X": WHT, "R": RED}, flip=(k % 2 == 1))
        cc += 18
        put(FLAKE, R + 8, cc, {"X": WHT})
        cc += 14
        k += 1
    zig(R + 22, WHT)
    dots(R + 26, WHT, 1)
    r = R + 28
    cyc = 0
    while r < nr:
        bg, fg, bm = ((RED, WHT, FLAKE) if cyc % 2 == 0 else (WHT, GRN, TREE))
        P[r:r + len(bm) + 2, :] = bg
        cc = c0 + (7 if cyc % 2 else 0)
        while cc < nc:
            put(bm, r + 1, cc, {"X": fg, "T": BRN if bg == WHT else WHT})
            cc += 15
        r += len(bm) + 2
        P[r:r + 6, :] = RED if bg == WHT else GRN
        zig(r + 1, WHT)
        dots(r + 4, WHT, cyc % 2)
        r += 6
        cyc += 1
    ci = np.clip((x / sw).astype(np.int32), 0, nc - 1)
    ri = np.clip((y / sh).astype(np.int32), 0, nr - 1)
    PAL = np.array([(0.72, 0.05, 0.08), (0.04, 0.36, 0.15), (0.96, 0.93, 0.85), (0.42, 0.22, 0.08)], np.float32)
    base = PAL[P[ri, ci]]
    fxs = x / sw - ci
    fys = y / sh - ri
    xl, xr = 0.12 + 0.36 * fys, 0.88 - 0.36 * fys
    leg = np.clip(np.maximum(1 - ((fxs - xl) / 0.24) ** 2, 1 - ((fxs - xr) / 0.24) ** 2), 0, 1)
    ply = 0.92 + 0.08 * np.sin((fys * 3.0 + np.where(fxs < 0.5, fxs, -fxs) * 2.0) * 2 * np.pi)
    fuzz = noise(W, H, 4001, H / sh * 2.2, 2)
    shade = (0.42 + 0.68 * leg ** 0.55) * ply * (0.9 + 0.2 * fuzz)
    c = base * shade[..., None]
    halo = blurf(np.clip(base, 0, 1).mean(-1), sh * 0.25)
    c = c * (0.92 + 0.12 * halo)[..., None]
    vv = np.clip(v, 0, 1)
    c = c * np.where(v <= 1, 0.84 + 0.22 * np.sin(vv * np.pi), 0.95)[..., None]
    return np.clip(c, 0, 1), 0.25, 0.0


def bear_parts(cx, cy, h, ang):
    """The ellipses of a gummy bear of height h (upright when ang == 0)."""
    parts = [(0, -0.30, 0.20, 0.18, 0), (-0.15, -0.44, 0.08, 0.08, 0), (0.15, -0.44, 0.08, 0.08, 0),
             (0, 0.07, 0.23, 0.27, 0), (-0.22, -0.04, 0.08, 0.14, 0.5), (0.22, -0.04, 0.08, 0.14, -0.5),
             (-0.14, 0.33, 0.115, 0.12, 0), (0.14, 0.33, 0.115, 0.12, 0)]
    ca, sa = math.cos(ang), math.sin(ang)
    return [ellpts(cx + ca * px * h - sa * py * h, cy + sa * px * h + ca * py * h, rx * h, ry * h, ang + a, 24)
            for px, py, rx, ry, a in parts]


def d_gummy(W, H, lay):
    """translucent cherry and lime gummy candy, sugar-crusted, with gummy bears set inside"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(4100)
    vv = np.clip(v, 0, 1)
    join = B + bh * 0.12 * np.sin(x / (bh * 0.5))
    red = y < join
    depth = lnoise(W, H, 4101, 2.5, 4)
    redc = ramp(depth, [(0, (0.40, 0.0, 0.04)), (0.5, (0.82, 0.03, 0.10)), (1, (1.0, 0.28, 0.25))])
    grnc = ramp(depth, [(0, (0.06, 0.26, 0.0)), (0.5, (0.28, 0.72, 0.04)), (1, (0.66, 0.96, 0.28))])
    c = np.where(red[..., None], redc * (0.55 + 0.55 * np.clip(np.sin(vv * np.pi), 0, 1) ** 0.7)[..., None], grnc * (0.8 + 0.25 * depth)[..., None])
    seam = np.abs(y - join) < bh * 0.03
    c = np.where(seam[..., None], solid(W, H, (1.0, 0.85, 0.6)), c)
    # bears inside
    G = Layer(W, H)
    in_red = [(255, 205, 30), (255, 120, 15), (245, 240, 225), (110, 215, 40)]
    in_grn = [(235, 25, 35), (255, 205, 30), (255, 120, 15), (245, 240, 225)]
    k = 0
    for f in (0.04, 0.17, 0.30, 0.44, 0.58, 0.72, 0.86, 0.97):
        cx = fx(lay, f)
        hh = max(at_d(lambda q: eh(lay, q), cx), bh * 0.7)
        cy = at_d(lay.top, cx) + hh * 0.5
        if hh < bh * 1.3:
            h = hh * 1.35
            ang = (math.pi / 2 if k % 2 else -math.pi / 2) + (rng.random() - 0.5) * 0.3
        else:
            h = hh * 0.82
            ang = (rng.random() - 0.5) * 0.7
        col = in_red[k % 4] + (255,)
        for part in bear_parts(cx, cy, h, ang):
            G.poly(part, col)
        k += 1
    yy = np.arange(H)[:, None]
    lowm = lay.mask & (yy > eb(lay, np.arange(W, dtype=np.float32))[None, :] + bh * 0.3)
    pts = np.argwhere(lowm[::8, ::8]) * 8
    placed = []
    for sx_, sy_, sr in spots(W, H, lay, 2):
        placed.append((sx_, sy_, sr * 1.7))
    rng.shuffle(pts)
    for py, px in pts[:400]:
        hb_ = max(bh * 1.25, H * 0.12) * (0.85 + 0.3 * rng.random())
        if all(math.hypot(px - qx, py - qy) > (hb_ + qh) * 0.36 for qx, qy, qh in placed):
            placed.append((px, py, hb_))
        if len(placed) > 14:
            break
    for i, (px, py, hb_) in enumerate(placed):
        col = in_grn[i % 4] + (255,)
        for part in bear_parts(px, py, hb_, (rng.random() - 0.5) * 1.2):
            G.poly(part, col)
    g = G.rgba()
    A = g[..., 3]
    inner = blurf(A, bh * 0.06)
    bearc = g[..., :3] * (0.40 + 0.85 * inner)[..., None]
    o = int(max(2, bh * 0.035))
    hl = np.clip(np.roll(np.roll(inner, o, 0), o, 1) - inner, 0, 1)
    bearc = bearc + (smooth(0.04, 0.2, hl) * 0.55)[..., None]
    c = shade_under(c, g, bh * 0.03, bh * 0.05, bh * 0.05, 0.35)
    c = mix(c, bearc * 0.88 + c * 0.22, A * 0.88)
    # tiny air bubbles, gloss, sugar
    Bb = Layer(W, H)
    for _ in range(45):
        px, py, r = rng.random() * W, rng.random() * H, bh * (0.02 + 0.04 * rng.random())
        Bb.circle(px, py, r, (255, 255, 255, 40), (255, 255, 255, 150), max(1.0, r * 0.2))
        Bb.circle(px - r * 0.35, py - r * 0.35, r * 0.25, (255, 255, 255, 220))
    c = over(c, Bb.rgba())
    c = c + ((np.exp(-((vv - 0.17) / 0.06) ** 2) * (v <= 1)) * 0.45)[..., None]
    c = c + ((np.exp(-((vv - 0.82) / 0.05) ** 2) * (v <= 1)) * 0.12)[..., None]
    S = Layer(W, H, ss=1)
    sz = max(H * 0.0042, 2.2)
    nS = int(W * H / (sz * sz * 9))
    P_ = rng.random((nS, 4))
    for px, py, a, b in P_:
        px, py = px * W, py * H
        r = sz * (0.6 + 0.8 * a)
        ca, sa = math.cos(b * 6.28) * r, math.sin(b * 6.28) * r
        S.d.polygon([(px + ca, py + sa), (px - sa, py + ca), (px - ca, py - sa), (px + sa, py - ca)], fill=(255, 250, 245, int(110 + 120 * a)))
    sg = S.rgba()
    c = over(c, sg, 0.8)
    c = add(c, sparkle(W, H, 70, 4102, H * 0.004), 0.8)
    return np.clip(c, 0, 1), 0.25, 0.03


def d_disco_ball(W, H, lay):
    """a mirror-ball finish: tiles throwing back pink, cyan and gold club lights, star glints"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(4200)
    t = float(np.clip(bh * 0.13, H * 0.017, H * 0.035))
    nr, ncol = int(H / t) + 2, int(W / t) + 4
    roff = rng.random(nr) * t
    ri = np.clip(np.floor(y / t).astype(np.int32), 0, nr - 1)
    xo = x + roff[ri]
    ci = np.clip(np.floor(xo / t).astype(np.int32), 0, ncol - 1)
    fxs, fys = xo / t - ci, y / t - ri
    J = rng.random((nr, ncol, 3)).astype(np.float32)
    jit = J[ri, ci]
    tcx = (ci + 0.5) * t - roff[ri]
    tcy = (ri + 0.5) * t
    vt = np.clip((tcy - T) / np.maximum(B - T, 1), -0.5, 1.5)
    u = tcx / W + (jit[..., 0] - 0.5) * 0.10
    w = tcy / H + (jit[..., 1] - 0.5) * 0.10 + 0.25 * (vt - 0.5) * (v <= 1)
    env = solid(W, H, (0.27, 0.28, 0.33)) + (0.22 * np.clip(1 - np.abs(w - 0.45) * 2.2, 0, 1))[..., None] * np.array([0.9, 0.95, 1.0], np.float32)
    # the last four light the rear top, which the first-person view looks down on (dark grey on the board)
    lights = [(0.12, 0.2, 0.09, (1.0, 0.15, 0.7)), (0.33, 0.55, 0.11, (0.1, 0.85, 1.0)), (0.55, 0.15, 0.08, (1.0, 0.75, 0.2)),
              (0.72, 0.5, 0.1, (0.65, 0.25, 1.0)), (0.9, 0.25, 0.09, (1.0, 0.2, 0.55)), (0.45, 0.85, 0.12, (1.0, 0.55, 0.1)),
              (0.85, 0.85, 0.1, (0.15, 0.9, 1.0)), (0.2, 0.8, 0.08, (0.7, 0.3, 1.0)), (0.62, 0.32, 0.035, (1, 1, 1)), (0.8, 0.12, 0.07, (1.0, 0.8, 0.3)),
              (0.27, 0.38, 0.03, (1, 1, 1)), (0.95, 0.6, 0.03, (1, 1, 1)),
              (0.97, 0.12, 0.08, (1.0, 0.25, 0.75)), (0.88, 0.04, 0.07, (0.15, 0.85, 1.0)), (0.77, 0.3, 0.06, (1.0, 0.8, 0.3)),
              (0.93, 0.42, 0.06, (0.7, 0.35, 1.0))]
    for lu, lw, lr, col in lights:
        g = np.exp(-(((u - lu) * 1.6) ** 2 + (w - lw) ** 2) / (lr * lr))
        env = env + g[..., None] * np.array(col, np.float32) * 1.15
    tile = env * (0.5 + 0.9 * jit[..., 2:3] ** 1.5) + 0.03
    tile = tile * (1.08 - 0.18 * fys)[..., None]
    gr = 0.08
    grout = (fxs < gr) | (fys < gr)
    bev = ((fxs < gr * 2.2) | (fys < gr * 2.2)) & ~grout
    tile = np.where(bev[..., None], tile * 1.35 + 0.06, tile)
    c = np.where(grout[..., None], solid(W, H, (0.015, 0.015, 0.02)), tile)
    vv = np.clip(v, 0, 1)
    c = c * np.where(v <= 1, 0.85 + 0.3 * np.sin(vv * np.pi), 0.9)[..., None]
    # light beams and star glints
    for bx0, sl, col in ((0.3, 0.5, (1.0, 0.2, 0.7)), (0.62, -0.4, (0.2, 0.8, 1.0)), (0.86, 0.3, (1.0, 0.8, 0.3))):
        d = (x - (lay.x0 + span * bx0) - (y - H * 0.5) * sl) / (span * 0.035)
        c = c + (np.exp(-d * d) * 0.10)[..., None] * np.array(col, np.float32)
    L = Layer(W, H)
    for f, vq, sz in ((0.12, 0.35, 0.45), (0.46, 0.3, 0.55), (0.76, 0.4, 0.6), (0.94, 0.3, 0.4), (0.86, 0.08, 0.3)):
        cx = fx(lay, f)
        hq = max(at_d(lambda q: eh(lay, q), cx), bh)
        star4(L, cx, at_d(lay.top, cx) + hq * vq, hq * sz, (255, 255, 255, 255))
    for sx_, sy_, sr in spots(W, H, lay, 1):
        star4(L, sx_, sy_, sr * 0.7, (255, 255, 255, 255))
    g = L.rgba()
    c = c + glow_of(g, bh * 0.08, 1.4) * np.array([1.0, 0.85, 1.0]) + glow_of(g, bh * 0.025, 1.0)
    c = over(c, g)
    return np.clip(c, 0, 1), 0.3, 0.1


def ribbon(L, pts, widths, dark, base, light):
    poly, nrm = outline_of(pts, widths)
    L.poly(poly, dark)
    inner, _ = outline_of(pts, [w_ * 0.7 for w_ in widths])
    L.poly(inner, base)
    hp = [(px - n_[0] * w_ * 0.18, py - abs(n_[1]) * w_ * 0.18) for (px, py), n_, w_ in zip(pts, nrm, widths)]
    L.line(hp, light, max(1.0, float(np.median(widths)) * 0.18))


def d_bubblegum(W, H, lay):
    """bubblegum pink: a huge glossy gum bubble, stretched gum strands and a big POP"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(4300)
    tone = lnoise(W, H, 4301, 1.5, 3)
    c = ramp(tone, [(0, (0.93, 0.34, 0.60)), (1, (1.0, 0.50, 0.73))])
    sw = lnoise(W, H, 4304, 1.2, 4, sx=0.35, sy=1.0) + 0.6 * lnoise(W, H, 4302, 2.0, 3)
    swirl = np.abs((sw * 6) % 1.0 - 0.5)
    c = mix(c, solid(W, H, (1.0, 0.74, 0.87)), smooth(0.07, 0.015, swirl) * 0.5)
    c = mix(c, solid(W, H, (0.80, 0.20, 0.48)), smooth(0.43, 0.49, swirl) * 0.3)
    _, lit = lbump(W, H, 4305, 2.0, 3)
    c = c * (0.9 + 0.16 * np.clip(lit, 0, 1.3))[..., None]
    streak = lnoise(W, H, 4303, 6.0, 3, sx=0.08, sy=1.0)
    c = np.where((v > 1)[..., None], c * (0.8 + 0.3 * streak)[..., None] * np.array([0.95, 0.9, 0.95]), c)
    vv = np.clip(v, 0, 1)
    c = c * np.where(v <= 1, 0.82 + 0.25 * np.sin(vv * np.pi), 1.0)[..., None]
    c = c + ((np.exp(-((vv - 0.2) / 0.05) ** 2) * 0.38 + np.exp(-((vv - 0.32) / 0.012) ** 2) * 0.25) * (v <= 1))[..., None]
    # popped splat below
    (sx1, sy1, sr1), = spots(W, H, lay, 1)
    SP = Layer(W, H)
    sp_ = blob(sx1, sy1, sr1 * 0.85, rng, 40, 0.18)
    SP.poly(sp_, (205, 45, 120, 255))
    SP.poly(blob(sx1, sy1, sr1 * 0.72, rng, 40, 0.2), (255, 120, 185, 255))
    for k in range(9):
        a = k / 9 * 6.283 + rng.random() * 0.4
        r1 = sr1 * (0.75 + 0.35 * rng.random())
        SP.poly([(sx1 + math.cos(a - 0.12) * sr1 * 0.6, sy1 + math.sin(a - 0.12) * sr1 * 0.6), (sx1 + math.cos(a) * r1 * 1.15, sy1 + math.sin(a) * r1 * 1.15),
                 (sx1 + math.cos(a + 0.12) * sr1 * 0.6, sy1 + math.sin(a + 0.12) * sr1 * 0.6)], (240, 95, 165, 255), (190, 40, 110, 255), 1.5)
        SP.line([(sx1 + math.cos(a) * sr1 * 0.15, sy1 + math.sin(a) * sr1 * 0.15), (sx1 + math.cos(a) * sr1 * 0.6, sy1 + math.sin(a) * sr1 * 0.6)], (200, 50, 120, 200), sr1 * 0.03)
    SP.ellipse((sx1 - sr1 * 0.45, sy1 - sr1 * 0.42, sx1 - sr1 * 0.1, sy1 - sr1 * 0.25), (255, 220, 235, 200))
    spr = SP.rgba()
    c = shade_under(c, spr, sr1 * 0.04, sr1 * 0.06, sr1 * 0.05, 0.4)
    c = over(c, spr)
    # the bubble
    bx = fx(lay, 0.74)
    hb = max(at_d(lambda q: eh(lay, q), bx), bh)
    by = at_d(lay.top, bx) + hb * 0.52
    R = min(hb * 0.62, span * 0.16)
    d = np.hypot(x - bx, y - by) / R
    c = c * (1 - 0.5 * smooth(1.3, 0.9, np.hypot(x - bx - R * 0.1, y - by - R * 0.16) / R) * (d > 0.97))[..., None]
    vol = np.clip(0.72 + 0.42 * ((bx - x) * 0.7 + (by - y)) / (R * 1.4), 0.42, 1.15)
    film = np.clip(0.72 + 0.28 * d ** 4, 0, 1)
    bub = mix(c, solid(W, H, (1.0, 0.40, 0.68)) * vol[..., None], film)
    bub = mix(bub, solid(W, H, (0.60, 0.04, 0.30)), smooth(0.93, 0.985, d))
    ang = np.arctan2(y - by, x - bx)
    rim = smooth(0.05, 0.0, np.abs(d - 0.87)) * smooth(0.8, 0.2, np.abs(ang + 2.3))
    wxr = np.abs(x - (bx - R * 0.42)) / (R * 0.2)
    wyr = np.abs(y - (by - R * 0.40)) / (R * 0.15)
    pane = smooth(1.0, 0.88, wxr) * smooth(1.0, 0.88, wyr) * smooth(0.07, 0.15, wxr) * smooth(0.08, 0.18, wyr)
    spot = smooth(0.09, 0.05, np.hypot(x - bx - R * 0.46, y - by - R * 0.42) / R)
    bub = bub + (pane * 0.8 + rim * 0.55 + spot * 0.8)[..., None]
    c = np.where((d < 1)[..., None], bub, c)
    # gum wad where it sticks, strands to the muzzle and drips
    S = Layer(W, H)
    wx, wy = bx - R * 0.92, by + R * 0.3
    DK, BS, LT = (165, 18, 88, 255), (255, 100, 170, 255), (255, 225, 238, 235)
    for k, (f, vq, sag) in enumerate(((0.05, 0.45, 0.25), (0.17, 0.7, 0.35), (0.36, 0.35, 0.2))):
        ex = fx(lay, f)
        he = max(at_d(lambda q: eh(lay, q), ex), bh * 0.7)
        ey = at_d(lay.top, ex) + he * vq
        mx_ = (ex + wx) / 2
        my_ = max(ey, wy) + min(bh, H * 0.12) * sag
        pts = bezier([(wx, wy + (k - 1.5) * R * 0.12), (mx_, my_), (ex, ey)], 40)
        n_ = len(pts)
        wd = [bh * (0.05 + 0.13 * abs(i / (n_ - 1) - 0.5) ** 1.5 * 2.8) for i in range(n_)]
        ribbon(S, pts, wd, DK, BS, LT)
        S.circle(ex, ey, bh * 0.1, BS, DK, bh * 0.02)
    for f, ln in ((0.22, 0.9), (0.5, 1.3), (0.88, 0.7)):
        ex = fx(lay, f)
        ey = at_d(lambda q: eb(lay, q), ex) - bh * 0.05
        pts = bezier([(ex, ey), (ex + bh * 0.05, ey + bh * ln * 0.5), (ex - bh * 0.03, ey + bh * ln)], 15)
        ribbon(S, pts, [bh * (0.1 - 0.06 * i / (len(pts) - 1)) for i in range(len(pts))], DK, BS, LT)
        S.circle(pts[-1][0], pts[-1][1], bh * 0.075, BS, DK, bh * 0.02)
        S.circle(pts[-1][0] - bh * 0.025, pts[-1][1] - bh * 0.025, bh * 0.022, LT)
    # the first-person view looks down on the rear top, which the board left plain pink: a strand stretched from the
    # bubble over the top to the butt, a second one lower down, and a small fresh bubble between them
    for (f0, v0), (f1, v1), sag in (((0.0, -0.6), (0.995, 0.1), 0.0), ((0.0, 0.3), (0.99, 0.62), 0.25)):
        sx0, sy0 = bx + R * 0.8, by + R * v0
        ex = fx(lay, f1)
        he = max(at_d(lambda q: eh(lay, q), ex), bh * 0.7)
        ey = at_d(lay.top, ex) + he * v1
        mx_ = (sx0 + ex) / 2
        my_ = min(sy0, ey) + he * sag
        pts = bezier([(sx0, sy0), (mx_, my_), (ex, ey)], 30)
        n_ = len(pts)
        ribbon(S, pts, [bh * (0.045 + 0.1 * abs(i / (n_ - 1) - 0.5) ** 1.5 * 2.8) for i in range(n_)], DK, BS, LT)
        S.circle(ex, ey, bh * 0.08, BS, DK, bh * 0.02)
    sbx = fx(lay, 0.93)
    sbr = max(at_d(lambda q: eh(lay, q), sbx), bh) * 0.17
    sby = at_d(lay.top, sbx) + sbr * 1.9
    S.circle(sbx, sby, sbr, (255, 110, 180, 245), DK, bh * 0.018)
    S.circle(sbx - sbr * 0.38, sby - sbr * 0.38, sbr * 0.24, LT)
    S.circle(sbx + sbr * 0.45, sby + sbr * 0.4, sbr * 0.1, (255, 255, 255, 220))
    S.poly(blob(wx, wy, R * 0.32, rng, 30, 0.25, 1.2, 0.9), DK)
    S.poly(blob(wx, wy, R * 0.27, rng, 30, 0.25, 1.2, 0.9), BS)
    S.ellipse((wx - R * 0.2, wy - R * 0.2, wx - R * 0.02, wy - R * 0.1), LT)
    s = S.rgba()
    c = shade_under(c, s, bh * 0.03, bh * 0.05, bh * 0.04, 0.4)
    c = over(c, s)
    # POP!
    L = Layer(W, H)
    px = fx(lay, 0.3)
    hp = max(at_d(lambda q: eh(lay, q), px), bh)
    py = at_d(lay.top, px) + hp * 0.48
    for k in range(10):
        a = k / 10 * 6.283 + 0.3
        L.line([(px + math.cos(a) * hp * 0.62 * 1.6, py + math.sin(a) * hp * 0.5), (px + math.cos(a) * hp * 0.85 * 1.6, py + math.sin(a) * hp * 0.68)],
               (255, 255, 255, 230), hp * 0.04)
    fit_paste(L, text_im("POP!", "SNAP____.TTF", 220, (110, 0, 55, 255), stroke=18, stroke_fill=(110, 0, 55, 255)), px + hp * 0.05, py + hp * 0.07,
              span * 0.3, hp * 0.9, ang=7)
    fit_paste(L, text_im("POP!", "SNAP____.TTF", 220, (255, 255, 255, 255), stroke=18, stroke_fill=(215, 20, 120, 255)), px, py, span * 0.3, hp * 0.9, ang=7)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.25, 0.03


def d_wildstyle(W, H, lay):
    """a wildstyle FATBOSS piece along the gun: 3D block, arrows, drips, a throw-up and tags below"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(4400)
    c = ramp(lnoise(W, H, 4401, 2.0, 3), [(0, (0.04, 0.035, 0.09)), (1, (0.12, 0.09, 0.20))])
    for k, col in enumerate([(0.95, 0.10, 0.60), (0.10, 0.75, 0.95), (0.55, 0.15, 0.95), (0.2, 0.9, 0.4)]):
        m = smooth(0.55, 0.78, lnoise(W, H, 4410 + k, 1.8, 3))
        c = c + m[..., None] * np.array(col, np.float32) * 0.42
    c = c * (0.92 + 0.12 * noise(W, H, 4402, 220.0, 1))[..., None]
    # letters
    word = "FATBOSS"
    Mk = Image.new("L", (W, H), 0)
    ar = []
    xa, xb = deep_run(lay)
    xa, xb = max(lay.x0, xa - span * 0.03), min(lay.x1, xb + span * 0.01)
    emax = float(envelope(lay)[int(lay.x0):int(lay.x1) + 1].max())
    lw = (xb - xa) * 0.96 / len(word) * 1.25
    for i, ch in enumerate(word):
        cx = xa + (xb - xa) * (0.02 + 0.96 * (i + 0.5) / len(word))
        hh = float(np.clip(at_d(lambda q: eh(lay, q), cx), emax * 0.8, emax))
        lh = hh * 0.98
        cy = at_d(lay.top, cx) + hh * 0.5 + (rng.random() - 0.5) * hh * 0.08
        im = text_im(ch, "SHOWG.TTF", 240, (255, 255, 255, 255)).split()[3]
        im = im.resize((max(1, int(min(lw, lh * 1.1))), max(1, int(lh))), Image.LANCZOS)
        s = 0.22
        im = im.transform((int(im.width + s * im.height), im.height), Image.AFFINE, (1, s, -s * im.height, 0, 1, 0), Image.BICUBIC)
        im = im.rotate((rng.random() - 0.5) * 16, Image.BICUBIC, expand=True)
        Mk.paste(255, (int(cx - im.width / 2), int(cy - im.height / 2)), im)
        ar.append((cx, cy, lh, min(lw, lh * 1.1)))
    D = ImageDraw.Draw(Mk)
    for i, (cx, cy, lh, lw_) in enumerate(ar):
        if i in (0, 2, 4, 6):
            sgn = -1 if i % 4 == 0 else 1
            bx_, by_ = cx + lw_ * 0.35, cy + sgn * lh * 0.42
            a = -0.5 if sgn < 0 else 0.45
            ln, wd = lh * 0.45, lh * 0.1
            ex, ey = bx_ + math.cos(a) * ln, by_ + math.sin(a) * ln
            nx_, ny_ = -math.sin(a), math.cos(a)
            D.polygon([(bx_ + nx_ * wd / 2, by_ + ny_ * wd / 2), (ex + nx_ * wd / 2, ey + ny_ * wd / 2), (ex + nx_ * wd * 1.6, ey + ny_ * wd * 1.6),
                       (ex + math.cos(a) * wd * 2.2, ey + math.sin(a) * wd * 2.2), (ex - nx_ * wd * 1.6, ey - ny_ * wd * 1.6),
                       (ex - nx_ * wd / 2, ey - ny_ * wd / 2), (bx_ - nx_ * wd / 2, by_ - ny_ * wd / 2)], fill=255)
    M = np.asarray(Mk, np.float32) / 255.0
    o = bh * 0.11
    E = np.zeros_like(M)
    for k in range(1, 9):
        E = np.maximum(E, np.roll(np.roll(M, int(o * k / 8 * 0.8), 1), int(o * k / 8), 0))
    U = np.maximum(M, E)
    out = smooth(0.05, 0.25, blurf(U, bh * 0.035))
    cloud = smooth(0.02, 0.1, blurf(U, bh * 0.12))
    cloudo = smooth(0.005, 0.03, blurf(U, bh * 0.13))
    c = mix(c, solid(W, H, (0.03, 0.02, 0.05)), cloudo)
    cl = ramp(np.clip((y - T) / np.maximum(B - T, 1), 0, 1), [(0, (0.95, 0.97, 1.0)), (1, (0.55, 0.85, 1.0))])
    c = mix(c, cl, cloud)
    c = mix(c, solid(W, H, (0.03, 0.02, 0.05)), out)
    blk = ramp(np.clip((y - T) / np.maximum(B - T, 1), 0, 1.2), [(0, (0.45, 0.10, 0.65)), (1, (0.12, 0.02, 0.25))])
    c = mix(c, blk, E * (1 - M))
    fillc = ramp(np.clip((y - T) / np.maximum(B - T, 1) + 0.1 * np.sin(x / (bh * 0.9)), 0, 1),
                 [(0, (1.0, 0.95, 0.25)), (0.4, (1.0, 0.55, 0.05)), (0.75, (1.0, 0.15, 0.45)), (1, (0.7, 0.1, 0.8))])
    shine = smooth(0.0, 0.05, ((x - y * 0.9) / (bh * 1.4)) % 1.0) * smooth(0.13, 0.08, ((x - y * 0.9) / (bh * 1.4)) % 1.0)
    fillc = fillc + (shine * 0.45)[..., None]
    c = mix(c, fillc, M)
    e1 = np.clip(M - np.roll(np.roll(M, int(max(2, bh * 0.025)), 0), int(max(2, bh * 0.025)), 1), 0, 1)
    c = mix(c, solid(W, H, (1, 1, 1)), e1 * 0.9)
    # drips, throw-up, crown, tags
    L = Layer(W, H)
    cl_bottom = np.array([np.nonzero(cloud[:, xx] > 0.5)[0].max() if (cloud[:, xx] > 0.5).any() else -1 for xx in range(0, W, 4)])
    for _ in range(26):
        i = int(rng.random() * len(cl_bottom))
        yb = cl_bottom[i]
        if yb < 0:
            continue
        xd = i * 4
        ln = bh * (0.2 + 0.9 * rng.random() ** 2)
        wd = bh * (0.025 + 0.025 * rng.random())
        col = (235, 245, 255, 255) if rng.random() < 0.6 else (255, 120, 20, 255)
        L.line([(xd, yb - 2), (xd, yb + ln)], col, wd)
        L.circle(xd, yb + ln, wd * 0.75, col)
    sp = spots(W, H, lay, 2)
    (tx, ty, tr) = sp[0]
    fb = text_im("FB", "SNAP____.TTF", 240, (255, 255, 255, 255))
    a_ = fb.split()[3]
    TU = Layer(W, H)
    big = Image.new("RGBA", a_.size, (0, 0, 0, 0))
    big.paste((20, 15, 25, 255), (0, 0), a_.filter(ImageFilter.MaxFilter(21)))
    big.paste((230, 30, 60, 255), (0, 0), a_.filter(ImageFilter.MaxFilter(13)))
    chrome = Image.fromarray((ramp(np.linspace(0, 1, a_.height)[:, None].repeat(a_.width, 1),
                                   [(0, (1, 1, 1)), (0.45, (0.75, 0.78, 0.85)), (0.5, (0.35, 0.38, 0.45)), (1, (0.85, 0.88, 0.95))]) * 255).astype(np.uint8))
    big.paste(chrome, (0, 0), a_)
    fit_paste(TU, big, tx, ty, tr * 1.75, tr * 1.5, ang=8)
    if len(sp) > 1:
        (kx, ky, kr) = sp[1]
        s2 = kr * 0.8
        crown = [(kx - s2, ky + s2 * 0.4), (kx - s2, ky - s2 * 0.3), (kx - s2 * 0.5, ky + s2 * 0.05), (kx, ky - s2 * 0.6), (kx + s2 * 0.5, ky + s2 * 0.05),
                 (kx + s2, ky - s2 * 0.3), (kx + s2, ky + s2 * 0.4)]
        TU.poly(crown, (255, 210, 0, 255), (20, 15, 25, 255), s2 * 0.12)
        for px_, py_ in crown[1:6:2]:
            TU.circle(px_, py_ - s2 * 0.12, s2 * 0.12, (255, 210, 0, 255), (20, 15, 25, 255), s2 * 0.08)
    yy = np.arange(H)[:, None]
    lowm = lay.mask & (yy > eb(lay, np.arange(W, dtype=np.float32))[None, :] + bh * 0.2)
    # the tags stay off the piece and its drips (on the 4k canvas one landed on the letters)
    lowm &= blurf(cloudo, bh * 0.25) < 0.02
    cand = np.argwhere(lowm[::10, ::10]) * 10
    rng.shuffle(cand)
    # and off the throw-up, the crown and each other
    tu = min(bh, H * 0.13)
    picked = []
    for py_, px_ in cand:
        if all(math.hypot(px_ - qx, py_ - qy) > r_ * 1.05 + tu * 0.6 for qx, qy, r_ in sp) and                 all(abs(px_ - qx) > tu * 1.6 or abs(py_ - qy) > tu * 0.7 for qy, qx in picked):
            picked.append((py_, px_))
        if len(picked) == 7:
            break
    for (py_, px_), col in zip(picked, [(15, 12, 20), (255, 255, 255), (15, 12, 20), (120, 255, 60), (15, 12, 20), (255, 255, 255), (255, 60, 200)]):
        tw, th_ = tu * (0.9 + 0.6 * rng.random()), tu * (0.35 + 0.2 * rng.random())
        pts = []
        n_ = 7 + int(rng.random() * 4)
        for j in range(n_ * 6):
            tt = j / 6
            pts.append((px_ - tw / 2 + tw * tt / n_ + math.cos(tt * 6.283) * tw / n_ * 0.45,
                        py_ - math.sin(tt * 6.283 + rng.random() * 0.4) * th_ * (0.35 + 0.65 * ((j // 6) % 3 == 0))))
        TU.line(pts, col + (235,), tu * 0.035)
        TU.line([(px_ - tw * 0.55, py_ + th_ * 0.35), (px_ + tw * 0.6, py_ + th_ * 0.2)], col + (235,), tu * 0.03)
    c = over(c, TU.rgba())
    lr = L.rgba()
    c = over(c, lr)
    over_s = (noise(W, H, 4420, 300.0, 1) > 0.78) & (cloudo < 0.5) & (blurf(U, bh * 0.25) > 0.02)
    c = np.where(over_s[..., None], c * 0.4 + np.array([0.6, 0.6, 0.62], np.float32), c)
    G = Layer(W, H)
    for i in (0, 3, 5):
        cx, cy, lh, lw_ = ar[i]
        star4(G, cx - lw_ * 0.3, cy - lh * 0.35, lh * 0.35, (255, 255, 255, 255), 0.09)
    g = G.rgba()
    c = c + glow_of(g, bh * 0.05, 0.8)
    c = over(c, g)
    return np.clip(c, 0, 1), 0.3, 0.05


def gem_heart(L, cx, cy, r, rng):
    def heart(rr):
        return [(cx + 16 * math.sin(t) ** 3 / 17 * rr, cy - (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 17 * rr)
                for t in np.linspace(0, 2 * math.pi, 64, endpoint=False)]
    L.poly(heart(r * 1.22), (120, 75, 10, 255))
    L.poly(heart(r * 1.15), (235, 180, 60, 255))
    L.poly(heart(r * 1.04), (255, 235, 150, 255))
    L.poly(heart(r * 1.0), (150, 10, 80, 255))
    out = heart(r * 0.98)
    ctr = (cx, cy - r * 0.05)
    shades = [(255, 70, 170), (220, 20, 120), (255, 130, 200), (190, 10, 100), (255, 90, 180), (235, 40, 140)]
    m = len(out)
    for k in range(16):
        a, b = out[k * m // 16], out[((k + 1) * m // 16) % m]
        L.poly([ctr, a, b], shades[k % 6] + (255,))
    L.poly(heart(r * 0.5), (255, 150, 210, 255))
    L.poly([(cx - r * 0.38, cy - r * 0.45), (cx - r * 0.12, cy - r * 0.62), (cx - r * 0.2, cy - r * 0.3)], (255, 240, 250, 230))
    for k in range(22):
        t = k / 22 * 2 * math.pi
        px, py = cx + 16 * math.sin(t) ** 3 / 17 * r * 1.38, cy - (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) / 17 * r * 1.38
        rhinestone(L, px, py, r * 0.085)


def rhinestone(L, cx, cy, r):
    L.circle(cx, cy, r * 1.25, (150, 105, 25, 255))
    L.circle(cx, cy, r * 1.08, (250, 210, 110, 255))
    L.circle(cx, cy, r, (235, 225, 245, 255))
    L.circle(cx + r * 0.15, cy + r * 0.15, r * 0.7, (170, 160, 200, 255))
    L.circle(cx - r * 0.1, cy - r * 0.1, r * 0.45, (255, 255, 255, 255))
    L.line([(cx - r * 0.8, cy), (cx + r * 0.8, cy)], (255, 255, 255, 200), max(1.0, r * 0.12))
    L.line([(cx, cy - r * 0.8), (cx, cy + r * 0.8)], (255, 255, 255, 200), max(1.0, r * 0.12))


def d_leopard_diva(W, H, lay):
    """hot-pink leopard print with gold piping, rhinestones, a jewelled heart and a gold chain"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(4500)
    fur = lnoise(W, H, 4501, 60.0, 2, sx=0.25, sy=1.0, div=2)
    c = ramp(lnoise(W, H, 4502, 2.0, 3), [(0, (0.92, 0.12, 0.52)), (1, (1.0, 0.36, 0.70))]) * (0.9 + 0.16 * fur)[..., None]
    c = np.where((v > 1)[..., None], c * np.array([0.82, 0.75, 0.85], np.float32), c)
    L = Layer(W, H)
    g = max(bh * 0.72, H * 0.085)
    for j in range(int(H / g) + 2):
        for i in range(int(W / g) + 2):
            cx = (i + 0.5 * (j % 2) + (rng.random() - 0.5) * 0.5) * g
            cy = (j + (rng.random() - 0.5) * 0.5) * g
            R = g * (0.30 + 0.08 * rng.random())
            ang = rng.random() * 6.28
            L.poly(blob(cx, cy, R * 0.72, rng, 18, 0.2, 1.15, 0.9, ang), (200, 15, 105, 255))
            nsp = 4 + int(rng.random() * 3)
            a0 = rng.random() * 6.28
            for k in range(nsp):
                if rng.random() < 0.12:
                    continue
                a = a0 + k / nsp * 6.283 + (rng.random() - 0.5) * 0.3
                px, py = cx + math.cos(a) * R * 1.05, cy + math.sin(a) * R * 0.95
                L.poly(blob(px, py, R * 0.5, rng, 14, 0.25, 1.0, 0.42, a + math.pi / 2), (30, 5, 25, 255))
            if rng.random() < 0.5:
                px, py = cx + g * 0.5, cy + g * 0.45
                L.poly(blob(px, py, R * 0.22, rng, 12, 0.3), (30, 5, 25, 255))
    c = over(c, L.rgba())
    # gold piping along the band with rhinestones
    G = Layer(W, H)
    xs = np.arange(-8, W + 8, 4.0)
    tw = max(bh * 0.075, H * 0.009)
    for yl in (lay.top(xs) + tw * 1.1, eb(lay, xs) - tw * 1.1):
        G.line(list(zip(xs, yl + tw * 0.1)), (110, 70, 10, 255), tw * 1.25)
        G.line(list(zip(xs, yl)), (230, 175, 55, 255), tw * 0.85)
        G.line(list(zip(xs, yl - tw * 0.22)), (255, 238, 160, 255), tw * 0.28)
    xr = lay.x0 + tw
    while xr < lay.x1:
        rhinestone(G, xr, at_d(lambda q: eb(lay, q), xr) - tw * 1.1, tw * 0.62)
        xr += tw * 2.6
    # gold chain with a gem drop below the band
    sp = spots(W, H, lay, 2)
    (sx1, sy1, sr1) = sp[0]
    ax_, bx_ = fx(lay, 0.3), fx(lay, 0.98)
    ay_, by_ = at_d(lambda q: eb(lay, q), ax_) + bh * 0.25, at_d(lambda q: eb(lay, q), bx_) + bh * 0.25
    path = bezier([(ax_, ay_), (sx1, sy1 + sr1 * 0.2), (bx_, by_)], 120)
    cl = max(bh * 0.16, H * 0.018)
    acc, last = 0.0, path[0]
    k = 0
    for p in path[1:]:
        acc += math.hypot(p[0] - last[0], p[1] - last[1])
        if acc >= cl * 0.8:
            a = math.atan2(p[1] - last[1], p[0] - last[0])
            if k % 2 == 0:
                G.poly(ellpts(p[0], p[1], cl * 0.55, cl * 0.33, a, 20), None, (110, 70, 10, 255), cl * 0.22)
                G.poly(ellpts(p[0], p[1], cl * 0.55, cl * 0.33, a, 20), None, (240, 190, 70, 255), cl * 0.13)
            else:
                G.line([(p[0] - math.cos(a) * cl * 0.5, p[1] - math.sin(a) * cl * 0.5), (p[0] + math.cos(a) * cl * 0.5, p[1] + math.sin(a) * cl * 0.5)],
                       (110, 70, 10, 255), cl * 0.26)
                G.line([(p[0] - math.cos(a) * cl * 0.45, p[1] - math.sin(a) * cl * 0.45), (p[0] + math.cos(a) * cl * 0.45, p[1] + math.sin(a) * cl * 0.45)],
                       (255, 225, 130, 255), cl * 0.12)
            acc, k = 0.0, k + 1
        last = p
    mid = path[len(path) // 2]
    gem_heart(G, mid[0], mid[1] + sr1 * 0.45, sr1 * 0.42, rng)
    # the big jewelled heart brooch
    hx = fx(lay, 0.74)
    hh = max(at_d(lambda q: eh(lay, q), hx), bh)
    gem_heart(G, hx, at_d(lay.top, hx) + hh * 0.5, hh * 0.33, rng)
    gg = G.rgba()
    c = shade_under(c, gg, bh * 0.03, bh * 0.05, bh * 0.04, 0.5)
    c = over(c, gg)
    c = add(c, sparkle(W, H, 60, 4503, H * 0.004), 0.9)
    return np.clip(c, 0, 1), 0.3, 0.08


def d_lava_lamp(W, H, lay):
    """a 70s lava lamp: glowing orange wax blobs rising and splitting in violet liquid"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(4600)
    liquid = ramp(y / H, [(0, (0.14, 0.02, 0.30)), (0.45, (0.30, 0.03, 0.45)), (1, (0.55, 0.03, 0.32))])
    liquid = liquid * (0.8 + 0.3 * lnoise(W, H, 4601, 2.0, 3))[..., None]
    blobs = []
    for f, vq, s_ in ((0.03, 0.55, 0.8), (0.13, 0.4, 1.0), (0.24, 0.62, 0.7), (0.33, 0.45, 1.15), (0.42, 0.3, 0.55), (0.5, 0.6, 1.2), (0.62, 0.42, 0.9),
                      (0.72, 0.55, 1.3), (0.8, 0.25, 0.6), (0.9, 0.5, 1.1), (0.99, 0.4, 0.8)):
        cx = fx(lay, f)
        hh = max(at_d(lambda q: eh(lay, q), cx), bh)
        r = min(hh, H * 0.17) * 0.33 * s_
        blobs.append((cx, at_d(lay.top, cx) + hh * vq, r * 1.05, r))
        if hh > r * 5:
            blobs.append((cx + span * 0.035, at_d(lay.top, cx) + hh * ((vq + 0.45) % 0.9 + 0.05), r * 0.8, r * 0.9))
        if rng.random() < 0.5:
            blobs.append((cx + r * 0.3, at_d(lay.top, cx) + hh * vq - r * 1.55, r * 0.45, r * 0.5))
    yb0 = float(np.median(eb(lay, np.arange(int(lay.x0), int(lay.x1)))))
    cell = max(bh * 1.4, H * 0.16)
    j = 0
    yy = yb0 + cell * 0.7
    while yy < H + cell:
        xx = -cell * 0.5 + (j % 2) * cell * 0.5
        while xx < W + cell:
            px, py = xx + (rng.random() - 0.5) * cell * 0.5, yy + (rng.random() - 0.5) * cell * 0.4
            r = cell * (0.18 + 0.16 * rng.random())
            blobs.append((px, py, r, r * 1.3))
            if rng.random() < 0.45:
                blobs.append((px + (rng.random() - 0.5) * r * 0.4, py - r * 1.9, r * 0.55, r * 0.75))
                blobs.append((px, py - r * 1.05, r * 0.28, r * 0.5))
            xx += cell
        yy += cell * 0.9
        j += 1
    blobs.append((W * 0.5, H * 1.08, W * 0.7, H * 0.1))
    F = np.zeros((H, W), np.float32)
    for cx, cy, rx, ry in blobs:
        x0_, x1_ = int(max(0, cx - 2 * rx)), int(min(W, cx + 2 * rx + 1))
        y0_, y1_ = int(max(0, cy - 2 * ry)), int(min(H, cy + 2 * ry + 1))
        if x1_ <= x0_ or y1_ <= y0_:
            continue
        q = ((x[y0_:y1_, x0_:x1_] - cx) / rx) ** 2 + ((y[y0_:y1_, x0_:x1_] - cy) / ry) ** 2
        F[y0_:y1_, x0_:x1_] += np.clip(1 - q / 4, 0, 1) ** 2
    th = 0.5625
    inside = smooth(th - 0.02, th + 0.02, F)
    t = np.clip((F - th) / 0.7, 0, 1)
    wax = ramp(t, [(0, (0.80, 0.10, 0.04)), (0.3, (1.0, 0.38, 0.04)), (0.75, (1.0, 0.66, 0.12)), (1, (1.0, 0.86, 0.38))])
    gy, gx = np.gradient(F)
    gm = np.hypot(gx, gy) + 1e-6
    ndl = (gx + gy) / (1.414 * gm)
    rim = smooth(0.25, 0.0, t) * smooth(0.3, 0.9, ndl)
    wax = wax + (rim * 0.5)[..., None] * np.array([1.0, 0.9, 0.6], np.float32)
    wax = wax * (0.75 + 0.3 * smooth(-0.6, 0.6, ndl) * (1 - t) + 0.25 * t)[..., None]
    glow = np.clip(F / th, 0, 1) ** 2 * (1 - inside)
    c = liquid + (glow * 0.45)[..., None] * np.array([1.0, 0.35, 0.1], np.float32)
    c = mix(c, wax, inside)
    vv = np.clip(v, 0, 1)
    band = (v <= 1)
    c = c * np.where(band, 0.78 + 0.3 * np.sin(vv * np.pi), 0.95)[..., None]
    c = c + ((np.exp(-((vv - 0.16) / 0.04) ** 2) * 0.35 + np.exp(-((vv - 0.3) / 0.012) ** 2) * 0.25) * band)[..., None]
    L = Layer(W, H)
    xs = np.arange(-8, W + 8, 4.0)
    tw = max(bh * 0.07, H * 0.008)
    for yl in (lay.top(xs) + tw * 0.8, eb(lay, xs) - tw * 0.8):
        L.line(list(zip(xs, yl)), (40, 40, 48, 255), tw * 1.3)
        L.line(list(zip(xs, yl)), (205, 210, 225, 255), tw * 0.9)
        L.line(list(zip(xs, yl - tw * 0.2)), (255, 255, 255, 255), tw * 0.25)
    c = over(c, L.rgba())
    return np.clip(c, 0, 1), 0.25, 0.06


def pine(L, bx, by, th, rng, dark, mid_, light):
    """A palette-knife pine: a trunk and stacked fan-brush dabs, lit from the left."""
    L.line([(bx, by), (bx, by - th * 0.98)], (45, 30, 20, 255), max(1.0, th * 0.025))
    n = 16
    for k in range(n):
        t = k / n
        yk = by - th * 0.12 - th * 0.86 * t
        w = th * 0.30 * (1 - t) ** 0.9 + th * 0.02
        for sgn in (-1, 1):
            j = (rng.random() - 0.5) * w * 0.25
            L.poly([(bx, yk - th * 0.035), (bx + sgn * (w + j), yk + th * 0.05 + rng.random() * th * 0.02), (bx + sgn * (w + j) * 0.6, yk + th * 0.06),
                    (bx, yk + th * 0.03)], dark)
        L.line([(bx - w * 0.85, yk + th * 0.035), (bx - w * 0.15, yk - th * 0.01)], mid_, max(1.0, th * 0.018))
        if rng.random() < 0.7:
            L.line([(bx - w * 0.7, yk + th * 0.03), (bx - w * 0.35, yk + th * 0.01)], light, max(1.0, th * 0.012))


def d_happy_trees(W, H, lay):
    """an oil-painted landscape: snowy peaks, a still lake, happy little pines, soft clouds"""
    x, y, T, B, v, span, bh = ctx(W, H, lay)
    rng = np.random.default_rng(4800)
    xs = np.arange(int(lay.x0), int(lay.x1) + 1)
    tm = float(np.median(lay.top(xs)))
    bm = float(np.median(eb(lay, xs)))
    hz = tm + 0.8 * (bm - tm)
    hs = hz - tm
    ys = np.clip((y - tm + hs * 0.3) / (hs * 1.3), 0, 1)
    c = ramp(ys, [(0, (0.16, 0.30, 0.60)), (0.45, (0.42, 0.60, 0.85)), (0.8, (0.85, 0.82, 0.80)), (1, (1.0, 0.85, 0.62))])
    cl = lnoise(W, H, 4801, 3.0, 5, sx=0.45, sy=1.0)
    cm = smooth(0.52, 0.66, cl) * smooth(hz - hs * 0.15, hz - hs * 0.6, y)
    c = mix(c, ramp(np.clip((y - tm) / hs, 0, 1) + (cl - 0.6), [(0, (1.0, 0.98, 0.95)), (1, (0.75, 0.70, 0.82))]), cm * 0.9)
    # far range: palette-knife peaks with snow
    pk = []
    px = lay.x0 - span * 0.05
    while px < W + span * 0.05:
        pk.append((px, 0.55 + 0.42 * rng.random(), span * (0.07 + 0.06 * rng.random())))
        px += span * (0.07 + 0.07 * rng.random())
    prof = np.zeros(W, np.float32)
    who = np.zeros(W, np.int32)
    cols = np.arange(W, dtype=np.float32)
    for i, (p, hgt, wdt) in enumerate(pk):
        pr = hgt * (1 - np.abs(cols - p) / wdt)
        better = pr > prof
        who = np.where(better, i, who)
        prof = np.maximum(prof, pr)
    rough = (noise(W, 8, 4802, 1.0, 4)[4] - 0.5) * 0.08
    prof = np.clip(prof + rough, 0, 1)
    ym = hz - hs * 0.95 * prof
    peaks = np.array([p for p, _, _ in pk], np.float32)
    ph = np.array([h_ for _, h_, _ in pk], np.float32)
    lit_side = x < peaks[who][None, :]
    mount = (y > ym[None, :]) & (y < hz)
    knife = lnoise(W, H, 4803, 9.0, 3, sx=0.6, sy=1.6, div=2)
    mc = np.where(lit_side[..., None], solid(W, H, (0.55, 0.56, 0.72)), solid(W, H, (0.27, 0.28, 0.46))) * (0.85 + 0.3 * knife)[..., None]
    snowline = ym[None, :] + hs * ph[who][None, :] * (0.28 + 0.12 * knife)
    snow = (y < snowline)
    sc = np.where(lit_side[..., None], solid(W, H, (0.98, 0.97, 1.0)), solid(W, H, (0.66, 0.70, 0.86))) * (0.92 + 0.1 * knife)[..., None]
    mc = np.where(snow[..., None], sc, mc)
    mist = smooth(hz - hs * 0.4, hz, y)
    mc = mix(mc, solid(W, H, (0.80, 0.80, 0.86)), mist * 0.7)
    c = np.where(mount[..., None], mc, c)
    hill = hz - hs * (0.18 + 0.1 * noise(W, 8, 4804, 3.0, 3)[4])
    hm = (y > hill[None, :]) & (y < hz)
    c = np.where(hm[..., None], solid(W, H, (0.16, 0.26, 0.28)) * (0.85 + 0.3 * knife)[..., None], c)
    # shoreline trees
    L = Layer(W, H)
    DK, MD, LT = (14, 40, 26, 255), (40, 85, 45, 255), (110, 150, 70, 255)
    xx = lay.x0
    while xx < lay.x1:
        th = hs * (0.25 + 0.35 * rng.random()) * (1.6 if (xx < lay.x0 + span * 0.12 or xx > lay.x0 + span * 0.8) else 1.0)
        pine(L, xx, hz + hs * 0.02, th, rng, DK, MD, LT)
        xx += hs * (0.06 + 0.12 * rng.random()) * (0.6 if (xx < lay.x0 + span * 0.12 or xx > lay.x0 + span * 0.8) else 1.6)
    tr = L.rgba()
    c = over(c, tr)
    # the lake reflects it all
    ry_ = np.clip(2 * hz - y + hs * 0.04, 0, H - 1)
    rip = (np.sin(y / max(bh * 0.05, 2.0)) * bh * 0.04 * smooth(hz, H, y)).astype(np.float32)
    rx_ = np.clip(x + rip, 0, W - 1)
    refl = c[ry_.astype(np.int32), rx_.astype(np.int32)]
    lake = mix(refl * 0.72 + np.array([0.02, 0.05, 0.1], np.float32), solid(W, H, (0.18, 0.30, 0.42)), smooth(hz, H, y) * 0.55)
    c = np.where((y >= hz)[..., None], lake, c)
    WL = Layer(W, H)
    for _ in range(60):
        wy = hz + (H - hz) * rng.random() ** 1.6
        wx = rng.random() * W
        wl = span * (0.03 + 0.1 * rng.random())
        WL.line([(wx, wy), (wx + wl, wy)], (235, 240, 250, int(90 + 110 * rng.random())), max(1.0, bh * 0.012))
    WL.line([(0, hz + hs * 0.02), (W, hz + hs * 0.02)], (245, 240, 230, 180), max(1.0, bh * 0.015))
    c = over(c, WL.rgba())
    # foreground bank and big happy trees at the back
    FG = Layer(W, H)
    gb = H - (H - hz) * 0.18
    pts = [(0, H)] + [(px_, gb + (H - hz) * 0.06 * math.sin(px_ / (span * 0.07)) - (H - hz) * 0.1 * (px_ > lay.x0 + span * 0.6))
                      for px_ in np.linspace(0, W, 40)] + [(W, H)]
    FG.poly(pts, (40, 60, 25, 255))
    for _ in range(140):
        gx_ = rng.random() * W
        gy_ = gb + (H - gb) * rng.random()
        FG.line([(gx_, gy_), (gx_ + bh * 0.2, gy_ - bh * 0.03)], (95 + int(80 * rng.random()), 120 + int(60 * rng.random()), 40, 200), max(1.0, bh * 0.02))
    for f, hf in ((0.84, 1.0), (0.93, 0.8), (0.76, 0.6), (0.47, 0.55)):
        bx = fx(lay, f)
        pine(FG, bx, H * 0.995, (H - tm) * 0.95 * hf, rng, (8, 26, 16, 255), (30, 70, 38, 255), (95, 140, 60, 255))
    fg = FG.rgba()
    c = shade_under(c, fg, bh * 0.04, 0, bh * 0.05, 0.3)
    c = over(c, fg)
    # oil paint: brush strokes, impasto, canvas weave
    strokes = lnoise(W, H, 4805, 14.0, 3, sx=0.12, sy=1.0, div=2)
    _, imp = lbump(W, H, 4806, 30.0, 2, div=2, sx=0.3, sy=1.0)
    weave = np.sin(x * 2 * np.pi / 3.2) * np.sin(y * 2 * np.pi / 3.2)
    c = c * (0.9 + 0.16 * strokes + 0.1 * (imp - 0.5) + 0.03 * weave)[..., None]
    return np.clip(c, 0, 1), 0.25, 0.0


# ---------------------------------------------------------------------------------------------- the themes
# key: (name, design, gloss 0..1, metal 0..1), the same as artskins.ART_THEMES. The key is a directory name in the pk3
# (models/fatboss/skins/<key>/, fbs/<key>/), kept short: the game refuses paths of 64 characters or more.
ART_THEMES_S9 = {
    "rabid_beast": ("Rabid Beast", d_rabid_beast, 0.45, 0.1),
    "golden_coil": ("Golden Coil", d_golden_coil, 0.8, 0.7),
    "empress": ("Empress", d_empress, 0.55, 0.3),
    "mecha_unit": ("Mecha Unit", d_mecha_unit, 0.55, 0.15),
    "red_vector": ("Red Vector", d_red_vector, 0.55, 0.15),
    "black_ice": ("Black Ice", d_black_ice, 0.65, 0.3),
    "corrupted": ("Corrupted", d_corrupted, 0.4, 0.1),
    "neon_tokyo": ("Neon Tokyo", d_neon_tokyo, 0.5, 0.15),
    "lost_space": ("Lost in Space", d_lost_in_space, 0.5, 0.15),
    "toxic_breach": ("Containment Breach", d_containment_breach, 0.5, 0.2),
    "nitro": ("Nitro", d_nitro, 0.7, 0.45),
    "quantum": ("Quantum", d_quantum, 0.55, 0.2),
    "bullet_rain": ("Bullet Rain", d_bullet_rain, 0.5, 0.35),
    "neon_riot": ("Neon Riot", d_neon_riot, 0.5, 0.1),
    "ti_burn": ("Titanium Burn", d_titanium_burn, 0.85, 0.8),
    "laminate": ("Black Laminate", d_black_laminate, 0.6, 0.1),
    "rust_coat": ("Rust Coat", d_rust_coat, 0.2, 0.15),
    "trench_art": ("Trench Art", d_trench_art, 0.85, 0.8),
    "butcher": ("Butcher", d_butcher, 0.75, 0.3),
    "pinstripe": ("Mafia Pinstripe", d_pinstripe, 0.3, 0.1),
    "hot_rod": ("Hot Rod", d_hot_rod, 0.75, 0.35),
    "wycinanki": ("Wycinanki", d_wycinanki, 0.25, 0.0),
    "amber": ("Baltic Amber", d_baltic_amber, 0.4, 0.7),
    "freehand": ("Freehand", d_freehand, 0.3, 0.0),
    "enigma": ("Enigma", d_enigma, 0.6, 0.35),
    "toy_blaster": ("Toy Blaster", d_toy_blaster, 0.55, 0.05),
    "cardboard": ("Cardboard Prop", d_cardboard, 0.05, 0.0),
    "comic_pow": ("Comic Pow", d_comic_pow, 0.35, 0.05),
    "ugly_sweater": ("Ugly Sweater", d_ugly_sweater, 0.05, 0.0),
    "gummy": ("Gummy", d_gummy, 0.7, 0.1),
    "disco_ball": ("Disco Ball", d_disco_ball, 0.8, 0.8),
    "bubblegum": ("Bubblegum", d_bubblegum, 0.7, 0.1),
    "wildstyle": ("Street Wildstyle", d_wildstyle, 0.4, 0.05),
    "leopard_diva": ("Leopard Diva", d_leopard_diva, 0.55, 0.2),
    "lava_lamp": ("Lava Lamp", d_lava_lamp, 0.65, 0.15),
    "happy_trees": ("Happy Little Trees", d_happy_trees, 0.2, 0.0),
}


def build(theme, tex, div=1):
    """The finished texture (float RGB, 4k size / div) of an s9 theme for one texture: the same as artskins.build, done
    in bands of rows and one colour at a time, so a 4k build needs about half the memory (the machine builds several at
    once)."""
    _name, design, _gloss, _metal = ART_THEMES_S9[theme]
    M = gs.get_maps(tex, div)
    CW = max(BOARD, CANVAS // div)
    CH = max(64, int(round(CW / M.aspect)))
    canvas, keep, wear = design(CW, CH, Layout(M, CW, CH))
    canvas = np.asarray(canvas, np.float32)
    shade, e = gs.stock_shade(tex, M.W, M.H)
    metal = np.array((0.72, 0.72, 0.74), np.float32)
    out = np.empty((M.H, M.W, 3), np.float32)
    for r0 in range(0, M.H, 256):
        r1 = min(M.H, r0 + 256)
        cx = np.clip(M.u[r0:r1] * (CW - 1), 0, CW - 1)
        cy = np.clip(M.v[r0:r1] * (CH - 1), 0, CH - 1)
        x0, y0 = np.floor(cx).astype(int), np.floor(cy).astype(int)
        x1, y1 = np.minimum(x0 + 1, CW - 1), np.minimum(y0 + 1, CH - 1)
        fx, fy = (cx - x0)[..., None], (cy - y0)[..., None]
        rgb = ((canvas[y0, x0] * (1 - fx) + canvas[y0, x1] * fx) * (1 - fy) + (canvas[y1, x0] * (1 - fx) + canvas[y1, x1] * fx) * fy)
        panel = 1 + keep * (np.clip(shade[r0:r1], 0.4, 1.2) - 1)
        o = rgb * panel[..., None]
        edge = np.clip((e[r0:r1] - 0.35) / 0.4, 0, 1) * wear
        o = gs.mix(o, np.broadcast_to(metal, o.shape), edge * 0.6)
        out[r0:r1] = np.clip(o, 0, 1)
    del canvas
    for k in range(3):      # the growth depends on the coverage only, so a colour at a time gives the same result
        out[..., k:k + 1] = gs.dilate(out[..., k:k + 1], M.cov)
    return np.clip(out, 0, 1)
