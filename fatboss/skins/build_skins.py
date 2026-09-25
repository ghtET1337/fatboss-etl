"""FatBoss weapon skins: builds the skins pk3 tree and the cgame's skin table.

The finishes are made from the stock ET / ET: Legacy weapon textures and the
models' surface lists, so the game's own paks must be at hand (they are not in
this repo), plus Codex's defender pk3 for his two finished skins:

  python fatboss/skins/build_skins.py --paks legacy_v2.86.0.pk3 pak0.pk3 --codex defender_v0_7.pk3

Writes
  fatboss/pk3-skins/          textures, shaders and .skin files; CI packs it as
                              zzz_fatboss_skins_<fatboss/skins/VERSION>.pk3
  src/cgame/cg_fatboss_skins.inc   the table the cgame finds them with

Each finish comes in three sizes:
  4k  first person, your own weapon
  2k  first person, the player you spectate
  1k  third person, everybody else's weapon
The cgame steps a first-person skin down to the next size when the player's
hunk (com_hunkMegs) has no room for the upload, so first-person .skin files
exist in all three sizes.
All shaders are nopicmip + nocompress, so r_picmip and texture compression on
the player's side never blur them.

Needs numpy and Pillow.
"""
import argparse
import io
import math
import os
import re
import shutil
import struct
import zipfile
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import textskins

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(REPO, "fatboss", "pk3-skins")
INC = os.path.join(REPO, "src", "cgame", "cg_fatboss_skins.inc")
OWN_PK3_DIR = os.path.join(REPO, "fatboss", "pk3")   # our thompson.weap and its models

TEXTURES = {
    # name: (stock image, 4k size (w, h), shader the stock models use for it)
    "colt": ("models/weapons2/colt/colt_yd.tga", (4096, 4096), "models/weapons2/colt/colt4"),
    "luger": ("models/weapons2/luger/luger7_yd.tga", (4096, 4096), "models/weapons2/luger/luger7"),
    "thompson": ("models/weapons2/thompson/thompson_la_yd.tga", (4096, 4096), "models/weapons2/thompson/thompson_la"),
    "mp40": ("models/weapons2/mp40/gun11_yd.tga", (4096, 4096), "models/weapons2/mp40/gun11"),
    "knife": ("models/weapons2/knife/knife_yd.tga", (4096, 1024), "models/weapons2/knife/knife1a"),
    "kabar": ("models/weapons2/knife_kbar/knife_yd.jpg", (4096, 2048), "models/weapons2/knife_kbar/knife_yd"),
}
ALL = tuple(TEXTURES)

# theme: (textures it has, strength of the environment reflection)
THEMES = {
    "gold": (ALL, (0.85, 0.75, 0.50)),
    "polska": (ALL, (0.35, 0.35, 0.35)),
    "neon": (ALL, (0.30, 0.34, 0.40)),
    "camo": (ALL, (0.10, 0.10, 0.10)),
    "damascus": (("knife", "kabar"), (0.70, 0.72, 0.76)),
    "defender": (("colt",), None),              # Codex's finished skins, their own lit reflection
    "wut": (("thompson", "kabar"), None),
    # picked from the second proposal board (2026-09-24)
    "cyber": (ALL, (0.30, 0.34, 0.40)),
    "plasma": (ALL, (0.35, 0.30, 0.45)),
    "airstrike": (ALL, (0.25, 0.22, 0.30)),
    # text skins, picked from the third proposal board (2026-09-25); made by textskins.py
    "skill_issue": (ALL, (0.12, 0.12, 0.14)),
    "caution_noob": (ALL, (0.12, 0.12, 0.12)),
    "sticker_bomb": (ALL, (0.10, 0.10, 0.10)),
    "knockoff": (ALL, (0.18, 0.14, 0.16)),
    "connection_interrupted": (ALL, (0.08, 0.08, 0.10)),
    "sale": (ALL, (0.10, 0.10, 0.08)),
}
TEXT_THEMES = ("skill_issue", "caution_noob", "sticker_bomb", "knockoff", "connection_interrupted", "sale")
CODEX = {
    # (theme, texture): (first person 4K source, third person 4K source)
    ("defender", "colt"): ("models/weapons2/colt/defender_native4k.tga",) * 2,
    ("wut", "thompson"): ("models/weapons2/thompson/wut_native4k_v03.tga", "models/weapons2/thompson/wut_world4k_v03.tga"),
    ("wut", "kabar"): ("models/weapons2/knife/wut_allies_native4k_v04.tga", "models/weapons2/knife/wut_allies_world4k_v04.tga"),
}
CODEX_ENV = "models/weapons2/colt/defender_soft_env.tga"

# loadout slots, in the order of the fbskin server command
SLOTS = ("knife", "colt", "luger", "thompson", "mp40")
WEAPONS = [
    # weapon, slot, texture, .weap file
    ("WP_KNIFE", "knife", "knife", "knife"),
    ("WP_KNIFE_KABAR", "knife", "kabar", "knife_kbar"),
    ("WP_COLT", "colt", "colt", "colt"),
    ("WP_SILENCED_COLT", "colt", "colt", "silenced_colt"),
    ("WP_AKIMBO_COLT", "colt", "colt", "akimbo_colt"),
    ("WP_AKIMBO_SILENCEDCOLT", "colt", "colt", "akimbo_silenced_colt"),
    ("WP_LUGER", "luger", "luger", "luger"),
    ("WP_SILENCER", "luger", "luger", "silenced_luger"),
    ("WP_AKIMBO_LUGER", "luger", "luger", "akimbo_luger"),
    ("WP_AKIMBO_SILENCEDLUGER", "luger", "luger", "akimbo_silenced_luger"),
    ("WP_THOMPSON", "thompson", "thompson", "thompson"),
    ("WP_MP40", "mp40", "mp40", "mp40"),
]
RES = {"4k": 1, "2k": 2, "1k": 4}   # divisor of the 4k size
# The UDP download (the fallback when the web redirect fails) numbers its 1 KB
# blocks with a signed 16-bit counter, so it stalls for good at 32 MiB. Every
# skins pk3 stays under that with room to spare; CI refuses anything bigger.
PART_LIMIT = 30 * 1024 * 1024
PARTS = os.path.join(HERE, "parts.txt")
JPEG_QUALITY = {"4k": 90, "2k": 92, "1k": 92}


