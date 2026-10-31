"""
tools/make_crop_assets.py
=========================
Imágenes por cultivo y por estilo (ver crops.py y ui/theme.py):

* assets/crops/<cultivo>/logo.png, wordmark.png: logos simples de PhenoBlue y PhenoCran
  (fruto con reloj y anillo punteado, como el de PhenoRubus) y su nombre.
* assets/crops/<cultivo>/background.jpg, start_bg.jpg, blob_id.png: fondos pastel con el
  color de la fruta (los de frambuesa, con el rosado llevado al azul o al carmesí).
* assets/styles/<estilo>/background.jpg: fondos de los estilos Bosque, Lino y Noche.
* assets/ui/app_logo.png: los tres frutos juntos (pantalla de cultivos y de carga).

    python tools/make_crop_assets.py
"""
from __future__ import annotations

import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "assets", "ui")


def _font_path():
    import kivymd   # Roboto Black viene con KivyMD
    return os.path.join(os.path.dirname(kivymd.__file__), "fonts", "Roboto-Black.ttf")

# (claro, medio, oscuro) del fruto
FRUIT = {
    "arandano": ((122, 146, 214), (62, 86, 168), (33, 45, 102)),
    "cranberry": ((226, 92, 112), (170, 28, 52), (104, 14, 32)),
}
LEAF = (86, 150, 88)
SS = 4   # sobremuestreo (bordes suaves)


def _canvas(n):
    return Image.new("RGBA", (n * SS, n * SS), (0, 0, 0, 0))


def _down(im, n):
    return im.resize((n, n), Image.LANCZOS)


def _ring(d, n, color):
    """Anillo punteado alrededor del fruto (como el logo de PhenoRubus)."""
    cx = cy = n * SS / 2
    r = n * SS * .44
    for k in range(48):
        if k % 2:
            continue
        a0, a1 = k / 48 * 360, (k + 1) / 48 * 360
        d.arc((cx - r, cy - r, cx + r, cy + r), a0, a1, fill=color, width=int(SS * n * .012))


def _clock(d, cx, cy, r, ink):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255), outline=ink, width=int(r * .14))
    for k in range(4):
        a = k * math.pi / 2
        x, y = cx + math.cos(a) * r * .72, cy + math.sin(a) * r * .72
        d.ellipse((x - r * .07, y - r * .07, x + r * .07, y + r * .07), fill=ink)
    d.line((cx, cy, cx + r * .42, cy - r * .32), fill=ink, width=int(r * .13))
    d.line((cx, cy, cx - r * .28, cy - r * .5), fill=ink, width=int(r * .13))
    d.ellipse((cx - r * .1, cy - r * .1, cx + r * .1, cy + r * .1), fill=ink)


def _shade(im, light, dark, cx, cy, r):
    """Degradado radial del fruto: brillo arriba a la izquierda."""
    w, h = im.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.hypot(xx - (cx - r * .35), yy - (cy - r * .4)) / (r * 1.9)
    t = np.clip(dist, 0, 1)[..., None]
    col = np.array(light, np.float32) * (1 - t) + np.array(dark, np.float32) * t
    a = np.asarray(im)[..., 3:4]
    return Image.fromarray(np.concatenate([col, a.astype(np.float32)], -1).astype(np.uint8), "RGBA")


