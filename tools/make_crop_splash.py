"""
tools/make_crop_splash.py
=========================
Capas de la animación de carga de PhenoBlue y PhenoCran, iguales a las de PhenoRubus
(assets/ui/splash): berry.png (fruto y esfera sin manijas), ring.png (anillo punteado),
icon1..n.png (los dibujos chicos del ciclo) y layout.json. Las mueve ui/splash_anim.LogoAnim.

    node tools/crop_splash_layers.js /tmp/capas PhenoBlue PhenoCran
    python tools/make_crop_splash.py /tmp/capas

También arma los nombres «PhenoRubus», «PhenoBlue» y «PhenoCran» con la misma letra
(Chewy, Apache 2.0: tools/fonts) y el mismo relieve: assets/crops/<cultivo>/name.png.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIDE = 512
CROPS = {"PhenoBlue": "arandano", "PhenoCran": "cranberry"}
HAND_RGB = [0.2431, 0.2471, 0.2314]
# Manijas a las 10:10 (grados: 0 = 3 en punto, antihorario), largo en unidades del SVG.
HOUR, MINUTE = (23.0, 152.0), (35.0, 37.0)
HAND_W, DOT_R = 5.0, 5.2


def split(src: str, name: str, out: str) -> None:
    geom = json.load(open(os.path.join(src, f"{name}_geom.json")))
    bx, by, side = geom["box"]
    body = Image.open(os.path.join(src, f"{name}_body.png")).convert("RGBA")
    ring = Image.open(os.path.join(src, f"{name}_ring.png")).convert("RGBA")
    k = body.width / side                   # px de la imagen por unidad del SVG
    a = np.asarray(body)[..., 3] > 20
    lab, n = ndimage.label(ndimage.binary_dilation(a, iterations=int(6 * k)))
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    berry_id = 1 + int(np.argmax(sizes))
    os.makedirs(out, exist_ok=True)
    arr = np.asarray(body).copy()
    berry = arr.copy()
    berry[..., 3] = np.where(lab == berry_id, berry[..., 3], 0)
    Image.fromarray(berry).resize((SIDE, SIDE), Image.LANCZOS).save(os.path.join(out, "berry.png"))
    ring.resize((SIDE, SIDE), Image.LANCZOS).save(os.path.join(out, "ring.png"))
    W = body.width
    icons = []
    for i in range(1, n + 1):
        if i == berry_id or sizes[i - 1] < 200:
            continue
        ys, xs = np.nonzero((lab == i) & a)
        x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        piece = arr[y0:y1, x0:x1].copy()
        piece[..., 3] = np.where((lab[y0:y1, x0:x1] == i), piece[..., 3], 0)
        icons.append(((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, piece))
    # Orden: como en PhenoRubus (de la derecha y abajo hacia la izquierda y arriba).
    icons.sort(key=lambda t: -math.atan2(-(t[1] - W / 2), t[0] - W / 2))
    lay_icons = []
    for j, (cx, cy, w, h, piece) in enumerate(icons, 1):
        f = f"icon{j}.png"
        im = Image.fromarray(piece)
        scale = SIDE / W
        im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS).save(os.path.join(out, f))
        lay_icons.append({"file": f, "u": round(cx / W, 5), "v": round(1 - cy / W, 5),
                          "w": round(w / W, 5), "h": round(h / W, 5)})
    rx, ry, rw, rh = geom["ring"]
    fx, fy, _fr = geom["face"]
    layout = {
        "ring": {"u": round((rx + rw / 2 - bx) / side, 5), "v": round(1 - (ry + rh / 2 - by) / side, 5),
                 "r": round(rw / 2 / side, 5)},
        "face": {"u": round((fx - bx) / side, 5), "v": round(1 - (fy - by) / side, 5)},
        "hour": {"len": round(HOUR[0] / side, 5), "deg": HOUR[1]},
        "minute": {"len": round(MINUTE[0] / side, 5), "deg": MINUTE[1]},
        "hand_w": round(HAND_W / side, 5), "dot_r": round(DOT_R / side, 5),
        "hand_rgb": HAND_RGB, "icons": lay_icons,
    }
    with open(os.path.join(out, "layout.json"), "w", encoding="utf-8") as f:
        json.dump(layout, f, indent=1)


NAME_COLORS = {"frambuesa": ((0xA8, 0x18, 0x4A), "PhenoRubus"),
               "arandano": ((0x3E, 0x5A, 0xA8), "PhenoBlue"),
               "cranberry": ((0x9C, 0x1C, 0x34), "PhenoCran")}
GREEN = (0x1E, 0x4A, 0x3A)


def name_image(text: str, top, w: int = 1400, h: int = 300) -> Image.Image:
    """Nombre del módulo con la letra Chewy, relleno claro, borde del color de la fruta que
    pasa a verde hacia abajo y relieve hacia abajo a la derecha (como «PhenoRubus App»)."""
    font = ImageFont.truetype(os.path.join(ROOT, "tools", "fonts", "Chewy-Regular.ttf"), 210)
    mask = Image.new("L", (w, h), 0)
    tw = font.getbbox(text)[2]
    ImageDraw.Draw(mask).text(((w - tw) // 2, 20), text, font=font, fill=255)
    m = np.asarray(mask) > 127
    t = np.linspace(0, 1, h)[:, None]
    ink = (np.array(top)[None, None] * (1 - t[..., None]) + np.array(GREEN)[None, None] * t[..., None])
    ink = np.broadcast_to(ink, (h, w, 3))
    out = np.zeros((h, w, 4), float)
    # relieve: copias desplazadas en tinta oscura
    shadow = np.zeros((h, w), bool)
    for d in range(1, 13):
        shadow |= np.roll(np.roll(m, d, 0), d, 1)
    edge = ndimage.binary_dilation(m, iterations=6)
    for layer, color in ((shadow | ndimage.binary_dilation(shadow, iterations=6), ink * .55),
                         (edge, ink), (m, None)):
        if color is None:
            fill = np.array([255, 252, 246])[None, None] * np.ones((h, w, 1))
            hatch = ((np.add.outer(np.arange(h), np.arange(w)) // 6) % 3 == 0)[..., None]
            fill = np.where(hatch & (t[..., None] > .45), fill * .86 + ink * .14, fill)
            out[layer, :3] = fill[layer]
        else:
            out[layer, :3] = color[layer]
        out[layer, 3] = 255
    im = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA").filter(ImageFilter.SMOOTH)
    return im.crop(im.getbbox())


def main(src: str):
    for name, crop in CROPS.items():
        split(src, name, os.path.join(ROOT, "assets", "crops", crop, "splash"))
    for crop, (top, text) in NAME_COLORS.items():
        d = os.path.join(ROOT, "assets", "crops", crop)
        os.makedirs(d, exist_ok=True)
        name_image(text, top).save(os.path.join(d, "name.png"))


if __name__ == "__main__":
    main(sys.argv[1])
