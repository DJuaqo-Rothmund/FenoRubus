"""
tools/make_aeon_icon.py
=======================
Ícono de AeonCrop en el teléfono: la huella con el reloj de arena (sin el nombre), GRANDE,
sobre un fondo azul estelar.

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

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = 512                       # lado de cada capa
DEEP, MID = (6, 11, 38), (26, 52, 120)   # azul noche (borde) y azul estelar (centro)


def space(n: int = N, seed: int = 7) -> Image.Image:
    """Fondo: degradado radial azul, nebulosas suaves (cian y violeta) y estrellas."""
    rnd = random.Random(seed)
    y, x = [list(range(n))] * 2
    bg = Image.new("RGB", (n, n))
    px = bg.load()
    c = n / 2
    for j in y:
        for i in x:
            d = min(1.0, math.hypot(i - c, j - c * .92) / (n * .72))
            t = d ** 1.3
            px[i, j] = tuple(int(MID[k] * (1 - t) + DEEP[k] * t) for k in range(3))
    neb = Image.new("RGB", (n, n), (0, 0, 0))
    dr = ImageDraw.Draw(neb)
    for (cx, cy, r, col) in ((.28, .30, .30, (40, 150, 200)), (.78, .72, .34, (120, 60, 170)),
                             (.70, .20, .18, (60, 90, 200)), (.22, .80, .20, (30, 120, 150))):
        dr.ellipse(((cx - r) * n, (cy - r) * n, (cx + r) * n, (cy + r) * n), fill=col)
    neb = neb.filter(ImageFilter.GaussianBlur(n * .09))
    bg = ImageChops.add(bg, Image.eval(neb, lambda v: int(v * .45)))
    stars = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ds = ImageDraw.Draw(stars)
    for _ in range(int(n * .45)):
        sx, sy = rnd.random() * n, rnd.random() * n
        r = rnd.choice((.6, .8, 1.0, 1.0, 1.4, 1.8)) * n / 512
        a = rnd.randint(110, 255)
        ds.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(255, 255, 255, a))
    for _ in range(7):                               # destellos de 4 puntas
        sx, sy = rnd.random() * n, rnd.random() * n
        L, w = rnd.uniform(5, 10) * n / 512, 1.2 * n / 512
        ds.polygon([(sx, sy - L), (sx + w, sy - w), (sx + L, sy), (sx + w, sy + w), (sx, sy + L),
                    (sx - w, sy + w), (sx - L, sy), (sx - w, sy - w)], fill=(235, 245, 255, 230))
    glow = stars.filter(ImageFilter.GaussianBlur(1.2))
    bg = bg.convert("RGBA")
    bg.alpha_composite(glow)
    bg.alpha_composite(stars)
    return bg


def mark_layer(mark: Image.Image, height: float, n: int = N) -> Image.Image:
    """El logo centrado, `height` = alto relativo al lienzo, con halo claro para que
    destaque sobre el azul."""
    m = mark.crop(mark.getchannel("A").getbbox())
    k = height * n / m.height
    m = m.resize((max(1, int(m.width * k)), max(1, int(m.height * k))), Image.LANCZOS)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    pos = ((n - m.width) // 2, (n - m.height) // 2)
    halo = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    white = Image.new("RGBA", m.size, (255, 255, 255, 0))
    white.putalpha(m.getchannel("A").point(lambda v: min(255, int(v * 1.0))))
    halo.alpha_composite(white, pos)
    edge = halo.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(n * .004))
    edge.putalpha(edge.getchannel("A").point(lambda v: int(v * .55)))   # contorno fino
    soft = halo.filter(ImageFilter.GaussianBlur(n * .03))
    soft.putalpha(soft.getchannel("A").point(lambda v: int(v * .22)))   # brillo muy suave
    out.alpha_composite(soft)
    out.alpha_composite(edge)
    out.alpha_composite(m, pos)
    return out


def main(mark_path: str):
    mark = Image.open(mark_path).convert("RGBA")
    assets = os.path.join(ROOT, "assets")
    bg = space()
    bg.convert("RGB").save(os.path.join(assets, "icon_aeoncrop_bg.png"))
    # Adaptativo: se ve el círculo central de 72/108 del lienzo; el logo (ovalado) ocupa
    # el 60 % del alto, casi todo lo visible.
    mark_layer(mark, .60).save(os.path.join(assets, "icon_aeoncrop_fg.png"))
    # Un solo cuadro (Android 7-): fondo y logo grandes, con las esquinas redondeadas.
    legacy = space(N, seed=7)
    legacy.alpha_composite(mark_layer(mark, .80))
    r = int(N * .2)
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), r, fill=255)
    legacy.putalpha(mask)
    legacy.save(os.path.join(assets, "icon_aeoncrop.png"))


if __name__ == "__main__":
    main(sys.argv[1])
