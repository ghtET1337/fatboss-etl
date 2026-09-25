"""Text skins: labels laid on the flat panels of the weapon models, so they read.

The stock weapon textures are atlases: one side of a gun can be cut into
several islands, mirrored, rotated, shared with the other side or reused by
another part. Text laid over such a texture blindly comes out chopped and
backwards. Here the first-person model, assembled in hand space (x forward
into the screen, y left, z up, the camera at the origin), gives for every
triangle the directions "along the gun" and "up" in the texture. Flat groups
of triangles (charts) get labels in their largest free rectangle, drawn in
that frame:

- the side the player sees in first person wins texels both sides share
  (the other side then shows the text mirrored, as the stock art does);
- no labels on texels another visible part of the first-person model also
  uses (the third-person model reuses more; see charts_of);
- main labels go on the side panels; grips and magazines read downwards.

build_skins.py calls build() for the themes in TEXT_THEMES. Fonts are the
Windows ones (C:\\Windows\\Fonts), the builds run on Windows.

    python fatboss/skins/textskins.py board <out.jpg> --paks legacy_v2.86.0.pk3 pak0.pk3 [--themes ...]
"""
import argparse
import io
import math
import os
import random
import re
import struct
import sys
import time
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_READ = None


def set_reader(read):
    """read(name) -> bytes from the game paks (build_skins.Paks.read)."""
    global _READ
    _READ = read
    _MESH.clear()
    _CHARTS.clear()


def read_file(name):
    return _READ(name)


# ---------------------------------------------------------------------------
# MD3 / MDC models

def _cstr(b):
    return b.split(b"\0", 1)[0].decode("latin1")


class Surface:
    def __init__(self, name, shaders, tris, frames, st=None):
        self.st = st or []        # list of (s, t) per vertex
        self.name = name
        self.shaders = shaders
        self.tris = tris          # list of (a, b, c)
        self.frames = frames      # list of list of (x, y, z)

    def verts(self, frame):
        return self.frames[min(frame, len(self.frames) - 1)]

    def bounds(self, frame):
        v = self.verts(frame)
        return ([min(p[i] for p in v) for i in range(3)], [max(p[i] for p in v) for i in range(3)])

    def boundary_loops(self, frame):
        """Open edges (used by exactly one triangle), chained into loops of vertex positions."""
        count = {}
        for t in self.tris:
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(a, b), max(a, b))
                count[k] = count.get(k, 0) + 1
        # weld vertices by position (seams duplicate verts)
        v = self.verts(frame)
        key = {}
        weld = []
        for i, p in enumerate(v):
            k = tuple(round(c, 3) for c in p)
            weld.append(key.setdefault(k, i))
        count2 = {}
        for t in self.tris:
            w = [weld[i] for i in t]
            for a, b in ((w[0], w[1]), (w[1], w[2]), (w[2], w[0])):
                if a == b:
                    continue
                k = (min(a, b), max(a, b))
                count2[k] = count2.get(k, 0) + 1
        edges = [k for k, c in count2.items() if c == 1]
        adj = {}
        for a, b in edges:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        seen = set()
        loops = []
        for start in adj:
            if start in seen:
                continue
            loop = []
            stack = [start]
            while stack:
                n = stack.pop()
                if n in seen:
                    continue
                seen.add(n)
                loop.append(n)
                stack.extend(adj[n])
            loops.append([v[i] for i in loop])
        return loops


class Model:
    def __init__(self, name):
        self.name = name
        data = read_file(name)
        ident = data[:4]
        if ident == b"IDP3":
            self._md3(data)
        elif ident == b"IDPC":
            self._mdc(data)
        else:
            raise ValueError("unknown model " + name)

    def _md3(self, d):
        (ver,) = struct.unpack_from("<i", d, 4)
        flags, nframes, ntags, nsurf, nskins, ofs_frames, ofs_tags, ofs_surf, ofs_end = struct.unpack_from("<9i", d, 72)
        self.num_frames = nframes
        self.tags = {}
        for f in range(nframes):
            for t in range(ntags):
                o = ofs_tags + (f * ntags + t) * 112
                name = _cstr(d[o:o + 64])
                org = struct.unpack_from("<3f", d, o + 64)
                axis = struct.unpack_from("<9f", d, o + 76)
                self.tags.setdefault(name, []).append((org, (axis[0:3], axis[3:6], axis[6:9])))
        self.surfaces = []
        o = ofs_surf
        for s in range(nsurf):
            name = _cstr(d[o + 4:o + 68])
            (sflags, snframes, nsh, nv, ntri, ofs_tri, ofs_sh, ofs_st, ofs_xyz, ofs_send) = struct.unpack_from("<10i", d, o + 68)
            shaders = [_cstr(d[o + ofs_sh + i * 68:o + ofs_sh + i * 68 + 64]) for i in range(nsh)]
            tris = [struct.unpack_from("<3i", d, o + ofs_tri + i * 12) for i in range(ntri)]
            st = [struct.unpack_from("<2f", d, o + ofs_st + i * 8) for i in range(nv)]
            frames = []
            for f in range(snframes):
                fr = []
                for i in range(nv):
                    x, y, z, _n = struct.unpack_from("<4h", d, o + ofs_xyz + (f * nv + i) * 8)
                    fr.append((x / 64.0, y / 64.0, z / 64.0))
                frames.append(fr)
            self.surfaces.append(Surface(name, shaders, tris, frames, st))
            o += ofs_send

    def _mdc(self, d):
        (ver,) = struct.unpack_from("<i", d, 4)
        flags, nframes, ntags, nsurf, nskins, ofs_frames, ofs_tagnames, ofs_tags, ofs_surf, ofs_end = struct.unpack_from("<10i", d, 72)
        self.num_frames = nframes
        tagnames = [_cstr(d[ofs_tagnames + i * 64:ofs_tagnames + i * 64 + 64]) for i in range(ntags)]
        self.tags = {}
        for f in range(nframes):
            for t in range(ntags):
                o = ofs_tags + (f * ntags + t) * 12
                x, y, z, a0, a1, a2 = struct.unpack_from("<6h", d, o)
                org = (x / 64.0, y / 64.0, z / 64.0)
                ang = [a * (360.0 / 32767.0) for a in (a0, a1, a2)]
                self.tags.setdefault(tagnames[t], []).append((org, angles_to_axis(ang)))
        self.surfaces = []
        o = ofs_surf
        for s in range(nsurf):
            name = _cstr(d[o + 4:o + 68])
            (sflags, ncomp, nbase, nsh, nv, ntri, ofs_tri, ofs_sh, ofs_st, ofs_xyz, ofs_comp,
             ofs_fbase, ofs_fcomp, ofs_send) = struct.unpack_from("<14i", d, o + 68)
            shaders = [_cstr(d[o + ofs_sh + i * 68:o + ofs_sh + i * 68 + 64]) for i in range(nsh)]
            tris = [struct.unpack_from("<3i", d, o + ofs_tri + i * 12) for i in range(ntri)]
            st = [struct.unpack_from("<2f", d, o + ofs_st + i * 8) for i in range(nv)]
            base = []
            for f in range(nbase):
                fr = []
                for i in range(nv):
                    x, y, z, _n = struct.unpack_from("<4h", d, o + ofs_xyz + (f * nv + i) * 8)
                    fr.append((x / 64.0, y / 64.0, z / 64.0))
                base.append(fr)
            fbase = struct.unpack_from("<%dh" % nframes, d, o + ofs_fbase)
            fcomp = struct.unpack_from("<%dh" % nframes, d, o + ofs_fcomp)
            frames = []
            for f in range(nframes):
                fr = list(base[fbase[f]])
                if fcomp[f] >= 0:
                    for i in range(nv):
                        (c,) = struct.unpack_from("<I", d, o + ofs_comp + (fcomp[f] * nv + i) * 4)
                        dx = ((c & 255) - 127.0) * 0.05
                        dy = (((c >> 8) & 255) - 127.0) * 0.05
                        dz = (((c >> 16) & 255) - 127.0) * 0.05
                        x, y, z = fr[i]
                        fr[i] = (x + dx, y + dy, z + dz)
                frames.append(fr)
            self.surfaces.append(Surface(name, shaders, tris, frames, st))
            o += ofs_send

    def tag(self, name, frame):
        t = self.tags[name]
        return t[min(frame, len(t) - 1)]


def angles_to_axis(angles):
    # q_math AnglesToAxis: forward, left (negated right), up
    pitch, yaw, roll = [math.radians(a) for a in angles]
    sp, cp = math.sin(pitch), math.cos(pitch)
    sy, cy = math.sin(yaw), math.cos(yaw)
    sr, cr = math.sin(roll), math.cos(roll)
    forward = (cp * cy, cp * sy, -sp)
    right = (-1 * sr * sp * cy + -1 * cr * -sy, -1 * sr * sp * sy + -1 * cr * cy, -1 * sr * cp)
    up = (cr * sp * cy + -sr * -sy, cr * sp * sy + -sr * cy, cr * cp)
    left = tuple(-c for c in right)
    return (forward, left, up)


