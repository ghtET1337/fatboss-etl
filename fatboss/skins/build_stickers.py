"""StatTrak display and sticker places on the guns (cgame b13), laid in texture space.

Every sticker, the StatTrak display and each of its digits is an extra pass of the gun drawn over the
skin: a shader that maps one image onto a rectangle of the gun's texture (clampmap + tcMod transform,
depthFunc equal, so it lands exactly on the gun's own depth). What lands on the texture shows on the
first- and the third-person model alike, and costs nothing when nobody wears it.

The places come from textskins' charts (flat groups of triangles with a frame that reads along the gun):
only panels of the main first-person model, on the side the player sees, where the hands do not cover
them; the display on a level side, reading along the gun. Knives take no stickers (as in CS2) and show
their StatTrak count on the inspect card only.

Writes into fatboss/pk3 (the cgame pk3):
    scripts/fatboss_stickers.shader  fbk/<tex>/s<place><code> (a sticker), fbk/<tex>/p (the display),
                                     fbk/<tex>/d<pos>_<digit> (a digit), fbk/nodraw
    fbk/<model>/*.skin               the same for models that also carry hands or other textures: every
                                     surface that is not the gun's draws nothing in these passes
    fatboss/stattrak/plate.png, 0.png .. 9.png
and src/cgame/cg_fatboss_stickers.inc. The sticker art itself (fatboss/stickers/<design>.png) is made
from the graffiti by the FatBoss bot's make_stickers.py; <code> is the design's place in the cgame's
graffiti table (cg_fatboss_names.inc), base 36, as FatBoss sends it.

    py fatboss/skins/build_stickers.py --paks legacy_v2.86.0.pk3 pak2.pk3 pak1.pk3 pak0.pk3 [--check out.jpg]
"""
import argparse
import math
import os
import re
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_skins as bs  # noqa: E402
import textskins as ts  # noqa: E402

PK3 = os.path.join(bs.REPO, "fatboss", "pk3")
INC = os.path.join(bs.REPO, "src", "cgame", "cg_fatboss_stickers.inc")
NAMES_INC = os.path.join(bs.REPO, "src", "cgame", "cg_fatboss_names.inc")
GUNS = ("colt", "luger", "thompson", "mp40")
PLACES = 4
DIGITS = 6
CODES = "0123456789abcdefghijklmnopqrstuvwxyz"
PLATE_W, PLATE_ASPECT = 512, 3.3
PLATE_H = round(PLATE_W / PLATE_ASPECT)
MIN_STICKER = 1.15          # game units: smaller places are not worth a sticker
MIN_PLATE = 0.55


# ------------------------------------------------------------------ the display's images

def plate_layout(W, H):
    """The display's window and its six digit cells, in plate pixels: (window, [cells], digit box in a cell)."""
    wx0, wy0, wx1, wy1 = H * 0.3, H * 0.36, W - H * 0.3, H * 0.9
    cw = (wx1 - wx0) / DIGITS
    cells = [(wx0 + cw * i, wy0, wx0 + cw * (i + 1), wy1) for i in range(DIGITS)]
    wh = wy1 - wy0
    dh = wh * 0.72
    dw = min(cw * 0.72, dh * 0.56)
    return (wx0, wy0, wx1, wy1), cells, ((cw - dw) / 2, (wh - dh) / 2, dw, dh)


SEG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc",
       "7": "abc", "8": "abcdefg", "9": "abcdfg"}


