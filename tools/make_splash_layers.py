"""
tools/make_splash_layers.py
===========================
Separa el logo (assets/logo_source.png) en capas para la animación de apertura:

* berry.png  la frambuesa grande con la esfera del reloj SIN manijas.
* ring.png   el círculo punteado.
* icon1..5   los dibujos chicos del ciclo (brote, flor, frambuesas…), recortados.
* layout.json  posiciones (0..1 del cuadrado del logo, y hacia arriba), centro y radio
             del círculo, centro de la esfera y largo/grosor/ángulo final de las manijas.

Todo sobre el mismo cuadrado que assets/ui/logo.png (make_ui_assets.load_logo), para que
la animación calce exacto con el logo fijo. También rehace assets/presplash.png con solo
la frambuesa y el reloj en 9:10: lo demás aparece animado al abrir la app.

    python tools/make_splash_layers.py
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_ui_assets as ui  # noqa: E402

OUT = os.path.join(ROOT, "assets", "ui", "splash")
SIDE = 512
RING_RGB = (180, 172, 168)
HAND_RGB = (61, 63, 59)
# Medido sobre logo_source.png (384 × 369): esfera y manijas (10:10).
FACE = (236.25, 177.5)
HOUR = (26.8, 152.0)        # largo (px), ángulo (grados, 0 = 3 en punto, antihorario)
MINUTE = (37.1, 32.6)
HAND_W, DOT_R = 5.6, 6.0


def main():
    os.makedirs(OUT, exist_ok=True)
    src = Image.open(ui.LOGO_SRC).convert("RGBA")
    im = np.array(src).astype(int)
    rgb, a = im[..., :3], im[..., 3]
    h, w = a.shape
    yy, xx = np.mgrid[:h, :w]

    # Círculo punteado: color gris del trazo cerca del círculo ajustado.
    d = np.abs(rgb - np.array(RING_RGB)).sum(-1)
    ys, xs = np.nonzero((a > 60) & (d < 45))
    A = np.c_[2 * xs, 2 * ys, np.ones(len(xs))]
    cx, cy, c0 = np.linalg.lstsq(A, xs ** 2 + ys ** 2, rcond=None)[0]
    R = math.sqrt(c0 + cx ** 2 + cy ** 2)
    ring = (a > 0) & (d < 70) & (np.abs(np.hypot(xx - cx, yy - cy) - R) < 9)

    # Piezas: la frambuesa (la más grande) y los dibujos chicos.
    lab, n = ndimage.label((a > 20) & ~ring)
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    big = int(np.argmax(sizes)) + 1

    # Esfera sin manijas: todo lo oscuro dentro de la esfera menos las 4 marcas.
    fx, fy = FACE
    rr = np.hypot(xx - fx, yy - fy)
    ang = np.degrees(np.arctan2(-(yy - fy), xx - fx))
    near_tick = np.zeros_like(rr, bool)
    for t in (0, 90, 180, -90):
        near_tick |= (np.abs(((ang - t + 180) % 360) - 180) < 11) & (rr > 27)
    hands = (rr < 42) & ~near_tick & (lab == big)        # esfera lisa (sin restos)

    # Recorte y cuadrado igual que load_logo().
    bbox = src.getbbox()
    cw, ch = bbox[2] - bbox[0], bbox[3] - bbox[1]
    side0 = max(cw, ch)
    ox, oy = (side0 - cw) // 2 - bbox[0], (side0 - ch) // 2 - bbox[1]
    k = SIDE / side0

    def to_square(mask=None, fill_white=None):
        arr = im.copy()
        if mask is not None:
            arr[..., 3] = np.where(mask, arr[..., 3], 0)
        if fill_white is not None:
            arr[fill_white] = [255, 255, 255, 255]
        layer = Image.fromarray(arr.clip(0, 255).astype("uint8"), "RGBA").crop(bbox)
        sq = Image.new("RGBA", (side0, side0), (0, 0, 0, 0))
        sq.paste(layer, ((side0 - cw) // 2, (side0 - ch) // 2))
        return sq.resize((SIDE, SIDE), Image.LANCZOS)

    def norm(x, y):        # píxel del original -> (u, v) del cuadrado, v hacia arriba
        return round((x + ox) / side0, 5), round(1 - (y + oy) / side0, 5)

    to_square(lab == big, fill_white=hands).save(os.path.join(OUT, "berry.png"))
    # Los dibujos chicos tienen grises parecidos al círculo: lo que el círculo les quitó
    # cerca de cada dibujo vuelve al dibujo y sale del círculo.
    pieces = {}
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if i != big and (lab[sl] == i).sum() >= 200:
            grow = ndimage.binary_dilation(lab == i, iterations=4)
            pieces[i] = (lab == i) | (ring & grow)
            ring = ring & ~grow
    to_square(ring).save(os.path.join(OUT, "ring.png"))

    icons = []
    for i, mask in pieces.items():
        sq = to_square(mask)
        box = sq.getbbox()
        sq.crop(box).save(os.path.join(OUT, f"icon{len(icons) + 1}.png"))
        u, v = (box[0] + box[2]) / 2 / SIDE, 1 - (box[1] + box[3]) / 2 / SIDE
        icons.append({"file": f"icon{len(icons) + 1}.png", "u": round(u, 5), "v": round(v, 5),
                      "w": round((box[2] - box[0]) / SIDE, 5), "h": round((box[3] - box[1]) / SIDE, 5)})

    rc, fc = norm(cx, cy), norm(fx, fy)
    layout = {
        "ring": {"u": rc[0], "v": rc[1], "r": round(R / side0, 5)},
        "face": {"u": fc[0], "v": fc[1]},
        "hour": {"len": round(HOUR[0] / side0, 5), "deg": HOUR[1]},
        "minute": {"len": round(MINUTE[0] / side0, 5), "deg": MINUTE[1]},
        "hand_w": round(HAND_W / side0, 5), "dot_r": round(DOT_R / side0, 5),
        "hand_rgb": [round(c / 255, 4) for c in HAND_RGB],
        "icons": icons,
    }
    with open(os.path.join(OUT, "layout.json"), "w", encoding="utf-8") as f:
        json.dump(layout, f, indent=1)

    # Presplash: solo la frambuesa con el reloj en 9:10 (sin círculo ni dibujos). La
    # animación arranca desde ahí y en una vuelta del minutero llega a las 10:10 del logo.
    from PIL import ImageDraw
    ss = 4
    berry = Image.open(os.path.join(OUT, "berry.png")).convert("RGBA")
    hands = Image.new("RGBA", (SIDE * ss, SIDE * ss), (0, 0, 0, 0))
    dr = ImageDraw.Draw(hands)
    fu, fv = layout["face"]["u"] * SIDE * ss, (1 - layout["face"]["v"]) * SIDE * ss
    wid = layout["hand_w"] * SIDE * ss
    ink = HAND_RGB + (255,)
    for key, extra in (("hour", 30), ("minute", 0)):
        r = math.radians(layout[key]["deg"] + extra)
        ln = layout[key]["len"] * SIDE * ss
        x1, y1 = fu + math.cos(r) * ln, fv - math.sin(r) * ln
        dr.line((fu, fv, x1, y1), fill=ink, width=round(wid))
        dr.ellipse((x1 - wid / 2, y1 - wid / 2, x1 + wid / 2, y1 + wid / 2), fill=ink)
    d = layout["dot_r"] * SIDE * ss
    dr.ellipse((fu - d, fv - d, fu + d, fv + d), fill=ink)
    first = Image.alpha_composite(berry, hands.resize((SIDE, SIDE), Image.LANCZOS))
    ui.load_logo = lambda size: first.resize((size, size), Image.LANCZOS)
    ui.make_presplash()
    print("Capas en", OUT, "·", len(icons), "dibujos")


if __name__ == "__main__":
    main()
