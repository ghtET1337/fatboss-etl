"""Stickers and the StatTrak display as decals (cgame b16): small models laid on the gun, like CS2's.

build_stickers.py (b13-b15) drew them as texture passes, which put a sticker on every face that shares its texels:
the MP 40's receiver tube repeats one strip of its texture round all its facets, and a flank's texture is often
the other flank's too. A decal is geometry instead, laid the way the game lays marks: the gun's own triangles
under a square, projected along its normal (so it wraps a round tube), lifted a hair off the gun, with the
sticker's own texture coordinates. The cgame draws it as one more entity with the gun's own origin, axis and frame
(every weapon model has one frame), so it sits on its one face only and follows the gun and its moving parts (a
pistol's slide is a part of the first-person model).

Where the places go is chosen in the game's own first-person view (the hands model moved by the weapon's
dynFov90, cg_fov 90, 4:3 so wider screens see more): every visible point of the gun is a candidate, each candidate
square is laid for real and drawn into that view with the hands in front, and it counts the pixels that show and
how square-on they are. The camera looks almost along the gun, so its flanks show edge-on (many pixels, all
squashed): a place is "in view" only when 85% of it shows, over 600 pixels of a 1440x1080 view, at least 0.22
square-on (the display, with its digits, 0.3). The display goes where it reads best, toward the muzzle; a gun
gets up to 4 (pistols) or 5 (SMGs) sticker spots, the normal view's first, then (to 4) the best of the inspect's
side view. The player picks the spot for each sticker.

The same places go on every model of the weapon: the silenced and akimbo variants (both guns; their models are
the base's moved, turned or scaled, found from the triangles textured alike) and the third-person model (another
mesh: the place carried over by the two outlines, then snapped onto the nearest face turned the same way).

Writes into fatboss/pk3 (the cgame pk3):
    models/fbd/<id>.md3              one decal (models that come out the same are written once)
    scripts/fatboss_decals.shader    fbd/s/<design>, fbd/plate, fbd/digit<N>, fbd/decal
    fatboss/stickers/<design>.png    the sticker art (FatBoss's make_stickers.py) put on a square, in place
    fatboss/stattrak/plate.png, 0.png .. 9.png
and src/cgame/cg_fatboss_decals.inc, fatboss/skins/sticker_spots.json (the website's picker).

    py fatboss/skins/build_decals.py --paks legacy_v2.86.0.pk3 pak2.pk3 pak1.pk3 pak0.pk3
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_skins as bs  # noqa: E402
import decal_art as art  # noqa: E402  (the display's images, the designs, the game camera)
import textskins as ts  # noqa: E402

PK3 = art.PK3
INC = os.path.join(bs.REPO, "src", "cgame", "cg_fatboss_decals.inc")
SPOTS_JSON = os.path.join(HERE, "sticker_spots.json")
GUNS, KNIVES = art.GUNS, art.KNIVES
PLACES = 4                  # stickers on one gun at most
SPOTS = 5                   # spots a gun has at most
SPOT_LIMIT = {"colt": 4, "luger": 4, "thompson": 5, "mp40": 5}      # like CS2: pistols 4, SMGs 5
DIGITS = art.DIGITS
MIN_SEEN = 0.85             # in the normal view: this much of it shows ...
MIN_AREA = 600              # ... over this many pixels of the 1440x1080 view (about 25x25) ...
MIN_SQUARE = 0.22           # ... not squashed flatter than this (see View.squash)
MIN_SQUARE_PLATE = 0.3      # the display's digits must read
PLATE_SIZES = (1.4, 1.25, 1.1, 0.95, 0.8, 0.7)     # display heights tried, game units
STICKER_SIZES = (2.6, 2.3, 2.0, 1.75, 1.5, 1.3, 1.15)
FORWARD_BONUS = 0.8
# the MP 40's display: on the top of the receiver tube just behind the barrel, on the side the player sees (the
# front 38% of the gun is the barrel, too thin for a display that reads); round, so it follows the tube (faces
# within ~37 degrees), every digit's cell on it
DISPLAY_FACING = 0.8
MP40_DISPLAY_ZONE = (0.4, 0.62)     # along the gun, 0 back .. 1 muzzle         # the display prefers the front of the gun: "just behind the barrel"
LIFT = 0.02                 # game units a decal sits off the gun (with polygonOffset: no fighting, no gap to see)
STRIDE = 9                  # candidate places: every STRIDE-th pixel of the gun in the view
INSPECT_PX = 40             # pixels per game unit of the inspect's side view
GAP = 0.25                  # game units between two places
# The StatTrak displays of b13-b15 (texture passes) stay where they were, now as decals: the players liked them and
# asked to move the MP 40's only (it sat on the magazine housing, seen edge-on). Hand space, from that build.
KEPT_DISPLAYS = {
    "colt": {"piece": 0, "center": (21.5649, -8.386, -13.5813), "normal": (-0.027, 0.9981, -0.0548),
             "right": (-0.9996, -0.0269, 0.0015), "up": (0.0, 0.0548, 0.9985), "w": 2.42, "h": 0.733},
    "luger": {"piece": 0, "center": (22.845, -7.5444, -12.946), "normal": (-0.0567, 0.9914, -0.1183),
              "right": (-0.9984, -0.0563, 0.0067), "up": (0.0, 0.1185, 0.9929), "w": 3.057, "h": 0.926},
    "thompson": {"piece": 0, "center": (15.7879, -6.7344, -7.3894), "normal": (0.0, 1.0, 0.0),
                 "right": (-1.0, 0.0, 0.0), "up": (0.0, 0.0, 1.0), "w": 4.125, "h": 1.25},
    "knife": {"piece": 1, "center": (17.6385, -4.6338, -5.9149), "normal": (-0.1818, 0.9115, 0.369),
              "right": (-0.8987, -0.0018, -0.4385), "up": (-0.399, -0.4113, 0.8195), "w": 3.821, "h": 1.158},
    "kabar": {"piece": 1, "center": (17.7358, -4.4333, -5.3287), "normal": (-0.2023, 0.9203, 0.3348),
              "right": (-0.8972, -0.0371, -0.44), "up": (-0.3926, -0.3894, 0.8332), "w": 3.954, "h": 1.198},
}


# ------------------------------------------------------------------ geometry

def clip_unit_square(poly):
    """Sutherland-Hodgman: poly [(a, b, w0, w1, w2)] clipped to 0 <= a, b <= 1 (keeps its winding)."""
    for axis, edge, keep in ((0, 0.0, 1), (0, 1.0, -1), (1, 0.0, 1), (1, 1.0, -1)):
        if not poly:
            break
        out = []
        for i in range(len(poly)):
            p, q = poly[i], poly[(i + 1) % len(poly)]
            ip, iq = keep * (p[axis] - edge) >= 0, keep * (q[axis] - edge) >= 0
            if ip:
                out.append(p)
            if ip != iq:
                t = (edge - p[axis]) / (q[axis] - p[axis])
                out.append(tuple(p[k] + (q[k] - p[k]) * t for k in range(5)))
        poly = out
    return poly


def lay(P, N, center, normal, right, up, w, h, need=0.95, depth=0.4, facing=0.8):
    """A decal the way the game lays marks: of the triangles P (outward normals N), those turned within ~37 degrees
    of normal and whose plane passes near center, projected along normal onto the w x h rectangle (right, up its
    axes) and cut to it; texture coordinates (a, b) run 0..1 along right and down up. None unless the triangles
    cover need of the rectangle (it would hang over an edge). Returns (verts, st, tris, normals)."""
    center, normal, right, up = (np.asarray(v, np.float64) for v in (center, normal, right, up))
    sel = N @ normal >= facing
    sel &= np.abs(np.einsum("ij,ij->i", center - P[:, 0], N)) <= depth
    idx = np.nonzero(sel)[0]
    if not len(idx):
        return None
    q = P[idx] - center
    a = q @ right / w + 0.5
    b = -(q @ up) / h + 0.5
    ov = (a.max(1) > 0) & (a.min(1) < 1) & (b.max(1) > 0) & (b.min(1) < 1)
    verts, st, tris, norms = [], [], [], []
    area = 0.0
    for j in np.nonzero(ov)[0]:
        i = idx[j]
        poly = clip_unit_square([(a[j, k], b[j, k], float(k == 0), float(k == 1), float(k == 2)) for k in range(3)])
        if len(poly) < 3:
            continue
        base = len(verts)
        for p in poly:
            verts.append(P[i, 0] * p[2] + P[i, 1] * p[3] + P[i, 2] * p[4] + N[i] * LIFT)
            st.append((p[0], p[1]))
            norms.append(N[i])
        for k in range(1, len(poly) - 1):
            tris.append((base, base + k, base + k + 1))
            area += abs((poly[k][0] - poly[0][0]) * (poly[k + 1][1] - poly[0][1])
                        - (poly[k][1] - poly[0][1]) * (poly[k + 1][0] - poly[0][0])) / 2
    if area < need:
        return None
    return np.array(verts), np.array(st), np.array(tris), np.array(norms)


def closest_on_triangle(p, a, b, c):
    """The point of the triangle abc closest to p (Ericson, Real-Time Collision Detection 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = ab @ ap, ac @ ap
    if d1 <= 0 and d2 <= 0:
        return a
    bp = p - b
    d3, d4 = ab @ bp, ac @ bp
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return a + ab * d1 / (d1 - d3)
    cp = p - c
    d5, d6 = ab @ cp, ac @ cp
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return a + ac * d2 / (d2 - d6)
    va = d3 * d6 - d5 * d4
    if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        return b + (c - b) * (d4 - d3) / ((d4 - d3) + (d5 - d6))
    den = va + vb + vc
    if abs(den) < 1e-12:
        return a
    return a + ab * vb / den + ac * vc / den


def lay_near(P, N, center, normal, right, up, w, h):
    """lay for a point carried over roughly (another mesh of the gun): onto the nearest face turned the same way,
    then moved (up to a rectangle's size) until it lies on the gun, smaller if it must."""
    facing = np.nonzero(N @ np.asarray(normal) >= 0.9)[0]
    if not len(facing):
        return None
    snaps = [closest_on_triangle(np.asarray(center, np.float64), *P[i]) for i in facing]
    center = snaps[int(np.argmin([np.linalg.norm(q - center) for q in snaps]))]
    steps = sorted(((i, j) for i in range(-4, 5) for j in range(-4, 5)), key=lambda v: v[0] ** 2 + v[1] ** 2)
    for shrink in (1.0, 0.8, 0.65, 0.5, 0.4):
        for i, j in steps:
            geo = lay(P, N, center + np.asarray(right) * (i * w / 4) + np.asarray(up) * (j * h / 4), normal, right, up,
                      shrink * w, shrink * h, need=0.85)
            if geo:
                return geo
    return None


def axes_for(n, F):
    """Right and up of a sticker on a face with outward normal n (hand space, x along the gun F, z up): along the
    gun on a side or the top (as textskins lays text), across it on a face that looks along the gun."""
    n = np.asarray(n, np.float64)
    Fp = F - (F @ n) * n
    if np.linalg.norm(Fp) > 0.5:
        Fp /= np.linalg.norm(Fp)
        if abs(n[2]) > 0.75:
            right = Fp                          # top or bottom: along the gun, away from the player
        else:
            right = Fp if np.cross(n, Fp)[2] > 0 else -Fp
    else:
        right = np.cross(np.array([0, 0, 1.0]), n)
        right = right / np.linalg.norm(right) if np.linalg.norm(right) > 1e-3 else np.array([0, -1.0, 0])
    return right, np.cross(n, right)


def kabsch(X, Y):
    """The scale, rotation and shift taking the points X onto Y best (Umeyama; least squares, no mirroring): the
    akimbo Luger is the Luger 8.7% bigger. Returns (R scaled, t)."""
    cx, cy = X.mean(0), Y.mean(0)
    U, S, Vt = np.linalg.svd((X - cx).T @ (Y - cy))
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
    R = Vt.T @ D @ U.T
    s = (S * np.diag(D)).sum() / max(((X - cx) ** 2).sum(), 1e-12)
    return s * R, cy - s * R @ cx


def align(base, host):
    """(R, t) taking the base model's frame into the host's when the host is that model again (a variant: moved,
    turned, scaled, with more or fewer triangles), from the triangles textured alike; None when it is another shape."""
    def keyed(h):
        out = {}
        for i in range(len(h.P)):
            order = sorted(range(3), key=lambda k: (round(h.UV[i, k, 0], 3), round(h.UV[i, k, 1], 3)))
            key = tuple((round(h.UV[i, k, 0], 3), round(h.UV[i, k, 1], 3)) for k in order)
            out.setdefault(key, []).append(h.P[i, order])
        return out
    kb, kh = keyed(base), keyed(host)
    X, Y = [], []
    for key, pb in kb.items():
        ph = kh.get(key)
        if ph and len(pb) == 1 and len(ph) == 1:
            X.extend(pb[0])
            Y.extend(ph[0])
    if len(X) < 12:
        return None
    X, Y = np.array(X), np.array(Y)
    keep = np.ones(len(X), bool)
    for _ in range(4):
        R, t = kabsch(X[keep], Y[keep])
        keep = np.linalg.norm(X @ R.T + t - Y, axis=1) < 0.15
        if keep.sum() < 12:
            return None
    if keep.sum() < 0.5 * len(X):
        return None
    return kabsch(X[keep], Y[keep])


class Host:
    """A weapon model's gun triangles, frame 0: positions, texture coordinates (each triangle moved into 0..1 by
    whole numbers, as textskins does), outward normals (the model's winding turned the way that points away from
    its middle, as textskins does)."""
    def __init__(self, name, key):
        m = ts.Model(name)
        tris, uvs = [], []
        for s in m.surfaces:
            if key not in (s.shaders[0] if s.shaders else "").lower():
                continue
            for t in s.tris:
                tris.append([s.frames[0][i] for i in t])
                uvs.append([s.st[i] for i in t])
        self.name = name
        self.P = np.array(tris, np.float64).reshape(-1, 3, 3)
        self.UV = np.array(uvs, np.float64).reshape(-1, 3, 2)
        self.N = np.zeros((len(self.P), 3))
        if len(self.P):
            self.UV -= np.floor(self.UV.mean(axis=1, keepdims=True))
            n = np.cross(self.P[:, 1] - self.P[:, 0], self.P[:, 2] - self.P[:, 0])
            area = np.linalg.norm(n, axis=1)
            n /= np.maximum(area, 1e-9)[:, None]
            c = self.P.reshape(-1, 3).mean(0)
            if (np.einsum("ij,ij->i", n, self.P.mean(1) - c) * area).sum() < 0:
                n = -n
            self.N = n
        self.frames = m.num_frames


# ------------------------------------------------------------------ views

def raster(scr, dep, W, H):
    """Front triangle and its barycentrics (w0, w1) per pixel, and the depth there."""
    idx = np.full((H, W), -1, np.int32)
    bary = np.zeros((H, W, 2), np.float64)
    zbuf = np.full((H, W), np.inf)
    for i in range(len(scr)):
        sx, sy = scr[i, :, 0], scr[i, :, 1]
        x0, x1 = int(max(0, np.floor(sx.min()))), int(min(W - 1, np.ceil(sx.max())))
        y0, y1 = int(max(0, np.floor(sy.min()))), int(min(H - 1, np.ceil(sy.max())))
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float64) + 0.5
        ax, ay, bx, by, cx, cy = sx[0], sy[0], sx[1], sy[1], sx[2], sy[2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        w0 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / den
        w1 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / den
        m = (w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0)
        z = w0 * dep[i, 0] + w1 * dep[i, 1] + (1 - w0 - w1) * dep[i, 2]
        zb = zbuf[y0:y1 + 1, x0:x1 + 1]
        m &= z < zb
        if not m.any():
            continue
        zb[m] = z[m]
        idx[y0:y1 + 1, x0:x1 + 1][m] = i
        bary[y0:y1 + 1, x0:x1 + 1, 0][m] = w0[m]
        bary[y0:y1 + 1, x0:x1 + 1, 1][m] = w1[m]
    return idx, bary, zbuf


class View:
    """The base weapon's first-person mesh (hand space) seen the way the player sees it: kind "fp", the game's own
    camera; "inspect", the gun's left side straight on (what +ilookatweapon turns toward the player). Per pixel of
    the gun: its point, triangle and how square-on a sticker there looks."""
    def __init__(self, mesh, tex, kind):
        self.kind = kind
        if kind == "fp":
            cam = art.game_camera(tex)
            self.W, self.H = art.VIEW_W, art.VIEW_H
            f = (self.H / 2) / math.tan(math.radians(art.FOV_Y) / 2)

            def project(p):
                q = np.asarray(p, np.float64) - cam
                x = np.maximum(q[..., 0], 0.1)
                return np.stack([self.W / 2 - f * q[..., 1] / x, self.H / 2 - f * q[..., 2] / x], axis=-1), q[..., 0]
        else:
            pts = mesh.P.reshape(-1, 3)
            lo, hi = pts.min(0), pts.max(0)
            c = (lo + hi) / 2
            self.W, self.H = int((hi[0] - lo[0]) * INSPECT_PX) + 80, int((hi[2] - lo[2]) * INSPECT_PX) + 80

            def project(p):
                p = np.asarray(p, np.float64)
                return np.stack([self.W / 2 - (p[..., 0] - c[0]) * INSPECT_PX,
                                 self.H / 2 - (p[..., 2] - c[2]) * INSPECT_PX], axis=-1), hi[1] + 5 - p[..., 1]
        self.project = project
        tris = np.concatenate([mesh.P, mesh.other]) if len(mesh.other) else mesh.P
        scr, dep = project(tris)
        idx, bary, self.zbuf = raster(scr, dep, self.W, self.H)
        ys, xs = np.nonzero((idx >= 0) & (idx < len(mesh.P)))
        tri = idx[ys, xs]
        w0, w1 = bary[ys, xs, 0], bary[ys, xs, 1]
        P = mesh.P[tri]
        self.ys, self.xs, self.tri = ys, xs, tri
        self.p = P[:, 0] * w0[:, None] + P[:, 1] * w1[:, None] + P[:, 2] * (1 - w0 - w1)[:, None]
        self.ratio = np.zeros((self.H, self.W))
        self.ratio[ys, xs] = self.squash(self.p, mesh.N[tri])

    def squash(self, p, n):
        """How square-on a flat sticker at the points p (normals n) looks: the smaller over the larger stretch of the
        face's own axes on screen (1 facing the camera, toward 0 edge-on)."""
        a1 = np.cross(n, np.array([0, 0, 1.0]))
        flat = np.linalg.norm(a1, axis=1) < 0.3
        a1[flat] = np.cross(n[flat], np.array([1.0, 0, 0]))
        a1 /= np.linalg.norm(a1, axis=1)[:, None]
        a2 = np.cross(n, a1)
        eps = 0.01
        s0 = self.project(p)[0]
        J = np.stack([(self.project(p + a1 * eps)[0] - s0) / eps, (self.project(p + a2 * eps)[0] - s0) / eps], axis=2)
        sv = np.linalg.svd(J, compute_uv=False)
        return sv[:, 1] / np.maximum(sv[:, 0], 1e-9)

    def shows(self, verts, tris):
        """Pixels a decal covers here, those that show (nothing in front: the hands, the gun), and the latter weighed
        by how square-on they are."""
        scr, dep = self.project(verts)
        tot, vis, leg = 0, 0, 0.0
        for t in tris:
            sx, sy, d = scr[t, 0], scr[t, 1], dep[t]
            x0, x1 = int(max(0, np.floor(sx.min()))), int(min(self.W - 1, np.ceil(sx.max())))
            y0, y1 = int(max(0, np.floor(sy.min()))), int(min(self.H - 1, np.ceil(sy.max())))
            den = (sy[1] - sy[2]) * (sx[0] - sx[2]) + (sx[2] - sx[1]) * (sy[0] - sy[2])
            if x1 < x0 or y1 < y0 or abs(den) < 1e-9:
                continue
            ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float64) + 0.5
            w0 = ((sy[1] - sy[2]) * (xs - sx[2]) + (sx[2] - sx[1]) * (ys - sy[2])) / den
            w1 = ((sy[2] - sy[0]) * (xs - sx[2]) + (sx[0] - sx[2]) * (ys - sy[2])) / den
            m = (w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0)
            if not m.any():
                continue
            z = w0 * d[0] + w1 * d[1] + (1 - w0 - w1) * d[2]
            front = m & (z <= self.zbuf[y0:y1 + 1, x0:x1 + 1] + 0.06)
            tot += int(m.sum())
            vis += int(front.sum())
            leg += float(self.ratio[y0:y1 + 1, x0:x1 + 1][front].sum())
        return tot, vis, leg


