"""
tools/make_tech_assets.py
=========================
Imágenes de los estilos «Aurora» y «Cristal» (Ajustes › Estilo):

* assets/styles/aurora/background.jpg    azul casi negro con luces de aurora y cuadrícula tenue
* assets/styles/cristal/background.jpg   blanco hielo con un velo de color muy suave
* assets/crops/<cultivo>/fruit_simple.png  el fruto del logo sin la órbita de estados

    python tools/make_tech_assets.py
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(ROOT, "assets")


def _glow(h, w, cx, cy, rx, ry, color, strength):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = ((xx - cx * w) / (rx * w)) ** 2 + ((yy - cy * h) / (ry * h)) ** 2
    k = np.clip(1 - d, 0, 1) ** 2 * strength
    return k[..., None] * np.array(color, np.float32)


def aurora(out, w=720, h=1280):
    im = np.zeros((h, w, 3), np.float32) + np.array((7, 11, 20), np.float32)
    im += _glow(h, w, .88, -.02, .75, .34, (0, 255, 170), .26)
    im += _glow(h, w, -.02, .30, .70, .32, (255, 45, 130), .22)
    im += _glow(h, w, .62, 1.04, .80, .36, (60, 120, 255), .26)
    step = 36                                                   # cuadrícula tenue
    im[::step, :, :] += 7
    im[:, ::step, :] += 7
    rng = np.random.default_rng(7)
    im += rng.normal(0, 1.2, (h, w, 1))                         # sin bandas en el degradado
    Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).save(out, quality=90)


def cristal(out, w=720, h=1280):
    im = np.zeros((h, w, 3), np.float32) + np.array((244, 246, 250), np.float32)
    im -= _glow(h, w, .95, .02, .8, .34, (255 - 255, 255 - 214, 255 - 232), .55)    # velo rosado
    im -= _glow(h, w, .0, .98, .8, .34, (255 - 214, 255 - 228, 255 - 255), .5)      # velo azul
    rng = np.random.default_rng(3)
    im += rng.normal(0, .8, (h, w, 1))
    Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).save(out, quality=92)


def largest_part(src, out, pad=10):
    """El fruto del logo sin la órbita: se queda con la mancha más grande (el anillo
    punteado y los estados de alrededor son manchas aparte)."""
    im = Image.open(src).convert("RGBA")
    px = np.asarray(im).astype(np.int32)
    ring = (np.abs(px[..., :3] - np.array((176, 170, 160))).max(-1) < 14) & (px[..., 3] > 0)   # anillo gris
    px[ring] = 0
    im = Image.fromarray(px.astype(np.uint8), "RGBA")
    a = np.asarray(im)[..., 3] > 40
    h, w = a.shape
    label = np.zeros((h, w), np.int32)
    sizes = {}
    n = 0
    for y0 in range(h):
        for x0 in range(w):
            if a[y0, x0] and not label[y0, x0]:
                n += 1
                stack, count = [(y0, x0)], 0
                label[y0, x0] = n
                while stack:
                    y, x = stack.pop()
                    count += 1
                    for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                        if 0 <= yy < h and 0 <= xx < w and a[yy, xx] and not label[yy, xx]:
                            label[yy, xx] = n
                            stack.append((yy, xx))
                sizes[n] = count
    keep = max(sizes, key=sizes.get)
    arr = np.asarray(im).copy()
    arr[label != keep] = 0
    ys, xs = np.where(label == keep)
    box = (max(0, xs.min() - pad), max(0, ys.min() - pad), min(w, xs.max() + pad), min(h, ys.max() + pad))
    cut = Image.fromarray(arr, "RGBA").crop(box)
    side = max(cut.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(cut, ((side - cut.width) // 2, (side - cut.height) // 2), cut)
    sq.save(out)


def main():
    for name, fn in (("aurora", aurora), ("cristal", cristal)):
        d = os.path.join(A, "styles", name)
        os.makedirs(d, exist_ok=True)
        fn(os.path.join(d, "background.jpg"))
    for crop, src in (("frambuesa", os.path.join(A, "ui", "logo.png")),
                      ("arandano", os.path.join(A, "crops", "arandano", "logo.png")),
                      ("cranberry", os.path.join(A, "crops", "cranberry", "logo.png"))):
        largest_part(src, os.path.join(A, "crops", crop, "fruit_simple.png"))


if __name__ == "__main__":
    main()