def seg_polys(x, y, w, h):
    """The seven slanted segments of a digit in the box (x, y, w, h)."""
    t = w * 0.17
    sl = 0.12 * w

    def P(u, v):
        return (x + u * w + (1 - v) * sl, y + v * h)
    ht, wt, g = t / h / 2, t / w / 2, 0.02
    return {
        "a": [P(wt + g, 0), P(1 - wt - g, 0), P(1 - 2 * wt - g, 2 * ht), P(2 * wt + g, 2 * ht)],
        "d": [P(2 * wt + g, 1 - 2 * ht), P(1 - 2 * wt - g, 1 - 2 * ht), P(1 - wt - g, 1), P(wt + g, 1)],
        "g": [P(wt + g, 0.5), P(2 * wt + g, 0.5 - ht), P(1 - 2 * wt - g, 0.5 - ht), P(1 - wt - g, 0.5),
              P(1 - 2 * wt - g, 0.5 + ht), P(2 * wt + g, 0.5 + ht)],
        "f": [P(0, ht + g), P(2 * wt, 2 * ht + g), P(2 * wt, 0.5 - ht - g), P(0, 0.5 - g)],
        "b": [P(1 - 2 * wt, 2 * ht + g), P(1, ht + g), P(1, 0.5 - g), P(1 - 2 * wt, 0.5 - ht - g)],
        "e": [P(0, 0.5 + g), P(2 * wt, 0.5 + ht + g), P(2 * wt, 1 - 2 * ht - g), P(0, 1 - ht - g)],
        "c": [P(1 - 2 * wt, 0.5 + ht + g), P(1, 0.5 + g), P(1, 1 - ht - g), P(1 - 2 * wt, 1 - 2 * ht - g)],
    }


def plate_image():
    """The display body, lit like the gun: a dark module, the label, the window with every segment dark.
    Its outermost pixels stay clear: the shader clamps to them all over the gun."""
    ss = 4
    W, H = PLATE_W * ss, PLATE_H * ss
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    e = 2 * ss
    r = int(H * 0.16)
    d.rounded_rectangle((e, e, W - 1 - e, H - 1 - e), r, fill=(34, 34, 36, 255))
    d.rounded_rectangle((e + H * 0.04, e + H * 0.04, W - 1 - e - H * 0.04, H - 1 - e - H * 0.04), r,
                        outline=(70, 70, 74, 255), width=max(1, int(H * 0.03)))
    for sx in (H * 0.16, W - H * 0.16):
        d.ellipse((sx - H * 0.06, H * 0.44, sx + H * 0.06, H * 0.56), fill=(90, 90, 94, 255))
    d.text((H * 0.34, H * 0.07), "StatTrak™", font=ts.font("arialbd.ttf", H * 0.2), fill=(236, 128, 36, 255))
    d.text((W - H * 0.34, H * 0.12), "CONFIRMED KILLS", font=ts.font("arial.ttf", H * 0.13), fill=(150, 150, 150, 255), anchor="ra")
    (wx0, wy0, wx1, wy1), cells, (ox, oy, dw, dh) = plate_layout(W, H)
    d.rounded_rectangle((wx0, wy0, wx1, wy1), int(H * 0.05), fill=(14, 12, 10, 255))
    for (cx0, cy0, _, _) in cells:
        for poly in seg_polys(cx0 + ox, cy0 + oy, dw, dh).values():
            d.polygon(poly, fill=(46, 30, 18, 255))
    return img.resize((PLATE_W, PLATE_H), Image.LANCZOS)