# ------------------------------------------------------------------ places

def uv_at(mesh, tri, p):
    """The texture coordinate (as textskins' mesh has them) of the point p of a triangle."""
    a, b, c = mesh.P[tri]
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
    den = d00 * d11 - d01 * d01
    s = (d11 * d20 - d01 * d21) / den if den else 0.0
    t = (d00 * d21 - d01 * d20) / den if den else 0.0
    return mesh.UV[tri, 0] * (1 - s - t) + mesh.UV[tri, 1] * s + mesh.UV[tri, 2] * t


def at_uv(host, uv, normal):
    """The point of a model where the texture coordinate uv is, on a face turned about normal (a flank's texture is
    often the other flank's too): (point, its face's normal) or None."""
    T = host.UV
    v0, v1, v2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0], np.asarray(uv) - T[:, 0]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    ok = np.abs(den) > 1e-12
    den = np.where(ok, den, 1.0)
    s = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
    t = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
    ok &= (s >= -1e-3) & (t >= -1e-3) & (s + t <= 1 + 1e-3)
    facing = host.N @ np.asarray(normal)
    ok &= facing >= 0.5
    if not ok.any():
        return None
    i = int(np.argmax(np.where(ok, facing, -9)))
    P = host.P[i]
    return P[0] + s[i] * (P[1] - P[0]) + t[i] * (P[2] - P[0]), host.N[i]


