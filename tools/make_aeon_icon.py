"""
tools/make_aeon_icon.py
=======================
Ícono de AeonCrop en el teléfono: la huella con el reloj de arena (sin el nombre), GRANDE,
sobre un fondo CLARO (blanco cálido al centro que pasa a menta suave, con toques pastel
verde y frambuesa y unos destellos), para que destaque en el cajón de aplicaciones.

    node tools/render_aeon_icon.js /tmp/marca.png
    python tools/make_aeon_icon.py /tmp/marca.png

* assets/icon_aeoncrop_bg.png + assets/icon_aeoncrop_fg.png: ícono ADAPTATIVO (Android 8+):
  el fondo llena toda la forma que use el teléfono (círculo, gota, cuadrado redondeado) y el
  logo va encima. Del lienzo de 108 dp se ven los 72 dp del centro: el logo ocupa casi todo
  ese círculo visible.
* assets/icon_aeoncrop.png: el mismo diseño en un solo cuadro (Android 7 y anteriores).
"""
from __future__ import annotations

import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = 512                                   # lado de cada capa
CENTER, EDGE = (255, 253, 247), (190, 228, 204)   # blanco cálido y menta suave
LEAF, BERRY = (46, 158, 80), (192, 42, 94)        # colores del logo (destellos)


def light(n: int = N, seed: int = 7) -> Image.Image:
    """Fondo: degradado radial claro, manchas pastel muy suaves y destellos."""
    rnd = random.Random(seed)
    bg = Image.new("RGB", (n, n))
    px = bg.load()
    c = n / 2
    for j in range(n):
        for i in range(n):
            t = min(1.0, math.hypot(i - c, j - c * .95) / (n * .7)) ** 1.6
            px[i, j] = tuple(int(CENTER[k] * (1 - t) + EDGE[k] * t) for k in range(3))
    bg = bg.convert("RGBA")
    blobs = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(blobs)
    for (cx, cy, r, col) in ((.16, .20, .20, (150, 215, 170, 90)), (.86, .84, .22, (240, 170, 200, 80)),
                             (.86, .14, .14, (170, 220, 200, 70)), (.12, .88, .14, (245, 190, 210, 60))):
        d.ellipse(((cx - r) * n, (cy - r) * n, (cx + r) * n, (cy + r) * n), fill=col)
    bg.alpha_composite(blobs.filter(ImageFilter.GaussianBlur(n * .07)))
    sparks = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sparks)
    for k in range(9):                    # destellos de 4 puntas cerca de los bordes
        while True:
            sx, sy = rnd.random() * n, rnd.random() * n
            if math.hypot(sx - c, sy - c) > n * .36:
                break
        L, w = rnd.uniform(5, 9) * n / 512, 1.3 * n / 512
        col = (LEAF if k % 2 else BERRY) + (150,)
        ds.polygon([(sx, sy - L), (sx + w, sy - w), (sx + L, sy), (sx + w, sy + w), (sx, sy + L),
                    (sx - w, sy + w), (sx - L, sy), (sx - w, sy - w)], fill=col)
    bg.alpha_composite(sparks)
    return bg


def mark_layer(mark: Image.Image, height: float, n: int = N) -> Image.Image:
    """El logo centrado (`height` = alto relativo al lienzo) con una sombra muy leve."""
    m = mark.crop(mark.getchannel("A").getbbox())
    k = height * n / m.height
    m = m.resize((max(1, int(m.width * k)), max(1, int(m.height * k))), Image.LANCZOS)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    pos = ((n - m.width) // 2, (n - m.height) // 2)
    shadow = Image.new("RGBA", m.size, (20, 60, 40, 0))
    shadow.putalpha(m.getchannel("A").point(lambda v: int(v * .28)))
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    layer.alpha_composite(shadow, (pos[0], pos[1] + int(n * .008)))
    out.alpha_composite(layer.filter(ImageFilter.GaussianBlur(n * .008)))
    out.alpha_composite(m, pos)
    return out


def main(mark_path: str):
    mark = Image.open(mark_path).convert("RGBA")
    assets = os.path.join(ROOT, "assets")
    light().convert("RGB").save(os.path.join(assets, "icon_aeoncrop_bg.png"))
    # Adaptativo: se ve el círculo central de 72/108 del lienzo; el logo (ovalado) ocupa
    # el 60 % del alto, casi todo lo visible.
    mark_layer(mark, .60).save(os.path.join(assets, "icon_aeoncrop_fg.png"))
    # Un solo cuadro (Android 7-): fondo y logo grandes, con las esquinas redondeadas.
    legacy = light()
    legacy.alpha_composite(mark_layer(mark, .80))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), int(N * .2), fill=255)
    legacy.putalpha(mask)
    legacy.save(os.path.join(assets, "icon_aeoncrop.png"))


if __name__ == "__main__":
    main(sys.argv[1])
