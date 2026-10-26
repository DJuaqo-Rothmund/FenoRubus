"""
Genera las imágenes de la pantalla de inicio (fondo con color, burbujas de los íconos,
cerebro celeste y su brillo). Se ejecuta en el computador, no en el teléfono:

    python tools/make_start_assets.py
"""
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ui")


def tint(im, rgb, op=1.0):
    out = Image.new("RGBA", im.size, rgb + (0,))
    out.putalpha(im.split()[3].point(lambda v: int(v * op)))
    return out


def background(w=824, h=1720):
    y = np.linspace(0, 1, h)[:, None]
    top, mid, bot = np.array((222, 239, 214)), np.array((250, 246, 238)), np.array((246, 214, 226))
    c = np.where(y < .5, top + (mid - top) * (y / .5), mid + (bot - mid) * ((y - .5) / .5))
    bg = Image.fromarray(np.repeat(c[:, None, :], w, axis=1).astype("uint8")).convert("RGBA")
    pred = Image.open(os.path.join(UI, "start_predio.png")).convert("RGBA").resize((440, 440))
    logo = Image.open(os.path.join(UI, "logo_line.png")).convert("RGBA").resize((400, 400))
    for im, cx, cy, rot, op in ((tint(logo, (168, 24, 74), .15), -60, 1520, 18, 1),
                                (tint(pred, (47, 86, 67), .12), 800, 500, -20, 1),
                                (tint(logo, (168, 24, 74), .10), 840, 1640, -12, 1)):
        im = im.rotate(rot, expand=True, resample=Image.BICUBIC)
        bg.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))
    bg.convert("RGB").save(os.path.join(UI, "start_bg.jpg"), quality=86)