def digit_image(digit):
    """One lit digit the size of a cell, with its glow; clear edges (the shader clamps to them)."""
    ss = 4
    (wx0, wy0, wx1, wy1), cells, (ox, oy, dw, dh) = plate_layout(PLATE_W * ss, PLATE_H * ss)
    cw, ch = cells[0][2] - cells[0][0], cells[0][3] - cells[0][1]
    img = Image.new("RGBA", (int(round(cw)), int(round(ch))), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for s, poly in seg_polys(ox, oy, dw, dh).items():
        if s in SEG[str(digit)]:
            d.polygon(poly, fill=(255, 150, 44, 255))
    halo = img.filter(ImageFilter.GaussianBlur(PLATE_H * ss * 0.03))
    halo = Image.fromarray((np.asarray(halo, np.float32) * [1, 1, 1, 0.55]).astype(np.uint8), "RGBA")
    out = Image.alpha_composite(halo, img)
    w, h = max(8, round(cw / ss)), max(8, round(ch / ss))
    out = out.resize((w, h), Image.LANCZOS)
    a = np.asarray(out).copy()
    a[:2, :, 3] = a[-2:, :, 3] = 0
    a[:, :2, 3] = a[:, -2:, 3] = 0
    return Image.fromarray(a, "RGBA")


def cells_normalized():
    """The digit cells as (x0, y0, x1, y1) fractions of the plate."""
    _, cells, _ = plate_layout(PLATE_W, PLATE_H)
    return [(x0 / PLATE_W, y0 / PLATE_H, x1 / PLATE_W, y1 / PLATE_H) for (x0, y0, x1, y1) in cells]


# ------------------------------------------------------------------ what the player sees

def raster_uv(scr, depth, n_gun, uv, W, H):
    """For every pixel the texture coordinate of the gun triangle in front (-1: nothing, or the hands)."""
    out = np.full((H, W, 2), -1.0)
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
        w2 = 1 - w0 - w1
        m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        z = w0 * depth[i, 0] + w1 * depth[i, 1] + w2 * depth[i, 2]
        zb = zbuf[y0:y1 + 1, x0:x1 + 1]
        m &= z < zb
        if not m.any():
            continue
        zb[m] = z[m]
        o = out[y0:y1 + 1, x0:x1 + 1]
        if i < n_gun:
            o[..., 0][m] = ((w0 * uv[i, 0, 0] + w1 * uv[i, 1, 0] + w2 * uv[i, 2, 0]) % 1.0)[m]
            o[..., 1][m] = ((w0 * uv[i, 0, 1] + w1 * uv[i, 1, 1] + w2 * uv[i, 2, 1]) % 1.0)[m]
        else:
            o[..., 0][m] = -1
            o[..., 1][m] = -1
    return out


def seen_texels(mesh, W=1280, H=960):
    """Texels (analysis size) the first-person view shows, the hands in front hiding theirs."""
    P = mesh.P
    other = mesh.other if len(mesh.other) else np.zeros((0, 3, 3))
    tris = np.concatenate([P, other]) if len(other) else P
    fwd = P.reshape(-1, 3).mean(0)
    fwd /= np.linalg.norm(fwd)
    left = np.cross(np.array([0, 0, 1.0]), fwd)
    left /= np.linalg.norm(left)
    up = np.cross(fwd, left)
    cam = np.stack([tris @ fwd, tris @ left, tris @ up], axis=-1)
    g = np.stack([P @ fwd, P @ left, P @ up], axis=-1)
    gx = np.maximum(g[..., 0], 0.5)
    x = np.maximum(cam[..., 0], 0.5)
    sx, sy = -g[..., 1] / gx, -g[..., 2] / gx
    f = 1.0 / (max(np.ptp(sx) / W, np.ptp(sy) / H) * 1.12)
    mx, my = (sx.max() + sx.min()) / 2, (sy.max() + sy.min()) / 2
    scr = np.stack([W / 2 + f * (-cam[..., 1] / x - mx), H / 2 + f * (-cam[..., 2] / x - my)], axis=-1)
    uv = raster_uv(scr, cam[..., 0], len(P), mesh.UV, W, H)
    ok = uv[..., 0] >= 0
    seen = np.zeros((mesh.ah, mesh.aw), np.uint8)
    seen[(uv[ok][:, 1] * (mesh.ah - 1)).astype(int), (uv[ok][:, 0] * (mesh.aw - 1)).astype(int)] = 255
    im = Image.fromarray(seen).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(3))
    return np.asarray(im) > 0


# ------------------------------------------------------------------ places

