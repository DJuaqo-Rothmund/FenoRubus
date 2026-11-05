"""
tools/make_scout_from_art.py
============================
Íconos de AeonScout a partir de los dibujos a línea hechos con Flow (fondo blanco):
assets/src/flow/{aeonscout,plagas,malezas,enfermedades}.jpg.

    python tools/make_scout_from_art.py

El blanco pasa a transparente (bordes suaves: la transparencia sale de qué tan oscuro es
cada punto), la tinta queda de un solo color (el del dibujo), se recorta al dibujo y se
centra en un cuadrado de 360 px: assets/ui/scout_<nombre>.png. Las burbujas de color
(blob_scout_*.png) las hace tools/make_scout_assets.py.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "src", "flow")
UI = os.path.join(ROOT, "assets", "ui")
SIDE, MARGIN = 360, .04


def cutout(path: str) -> Image.Image:
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(float)
    lum = rgb @ np.array([.299, .587, .114])
    ink_mask = lum < np.percentile(lum, 2) + 25            # los trazos más oscuros
    ink = np.median(rgb[ink_mask], axis=0)
    ink_lum = float(ink @ np.array([.299, .587, .114]))
    alpha = np.clip((250 - lum) / max(1.0, 250 - ink_lum), 0, 1)
    out = np.zeros(rgb.shape[:2] + (4,), np.uint8)
    out[..., :3] = ink.astype(np.uint8)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    im = Image.fromarray(out, "RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
    im = im.crop(box)
    side = int(max(im.size) / (1 - 2 * MARGIN))
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return sq.resize((SIDE, SIDE), Image.LANCZOS)


def main():
    for name in ("aeonscout", "plagas", "malezas", "enfermedades"):
        cutout(os.path.join(SRC, name + ".jpg")).save(os.path.join(UI, f"scout_{name}.png"))


if __name__ == "__main__":
    main()