def upright(view, c, n, right, up, square):
    """The way round a picture on a face reads upright to the player in this view: its top toward the top of the
    screen, its lines from left to right. A long display stays along the gun (turned half round at most); a square
    sticker may turn a quarter too. (Laid by the gun's own axes, the display read upside down: "LEEI".)"""
    c, n, right, up = (np.asarray(v, np.float64) for v in (c, n, right, up))
    ways = [(right, up), (-right, -up)]
    if square:
        ways += [(up, -right), (-up, right)]
    s0 = view.project(c)[0]

    def score(way):
        r, u = way
        sr = view.project(c + r * 0.05)[0] - s0
        su = view.project(c + u * 0.05)[0] - s0
        sr /= max(np.linalg.norm(sr), 1e-9)
        su /= max(np.linalg.norm(su), 1e-9)
        return -su[1] + sr[0]          # screen y grows downward
    return max(ways, key=score)


def place(tex, zone=None):
    """The StatTrak display's place and the sticker spots of a weapon. Returns (plate, spots, mesh): plate a place or
    None, spots [place]; a place {view, center, normal, right, up, w, h (hand space, game units), piece, part,
    area (pixels shown), seen (share shown), square, fp (shows in the normal view)}."""
    mesh = ts.mesh_of(tex)
    _, _, parts = ts.weap(ts.TEX[tex][0])
    F = mesh.F
    xs_all = mesh.P[..., 0]
    lo_x, hi_x = xs_all.min(), xs_all.max()
    length = hi_x - lo_x
    pieces = {int(g): (mesh.P[mesh.G == g], mesh.N[mesh.G == g]) for g in np.unique(mesh.G)}
    taken = []

    def part_of(g):
        return -1 if g == 0 else list(parts.keys())[g - 1]

    def overlaps(c, n, r, u, w, h):
        def inside(pts, o):
            q = pts - o["center"]
            return ((np.abs(q @ o["right"]) <= o["w"] / 2 + GAP) & (np.abs(q @ o["up"]) <= o["h"] / 2 + GAP)
                    & (np.abs(q @ o["normal"]) <= 1.0)).any()
        mine = np.array([c + r * dx * w / 2 + u * dy * h / 2 for dx in (-1, 0, 1) for dy in (-1, 0, 1)])
        for o in taken:
            theirs = np.array([o["center"] + o["right"] * dx * o["w"] / 2 + o["up"] * dy * o["h"] / 2
                               for dx in (-1, 0, 1) for dy in (-1, 0, 1)])
            box = {"center": c, "right": r, "up": u, "normal": n, "w": w, "h": h}
            if inside(mine, o) or inside(theirs, box):
                return True
        return False

    views = {}

    def view(kind):
        if kind not in views:
            v = View(mesh, tex, kind)
            pick = (v.ys % STRIDE == 0) & (v.xs % STRIDE == 0)
            v.cands = [(v.p[i], mesh.N[v.tri[i]], int(mesh.G[v.tri[i]]), int(v.tri[i])) for i in np.nonzero(pick)[0]]
            v.cache = {}
            views[kind] = v
        return views[kind]

    def best(kind, sizes, aspect, need_square, score, allowed=None, all_sizes=False, zone=None):
        """The best free place of a size (the largest that has one, or of every size with all_sizes) in this view:
        laid for real, drawn with what is in front of it. A display lies on one flat face only: wrapped round a
        bend its digits would part."""
        v = view(kind)
        min_area = MIN_AREA if kind == "fp" else (1.1 * INSPECT_PX) ** 2 * 0.8
        flat = dict(facing=DISPLAY_FACING, need=0.97) if aspect > 1 else {}
        found = None
        for s in sizes:
            if s > 0.105 * length and aspect == 1:
                continue
            w, h = s * aspect, s
            if not all_sizes:
                found = None
            for ci, (c, n, g, tri) in enumerate(v.cands):
                if allowed is not None and g not in allowed:
                    continue
                if zone and not zone[0] <= (c[0] - lo_x) / max(length, 1e-6) <= zone[1]:
                    continue                    # outside the stretch of the gun asked for
                r, u = axes_for(n, F)
                if aspect > 1 and abs(n @ F) > 0.5:
                    continue                    # the display reads along the gun
                key = (ci, s, aspect)
                if key not in v.cache:
                    geo = lay(*pieces[g], c, n, r, u, w, h, **flat)
                    if geo and aspect > 1:
                        # every digit's cell on the face too (a display may just clear an edge its first digit does not)
                        box = {"center": c, "normal": n, "right": r, "up": u, "w": w, "h": h}
                        for cell in art.cells_normalized():
                            cp = cell_place(box, cell)
                            if not lay(*pieces[g], cp["center"], n, r, u, cp["w"], cp["h"], **flat):
                                geo = None
                                break
                    v.cache[key] = v.shows(geo[0], geo[2]) if geo else None
                st = v.cache[key]
                if not st:
                    continue
                tot, vis, leg = st
                seen, square = vis / max(tot, 1), leg / max(vis, 1)
                if seen < MIN_SEEN or vis < min_area or square < need_square:
                    continue
                if overlaps(c, n, r, u, w, h):
                    continue
                sc = score(vis, leg, (c[0] - lo_x) / max(length, 1e-6), s)
                if sc is None:
                    continue
                if found is None or sc > found[0]:
                    found = (sc, {"view": kind, "center": c, "normal": n, "right": r, "up": u, "w": w, "h": h,
                                  "piece": g, "part": part_of(g), "area": vis, "seen": seen, "square": square,
                                  "fp": kind == "fp", "uv": uv_at(mesh, tri, c)})
            if found and not all_sizes:
                break
        if not found:
            return None
        pl = found[1]
        pl["right"], pl["up"] = upright(v, pl["center"], pl["normal"], pl["right"], pl["up"], aspect == 1)
        taken.append(pl)
        return pl

    if tex in KEPT_DISPLAYS:
        k = KEPT_DISPLAYS[tex]
        plate = {key: np.array(val, np.float64) for key, val in k.items() if key in ("center", "normal", "right", "up")}
        plate.update(view="fp", w=k["w"], h=k["h"], piece=k["piece"], part=part_of(k["piece"]))
        geo = lay(*pieces[k["piece"]], plate["center"], plate["normal"], plate["right"], plate["up"], k["w"], k["h"], need=0.9)
        tot, vis, leg = view("fp").shows(geo[0], geo[2]) if geo else (0, 0, 0.0)
        plate.update(area=vis, seen=vis / max(tot, 1), square=leg / max(vis, 1))
        plate["fp"] = plate["seen"] >= MIN_SEEN and vis >= MIN_AREA
        taken.append(plate)
    else:
        # the MP 40 (asked 2026-09-29): seen without inspecting, just behind the barrel on the side the player sees,
        # readable: the place nearest the muzzle that does, on one flat face
        plate_sizes = [s for s in PLATE_SIZES if s <= 0.06 * length]
        plate_score = lambda vis, leg, al, s: leg  # noqa: E731
        zone = zone or MP40_DISPLAY_ZONE
        plate = (best("fp", plate_sizes, art.PLATE_ASPECT, MIN_SQUARE_PLATE, plate_score, all_sizes=True, zone=zone)
                 or best("fp", plate_sizes, art.PLATE_ASPECT, MIN_SQUARE, plate_score, all_sizes=True, zone=zone))
    spots = []
    limit = SPOT_LIMIT.get(tex, 0)
    while len(spots) < limit:
        sp = best("fp", STICKER_SIZES, 1, MIN_SQUARE, lambda vis, leg, al, s: leg)
        if not sp:
            break
        spots.append(sp)
    while len(spots) < min(limit, PLACES):
        sp = best("inspect", STICKER_SIZES, 1, MIN_SQUARE, lambda vis, leg, al, s: leg)
        if not sp:
            break
        spots.append(sp)
    return plate, spots, mesh


