"""
rendimiento.py
==============
Estimaciones de rendimiento: un SET de fotos de detalle (varias fotos pequeñas de la misma
planta o tramo), en cada una se cuentan las estructuras desde botón floral (botón, botón
blanco, flor, flor pasada, fruto verde, pintón y maduro) y con eso se extrapolan los frutos
que habrá a fin de temporada y el rendimiento:

    frutos de la muestra = frutos ya cuajados + cuaja % × (botones + flores)
    frutos por planta    = frutos de la muestra ÷ (parte de la planta fotografiada %)
    kg por planta        = frutos por planta × peso medio del fruto (g) ÷ 1000
    kg por hectárea      = kg por planta × plantas por hectárea

Los conteos se ingresan a mano en cada foto o se toman de las cajas de IA+ (las fotos de las
estimaciones también aparecen en IA+ para marcarlas: así sirven para entrenar el detector,
que después contará solo).

Drive: «AeonCrop/<módulo>/Estimaciones de rendimiento/<fecha · lugar>/foto.jpg», aparte de
I+D y Predio, y «…/Estimaciones de rendimiento/estimaciones.csv» con todas.

Base propia por cultivo («rendimiento/rendimiento.sqlite3» en la carpeta de datos del
cultivo). Puro Python (sin Kivy).
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
import re
import unicodedata

from database import Database

DIR = "rendimiento"
DB_FILE = "rendimiento.sqlite3"
DRIVE_DIR = "Estimaciones de rendimiento"
CSV_NAME = "estimaciones.csv"
VEGETATIVE = {"yema", "brote", "lateral", "upright", "estolon"}   # no cuentan para el rendimiento
FRUIT_WEIGHT = {"frambuesa": 4.0, "arandano": 1.8, "cranberry": 1.2}   # g por fruto (por defecto)
FRUIT_SET = 80.0                       # % de botones y flores que llegan a fruto (por defecto)

SCHEMA = """
CREATE TABLE IF NOT EXISTS yield_sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    crop        TEXT NOT NULL DEFAULT '',
    place_kind  TEXT NOT NULL DEFAULT '',   -- ensayo | predio | otro
    place       TEXT NOT NULL DEFAULT '',
    place_code  TEXT NOT NULL DEFAULT '',
    sector      TEXT NOT NULL DEFAULT '',   -- sector, parcela o variedad
    taken_on    TEXT NOT NULL,              -- aaaa-mm-dd
    fruit_g     REAL,                       -- peso medio del fruto (g)
    fruit_set   REAL,                       -- cuaja de botones y flores (%)
    coverage    REAL,                       -- parte de la planta fotografiada (%)
    plants_ha   REAL,                       -- plantas por hectárea
    notes       TEXT NOT NULL DEFAULT '',
    latitude    REAL,
    longitude   REAL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS yield_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id      INTEGER NOT NULL REFERENCES yield_sets(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    queue_id    INTEGER,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS yield_counts (
    photo_id    INTEGER NOT NULL REFERENCES yield_photos(id) ON DELETE CASCADE,
    stage       TEXT NOT NULL,
    n           INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'manual',   -- manual | ia (cajas de IA+)
    PRIMARY KEY (photo_id, stage)
);
CREATE INDEX IF NOT EXISTS idx_yield_photo_set ON yield_photos(set_id);
"""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-")[:30] or "x"


def stages(crop_id: str) -> list[tuple[str, str, str]]:
    """Estructuras que se cuentan (desde botón floral), con el nombre y color de IA+."""
    from training_labels import CROP_CLASSES
    return [c for c in CROP_CLASSES.get(crop_id, CROP_CLASSES["frambuesa"]) if c[0] not in VEGETATIVE]


def is_fruit(stage: str) -> bool:
    return stage.startswith("fruto")


def estimate(totals: dict, fruit_g: float | None, fruit_set: float | None, coverage: float | None,
             plants_ha: float | None) -> dict:
    """Extrapolación (ver arriba). totals: {estructura: n} de todo el set."""
    fruits = sum(n for k, n in totals.items() if is_fruit(k))
    flowers = sum(n for k, n in totals.items() if not is_fruit(k))
    cuaja = (FRUIT_SET if fruit_set is None else fruit_set) / 100
    sample = fruits + cuaja * flowers
    cov = (coverage or 100) / 100
    per_plant = sample / cov if cov > 0 else 0.0
    kg_plant = per_plant * (fruit_g or 0) / 1000 if fruit_g else None
    kg_ha = kg_plant * plants_ha if kg_plant is not None and plants_ha else None
    return {"fruits": fruits, "flowers": flowers, "sample": sample, "per_plant": per_plant,
            "kg_plant": kg_plant, "kg_ha": kg_ha, "t_ha": kg_ha / 1000 if kg_ha is not None else None}


def counts_from_boxes(rec: dict | None, keys) -> dict | None:
    """Conteo por estructura a partir de las cajas de IA+ de una foto (None si no está
    marcada; {} si se marcó «sin estructuras»)."""
    if not rec:
        return None
    if rec.get("empty") and not rec.get("boxes"):
        return {}
    if not rec.get("boxes"):
        return None
    out = {k: 0 for k in keys}
    for b in rec["boxes"]:
        if b.get("c") in out:
            out[b["c"]] += 1
    return out


class YieldDB(Database):
    """Base de las estimaciones de un cultivo (con la maquinaria común: ajustes y cola de Drive)."""

    def __init__(self, data_dir: str, crop_id: str = "frambuesa"):
        self.base_dir = os.path.join(data_dir, DIR)
        self.crop_id = crop_id
        os.makedirs(self.base_dir, exist_ok=True)
        super().__init__(os.path.join(self.base_dir, DB_FILE), seed=False)
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    @property
    def photo_dir(self) -> str:
        d = os.path.join(self.base_dir, "fotos")
        os.makedirs(d, exist_ok=True)
        return d

    # ------------------------------------------------------------- sets
    def new_set(self, place: dict | None = None, sector: str = "", taken_on: str | None = None,
                fruit_g: float | None = None, fruit_set: float | None = None, coverage: float | None = 100,
                plants_ha: float | None = None) -> int:
        last = self.get_setting("yield_last") or {}
        place = place or {}
        cur = self.execute(
            "INSERT INTO yield_sets(crop, place_kind, place, place_code, sector, taken_on, fruit_g, fruit_set, "
            "coverage, plants_ha, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.crop_id, place.get("kind", ""), place.get("name", ""), place.get("code", ""), sector or "",
             taken_on or _dt.date.today().isoformat(),
             fruit_g if fruit_g is not None else last.get("fruit_g", FRUIT_WEIGHT.get(self.crop_id, 4.0)),
             fruit_set if fruit_set is not None else last.get("fruit_set", FRUIT_SET),
             coverage, plants_ha if plants_ha is not None else last.get("plants_ha"), _now()))
        return cur.lastrowid

    def get_set(self, set_id: int) -> dict | None:
        return self.query_one("SELECT * FROM yield_sets WHERE id=?", (set_id,))

    def update_set(self, set_id: int, **fields) -> None:
        allowed = {"place_kind", "place", "place_code", "sector", "taken_on", "fruit_g", "fruit_set",
                   "coverage", "plants_ha", "notes", "latitude", "longitude"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        self.execute(f"UPDATE yield_sets SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                     (*sets.values(), set_id))
        s = self.get_set(set_id)
        self.set_setting("yield_last", {"fruit_g": s["fruit_g"], "fruit_set": s["fruit_set"],
                                        "plants_ha": s["plants_ha"]})
        # Lugar o fecha cambiados: las fotos ya subidas van a su carpeta nueva.
        if {"place", "sector", "taken_on"} & set(sets):
            for p in self.photos(set_id):
                if p["queue_id"]:
                    q = self.query_one("SELECT * FROM drive_queue WHERE id=?", (p["queue_id"],))
                    if q:
                        status = "move" if q["status"] == "done" and q["drive_id"] else q["status"]
                        self.execute("UPDATE drive_queue SET name=?, status=? WHERE id=?",
                                     (self.remote_name(s, p["path"]), status, q["id"]))

    def sets(self) -> list[dict]:
        """Estimaciones (la más reciente primero) con su resultado."""
        out = []
        for s in self.query("SELECT * FROM yield_sets ORDER BY taken_on DESC, id DESC"):
            out.append(dict(s, **self.result(s["id"])))
        return out

    def delete_set(self, set_id: int) -> None:
        """Borra la estimación y sus fotos del teléfono (en Drive quedan)."""
        for p in self.photos(set_id):
            self._drop_photo(p)
        self.execute("DELETE FROM yield_sets WHERE id=?", (set_id,))

    # ------------------------------------------------------------- fotos
    def folder(self, s: dict) -> str:
        """Carpeta del set en Drive: «2026-11-09 · Nuevas variedades · Meeker»."""
        parts = [s["taken_on"], s["place"] or "Sin lugar", s["sector"]]
        return " · ".join(p.replace("/", "-").strip() for p in parts if p)

    def remote_name(self, s: dict, path: str) -> str:
        return f"{DRIVE_DIR}/{self.folder(s)}/{os.path.basename(path)}"

    def photo_basename(self, s: dict) -> str:
        """«20261109-REND-NV-Meeker»: fecha, REND, código del lugar y sector."""
        parts = [s["taken_on"].replace("-", ""), "REND", s["place_code"] or slug(s["place"]), slug(s["sector"])]
        return "-".join(p for p in parts if p and p != "x")

    def add_photo(self, set_id: int, path: str, enqueue: bool = True) -> int:
        s = self.get_set(set_id)
        queue_id = None
        if enqueue:
            queue_id = self.execute("INSERT INTO drive_queue(photo_id, path, name, created_at) VALUES (NULL,?,?,?)",
                                    (path, self.remote_name(s, path), _now())).lastrowid
        return self.execute("INSERT INTO yield_photos(set_id, path, queue_id, created_at) VALUES (?,?,?,?)",
                            (set_id, path, queue_id, _now())).lastrowid

    def photos(self, set_id: int) -> list[dict]:
        return self.query("SELECT * FROM yield_photos WHERE set_id=? ORDER BY id", (set_id,))

    def remove_photo(self, photo_id: int) -> None:
        p = self.query_one("SELECT * FROM yield_photos WHERE id=?", (photo_id,))
        if p:
            self._drop_photo(p)
            self.execute("DELETE FROM yield_photos WHERE id=?", (photo_id,))

    def _drop_photo(self, p: dict) -> None:
        if p["queue_id"]:
            self.execute("UPDATE drive_queue SET status='skipped', error='Quitada de la estimación' "
                         "WHERE id=? AND status='pending'", (p["queue_id"],))
        try:
            os.remove(p["path"])
        except OSError:
            pass

    # ------------------------------------------------------------- conteos
    def counts(self, photo_id: int) -> dict:
        return {r["stage"]: r["n"] for r in self.query("SELECT * FROM yield_counts WHERE photo_id=?", (photo_id,))}

    def count_source(self, photo_id: int) -> str:
        r = self.query_one("SELECT source FROM yield_counts WHERE photo_id=? LIMIT 1", (photo_id,))
        return r["source"] if r else ""

    def set_count(self, photo_id: int, stage: str, n: int, source: str = "manual") -> None:
        self.execute("INSERT INTO yield_counts(photo_id, stage, n, source) VALUES (?,?,?,?) "
                     "ON CONFLICT(photo_id, stage) DO UPDATE SET n=excluded.n, source=excluded.source",
                     (photo_id, stage, max(0, int(n)), source))

    def set_counts(self, photo_id: int, counts: dict, source: str = "manual") -> None:
        self.execute("DELETE FROM yield_counts WHERE photo_id=?", (photo_id,))
        for k, n in counts.items():
            self.set_count(photo_id, k, n, source)

    def apply_boxes(self, labels: dict, overwrite: bool = False) -> int:
        """Conteos desde las cajas de IA+ (labels: {nombre de foto: marcas}) para las fotos
        sin conteo a mano (o todas, con overwrite). Devuelve cuántas fotos se contaron."""
        keys = [k for k, _n, _c in stages(self.crop_id)]
        n = 0
        for p in self.query("SELECT * FROM yield_photos"):
            got = counts_from_boxes(labels.get(os.path.basename(p["path"])), keys)
            if got is None:
                continue
            src = self.count_source(p["id"])
            if src == "manual" and not overwrite:
                continue
            if src == "ia" and self.counts(p["id"]) == {k: v for k, v in got.items()}:
                continue
            self.set_counts(p["id"], got, "ia")
            n += 1
        return n

    def totals(self, set_id: int) -> dict:
        out = {k: 0 for k, _n, _c in stages(self.crop_id)}
        for r in self.query("SELECT c.stage, SUM(c.n) AS n FROM yield_counts c JOIN yield_photos p "
                            "ON p.id = c.photo_id WHERE p.set_id=? GROUP BY c.stage", (set_id,)):
            out[r["stage"]] = r["n"] or 0
        return out

    def result(self, set_id: int) -> dict:
        s = self.get_set(set_id)
        tot = self.totals(set_id)
        counted = self.query_one("SELECT COUNT(DISTINCT c.photo_id) AS n FROM yield_counts c JOIN yield_photos p "
                                 "ON p.id = c.photo_id WHERE p.set_id=?", (set_id,))["n"]
        n_photos = self.query_one("SELECT COUNT(*) AS n FROM yield_photos WHERE set_id=?", (set_id,))["n"]
        return dict(estimate(tot, s["fruit_g"], s["fruit_set"], s["coverage"], s["plants_ha"]),
                    totals=tot, photos=n_photos, counted=counted)

    # ------------------------------------------------------------- planilla
    def export_csv(self, path: str | None = None) -> str:
        """Todas las estimaciones en una planilla (una fila por estimación)."""
        path = path or os.path.join(self.base_dir, CSV_NAME)
        keys = stages(self.crop_id)
        head = (["Fecha", "Lugar", "Código", "Sector / variedad", "Fotos", "Fotos contadas"]
                + [n for _k, n, _c in keys]
                + ["Cuaja (%)", "Parte fotografiada (%)", "Peso fruto (g)", "Plantas/ha",
                   "Frutos por planta", "kg por planta", "kg/ha", "Notas"])
        num = lambda v, d=1: "" if v is None else f"{v:.{d}f}".replace(".", ",")   # noqa: E731
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(head)
            for s in self.sets():
                w.writerow([s["taken_on"], s["place"], s["place_code"], s["sector"], s["photos"], s["counted"]]
                           + [s["totals"].get(k, 0) for k, _n, _c in keys]
                           + [num(s["fruit_set"], 0), num(s["coverage"], 0), num(s["fruit_g"]),
                              num(s["plants_ha"], 0), num(s["per_plant"]), num(s["kg_plant"], 2),
                              num(s["kg_ha"], 0), s["notes"]])
        return path


class YieldDrive:
    """Respaldo en Drive: fotos en «AeonCrop/<módulo>/Estimaciones de rendimiento/…» y la planilla."""

    def __init__(self, db: YieldDB, backup=None, crop=None):
        self.db = db
        if backup is None:
            from drive_backup import DriveBackup
            backup = DriveBackup(db, crop=crop)
        self.backup = backup

    @property
    def enabled(self) -> bool:
        return self.backup.enabled

    def move_pending(self) -> int:
        n = 0
        for r in self.db.query("SELECT * FROM drive_queue WHERE status='move'"):
            try:
                self.backup.move_file(r["drive_id"], r["name"])
                self.db.execute("UPDATE drive_queue SET status='done' WHERE id=?", (r["id"],))
                n += 1
            except Exception as exc:  # noqa: BLE001 (sin red: se reintenta la próxima vez)
                if getattr(exc, "status", None) in (403, 404):
                    self.db.execute("UPDATE drive_queue SET status='pending', drive_id=NULL WHERE id=?", (r["id"],))
                else:
                    break
        return n

    def run(self) -> int:
        if not self.enabled:
            return 0
        self.move_pending()
        n = self.backup.flush()
        if self.db.query_one("SELECT 1 FROM yield_sets LIMIT 1"):
            try:
                self.backup.put_file(self.db.export_csv(), f"{DRIVE_DIR}/{CSV_NAME}")
            except Exception:  # noqa: BLE001 (la planilla se repone en la próxima subida)
                pass
        return n
