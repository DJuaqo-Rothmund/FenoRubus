"""
tools/make_module_icons.py
==========================
Íconos de AeonCrop dibujados por el usuario (SVG en assets/src) -> PNG de la app:

    T=/tmp/svgpng; mkdir -p $T
    node tools/render_svgs.js 900 $T assets/src/{AeonCrop,Lab_ID,Cuaderno,Camara,IA_color}.svg \\
        assets/src/Campo_{Frambuesas,Arandanos,Cran}.svg
    node tools/render_ia_brain.js $T/IA_brain.png
    python tools/make_module_icons.py $T
    node tools/aeon_anim.js assets/aeon_anim          # animación de apertura (logo nuevo)
    node tools/render_aeon_icon.js $T/marca.png && python tools/make_aeon_icon.py $T/marca.png

* assets/ui/aeoncrop.png ............ logo de la pantalla principal (AeonCrop.svg).
* assets/ui/aeon_ia.png / aeon_iaplus.png: Entrenador IA (cerebro sin letras) e IA+ (dibujo
  completo), sobre un disco claro (el dibujo tiene líneas azul marino: se ven en todo estilo);
  aeon_ia_glow.png: su brillo.
* assets/ui/start_id.png ............ I+D (Lab_ID.svg, línea negra).
* assets/ui/start_notebook.png ...... Cuaderno de campo (Cuaderno.svg); *_light.png: la misma
  línea en claro para cuando va directo sobre un fondo oscuro.
* assets/ui/start_predio.png (frambuesa) y assets/crops/<cultivo>/start_predio.png: Predio.
* assets/ui/nav_sampling_active.png / _idle.png: pestaña Muestreo (Camara.svg; inactiva en gris).
* assets/ui/camera_art.png .......... botón redondo «Cámara».
* assets/presplash.png .............. pantalla de carga de Android (primer cuadro de la animación).
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_aeon_assets import CROPS, ROOT, UI, square, presplash   # noqa: E402


def light_lines(im: Image.Image, rgb=(240, 242, 236)) -> Image.Image:
    """Las líneas negras pasan a claras (para fondos oscuros); el color se conserva."""
    px = im.copy()
    data = px.load()
    for y in range(px.height):
        for x in range(px.width):
            r, g, b, a = data[x, y]
            if a and r + g + b < 160:
                data[x, y] = rgb + (a,)
    return px


def on_disc(art: Image.Image, n: int = 420, art_frac: float = .74) -> Image.Image:
    """Dibujo sobre un disco claro con borde suave."""
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    sh = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    m = int(n * .04)
    d.ellipse((m, m + 4, n - m, n - m + 4), fill=(0, 0, 0, 70))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(out)
    d.ellipse((m, m, n - m, n - m), fill=(252, 253, 250, 255), outline=(200, 214, 205, 255), width=3)
    a = square(art, int(n * art_frac))
    out.alpha_composite(a, ((n - a.width) // 2, (n - a.height) // 2))
    return out


def glow_of(art: Image.Image, n: int = 420) -> Image.Image:
    sil = square(art, int(n * .86))
    halo = Image.new("RGBA", sil.size, (80, 220, 255, 0))
    halo.putalpha(sil.getchannel("A").point(lambda v: 255 if v > 10 else 0))
    halo = halo.filter(ImageFilter.GaussianBlur(18))
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.alpha_composite(halo, ((n - halo.width) // 2, (n - halo.height) // 2))
    return out


def idle(im: Image.Image) -> Image.Image:
    """Versión apagada (pestaña inactiva): gris verdoso, algo transparente."""
    g = im.convert("LA").convert("RGBA")
    tint = Image.new("RGBA", g.size, (60, 90, 78, 0))
    out = Image.blend(g, tint, .35)
    out.putalpha(im.getchannel("A").point(lambda v: int(v * .85)))
    return out


def main(src: str):
    def load(name):
        return Image.open(os.path.join(src, name + ".png")).convert("RGBA")

    square(load("AeonCrop"), 600, .02).save(os.path.join(UI, "aeoncrop.png"))
    brain, full = load("IA_brain"), load("IA_color")
    on_disc(brain).save(os.path.join(UI, "aeon_ia.png"))
    on_disc(full).save(os.path.join(UI, "aeon_iaplus.png"))
    glow_of(brain).save(os.path.join(UI, "aeon_ia_glow.png"))
    lab = square(load("Lab_ID"), 360, .03)
    lab.save(os.path.join(UI, "start_id.png"))
    nb = square(load("Cuaderno"), 360, .03)
    nb.save(os.path.join(UI, "start_notebook.png"))
    light_lines(nb).save(os.path.join(UI, "start_notebook_light.png"))
    for crop, name in (("frambuesa", "Campo_Frambuesas"), ("arandano", "Campo_Arandanos"),
                       ("cranberry", "Campo_Cran")):
        im = square(load(name), 360, .03)
        d = UI if crop == "frambuesa" else os.path.join(CROPS, crop)
        os.makedirs(d, exist_ok=True)
        im.save(os.path.join(d, "start_predio.png"))
    cam = square(load("Camara"), 192, .02)
    cam.save(os.path.join(UI, "nav_sampling_active.png"))
    idle(cam).save(os.path.join(UI, "nav_sampling_idle.png"))
    square(load("Camara"), 256, .02).save(os.path.join(UI, "camera_art.png"))
    presplash()
    print("listo:", ROOT)


if __name__ == "__main__":
    main(sys.argv[1])
