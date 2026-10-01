"""The punishment prop (cgame b17): a pink toy with its balls on a spring, on top of a player's helmet.

An admin puts it on a player from the FatBoss website or Discord; fatboss.lua passes it on in the player's
configstring and the cgame draws the two models on the helmet (the spring from the top of the helmet, the toy on
the spring) and wobbles them with the head's movement. Units are the helmet model's own (it is about 11 wide).

Writes (the cgame pk3):
  fatboss/pk3/models/fbprop/dong.md3, spring.md3     the models, +z up from their foot
  fatboss/pk3/models/fbprop/pink.jpg, steel.jpg, shine.jpg
  fatboss/pk3/scripts/fatboss_prop.shader

    py fatboss/skins/build_prop.py
"""
import math
import os
import struct

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PK3 = os.path.normpath(os.path.join(HERE, "..", "pk3"))
DIR = "models/fbprop"
TOY_LENGTH = 6.0           # the toy, foot to tip
SPRING_HEIGHT = 2.0        # the cgame puts the toy's foot this high over the helmet (FB_PROP_SPRING)
K = 1.3                    # the toy's girth


# ------------------------------------------------------------------------------------------------ shapes
def lathe(profile, segs=24):
    """A surface of revolution about +z: profile [(z, r), ...] bottom to top -> verts, normals, uvs, tris."""
    prof = np.asarray(profile, np.float64)
    n = segs + 1                                   # a seam column, so the texture wraps
    a = np.linspace(0, 2 * math.pi, n)
    dz, dr = np.gradient(prof[:, 0]), np.gradient(prof[:, 1])
    V, N, UV = [], [], []
    for i, ((z, r), gz, gr) in enumerate(zip(prof, dz, dr)):
        nr, nz = gz, -gr
        ln = math.hypot(nr, nz) or 1.0
        for j, t in enumerate(a):
            V.append((r * math.cos(t), r * math.sin(t), z))
            N.append((nr / ln * math.cos(t), nr / ln * math.sin(t), nz / ln))
            UV.append((j / segs, i / (len(prof) - 1)))
    tris = []
    for i in range(len(prof) - 1):
        for j in range(segs):
            p, q = i * n + j, i * n + j + 1
            tris += [(p, p + n, q), (q, p + n, q + n)]
    return np.array(V), np.array(N), np.array(UV), np.array(tris)


def toy_profile(L):
    """Cartoon style: a suction cup, a smooth shaft, a rim and a round head, z from 0 (cup) to L (tip)."""
    pts = [(0.0, 0.0), (0.0, 1.15), (0.08, 1.25), (0.2, 1.2), (0.32, 0.9), (0.45, 0.62)]
    shaft_end = L - 1.25
    for z in np.linspace(0.6, shaft_end, 10):
        k = (z - 0.6) / max(shaft_end - 0.6, 1e-6)
        pts.append((z, 0.56 + 0.05 * math.sin(k * math.pi)))
    pts += [(L - 1.15, 0.6), (L - 1.05, 0.71), (L - 0.95, 0.7)]
    for k in np.linspace(0, 1, 9)[1:]:
        ang = k * math.pi / 2
        pts.append((L - 0.95 + 0.95 * math.sin(ang), 0.7 * math.cos(ang) + 1e-3))
    pts.append((L, 0.0))
    return [(z, r * K) for z, r in pts]


def ball(r):
    prof = [(-r * math.cos(a), r * math.sin(a)) for a in np.linspace(0, math.pi, 12)]
    prof[0], prof[-1] = (-r, 0.0), (r, 0.0)
    return lathe(prof, 16)


def merge(parts):
    V, N, UV, T, off = [], [], [], [], 0
    for v, n, uv, t in parts:
        V.append(v), N.append(n), UV.append(uv), T.append(t + off)
        off += len(v)
    return np.concatenate(V), np.concatenate(N), np.concatenate(UV), np.concatenate(T)


def toy():
    parts = [lathe(toy_profile(TOY_LENGTH))]
    r = 0.62 * K
    for side in (-1, 1):
        v, n, uv, t = ball(r)
        # the balls at the foot, on the side that faces forward (+x), side by side
        parts.append((v + (0.62 * K, side * 0.6 * K, 0.55 + r * 0.95), n, uv, t))
    return merge(parts)