def weap(w):
    """First-person main model, hands model and {part: (tag, model)} of weapons/<w>.weap."""
    t = read_file(f"weapons/{w}.weap").decode("latin1")
    t = re.sub(r"//[^\n]*", "", t)
    fp = t[t.find("firstPerson"):t.find("thirdPerson")]
    main = re.search(r'\bmodel\s+"([^"]+)"', fp).group(1)
    hands = re.search(r'handsModel\s+"([^"]+)"', t).group(1)
    parts = {}
    for block in re.finditer(r"part\s+(\d+)\s*\{([^}]*)\}", fp):
        tag = re.search(r'tag\s+"([^"]+)"', block.group(2))
        model = re.search(r'model\s+"([^"]+)"', block.group(2))
        if tag and model:
            parts[int(block.group(1))] = (tag.group(1), model.group(1))
    return main, hands, parts


def weap_tp(w):
    """Third-person model of weapons/<w>.weap."""
    t = read_file(f"weapons/{w}.weap").decode("latin1")
    t = re.sub(r"//[^\n]*", "", t)
    tp = t[t.find("thirdPerson"):]
    return re.search(r'\bmodel\s+"([^"]+)"', tp).group(1)


# ---------------------------------------------------------------------------
# first-person mesh, charts, rendering

SIZES = {"colt": (4096, 4096), "luger": (4096, 4096), "thompson": (4096, 4096), "mp40": (4096, 4096),
         "knife": (4096, 1024), "kabar": (4096, 2048)}
STOCK = {"colt": "models/weapons2/colt/colt_yd.tga", "luger": "models/weapons2/luger/luger7_yd.tga",
         "thompson": "models/weapons2/thompson/thompson_la_yd.tga", "mp40": "models/weapons2/mp40/gun11_yd.tga",
         "knife": "models/weapons2/knife/knife_yd.tga", "kabar": "models/weapons2/knife_kbar/knife_yd.jpg"}
TEX = {
    # texture: (.weap of the first-person model, shader substring of its surfaces)
    "colt": ("colt", "colt/colt4"),
    "luger": ("luger", "luger/luger7"),
    "thompson": ("thompson", "thompson/thompson_la"),
    "mp40": ("mp40", "mp40/gun11"),
    "knife": ("knife", "knife/knife1a"),
    "kabar": ("knife_kbar", "knife_kbar/knife_yd"),
}
AN = 1024          # analysis resolution of the wider texture side


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), max(4, int(size)))


