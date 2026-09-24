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
from PIL import Image, ImageFilter

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
}
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


def finish(paks, tex, theme):
    """4k finish of a stock texture: (rgb float array, glow array or None)."""
    stock, (w, h), _ = TEXTURES[tex]
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
    args = ap.parse_args()

    paks = Paks(args.paks)
    codex = Paks([args.codex])
    textures = [t for t in ALL if not args.only or t in args.only]
    if not args.tables_only:
        if os.path.isdir(OUT):
            shutil.rmtree(OUT)
        os.makedirs(OUT)
        # environment map for the reflection stage
        env = Image.open(io.BytesIO(codex.read(CODEX_ENV))).convert("RGB")
        save_jpg(env, os.path.join(OUT, "models/fatboss/skins/env.jpg"), (256, 256), 92)
        for theme, (covers, _) in THEMES.items():
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