# ------------------------------------------------------------------ files

def md3_bytes(name, frames, verts, st, tris, normals):
    """A one-surface MD3 whose every frame is verts (the host models have one frame; the cgame's customShader draws
    it, so its own shader fbd/decal draws nothing)."""
    nv, nt = len(verts), len(tris)
    ofs_tri = 108
    ofs_sh = ofs_tri + nt * 12
    ofs_st = ofs_sh + 68
    ofs_xyz = ofs_st + nv * 8
    surf_end = ofs_xyz + frames * nv * 8
    surf = bytearray(b"IDP3" + b"decal".ljust(64, b"\0"))
    surf += struct.pack("<10i", 0, frames, 1, nv, nt, ofs_tri, ofs_sh, ofs_st, ofs_xyz, surf_end)
    for t in tris:
        surf += struct.pack("<3i", *(int(v) for v in t))
    surf += b"fbd/decal".ljust(64, b"\0") + struct.pack("<i", 0)
    for a, b in st:
        surf += struct.pack("<2f", float(a), float(b))
    xyz = bytearray()
    for (x, y, z), (nx, ny, nz) in zip(verts, normals):
        # tr_model.c: x = cos(lat) sin(lng), y = sin(lat) sin(lng), z = cos(lng); lat the high byte
        lat = int(round(math.atan2(ny, nx) * 256 / (2 * math.pi))) & 255
        lng = int(round(math.acos(max(-1.0, min(1.0, nz))) * 256 / (2 * math.pi))) & 255
        xyz += struct.pack("<3hH", int(round(x * 64)), int(round(y * 64)), int(round(z * 64)), (lat << 8) | lng)
    surf += xyz * frames
    mins, maxs = verts.min(0), verts.max(0)
    radius = float(np.linalg.norm(maxs - mins) / 2)
    frame = struct.pack("<3f3f3ff", *mins, *maxs, *((mins + maxs) / 2), radius) + b"fbd".ljust(16, b"\0")
    ofs_frames = 108
    ofs_tags = ofs_frames + frames * 56
    ofs_surf = ofs_tags
    ofs_end = ofs_surf + len(surf)
    out = bytearray(b"IDP3" + struct.pack("<i", 15) + name.encode()[:63].ljust(64, b"\0"))
    out += struct.pack("<9i", 0, frames, 0, 1, 0, ofs_frames, ofs_tags, ofs_surf, ofs_end)
    out += frame * frames + surf
    return bytes(out)