def main_uv_offsets(tex, mesh):
    """Whole-number shift of every main-model triangle's texture coordinates (the model's own tiling)."""
    weap_name, key = ts.TEX[tex]
    main, _, _ = ts.weap(weap_name)
    m = ts.Model(main)
    raw = []
    for s in m.surfaces:
        sh = (s.shaders[0] if s.shaders else "").lower()
        if key in sh:
            for a, b, c in s.tris:
                raw.append((s.st[a], s.st[b], s.st[c]))
    raw = np.array(raw, np.float64)
    n0 = int(np.sum(mesh.G == 0))
    assert len(raw) == n0, (tex, len(raw), n0)
    return np.round((raw - mesh.UV[:n0]).mean(axis=1)).astype(int)


def place(tex):
    """The display's place and four sticker places: [(kind, chart, rect in the chart's frame px)]."""
    mesh = ts.mesh_of(tex)
    charts = ts.charts_of(tex)
    seen = seen_texels(mesh)
    offsets = main_uv_offsets(tex, mesh)
    pts = mesh.P[mesh.G == 0].reshape(-1, 3)
    length = np.ptp(pts[:, 0])
    for ch in charts:
        ch.free_all = ch.free.copy()
        ch.avoid(~seen)
        ch.right = mesh.text_axes(ch.idx)[0]
        main = np.all(mesh.G[ch.idx] == 0)
        ch.offset = tuple(offsets[ch.idx[0]]) if main else None
        ch.usable = bool(main and ch.facing > 0.5 and len({tuple(o) for o in offsets[ch.idx]}) == 1)

    def occupy(ch, rect, pad):
        ch.occupy(rect, pad=pad)
        x0, y0, x1, y1 = [int(v) for v in rect[:4]]
        ch.free_all[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = False

    def best(aspect, minimum, cap, level_only):
        found = None
        for ci, ch in enumerate(charts):
            if not ch.usable or ch.free.sum() < 30:
                continue
            side = abs(ch.n[2]) < 0.75
            if level_only and (not side or abs(ch.right @ mesh.F) < 0.85):
                continue
            r = ch.best_rect(aspect, margin=3 if level_only else 2)
            if not r or r[4] / ch.k < minimum:
                continue
            score = min(r[4] / ch.k, cap) * (1.0 if side else (0.35 if level_only else 0.55))
            if found is None or score > found[0]:
                found = (score, ci, r)
        return found

    out = []
    plate_h = min(1.25, 0.052 * length)
    b = best(PLATE_ASPECT, MIN_PLATE, plate_h, True)
    if b:
        _, ci, r = b
        ch = charts[ci]
        h = min(r[4], plate_h * ch.k)
        w = h * PLATE_ASPECT
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        rect = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        occupy(ch, rect, int(0.3 * ch.k))
        out.append(("plate", ci, rect))
    cap = min(2.6, 0.105 * length)
    opened = False
    while sum(1 for p in out if p[0] == "sticker") < PLACES:
        b = best(1.0, MIN_STICKER, cap, False)
        if not b and not opened:
            opened = True          # nothing left in sight: the rest go where the inspect shows them
            for ch in charts:
                ch.free = ch.free_all.copy()
            continue
        if not b:
            break
        _, ci, r = b
        ch = charts[ci]
        s = min(r[4], cap * ch.k)
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        rect = (cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2)
        occupy(ch, rect, int(0.25 * ch.k))
        out.append(("sticker", ci, rect))
    return out, charts, mesh


def to_uv(mesh, ch, rect, sub=(0.0, 0.0, 1.0, 1.0)):
    """The affine map from an image's own coordinates (a, b in 0..1, over the part sub of rect) to the
    model's texture coordinates: uv = A @ (a, b) + B."""
    x0, y0, x1, y1 = rect[:4]
    sx0, sy0, sx1, sy1 = sub
    qx0, qy0 = x0 + (x1 - x0) * sx0, y0 + (y1 - y0) * sy0
    qw, qh = (x1 - x0) * (sx1 - sx0), (y1 - y0) * (sy1 - sy0)
    D = np.diag([1.0 / mesh.aw, 1.0 / mesh.ah])
    A = D @ ch.M @ np.diag([qw, qh])
    B = D @ (ch.c + ch.M @ (np.array([qx0, qy0]) + ch.lo)) + np.array(ch.offset, np.float64)
    return A, B


def tcmod(A, B):
    """tcMod transform m00 m01 m10 m11 t0 t1 for (a, b) = A^-1 (uv - B); the renderer does
    s' = s m00 + t m10 + t0, t' = s m01 + t m11 + t1."""
    Ai = np.linalg.inv(A)
    t = -Ai @ B
    return (Ai[0, 0], Ai[1, 0], Ai[0, 1], Ai[1, 1], t[0], t[1])


def fit(rect_aspect, img_w, img_h):
    """The part of a place (height / width = rect_aspect) an image of this size fills, centred, its
    proportions kept: (x0, y0, x1, y1) fractions of the place."""
    k = min(1.0 / img_w, rect_aspect / img_h)
    w, h = img_w * k, img_h * k / rect_aspect
    return ((1 - w) / 2, (1 - h) / 2, (1 + w) / 2, (1 + h) / 2)


def stage(image, transform, rgbgen):
    m = " ".join(f"{v:.6f}" for v in transform)
    return ("\t{\n"
            f"\t\tclampmap {image}\n"
            "\t\tblendFunc blend\n"
            f"\t\trgbGen {rgbgen}\n"
            "\t\tdepthFunc equal\n"
            f"\t\ttcMod transform {m}\n"
            "\t}\n")


def shader(name, image, transform, rgbgen, sort):
    return f"{name}\n{{\n\tnopicmip\n\tnomipmaps\n\tsort {sort}\n{stage(image, transform, rgbgen)}}}\n"


# ------------------------------------------------------------------ build

def sticker_designs():
    """(code, design) of every graffiti design but the starter, in the cgame's table order."""
    text = open(NAMES_INC, encoding="utf-8").read()
    block = text[text.index("fbGraffitiNames"):]
    keys = re.findall(r'\{ "([a-z0-9_]+)",', block)
    return [(CODES[i], k) for i, k in enumerate(keys) if k != "fatboss"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paks", nargs="+", required=True)
    ap.add_argument("--check", help="also write a picture of every gun's texture with its places filled")
    args = ap.parse_args()
    paks = bs.Paks(args.paks)
    ts.set_reader(paks.read)
    designs = sticker_designs()
    art = {}
    for code, design in designs:
        p = os.path.join(PK3, "fatboss", "stickers", f"{design}.png")
        if not os.path.isfile(p):
            raise SystemExit(f"missing sticker art {p}")
        art[design] = Image.open(p).size
    # images of the display
    st_dir = os.path.join(PK3, "fatboss", "stattrak")
    shutil.rmtree(st_dir, ignore_errors=True)
    os.makedirs(st_dir)
    plate_image().save(os.path.join(st_dir, "plate.png"), optimize=True)
    for dgt in range(10):
        digit_image(dgt).save(os.path.join(st_dir, f"{dgt}.png"), optimize=True)
    cells = cells_normalized()

    shaders = ["// FatBoss stickers and StatTrak displays - generated by fatboss/skins/build_stickers.py, do not edit", "",
               "// the other surfaces of a model that also carries hands: nothing in these passes",
               "fbk/nodraw\n{\n\t{\n\t\tmap $whiteimage\n\t\tblendFunc GL_ZERO GL_ONE\n\t\tdepthFunc equal\n\t}\n}\n"]
    places = {}
    report = []
    for tex in GUNS:
        pl, charts, mesh = place(tex)
        places[tex] = (pl, charts, mesh)
        k = 0
        for kind, ci, rect in pl:
            ch = charts[ci]
            size = ((rect[2] - rect[0]) / ch.k, (rect[3] - rect[1]) / ch.k)
            report.append(f"{tex:9s} {kind:7s} chart {ci:3d} {size[0]:.2f} x {size[1]:.2f} u")
            if kind == "plate":
                A, B = to_uv(mesh, ch, rect)
                shaders.append(shader(f"fbk/{tex}/p", "fatboss/stattrak/plate.png", tcmod(A, B), "lightingDiffuse", 4))
                for pos, cell in enumerate(cells):
                    A, B = to_uv(mesh, ch, rect, cell)
                    for dgt in range(10):
                        shaders.append(shader(f"fbk/{tex}/d{pos}_{dgt}", f"fatboss/stattrak/{dgt}.png", tcmod(A, B), "identity", 5))
            else:
                aspect = (rect[3] - rect[1]) / (rect[2] - rect[0])
                for code, design in designs:
                    w, h = art[design]
                    A, B = to_uv(mesh, ch, rect, fit(aspect, w, h))
                    shaders.append(shader(f"fbk/{tex}/s{k}{code}", f"fatboss/stickers/{design}.png", tcmod(A, B), "lightingDiffuse", 4))
                k += 1
        if k < PLACES or not any(p[0] == "plate" for p in pl):
            raise SystemExit(f"{tex}: only {k} sticker places" + ("" if any(p[0] == "plate" for p in pl) else " and no display"))
    with open(os.path.join(PK3, "scripts", "fatboss_stickers.shader"), "w", newline="\n") as f:
        f.write("\n".join(shaders))

    # .skin files for the models that mix the gun with hands or another texture
    skin_root = os.path.join(PK3, "fbk")
    shutil.rmtree(skin_root, ignore_errors=True)
    skin_models = []
    n_skins = 0
    for wp, slot, tex, weap in bs.WEAPONS:
        if tex not in GUNS:
            continue
        models = bs.parse_weap(paks.read(f"weapons/{weap}.weap").decode("latin1"))
        gun = bs.TEXTURES[tex][2]
        for view in ("fp", "tp"):
            model = (models.get((view, -1)) or (None,))[0]
            if not model:
                continue
            surfs = bs.surfaces(paks.read(model))
            gun_surfs = [s for s, sh in surfs if sh == gun]
            if not gun_surfs or len(gun_surfs) == len(surfs):
                continue
            skin_id = os.path.splitext(os.path.basename(model))[0].lower()
            if skin_id in skin_models:
                continue
            skin_models.append(skin_id)
            names = [f"s{k}{code}" for k in range(PLACES) for code, _ in designs]
            if view == "fp":
                names += ["p"] + [f"d{pos}_{dgt}" for pos in range(DIGITS) for dgt in range(10)]
            for n in names:
                lines = [f"{s},fbk/{tex}/{n}" if sh == gun else f"{s},fbk/nodraw" for s, sh in surfs]
                p = os.path.join(skin_root, skin_id, f"{n}.skin")
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", newline="\n") as f:
                    f.write("\n".join(lines) + "\n")
                n_skins += 1
                rel = f"fbk/{skin_id}/{n}.skin"
                if len(rel) >= bs.MAX_QPATH:
                    raise SystemExit(f"{rel}: {len(rel)} characters, the engine takes fewer than {bs.MAX_QPATH}")

    with open(INC, "w", newline="\n") as f:
        f.write("// FatBoss stickers and StatTrak displays - generated by fatboss/skins/build_stickers.py, do not edit\n\n")
        f.write(f"#define FB_STICKER_PLACES {PLACES}\n#define FB_STATTRAK_DIGITS {DIGITS}\n\n")
        f.write("// textures with sticker places and a display (the knives have neither)\n")
        f.write("static const qboolean fbStickerTex[FB_SKIN_TEXTURES] = { %s };\n\n" % ", ".join(
            "qtrue" if t in GUNS else "qfalse" for t in bs.ALL))
        f.write("// models whose passes need a .skin file (fbk/<model>/<pass>.skin): the rest take the shader\n")
        f.write("static const char *fbStickerSkinModels[] = { %s, NULL };\n" % ", ".join(f'"{m}"' for m in skin_models))
    print("\n".join(report))
    print(f"{len(shaders) - 1} shaders, {n_skins} .skin files for {', '.join(skin_models)} -> {INC}")
    if args.check:
        check_board(args.check, places, designs)


def check_board(out, places, designs):
    """Every gun's texture with its places filled through the shaders' own transforms (not the placement's
    drawing), and the third-person model's two sides: what the game will show."""
    rows = []
    for tex, (pl, charts, mesh) in places.items():
        theme = "fade"
        W4, H4 = ts.SIZES[tex]
        Wc, Hc = W4 // 4, H4 // 4
        base = Image.open(os.path.join(bs.OUT, "models", "fatboss", "skins", theme, f"{tex}_1k.jpg")).convert("RGB").resize((Wc, Hc))
        arr = np.asarray(base, np.float32) / 255
        vv, uu = np.mgrid[0:Hc, 0:Wc].astype(np.float64)
        uv = np.stack([(uu + 0.5) / Wc, (vv + 0.5) / Hc], axis=-1)
        k = 0
        layers = []
        for kind, ci, rect in pl:
            ch = charts[ci]
            off = np.array(ch.offset, np.float64)
            if kind == "plate":
                layers.append((to_uv(mesh, ch, rect), off, Image.open(os.path.join(PK3, "fatboss", "stattrak", "plate.png"))))
                for pos, cell in enumerate(cells_normalized()):
                    dgt = int("001337"[pos])
                    if pos >= 2:
                        layers.append((to_uv(mesh, ch, rect, cell), off, Image.open(os.path.join(PK3, "fatboss", "stattrak", f"{dgt}.png"))))
            else:
                design = designs[(k * 5) % len(designs)][1]
                img = Image.open(os.path.join(PK3, "fatboss", "stickers", f"{design}.png"))
                aspect = (rect[3] - rect[1]) / (rect[2] - rect[0])
                layers.append((to_uv(mesh, ch, rect, fit(aspect, *img.size)), off, img))
                k += 1
        for (A, B), off, img in layers:
            # what the shader does to a texel of the model's own coordinates (the normalized ones + the tiling)
            a_b = (uv + off - B) @ np.linalg.inv(A).T
            im = np.asarray(img.convert("RGBA"), np.float32) / 255
            ih, iw = im.shape[:2]
            a = np.clip(a_b[..., 0], 0, 1)          # clampmap: outside the image, its clear edge
            b = np.clip(a_b[..., 1], 0, 1)
            px = im[(b * (ih - 1)).astype(int), (a * (iw - 1)).astype(int)]
            arr = arr * (1 - px[..., 3:]) + px[..., :3] * px[..., 3:]
        tp = ts.Mesh(tex, view="tp")
        sides = [ts.render_side(tp, np.clip(arr, 0, 1), s, 420, 180) for s in (1, -1)]
        fp = ts.render_fp(mesh, np.clip(arr, 0, 1), 420, 315)
        rows.append((tex, fp, sides))
    board = Image.new("RGB", (420 * 3 + 40, 330 * len(rows)), (30, 32, 36))
    for i, (tex, fp, sides) in enumerate(rows):
        y = i * 330
        for j, im in enumerate([fp] + sides):
            bg = Image.new("RGBA", im.size, (48, 50, 54, 255))
            bg.alpha_composite(im)
            board.paste(bg.convert("RGB"), (10 + j * 430, y + 8))
        ImageDraw.Draw(board).text((14, y + 10), tex, fill=(255, 255, 255))
    board.save(out, quality=88)
    print("check board", out)


if __name__ == "__main__":
    main()
