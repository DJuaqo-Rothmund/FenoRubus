"""
tools/make_scout_assets.py
==========================
Íconos de AeonScout (assets/src/AeonScout.svg, Plagas.svg, Malezas.svg, Enfermedades.svg)
y una burbuja suave del color de cada uno (como las del inicio):

    node tools/render_svgs.js 480 /tmp/scout assets/src/AeonScout.svg assets/src/Plagas.svg \\
        assets/src/Malezas.svg assets/src/Enfermedades.svg
    python tools/make_scout_assets.py /tmp/scout

Salida: assets/ui/scout_<nombre>.png (360 px) y assets/ui/blob_scout_<nombre>.png (420 px).
"""
from __future__ import annotations

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "assets", "ui")
TINTS = {"aeonscout": (196, 228, 226), "plagas": (246, 214, 196), "malezas": (208, 234, 204),
         "enfermedades": (226, 214, 242)}
NAMES = {"aeonscout": "AeonScout", "plagas": "Plagas", "malezas": "Malezas", "enfermedades": "Enfermedades"}


def bubble(rgb) -> Image.Image:
    """La burbuja del inicio (blob_predio) con otro color: mismo sombreado y forma."""
    src = Image.open(os.path.join(UI, "blob_predio.png")).convert("RGBA")
    lum = src.convert("L")
    lo, hi = lum.getextrema()
    out = Image.new("RGBA", src.size)
    px, lp, sp = out.load(), lum.load(), src.load()
    for y in range(src.height):
        for x in range(src.width):
            k = (lp[x, y] - lo) / max(1, hi - lo) * .25 + .75
            px[x, y] = tuple(min(255, int(c * k + 255 * (1 - k) * .3)) for c in rgb) + (sp[x, y][3],)
    return out


def main(src: str):
    for key, name in NAMES.items():
        icon = Image.open(os.path.join(src, name + ".png")).convert("RGBA")
        icon.crop(icon.getchannel("A").getbbox())
        icon.resize((360, 360), Image.LANCZOS).save(os.path.join(UI, f"scout_{key}.png"))
        bubble(TINTS[key]).save(os.path.join(UI, f"blob_scout_{key}.png"))


if __name__ == "__main__":
    main(sys.argv[1])
