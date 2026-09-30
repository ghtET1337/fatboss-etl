"""The StatTrak display's images, the sticker designs and the game's first-person camera, for build_decals.py.

(b13-b15 drew stickers and the display as texture passes, made by build_stickers.py; since cgame b16 they are
decals, and this is what is left of it.)
"""
import math
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_skins as bs  # noqa: E402
import textskins as ts  # noqa: E402

PK3 = os.path.join(bs.REPO, "fatboss", "pk3")
NAMES_INC = os.path.join(bs.REPO, "src", "cgame", "cg_fatboss_names.inc")
GUNS = ("colt", "luger", "thompson", "mp40")
KNIVES = ("knife", "kabar")          # a StatTrak display, no stickers
DIGITS = 6
CODES = "0123456789abcdefghijklmnopqrstuvwxyz"
PLATE_W, PLATE_ASPECT = 512, 3.3
PLATE_H = round(PLATE_W / PLATE_ASPECT)


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


# ------------------------------------------------------------------ the game's first-person camera

VIEW_W, VIEW_H = 1440, 1080                    # 4:3 at 1080 lines: wider screens see more, never less
FOV_Y = 2 * math.degrees(math.atan(math.tan(math.radians(45)) * 3 / 4))   # cg_fov 90, the vertical of 4:3


def game_camera(tex):
    """Where the game's camera is in hand space (x forward, y left, z up): ET: Legacy moves the hands model by
    the weapon's dynFov90 (up, forward, right) at cg_fov 90 and cg_gunFovOffset 0, the defaults."""
    text = ts.read_file(f"weapons/{ts.TEX[tex][0]}.weap").decode("latin1")
    m = re.search(r"dynFov90\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", text)
    up, fwd, right = (float(v) for v in m.groups()) if m else (-3.0, 0.0, 0.0)
    return np.array([-fwd, right, -up])


# ------------------------------------------------------------------ the designs

def sticker_designs():
    """(code, design) of every graffiti design but the starter, in the cgame's table order."""
    text = open(NAMES_INC, encoding="utf-8").read()
    block = text[text.index("fbGraffitiNames"):]
    keys = re.findall(r'\{ "([a-z0-9_]+)",', block)
    return [(CODES[i], k) for i, k in enumerate(keys) if k != "fatboss"]
