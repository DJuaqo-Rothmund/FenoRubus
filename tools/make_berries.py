"""
tools/make_berries.py
=====================
Recorta las frambuesas ilustradas (una lámina 3×3 con su nombre debajo) y genera
PNG con fondo transparente para la vista previa: color y gris (semana sin registro).

    python tools/make_berries.py lamina.jpg

Orden de la lámina (filas de arriba a abajo, de izquierda a derecha).
"""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

NAMES = ["codigo_55", "meeker", "codigo_31",
         "codigo_81", "wakefield", "codigo_24",
         "lagorai", "cascade_harvest", "codigo_11"]
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "ui", "berries")
SIDE = 240   # alto máximo de cada PNG


def main(src):
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # Fruto: rojo dominante (el papel es crema y las hojas verdes).
    mask = (r - g > 45) & (r - b > 25)
    mask = ndimage.binary_closing(mask, iterations=4)
    mask = ndimage.binary_fill_holes(mask)
    mask = ndimage.binary_opening(mask, iterations=2)
    lab, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = [i + 1 for i in np.argsort(sizes)[::-1][:9]]
    boxes = []
    for k in keep:
        ys, xs = np.where(lab == k)
        boxes.append((ys.min(), xs.min(), ys.max(), xs.max(), k))
    # Ordenar por filas (y) y luego columnas (x).
    boxes.sort(key=lambda t: t[0])
    rows = [sorted(boxes[i:i + 3], key=lambda t: t[1]) for i in range(0, 9, 3)]
    os.makedirs(OUT, exist_ok=True)
    for name, (y0, x0, y1, x1, k) in zip(NAMES, [b for row in rows for b in row]):
        pad = 6
        y0, x0 = max(0, y0 - pad), max(0, x0 - pad)
        y1, x1 = min(a.shape[0], y1 + pad), min(a.shape[1], x1 + pad)
        crop = im.crop((x0, y0, x1, y1))
        m = Image.fromarray(((lab[y0:y1, x0:x1] == k) * 255).astype("uint8"))
        m = m.filter(ImageFilter.GaussianBlur(1.2))       # borde suave
        rgba = crop.copy()
        rgba.putalpha(m)
        scale = SIDE / max(rgba.size)
        rgba = rgba.resize((max(1, int(rgba.width * scale)), max(1, int(rgba.height * scale))),
                           Image.LANCZOS)
        rgba.save(os.path.join(OUT, f"{name}.png"), optimize=True)
        gray = rgba.convert("LA").convert("RGBA")
        # gris claro y lavado (semana sin registro)
        g_arr = np.asarray(gray).astype(float)
        g_arr[..., :3] = 150 + g_arr[..., :3] * .38
        Image.fromarray(g_arr.astype("uint8")).save(os.path.join(OUT, f"{name}_gris.png"), optimize=True)
        print(name, rgba.size)


if __name__ == "__main__":
    main(sys.argv[1])