def spring(h=SPRING_HEIGHT, turns=5, r=0.5, wire=0.13, segs=8):
    t = np.linspace(0, 1, turns * 20 + 1)
    path = np.stack([r * np.cos(t * turns * 2 * math.pi), r * np.sin(t * turns * 2 * math.pi), t * h], 1)
    # a short straight foot and top, so it sits on the helmet and holds the cup
    path = np.concatenate([[(r, 0, -0.1)], path, [path[-1] + (0, 0, 0.1)]])
    tang = np.gradient(path, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    V, N, UV = [], [], []
    for i, (p, tg) in enumerate(zip(path, tang)):
        u = np.cross(tg, (0.0, 0.0, 1.0) if abs(tg[2]) < 0.9 else (1.0, 0.0, 0.0))
        u /= np.linalg.norm(u)
        w = np.cross(tg, u)
        for k in range(segs + 1):
            a = 2 * math.pi * k / segs
            nrm = math.cos(a) * u + math.sin(a) * w
            V.append(p + wire * nrm)
            N.append(nrm)
            UV.append((k / segs, i / (len(path) - 1)))
    n = segs + 1
    tris = []
    for i in range(len(path) - 1):
        for k in range(segs):
            p, q = i * n + k, i * n + k + 1
            tris += [(p, q, p + n), (q, q + n, p + n)]
    V, N = np.array(V), np.array(N)
    return V, N, np.array(UV), outward(V, N, np.array(tris))


def outward(V, N, T):
    """Every triangle counter-clockwise seen from outside (its normal along the vertex normals)."""
    fn = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    flip = (fn * N[T].mean(1)).sum(1) < 0
    T = T.copy()
    T[flip] = T[flip][:, [0, 2, 1]]
    return T


# ------------------------------------------------------------------------------------------------ files
def md3_bytes(name, shader, V, N, UV, T):
    """A one-frame, one-surface MD3. T: counter-clockwise seen from outside; written the other way round, as the
    game's own models are (the renderer culls GL_FRONT: the stock helmet's triangles all wind clockwise)."""
    nv, nt = len(V), len(T)
    assert nv < 4096 and nt < 8192, (nv, nt)
    ofs_tri = 108
    ofs_sh = ofs_tri + nt * 12
    ofs_st = ofs_sh + 68
    ofs_xyz = ofs_st + nv * 8
    surf_end = ofs_xyz + nv * 8
    surf = bytearray(b"IDP3" + b"prop".ljust(64, b"\0"))
    surf += struct.pack("<10i", 0, 1, 1, nv, nt, ofs_tri, ofs_sh, ofs_st, ofs_xyz, surf_end)
    for a, b, c in T:
        surf += struct.pack("<3i", int(a), int(c), int(b))
    surf += shader.encode().ljust(64, b"\0") + struct.pack("<i", 0)
    for a, b in UV:
        surf += struct.pack("<2f", float(a), float(b))
    for (x, y, z), (nx, ny, nz) in zip(V, N):
        # tr_model.c: x = cos(lat) sin(lng), y = sin(lat) sin(lng), z = cos(lng); lat the high byte
        lat = int(round(math.atan2(ny, nx) * 256 / (2 * math.pi))) & 255
        lng = int(round(math.acos(max(-1.0, min(1.0, nz))) * 256 / (2 * math.pi))) & 255
        surf += struct.pack("<3hH", int(round(x * 64)), int(round(y * 64)), int(round(z * 64)), (lat << 8) | lng)
    mins, maxs = V.min(0), V.max(0)
    radius = float(np.linalg.norm(np.maximum(np.abs(mins), np.abs(maxs))))
    frame = struct.pack("<3f3f3ff", *mins, *maxs, 0.0, 0.0, 0.0, radius) + b"fbprop".ljust(16, b"\0")
    ofs_frames = 108
    ofs_surf = ofs_frames + 56
    out = bytearray(b"IDP3" + struct.pack("<i", 15) + name.encode()[:63].ljust(64, b"\0"))
    out += struct.pack("<9i", 0, 1, 0, 1, 0, ofs_frames, ofs_surf, ofs_surf, ofs_surf + len(surf))
    out += frame + surf
    return bytes(out)


def images(root):
    d = os.path.join(root, DIR)
    os.makedirs(d, exist_ok=True)
    yy = np.linspace(0, 1, 64)[:, None, None]
    pink = np.clip(np.array([1.0, 0.36, 0.68]) * (0.9 + 0.12 * yy) + np.zeros((64, 64, 3)), 0, 1)
    Image.fromarray((pink * 255 + 0.5).astype(np.uint8)).save(os.path.join(d, "pink.jpg"), quality=92)
    steel = np.clip(np.array([0.62, 0.63, 0.67]) * (0.85 + 0.25 * yy) + np.zeros((64, 64, 3)), 0, 1)
    Image.fromarray((steel * 255 + 0.5).astype(np.uint8)).save(os.path.join(d, "steel.jpg"), quality=92)
    # the reflection: dark, one soft light above, a strip light at the side (the skins' studio, small)
    y, x = np.mgrid[0:64, 0:64] / 63.0
    v = 0.05 + 0.9 * np.exp(-(((x - 0.32) / 0.14) ** 2 + ((y - 0.2) / 0.1) ** 2) ** 2) + 0.5 * np.exp(-(((x - 0.85) / 0.04) ** 2)) * (y > 0.15) * (y < 0.7)
    Image.fromarray((np.clip(np.dstack([v, v, v]), 0, 1) * 255 + 0.5).astype(np.uint8)).save(os.path.join(d, "shine.jpg"), quality=92)


SHADER = """// FatBoss punishment prop (cgame b17) - generated by fatboss/skins/build_prop.py, do not edit

models/fbprop/pink
{
	nopicmip
	{
		map models/fbprop/pink.jpg
		rgbGen lightingDiffuse
	}
	{
		map models/fbprop/shine.jpg
		tcGen environment
		blendFunc GL_ONE GL_ONE
		rgbGen const ( 0.55 0.5 0.52 )
	}
}

models/fbprop/steel
{
	nopicmip
	{
		map models/fbprop/steel.jpg
		rgbGen lightingDiffuse
	}
	{
		map models/fbprop/shine.jpg
		tcGen environment
		blendFunc GL_ONE GL_ONE
		rgbGen const ( 0.6 0.6 0.6 )
	}
}
"""


def main():
    images(PK3)
    d = os.path.join(PK3, DIR)
    V, N, UV, T = toy()
    with open(os.path.join(d, "dong.md3"), "wb") as f:
        f.write(md3_bytes("dong", "models/fbprop/pink", V, N, UV, outward(V, N, T)))
    V, N, UV, T = spring()
    with open(os.path.join(d, "spring.md3"), "wb") as f:
        f.write(md3_bytes("spring", "models/fbprop/steel", V, N, UV, T))
    with open(os.path.join(PK3, "scripts", "fatboss_prop.shader"), "w", newline="\n") as f:
        f.write(SHADER)
    for name in sorted(os.listdir(d)):
        print(f"{DIR}/{name}: {os.path.getsize(os.path.join(d, name))} bytes")


if __name__ == "__main__":
    main()
