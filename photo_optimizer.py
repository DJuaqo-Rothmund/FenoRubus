"""
photo_optimizer.py
==================
Aligera las fotos ya guardadas en el teléfono (versiones anteriores las guardaban en JPEG
calidad 88, o sin reducir): lado mayor ≤ 1600 px y JPEG calidad 78, como las nuevas.

* Cada foto se reescribe en el MISMO archivo (primero en un temporal que se verifica y
  luego reemplaza al original): las rutas guardadas en SQLite no cambian.
* Se conserva la fecha del archivo, así las miniaturas en caché siguen valiendo.
* Solo toca JPEG de la app (fotos de registro, adjuntas, mediciones e IA); no vuelve a
  subir nada a Drive (allí queda la copia que ya estaba).
"""
from __future__ import annotations

import os
from typing import Callable, Iterable

from PIL import Image, ImageOps

MAX_SIDE = 1600
QUALITY = 78
HEAVY_KB = 450            # por debajo de esto (y ≤ 1600 px) la foto ya está liviana
_EXT = (".jpg", ".jpeg")

_QUERIES = (
    "SELECT path FROM photos",
    "SELECT path FROM variety_attachments",
    "SELECT path FROM measure_entries WHERE path IS NOT NULL",
    "SELECT image_path AS path FROM ai_references WHERE image_path IS NOT NULL",
)


def save_jpeg(img: Image.Image, dest: str, quality: int = QUALITY) -> None:
    """JPEG liviano: calidad ~78, tablas Huffman optimizadas y progresivo (carga suave)."""
    img.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)


def photo_paths(dbs: Iterable) -> list[str]:
    """Rutas de imagen (sin repetir) de todas las bases: ensayos, predios y la común."""
    seen: dict[str, None] = {}
    for db in dbs:
        for sql in _QUERIES:
            try:
                rows = db.query(sql)
            except Exception:  # noqa: BLE001 (tabla ausente en la base común, etc.)
                continue
            for r in rows:
                p = r.get("path")
                if p and p.lower().endswith(_EXT):
                    seen.setdefault(p, None)
    return list(seen)


def is_heavy(path: str) -> bool:
    """Más de 1600 px, o pesada y aún no pasada por save_jpeg (que la deja progresiva)."""
    try:
        with Image.open(path) as im:
            if max(im.size) > MAX_SIDE:
                return True
            done = bool(im.info.get("progressive") or im.info.get("progression"))
        return not done and os.path.getsize(path) > HEAVY_KB * 1024
    except (OSError, ValueError):
        return False


def scan(dbs: Iterable) -> dict:
    """{"paths": fotos pesadas, "bytes": lo que pesan, "total": fotos revisadas}."""
    paths = [p for p in photo_paths(dbs) if os.path.exists(p)]
    heavy = [p for p in paths if is_heavy(p)]
    return {"paths": heavy, "bytes": sum(os.path.getsize(p) for p in heavy), "total": len(paths)}


def optimize_file(path: str) -> int:
    """Reescribe la foto liviana en el mismo lugar; devuelve los bytes ahorrados (0 si
    no convenía o no se pudo: el original queda intacto)."""
    try:
        before = os.path.getsize(path)
        stat = os.stat(path)
        img = Image.open(path)
        w, h = img.size
        scale = MAX_SIDE / max(w, h)
        if scale < 1:
            img.draft("RGB", (int(w * scale), int(h * scale)))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        tmp = path + ".opt.tmp"
        save_jpeg(img, tmp)
        with Image.open(tmp) as check:          # el temporal se abre bien
            check.verify()
        after = os.path.getsize(tmp)
        if after >= before * .95:                # casi no ahorra: se deja como estaba
            os.remove(tmp)
            return 0
        os.replace(tmp, path)
        os.utime(path, (stat.st_atime, stat.st_mtime))
        return before - after
    except Exception:  # noqa: BLE001
        try:
            os.remove(path + ".opt.tmp")
        except OSError:
            pass
        return 0


def optimize(paths: list[str], progress: Callable[[int, int, int], None] | None = None) -> dict:
    """Optimiza `paths`; progress(hechas, total, bytes_ahorrados) tras cada foto."""
    saved = done = 0
    for i, p in enumerate(paths, 1):
        s = optimize_file(p)
        saved += s
        done += s > 0
        if progress:
            progress(i, len(paths), saved)
    return {"optimized": done, "saved": saved, "total": len(paths)}