def blueberry_logo(n=384):
    light, mid, dark = FRUIT["arandano"]
    im = _canvas(n)
    d = ImageDraw.Draw(im)
    _ring(d, n, (176, 170, 160, 255))
    cx, cy, r = n * SS / 2, n * SS * .53, n * SS * .3
    body = _canvas(n)
    ImageDraw.Draw(body).ellipse((cx - r, cy - r, cx + r, cy + r * .96), fill=(255, 255, 255, 255))
    body = _shade(body, light, dark, cx, cy, r)
    im.alpha_composite(body)
    d = ImageDraw.Draw(im)
    d.ellipse((cx - r, cy - r, cx + r, cy + r * .96), outline=(24, 30, 70, 255), width=int(SS * n * .012))
    # corona (cáliz en estrella) arriba
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = r * (.3 if k % 2 == 0 else .13)
        pts.append((cx + math.cos(a) * rr, cy - r * .84 + math.sin(a) * rr * .55))
    d.polygon(pts, fill=(40, 52, 110, 255), outline=(20, 26, 60, 255))
    # hoja
    d.line((cx + r * .05, cy - r * .9, cx + r * .32, cy - r * 1.12), fill=(60, 100, 60, 255), width=int(SS * 5))
    d.ellipse((cx + r * .25, cy - r * 1.4, cx + r * .95, cy - r * .98), fill=LEAF + (255,),
              outline=(40, 90, 50, 255), width=int(SS * 3))
    # pruina (brillo blanquecino)
    glow = _canvas(n)
    ImageDraw.Draw(glow).ellipse((cx - r * .7, cy - r * .65, cx - r * .1, cy - r * .2),
                                 fill=(255, 255, 255, 90))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(SS * 6)))
    _clock(ImageDraw.Draw(im), cx + r * .12, cy + r * .1, r * .42, (40, 44, 60, 255))
    return _down(im, n)


def cranberry_logo(n=384):
    light, mid, dark = FRUIT["cranberry"]
    im = _canvas(n)
    d = ImageDraw.Draw(im)
    _ring(d, n, (176, 170, 160, 255))
    cx, cy = n * SS / 2, n * SS * .55
    rx, ry = n * SS * .26, n * SS * .3
    # tallo vertical («upright») con hojitas
    d.line((cx, cy - ry * .9, cx - rx * .15, cy - ry * 1.55), fill=(70, 110, 60, 255), width=int(SS * n * .02))
    for k, s in ((0, 1), (1, -1), (2, 1)):
        y = cy - ry * (1.1 + k * .16)
        x = cx - rx * .05 * k
        d.ellipse((x + (0 if s > 0 else -rx * .42), y - ry * .07, x + (rx * .42 if s > 0 else 0), y + ry * .07),
                  fill=LEAF + (255,))
    body = _canvas(n)
    ImageDraw.Draw(body).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(255, 255, 255, 255))
    body = _shade(body, light, dark, cx, cy, max(rx, ry))
    im.alpha_composite(body)
    d = ImageDraw.Draw(im)
    d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=(70, 10, 24, 255), width=int(SS * n * .012))
    shine = _canvas(n)
    ImageDraw.Draw(shine).ellipse((cx - rx * .65, cy - ry * .7, cx - rx * .15, cy - ry * .25),
                                  fill=(255, 255, 255, 120))
    im.alpha_composite(shine.filter(ImageFilter.GaussianBlur(SS * 5)))
    _clock(ImageDraw.Draw(im), cx + rx * .1, cy + ry * .12, rx * .5, (60, 30, 36, 255))
    return _down(im, n)