# ---------------------------------------------------------------------------
# game files

class Paks:
    def __init__(self, paths):
        self.zips = [zipfile.ZipFile(p) for p in paths]
        self.index = []
        for z in self.zips:
            self.index.append({n.lower(): n for n in z.namelist()})

    def read(self, name):
        low = name.lower().replace("\\", "/")
        own = os.path.join(OWN_PK3_DIR, low)
        if os.path.isfile(own):
            with open(own, "rb") as f:
                return f.read()
        cands = [low]
        # the renderer swaps .md3 and .mdc when the requested one is missing
        for a, b in ((".md3", ".mdc"), (".mdc", ".md3")):
            if low.endswith(a):
                cands.append(low[:-4] + b)
        for c in cands:
            for z, idx in zip(self.zips, self.index):
                if c in idx:
                    return z.read(idx[c])
        raise FileNotFoundError(name)


def shader_name(s):
    s = s.lower().replace("\\", "/").split("\0")[0]
    return re.sub(r"\.(tga|jpg|png)$", "", s)


def surfaces(data):
    """(surface name, shader name) of every surface of an MD3 or MDC model."""
    out = []
    ident = data[:4]
    if ident == b"IDP3":
        nsurf, = struct.unpack_from("<i", data, 84)
        o, = struct.unpack_from("<i", data, 100)
        for _ in range(nsurf):
            name = data[o + 4:o + 68].split(b"\0")[0].decode("latin1").lower()
            nsh, = struct.unpack_from("<i", data, o + 76)
            ofs_sh, = struct.unpack_from("<i", data, o + 92)
            ofs_end, = struct.unpack_from("<i", data, o + 104)
            sh = data[o + ofs_sh:o + ofs_sh + 64].split(b"\0")[0].decode("latin1") if nsh else ""
            out.append((name, shader_name(sh)))
            o += ofs_end
    elif ident == b"IDPC":
        nsurf, = struct.unpack_from("<i", data, 84)
        o, = struct.unpack_from("<i", data, 104)
        for _ in range(nsurf):
            name = data[o + 4:o + 68].split(b"\0")[0].decode("latin1").lower()
            nsh, = struct.unpack_from("<i", data, o + 80)
            ofs_sh, = struct.unpack_from("<i", data, o + 96)
            ofs_end, = struct.unpack_from("<i", data, o + 120)
            sh = data[o + ofs_sh:o + ofs_sh + 64].split(b"\0")[0].decode("latin1") if nsh else ""
            out.append((name, shader_name(sh)))
            o += ofs_end
    else:
        raise ValueError("not a model")
    return out


def read_skin(text):
    mapping = {}
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if "," not in line:
            continue
        surf, sh = line.split(",", 1)
        mapping[surf.strip().lower()] = shader_name(sh.strip().strip('"'))
    return mapping


def parse_weap(text):
    """Models of a .weap file: {("fp"|"tp", part or -1): (model, axis skin, allied skin)}"""
    text = re.sub(r"//[^\n]*", "", text)
    tokens = re.findall(r'"[^"]*"|[{}]|[^\s{}"]+', text)
    found = {}
    stack = []   # labels of the open blocks ("firstperson", "part 0", ...)
    label = []   # tokens since the last brace
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "{":
            stack.append(" ".join(label[-2:]).lower())
            label = []
        elif t == "}":
            stack.pop()
            label = []
        elif t.lower() in ("model", "axisskin", "alliedskin") and i + 1 < len(tokens):
            view, part = None, -1
            for s in reversed(stack):
                m = re.search(r"(?:^|\s)part (\d+)$", s)
                if m and view is None and part == -1:
                    part = int(m.group(1))
                if s.endswith("firstperson") or s.endswith("thirdperson"):
                    view = "fp" if s.endswith("firstperson") else "tp"
                    break
            if view:
                found.setdefault((view, part), {})[t.lower()] = tokens[i + 1].strip('"')
            i += 2
            label = []
            continue
        else:
            label.append(t)
        i += 1
    return {k: (v.get("model"), v.get("axisskin"), v.get("alliedskin")) for k, v in found.items()}


# ---------------------------------------------------------------------------
# finishes (procedural, from the stock texture's panel shading)