def square_art(path):
    """A sticker's art centred on a clear square, in place (the decals are square, one takes any design); the
    pixels themselves stay as they are, so doing it again changes nothing."""
    im = Image.open(path).convert("RGBA")
    if im.width == im.height:
        return
    size = max(im.size)
    sq = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sq.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    sq.save(path, optimize=True)


def decal_shader(name, image, rgbgen):
    return (f"{name}\n{{\n\tnopicmip\n\tpolygonOffset\n\tsort decal\n\t{{\n\t\tclampmap {image}\n"
            f"\t\tblendFunc blend\n\t\trgbGen {rgbgen}\n\t}}\n}}\n")


def hand_to_model(hand, tag):
    """(point, direction) maps from hand space into the frame of the model hanging on this tag of the hands."""
    org, axis = hand.tag(tag, 0)
    axis = np.array(axis, np.float64)
    org = np.array(org, np.float64)
    return (lambda p: axis @ (np.asarray(p) - org)), (lambda n: axis @ np.asarray(n))


def cell_place(pl, cell):
    """The part of a place a digit cell (x0, y0, x1, y1 fractions, y down) covers."""
    x0, y0, x1, y1 = cell
    c = pl["center"] + pl["right"] * pl["w"] * ((x0 + x1) / 2 - 0.5) - pl["up"] * pl["h"] * ((y0 + y1) / 2 - 0.5)
    return dict(pl, center=c, w=pl["w"] * (x1 - x0), h=pl["h"] * (y1 - y0))