def cross2(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


# ---------------------------------------------------------------------------
# first-person mesh in hand space

def xf(org, axis, p):
    return [org[i] + p[0] * axis[0][i] + p[1] * axis[1][i] + p[2] * axis[2][i] for i in range(3)]


class Mesh:
    def __init__(self, tex, view="fp"):
        weap_name, key = TEX[tex]
        main, hands, parts = weap(weap_name)
        hand = Model(hands)
        self.tex, self.view = tex, view
        w, h = SIZES[tex]
        self.aw, self.ah = AN, AN * h // w          # analysis size
        P, UV, G, other = [], [], [], []
        pieces = [(main, "tag_weapon")] + [(m, t) for t, m in parts.values()]
        if view == "tp":
            pieces = [(weap_tp(weap_name), None)]
        for gid, (mname, tag) in enumerate(pieces):
            try:
                m = Model(mname)
            except FileNotFoundError:
                continue
            org, axis = hand.tag(tag, 0) if tag else ((0, 0, 0), ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
            for s in m.surfaces:
                sh = (s.shaders[0] if s.shaders else "").lower()
                v = [xf(org, axis, p) for p in s.verts(0)]
                for a, b, c in s.tris:
                    tri = (v[a], v[b], v[c])
                    if key in sh:
                        P.append(tri)
                        UV.append((s.st[a], s.st[b], s.st[c]))
                        G.append(gid)
                    else:
                        other.append(tri)
        self.P = np.array(P, np.float64)
        self.UV = np.array(UV, np.float64)
        self.UV -= np.floor(self.UV.mean(axis=1, keepdims=True))     # tiled coordinates back into 0..1
        self.G = np.array(G)
        self.other = np.array(other, np.float64) if other else np.zeros((0, 3, 3))
        self._frames()

    def _frames(self):
        P, n_t = self.P, len(self.P)
        nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        area = np.linalg.norm(nrm, axis=1)
        nrm = nrm / np.maximum(area, 1e-9)[:, None]
        # outward: per model, the winding that points away from its centre
        for g in np.unique(self.G):
            sel = self.G == g
            c = P[sel].reshape(-1, 3).mean(0)
            score = (np.einsum("ij,ij->i", nrm[sel], P[sel].mean(1) - c) * area[sel]).sum()
            if score < 0:
                nrm[sel] = -nrm[sel]
        self.N, self.area3 = nrm, area / 2
        pts = P.reshape(-1, 3)
        if self.tex in ("knife", "kabar") or self.view == "tp":
            c = pts.mean(0)
            _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
            F = vt[0] * (1 if vt[0][0] >= 0 else -1)
        else:
            F = np.array([1.0, 0, 0])
        self.F = F
        uvpx = self.UV * np.array([self.aw, self.ah])
        pj = np.zeros((n_t, 2, 3))
        hand = np.zeros(n_t)
        ok = np.zeros(n_t, bool)
        for i in range(n_t):
            A = np.stack([P[i, 1] - P[i, 0], P[i, 2] - P[i, 0]], axis=1)          # 3x2
            B = np.stack([uvpx[i, 1] - uvpx[i, 0], uvpx[i, 2] - uvpx[i, 0]], axis=1)  # 2x2
            if abs(np.linalg.det(B)) < 1e-6 or area[i] < 1e-6:
                continue
            J = A @ np.linalg.inv(B)          # d(position)/d(uv px)
            pj[i] = np.linalg.pinv(J)
            hand[i] = np.sign(nrm[i].dot(np.cross(J[:, 0], J[:, 1])))    # mirrored mapping or not
            ok[i] = True
        self.pj, self.hand, self.ok = pj, hand, ok
        self.uvpx = uvpx
        self.uvarea = np.abs(cross2(uvpx[:, 1] - uvpx[:, 0], uvpx[:, 2] - uvpx[:, 0])) / 2
        # the camera sees these in first person
        self.facing = np.einsum("ij,ij->i", nrm, -P.mean(1)) > 0 if self.view == "fp" else np.ones(n_t, bool)

    def text_axes(self, idx):
        """Right and up of text on a flat group of triangles, in game units."""
        w = self.area3[idx]
        n = (self.N[idx] * w[:, None]).sum(0)
        n /= np.linalg.norm(n)
        Z = np.array([0, 0, 1.0])
        pts = self.P[idx].reshape(-1, 3)
        flat = pts - pts.mean(0)
        flat = flat - np.outer(flat @ n, n)
        _, sv, vt = np.linalg.svd(flat, full_matrices=False)
        d = vt[0]
        long = sv[0] / max(sv[1], 1e-6)
        Fp = self.F - self.F.dot(n) * n
        if np.linalg.norm(Fp) > 0.3:
            Fp /= np.linalg.norm(Fp)
        else:
            Fp = d
        if abs(n[2]) > 0.75:
            right = Fp                          # top or bottom: along the gun, away from the player
        elif long > 1.6 and abs(d[2]) > 0.7:
            right = d if d[2] < 0 else -d       # grip, magazine: along it, read downwards
        else:
            right = Fp if np.cross(n, Fp)[2] > 0 else -Fp
        return right, np.cross(n, right), n

    def charts(self, extra_block=None):
        """Flat groups of neighbouring triangles, each with one text frame.
        extra_block: uv map (analysis size) of texels to keep free of labels."""
        n_t = len(self.P)
        parent = list(range(n_t))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        edges = {}
        for i in range(n_t):
            if not self.ok[i]:
                continue
            keys = [(round(self.UV[i, k, 0], 4), round(self.UV[i, k, 1], 4), self.G[i]) for k in range(3)]
            for a, b in ((0, 1), (1, 2), (2, 0)):
                e = tuple(sorted((keys[a], keys[b])))
                edges.setdefault(e, []).append(i)
        for tris in edges.values():
            for a in tris:
                for b in tris:
                    if a >= b or self.N[a].dot(self.N[b]) < 0.96:
                        continue
                    if self.hand[a] != self.hand[b] or self.facing[a] != self.facing[b]:
                        continue
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[ra] = rb
        groups = {}
        for i in range(n_t):
            if self.ok[i]:
                groups.setdefault(find(i), []).append(i)
        out = []
        for idx in groups.values():
            idx = np.array(idx)
            wgt = self.uvarea[idx]
            if wgt.sum() < 1:
                continue
            right, up, n = self.text_axes(idx)
            er = (np.einsum("nij,j->ni", self.pj[idx], right) * wgt[:, None]).sum(0) / wgt.sum()
            et = (np.einsum("nij,j->ni", self.pj[idx], up) * wgt[:, None]).sum(0) / wgt.sum()
            if abs(cross2(er, et)) < 1e-6:
                continue
            out.append(Chart(self, idx, er, et, float(self.facing[idx[0]])))
        # first-person side first, then size
        out.sort(key=lambda c: (-int(c.facing > 0.5), -c.uvarea))
        owner = Image.new("I", (self.aw, self.ah), -1)
        d = ImageDraw.Draw(owner)
        for ci in range(len(out) - 1, -1, -1):
            for i in out[ci].idx:
                d.polygon([tuple(p) for p in self.uvpx[i]], fill=ci)
        owner = np.asarray(owner)
        for ci, ch in enumerate(out):
            ch.own(owner, ci)
        self.conflicts = np.zeros((self.ah, self.aw), bool)
        # texels another part of the gun also uses (not the mirrored other side of the same panel):
        # a label there would turn up, stretched or backwards, on that part too
        masks = []
        for ch in out:
            pts = self.uvpx[ch.idx].reshape(-1, 2)
            x0, y0 = np.floor(pts.min(0)).astype(int)
            x1, y1 = np.ceil(pts.max(0)).astype(int) + 1
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(self.aw, x1), min(self.ah, y1)
            im = Image.new("L", (max(1, x1 - x0), max(1, y1 - y0)), 0)
            d = ImageDraw.Draw(im)
            for i in ch.idx:
                d.polygon([tuple(p - (x0, y0)) for p in self.uvpx[i]], fill=255)
            n = (self.N[ch.idx] * self.area3[ch.idx, None]).sum(0)
            n = n / (np.linalg.norm(n) + 1e-9)
            a3 = self.area3[ch.idx].sum()
            ch.n = n
            # only a part that shows matters: not an end cap, not a sliver, not a face the texture is smeared over
            ch.blocks = abs(n.dot(self.F)) < 0.7 and a3 >= 0.0025 * self.area3.sum()
            ch.density = math.sqrt(ch.uvarea / max(a3, 1e-9))
            masks.append(((x0, y0, x1, y1), np.asarray(im) > 0, n))
        for a, ch in enumerate(out):
            (ax0, ay0, ax1, ay1), _, na = masks[a]
            conflict = np.zeros((ay1 - ay0, ax1 - ax0), bool)
            for b, ((bx0, by0, bx1, by1), mb, nb) in enumerate(masks):
                if b == a or bx1 <= ax0 or bx0 >= ax1 or by1 <= ay0 or by0 >= ay1:
                    continue
                if na.dot(nb) < -0.85:      # the other side of the same panel, mirrored: fine
                    continue
                if not out[b].blocks or out[b].density < 0.25 * ch.density:
                    continue
                ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
                conflict[iy0 - ay0:iy1 - ay0, ix0 - ax0:ix1 - ax0] |= mb[iy0 - by0:iy1 - by0, ix0 - bx0:ix1 - bx0]
            full = np.zeros((self.ah, self.aw), bool)
            full[ay0:ay1, ax0:ax1] = conflict
            self.conflicts[ay0:ay1, ax0:ax1] |= conflict
            if extra_block is not None:
                full |= extra_block
            ch.avoid(full)
        return out


class Chart:
    def __init__(self, mesh, idx, er, et, facing):
        self.mesh, self.idx, self.er, self.et, self.facing = mesh, idx, er, et, facing
        self.uvarea = mesh.uvarea[idx].sum()
        self.c = mesh.uvpx[idx].reshape(-1, 2).mean(0)
        self.k = math.sqrt(abs(er[0] * et[1] - er[1] * et[0]))        # texel density (px per game unit)
        self.M = np.stack([er / self.k, -et / self.k], axis=1)           # text-frame px -> uv px
        self.Minv = np.linalg.inv(self.M)
        tf = (mesh.uvpx[idx].reshape(-1, 2) - self.c) @ self.Minv.T
        self.lo = np.floor(tf.min(0)) - 2
        size = np.ceil(tf.max(0) - self.lo).astype(int) + 3
        mask = Image.new("L", tuple(size), 0)
        d = ImageDraw.Draw(mask)
        for tri in tf.reshape(-1, 3, 2):
            d.polygon([tuple(p - self.lo) for p in tri], fill=255)
        self.mask = np.asarray(mask) > 0
        self.free = self.mask.copy()
        self.mirrored = cross2(er, et) > 0

    def own(self, owner, ci):
        """Keep only the texels no chart with a higher priority uses."""
        hgt, wid = self.mask.shape
        ys, xs = np.mgrid[0:hgt, 0:wid].astype(np.float64) + 0.5
        pts = np.stack([xs + self.lo[0], ys + self.lo[1]], axis=-1) @ self.M.T + self.c
        u = np.clip(pts[..., 0].astype(int), 0, owner.shape[1] - 1)
        v = np.clip(pts[..., 1].astype(int), 0, owner.shape[0] - 1)
        self.mask &= owner[v, u] == ci
        self.free = self.mask.copy()

    def avoid(self, blocked):
        """No labels on these texels (uv space, analysis size)."""
        hgt, wid = self.mask.shape
        ys, xs = np.mgrid[0:hgt, 0:wid].astype(np.float64) + 0.5
        pts = np.stack([xs + self.lo[0], ys + self.lo[1]], axis=-1) @ self.M.T + self.c
        u = np.clip(pts[..., 0].astype(int), 0, blocked.shape[1] - 1)
        v = np.clip(pts[..., 1].astype(int), 0, blocked.shape[0] - 1)
        self.free &= ~blocked[v, u]

    def best_rect(self, aspect, margin=3, step=2):
        """Largest free rectangle (x0, y0, x1, y1, text height) in text-frame px for text of this aspect."""
        m = self.free
        if margin:
            im = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(2 * margin + 1))
            m = np.asarray(im) > 0
        m = m[::step, ::step]
        rows, cols = m.shape
        heights = [0] * (cols + 1)
        best = None
        for y in range(rows):
            row = m[y]
            for x in range(cols):
                heights[x] = heights[x] + 1 if row[x] else 0
            stack = []
            for x in range(cols + 1):
                hgt = heights[x] if x < cols else 0
                start = x
                while stack and stack[-1][1] >= hgt:
                    sx, sh = stack.pop()
                    w = x - sx
                    th = min(sh, w / aspect)
                    if best is None or th > best[4]:
                        best = (sx, y - sh + 1, x, y + 1, th)
                    start = sx
                stack.append((start, hgt))
        if not best:
            return None
        x0, y0, x1, y1, th = best
        return (x0 * step, y0 * step, x1 * step, y1 * step, th * step)

    def occupy(self, rect, pad=4):
        x0, y0, x1, y1 = [int(v) for v in rect[:4]]
        self.free[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = False

    def paste(self, canvas, label, rect, scale, clip=None, ci=None):
        """Warp label (RGBA, drawn upright for rect) into the texture canvas (size = scale x analysis).
        clip: owner map at canvas size; with ci, only this chart's own texels are painted."""
        x0, y0, x1, y1 = rect[:4]
        rx0, ry0 = x0 + self.lo[0], y0 + self.lo[1]
        lw, lh = label.size
        corners = np.array([[0, 0], [lw, 0], [0, lh], [lw, lh]], np.float64)
        uv = scale * self.c + (self.M @ (corners + scale * np.array([rx0, ry0])).T).T
        ox, oy = np.floor(uv.min(0)).astype(int) - 1
        ex, ey = np.ceil(uv.max(0)).astype(int) + 2
        ox, oy = max(0, ox), max(0, oy)
        ex, ey = min(canvas.width, ex), min(canvas.height, ey)
        if ex <= ox or ey <= oy:
            return
        Mi = self.Minv
        off = Mi @ (np.array([ox, oy], np.float64) - scale * self.c) - scale * np.array([rx0, ry0])
        data = (Mi[0, 0], Mi[0, 1], off[0], Mi[1, 0], Mi[1, 1], off[1])
        warped = label.transform((int(ex - ox), int(ey - oy)), Image.AFFINE, data, resample=Image.BICUBIC)
        if clip is not None:
            keep = clip[oy:ey, ox:ex] == ci
            a = np.asarray(warped.getchannel("A"), np.float32) * keep
            warped.putalpha(Image.fromarray(a.astype(np.uint8)))
        canvas.alpha_composite(warped, (int(ox), int(oy)))

    def whole(self):
        """The rectangle of the whole chart, for patterns that fill it."""
        return (0, 0, self.mask.shape[1], self.mask.shape[0], 0)


# ---------------------------------------------------------------------------
# rendering

def raster(scr, depth, uv, texs, tex_ids, lit, W, H):
    """Triangles: scr (n,3,2) px, depth (n,3) smaller = nearer, uv (n,3,2), texture index per tri (-1 = grey)."""
    img = np.zeros((H, W, 3), np.float32)
    alpha = np.zeros((H, W), np.float32)
    zbuf = np.full((H, W), np.inf, np.float32)
    for i in range(len(scr)):
        sx, sy = scr[i, :, 0], scr[i, :, 1]
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
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        z = w0 * depth[i, 0] + w1 * depth[i, 1] + w2 * depth[i, 2]
        zb = zbuf[y0:y1 + 1, x0:x1 + 1]
        m = inside & (z < zb)
        if not m.any():
            continue
        if tex_ids[i] >= 0:
            t = texs[tex_ids[i]]
            th, tw = t.shape[:2]
            u = (w0 * uv[i, 0, 0] + w1 * uv[i, 1, 0] + w2 * uv[i, 2, 0]) % 1.0
            v = (w0 * uv[i, 0, 1] + w1 * uv[i, 1, 1] + w2 * uv[i, 2, 1]) % 1.0
            col = t[(v * (th - 1)).astype(int), (u * (tw - 1)).astype(int)]
        else:
            col = np.broadcast_to(np.array([0.32, 0.27, 0.22], np.float32), m.shape + (3,))
        zb[m] = z[m]
        img[y0:y1 + 1, x0:x1 + 1][m] = np.clip(col[m] * lit[i], 0, 1)
        alpha[y0:y1 + 1, x0:x1 + 1][m] = 1
    return img, alpha


def lighting(N, light=(0.3, 0.6, 0.75)):
    L = np.array(light) / np.linalg.norm(light)
    return 0.5 + 0.7 * np.abs(N @ L)


def render_fp(mesh, tex_arr, W=560, H=420):
    """What the player sees: the camera at the origin of hand space, turned towards the gun."""
    tris = np.concatenate([mesh.P, mesh.other]) if len(mesh.other) else mesh.P
    uv = np.concatenate([mesh.UV, np.zeros((len(mesh.other), 3, 2))]) if len(mesh.other) else mesh.UV
    ids = np.array([0] * len(mesh.P) + [-1] * len(mesh.other))
    fwd = mesh.P.reshape(-1, 3).mean(0)
    fwd /= np.linalg.norm(fwd)
    left = np.cross(np.array([0, 0, 1.0]), fwd)
    left /= np.linalg.norm(left)
    up = np.cross(fwd, left)
    cam = np.stack([tris @ fwd, tris @ left, tris @ up], axis=-1)
    x = np.maximum(cam[..., 0], 0.5)
    gun = np.stack([mesh.P @ fwd, mesh.P @ left, mesh.P @ up], axis=-1)
    gx = np.maximum(gun[..., 0], 0.5)
    ext = max(np.abs(gun[..., 1] / gx).max() / (W / 2), np.abs(gun[..., 2] / gx).max() / (H / 2)) * 1.12
    f = 1.0 / ext
    ss = 2
    scr = np.stack([W * ss / 2 - f * ss * cam[..., 1] / x, H * ss / 2 - f * ss * cam[..., 2] / x], axis=-1)
    N = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    N /= np.maximum(np.linalg.norm(N, axis=1), 1e-9)[:, None]
    img, a = raster(scr, cam[..., 0], uv, [tex_arr], ids, lighting(N), W * ss, H * ss)
    out = Image.fromarray((np.dstack([img, a]) * 255).astype(np.uint8), "RGBA")
    return out.resize((W, H), Image.LANCZOS)


def render_side(mesh, tex_arr, side, W=520, H=240):
    """Orthographic side view of the gun alone: side +1 = its left flank (the first-person side), -1 = right."""
    P = mesh.P
    F = mesh.F
    Z = np.array([0, 0, 1.0])
    if mesh.tex in ("knife", "kabar"):
        up = np.cross(np.cross(F, Z), F)
        up = up / np.linalg.norm(up) if np.linalg.norm(up) > 0.2 else np.array([0, 0, 1.0])
    else:
        up = Z
    left = np.cross(up, F)       # towards the camera for side +1
    right = -F * side            # screen right: muzzle on the left for the left flank
    a = P @ right
    b = P @ up
    depth = -(P @ left) * side
    lo, hi = np.array([a.min(), b.min()]), np.array([a.max(), b.max()])
    span = max((hi[0] - lo[0]) / (W * 0.92), (hi[1] - lo[1]) / (H * 0.88))
    ss = 2
    scr = np.stack([(a - (lo[0] + hi[0]) / 2) / span * ss + W * ss / 2, -(b - (lo[1] + hi[1]) / 2) / span * ss + H * ss / 2], axis=-1)
    img, al = raster(scr, depth, mesh.UV, [tex_arr], np.zeros(len(P), int), lighting(mesh.N, light=(0.35 * side, 0.8 * side, 0.6)), W * ss, H * ss)
    out = Image.fromarray((np.dstack([img, al]) * 255).astype(np.uint8), "RGBA")
    return out.resize((W, H), Image.LANCZOS)




# ---------------------------------------------------------------------------
# small image helpers (as in build_skins)

def value_noise(size, cells, rng):
    g = rng.random((cells, cells)).astype(np.float32)
    im = Image.fromarray((g * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def fbm(size, rng, base=6, octaves=5):
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        out += amp * value_noise(size, base * (2 ** o), rng)
        total += amp
        amp *= 0.5
    return out / total


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def ramp(t, stops):
    t = np.clip(t, stops[0][0], stops[-1][0])
    out = np.zeros(t.shape + (3,), np.float32)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        m = (t >= t0) & (t <= t1)
        f = ((t[m] - t0) / max(t1 - t0, 1e-6))[..., None]
        out[m] = np.array(c0, np.float32) * (1 - f) + np.array(c1, np.float32) * f
    return out


WEAPS = ["colt", "luger", "thompson", "mp40", "knife", "kabar"]
_MESH = {}
_CHARTS = {}


def mesh_of(tex):
    if tex not in _MESH:
        _MESH[tex] = Mesh(tex)
    return _MESH[tex]


def charts_of(tex, tp_block=False):
    """The first-person charts of a texture, free space reset for a new skin.
    tp_block also keeps labels off texels the third-person model reuses on other
    parts; it costs the thompson and the MP 40 most of their label space, and the
    first-person view (4k, your own gun) matters more, so it is off."""
    if tex not in _CHARTS:
        block = None
        if tp_block:
            tp = Mesh(tex, view="tp")
            tp.charts()
            block = tp.conflicts
        _CHARTS[tex] = mesh_of(tex).charts(extra_block=block)
        for ch in _CHARTS[tex]:
            ch.free0 = ch.free.copy()
    for ch in _CHARTS[tex]:
        ch.free = ch.free0.copy()
    return _CHARTS[tex]


def build(theme, tex, div=1):
    """The finished texture of a text theme: float RGB array, 4k size / div."""
    return theme_build(theme, tex, div)


# ---------------------------------------------------------------------------
# text and label pieces

def text_block(lines, fontname, fill, size=120, spacing=0.12, stroke=0, stroke_fill=(0, 0, 0, 255), align="center"):
    if isinstance(lines, str):
        lines = [lines]
    f = font(fontname, size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    boxes = [probe.textbbox((0, 0), ln, font=f, stroke_width=stroke) for ln in lines]
    asc, desc = f.getmetrics()
    lh = asc + desc
    W = max(b[2] - b[0] for b in boxes) + 2 * stroke + 8
    H = int(lh * len(lines) + spacing * size * (len(lines) - 1)) + 2 * stroke + 8
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = stroke + 4
    for ln, b in zip(lines, boxes):
        w = b[2] - b[0]
        x = (W - w) // 2 - b[0] if align == "center" else stroke + 4 - b[0]
        d.text((x, y), ln, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        y += lh + spacing * size
    bb = img.getbbox()
    return img.crop(bb) if bb else img


def fit_into(img, w, h):
    s = min(w / img.width, h / img.height)
    nw, nh = max(1, int(img.width * s)), max(1, int(img.height * s))
    return img.resize((nw, nh), Image.LANCZOS), ((w - nw) // 2, (h - nh) // 2)


class Label:
    def __init__(self, draw, aspect, min_h=7, weight=1.0):
        self.draw, self.aspect, self.min_h, self.weight = draw, aspect, min_h, weight


def plate(lines, fontname, fg, bg=None, border=None, pad=0.22, radius=0.18, bw=0.07, stroke=0, stroke_fill=(0, 0, 0, 255),
          spacing=0.12, rot=0.0, grunge=0.0, min_h=7, align="center", seed=0):
    tb = text_block(lines, fontname, fg, spacing=spacing, stroke=stroke, stroke_fill=stroke_fill, align=align)
    aspect = (tb.width + 2 * pad * tb.height) / (tb.height * (1 + 2 * pad))

    def draw(w, h):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        p = pad * h / (1 + 2 * pad)
        r = int(radius * h)
        b = max(1, int(bw * h)) if border else 0
        if bg or border:
            d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=border or bg)
            if border and bg:
                d.rounded_rectangle((b, b, w - 1 - b, h - 1 - b), radius=max(0, r - b), fill=bg)
        t, (ox, oy) = fit_into(tb, max(1, int(w - 2 * p - 2 * b)), max(1, int(h - 2 * p - 2 * b)))
        img.alpha_composite(t, (int(p + b + ox), int(p + b + oy)))
        if rot:
            big = img.rotate(rot, resample=Image.BICUBIC, expand=True)
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            t, (ox, oy) = fit_into(big, w, h)
            img.alpha_composite(t, (ox, oy))
        if grunge:
            rng = np.random.default_rng(seed + w * 7 + h)
            n = rng.random((max(1, h // 3 + 1), max(1, w // 3 + 1))).astype(np.float32)
            n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR), np.float32) / 255
            a = np.asarray(img.getchannel("A"), np.float32) * np.clip((n - grunge) * 4, 0, 1)
            img.putalpha(Image.fromarray(a.astype(np.uint8)))
        return img
    return Label(draw, aspect, min_h)


def stamp(text, color=(200, 20, 30, 255), rot=-8, fontname="impact.ttf", seed=1):
    lab = plate([text], fontname, color, bg=None, border=None, pad=0.3, rot=rot, grunge=0.35, seed=seed)
    inner = lab.draw

    def draw(w, h):
        img = inner(w, h)
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(frame)
        bwid = max(1, int(h * 0.07))
        d.rounded_rectangle((bwid, bwid, w - 1 - bwid, h - 1 - bwid), radius=int(h * 0.12), outline=color, width=bwid)
        frame = frame.rotate(rot * 0.6, resample=Image.BICUBIC)
        frame.alpha_composite(img)
        rng = np.random.default_rng(seed + w)
        n = np.asarray(Image.fromarray((rng.random((h // 3 + 1, w // 3 + 1)) * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR), np.float32) / 255
        a = np.asarray(frame.getchannel("A"), np.float32) * np.clip((n - 0.25) * 3, 0, 1) * 0.9
        frame.putalpha(Image.fromarray(a.astype(np.uint8)))
        return frame
    return Label(draw, lab.aspect, 8)


def tape(text, band=(250, 205, 20, 255), ink=(15, 15, 15, 255), repeats=1, fontname="ariblk.ttf"):
    unit = text_block([text + "   \u2022   "], fontname, ink, size=120)
    word = text_block([text], fontname, ink, size=120)
    aspect = (unit.width * (repeats - 1) + word.width) / unit.height * 0.56 + 0.6

    def draw(w, h):
        img = Image.new("RGBA", (w, h), band)
        d = ImageDraw.Draw(img)
        edge = max(1, int(h * 0.09))
        d.rectangle((0, 0, w, edge), fill=ink)
        d.rectangle((0, h - edge, w, h), fill=ink)
        th = int(h * 0.56)
        u = unit.resize((max(1, int(unit.width * th / unit.height)), th), Image.LANCZOS)
        # whole repeats, centred; the last one without its separator
        wd = word.resize((max(1, int(word.width * th / word.height)), th), Image.LANCZOS)
        n = max(1, int((w - h * 0.5 - wd.width) // u.width) + 1)
        total = u.width * (n - 1) + wd.width
        x = int((w - total) / 2)
        for k in range(n):
            img.alpha_composite(wd if k == n - 1 else u, (x, (h - th) // 2))
            x += u.width
        # a little wear on the tape
        rng = np.random.default_rng(w * 3 + h)
        n = rng.random((h // 2 + 1, w // 2 + 1)).astype(np.float32)
        n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR), np.float32) / 255
        rgb = np.asarray(img, np.float32)
        rgb[..., :3] *= (0.9 + 0.1 * n)[..., None]
        return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGBA")
    return Label(draw, aspect, 8)


def glitch(lines, fontname="impact.ttf", fg=(255, 255, 255, 255), aspect_pad=0.2, seed=0):
    tb = text_block(lines, fontname, fg, spacing=0.05)
    aspect = tb.width * (1 + aspect_pad) / tb.height

    def draw(w, h):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        t, (ox, oy) = fit_into(tb, int(w / (1 + aspect_pad)), int(h * 0.86))
        off = max(1, int(h * 0.05))
        a = t.getchannel("A")
        for col, dx in (((255, 30, 60), -off), ((20, 230, 255), off)):
            layer = Image.new("RGBA", t.size, col + (0,))
            layer.putalpha(a.point(lambda v: int(v * 0.8)))
            img.alpha_composite(layer, (ox + dx + int(w * aspect_pad / 2 / (1 + aspect_pad)), oy))
        img.alpha_composite(t, (ox + int(w * aspect_pad / 2 / (1 + aspect_pad)), oy))
        rng = random.Random(seed + w)
        arr = np.asarray(img).copy()
        for _ in range(4):
            y0 = rng.randrange(0, max(1, h - 2))
            y1 = min(h, y0 + max(1, int(h * rng.uniform(0.04, 0.12))))
            arr[y0:y1] = np.roll(arr[y0:y1], rng.randint(-int(h * 0.3) - 1, int(h * 0.3) + 1), axis=1)
        return Image.fromarray(arr, "RGBA")
    return Label(draw, aspect, 8)


def price_tag(lines, bg=(220, 20, 30, 255), fg=(255, 255, 255, 255), fontname="ariblk.ttf"):
    tb = text_block(lines, fontname, fg, spacing=0.05)
    aspect = (tb.width * 1.45) / (tb.height * 1.3)

    def draw(w, h):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        k = h * 0.5
        pts = [(0, h / 2), (k, 0), (w - 1, 0), (w - 1, h - 1), (k, h - 1)]
        d.polygon(pts, fill=(255, 255, 255, 255))
        e = max(1, h * 0.06)
        d.polygon([(e * 1.6, h / 2), (k + e * 0.4, e), (w - 1 - e, e), (w - 1 - e, h - 1 - e), (k + e * 0.4, h - 1 - e)], fill=bg)
        r = h * 0.09
        d.ellipse((k * 0.55 - r, h / 2 - r, k * 0.55 + r, h / 2 + r), fill=(255, 255, 255, 255))
        t, (ox, oy) = fit_into(tb, int(w - k - h * 0.2), int(h * 0.74))
        img.alpha_composite(t, (int(k + ox), oy))
        return img
    return Label(draw, aspect, 8)


def receipt(lines, fontname="consolab.ttf"):
    tb = text_block(lines, fontname, (30, 30, 34, 255), spacing=0.25, align="left")
    aspect = (tb.width * 1.18) / (tb.height * 1.22)

    def draw(w, h):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        t, (ox, oy) = fit_into(tb, int(w / 1.18), int(h / 1.22))
        img.alpha_composite(t, (int(w * 0.09 / 1.18) + ox, oy))
        return img
    return Label(draw, aspect, 6)


def barcode(digits="5901234123457", seed=0):
    def draw(w, h):
        img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        d = ImageDraw.Draw(img)
        rng = random.Random(seed)
        x = w * 0.06
        bar_h = h * 0.72
        while x < w * 0.94:
            bwid = w * rng.choice((0.006, 0.012, 0.018))
            d.rectangle((x, h * 0.06, x + bwid, h * 0.06 + bar_h), fill=(0, 0, 0, 255))
            x += bwid + w * rng.choice((0.006, 0.012))
        t = text_block([digits], "consolab.ttf", (0, 0, 0, 255))
        t, (ox, oy) = fit_into(t, int(w * 0.8), int(h * 0.18))
        img.alpha_composite(t, (int(w * 0.1) + ox, int(h * 0.8)))
        return img
    return Label(draw, 2.6, 10)


def stencil(lines, color=(20, 20, 18, 255), seed=0):
    tb = text_block(lines, "STENCIL.TTF", color, spacing=0.05)
    aspect = tb.width * 1.12 / (tb.height * 1.15)

    def draw(w, h):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        t, (ox, oy) = fit_into(tb, int(w / 1.12), int(h / 1.15))
        soft = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        soft.alpha_composite(t, (int(w * 0.06) + ox, int(h * 0.07) + oy))
        over = soft.filter(ImageFilter.GaussianBlur(max(1, h * 0.03)))
        a = np.asarray(over.getchannel("A"), np.float32) * 0.45
        rng = np.random.default_rng(seed + w)
        speck = rng.random(a.shape) > 0.6
        base = np.asarray(soft.getchannel("A"), np.float32)
        alpha = np.maximum(base * 0.92, a * speck)
        out = Image.new("RGBA", (w, h), color[:3] + (0,))
        out.putalpha(Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8)))
        return out
    return Label(draw, aspect, 8)


# ---------------------------------------------------------------------------
# building one texture

class Ctx:
    def __init__(self, theme, tex, div):
        self.theme, self.tex = theme, tex
        self.mesh = mesh_of(tex)
        self.charts = charts_of(tex)
        W, H = SIZES[tex]
        self.W, self.H = W // div, H // div
        self.f = self.W / self.mesh.aw
        owner = Image.new("I", (self.W, self.H), -1)
        d = ImageDraw.Draw(owner)
        for ci in range(len(self.charts) - 1, -1, -1):
            for i in self.charts[ci].idx:
                d.polygon([tuple(p * self.f) for p in self.mesh.uvpx[i]], fill=ci)
        self.owner = np.asarray(owner)
        stock = Image.open(io.BytesIO(read_file(STOCK[tex]))).convert("RGB").resize((self.W, self.H), Image.LANCZOS)
        base = np.asarray(stock, np.float32) / 255.0
        l = luminance(base)
        self.shade = np.clip(0.35 + 0.95 * (l / (np.percentile(l, 98) + 1e-6)), 0.25, 1.25)
        self.rng = np.random.default_rng(zlib.crc32((tex + theme).encode()))
        self.prng = random.Random(zlib.crc32((theme + tex).encode()))
        self.pattern = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        self.labels = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        side = max(self.W, self.H)
        self.v, self.u = np.mgrid[0:self.H, 0:self.W].astype(np.float32) / side
        self.side = side

    def fbm(self, base, octaves):
        return fbm(self.side, self.rng, base=base, octaves=octaves)[:self.H, :self.W]

    def flat(self, color):
        return np.broadcast_to(np.array(color, np.float32), (self.H, self.W, 3)).copy()

    def fill(self, painter, min_area=40):
        """painter(w, h, chart, rng) -> RGBA in the chart's text frame; painted onto the pattern layer."""
        for ci, ch in enumerate(self.charts):
            if ch.mask.sum() < min_area:
                continue
            w, h = int(ch.mask.shape[1] * self.f), int(ch.mask.shape[0] * self.f)
            if w < 2 or h < 2:
                continue
            img = painter(w, h, ch, random.Random(self.prng.random()))
            if img is not None:
                ch.paste(self.pattern, img, ch.whole(), self.f, clip=self.owner, ci=ci)

    def place(self, labels, repeat=None, max_repeat=6, facing_weight=0.55, scale_cap=None, filler_min=16):
        """Greedy: each label into the free rectangle where it gets the largest; then fillers while they fit."""
        todo = list(labels)
        n_rep = 0
        while todo or (repeat and n_rep < max_repeat):
            filler = not todo
            if todo:
                lab = todo.pop(0)
            else:
                lab = repeat[n_rep % len(repeat)]
                n_rep += 1
            best = None
            variants = lab if isinstance(lab, (list, tuple)) else [lab]
            for ci, ch in enumerate(self.charts):
                if ch.free.sum() < 30:
                    continue
                for var in variants:
                    r = ch.best_rect(var.aspect, margin=2)
                    if not r:
                        continue
                    th = r[4] if not scale_cap else min(r[4], scale_cap)
                    # the area the text gets, not only its height: two lines of a long text can win
                    where = 1.0 if abs(ch.n[2]) < 0.75 else (0.75 if ch.n[2] > 0 else 0.4)      # sides first, then the top
                    score = th * var.aspect ** 0.35 * where * (1.0 if ch.facing > 0.5 else facing_weight) * var.weight
                    if best is None or score > best[0]:
                        best = (score, ci, r, th, var)
            if not best or best[3] < (best[4].min_h if not filler else max(best[4].min_h, filler_min)):
                if not todo:
                    break
                continue
            _, ci, r, th, lab = best
            ch = self.charts[ci]
            lw = th * lab.aspect
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            rect = (cx - lw / 2, cy - th / 2, cx + lw / 2, cy + th / 2)
            img = lab.draw(max(2, int(lw * self.f)), max(2, int(th * self.f)))
            ch.paste(self.labels, img, rect, self.f, clip=self.owner, ci=ci)
            ch.occupy(rect, pad=3)

    def compose(self, base, strong=True):
        panel = np.clip(0.55 + 0.55 * self.shade, 0.4, 1.2)[..., None] if strong else np.clip(0.75 + 0.3 * self.shade, 0.6, 1.1)[..., None]
        light = np.clip(0.82 + 0.2 * self.shade, 0.72, 1.06)[..., None]
        pat = np.asarray(self.pattern, np.float32) / 255.0
        out = base + (pat[..., :3] - base) * pat[..., 3:4]
        out = out * panel
        lab = np.asarray(self.labels, np.float32) / 255.0
        out = out + (lab[..., :3] * light - out) * lab[..., 3:4]
        return np.clip(out, 0, 1)


WORDS = ("sprzedam opla stan igła niemiec płakał jak sprzedawał tel pilne okazja zamienię na golfa bez rdzy "
         "garażowany pierwszy właściciel kupię mieszkanie oddam kota tanio super cena faktura vat do negocjacji "
         "silnik 1.6 benzyna gaz klima alufelgi przebieg 120 tys serwisowany zadbany kolor srebrny").split()
STICKERS = [("GG", "BAUHS93.TTF"), ("EZ", "BAUHS93.TTF"), ("NOOB", "ariblk.ttf"), ("1 HP", "impact.ttf"), ("LAG", "impact.ttf"),
            ("SKILL ISSUE", "ariblk.ttf"), ("ALT+F4", "consolab.ttf"), ("11/12", "ariblk.ttf"), ("CAMPER", "STENCIL.TTF"),
            ("RAGE", "HATTEN.TTF"), ("BOT", "impact.ttf"), ("AFK", "ariblk.ttf"), ("GG NO RE", "impact.ttf"), ("NT", "BAUHS93.TTF"),
            ("WuT", "ariblk.ttf"), ("MEDIC!", "GILSANUB.TTF"), ("FATBOSS", "GILSANUB.TTF"), ("PANZER", "STENCIL.TTF")]
STICKER_COLORS = [((255, 70, 70), (255, 255, 255)), ((255, 210, 40), (20, 20, 20)), ((60, 200, 255), (10, 20, 40)),
                  ((150, 90, 255), (255, 255, 255)), ((40, 220, 120), (10, 30, 20)), ((255, 120, 200), (255, 255, 255)),
                  ((20, 20, 24), (255, 255, 255)), ((255, 255, 255), (20, 20, 24)), ((255, 140, 20), (20, 20, 20))]
FAKE_NAMES = {"colt": "KOLT 1911 ORIGINAL", "luger": "LUGAR P-08 PREMIUM", "thompson": "TOMSON M1 PRO MAX", "mp40": "MP-40 ULTRA HD",
              "knife": "SAMURAI NIFE", "kabar": "KA-BAR DELUXE"}


def theme_build(theme, tex, div=4):
    c = Ctx(theme, tex, div)
    rng = c.rng

    if theme == "sprzedam_opla":
        base = c.flat((0.9, 0.88, 0.79)) * (0.94 + 0.08 * c.fbm(8, 3))[..., None]

        def news(w, h, ch, r):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            fs = max(5, int(16 / 4 * c.f))
            f = font("times.ttf", fs)
            fb = font("timesbd.ttf", int(fs * 1.3))
            colw = int(fs * 16)
            x = 2
            while x < w:
                y = 2
                while y < h:
                    if r.random() < 0.12:
                        d.text((x, y), r.choice(["MOTORYZACJA", "SPRZEDAM", "KUPIĘ", "ZAMIENIĘ", "OGŁOSZENIA"]), font=fb, fill=(20, 20, 20, 235))
                        y += int(fs * 1.7)
                    words = " ".join(r.choice(WORDS) for _ in range(12))
                    d.text((x, y), words, font=f, fill=(40, 40, 40, 200))
                    y += int(fs * 1.25)
                x += colw
                d.line((x - fs // 2, 0, x - fs // 2, h), fill=(60, 60, 60, 120), width=max(1, fs // 8))
            return img.crop((0, 0, w, h))
        c.fill(news)
        c.place([[plate(["SPRZEDAM OPLA"], "impact.ttf", (10, 10, 10, 255), bg=(255, 232, 40, 255), border=(10, 10, 10, 255)),
                  plate(["SPRZEDAM", "OPLA"], "impact.ttf", (10, 10, 10, 255), bg=(255, 232, 40, 255), border=(10, 10, 10, 255))],
                 stamp("PILNE!", seed=1),
                 plate(["STAN IGŁA"], "ariblk.ttf", (210, 20, 30, 255), bg=(255, 255, 255, 255), border=(10, 10, 10, 255)),
                 plate(["NIEMIEC PŁAKAŁ", "JAK SPRZEDAWAŁ"], "comicbd.ttf", (10, 10, 10, 255), bg=(255, 255, 255, 255), border=(10, 10, 10, 255)),
                 plate(["TEL. 600 100 100"], "arialbd.ttf", (10, 10, 10, 255), bg=(255, 255, 255, 235), border=(10, 10, 10, 255)),
                 stamp("OKAZJA", seed=2, rot=6)],
                repeat=[plate(["SPRZEDAM OPLA"], "impact.ttf", (10, 10, 10, 255), bg=(255, 232, 40, 255), border=(10, 10, 10, 255)),
                        plate(["STAN IGŁA"], "ariblk.ttf", (210, 20, 30, 255), bg=(255, 255, 255, 255), border=(10, 10, 10, 255))])
        return c.compose(base, strong=False)

    if theme == "skill_issue":
        n = c.fbm(3, 3)
        base = ramp((c.u * c.side / c.W) * 0.85 + 0.15 * n, [(0.0, (0.1, 0.85, 0.9)), (0.5, (0.45, 0.3, 0.95)), (1.0, (0.95, 0.35, 0.75))])

        def stripes(w, h, ch, r):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            step = max(4, int(h * 0.12)) if h < w else max(4, int(w * 0.12))
            for x in range(-h, w, step):
                d.line((x, h, x + h, 0), fill=(255, 255, 255, 38), width=max(1, step // 4))
            return img
        c.fill(stripes)
        navy = (14, 18, 48, 255)
        c.place([[plate(["SKILL ISSUE"], "ariblk.ttf", (255, 255, 255, 255), bg=navy, border=(120, 240, 255, 255)),
                  plate(["SKILL", "ISSUE"], "ariblk.ttf", (255, 255, 255, 255), bg=navy, border=(120, 240, 255, 255))],
                 plate(["GIT GUD"], "ariblk.ttf", (255, 255, 255, 255), bg=(200, 40, 140, 255), border=(255, 255, 255, 255)),
                 plate(["L2P"], "ariblk.ttf", navy, bg=(255, 255, 255, 255), border=navy),
                 plate(["DIAGNOSIS:", "SKILL ISSUE"], "ariblk.ttf", (255, 255, 255, 255), bg=navy, border=(255, 120, 200, 255)),
                 plate(["ZERO SKILL"], "ariblk.ttf", (255, 255, 255, 255), bg=(120, 60, 230, 255), border=(255, 255, 255, 255))],
                repeat=[plate(["SKILL ISSUE"], "ariblk.ttf", (255, 255, 255, 255), bg=navy, border=(120, 240, 255, 255))])
        return c.compose(base)

    if theme == "camper":
        n1, n2 = c.fbm(5, 4), c.fbm(7, 4)
        cols = [np.array(x, np.float32) for x in ((0.2, 0.22, 0.14), (0.36, 0.37, 0.22), (0.47, 0.4, 0.26), (0.09, 0.09, 0.08))]
        base = np.empty((c.H, c.W, 3), np.float32)
        base[:] = cols[0]
        base[n1 > 0.52] = cols[1]
        base[n2 > 0.56] = cols[2]
        base[(n1 < 0.4) & (n2 < 0.47)] = cols[3]
        ink, pale = (12, 12, 10, 255), (225, 220, 190, 255)
        c.place([stencil(["CAMPER"], ink, seed=1), stencil(["WARNING: CAMPER"], pale, seed=2), stencil(["DO NOT DISTURB"], ink, seed=3),
                 stencil(["CAMPING", "ZONE"], pale, seed=4), stencil(["11/12"], ink, seed=5)],
                repeat=[stencil(["CAMPER"], ink, seed=6), stencil(["CAMPER"], pale, seed=7)])
        return c.compose(base)

    if theme == "caution_noob":
        n = c.fbm(40, 3)
        streak = np.repeat(rng.random((c.H, 1)).astype(np.float32), c.W, axis=1)
        base = c.flat((0.17, 0.18, 0.2)) * (0.85 + 0.12 * n + 0.08 * streak)[..., None]
        c.place([[tape("CAUTION: NOOB"), tape("CAUTION: NOOB", repeats=2)], tape("DO NOT TOUCH"), tape("NOOB ZONE"), tape("WARNING: NOOB")],
                repeat=[tape("CAUTION: NOOB")], max_repeat=8)
        return c.compose(base)

    if theme == "receipt":
        base = c.flat((0.96, 0.96, 0.94)) * (0.96 + 0.05 * c.fbm(12, 3))[..., None]
        items = ["HEADSHOT x1", "PANZERFAUST", "MEDPACK x3", "AMMO PACK", "SKILL ISSUE", "RAGEQUIT", "TEAMKILL", "GIB x2",
                 "CAMPER", "DYNAMITE", "REVIVE", "SPAWNKILL"]

        def lines(w, h, ch, r):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            fs = max(5, int(15 / 4 * c.f))
            f = font("consola.ttf" if os.path.exists(os.path.join(FONTS, "consola.ttf")) else "cour.ttf", fs)
            y = 2
            while y < h:
                it = r.choice(items)
                price = f"{r.randint(0, 99)}.{r.randint(0, 99):02d}"
                txt = it + " " + "." * max(2, 26 - len(it) - len(price)) + " " + price
                d.text((3, y), txt, font=f, fill=(40, 40, 46, 235))
                y += int(fs * 1.5)
                if r.random() < 0.15:
                    d.text((3, y), "-" * 34, font=f, fill=(90, 90, 96, 150))
                    y += int(fs * 1.5)
            return img
        c.fill(lines)
        c.place([receipt(["*** RECEIPT ***"], "consolab.ttf"),
                 receipt(["TOTAL        11/12"], "consolab.ttf"),
                 barcode(),
                 receipt(["HEADSHOT x1 ........ 0.00", "SKILL ISSUE ...... 99.99", "CHANGE: 0 SKILL"], "consolab.ttf"),
                 receipt(["THANK YOU,", "COME AGAIN"], "consolab.ttf")],
                repeat=[receipt(["*** RECEIPT ***"], "consolab.ttf"), receipt(["TOTAL 11/12"], "consolab.ttf")], max_repeat=8)
        return c.compose(base, strong=False)

    if theme == "sticker_bomb":
        base = c.flat((0.1, 0.1, 0.11)) * (0.9 + 0.15 * c.fbm(20, 2))[..., None]

        def stickers(w, h, ch, r):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            short = min(w, h)
            count = int(w * h / (short * short) * 2.2) + 2
            for _ in range(count * 3):
                text, fontname = r.choice(STICKERS)
                bg, fg = r.choice(STICKER_COLORS)
                sh = short * r.uniform(0.35, 0.75)
                tb = text_block([text], fontname, fg + (255,))
                sw = sh * (tb.width / tb.height) * 0.72 + sh * 0.5
                st = Image.new("RGBA", (int(sw) + 4, int(sh) + 4), (0, 0, 0, 0))
                d = ImageDraw.Draw(st)
                shape = r.random()
                bwid = max(1, int(sh * 0.08))
                if shape < 0.25 and len(text) <= 3:
                    st = Image.new("RGBA", (int(sh) + 4, int(sh) + 4), (0, 0, 0, 0))
                    d = ImageDraw.Draw(st)
                    d.ellipse((1, 1, sh + 2, sh + 2), fill=(255, 255, 255, 255))
                    d.ellipse((1 + bwid, 1 + bwid, sh + 2 - bwid, sh + 2 - bwid), fill=bg + (255,))
                    t, (ox, oy) = fit_into(tb, int(sh * 0.62), int(sh * 0.5))
                    st.alpha_composite(t, (int(sh * 0.19) + 2 + ox, int(sh * 0.25) + 2 + oy))
                else:
                    d.rounded_rectangle((1, 1, sw + 2, sh + 2), radius=int(sh * 0.22), fill=(255, 255, 255, 255))
                    d.rounded_rectangle((1 + bwid, 1 + bwid, sw + 2 - bwid, sh + 2 - bwid), radius=int(sh * 0.16), fill=bg + (255,))
                    t, (ox, oy) = fit_into(tb, int(sw - sh * 0.4), int(sh * 0.56))
                    st.alpha_composite(t, (int(sh * 0.2) + 2 + ox, int(sh * 0.22) + 2 + oy))
                st = st.rotate(r.uniform(-14, 14), resample=Image.BICUBIC, expand=True)
                sh_img = Image.new("RGBA", st.size, (0, 0, 0, 0))
                sh_img.putalpha(st.getchannel("A").point(lambda v: v * 0.45))
                x, y = r.uniform(-st.width * 0.3, w - st.width * 0.7), r.uniform(-st.height * 0.3, h - st.height * 0.7)
                img.alpha_composite(sh_img, (int(x + short * 0.03), int(y + short * 0.04))) if x + short * 0.03 >= 0 and y + short * 0.04 >= 0 else None
                tmp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                tmp.paste(st, (int(x), int(y)), st)
                img.alpha_composite(tmp)
            return img
        c.fill(stickers, min_area=150)
        return c.compose(base, strong=False)

    if theme == "knockoff":
        n = c.fbm(6, 3)
        base = ramp(n, [(0.2, (0.95, 0.45, 0.68)), (0.8, (1.0, 0.62, 0.8))])
        seam = np.abs(((c.u + c.v * 0.3) * 9) % 1.0 - 0.5) < 0.004
        base[seam] *= 0.8
        yellow, white, red, blk = (255, 225, 40, 255), (255, 255, 255, 255), (220, 20, 30, 255), (15, 15, 15, 255)
        two = FAKE_NAMES[tex].split(" ", 1) if " " in FAKE_NAMES[tex] else [FAKE_NAMES[tex]]
        c.place([[plate([FAKE_NAMES[tex]], "comicbd.ttf", blk, bg=yellow, border=blk), plate(two, "comicbd.ttf", blk, bg=yellow, border=blk)],
                 plate(["MADE IN CHINA"], "arialbd.ttf", blk, bg=white, border=blk, radius=0.05),
                 plate(["100% ORIGINAL"], "ariblk.ttf", white, bg=red, border=white),
                 plate(["NOT A TOY", "3+"], "arialbd.ttf", blk, bg=white, border=blk, radius=0.05),
                 plate(["BATTERIES NOT", "INCLUDED"], "comicbd.ttf", blk, bg=yellow, border=blk),
                 plate(["3 DAY WARRANTY"], "ariblk.ttf", white, bg=(40, 90, 220, 255), border=white)],
                repeat=[plate(["MADE IN CHINA"], "arialbd.ttf", blk, bg=white, border=blk, radius=0.05),
                        plate([FAKE_NAMES[tex]], "comicbd.ttf", blk, bg=yellow, border=blk)])
        return c.compose(base, strong=False)

    if theme == "connection_interrupted":
        base = c.flat((0.02, 0.025, 0.04)) * (0.8 + 0.4 * c.fbm(30, 2))[..., None]

        def crt(w, h, ch, r):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            step = max(2, int(3 * c.f / 4 * 2))
            for y in range(0, h, step):
                d.line((0, y, w, y), fill=(40, 255, 120, 22), width=1)
            for _ in range(int(h / max(1, step * 6)) + 2):
                y0 = r.uniform(0, h)
                hh = r.uniform(1, max(2, h * 0.05))
                x0 = r.uniform(0, w)
                col = r.choice([(255, 30, 90, 120), (30, 220, 255, 110), (255, 255, 255, 60)])
                d.rectangle((x0, y0, x0 + r.uniform(w * 0.05, w * 0.5), y0 + hh), fill=col)
            return img
        c.fill(crt)
        c.place([[glitch(["CONNECTION INTERRUPTED"], seed=1), glitch(["CONNECTION", "INTERRUPTED"], seed=1)], glitch(["PING 999"], seed=2), glitch(["LAG"], seed=3),
                 plate(["RECONNECT?"], "consolab.ttf", (40, 255, 120, 255), bg=(0, 0, 0, 200), border=(40, 255, 120, 255), radius=0.05),
                 glitch(["LOSS 100%"], seed=4)],
                repeat=[glitch(["CONNECTION INTERRUPTED"], seed=5), glitch(["LAG"], seed=6)])
        return c.compose(base, strong=False)

    if theme == "bus_ticket":
        g = np.sin((c.u * 90 + np.sin(c.v * 40) * 2.5) * math.pi) * np.sin((c.v * 70 + np.cos(c.u * 33) * 2.0) * math.pi)
        line = np.clip(1 - np.abs(g) / 0.08, 0, 1)
        base = c.flat((0.93, 0.95, 0.86))
        base = base + (np.array([0.3, 0.62, 0.45], np.float32) - base) * (line * 0.6)[..., None]

        def micro(w, h, ch, r):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            fs = max(5, int(11 / 4 * c.f))
            f = font("arialbd.ttf", fs)
            for y in range(0, h, int(fs * 1.6)):
                d.text((2 - (y % 7) * fs // 3, y), "BUS  " * 60, font=f, fill=(40, 100, 70, 120))
            return img
        c.fill(micro)
        violet = (110, 40, 160, 255)
        c.place([[plate(["NEXT STOP:", "YOUR MOTHER'S HOUSE"], "arialbd.ttf", (20, 60, 40, 255), bg=(255, 255, 255, 200), border=(20, 60, 40, 255), radius=0.05),
                  plate(["NEXT STOP:", "YOUR MOTHER'S", "HOUSE"], "arialbd.ttf", (20, 60, 40, 255), bg=(255, 255, 255, 200), border=(20, 60, 40, 255), radius=0.05)],
                 plate(["SINGLE FARE"], "ariblk.ttf", (20, 60, 40, 255), bg=(255, 255, 255, 200), border=(20, 60, 40, 255), radius=0.05),
                 plate(["$3.40"], "ariblk.ttf", (20, 60, 40, 255)),
                 plate(["25.09.26  11:12  ROUTE 69"], "consolab.ttf", violet, grunge=0.2, seed=3),
                 plate(["VALIDATE YOUR TICKET!"], "ariblk.ttf", (200, 20, 30, 255)),
                 barcode("0069 1112 2026")],
                repeat=[plate(["SINGLE FARE"], "ariblk.ttf", (20, 60, 40, 255), bg=(255, 255, 255, 200), border=(20, 60, 40, 255), radius=0.05)],
                max_repeat=8)
        return c.compose(base, strong=False)

    if theme == "sale":
        base = c.flat((1.0, 0.84, 0.08)) * (0.95 + 0.06 * c.fbm(10, 2))[..., None]

        def dots(w, h, ch, r):
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            step = max(4, int(min(w, h) * 0.18))
            rad = step * 0.22
            for y in range(0, h + step, step):
                for x in range((y // step % 2) * step // 2, w + step, step):
                    d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=(230, 60, 20, 60))
            return img
        c.fill(dots)
        c.place([price_tag(["SALE"]), price_tag(["-90%"]), plate(["ONLY", "$2.99"], "ariblk.ttf", (220, 20, 30, 255), bg=(255, 255, 255, 255), border=(220, 20, 30, 255)),
                 price_tag(["BUY 1 GET 1 FREE"], bg=(20, 90, 200, 255)), plate(["LAST ONES!"], "ariblk.ttf", (255, 255, 255, 255), bg=(220, 20, 30, 255)),
                 plate(["HOT DEAL"], "ariblk.ttf", (220, 20, 30, 255), bg=(255, 255, 255, 255), border=(220, 20, 30, 255))],
                repeat=[price_tag(["-90%"]), price_tag(["SALE"])])
        return c.compose(base, strong=False)

    raise ValueError(theme)


THEMES = [("skill_issue", "Skill Issue"), ("camper", "Camper"), ("caution_noob", "Caution: Noob"), ("receipt", "Receipt"),
          ("sticker_bomb", "Sticker Bomb"), ("knockoff", "Knockoff"), ("connection_interrupted", "Connection Interrupted"),
          ("bus_ticket", "Bus Ticket"), ("sale", "Sale -90%"), ("sprzedam_opla", "Sprzedam Opla (PL)")]



def board(out, themes, first=37):
    """Proposal board: the first-person side of every weapon, plus first person colt and thompson."""
    sw, sh, fw, fh = 400, 185, 300, 225
    left = 250
    rowh = max(sh, fh) + 12
    Wb = left + sw * len(WEAPS) + fw * 2
    b = Image.new("RGB", (Wb, 50 + rowh * len(themes)), (30, 32, 36))
    d = ImageDraw.Draw(b)
    fb = font("arialbd.ttf", 26)
    fs = font("arial.ttf", 18)
    for j, name in enumerate(WEAPS):
        d.text((left + j * sw + 12, 12), name, font=fb, fill=(255, 210, 60))
    d.text((left + len(WEAPS) * sw + 12, 12), "FP colt", font=fb, fill=(255, 210, 60))
    d.text((left + len(WEAPS) * sw + fw + 12, 12), "FP thompson", font=fb, fill=(255, 210, 60))
    for i, theme in enumerate(themes):
        y = 50 + i * rowh
        if i % 2:
            d.rectangle((0, y, Wb, y + rowh), fill=(36, 38, 43))
        d.text((14, y + rowh // 2 - 26), f"{first + i}.", font=fb, fill=(255, 210, 60))
        d.text((64, y + rowh // 2 - 26), dict(THEMES).get(theme, theme), font=fb, fill=(255, 255, 255))
        d.text((64, y + rowh // 2 + 8), theme, font=fs, fill=(150, 155, 165))
        t0 = time.time()
        for j, tex in enumerate(WEAPS):
            arr = theme_build(theme, tex, div=4)
            m = mesh_of(tex)
            s = render_side(m, arr, +1, sw, sh)
            b.paste(s, (left + j * sw, y + (rowh - sh) // 2), s)
            if tex in ("colt", "thompson"):
                fp = render_fp(m, arr, fw, fh)
                b.paste(fp, (left + len(WEAPS) * sw + (0 if tex == "colt" else fw), y + (rowh - fh) // 2), fp)
        print(theme, round(time.time() - t0, 1), "s", flush=True)
    b.save(out, quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["board"])
    ap.add_argument("out")
    ap.add_argument("--paks", nargs="+", required=True)
    ap.add_argument("--themes", nargs="*")
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_skins
    set_reader(build_skins.Paks(args.paks).read)
    board(args.out, args.themes or [t for t, _ in THEMES])


if __name__ == "__main__":
    main()