def blob(n, rgb, seed, stars=False):
    random.seed(seed)
    m = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(m)
    pts = []
    for k in range(10):
        t = 2 * math.pi * k / 10
        r = n * (0.36 + random.uniform(-.035, .045))
        pts.append((n / 2 + r * math.cos(t), n / 2 + r * math.sin(t)))
    d.polygon(pts, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(n * .05)).point(lambda v: 255 if v > 128 else 0)
    m = m.filter(ImageFilter.GaussianBlur(1.5))
    shadow = Image.new("RGBA", (n, n), (60, 30, 50, 0))
    shadow.putalpha(m.filter(ImageFilter.GaussianBlur(n * .04)).point(lambda v: v * 50 // 255))
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.alpha_composite(shadow, (3, int(n * .03)))
    body = Image.new("RGBA", (n, n), rgb + (0,))
    body.putalpha(m)
    out.alpha_composite(body)
    if stars:
        d = ImageDraw.Draw(out)
        random.seed(3)
        for _ in range(40):
            r = random.uniform(0.05, 0.30) * n
            t = random.uniform(0, 2 * math.pi)
            x, y = n / 2 + r * math.cos(t), n / 2 + r * math.sin(t)
            s = random.choice((1.2, 1.2, 1.8, 2.4))
            d.ellipse([x - s, y - s, x + s, y + s], fill=(255, 255, 255, random.randint(110, 230)))
    return out


def bar_icons():
    """Barra del muestreo: cerebro azul destacado (sin destellos) y botón de Drive."""
    from scipy import ndimage as nd
    ai = Image.open(os.path.join(UI, "start_ai.png")).convert("RGBA")
    a = np.asarray(ai)[..., 3] > 60
    lab, n = nd.label(nd.binary_dilation(a, iterations=2))
    sizes = nd.sum(a, lab, range(1, n + 1))
    keep = np.isin(lab, [int(np.argmax(sizes)) + 1])
    arr = np.asarray(ai).copy()
    arr[..., 3] = (arr[..., 3] * keep).astype("uint8")
    core = Image.fromarray(arr)
    core = core.crop(core.getbbox())
    side = max(core.size) + 16
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.alpha_composite(core, ((side - core.width) // 2, (side - core.height) // 2))
    sq.resize((144, 144), Image.LANCZOS).save(os.path.join(UI, "ai_bar.png"))

    from PIL import ImageFont
    from kivymd import fonts_path
    from kivymd.icon_definitions import md_icons
    font = ImageFont.truetype(os.path.join(fonts_path, "materialdesignicons-webfont.ttf"), 120)
    small = ImageFont.truetype(os.path.join(fonts_path, "materialdesignicons-webfont.ttf"), 40)
    ink = (0x1E, 0x4A, 0x3A, 255)

    def drive(badge, color):
        im = Image.new("RGBA", (144, 144), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.text((60, 66), md_icons["google-drive"], font=font, fill=ink, anchor="mm")
        if badge:
            d.ellipse([86, 86, 142, 142], fill=color, outline=(255, 255, 255, 255), width=5)
            d.text((114, 115), md_icons[badge], font=small, fill=(255, 255, 255, 255), anchor="mm")
        return im

    drive("arrow-up-bold", (0xA8, 0x18, 0x4A, 255)).save(os.path.join(UI, "drive_up.png"))
    drive("check-bold", (0x2F, 0x6B, 0x4F, 255)).save(os.path.join(UI, "drive_ok.png"))
    drive("cloud-off-outline", (0x8A, 0x8F, 0x80, 255)).save(os.path.join(UI, "drive_off.png"))
    for k in range(8):   # círculo de carga (8 cuadros)
        im = Image.new("RGBA", (144, 144), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([22, 22, 122, 122], outline=(0x1E, 0x4A, 0x3A, 50), width=12)
        d.arc([22, 22, 122, 122], k * 45, k * 45 + 110, fill=(0xA8, 0x18, 0x4A, 255), width=12)
        im.save(os.path.join(UI, f"spin_{k}.png"))


def notebook_icon():
    """Cuaderno de campo: cuaderno con espiral, renglones y lápiz, con una frambuesa en la
    esquina y destellos; trazo café (como el resto de los íconos de inicio) y burbuja ocre."""
    import math as _m
    S = 4                                   # se dibuja a 4× y se reduce (bordes suaves)
    n = 360 * S
    ink = (0x6B, 0x44, 0x23, 255)           # café
    paper = (250, 246, 238, 255)
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = 12 * S

    def dot(x, y, r):
        d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=ink)

    def line(pts, width=w):
        d.line([(x * S, y * S) for x, y in pts], fill=ink, width=width, joint="curve")
        for x, y in (pts[0], pts[-1]):
            dot(x, y, width / S / 2)

    def star(x, y, r):                       # destello de 4 puntas
        k = r * .28
        pts = [(x, y - r), (x + k, y - k), (x + r, y), (x + k, y + k), (x, y + r), (x - k, y + k), (x - r, y), (x - k, y - k)]
        d.polygon([(a * S, b * S) for a, b in pts], fill=ink)

    # tapa y hoja interior
    d.rounded_rectangle([78 * S, 38 * S, 268 * S, 312 * S], radius=24 * S, outline=ink, width=w)
    d.rounded_rectangle([104 * S, 60 * S, 246 * S, 290 * S], radius=12 * S, outline=ink, width=int(w * .7))
    # espiral: anillos que cruzan el borde izquierdo
    for k in range(7):
        y = 70 + k * 34
        d.rounded_rectangle([60 * S, (y - 7) * S, 98 * S, (y + 7) * S], radius=7 * S, outline=ink, width=int(w * .65))
        d.rectangle([80 * S, (y - 3) * S, 96 * S, (y + 3) * S], fill=paper)
    # renglones
    for k, x1 in enumerate((222, 222, 200, 222, 170)):
        y = 98 + k * 28
        line([(126, y), (x1, y)], int(w * .65))
    # lápiz en diagonal
    a, b = (150, 262), (246, 150)
    ang = _m.atan2(b[1] - a[1], b[0] - a[0])
    px, py = -_m.sin(ang) * 13, _m.cos(ang) * 13
    c1, c2, c3, c4 = (a[0] + px, a[1] + py), (b[0] + px, b[1] + py), (b[0] - px, b[1] - py), (a[0] - px, a[1] - py)
    d.polygon([(x * S, y * S) for x, y in (c1, c2, c3, c4)], fill=paper)
    line([c1, c2]); line([c4, c3]); line([c2, c3])
    tip = (a[0] - _m.cos(ang) * 28, a[1] - _m.sin(ang) * 28)
    d.polygon([(x * S, y * S) for x, y in (c1, tip, c4)], fill=paper)
    line([c1, tip, c4])
    dot(tip[0] + _m.cos(ang) * 7, tip[1] + _m.sin(ang) * 7, 5)
    back = (b[0] - _m.cos(ang) * 22, b[1] - _m.sin(ang) * 22)
    line([(back[0] + px, back[1] + py), (back[0] - px, back[1] - py)], int(w * .65))
    # frambuesa grande en la esquina inferior derecha, sobre la tapa
    cx, cy, r = 270, 258, 13
    fill = (238, 218, 184, 255)              # mismo ocre de la burbuja
    # forma de frambuesa: más ancha arriba, termina en punta (drupas que se montan)
    rows = [(-30, (-24, 0, 24)), (-9, (-34, -11, 11, 34)), (12, (-24, 0, 24)), (33, (-34, -11, 11, 34)),
            (54, (-22, 0, 22)), (73, (-11, 11))]
    for dy, xs in rows:
        for dx in xs:
            x, y = cx + dx, cy + dy
            d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill, outline=ink, width=int(w * .72))
            d.arc([(x - r * .55) * S, (y - r * .55) * S, (x + r * .35) * S, (y + r * .35) * S], 190, 260,
                  fill=ink, width=int(w * .45))     # brillo de cada drupa
    # cáliz: hojitas sobre la frambuesa
    for ex, ey in ((-30, -62), (-12, -70), (12, -70), (30, -62)):   # cáliz en estrella
        d.polygon([((cx + ex * .25) * S, (cy - 40) * S), ((cx + ex) * S, (cy + ey + 12) * S),
                   ((cx + ex * .55) * S, (cy - 42) * S)], fill=fill, outline=ink)
        line([(cx + ex * .25, cy - 40), (cx + ex, cy + ey + 12), (cx + ex * .55, cy - 42)], int(w * .6))
    line([(cx, cy - 44), (cx + 6, cy - 72)], int(w * .7))
    # destellos
    for x, y, r in ((44, 36, 16), (316, 44, 13), (326, 168, 10), (40, 318, 12)):
        star(x, y, r)
    # start_notebook.png es ahora el ícono dibujado aparte (estilo de I+D y Predio): no se pisa.
    if not os.path.exists(os.path.join(UI, "start_notebook.png")):
        im.resize((360, 360), Image.LANCZOS).save(os.path.join(UI, "start_notebook.png"))
    blob(420, (238, 218, 184), 811).save(os.path.join(UI, "blob_notebook.png"))   # ocre claro


def main():
    background()
    blob(420, (250, 214, 228), 115).save(os.path.join(UI, "blob_id.png"))
    blob(420, (214, 236, 220), 297).save(os.path.join(UI, "blob_predio.png"))
    blob(440, (46, 52, 130), 7, stars=True).save(os.path.join(UI, "blob_ai.png"))
    ai = Image.open(os.path.join(UI, "start_ai.png")).convert("RGBA")
    tint(ai, (190, 228, 255)).save(os.path.join(UI, "start_ai_night.png"))
    glow = tint(ai, (120, 190, 255)).filter(ImageFilter.GaussianBlur(14))
    glow.putalpha(glow.split()[3].point(lambda v: min(255, int(v * 2.2))))
    glow.save(os.path.join(UI, "ai_glow.png"))
    bar_icons()
    notebook_icon()


if __name__ == "__main__":
    main()
