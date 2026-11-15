"""
tools/icon_from_drawing.py
==========================
Un dibujo sobre fondo blanco (JPG/PNG del usuario) -> ícono PNG cuadrado con fondo
transparente. Solo se quita el blanco de AFUERA (relleno desde los bordes): lo blanco por
dentro del dibujo (el cuerpo de la balanza, del contador) se conserva.

    python tools/icon_from_drawing.py assets/src/Contador.jpg assets/ui/measures_counter.png 360
    python tools/icon_from_drawing.py assets/src/Rendimiento_flow.jpg assets/ui/start_yield.png 360
"""
from __future__ import annotations

import sys

from PIL import Image, ImageDraw, ImageFilter


def convert(src: str, dest: str, side: int = 360, pad: float = .02) -> None:
    im = Image.open(src).convert("RGB")
    g = im.convert("L")
    bbox = g.point(lambda v: 255 if v < 235 else 0).getbbox()
    im, g = im.crop(bbox), g.crop(bbox)
    # Exterior: lo claro conectado con el borde (con un margen blanco alrededor para el relleno).
    m = Image.new("L", (g.width + 4, g.height + 4), 255)
    m.paste(g.point(lambda v: 255 if v > 232 else 0), (2, 2))
    ImageDraw.floodfill(m, (0, 0), 128)
    outside = m.crop((2, 2, g.width + 2, g.height + 2)).point(lambda v: 255 if v == 128 else 0)
    # Borde suave: el antialias de la línea contra el exterior se vuelve transparencia.
    soft = g.point(lambda v: max(0, min(255, int((250 - v) * 255 / 60))))
    alpha = Image.composite(soft, Image.new("L", g.size, 255), outside.filter(ImageFilter.MaxFilter(3)))
    rgba = im.convert("RGBA")
    rgba.putalpha(alpha)
    n = int(max(rgba.size) * (1 + 2 * pad))
    sq = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    sq.alpha_composite(rgba, ((n - rgba.width) // 2, (n - rgba.height) // 2))
    sq.resize((side, side), Image.LANCZOS).save(dest)


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 360)
