"""
tools/make_ai_assets.py
=======================
Imágenes de la identidad IA (violeta · púrpura · índigo, neón y estelar):

* assets/ui/cyber_berry.png  — frambuesa «cibernética»: la frambuesa de siempre, con la mitad
  derecha cruzada por pistas de circuito neón (como el cerebro de IA+: mitad naturaleza, mitad
  tecnología) y un aura morada con estrellas. Abre el Entrenador IA (juegos, modelo y datos).
* assets/ui/ai_aura.png      — aura estelar (anillo violeta → azul con destellos) que va DETRÁS
  del logo de IA+ sin cambiarle los colores.

    python tools/make_ai_assets.py
"""
from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "assets", "ui")

VIOLET = (124, 77, 255)
PURPLE = (177, 77, 255)
INDIGO = (61, 90, 254)
MAGENTA = (224, 64, 251)
CYAN = (110, 200, 255)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _glow(mask: Image.Image, color, radius: float, strength: float = 1.0) -> Image.Image:
    a = mask.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * strength)))
    out = Image.new("RGBA", mask.size, color + (0,))
    out.putalpha(a)
    return out


def _stars(size, n, seed, box=None, rmax=3.2):
    rnd = random.Random(seed)
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box or (0, 0, size[0], size[1])
    for _ in range(n):
        x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        r = rnd.uniform(.8, rmax)
        col = _lerp(INDIGO, MAGENTA, rnd.random())
        col = _lerp(col, (255, 255, 255), .55)
        d.ellipse((x - r, y - r, x + r, y + r), fill=col + (255,))
        if r > 2.4:                                   # destello en cruz
            L = r * 3.2
            d.line((x - L, y, x + L, y), fill=col + (170,), width=1)
            d.line((x, y - L, x, y + L), fill=col + (170,), width=1)
    return im


def cyber_berry(out=os.path.join(UI, "cyber_berry.png"), S=512):
    berry = Image.open(os.path.join(UI, "berries", "meeker.png")).convert("RGBA")
    k = (S * .62) / max(berry.size)
    berry = berry.resize((int(berry.width * k), int(berry.height * k)), Image.LANCZOS)
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bx, by = (S - berry.width) // 2, (S - berry.height) // 2 + int(S * .02)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    layer.paste(berry, (bx, by), berry)
    alpha = layer.getchannel("A")

    # Mitad derecha «tecnológica»: un velo violeta-índigo y pistas de circuito neón.
    cx = bx + berry.width * .5
    tech = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    td = ImageDraw.Draw(tech)
    td.rectangle((cx, 0, S, S), fill=INDIGO + (70,))
    rnd = random.Random(5)
    for i in range(11):
        y = by + berry.height * (.12 + .78 * i / 10) + rnd.uniform(-6, 6)
        x = cx + rnd.uniform(4, 18)
        pts = [(x, y)]
        for _ in range(3):
            x += rnd.uniform(22, 48)
            if rnd.random() < .6:
                y += rnd.choice([-1, 1]) * rnd.uniform(10, 26)
            pts.append((x, y))
        col = _lerp(CYAN, MAGENTA, i / 10)
        td.line(pts, fill=col + (255,), width=4, joint="curve")
        for px, py in (pts[0], pts[-1]):
            td.ellipse((px - 6, py - 6, px + 6, py + 6), fill=(255, 255, 255, 255), outline=col + (255,), width=3)
    td.line((cx, by + 8, cx, by + berry.height - 8), fill=(220, 210, 255, 200), width=3)   # costura
    tech.putalpha(ImageChops.multiply(tech.getchannel("A"), alpha))
    glow_lines = tech.filter(ImageFilter.GaussianBlur(5))
    layer = Image.alpha_composite(layer, glow_lines)
    layer = Image.alpha_composite(layer, tech)

    # Aura morada → índigo (dos capas) y estrellas alrededor.
    dil = alpha.filter(ImageFilter.MaxFilter(31))
    canvas = Image.alpha_composite(canvas, _glow(dil, INDIGO, 34, 1.1))
    canvas = Image.alpha_composite(canvas, _glow(dil, PURPLE, 18, 1.3))
    canvas = Image.alpha_composite(canvas, _glow(alpha, MAGENTA, 6, 1.2))
    st = _stars((S, S), 26, 3)
    st.putalpha(ImageChops.multiply(st.getchannel("A"), Image.eval(dil.filter(ImageFilter.GaussianBlur(40)),
                                                                    lambda v: 255 - v)))
    canvas = Image.alpha_composite(canvas, st)
    canvas = Image.alpha_composite(canvas, layer)
    canvas.save(out)
    print(out)


def ai_aura(out=os.path.join(UI, "ai_aura.png"), S=512):
    """Anillo estelar: degradado violeta → azul alrededor de un círculo (el logo va encima)."""
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c = S / 2
    r_logo = S * .30
    ring = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ring).ellipse((c - r_logo * 1.06, c - r_logo * 1.06, c + r_logo * 1.06, c + r_logo * 1.06), fill=255)
    # Color que gira alrededor (violeta arriba-izq., azul abajo-der., magenta al lado).
    col = Image.new("RGBA", (S, S))
    px = col.load()
    for y in range(S):
        for x in range(S):
            a = (math.atan2(y - c, x - c) + math.pi) / (2 * math.pi)
            t = .5 + .5 * math.sin(a * 2 * math.pi)
            u = .5 + .5 * math.cos(a * 4 * math.pi)
            px[x, y] = _lerp(_lerp(PURPLE, INDIGO, t), MAGENTA, u * .35) + (255,)
    for rad, k in ((40, 1.0), (22, 1.2), (9, 1.4)):
        g = ring.filter(ImageFilter.GaussianBlur(rad)).point(lambda v, k=k: min(255, int(v * k)))
        layer = col.copy()
        layer.putalpha(g)
        im = Image.alpha_composite(im, layer)
    hole = Image.new("L", (S, S), 0)                   # el centro queda libre (lo tapa el logo)
    ImageDraw.Draw(hole).ellipse((c - r_logo, c - r_logo, c + r_logo, c + r_logo), fill=255)
    im.putalpha(ImageChops.subtract(im.getchannel("A"), hole))
    stars = _stars((S, S), 34, 9, rmax=3.6)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((c - S * .48, c - S * .48, c + S * .48, c + S * .48), fill=255)
    ImageDraw.Draw(mask).ellipse((c - r_logo * 1.1, c - r_logo * 1.1, c + r_logo * 1.1, c + r_logo * 1.1), fill=0)
    stars.putalpha(ImageChops.multiply(stars.getchannel("A"), mask))
    im = Image.alpha_composite(im, stars)
    im.save(out)
    print(out)


if __name__ == "__main__":
    cyber_berry()
    ai_aura()
