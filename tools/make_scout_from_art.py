"""
tools/make_scout_from_art.py
============================
Íconos y logo de AeonScout a partir de los dibujos A COLOR hechos con Flow (fondo blanco):

    assets/src/flow/{plagas,malezas,enfermedades,aeonscout}_color.jpg -> assets/ui/scout_<nombre>.png (360 px)
    assets/src/flow/aeonscout_pheno.jpg                                -> assets/ui/scout_logo.png     (384 px)

    python tools/make_scout_from_art.py            # a color (lo que usa la app)
    python tools/make_scout_from_art.py --line     # versión antigua: dibujos a línea de un solo color

A color: el blanco del fondo (el que toca el borde, y los huecos blancos grandes encerrados)
pasa a transparente; los blancos pequeños dentro del dibujo (brillos, la lupa) se mantienen.
En el borde la transparencia sale de qué tan blanco es el punto y se le quita el blanco al
color, para que no quede un halo. Se recorta al dibujo y se centra en un cuadrado.
Las burbujas de color (blob_scout_*.png) las hace tools/make_scout_assets.py.
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "src", "flow")
UI = os.path.join(ROOT, "assets", "ui")
SIDE, LOGO_SIDE, MARGIN = 360, 384, .04
WHITE = 232            # min(R,G,B) por encima de esto cuenta como blanco
HOLE = 0.0012          # huecos blancos encerrados más grandes que esta fracción de la imagen: fondo


def _square(im: Image.Image, side: int) -> Image.Image:
    box = im.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
    im = im.crop(box)
    n = int(max(im.size) / (1 - 2 * MARGIN))
    sq = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    sq.alpha_composite(im, ((n - im.width) // 2, (n - im.height) // 2))
    return sq.resize((side, side), Image.LANCZOS)


def _background(white: np.ndarray) -> np.ndarray:
    """Zonas blancas conectadas que tocan el borde, o encerradas pero grandes: fondo."""
    h, w = white.shape
    flat = white.ravel()
    label = np.zeros(h * w, np.int32)
    limit = HOLE * h * w
    bg = np.zeros(h * w, bool)
    n = 0
    for start in np.flatnonzero(flat):
        if label[start]:
            continue
        n += 1
        label[start] = n
        stack, members, edge = [int(start)], [], False
        while stack:
            i = stack.pop()
            members.append(i)
            y, x = divmod(i, w)
            if y == 0 or x == 0 or y == h - 1 or x == w - 1:
                edge = True
            for j in ((i - w) if y else -1, (i + w) if y < h - 1 else -1,
                      (i - 1) if x else -1, (i + 1) if x < w - 1 else -1):
                if j >= 0 and flat[j] and not label[j]:
                    label[j] = n
                    stack.append(j)
        if edge or len(members) > limit:
            bg[members] = True
    return bg.reshape(h, w)


def cutout_color(path: str, side: int) -> Image.Image:
    img = Image.open(path).convert("RGB")
    rgb = np.asarray(img).astype(float)
    lo = rgb.min(axis=2)
    bg = _background(lo > WHITE)
    # franja de borde: puntos del dibujo junto al fondo
    bgi = Image.fromarray((bg * 255).astype(np.uint8), "L")
    near = np.asarray(bgi.filter(ImageFilter.MaxFilter(5))) > 0
    soft = np.clip((255 - lo) / (255 - 150), 0, 1)        # qué tan "no blanco" es
    alpha = np.where(bg, 0.0, np.where(near, soft, 1.0))
    a = np.maximum(alpha, 1e-3)[..., None]
    col = np.clip((rgb - 255 * (1 - a)) / a, 0, 255)      # quita el blanco mezclado
    out = np.zeros(rgb.shape[:2] + (4,), np.uint8)
    out[..., :3] = col.astype(np.uint8)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return _square(Image.fromarray(out, "RGBA"), side)


def cutout_line(path: str) -> Image.Image:
    """Dibujo a línea: la tinta de un solo color (el del dibujo)."""
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(float)
    lum = rgb @ np.array([.299, .587, .114])
    ink_mask = lum < np.percentile(lum, 2) + 25
    ink = np.median(rgb[ink_mask], axis=0)
    ink_lum = float(ink @ np.array([.299, .587, .114]))
    alpha = np.clip((250 - lum) / max(1.0, 250 - ink_lum), 0, 1)
    out = np.zeros(rgb.shape[:2] + (4,), np.uint8)
    out[..., :3] = ink.astype(np.uint8)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return _square(Image.fromarray(out, "RGBA"), SIDE)


def main(line: bool = False):
    for name in ("aeonscout", "plagas", "malezas", "enfermedades"):
        if line:
            im = cutout_line(os.path.join(SRC, name + ".jpg"))
        else:
            im = cutout_color(os.path.join(SRC, name + "_color.jpg"), SIDE)
        im.save(os.path.join(UI, f"scout_{name}.png"))
    if not line:
        cutout_color(os.path.join(SRC, "aeonscout_pheno.jpg"), LOGO_SIDE).save(os.path.join(UI, "scout_logo.png"))


if __name__ == "__main__":
    main("--line" in sys.argv)
