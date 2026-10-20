"""
sync_drive.py
=============
Sincronización celular ↔ PC por Google Drive (etapa 2): lleva los paquetes de sync.py.

Carpeta en Drive (la misma del respaldo, permiso `drive.file`):

    PhenoRubus · Imágenes de Fenología / Sincronización /
        ensayos-<equipo>.json          lista de ensayos y predios de cada equipo
        <CÓDIGO>/<fecha>-<equipo>.json paquetes de cambios de ese ensayo o predio

* Cada equipo sube solo sus paquetes y lee los de los demás (los ya leídos se recuerdan).
* Primero se reciben los cambios de los otros y luego se envían los propios; el más
  reciente gana (sync.apply_changes).
* Si en el otro equipo hay un ensayo o predio que aquí no existe, se crea vacío y se
  llena con sus paquetes.
* Los paquetes son livianos (texto); las fotos van aparte (etapa 3).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor

import sync
from drive_backup import API, ROOT_FOLDER, UPLOAD, DriveError

SYNC_FOLDER = "Sincronización"
MAX_DOWNLOADS = 200         # fotos por sincronización automática (la manual las baja todas)
LOOKUP_BATCH = 40           # nombres de foto por consulta a Drive
THREADS = 4                 # descargas simultáneas
WS_FIELDS = ("profile", "kind", "name", "code")


def _stamp() -> str:
    return _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")[:-3]


class DriveSync:
    def __init__(self, drive, workspaces, open_db, data_dir: str):
        self.drive = drive                  # DriveBackup: cuenta, token y llamadas a la API
        self.workspaces = workspaces
        self.open_db = open_db
        self.data_dir = data_dir

    # ------------------------------------------------------------ Drive
    def _root(self) -> str:
        return self.drive._folder(SYNC_FOLDER, self.drive._folder(ROOT_FOLDER, None))

    def _list(self, folder: str) -> list[dict]:
        out, token = [], None
        while True:
            params = {"q": f"'{folder}' in parents and trashed=false",
                      "fields": "nextPageToken, files(id, name)", "orderBy": "name",
                      "pageSize": "1000", "spaces": "drive"}
            if token:
                params["pageToken"] = token
            res = self.drive._call("GET", f"{API}?" + urllib.parse.urlencode(params))
            out += res.get("files", [])
            token = res.get("nextPageToken")
            if not token:
                return out

    def _put(self, folder: str, name: str, data: bytes, file_id: str | None = None) -> str:
        boundary = uuid.uuid4().hex
        meta = {"name": name} if file_id else {"name": name, "parents": [folder]}
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                + json.dumps(meta).encode()
                + f"\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode()
                + data + f"\r\n--{boundary}--\r\n".encode())
        ctype = f"multipart/related; boundary={boundary}"
        if file_id:                          # reemplaza el contenido (lista de ensayos)
            url = UPLOAD.replace("/files?", f"/files/{file_id}?")
            return self.drive._call("PATCH", url, body, ctype)["id"]
        return self.drive._call("POST", UPLOAD, body, ctype)["id"]

    def _get(self, file_id: str) -> bytes:
        return self.drive._download(file_id)

    def _parallel(self, fn, items: list) -> list:
        """fn(item) para cada item con THREADS descargas a la vez (solo red, sin tocar la base)."""
        if len(items) <= 1:
            return [fn(x) for x in items]
        self.drive._get_token()             # el token se pide una vez, antes de los hilos
        with ThreadPoolExecutor(THREADS) as ex:
            return list(ex.map(fn, items))

    def _find(self, names: list[str]) -> dict[str, str]:
        """{nombre: id} de las fotos que ya están en Drive (de a LOOKUP_BATCH por consulta)."""
        def query(part):
            esc = [n.replace("\\", "\\\\").replace("'", "\\'") for n in part]
            q = "(" + " or ".join(f"name='{n}'" for n in esc) + ") and trashed=false"
            out, token = {}, None
            while True:
                params = {"q": q, "fields": "nextPageToken, files(id, name)", "pageSize": "1000", "spaces": "drive"}
                if token:
                    params["pageToken"] = token
                res = self.drive._call("GET", f"{API}?" + urllib.parse.urlencode(params))
                for f in res.get("files", []):
                    out.setdefault(f["name"], f["id"])
                token = res.get("nextPageToken")
                if not token:
                    return out
        found: dict[str, str] = {}
        parts = [names[i:i + LOOKUP_BATCH] for i in range(0, len(names), LOOKUP_BATCH)]
        for res in self._parallel(query, parts):
            found.update(res)
        return found

    # ------------------------------------------------------------ ensayos
    def _sync_workspaces(self, root: str, device: str, files: list[dict]) -> int:
        """Crea aquí los ensayos/predios que el otro equipo tiene y este no; publica los de aquí."""
        created = 0
        mine = f"ensayos-{device}.json"
        codes = self.workspaces.codes()
        for f in files:
            if not f["name"].startswith("ensayos-") or f["name"] == mine:
                continue
            for ws in json.loads(self._get(f["id"]).decode("utf-8")):
                if ws["code"] not in codes:
                    self.workspaces.create(ws["profile"], ws["kind"], ws["name"], ws["code"])
                    codes.add(ws["code"])
                    created += 1
        local = [{k: w[k] for k in WS_FIELDS} for w in self.workspaces.list()]
        raw = json.dumps(local, ensure_ascii=False, sort_keys=True).encode("utf-8")
        digest = hashlib.sha1(raw).hexdigest()
        shared = self.workspaces.shared
        if shared.get_setting("sync_ws_sent") != digest:
            existing = next((f for f in files if f["name"] == mine), None)
            self._put(root, mine, raw, existing["id"] if existing else None)
            shared.set_setting("sync_ws_sent", digest)
        return created

    # ------------------------------------------------------------ un ensayo
    def sync_db(self, db, folder: str) -> dict:
        device = sync.device_id(db)
        stats = {"received": 0, "sent": 0, "applied": 0, "missing_files": []}
        seen = {r["name"] for r in db.query("SELECT name FROM sync_seen")}
        new = [f for f in self._list(folder) if f["name"].endswith(".json")
               and not f["name"].endswith(f"-{device}.json") and f["name"] not in seen]
        new.sort(key=lambda f: f["name"])
        # Se bajan en paralelo y se aplican en orden (el más reciente gana igual).
        for f, raw in zip(new, self._parallel(lambda f: self._get(f["id"]), new)):
            name = f["name"]
            bundle = sync.loads(raw)
            res = sync.apply_changes(db, bundle, self.data_dir, week_for_date=db.week_for_date)
            stats["received"] += 1
            stats["applied"] += res["applied"]
            stats["missing_files"] += res["missing_files"]
            for path in res["missing_files"]:
                db.execute("INSERT OR IGNORE INTO sync_missing(path) VALUES (?)", (path,))
            db.execute("INSERT OR IGNORE INTO sync_seen(name) VALUES (?)", (name,))
        bundle = sync.export_changes(db, self.data_dir)
        settings_hash = hashlib.sha1(json.dumps(bundle["settings"], sort_keys=True).encode()).hexdigest()
        sent_hash = db.query_one("SELECT value FROM sync_state WHERE key='settings_sent'")
        if bundle["changes"] or (sent_hash or {}).get("value") != settings_hash:
            self._put(folder, f"{_stamp()}-{device}.json", sync.dumps(bundle))
            sync.mark_exported(db, bundle)
            db.execute("INSERT OR REPLACE INTO sync_state(key, value) VALUES ('settings_sent', ?)",
                       (settings_hash,))
            stats["sent"] = len(bundle["changes"])
        return stats

    # ------------------------------------------------------------ fotos
    def fetch_missing(self, db, limit: int | None = MAX_DOWNLOADS) -> tuple[int, int]:
        """Baja de Drive las fotos de registros que llegaron del otro equipo. Se buscan por su
        nombre (fecha, código del ensayo y tipo: no se repiten), de a varias por consulta, y se
        bajan THREADS a la vez; si el otro equipo aún no la subió, se reintenta en la próxima
        sincronización. limit=None: todas. Devuelve (bajadas, pendientes)."""
        rows = []
        for r in db.query("SELECT * FROM sync_missing ORDER BY tries, path"):
            if os.path.exists(r["path"]):
                db.execute("DELETE FROM sync_missing WHERE path=?", (r["path"],))
            else:
                rows.append(r)
        ids = self._find(sorted({os.path.basename(r["path"]) for r in rows}))
        now = _dt.datetime.now().isoformat(timespec="seconds")
        todo = []
        for r in rows:
            fid = ids.get(os.path.basename(r["path"]))
            if not fid:
                db.execute("UPDATE sync_missing SET tries=tries+1, last=? WHERE path=?", (now, r["path"]))
            elif limit is None or len(todo) < limit:
                todo.append((r["path"], fid))
        got = 0
        for i in range(0, len(todo), 20):       # de a 20: lo bajado se guarda aunque luego se corte
            chunk = todo[i:i + 20]
            for (path, fid), data in zip(chunk, self._parallel(lambda t: self._get(t[1]), chunk)):
                self._store(db, path, fid, data)
                got += 1
        left = db.query_one("SELECT COUNT(*) AS n FROM sync_missing")["n"]
        return got, left

    def _store(self, db, path: str, file_id: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        # Ya está en Drive: que el respaldo de este equipo no la vuelva a subir.
        photo = db.query_one("SELECT id FROM photos WHERE path=?", (path,))
        now = _dt.datetime.now().isoformat(timespec="seconds")
        db.execute("INSERT INTO drive_queue(photo_id, path, name, status, drive_id, created_at, "
                   "uploaded_at) VALUES (?,?,?,?,?,?,?)",
                   (photo["id"] if photo else None, path, os.path.basename(path), "done",
                    file_id, now, now))
        db.execute("DELETE FROM sync_missing WHERE path=?", (path,))

    # ------------------------------------------------------------ todo
    def run(self, manual: bool = False) -> dict:
        """Sincroniza todos los ensayos y predios. Devuelve un resumen para la pantalla.
        manual=True (botón «Sincronizar»): baja todas las fotos pendientes."""
        root = self._root()
        files = self._list(root)
        device = sync.device_id(self.workspaces.shared)
        total = {"workspaces": 0, "created": 0, "received": 0, "sent": 0, "applied": 0,
                 "missing_files": [], "downloaded": 0, "pending_photos": 0, "when": _dt.datetime.now().isoformat(timespec="seconds")}
        total["created"] = self._sync_workspaces(root, device, files)
        folders = {f["name"]: f["id"] for f in files}
        for ws in self.workspaces.list():
            db = self.open_db(ws)
            folder = folders.get(ws["code"]) or self.drive._folder(ws["code"], root)
            res = self.sync_db(db, folder)
            total["workspaces"] += 1
            for k in ("received", "sent", "applied"):
                total[k] += res[k]
            if self.photos_allowed():
                got, left = self.fetch_missing(db, None if manual else MAX_DOWNLOADS)
                total["downloaded"] += got
                total["pending_photos"] += left
            else:
                total["pending_photos"] += db.query_one("SELECT COUNT(*) AS n FROM sync_missing")["n"]
        return total

    def photos_allowed(self) -> bool:
        """Las fotos se bajan con Wi-Fi si así está el respaldo («Subir solo con Wi-Fi»)."""
        return not (self.drive.wifi_only and self.drive.metered())


def summary(res: dict) -> str:
    """«Sincronizado: 12 cambios recibidos, 3 enviados» para la tarjeta de Ajustes."""
    parts = []
    if res.get("created"):
        parts.append(f"{res['created']} ensayo(s) nuevo(s)")
    parts.append(f"{res.get('applied', 0)} cambio(s) recibido(s)")
    parts.append(f"{res.get('sent', 0)} enviado(s)")
    if res.get("downloaded"):
        parts.append(f"{res['downloaded']} foto(s) descargada(s)")
    if res.get("pending_photos"):
        parts.append(f"{res['pending_photos']} foto(s) por bajar")
    return "Sincronizado: " + ", ".join(parts)