def art_point(mesh, p):
    """Where a point shows on the website's item picture of the gun (960x400, the first-person model's left flank,
    orthographic, framed as FatBoss's make_cosmetic_art2.py frames it): (x, y) fractions of the picture."""
    F, up = mesh.F, np.array([0, 0, 1.0])
    right = -F
    a, b = mesh.P.reshape(-1, 3) @ right, mesh.P.reshape(-1, 3) @ up
    lo, hi = np.array([a.min(), b.min()]), np.array([a.max(), b.max()])
    span = max((hi[0] - lo[0]) / (960 * 0.92), (hi[1] - lo[1]) / (400 * 0.88))
    x = (np.asarray(p) @ right - (lo[0] + hi[0]) / 2) / span + 480
    y = -(np.asarray(p) @ up - (lo[1] + hi[1]) / 2) / span + 200
    return float(np.clip(x / 960, 0, 1)), float(np.clip(y / 400, 0, 1))


def write_bot_module(path, spot_json):
    """FatBoss's copy of the spots (the website's picker and the checks): fatboss_sticker_spots.py."""
    lines = ['"""The sticker spots of each gun, as the FatBoss cgame (b16) draws them - generated by the fatboss-etl',
             "repo's fatboss/skins/build_decals.py --bot, do not edit.",
             "",
             "Per gun slot, in spot order: seen, whether it shows in the normal first-person view (else only when you",
             "inspect the gun); art, where it is on the website's item picture (x, y fractions of the 960x400 picture).",
             '"""',
             "",
             "STICKERS_PER_GUN = %d        # stickers on one gun at most, like CS2's" % PLACES,
             "",
             "SPOTS = {"]
    for slot, spots in spot_json.items():
        lines.append(f'    "{slot}": [')
        for sp in spots:
            lines.append(f'        {{"seen": {sp["fp"]}, "art": ({sp["art"][0]:.3f}, {sp["art"][1]:.3f})}},')
        lines.append("    ],")
    lines.append("}")
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("bot module ->", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paks", nargs="+", required=True)
    ap.add_argument("--bot", help="FatBoss bot folder: write its fatboss_sticker_spots.py there")
    args = ap.parse_args()
    paks = bs.Paks(args.paks)
    ts.set_reader(paks.read)
    designs = art.sticker_designs()

    for code, design in designs:
        square_art(os.path.join(PK3, "fatboss", "stickers", f"{design}.png"))
    st_dir = os.path.join(PK3, "fatboss", "stattrak")
    shutil.rmtree(st_dir, ignore_errors=True)
    os.makedirs(st_dir)
    art.plate_image().save(os.path.join(st_dir, "plate.png"), optimize=True)
    for dgt in range(10):
        art.digit_image(dgt).save(os.path.join(st_dir, f"{dgt}.png"), optimize=True)
    shaders = ["// FatBoss decals - generated by fatboss/skins/build_decals.py, do not edit", "",
               "// the decal models' own shader: the cgame always draws them with a customShader",
               "fbd/decal\n{\n\tsurfaceparm nodraw\n\tsurfaceparm nomarks\n}\n"]
    shaders += [decal_shader(f"fbd/s/{design}", f"fatboss/stickers/{design}.png", "lightingDiffuse") for _, design in designs]
    shaders.append(decal_shader("fbd/plate", "fatboss/stattrak/plate.png", "lightingDiffuse"))
    shaders += [decal_shader(f"fbd/digit{d}", f"fatboss/stattrak/{d}.png", "identity") for d in range(10)]
    with open(os.path.join(PK3, "scripts", "fatboss_decals.shader"), "w", newline="\n") as f:
        f.write("\n".join(shaders))

    places, report, spot_json = {}, [], {}
    for tex in GUNS + KNIVES:
        plate, spots, mesh = place(tex)
        if plate is None or (tex in GUNS and len(spots) < min(SPOT_LIMIT[tex], PLACES)):
            raise SystemExit(f"{tex}: {len(spots)} spots" + ("" if plate else ", no display"))
        places[tex] = (plate, spots, mesh)
        for label, pl in [("display", plate)] + [(f"spot {k + 1}", sp) for k, sp in enumerate(spots)]:
            report.append(f"{tex:9s} {label:8s} {pl['w']:.2f} x {pl['h']:.2f} u  {pl['area']:6.0f} px  seen {pl['seen']:.2f}  "
                          f"square {pl['square']:.2f}  {'in view' if pl['fp'] else 'inspect'}  part {pl['part']}  "
                          f"n {np.round(pl['normal'], 2)}")
        if tex in GUNS:
            spot_json[tex] = [{"spot": k, "fp": sp["fp"], "screen": int(sp["area"]), "square": round(sp["square"], 2),
                               "part": sp["part"], "size": round(sp["w"], 2),
                               "center": [round(float(v), 3) for v in sp["center"]],
                               "art": [round(v, 3) for v in art_point(mesh, sp["center"])],
                               "normal": [round(float(v), 3) for v in sp["normal"]]} for k, sp in enumerate(spots)]
    with open(SPOTS_JSON, "w", newline="\n") as f:
        json.dump(spot_json, f, indent=1)
    if args.bot:
        write_bot_module(os.path.join(args.bot, "fatboss_sticker_spots.py"), spot_json)

    model_dir = os.path.join(PK3, "models", "fbd")
    shutil.rmtree(model_dir, ignore_errors=True)
    os.makedirs(model_dir)
    cells = art.cells_normalized()
    files, by_hash = [], {}          # decal files in order; content hash -> index

    def store(stem, geo, frames):
        if geo is None:
            return -1
        data = md3_bytes(stem, frames, *geo)
        h = hashlib.sha1(data[72:]).hexdigest()
        if h not in by_hash:
            path = f"models/fbd/{stem}.md3"
            n = 1
            while path in files:        # two models of one name (the knife's and the KA-BAR's v_knife_barrel)
                n += 1
                path = f"models/fbd/{stem}{n}.md3"
            if len(path) >= bs.MAX_QPATH:
                raise SystemExit(f"{path}: too long for the engine")
            with open(os.path.join(PK3, path), "wb") as f:
                f.write(data)
            by_hash[h] = len(files)
            files.append(path)
        return by_hash[h]

    hosts = []                       # (weapon, view, part, [spot decal], plate decal, [digit decals], stem)
    for wp, slot, tex, weap in bs.WEAPONS:
        if tex not in GUNS + KNIVES:
            continue
        plate, spots, mesh = places[tex]
        key = ts.TEX[tex][1]
        main_base, hands_base, parts_base = ts.weap(ts.TEX[tex][0])
        hand = ts.Model(hands_base)
        base_tags = ["tag_weapon"] + [t for t, _ in parts_base.values()]
        base_models = [main_base] + [mdl for _, mdl in parts_base.values()]
        models = bs.parse_weap(paks.read(f"weapons/{weap}.weap").decode("latin1"))
        items = [("s", k, sp) for k, sp in enumerate(spots)] + [("p", 0, plate)]
        for (view, part), m in sorted(models.items(), key=lambda kv: (kv[0][0] != "fp", kv[0][1])):
            if not m[0] or view not in ("fp", "tp"):
                continue
            try:
                host = Host(m[0], key)
            except FileNotFoundError:
                continue
            if not len(host.P):
                continue
            stem = os.path.splitext(os.path.basename(m[0]))[0].lower()
            spot_ids, plate_id, digit_ids = [-1] * SPOTS, -1, [-1] * DIGITS
            fits = {}                   # base piece -> (R, t) into this model, None: not that piece

            def into(piece):
                if piece not in fits:
                    if m[0].lower() == base_models[piece].lower():
                        fits[piece] = (np.eye(3), np.zeros(3))
                    else:
                        fits[piece] = align(Host(base_models[piece], key), host)
                return fits[piece]

            def carried(pl):
                """The place in this model's frame, and whether it is only rough (another mesh)."""
                pt, nr = hand_to_model(hand, base_tags[pl["piece"]])
                if view == "fp":
                    fit_ = into(pl["piece"])
                    if fit_ is None:
                        return None, False
                    R, t = fit_
                    s = np.linalg.norm(R[:, 0])
                    unit = lambda d: R @ nr(d) / np.linalg.norm(R @ nr(d))  # noqa: E731
                    return dict(pl, center=R @ pt(pl["center"]) + t, normal=unit(pl["normal"]), right=unit(pl["right"]),
                                up=unit(pl["up"]), w=pl["w"] * s, h=pl["h"] * s), False
                # third person: another mesh of the gun (x along it, z up, as the first-person models): where it has
                # the same spot of the texture, on a face turned the same way; else carried by the two outlines
                gun = mesh.P.reshape(-1, 3)
                f0, f1 = gun.min(0), gun.max(0)
                t0, t1 = host.P.reshape(-1, 3).min(0), host.P.reshape(-1, 3).max(0)
                s = (t1[0] - t0[0]) / (f1[0] - f0[0])
                def turned(n):
                    # the way round the first-person place reads (see upright), on this model's face
                    r, u = axes_for(n, np.array([1.0, 0, 0]))
                    ways = [(r, u), (-r, -u)] + ([(u, -r), (-u, r)] if pl["w"] == pl["h"] else [])
                    return max(ways, key=lambda way: way[0] @ nr(pl["right"]) + way[1] @ nr(pl["up"]))
                hit = at_uv(host, pl["uv"], nr(pl["normal"]))
                if hit is not None:
                    right, up = turned(hit[1])
                    return dict(pl, center=hit[0], normal=hit[1], right=right, up=up, w=pl["w"] * s, h=pl["h"] * s), False
                n = nr(pl["normal"])
                right, up = turned(n)
                return dict(pl, center=s * (pl["center"] - (f0 + f1) / 2) + (t0 + t1) / 2, normal=n, right=right, up=up,
                            w=pl["w"] * s, h=pl["h"] * s), True

            def laid(pl, rough, **flat):
                args = (host.P, host.N, pl["center"], pl["normal"], pl["right"], pl["up"], pl["w"], pl["h"])
                geo = None if rough else lay(*args, **dict(dict(need=0.9), **flat))
                return geo or (None if flat else lay_near(*args))
            for kind, k, pl in items:
                if kind == "p" and view != "fp":
                    continue            # the display shows to its owner only
                here, rough = carried(pl)
                if here is None:
                    continue
                if kind == "s":
                    spot_ids[k] = store(f"{stem}_{k}", laid(here, rough), host.frames)
                    if rough and spot_ids[k] >= 0:
                        print(f"  {stem} spot {k + 1}: third person, laid near")
                    continue
                # the display and its digits on one flat face: laid round a bend the digits would part (the place was
                # checked on the base model; another model of the weapon is the same shape, give or take a facet)
                flat = dict(facing=DISPLAY_FACING) if m[0].lower() == base_models[pl["piece"]].lower() else dict(facing=0.8, depth=0.8, need=0.85)
                plate_id = store(f"{stem}_p", laid(here, rough, **flat), host.frames)
                if plate_id < 0:
                    continue
                digit_ids = [store(f"{stem}_d{pos}", laid(cell_place(here, cell), rough, **flat), host.frames)
                             for pos, cell in enumerate(cells)]
                if min(digit_ids) < 0:
                    print(f"  {stem}: a digit found no face, no display")
                    plate_id, digit_ids = -1, [-1] * DIGITS
            if max(spot_ids) >= 0 or plate_id >= 0:
                hosts.append((wp, "W_FP_MODEL" if view == "fp" else "W_TP_MODEL", part, spot_ids, plate_id, digit_ids, stem))

    with open(INC, "w", newline="\n") as f:
        f.write("// FatBoss decals - generated by fatboss/skins/build_decals.py, do not edit\n\n")
        f.write(f"#define FB_STICKER_PLACES {PLACES}   // stickers on one gun at most\n")
        f.write(f"#define FB_STICKER_SPOTS {SPOTS}    // spots a gun has at most (the player picks one per sticker)\n")
        f.write(f"#define FB_STATTRAK_DIGITS {DIGITS}\n")
        f.write(f"#define FB_DECAL_MODELS {len(files)}\n\n")
        f.write("// textures with sticker spots (the guns), and with a StatTrak display (the knives too)\n")
        f.write("static const qboolean fbStickerTex[FB_SKIN_TEXTURES] = { %s };\n" % ", ".join(
            "qtrue" if t in GUNS else "qfalse" for t in bs.ALL))
        f.write("static const qboolean fbDisplayTex[FB_SKIN_TEXTURES] = { %s };\n" % ", ".join(
            "qtrue" if t in GUNS + KNIVES else "qfalse" for t in bs.ALL))
        f.write("static const int fbStickerSpots[FB_SKIN_TEXTURES] = { %s };\n\n" % ", ".join(
            str(len(places[t][1])) if t in GUNS else "0" for t in bs.ALL))
        f.write("static const char *fbDecalModels[FB_DECAL_MODELS] =\n{\n")
        for p in files:
            f.write(f'\t"{p}",\n')
        f.write("};\n\n")
        f.write("// the models of each weapon that carry decals (-1 the weapon model, else its part), and per sticker spot,\n"
                "// the display and its digits the decal in fbDecalModels (-1 none on this model)\n")
        f.write("typedef struct\n{\n\tint weapon;\n\tint view;\n\tint part;\n\tshort spot[FB_STICKER_SPOTS];\n"
                "\tshort plate;\n\tshort digit[FB_STATTRAK_DIGITS];\n} fbDecalHost_t;\n\n")
        f.write("static const fbDecalHost_t fbDecalHosts[] =\n{\n")
        for wp, view, part, spot_ids, plate_id, digit_ids, stem in hosts:
            f.write("\t{ %s, %s, %d, { %s }, %d, { %s } },   // %s\n" % (
                wp, view, part, ", ".join(str(v) for v in spot_ids), plate_id, ", ".join(str(v) for v in digit_ids), stem))
        f.write("};\n")
    print("\n".join(report))
    print(f"{len(files)} decal models, {len(hosts)} host models -> {INC}")
    for wp, view, part, spot_ids, plate_id, digit_ids, stem in hosts:
        print(f"  {wp:24s} {view:10s} {part:3d} {stem:28s} spots {spot_ids} display {plate_id}")


if __name__ == "__main__":
    main()
