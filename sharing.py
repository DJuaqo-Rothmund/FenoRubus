"""
sharing.py
==========
Ensayos compartidos entre DOS O MÁS CUENTAS de Google (p. ej. tú y una compañera).

Quien comparte deja su carpeta del ensayo en Drive como carpeta común y le da permiso de
edición a la otra cuenta. Dentro:

    <carpeta del ensayo>/                fotos por semana y parcela (cada una la sube quien la tomó:
        Año 2026/Semana 46 · …/…         queda en el Drive de quien la tomó)
        Sincronización/                  paquetes de cambios de cada teléfono (sync.py)

* La carpeta lleva propiedades («aeoncrop_shared»…) para que la otra persona la encuentre
  entre «Compartido conmigo» y se una con un toque.
* En cada teléfono el ensayo guarda `share_folder` y `share_sync` (ajustes del ensayo, viajan
  también a los otros equipos de la misma cuenta).
* Hace falta el permiso amplio de Drive (drive_backup.SHARE_SCOPE): con el de siempre la app
  solo ve lo que ella misma creó en esa cuenta.

Puro Python (la red va por DriveBackup._call): se prueba con un Drive falso.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from drive_backup import API, FOLDER_MIME, DriveError

PROP = "aeoncrop_shared"
SYNC_SUB = "Sincronización"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
JSON = "application/json; charset=UTF-8"


def is_shared(db) -> bool:
    return bool(db.get_setting("share_folder"))


def _ensayo_folder(drive) -> str:
    """Carpeta del ensayo en Drive del dueño (la de siempre: «I+D/<ensayo>»), creándola."""
    from workspaces import Workspaces
    parent = drive.root_id()
    for part in Workspaces.drive_prefix(drive.db.workspace).split("/"):
        parent = drive._folder(part, parent)
    return parent


def share(drive, email: str, message: str = "") -> dict:
    """Comparte el ensayo de `drive.db` con `email` (permiso de edición). La primera vez deja
    su carpeta como carpeta común. Devuelve {"folder", "sync", "email"}."""
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("Escriba un correo válido (la cuenta de Google de la otra persona).")
    db = drive.db
    ws = db.workspace or {}
    folder = db.get_setting("share_folder") or _ensayo_folder(drive)
    props = {PROP: "1", "code": ws.get("code", ""), "profile": ws.get("profile", ""),
             "kind": ws.get("kind", ""), "name": (ws.get("name") or "")[:100]}
    drive._call("PATCH", f"{API}/{folder}?fields=id", json.dumps({"properties": props}).encode(), JSON)
    sync_folder = db.get_setting("share_sync") or drive._folder(SYNC_SUB, folder)
    body = {"type": "user", "role": "writer", "emailAddress": email}
    params = {"sendNotificationEmail": "true", "fields": "id"}
    if message:
        params["emailMessage"] = message[:500]
    drive._call("POST", f"{API}/{folder}/permissions?" + urllib.parse.urlencode(params),
                json.dumps(body).encode(), JSON)
    db.set_setting("share_folder", folder)
    db.set_setting("share_sync", sync_folder)
    db.log("share", "workspace", None, f"compartido con {email}")
    return {"folder": folder, "sync": sync_folder, "email": email}


def members(drive, folder: str) -> list[dict]:
    """[{email, role, name}] de quienes tienen acceso a la carpeta común."""
    res = drive._call("GET", f"{API}/{folder}/permissions?" + urllib.parse.urlencode(
        {"fields": "permissions(id,emailAddress,role,displayName,type)"}))
    return [{"id": p.get("id"), "email": (p.get("emailAddress") or "").lower(), "role": p.get("role"),
             "name": p.get("displayName") or ""} for p in res.get("permissions", [])
            if p.get("type") == "user"]


def unshare(drive, email: str) -> bool:
    """Quita el acceso de `email` a la carpeta común (sus datos ya sincronizados quedan)."""
    folder = drive.db.get_setting("share_folder")
    if not folder:
        return False
    for m in members(drive, folder):
        if m["email"] == email.lower() and m["role"] != "owner":
            drive._call("DELETE", f"{API}/{folder}/permissions/{m['id']}")
            return True
    return False


def invitations(drive) -> list[dict]:
    """Ensayos que otras cuentas compartieron conmigo: [{folder, code, name, profile, kind, owner}]."""
    q = (f"sharedWithMe and mimeType='{FOLDER_MIME}' and trashed=false and "
         f"properties has {{ key='{PROP}' and value='1' }}")
    res = drive._call("GET", f"{API}?" + urllib.parse.urlencode(
        {"q": q, "fields": "files(id,name,properties,owners(emailAddress,displayName))",
         "spaces": "drive", "pageSize": "100"}))
    out = []
    for f in res.get("files", []):
        p = f.get("properties") or {}
        owner = (f.get("owners") or [{}])[0]
        out.append({"folder": f["id"], "code": (p.get("code") or "").upper(),
                    "name": p.get("name") or f.get("name") or "", "profile": p.get("profile") or "id",
                    "kind": p.get("kind") or "variedades",
                    "owner": owner.get("displayName") or owner.get("emailAddress") or ""})
    return out


def joined_folders(workspaces, open_db) -> dict[str, str]:
    """{carpeta común: código} de los ensayos de este teléfono que ya están unidos."""
    out = {}
    for ws in workspaces.list() + workspaces.list(archived=True):
        f = open_db(ws).get_setting("share_folder")
        if f:
            out[f] = ws["code"]
    return out


def join(drive, workspaces, open_db, inv: dict) -> dict:
    """Une el ensayo compartido a este teléfono: si ya hay uno con el mismo código, se une a
    ese (sus datos se juntan al sincronizar); si no, se crea. Devuelve el ensayo."""
    code = inv["code"]
    if not code:
        raise ValueError("La invitación no trae el código del ensayo.")
    ws = workspaces.by_code(code)
    if ws is None:
        ws = workspaces.create(inv.get("profile") or "id", inv.get("kind") or "variedades",
                               inv.get("name") or code, code)
    db = open_db(ws)
    q = (f"name='{SYNC_SUB}' and mimeType='{FOLDER_MIME}' and trashed=false "
         f"and '{inv['folder']}' in parents")
    found = drive._call("GET", f"{API}?" + urllib.parse.urlencode(
        {"q": q, "fields": "files(id)", "spaces": "drive"})).get("files", [])
    if found:
        sync_folder = found[0]["id"]
    else:
        meta = {"name": SYNC_SUB, "mimeType": FOLDER_MIME, "parents": [inv["folder"]]}
        sync_folder = drive._call("POST", f"{API}?fields=id", json.dumps(meta).encode(), JSON)["id"]
    db.set_setting("share_folder", inv["folder"])
    db.set_setting("share_sync", sync_folder)
    db.log("share", "workspace", None, f"unido al ensayo compartido por {inv.get('owner', '')}")
    return ws


def check_access(drive, folder: str) -> bool:
    """¿Esta cuenta todavía ve la carpeta común? (False: se quitó el acceso o se borró)."""
    try:
        drive._call("GET", f"{API}/{folder}?fields=id,trashed")
        return True
    except DriveError as exc:
        if exc.status in (403, 404):
            return False
        raise
