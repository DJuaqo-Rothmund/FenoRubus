"""
tools/make_aeon_assets.py
=========================
Imágenes de AeonCrop (la app Lab) a partir de los SVG de assets/src:

    node tools/render_svgs.js 900 /tmp/svg assets/src/*.svg
    python tools/make_aeon_assets.py /tmp/svg

* assets/ui/aeoncrop.png: logo de AeonCrop (pantalla principal).
* assets/ui/logo.png y assets/crops/<cultivo>/logo.png: logos de PhenoRubus, PhenoBlue y
  PhenoCran; fruit.png / fruit_gris.png: el fruto solo (vista previa).
* assets/ui/aeon_ia.png y aeon_iaplus.png: IA e IA+ (dibujo blanco teñido de celeste)
  sobre la burbuja azul con estrellas, centrada en el cerebro; aeon_ia_glow.png: su brillo neón.
* El ícono de la app en el teléfono (logo grande sobre fondo azul estelar, adaptativo) lo
  hace ahora tools/make_aeon_icon.py: no pase el segundo argumento aquí.
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "assets", "ui")
CROPS = os.path.join(ROOT, "assets", "crops")


def trim(im: Image.Image) -> Image.Image:
    return im.crop(im.getchannel("A").getbbox())


def square(im: Image.Image, n: int, pad: float = 0.0) -> Image.Image:
    """Centra en un cuadrado n×n (con margen relativo)."""
    im = trim(im)
    side = int(n * (1 - 2 * pad))
    k = side / max(im.size)
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.alpha_composite(im, ((n - im.width) // 2, (n - im.height) // 2))
    return out


def tint(im: Image.Image, rgb) -> Image.Image:
    out = Image.new("RGBA", im.size, rgb + (0,))
    out.putalpha(im.getchannel("A"))
    return out


def neon(im: Image.Image) -> Image.Image:
    near = tint(im, (90, 240, 255)).filter(ImageFilter.GaussianBlur(4))
    near.putalpha(near.getchannel("A").point(lambda v: min(255, int(v * 2.6))))
    far = tint(im, (40, 200, 255)).filter(ImageFilter.GaussianBlur(16))
    far.putalpha(far.getchannel("A").point(lambda v: min(255, int(v * 1.8))))
    far.alpha_composite(near)
    return far


def on_blob(art: Image.Image, n: int = 420, art_frac: float = .6) -> Image.Image:
    """Dibujo sobre la burbuja azul nocturna (assets/ui/blob_ai.png), centrado en el cerebro
    (el centro del dibujo); las letras pueden quedar un poco afuera."""
    blob = Image.open(os.path.join(UI, "blob_ai.png")).convert("RGBA").resize((n, n), Image.LANCZOS)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.alpha_composite(blob)
    a = square(art, int(n * art_frac))
    out.alpha_composite(a, ((n - a.width) // 2, (n - a.height) // 2))
    return out


def fruit_only(logo: Image.Image, crop: str) -> Image.Image:
    """El fruto del centro, sin el anillo de íconos: la mancha más grande del color de la
    fruta (azul o carmesí), con un margen."""
    import numpy as np
    from scipy import ndimage
    a = np.asarray(logo).astype(int)
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    mask = (al > 200) & ((b > r + 25) if crop == "arandano" else (r > g + 60))
    lab, n = ndimage.label(mask)
    big = 1 + int(np.argmax(ndimage.sum(mask, lab, range(1, n + 1))))
    ys, xs = np.nonzero(lab == big)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 * 1.08
    box = tuple(int(v) for v in (cx - half, cy - half, cx + half, cy + half))
    keep = ndimage.binary_fill_holes(ndimage.binary_dilation(lab == big, iterations=6))
    alpha = Image.fromarray((np.minimum(al, keep * 255)).astype("uint8"))
    out = logo.copy()
    out.putalpha(alpha)
    return out.crop(box).resize((300, 300), Image.LANCZOS)


def main(src: str):
    def load(name):
        return Image.open(os.path.join(src, name + ".png")).convert("RGBA")

    square(load("AeonCrop"), 600, .02).save(os.path.join(UI, "aeoncrop.png"))
    rub = square(load("PhenoRubus"), 384)
    rub.save(os.path.join(UI, "logo.png"))
    for crop, name in (("arandano", "PhenoBlue"), ("cranberry", "PhenoCran")):
        d = os.path.join(CROPS, crop)
        os.makedirs(d, exist_ok=True)
        logo = square(load(name), 384)
        logo.save(os.path.join(d, "logo.png"))
        fruit = fruit_only(logo, crop)
        fruit.save(os.path.join(d, "fruit.png"))
        gray = fruit.convert("LA").convert("RGBA")
        gray.putalpha(fruit.getchannel("A").point(lambda v: v * 6 // 10))
        gray.save(os.path.join(d, "fruit_gris.png"))
    ia = tint(load("IA"), (190, 228, 255))
    on_blob(ia).save(os.path.join(UI, "aeon_ia.png"))
    glow = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
    g = neon(square(ia, int(420 * .6)))
    glow.alpha_composite(g, ((420 - g.width) // 2, (420 - g.height) // 2))
    glow.save(os.path.join(UI, "aeon_ia_glow.png"))
    on_blob(tint(load("IAplus"), (150, 210, 255))).save(os.path.join(UI, "aeon_iaplus.png"))
    if len(sys.argv) > 2:      # ícono sin letras (tools/render_aeon_icon.js)
        icon = Image.new("RGBA", (512, 512), (242, 244, 238, 255))
        icon.alpha_composite(square(Image.open(sys.argv[2]).convert("RGBA"), 512, .10))
        icon.convert("RGB").save(os.path.join(ROOT, "assets", "icon_aeoncrop.png"))
    presplash()


def presplash(w=1080, h=2340, bg=(242, 244, 238)):
    """Pantalla de carga de Android = primer cuadro de la animación de AeonCrop, en el mismo
    lugar que LaunchScreen (ui/launch.kv): cuadro de min(62 % ancho, 34 % alto), centro al 55 %."""
    im = Image.new("RGB", (w, h), bg)
    f0 = Image.open(os.path.join(ROOT, "assets", "aeon_anim", "f000.png")).convert("RGBA")
    side = int(min(.62 * w, .34 * h))
    k = min(side / f0.width, side / f0.height)
    f0 = f0.resize((int(f0.width * k), int(f0.height * k)), Image.LANCZOS)
    cx, cy = w / 2, h * (1 - .55)
    im.paste(f0, (int(cx - f0.width / 2), int(cy - f0.height / 2)), f0)
    im.save(os.path.join(ROOT, "assets", "presplash.png"))


if __name__ == "__main__":
    main(sys.argv[1])
