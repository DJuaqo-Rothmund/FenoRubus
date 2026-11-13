"""
photo_cache.py
==============
Fotos reducidas para los informes, guardadas en disco y reutilizadas.

Una foto del teléfono (12 MP, 3-5 MB) tarda ~0,3-0,6 s en abrirse y reducirse. Un informe
semanal con 30 fotos lo hacía cada vez, y el ZIP de todas las semanas, para cada semana.
Aquí la versión reducida queda en caché (clave: ruta + fecha de modificación + tamaño +
calidad), así que generar de nuevo un informe —o la semana siguiente con las mismas
fotos de referencia— no vuelve a decodificar la original.

    data, w, h = photo_cache.reduced(path, 960, quality=78)

Sin carpeta configurada (p. ej. la web) reduce sin guardar. Puro Python + PIL.
"""
from __future__ import annotations

import hashlib
import io
import os
import threading

MAX_BYTES = 150 * 1024 * 1024       # tope de la caché; al pasarlo se borran las más viejas

_dir: str | None = None
_lock = threading.Lock()
_pruned = False


def set_dir(path: str | None) -> None:
    global _dir, _pruned
    if path:
        os.makedirs(path, exist_ok=True)
    _dir, _pruned = path, False


def _encode(src, max_side: int, quality: int, progressive: bool):
    from PIL import Image, ImageOps
    img = Image.open(src if isinstance(src, str) else io.BytesIO(src))
    img.draft("RGB", (max_side, max_side))          # decodificación JPEG reducida
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=progressive)
    return buf.getvalue(), img.width, img.height


def _key(path: str, max_side: int, quality: int, progressive: bool) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    raw = f"{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}|{max_side}|{quality}|{int(progressive)}"
    return hashlib.md5(raw.encode()).hexdigest()


def add(name: str) -> None:
    try:
        import perf
        perf.add(name)
    except Exception:  # noqa: BLE001 - en la web perf puede no estar
        pass


def reduced(src, max_side: int, quality: int = 78, progressive: bool = False) -> tuple[bytes, int, int]:
    """(JPEG reducido, ancho, alto). src: ruta o bytes. Lanza si la foto no se puede leer."""
    key = _key(src, max_side, quality, progressive) if isinstance(src, str) and _dir else None
    if key:
        dest = os.path.join(_dir, key[:2], key + ".jpg")
        try:
            with open(dest, "rb") as f:
                data = f.read()
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:      # solo lee la cabecera
                w, h = im.size
            add("informes.fotos desde caché")
            return data, w, h
        except (OSError, ValueError):
            pass
    data, w, h = _encode(src, max_side, quality, progressive)
    add("informes.fotos reducidas")
    if key:
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = f"{dest}.{threading.get_ident()}.part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            _maybe_prune()
        except OSError:
            pass
    return data, w, h


def _maybe_prune() -> None:
    """Una vez por apertura: si la caché pasa el tope, borra las menos usadas recientemente."""
    global _pruned
    with _lock:
        if _pruned or not _dir:
            return
        _pruned = True
    files, total = [], 0
    for root, _dirs, names in os.walk(_dir):
        for n in names:
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
    if total <= MAX_BYTES:
        return
    for _m, size, p in sorted(files):
        try:
            os.remove(p)
            total -= size
        except OSError:
            pass
        if total <= MAX_BYTES * 0.7:
            break