def wordmark(name, top, bottom, w=700, h=248):
    """«PhenoBlue / App» en letra gruesa con degradado y contorno, como el de PhenoRubus."""
    im = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    font = ImageFont.truetype(_font_path(), 230)
    small = ImageFont.truetype(_font_path(), 190)
    for text, f, y in ((name, font, -10), ("App", small, 255)):
        tw = f.getbbox(text)[2]
        x = (w * 2 - tw) // 2
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).text((x, y), text, font=f, fill=255)
        edge = mask.filter(ImageFilter.MaxFilter(11))
        outline = Image.new("RGBA", im.size, (40, 40, 48, 255))
        im.paste(outline, (0, 0), edge)
        grad = np.zeros((im.size[1], im.size[0], 4), np.uint8)
        t = np.linspace(0, 1, im.size[1])[:, None]
        for i in range(3):
            grad[..., i] = (top[i] * (1 - t) + bottom[i] * t).astype(np.uint8)
        grad[..., 3] = 255
        im.paste(Image.fromarray(grad, "RGBA"), (0, 0), mask)
        shine = mask.filter(ImageFilter.MinFilter(9)).point(lambda v: v * 55 // 255)
        hl = Image.new("RGBA", im.size, (255, 255, 255, 0))
        hl.putalpha(shine)
        top_half = Image.new("L", im.size, 0)
        ImageDraw.Draw(top_half).rectangle((0, 0, im.size[0], y + f.size * .55), fill=255)
        hl.putalpha(Image.fromarray(np.minimum(np.asarray(shine), np.asarray(top_half))))
        im.alpha_composite(hl)
    return im.resize((w, h), Image.LANCZOS)


def hue_shift(path, out, target_h, sat=1.0, val=1.0):
    """Lleva los rosados/rojos de frambuesa al tono del fruto (H en 0-255 de PIL), con un
    peso suave según cuán rosado es cada píxel (sin bordes marcados)."""
    im = Image.open(path)
    alpha = im.getchannel("A") if im.mode == "RGBA" else None
    rgb0 = im.convert("RGB")
    hsv = np.asarray(rgb0.convert("HSV")).astype(np.float32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    dist = np.minimum(np.abs(h - 240), 256 - np.abs(h - 240))        # 240 ≈ rosado frambuesa
    w = np.clip(1 - (dist - 22) / 30, 0, 1) * np.clip(s / 40, 0, 1)
    shifted = np.stack([np.full_like(h, target_h), np.clip(s * sat, 0, 255), np.clip(v * val, 0, 255)], -1)
    new = np.asarray(Image.fromarray(shifted.astype(np.uint8), "HSV").convert("RGB")).astype(np.float32)
    arr = np.asarray(rgb0).astype(np.float32)
    w = np.asarray(Image.fromarray((w * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))) / 255.0
    rgb = Image.fromarray((arr * (1 - w[..., None]) + new * w[..., None]).astype(np.uint8), "RGB")
    if alpha is not None:
        rgb = rgb.convert("RGBA")
        rgb.putalpha(alpha)
        rgb.save(out)
    else:
        rgb.save(out, quality=90)


def plain_start_bg(out, top, mid, bottom, w=824, h=1720):
    """Fondo del inicio sin el dibujo de la planta de frambueso (otros cultivos)."""
    y = np.linspace(0, 1, h)[:, None]
    col = np.where(y < .5, (1 - y * 2) * np.array(top)[None] + (y * 2) * np.array(mid)[None],
                   (2 - y * 2) * np.array(mid)[None] + (y * 2 - 1) * np.array(bottom)[None])
    arr = np.repeat(col[:, None, :], w, axis=1).astype(np.uint8)
    Image.fromarray(arr, "RGB").save(out, quality=90)


def style_bg(out, stops, w=720, h=1280, stars=False, grain=0):
    y = np.linspace(0, 1, h)[:, None, None]
    x = np.linspace(0, 1, w)[None, :, None]
    t = np.clip(y * .8 + x * .2, 0, 1)
    a, b = np.array(stops[0], np.float32), np.array(stops[1], np.float32)
    arr = a * (1 - t) + b * t
    if grain:
        rng = np.random.default_rng(7)
        arr = arr + rng.normal(0, grain, arr.shape[:2])[..., None]
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    if stars:
        d = ImageDraw.Draw(im)
        rnd = random.Random(11)
        for _ in range(140):
            px, py, r = rnd.uniform(0, w), rnd.uniform(0, h), rnd.choice((0.6, 0.8, 1.0, 1.4))
            c = rnd.randint(120, 220)
            d.ellipse((px - r, py - r, px + r, py + r), fill=(c, c, min(255, c + 25)))
    im.save(out, quality=90)


def app_logo(n=420):
    """Los tres frutos juntos: pantalla de cultivos y de carga."""
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    rub = Image.open(os.path.join(UI, "logo.png")).convert("RGBA").resize((int(n * .55),) * 2, Image.LANCZOS)
    blue = blueberry_logo(int(n * .55))
    cran = cranberry_logo(int(n * .55))
    im.alpha_composite(blue, (0, int(n * .38)))
    im.alpha_composite(cran, (int(n * .45), int(n * .38)))
    im.alpha_composite(rub, (int(n * .225), 0))
    return im


def presplash(w=1080, h=2340, bg=(242, 244, 238)):
    """Pantalla de carga de Android al abrir la app: los tres frutos y «App Fenología»,
    igual que LaunchScreen (ui/layout.kv): logo al 56 % de alto, nombre al 36 %."""
    im = Image.new("RGB", (w, h), bg)
    side = int(min(.6 * w, .3 * h))
    logo = app_logo(side)
    im.paste(logo, ((w - side) // 2, int(h * (1 - .56) - side / 2)), logo)
    font = ImageFont.truetype(_font_path().replace("Black", "Bold"), 63)
    text = "App Fenología"
    tw = font.getbbox(text)[2]
    ImageDraw.Draw(im).text(((w - tw) // 2, int(h * (1 - .36)) - 38), text, font=font, fill=(30, 74, 58))
    return im


def main():
    for crop, logo, top, bottom in (("arandano", blueberry_logo, (96, 120, 200), (40, 54, 120)),
                                    ("cranberry", cranberry_logo, (214, 70, 92), (110, 16, 36))):
        d = os.path.join(ROOT, "assets", "crops", crop)
        os.makedirs(d, exist_ok=True)
        logo().save(os.path.join(d, "logo.png"))
        fruit = logo(384)
        fruit = fruit.crop((40, 40, 344, 344))       # el fruto sin el anillo (vista previa)
        fruit.save(os.path.join(d, "fruit.png"))
        gray = fruit.convert("LA").convert("RGBA")
        gray.putalpha(fruit.getchannel("A").point(lambda v: v * 6 // 10))
        gray.save(os.path.join(d, "fruit_gris.png"))
        wordmark({"arandano": "PhenoBlue", "cranberry": "PhenoCran"}[crop], top, bottom).save(
            os.path.join(d, "wordmark.png"))
    blue_h, cran_h = 160, 246          # tonos de PIL (0-255): azul arándano, carmesí
    d = os.path.join(ROOT, "assets", "crops")
    hue_shift(os.path.join(UI, "background.jpg"), os.path.join(d, "arandano", "background.jpg"), blue_h, .85)
    hue_shift(os.path.join(UI, "background.jpg"), os.path.join(d, "cranberry", "background.jpg"), cran_h, 1.1, .92)
    hue_shift(os.path.join(UI, "blob_id.png"), os.path.join(d, "arandano", "blob_id.png"), blue_h, .8)
    hue_shift(os.path.join(UI, "blob_id.png"), os.path.join(d, "cranberry", "blob_id.png"), cran_h, 1.1, .95)
    plain_start_bg(os.path.join(d, "arandano", "start_bg.jpg"), (222, 239, 214), (247, 247, 244), (218, 226, 246))
    plain_start_bg(os.path.join(d, "cranberry", "start_bg.jpg"), (222, 239, 214), (250, 245, 240), (246, 214, 220))
    s = os.path.join(ROOT, "assets", "styles")
    for name in ("bosque", "lino", "noche"):
        os.makedirs(os.path.join(s, name), exist_ok=True)
    style_bg(os.path.join(s, "bosque", "background.jpg"), ((26, 58, 48), (17, 40, 33)))
    style_bg(os.path.join(s, "lino", "background.jpg"), ((248, 244, 235), (239, 232, 218)), grain=2.2)
    style_bg(os.path.join(s, "noche", "background.jpg"), ((20, 22, 42), (38, 24, 52)), stars=True)
    app_logo().save(os.path.join(UI, "app_logo.png"))
    presplash().save(os.path.join(ROOT, "assets", "presplash.png"))


if __name__ == "__main__":
    main()
