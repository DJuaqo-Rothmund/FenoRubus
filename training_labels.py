"""
training_labels.py
==================
Marcas para entrenar el detector de estructuras (yemas, brotes, laterales, botones, flores
y frutos): cajas sobre las fotos de detalle de TODOS los ensayos y predios (es una sola
especie, una sola meta).

Mismo formato y mismo archivo que la web (web/train.js), para marcar en el teléfono o en
el PC indistintamente:

    Drive: «PhenoRubus · Imágenes de Fenología/Entrenamiento IA/marcas.json»
    {"version": 1, "classes": [...],
     "photos": {"<nombre del archivo>": {"w", "h", "boxes": [{"c", "x", "y", "w", "h"}],
                                         "empty", "by", "ts"}}}

x, y, w, h van de 0 a 1 respecto de la foto. Al sincronizar se suman las marcas de ambos
lados y, por foto, gana la más reciente (ts).
"""
from __future__ import annotations

import datetime as _dt
import json
import os

CLASSES = [            # (clave, nombre, color): la posición es la tecla en la web (0–9)
    ("yema", "Yema", "#A1887F"),
    ("brote", "Brote", "#8BC34A"),
    ("lateral", "Lateral", "#5C6BC0"),
    ("boton", "Botón", "#00897B"),
    ("boton_blanco", "Botón blanco", "#78909C"),
    ("flor", "Flor", "#F9A825"),
    ("flor_pasada", "Flor pasada", "#8D6E63"),
    ("fruto_verde", "Fruto verde", "#2E7D32"),
    ("fruto_pinton", "Fruto pintón", "#EC407A"),
    ("fruto_maduro", "Fruto maduro", "#B71C1C"),
]
NAMES = {k: n for k, n, _ in CLASSES}
COLORS = {k: c for k, _, c in CLASSES}
GOAL = 300
DRIVE_DIR = "Entrenamiento IA"
DRIVE_FILE = "marcas.json"


def now_ts() -> str:
    """Mismo formato que la web (ISO sin zona, con milisegundos): se comparan como texto."""
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="milliseconds")


def merge(into: dict, other: dict | None) -> int:
    """Suma a `into` las fotos de `other` que sean nuevas o más recientes. Devuelve cuántas."""
    n = 0
    photos = into.setdefault("photos", {})
    for name, rec in ((other or {}).get("photos") or {}).items():
        cur = photos.get(name)
        if cur is None or (rec.get("ts") or "") > (cur.get("ts") or ""):
            photos[name] = rec
            n += 1
    return n


def is_marked(rec: dict | None) -> bool:
    return bool(rec and (rec.get("empty") or rec.get("boxes")))


class LabelStore:
    """Copia local de las marcas (data/training/marcas.json) y su sincronización con Drive."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "training", DRIVE_FILE)
        self.data = {"version": 1, "classes": [k for k, _, _ in CLASSES], "photos": {}}
        self.dirty = False
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                got = json.load(f)
            self.data["photos"] = got.get("photos") or {}
            self.dirty = bool(got.get("_dirty"))
        except (OSError, ValueError):
            pass

    def save_local(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({**self.data, "_dirty": self.dirty}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, name: str) -> dict | None:
        return self.data["photos"].get(name)

    def put(self, name: str, rec: dict, by: str = "") -> None:
        rec["ts"] = now_ts()
        rec["by"] = by
        if rec.get("boxes"):
            rec["empty"] = False
        self.data["photos"][name] = rec
        self.dirty = True
        self.save_local()

    def totals(self) -> dict[str, int]:
        out = {k: 0 for k, _, _ in CLASSES}
        for rec in self.data["photos"].values():
            for b in rec.get("boxes") or []:
                out[b["c"]] = out.get(b["c"], 0) + 1
        return out

    # ------------------------------------------------------------ Drive
    def sync(self, drive_sync) -> int:
        """Baja las marcas de Drive (las del PC u otro teléfono), las suma y sube el total si
        aquí hay cambios. drive_sync: sync_drive.DriveSync. Devuelve cuántas fotos llegaron."""
        from drive_backup import ROOT_FOLDER
        drive = drive_sync.drive
        root = drive._folder(ROOT_FOLDER, None)
        folder = drive._folder(DRIVE_DIR, root)
        files = [f for f in drive_sync._list(folder) if f["name"].endswith(".json")]
        main = next((f for f in files if f["name"] == DRIVE_FILE), None)
        got = 0
        for f in files:          # marcas.json y, si quedan, los archivos por ensayo de la web v1
            try:
                got += merge(self.data, json.loads(drive_sync._get(f["id"]).decode("utf-8")))
            except ValueError:
                continue
        if self.dirty or main is None:       # aquí hay marcas nuevas: se sube el total
            body = json.dumps({"version": 1, "classes": self.data["classes"], "photos": self.data["photos"]},
                              ensure_ascii=False).encode("utf-8")
            drive_sync._put(folder, DRIVE_FILE, body, main["id"] if main else None)
        self.dirty = False
        self.save_local()
        return got


def detail_photos(dbs) -> list[dict]:
    """Fotos de detalle de todos los ensayos/predios abiertos (la más reciente primero).
    Cada una: {name, path, code, ws, variety, week, exists}."""
    out, seen = [], set()
    for db in dbs:
        ws = getattr(db, "workspace", None) or {}
        rows = db.query(
            "SELECT p.path, v.name AS variety, v.cultivar, w.start_date AS week FROM photos p "
            "JOIN observations o ON o.id = p.observation_id JOIN varieties v ON v.id = o.variety_id "
            "JOIN sampling_weeks w ON w.id = o.week_id WHERE p.kind = 'detail' AND p.path IS NOT NULL")
        for r in rows:
            name = os.path.basename(r["path"])
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "path": r["path"], "code": ws.get("code", ""),
                        "ws": ws.get("name") or ws.get("code", ""),
                        "variety": r["cultivar"] or r["variety"] or "", "week": r["week"] or "",
                        "exists": os.path.exists(r["path"])})
    out.sort(key=lambda p: (p["week"], p["name"]), reverse=True)
    return out
