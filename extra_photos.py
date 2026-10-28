"""
extra_photos.py
===============
Fotos extra para entrenar IA+: fotos que no son de ningún ensayo ni predio (de otros
años, de otros lugares…), en una carpeta propia de Drive:

    PhenoRubus · Imágenes de Fenología/IA+ Conocimiento ampliado/
        20261028-153012-extra.jpg          ← sacadas o elegidas en el teléfono
        2024/Regina/IMG_1234.jpg           ← subidas desde la web (con sus subcarpetas)

La app solo ve los archivos que ella misma (o la web de PhenoRubus) subió: así funciona el
permiso de Drive que usa (drive.file). Por eso las fotos de afuera se suben desde la web
(«Entrenar IA» › «Subir fotos extra»), que respeta las subcarpetas.

En el teléfono no se guardan las fotos completas: la lista usa las miniaturas de Drive y la
foto se baja solo al abrirla para marcarla; una vez marcada se borra del teléfono (sigue en
Drive y sus cajas en marcas.json).

Cada foto se identifica por «ext/<subcarpetas>/<nombre>» (la clave en marcas.json).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import urllib.parse

from platform_utils import data_subdir

FOLDER = "IA+ Conocimiento ampliado"
PREFIX = "ext/"
FIELDS = "nextPageToken, files(id, name, mimeType, thumbnailLink, imageMediaMetadata(width, height), createdTime)"
FOLDER_MIME = "application/vnd.google-apps.folder"


def key_for(rel: str) -> str:
    return PREFIX + rel


def is_extra(name: str) -> bool:
    return (name or "").startswith(PREFIX)


def _dir(*parts) -> str:
    return data_subdir("extra", *parts)


def index_path() -> str:
    return os.path.join(_dir(), "index.json")


def load_index() -> list[dict]:
    """Última lista conocida de la carpeta de Drive (para abrir al instante y sin red)."""
    try:
        with open(index_path(), encoding="utf-8") as f:
            return json.load(f).get("photos", [])
    except (OSError, ValueError):
        return []


def save_index(photos: list[dict]) -> None:
    tmp = index_path() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"when": _dt.datetime.now().isoformat(timespec="seconds"), "photos": photos}, f,
                  ensure_ascii=False)
    os.replace(tmp, index_path())


def local_path(photo: dict) -> str:
    """Dónde queda la foto completa mientras se marca (se borra después)."""
    ext = os.path.splitext(photo["name"])[1].lower() or ".jpg"
    return os.path.join(_dir("fotos"), photo["id"] + ext)


def thumb_path(photo: dict) -> str:
    return os.path.join(_dir("miniaturas"), photo["id"] + ".jpg")


# ------------------------------------------------------------------ Drive
def folder_id(drive, create: bool = True) -> str | None:
    from drive_backup import ROOT_FOLDER
    root = drive._folder(ROOT_FOLDER, None)
    return drive._folder(FOLDER, root) if create else root and drive._folder(FOLDER, root)


def _list(drive, parent: str) -> list[dict]:
    from drive_backup import API
    out, token = [], None
    while True:
        params = {"q": f"'{parent}' in parents and trashed=false", "fields": FIELDS,
                  "pageSize": "1000", "spaces": "drive"}
        if token:
            params["pageToken"] = token
        res = drive._call("GET", f"{API}?" + urllib.parse.urlencode(params))
        out += res.get("files", [])
        token = res.get("nextPageToken")
        if not token:
            return out


def list_remote(drive) -> list[dict]:
    """Todas las fotos de la carpeta y sus subcarpetas (recorrido por niveles).
    Cada una: {id, name, rel, key, folder, w, h, thumb, created}."""
    out = []
    todo = [(folder_id(drive), "")]
    while todo:
        parent, prefix = todo.pop(0)
        for f in _list(drive, parent):
            if f.get("mimeType") == FOLDER_MIME:
                todo.append((f["id"], f"{prefix}{f['name']}/"))
            elif (f.get("mimeType") or "").startswith("image/"):
                meta = f.get("imageMediaMetadata") or {}
                rel = prefix + f["name"]
                out.append({"id": f["id"], "name": f["name"], "rel": rel, "key": key_for(rel),
                            "folder": prefix.rstrip("/"), "w": meta.get("width"), "h": meta.get("height"),
                            "thumb": f.get("thumbnailLink") or "", "created": f.get("createdTime") or ""})
    out.sort(key=lambda p: (p["folder"], p["name"]))
    return out


def refresh(drive) -> list[dict]:
    photos = list_remote(drive)
    save_index(photos)
    return photos


def fetch_thumb(drive, photo: dict, size: int = 240) -> str | None:
    """Miniatura de Drive (sin bajar la foto); si Drive no la entrega, se arma con la foto
    completa y esta se borra enseguida."""
    dest = thumb_path(photo)
    if os.path.exists(dest):
        return dest
    url = photo.get("thumb") or ""
    if url:
        url = url.split("=s")[0] + f"=s{size * 2}" if "=s" in url else url
        try:
            status, data = drive.transport("GET", url, {"Authorization": f"Bearer {drive._get_token()}"}, None)
            if status < 400 and data:
                with open(dest + ".part", "wb") as f:
                    f.write(data)
                os.replace(dest + ".part", dest)
                return dest
        except Exception:  # noqa: BLE001 (se intenta con la foto completa)
            pass
    full = local_path(photo)
    had = os.path.exists(full)
    try:
        if not had:
            fetch_full(drive, photo)
        from android_bridge import make_thumbnail
        make_thumbnail(full, dest, size)
        return dest
    except Exception:  # noqa: BLE001
        return None
    finally:
        if not had and os.path.exists(full):
            os.remove(full)


def fetch_full(drive, photo: dict) -> str:
    dest = local_path(photo)
    if not os.path.exists(dest):
        data = drive._download(photo["id"])
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
    return dest


def release(photo: dict) -> bool:
    """Borra la foto completa del teléfono (queda en Drive). True si había algo que borrar."""
    p = local_path(photo)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


def local_size() -> int:
    """Bytes que ocupan en el teléfono las fotos extra (completas y miniaturas)."""
    total = 0
    for sub in ("fotos", "miniaturas", "subir"):
        d = _dir(sub)
        for n in os.listdir(d):
            try:
                total += os.path.getsize(os.path.join(d, n))
            except OSError:
                pass
    return total


# ------------------------------------------------------------------ subir desde el teléfono
def add_local(src: str, drive) -> str:
    """Foto de la cámara o la galería → (EXIF, lado mayor ≤ 2400 px) → cola de subida a la
    carpeta (se sube sola, con reintentos). Devuelve el nombre en Drive."""
    from android_bridge import store_photo
    base = f"{_dt.datetime.now():%Y%m%d-%H%M%S}-extra"
    dest = store_photo(src, _dir("subir"), base, max_side=2400, exact=True)
    name = os.path.basename(dest)
    drive.enqueue(None, dest, remote=f"{FOLDER}/{name}")
    return name


def pending_uploads(drive) -> list[str]:
    """Fotos del teléfono que aún esperan subir; las ya subidas se borran de aquí."""
    left = []
    d = _dir("subir")
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        row = drive.db.query_one("SELECT status FROM drive_queue WHERE path=? ORDER BY id DESC LIMIT 1", (p,))
        if row and row["status"] == "done":
            os.remove(p)
        else:
            left.append(p)
    return left