def noise(size, cells, rng):
    """Smooth value noise over a size x size square, in [0, 1]."""
    g = rng.random((cells, cells)).astype(np.float32)
    im = Image.fromarray((g * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def fbm(size, rng, base=6, octaves=5):
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        out += amp * noise(size, base * (2 ** o), rng)
        total += amp
        amp *= 0.5
    return out / total


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


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


def mix(a, b, t):
    return a + (b - a) * t[..., None]


def ramp(t, stops):
    """Colour ramp over t: stops = [(position, (r, g, b)), ...] in rising order."""
    t = np.clip(t, stops[0][0], stops[-1][0])
    out = np.zeros(t.shape + (3,), np.float32)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        m = (t >= p0) & (t <= p1)
        f = ((t[m] - p0) / max(p1 - p0, 1e-6))[:, None]
        c0, c1 = np.array(c0, np.float32), np.array(c1, np.float32)
        out[m] = c0 + (c1 - c0) * f
    return out


def finish(paks, tex, theme, div=1):
    """4k finish of a stock texture (div > 1: smaller, for previews): (rgb float array, glow array or None)."""
    if theme in TEXT_THEMES or theme in dict(textskins.THEMES):
        if textskins._READ is None:
            textskins.set_reader(paks.read)
        return textskins.build(theme, tex, div), None
    stock, (w, h), _ = TEXTURES[tex]
    w, h = w // div, h // div
    base_img = Image.open(io.BytesIO(paks.read(stock))).convert("RGB")
    base = np.asarray(base_img.resize((w, h), Image.LANCZOS), dtype=np.float32) / 255.0
    l = luminance(base)
    shade = np.clip(0.35 + 0.95 * (l / (np.percentile(l, 98) + 1e-6)), 0.25, 1.25)
    rng = np.random.default_rng(zlib.crc32((tex + theme).encode()))
    # patterns are laid out on a square and cropped, so they keep their shape
    # on textures that are not square
    side = max(w, h)
    v, u = np.mgrid[0:h, 0:w].astype(np.float32) / side
    scale = side / 1024.0

    def square(a):
        return a[:h, :w]

    if theme == "gold":
        dark = np.array([0.42, 0.28, 0.05], np.float32)
        bright = np.array([1.0, 0.86, 0.42], np.float32)
        t = np.clip((shade - 0.25) / 1.0, 0, 1) ** 0.85
        out = mix(np.broadcast_to(dark, base.shape), np.broadcast_to(bright, base.shape), t)
        streak = np.repeat(rng.random((h, 1)).astype(np.float32), w, axis=1)
        out *= (0.93 + 0.12 * streak)[..., None]
        wv = np.sin((u * 46 + np.sin(v * 31 + u * 7) * 1.6) * math.pi) * np.sin((v * 46 + np.cos(u * 29) * 1.6) * math.pi)
        line = np.clip(1 - np.abs(wv) / 0.07, 0, 1)
        out *= (1 - 0.42 * line)[..., None]
        return np.clip(out, 0, 1), None

    if theme == "polska":
        n = square(fbm(side, rng, base=4, octaves=4))
        boundary = 0.5 * h / side + 0.13 * np.sin(u * 2 * math.pi * 1.3 + 0.7) * h / side + 0.18 * (n - 0.5) * h / side
        t = np.clip((v - boundary) / 0.012 + 0.5, 0, 1)
        white = np.array([0.96, 0.96, 0.97], np.float32)
        red = np.array([0.83, 0.07, 0.14], np.float32)
        out = mix(np.broadcast_to(white, base.shape), np.broadcast_to(red, base.shape), t)
        swirl = square(fbm(side, rng, base=12, octaves=4))
        out *= (0.9 + 0.2 * swirl)[..., None]
        speck = rng.random((h, w)).astype(np.float32) > 0.9975
        out[speck] = out[speck] * 0.4
        out *= np.clip(0.55 + 0.5 * shade, 0.4, 1.15)[..., None]
        return np.clip(out, 0, 1), None

    if theme == "neon":
        g = np.array([0.075, 0.08, 0.095], np.float32)
        out = np.broadcast_to(g, base.shape) * np.clip(0.55 + 0.7 * shade, 0.3, 1.3)[..., None]
        e = np.clip((edges(l, scale) - 0.18) / 0.35, 0, 1)
        glow = blur(e, scale * 5)
        cyan = np.array([0.1, 0.95, 1.0], np.float32)
        pink = np.array([1.0, 0.18, 0.78], np.float32)
        side_mix = np.clip((np.sin((u + v) * 2 * math.pi * 1.5) + 0.2) * 3, 0, 1)
        col = mix(np.broadcast_to(pink, base.shape), np.broadcast_to(cyan, base.shape), side_mix)
        out = out + col * (e[..., None] * 0.95 + glow[..., None] * 0.6)
        # the lines also glow in the dark, through an additive stage
        glow_map = col * np.clip(e * 0.8 + glow * 0.5, 0, 1)[..., None]
        return np.clip(out, 0, 1), np.clip(glow_map, 0, 1)

    if theme == "camo":
        n1 = square(fbm(side, rng, base=5, octaves=4))
        n2 = square(fbm(side, rng, base=7, octaves=4))
        cols = [np.array(c, np.float32) for c in
                ((0.20, 0.22, 0.14), (0.36, 0.37, 0.22), (0.47, 0.40, 0.26), (0.09, 0.09, 0.08))]
        out = np.empty_like(base)
        out[:] = cols[0]
        out[n1 > 0.52] = cols[1]
        out[n2 > 0.56] = cols[2]
        out[(n1 < 0.40) & (n2 < 0.47)] = cols[3]
        out *= np.clip(0.5 + 0.65 * shade, 0.35, 1.2)[..., None]
        return np.clip(out, 0, 1), None

    if theme == "damascus":
        n = square(fbm(side, rng, base=6, octaves=5))
        bands = np.sin((u * 9 + v * 2 + n * 2.2) * 2 * math.pi * 3)
        steel = 0.5 + 0.28 * bands + 0.07 * np.sin((u * 60 + n * 8) * math.pi)
        out = np.stack([steel * 0.93, steel * 0.95, steel * 1.0], axis=-1)
        out *= np.clip(0.55 + 0.55 * shade, 0.4, 1.2)[..., None]
        return np.clip(out, 0, 1), None

    # panel shading of the stock texture, for the finishes below
    panel = np.clip(0.55 + 0.55 * shade, 0.4, 1.2)[..., None]

    def ridges(n, width):
        """Thin lines where a noise field crosses its middle (cracks, veins)."""
        return np.clip(1 - np.abs(n - 0.5) / width, 0, 1)

    def pixelated(cells, base, octaves):
        """Noise in square blocks: cells x cells over the square, nearest-neighbour."""
        small = fbm(cells, rng, base=base, octaves=octaves)
        im = Image.fromarray((small * 255).astype(np.uint8)).resize((side, side), Image.NEAREST)
        return square(np.asarray(im, dtype=np.float32) / 255.0)

    if theme == "fade":
        n = square(fbm(side, rng, base=3, octaves=3))
        t = u * side / w + 0.12 * (n - 0.5)
        out = ramp(t, [(0.0, (0.98, 0.86, 0.25)), (0.4, (0.98, 0.38, 0.62)), (0.75, (0.62, 0.3, 0.9)),
                       (1.0, (0.35, 0.3, 0.85))])
        return np.clip(out * panel, 0, 1), None

    if theme == "hardened":
        n1 = square(fbm(side, rng, base=5, octaves=5))
        n2 = square(fbm(side, rng, base=9, octaves=4))
        t = n1 * 0.75 + n2 * 0.25
        out = ramp(t, [(0.3, (0.12, 0.25, 0.62)), (0.42, (0.2, 0.42, 0.85)), (0.5, (0.45, 0.28, 0.55)),
                       (0.56, (0.62, 0.6, 0.62)), (0.64, (0.85, 0.66, 0.25)), (0.75, (0.95, 0.8, 0.4))])
        return np.clip(out * panel, 0, 1), None

    if theme == "tiger":
        n = square(fbm(side, rng, base=4, octaves=4))
        body = ramp(v * side / h + 0.3 * (n - 0.5), [(0.0, (0.98, 0.7, 0.18)), (1.0, (0.85, 0.42, 0.06))])
        s = np.sin((u * 14 + n * 3.5 + np.sin(v * 9) * 0.4) * 2 * math.pi)
        width = 0.55 + 0.35 * square(fbm(side, rng, base=7, octaves=3))
        stripe = np.clip((s - width) / 0.08, 0, 1)
        out = mix(body, np.broadcast_to(np.array([0.07, 0.04, 0.02], np.float32), body.shape), stripe)
        return np.clip(out * panel, 0, 1), None

    if theme == "carbon":
        f = 80
        cu, cv = u * f, v * f
        iu, iv = np.floor(cu), np.floor(cv)
        fu, fv = cu - iu, cv - iv
        across = ((iu + iv) % 2 == 0)
        fiber = np.where(across, np.sin(fv * math.pi) * (0.8 + 0.2 * np.sin(cu * math.pi * 7)),
                         np.sin(fu * math.pi) * (0.8 + 0.2 * np.sin(cv * math.pi * 7)))
        g = 0.16 + 0.42 * np.clip(fiber, 0, 1) ** 1.2
        out = np.stack([g * 0.95, g, g * 1.08], axis=-1)
        return np.clip(out * panel, 0, 1), None

    if theme == "digital":
        t = pixelated(160, 4, 3) * 0.6 + pixelated(320, 7, 2) * 0.4
        # quartiles, so every texture gets all four colours in equal shares
        q = np.quantile(t, [0.25, 0.5, 0.75])
        cols = np.array([(0.6, 0.62, 0.66), (0.4, 0.43, 0.49), (0.24, 0.26, 0.31), (0.11, 0.12, 0.15)], np.float32)
        out = cols[np.searchsorted(q, t)]
        return np.clip(out * panel, 0, 1), None

    if theme == "winter":
        n1 = square(fbm(side, rng, base=4, octaves=4))
        n2 = square(fbm(side, rng, base=6, octaves=3))
        cols = [(0.93, 0.95, 0.97), (0.76, 0.8, 0.85), (0.52, 0.59, 0.68), (0.3, 0.34, 0.4)]
        out = np.empty((h, w, 3), np.float32)
        out[:] = cols[0]
        out[n1 > 0.54] = cols[1]
        out[(n2 > 0.58) & (n1 > 0.48)] = cols[2]
        out[(n1 < 0.36) & (n2 < 0.44)] = cols[3]
        # short vertical "rain" dashes, like German splinter camo
        rain = (np.sin(u * side / (6 * scale)) > 0.92) & (np.sin(v * side / (22 * scale) + np.floor(u * side / (6 * scale)) * 1.7) > 0.3)
        out[rain] *= 0.72
        return np.clip(out * panel, 0, 1), None

    if theme == "desert":
        n1 = square(fbm(side, rng, base=3, octaves=4))
        n2 = square(fbm(side, rng, base=5, octaves=4))
        cols = [(0.8, 0.7, 0.52), (0.68, 0.56, 0.38), (0.5, 0.39, 0.26), (0.9, 0.83, 0.67)]
        out = np.empty((h, w, 3), np.float32)
        out[:] = cols[0]
        out[n1 > 0.53] = cols[1]
        out[(n2 > 0.6) & (n1 > 0.5)] = cols[2]
        out[(n1 < 0.4) & (n2 < 0.5)] = cols[3]
        return np.clip(out * panel, 0, 1), None

    if theme == "web":
        n = square(fbm(side, rng, base=5, octaves=4))
        out = ramp(n, [(0.3, (0.35, 0.02, 0.04)), (0.7, (0.72, 0.06, 0.09))])
        lines = np.zeros((h, w), np.float32)
        lw = 0.0014
        for _ in range(4):
            cx, cy = rng.random() * w / side, rng.random() * h / side
            dx, dy = u - cx, v - cy
            r = np.sqrt(dx * dx + dy * dy)
            theta = np.arctan2(dy, dx)
            spacing = 2 * math.pi / 14
            a = theta / spacing
            spoke = r * np.abs(a - np.round(a)) * spacing
            gap = 0.035
            sag = r + 0.012 * np.abs(a - np.round(a))
            ring = np.abs(sag / gap - np.round(sag / gap)) * gap
            near = r < 0.32
            web = near & ((spoke < lw) | ((ring < lw) & (r > 0.02)))
            lines = np.maximum(lines, web.astype(np.float32))
        lines = blur(lines, scale * 0.6)
        out = mix(out, np.broadcast_to(np.array([0.02, 0.01, 0.01], np.float32), out.shape), np.clip(lines * 1.5, 0, 1))
        return np.clip(out * panel, 0, 1), None

    if theme == "galaxy":
        n1 = square(fbm(side, rng, base=3, octaves=5))
        n2 = square(fbm(side, rng, base=5, octaves=5))
        out = np.broadcast_to(np.array([0.02, 0.02, 0.07], np.float32), (h, w, 3)).copy()
        neb = np.clip((n1 - 0.45) / 0.3, 0, 1) ** 1.5
        col = ramp(n2, [(0.3, (0.1, 0.25, 0.95)), (0.5, (0.55, 0.12, 0.7)), (0.7, (0.95, 0.25, 0.6))])
        out += col * neb[..., None]
        stars = (rng.random((h, w)) > 0.9993).astype(np.float32)
        glow = blur(stars, scale * 1.2) * 6
        out += np.clip(stars + glow, 0, 1)[..., None] * np.array([0.95, 0.95, 1.0], np.float32)
        return np.clip(out * np.clip(0.75 + 0.35 * shade, 0.6, 1.2)[..., None], 0, 1), None

    if theme == "rust":
        n1 = square(fbm(side, rng, base=6, octaves=6))
        n2 = square(fbm(side, rng, base=14, octaves=4))
        steel = np.broadcast_to(np.array([0.3, 0.3, 0.32], np.float32), (h, w, 3))
        rust = ramp(n2, [(0.3, (0.3, 0.12, 0.05)), (0.55, (0.58, 0.26, 0.08)), (0.75, (0.78, 0.42, 0.16))])
        m = np.clip((n1 - 0.44) / 0.08, 0, 1)
        out = mix(steel, rust, m)
        pits = rng.random((h, w)) > 0.994
        out[pits] *= 0.45
        return np.clip(out * panel, 0, 1), None

    if theme == "magma":
        n = square(fbm(side, rng, base=6, octaves=5))
        rock = square(fbm(side, rng, base=20, octaves=3))
        out = ramp(rock, [(0.3, (0.04, 0.035, 0.035)), (0.7, (0.16, 0.13, 0.12))])
        crack = ridges(n, 0.018) ** 1.5
        heat = blur(crack, scale * 4)
        lava = ramp(crack, [(0.0, (0.9, 0.2, 0.02)), (1.0, (1.0, 0.85, 0.3))])
        out = out * panel + lava * np.clip(crack + heat * 0.8, 0, 1)[..., None]
        glow = lava * np.clip(crack * 0.9 + heat * 0.7, 0, 1)[..., None]
        return np.clip(out, 0, 1), np.clip(glow, 0, 1)

    if theme == "hazard":
        n = square(fbm(side, rng, base=10, octaves=4))
        s = ((u + v) * 22) % 1.0 < 0.5
        out = np.where(s[..., None], np.array([0.96, 0.78, 0.08], np.float32), np.array([0.07, 0.07, 0.07], np.float32))
        # worn paint: bare steel on the edges of the panels and in scratches
        wear = (edges(l, scale) * 1.4 + (n > 0.7) * 0.8 + (rng.random((h, w)) > 0.996)) > 0.9
        out[wear] = np.array([0.45, 0.45, 0.47], np.float32)
        return np.clip(out * panel, 0, 1), None

    if theme == "ice":
        n1 = square(fbm(side, rng, base=4, octaves=4))
        n2 = square(fbm(side, rng, base=9, octaves=5))
        out = ramp(n1, [(0.3, (0.55, 0.78, 0.95)), (0.7, (0.85, 0.95, 1.0))])
        crack = np.maximum(ridges(n2, 0.012), ridges(n1, 0.008) * 0.7)
        out = mix(out, np.broadcast_to(np.array([1.0, 1.0, 1.0], np.float32), out.shape), crack)
        return np.clip(out * np.clip(0.7 + 0.4 * shade, 0.55, 1.15)[..., None], 0, 1), None

    if theme == "marble":
        n = square(fbm(side, rng, base=4, octaves=6))
        n2 = square(fbm(side, rng, base=7, octaves=5))
        dark = np.maximum(np.clip(1 - np.abs(np.sin((u * 5 + v * 3 + n * 7) * math.pi)) / 0.2, 0, 1) ** 1.5,
                          np.clip(1 - np.abs(np.sin((u * 9 - v * 4 + n2 * 9) * math.pi)) / 0.1, 0, 1) ** 1.5 * 0.7)
        gold = np.clip(1 - np.abs(np.sin((u * 2 - v * 3 + n * 4) * math.pi)) / 0.03, 0, 1)
        out = ramp(n, [(0.3, (0.86, 0.86, 0.84)), (0.7, (0.97, 0.96, 0.94))])
        out = mix(out, np.broadcast_to(np.array([0.12, 0.12, 0.13], np.float32), out.shape), dark * 0.85)
        out = mix(out, np.broadcast_to(np.array([0.85, 0.66, 0.25], np.float32), out.shape), gold)
        return np.clip(out * panel, 0, 1), None

    if theme == "wood":
        n = square(fbm(side, rng, base=3, octaves=5))
        grain = np.sin((v * 22 + n * 5) * 2 * math.pi) * 0.5 + 0.5
        fine = square(fbm(side, rng, base=60, octaves=2))
        t = grain * 0.6 + fine * 0.4
        out = ramp(t, [(0.2, (0.24, 0.13, 0.06)), (0.6, (0.43, 0.25, 0.12)), (0.9, (0.58, 0.36, 0.18))])
        return np.clip(out * panel, 0, 1), None

    def hsv(hue, sat, val):
        """HSV (0..1 arrays) to an RGB array."""
        i = np.floor(hue * 6) % 6
        f = hue * 6 - np.floor(hue * 6)
        p, q, t = val * (1 - sat), val * (1 - f * sat), val * (1 - (1 - f) * sat)
        sectors = [i == 0, i == 1, i == 2, i == 3, i == 4]
        r = np.select(sectors, [val, q, p, p, t], default=val)
        g = np.select(sectors, [t, val, val, q, p], default=p)
        b = np.select(sectors, [p, p, t, val, val], default=q)
        return np.stack([r, g, b], axis=-1).astype(np.float32)

    if theme == "cyber":
        # circuit board: traces that walk the grid, bend by 45 degrees and end in solder pads
        step = side / 56.0
        lw = max(2, int(round(step * 0.16)))
        board = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(board)
        dirs = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
        for _ in range(max(6, int(w * h / (side * side) * 110))):
            x, y = int(rng.integers(0, w // step + 1)) * step, int(rng.integers(0, h // step + 1)) * step
            d = int(rng.integers(0, 4)) * 2          # start straight, never diagonal
            pts = [(x, y)]
            for _s in range(int(rng.integers(3, 12))):
                if rng.random() < 0.3:
                    d = (d + (1 if rng.random() < 0.5 else -1)) % 8
                x, y = x + dirs[d][0] * step, y + dirs[d][1] * step
                pts.append((x, y))
            draw.line(pts, fill=255, width=lw, joint="curve")
            for px, py in (pts[0], pts[-1]):
                pr = lw * 1.7
                draw.ellipse((px - pr, py - pr, px + pr, py + pr), outline=255, width=max(1, lw // 2 + 1))
        lines = np.asarray(board, dtype=np.float32) / 255.0
        base_col = np.array([0.05, 0.065, 0.075], np.float32)
        out = np.broadcast_to(base_col, (h, w, 3)) * np.clip(0.6 + 0.6 * shade, 0.4, 1.3)[..., None]
        col = mix(np.broadcast_to(np.array([0.1, 1.0, 0.8], np.float32), (h, w, 3)),
                  np.broadcast_to(np.array([0.2, 0.55, 1.0], np.float32), (h, w, 3)), square(fbm(side, rng, base=3, octaves=2)))
        glow = blur(lines, scale * 3)
        out = out + col * (lines[..., None] * 0.9 + glow[..., None] * 0.5)
        return np.clip(out, 0, 1), np.clip(col * np.clip(lines * 0.8 + glow * 0.6, 0, 1)[..., None], 0, 1)

    if theme == "hologram":
        n = square(fbm(side, rng, base=3, octaves=3))
        hue = (u * 1.6 + v * 0.9 + n * 0.7 + shade * 0.35) % 1.0
        val = np.clip(0.55 + 0.4 * shade, 0.4, 1.0)
        out = hsv(hue, np.full_like(hue, 0.55), val)
        scan = 0.9 + 0.1 * np.sin(v * side / (3.2 * scale) * math.pi)
        out = out * scan[..., None] + 0.12
        return np.clip(out, 0, 1), None

    if theme == "plasma":
        n1 = square(fbm(side, rng, base=5, octaves=5))
        n2 = square(fbm(side, rng, base=9, octaves=4))
        bolt = np.maximum(ridges(n1, 0.014), ridges(n2, 0.01) * 0.8) ** 1.3
        halo = blur(bolt, scale * 5)
        base_col = ramp(n2, [(0.3, (0.03, 0.01, 0.06)), (0.7, (0.1, 0.03, 0.16))])
        col = ramp(n1, [(0.3, (0.35, 0.55, 1.0)), (0.7, (0.85, 0.35, 1.0))])
        out = base_col * np.clip(0.7 + 0.5 * shade, 0.5, 1.3)[..., None] + col * np.clip(bolt + halo * 0.7, 0, 1)[..., None]
        return np.clip(out, 0, 1), np.clip(col * np.clip(bolt * 0.9 + halo * 0.6, 0, 1)[..., None], 0, 1)

    if theme == "synthwave":
        t = v * side / h
        out = ramp(t, [(0.0, (0.12, 0.02, 0.22)), (0.45, (0.85, 0.15, 0.55)), (0.75, (1.0, 0.45, 0.2)), (1.0, (1.0, 0.8, 0.3))])
        out = out * np.clip(0.6 + 0.5 * shade, 0.45, 1.2)[..., None]
        cells = 40
        gu, gv = (u * cells) % 1.0, (v * cells) % 1.0
        grid = ((np.minimum(gu, 1 - gu) < 0.05) | (np.minimum(gv, 1 - gv) < 0.05)).astype(np.float32)
        glow = blur(grid, scale * 2.5)
        cyan = np.array([0.2, 0.95, 1.0], np.float32)
        out = mix(out, np.broadcast_to(cyan, out.shape), np.clip(grid * 0.85 + glow * 0.3, 0, 1))
        return np.clip(out, 0, 1), np.clip(cyan * np.clip(grid * 0.7 + glow * 0.5, 0, 1)[..., None], 0, 1)

    if theme == "radar":
        out = np.broadcast_to(np.array([0.01, 0.05, 0.025], np.float32), (h, w, 3)) * np.clip(0.7 + 0.6 * shade, 0.5, 1.4)[..., None]
        green = np.array([0.25, 1.0, 0.45], np.float32)
        lines = np.zeros((h, w), np.float32)
        sweep = np.zeros((h, w), np.float32)
        for _ in range(3):
            cx, cy = rng.random() * w / side, rng.random() * h / side
            r = np.hypot(u - cx, v - cy)
            ring = np.abs((r / 0.05) - np.round(r / 0.05)) * 0.05 < 0.0016
            cross = (np.abs(u - cx) < 0.0012) | (np.abs(v - cy) < 0.0012)
            lines = np.maximum(lines, ((ring | cross) & (r < 0.3)).astype(np.float32) * 0.8)
            ang = (np.arctan2(v - cy, u - cx) / (2 * math.pi)) % 1.0
            sweep = np.maximum(sweep, np.where(r < 0.3, np.clip(1 - ((ang - rng.random()) % 1.0) / 0.2, 0, 1) ** 2, 0))
        blips = (rng.random((h, w)) > 0.9996).astype(np.float32)
        blips = np.clip(blur(blips, scale * 1.5) * 12, 0, 1)
        light = np.clip(lines + sweep * 0.45 + blips, 0, 1)
        out = out + green * light[..., None]
        return np.clip(out, 0, 1), np.clip(green * np.clip(lines * 0.6 + sweep * 0.35 + blips, 0, 1)[..., None], 0, 1)

    if theme == "invasion":
        # D-Day invasion stripes over olive drab, worn at the edges
        n = square(fbm(side, rng, base=8, octaves=4))
        olive = ramp(n, [(0.3, (0.24, 0.27, 0.15)), (0.7, (0.33, 0.36, 0.21))])
        k = np.floor(u * 26).astype(int) % 9
        white = np.isin(k, (0, 2, 4))
        black = np.isin(k, (1, 3))
        out = olive.copy()
        out[white] = np.array([0.88, 0.87, 0.82], np.float32)
        out[black] = np.array([0.06, 0.06, 0.06], np.float32)
        wear = (edges(l, scale) * 1.3 + (square(fbm(side, rng, base=30, octaves=2)) > 0.72) * 0.9) > 0.95
        out[wear] = olive[wear] * 0.8
        return np.clip(out * panel, 0, 1), None

    if theme == "airstrike":
        # a gunmetal body in the purple smoke of a field ops airstrike marker
        metal = np.broadcast_to(np.array([0.2, 0.21, 0.23], np.float32), (h, w, 3)) * panel
        n1 = square(fbm(side, rng, base=4, octaves=5))
        n2 = square(fbm(side, rng, base=9, octaves=4))
        smoke = np.clip((n1 * 0.7 + n2 * 0.3 - 0.42) / 0.25, 0, 1) ** 1.2
        purple = ramp(n2, [(0.3, (0.45, 0.15, 0.62)), (0.7, (0.78, 0.45, 0.9))])
        out = mix(metal, purple, smoke * 0.9)
        canister = np.abs(((u + 0.13) * 5) % 1.0 - 0.5) < 0.012
        out[canister] = np.array([0.85, 0.72, 0.1], np.float32)
        return np.clip(out, 0, 1), None

    if theme == "supply":
        # the planks of a FatBoss supply crate, with stencilled stars
        plank = np.floor(v * 9)
        n = square(fbm(side, rng, base=3, octaves=4))
        grain = np.sin((v * 90 + n * 6 + plank * 1.7) * 2 * math.pi) * 0.5 + 0.5
        tone = (np.sin(plank * 12.9898) * 43758.5453) % 1.0
        out = ramp(grain * 0.5 + tone * 0.5, [(0.0, (0.36, 0.24, 0.12)), (0.5, (0.55, 0.38, 0.2)), (1.0, (0.68, 0.5, 0.28))])
        gap = ((v * 9) % 1.0) < 0.035
        out[gap] = np.array([0.12, 0.08, 0.04], np.float32)
        stars = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(stars)
        for _ in range(max(3, int(w * h / (side * side) * 14))):
            cx, cy, r = rng.random() * w, rng.random() * h, side * (0.03 + rng.random() * 0.03)
            pts = []
            for i in range(10):
                a = -math.pi / 2 + i * math.pi / 5
                rad = r if i % 2 == 0 else r * 0.42
                pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
            draw.polygon(pts, fill=255)
        stencil = np.asarray(stars, dtype=np.float32) / 255.0 * (0.75 + 0.25 * square(fbm(side, rng, base=40, octaves=2)))
        out = mix(out, np.broadcast_to(np.array([0.08, 0.07, 0.05], np.float32), out.shape), np.clip(stencil, 0, 1) * 0.85)
        return np.clip(out * panel, 0, 1), None

    if theme == "cobalt":
        n = square(fbm(side, rng, base=5, octaves=4))
        streak = np.repeat(rng.random((h, 1)).astype(np.float32), w, axis=1)
        out = ramp(shade / 1.25 + 0.1 * (n - 0.5), [(0.2, (0.03, 0.08, 0.3)), (0.6, (0.1, 0.3, 0.8)), (1.0, (0.45, 0.7, 1.0))])
        out *= (0.92 + 0.1 * streak)[..., None]
        return np.clip(out, 0, 1), None

    raise ValueError(theme)


def save_jpg(arr_or_img, path, size, quality):
    im = arr_or_img if isinstance(arr_or_img, Image.Image) else Image.fromarray((arr_or_img * 255 + 0.5).astype(np.uint8))
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, quality=quality, optimize=True)


# ---------------------------------------------------------------------------

def stage_shader(name, image, env, glow):
    lines = [name, "{", "\tnopicmip", "\tnocompress", "\t{", f"\t\tmap {image}", "\t\trgbGen lightingDiffuse", "\t}"]
    lines += ["\t{", "\t\tmap models/fatboss/skins/env.jpg"]
    if env is None:
        lines += ["\t\trgbGen lightingDiffuse"]
    else:
        lines += ["\t\trgbGen const ( %.2f %.2f %.2f )" % env]
    lines += ["\t\ttcGen environment", "\t\tblendFunc GL_DST_COLOR GL_ONE", "\t}"]
    if glow:
        lines += ["\t{", f"\t\tmap {glow}", "\t\tblendFunc GL_ONE GL_ONE", "\t\trgbGen identity", "\t}"]
    lines += ["}", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paks", nargs="+", required=True, help="legacy_v2.86.0.pk3 first, then pak0.pk3 ...")
    ap.add_argument("--codex", required=True, help="Codex's defender_v0_7.pk3")
    ap.add_argument("--only", nargs="*", help="build only these textures (quick tests)")
    ap.add_argument("--tables-only", action="store_true",
                    help="keep the textures, rewrite only shaders, .skin files and the cgame table")
    ap.add_argument("--themes", nargs="*", help="(re)build only these themes' textures, keep the others")
    args = ap.parse_args()

    paks = Paks(args.paks)
    codex = Paks([args.codex])
    textskins.set_reader(paks.read)
    textures = [t for t in ALL if not args.only or t in args.only]
    if not args.tables_only:
        if args.themes:
            for theme in args.themes:
                if theme not in THEMES:
                    raise SystemExit(f"unknown theme {theme}")
                shutil.rmtree(os.path.join(OUT, "models", "fatboss", "skins", theme), ignore_errors=True)
        else:
            if os.path.isdir(OUT):
                shutil.rmtree(OUT)
            os.makedirs(OUT)
        # environment map for the reflection stage
        env = Image.open(io.BytesIO(codex.read(CODEX_ENV))).convert("RGB")
        save_jpg(env, os.path.join(OUT, "models/fatboss/skins/env.jpg"), (256, 256), 92)
        for theme, (covers, _) in THEMES.items():
            if args.themes and theme not in args.themes:
                continue
            for tex in covers:
                if tex not in textures:
                    continue
                (w, h) = TEXTURES[tex][1]
                d = f"models/fatboss/skins/{theme}"
                if (theme, tex) in CODEX:
                    fp_src, tp_src = CODEX[(theme, tex)]
                    fp = Image.open(io.BytesIO(codex.read(fp_src))).convert("RGB")
                    tp = Image.open(io.BytesIO(codex.read(tp_src))).convert("RGB")
                else:
                    arr, glow = finish(paks, tex, theme)
                    fp = tp = Image.fromarray((arr * 255 + 0.5).astype(np.uint8))
                    if glow is not None:
                        save_jpg(glow, os.path.join(OUT, f"{d}/{tex}_glow.jpg"), (w // 4, h // 4), 90)
                for res, div in RES.items():
                    src = tp if res == "1k" else fp
                    save_jpg(src, os.path.join(OUT, f"{d}/{tex}_{res}.jpg"), (w // div, h // div), JPEG_QUALITY[res])
                print(theme, tex, flush=True)
    else:
        for p, _, files in os.walk(OUT):
            for f in files:
                if f.endswith(".skin"):
                    os.remove(os.path.join(p, f))

    # one shader file per theme, so a theme and its shaders always travel in the same pk3
    scripts = os.path.join(OUT, "scripts")
    if os.path.isdir(scripts):
        shutil.rmtree(scripts)
    os.makedirs(scripts)
    for theme, (covers, env_strength) in THEMES.items():
        shaders = ["// FatBoss weapon skins - generated by fatboss/skins/build_skins.py, do not edit", ""]
        for tex in covers:
            if tex not in textures:
                continue
            d = f"models/fatboss/skins/{theme}"
            glow_path = f"{d}/{tex}_glow.jpg"
            if not os.path.isfile(os.path.join(OUT, glow_path)):
                glow_path = None
            for res in RES:
                # no glow on third-person weapons: it would light players up in the dark
                shaders.append(stage_shader(f"fatboss/skins/{theme}/{tex}_{res}", f"{d}/{tex}_{res}.jpg", env_strength,
                                            glow_path if res != "1k" else None))
        with open(os.path.join(scripts, f"fatboss_skins_{theme}.shader"), "w", newline="\n") as f:
            f.write("\n".join(shaders))

    # which model of which weapon carries the gun texture; mixed models (gun
    # plus hands or sleeves) get .skin files, the rest a custom shader
    rows = []
    skin_files = 0
    for wp, slot, tex, weap in WEAPONS:
        models = parse_weap(paks.read(f"weapons/{weap}.weap").decode("latin1"))
        gun = TEXTURES[tex][2]
        for (view, part), (model, axis_skin, allied_skin) in sorted(models.items()):
            if not model:
                continue
            surfs = surfaces(paks.read(model))
            gun_surfs = [s for s, sh in surfs if sh == gun]
            if not gun_surfs:
                continue
            skin_id = None
            team = False
            if len(gun_surfs) != len(surfs):
                skin_id = os.path.splitext(os.path.basename(model))[0].lower()
                team = bool(axis_skin or allied_skin)
                variants = {"": {}}
                if team:
                    variants = {"_axis": read_skin(paks.read(axis_skin).decode("latin1")) if axis_skin else {},
                                "_allied": read_skin(paks.read(allied_skin).decode("latin1")) if allied_skin else {}}
                for theme, (covers, _) in THEMES.items():
                    if tex not in covers or tex not in textures:
                        continue
                    # first person steps down to 1k when the player's hunk is short
                    for res in (("1k",) if view == "tp" else RES):
                        for suffix, team_map in variants.items():
                            lines = []
                            for s, sh in surfs:
                                if sh == gun:
                                    lines.append(f"{s},fatboss/skins/{theme}/{tex}_{res}")
                                else:
                                    lines.append(f"{s},{team_map.get(s, sh)}")
                            p = os.path.join(OUT, f"models/fatboss/skins/{theme}/{skin_id}_{res}{suffix}.skin")
                            with open(p, "w", newline="\n") as f:
                                f.write("\n".join(lines) + "\n")
                            skin_files += 1
            rows.append((wp, slot, tex, view, part, skin_id, team))

    with open(INC, "w", newline="\n") as f:
        f.write("// FatBoss weapon skins - generated by fatboss/skins/build_skins.py, do not edit\n\n")
        f.write("static const char *fbSkinSlotNames[FB_SKIN_SLOTS] = { %s };\n\n" % ", ".join(f'"{s}"' for s in SLOTS))
        f.write("static const char *fbSkinTexNames[FB_SKIN_TEXTURES] = { %s };\n\n" % ", ".join(f'"{t}"' for t in ALL))
        f.write("// pixels of the 4k texture; the 2k and 1k ones have a quarter and a sixteenth\n")
        f.write("static const int fbSkinTexPixels[FB_SKIN_TEXTURES] = { %s };\n\n" % ", ".join(
            str(TEXTURES[t][1][0] * TEXTURES[t][1][1]) for t in ALL))
        f.write("static const fbSkinTheme_t fbSkinThemes[] =\n{\n")
        for theme, (covers, _) in THEMES.items():
            mask = " | ".join(f"(1 << {ALL.index(t)})" for t in covers)
            f.write(f'\t{{ "{theme}", {mask} }},\n')
        f.write("};\n\n")
        f.write("// weapon, slot, texture, view, part (-1 main model), .skin id (NULL: custom shader on the whole model), per-team .skin\n")
        f.write("static const fbSkinModel_t fbSkinModels[] =\n{\n")
        for wp, slot, tex, view, part, skin_id, team in rows:
            f.write("\t{ %s, %d, %d, %s, %d, %s, %s },\n" % (
                wp, SLOTS.index(slot), ALL.index(tex), "W_FP_MODEL" if view == "fp" else "W_TP_MODEL", part,
                f'"{skin_id}"' if skin_id else "NULL", "qtrue" if team else "qfalse"))
        f.write("};\n")
    print(f"{len(rows)} models, {skin_files} .skin files -> {INC}")
    write_parts()


def write_parts():
    """Splits the themes into pk3 parts under PART_LIMIT (largest first, first fit)."""
    sizes = {}
    for theme in THEMES:
        d = os.path.join(OUT, "models", "fatboss", "skins", theme)
        total = os.path.getsize(os.path.join(OUT, "scripts", f"fatboss_skins_{theme}.shader"))
        for p, _, files in os.walk(d):
            total += sum(os.path.getsize(os.path.join(p, f)) for f in files)
        sizes[theme] = total
    env = os.path.getsize(os.path.join(OUT, "models", "fatboss", "skins", "env.jpg"))
    parts = []   # [size, [themes]]
    for theme in sorted(sizes, key=lambda t: -sizes[t]):
        if sizes[theme] + env > PART_LIMIT:
            raise SystemExit(f"theme {theme} alone is {sizes[theme] / 1048576:.1f} MiB, over the part limit")
        for part in parts:
            if part[0] + sizes[theme] <= PART_LIMIT:
                part[0] += sizes[theme]
                part[1].append(theme)
                break
        else:
            parts.append([env + sizes[theme], [theme]])
    with open(PARTS, "w", newline="\n") as f:
        f.write("# skins pk3 parts: <letter> <themes>; generated by build_skins.py\n")
        for i, (size, themes) in enumerate(parts):
            f.write(f"{chr(ord('a') + i)} {' '.join(themes)}\n")
            print(f"part {chr(ord('a') + i)}: {size / 1048576:.1f} MiB  {' '.join(themes)}")


if __name__ == "__main__":
    main()
