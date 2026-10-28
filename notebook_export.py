"""
notebook_export.py
==================
Páginas del cuaderno de campo como PDF en Drive, en una carpeta exclusiva:

    PhenoRubus · Imágenes de Fenología/Cuaderno de campo/
        20261026-NV-cuaderno.pdf          ← la página (texto, escritura a mano y fotos)
        20261026-NV-cuaderno.jpg, …-a1.jpg ← sus fotos

El nombre parte con la fecha (mismo formato que las fotos) y lleva el código del ensayo o
predio. Al volver a editar la página, el PDF se reemplaza (mismo nombre). Se exportan solo
las páginas que cambiaron desde la última vez (firma guardada en el equipo).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os

import phenology as ph

FOLDER = "Cuaderno de campo"
DPI = 150
W, H = 1240, 1754                 # A4 a 150 ppp
M = 96                            # margen
STEP = 46                         # alto de renglón (px)
WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def page_name(code: str, day: str) -> str:
    return f"{ph.photo_date(day)}-{code}-cuaderno.pdf" if code else f"{ph.photo_date(day)}-cuaderno.pdf"


def photo_remote(path: str) -> str:
    """Carpeta de Drive de las fotos del cuaderno (la misma de las páginas)."""
    return f"{FOLDER}/{os.path.basename(path)}"


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = ["Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf"]
    dirs = []
    try:
        import kivymd
        dirs.append(os.path.join(os.path.dirname(kivymd.__file__), "fonts"))
    except Exception:  # noqa: BLE001
        pass
    dirs.append("/usr/share/fonts/truetype/dejavu")
    names.append("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow antiguo
        return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines = []
    for para in (text or "").split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            test = f"{cur} {w}".strip()
            if draw.textlength(test, font=font) <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _hex(col: str):
    col = (col or "#1E3A8A").lstrip("#")
    return tuple(int(col[i:i + 2], 16) for i in (0, 2, 4))


def _stroke(d, s: dict, top: int, col) -> None:
    p = s.get("p") or []
    pts = [(M + p[i] * STEP, top + p[i + 1] * STEP) for i in range(0, len(p) - 1, 2)]
    w = max(2, int(round(s.get("w", .06) * STEP * 2)))
    if len(pts) > 1:
        d.line(pts, fill=col, width=w, joint="curve")
    if s.get("k") == "hl":
        return                    # punta cuadrada
    for x, y in (pts[:1] + pts[-1:]):
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=col)


def signature(entry: dict) -> str:
    raw = json.dumps([entry.get("day"), entry.get("text"), entry.get("ink"),
                      [p["path"] for p in entry.get("photos", [])]], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def render(entry: dict, ws_name: str, code: str, dest: str) -> str:
    """Dibuja la página (una o más hojas A4) y la guarda como PDF en `dest`."""
    from PIL import Image, ImageDraw, ImageOps
    pages = []

    def new_page():
        im = Image.new("RGB", (W, H), (255, 255, 255))
        pages.append(im)
        return im, ImageDraw.Draw(im)

    im, d = new_page()
    day = _dt.date.fromisoformat(entry["day"][:10])
    title = f"{WEEKDAYS[day.weekday()]} {day.day} de {ph.MESES[day.month - 1]} de {day.year}"
    d.text((M, M - 30), "CUADERNO DE CAMPO", font=_font(22, True), fill=(200, 150, 62))
    d.text((M, M), title, font=_font(44, True), fill=(107, 68, 35))
    d.text((M, M + 58), f"{ws_name} ({code})" if code else ws_name, font=_font(26), fill=(110, 126, 117))
    top = M + 120                                  # primer renglón del texto
    font = _font(28)
    lines = _wrap(d, entry.get("text") or "", font, W - 2 * M)
    strokes = []
    try:
        strokes = json.loads(entry.get("ink") or "[]")
    except ValueError:
        pass
    ink_bottom = max([max(s["p"][1::2]) for s in strokes if s.get("p")] + [0])
    n_rows = max(len(lines), int(ink_bottom) + 1, 6)
    bottom = min(H - M, top + n_rows * STEP)
    for i in range(int((bottom - top) / STEP) + 1):       # renglones
        y = top + (i + 1) * STEP - 6
        if y < H - M:
            d.line([(M, y), (W - M, y)], fill=(234, 222, 200), width=2)
    for i, ln in enumerate(lines):
        y = top + i * STEP + 8
        if y + STEP > H - M:
            break
        d.text((M, y), ln, font=font, fill=(27, 42, 35))
    # Escritura a mano (en renglones): el destacador, translúcido y debajo de la tinta.
    hl = [s for s in strokes if s.get("k") == "hl"]
    if hl:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for s in hl:
            _stroke(ld, s, top, (*_hex(s.get("c")), 255))
        alpha = layer.getchannel("A").point(lambda v: int(v * .35))
        layer.putalpha(alpha)
        im.paste(layer, (0, 0), layer)
        d = ImageDraw.Draw(im)
    for s in strokes:
        if s.get("k") != "hl":
            _stroke(d, s, top, _hex(s.get("c")))
    # Fotos de la página, dos por fila (siguen en otra hoja si no caben).
    y = bottom + 30
    col_w = (W - 2 * M - 30) // 2
    x_i = 0
    row_h = 0
    for ph_ in entry.get("photos", []):
        path = ph_.get("path")
        if not path or not os.path.exists(path):
            continue
        try:
            with Image.open(path) as src:
                pic = ImageOps.exif_transpose(src).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        k = col_w / pic.width
        pic = pic.resize((col_w, max(1, int(pic.height * k))), Image.BILINEAR)
        if pic.height > H - 2 * M:
            pic = pic.crop((0, 0, pic.width, H - 2 * M))
        if y + pic.height > H - M:
            im, d = new_page()
            y, x_i, row_h = M, 0, 0
        x = M + x_i * (col_w + 30)
        im.paste(pic, (x, y))
        row_h = max(row_h, pic.height)
        x_i += 1
        if x_i == 2:
            x_i, y, row_h = 0, y + row_h + 30, 0
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    pages[0].save(dest, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    return dest


def export_pending(db, drive, out_dir: str) -> int:
    """Genera y sube a Drive las páginas del cuaderno de `db` que cambiaron. Devuelve cuántas."""
    ws = getattr(db, "workspace", None) or {}
    code = ws.get("code") or getattr(db, "code", "") or ""
    done = db.get_setting("notebook_exported") or {}
    n = 0
    for entry in db.note_days():
        sig = signature(entry)
        if done.get(entry["day"]) == sig:
            continue
        if not (entry.get("text") or "").strip() and not entry["photos"] and not (entry.get("ink") or "").strip("[] "):
            continue                       # página vacía: nada que guardar
        name = page_name(code, entry["day"])
        path = render(entry, ws.get("name") or code, code, os.path.join(out_dir, name))
        drive.put_file(path, f"{FOLDER}/{name}")
        done[entry["day"]] = sig
        db.set_setting("notebook_exported", done)
        n += 1
    return n
