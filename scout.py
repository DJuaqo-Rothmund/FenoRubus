"""
scout.py
========
AeonScout: banco de imágenes de PLAGAS, MALEZAS y ENFERMEDADES del campo, para entrenar
más adelante una IA que las reconozca.

* Cada captura = un individuo (o una muestra): una o varias fotos, la especie (o «No
  identificada»: NI-001, NI-002…), su estadio, el órgano, la abundancia, notas, GPS y DÓNDE
  se tomó (cultivo, ensayo o predio y sector).
* Las no identificadas se agrupan por código: si se vuelve a ver la misma, se suman fotos
  a su NI. Al identificarla, todas sus fotos pasan a la especie (también en Drive).
* Drive: «AeonCrop/AeonScout/<Plagas|Malezas|Enfermedades>/<especie>/<estadio>/foto.jpg»
  (las no identificadas en «…/No identificadas/NI-003/…») y «AeonCrop/AeonScout/registro.csv»
  con todas las capturas.

Base propia («aeonscout/aeonscout.sqlite3» en la raíz de datos: vale para todos los
cultivos). Puro Python (sin Kivy).
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from database import Database

DIR = "aeonscout"
DB_FILE = "aeonscout.sqlite3"
DRIVE_FOLDER = "AeonScout"
UNIDENTIFIED = "No identificadas"

# sección -> (nombre, carpeta en Drive, código en el nombre de las fotos, color)
SECTIONS = {
    "plagas": ("Plagas", "Plagas", "PL", "#A0441E"),
    "malezas": ("Malezas", "Malezas", "MZ", "#2E6B34"),
    "enfermedades": ("Enfermedades", "Enfermedades", "EF", "#6E4A9E"),
}
STAGES = {
    "plagas": ["Huevo", "Larva / ninfa", "Pupa", "Adulto", "Daño / síntoma"],
    "malezas": ["Plántula (cotiledones)", "Vegetativo / roseta", "Floración", "Semillado", "Rebrote"],
    "enfermedades": ["Síntoma inicial", "Síntoma avanzado", "Signos (micelio, esporas)"],
}
ORGANS = ["Hoja", "Brote", "Caña / tallo", "Flor", "Fruto", "Raíz / cuello", "Planta completa",
          "Suelo", "Trampa"]
ABUNDANCE = ["Escasa", "Media", "Alta"]
VIEWS = {   # vistas que sirven para entrenar (la app sugiere la que falta)
    "plagas": ["Dorsal", "Lateral", "Ventral", "Daño"],
    "malezas": ["Planta completa", "Hoja (haz)", "Hoja (envés)", "Flor / semilla"],
    "enfermedades": ["Órgano completo", "Detalle de la lesión"],
}
GOAL = 100   # fotos por especie y estadio para entrenar bien (meta del contador)

# Catálogo inicial (se puede editar): (nombre común, nombre científico, tipo)
CATALOG = {
    "malezas": [
        ("Correhuela", "Convolvulus arvensis", ""),
        ("Chufa", "Cyperus spp.", ""),
        ("Maicillo", "Sorghum halepense", ""),
        ("Diente de león", "Taraxacum officinale", ""),
        ("Malva", "Malva spp.", ""),
        ("Rábano silvestre", "Raphanus raphanistrum", ""),
        ("Ballica", "Lolium spp.", ""),
        ("Sanguinaria", "Polygonum aviculare", ""),
        ("Pasto cebolla", "Arrhenatherum elatius", ""),
        ("Vinagrillo", "Rumex acetosella", ""),
        ("Milenrama", "Achillea millefolium", ""),
        ("Romaza", "Rumex spp.", ""),
    ],
    "plagas": [
        ("Burrito de la vid", "Naupactus xanthographus", "plaga"),
        ("Drosophila de alas manchadas", "Drosophila suzukii", "plaga"),
        ("Trips", "Frankliniella spp.", "plaga"),
        ("Pulgones", "Aphididae", "plaga"),
        ("Arañita roja (ácaro)", "Tetranychus urticae", "plaga"),
        ("Chanchito blanco", "Pseudococcus spp.", "plaga"),
        ("Gusano blanco", "Hylamorpha elegans", "plaga"),
        ("Escamas", "Coccoidea", "plaga"),
        ("Chinita", "Coccinellidae", "benefico"),
    ],
    "enfermedades": [
        ("Botritis (pudrición gris)", "Botrytis cinerea", ""),
        ("Oídio", "Podosphaera spp.", ""),
        ("Roya", "Phragmidium rubi-idaei", ""),
        ("Pudrición de raíz", "Phytophthora spp.", ""),
        ("Cancro bacteriano", "Pseudomonas syringae", ""),
        ("Antracnosis", "Elsinoë veneta", ""),
        ("Agalla del cuello", "Agrobacterium tumefaciens", ""),
        ("Verticilosis", "Verticillium spp.", ""),
        ("Virosis", "virus", ""),
    ],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_species (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT NOT NULL,              -- plagas | malezas | enfermedades
    name        TEXT NOT NULL COLLATE NOCASE,
    scientific  TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT '',   -- plaga | benefico (insectos)
    notes       TEXT NOT NULL DEFAULT '',
    unidentified INTEGER NOT NULL DEFAULT 0, -- 1 = «NI-003» (por identificar)
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    UNIQUE (section, name)
);
CREATE TABLE IF NOT EXISTS scout_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT NOT NULL,
    species_id  INTEGER NOT NULL REFERENCES scout_species(id),
    stage       TEXT NOT NULL DEFAULT '',
    organ       TEXT NOT NULL DEFAULT '',
    abundance   TEXT NOT NULL DEFAULT '',
    crop        TEXT NOT NULL DEFAULT '',   -- id del cultivo (frambuesa…) u otro escrito
    place_kind  TEXT NOT NULL DEFAULT '',   -- ensayo | predio | otro
    place       TEXT NOT NULL DEFAULT '',   -- nombre del ensayo o predio
    place_code  TEXT NOT NULL DEFAULT '',
    sector      TEXT NOT NULL DEFAULT '',   -- sector / unidad del predio (o parcela)
    notes       TEXT NOT NULL DEFAULT '',
    latitude    REAL,
    longitude   REAL,
    taken_at    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scout_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   INTEGER NOT NULL REFERENCES scout_records(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    view        TEXT NOT NULL DEFAULT '',
    queue_id    INTEGER,                    -- fila de drive_queue (subida a Drive)
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scout_rec_species ON scout_records(species_id);
CREATE INDEX IF NOT EXISTS idx_scout_photo_rec ON scout_photos(record_id);
"""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def slug(text: str) -> str:
    """«Diente de león» -> «Diente-de-leon» (para nombres de archivo)."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-")
    return t[:40] or "x"


def folder_name(text: str) -> str:
    """Nombre seguro para una carpeta de Drive (sin «/»)."""
    return (text or "").replace("/", "-").strip() or "Sin nombre"


@dataclass(frozen=True)
class ScoutModule:
    """Lo que DriveBackup necesita de un «módulo»: su carpeta en «AeonCrop»."""
    id: str = "aeonscout"
    app: str = DRIVE_FOLDER

    @property
    def drive_folder(self) -> str:
        return self.app


MODULE = ScoutModule()


class ScoutDB(Database):
    """Base de AeonScout (usa la maquinaria común: ajustes, bitácora y cola de Drive)."""

    def __init__(self, base_dir: str):
        self.base_dir = os.path.join(base_dir, DIR)
        os.makedirs(self.base_dir, exist_ok=True)
        super().__init__(os.path.join(self.base_dir, DB_FILE), seed=False)
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()
        self.seed_catalog()

    # ------------------------------------------------------------- catálogo
    def seed_catalog(self) -> None:
        if self.get_setting("scout_catalog_v1"):
            return
        for section, rows in CATALOG.items():
            for name, sci, kind in rows:
                self.execute("INSERT OR IGNORE INTO scout_species(section, name, scientific, kind, created_at) "
                             "VALUES (?,?,?,?,?)", (section, name, sci, kind, _now()))
        self.set_setting("scout_catalog_v1", True)

    def species(self, section: str, unidentified: bool | None = None) -> list[dict]:
        """Especies de la sección con sus conteos ("records", "photos"), las con más fotos
        primero (después por nombre)."""
        sql = ("SELECT s.*, (SELECT COUNT(*) FROM scout_records r WHERE r.species_id = s.id) AS records, "
               "(SELECT COUNT(*) FROM scout_photos p JOIN scout_records r ON r.id = p.record_id "
               " WHERE r.species_id = s.id) AS photos FROM scout_species s WHERE s.section=? AND s.active=1")
        params: list = [section]
        if unidentified is not None:
            sql += " AND s.unidentified=?"
            params.append(int(unidentified))
        return self.query(sql + " ORDER BY photos DESC, s.name COLLATE NOCASE", tuple(params))

    def get_species(self, species_id: int) -> dict | None:
        return self.query_one("SELECT * FROM scout_species WHERE id=?", (species_id,))

    def add_species(self, section: str, name: str, scientific: str = "", kind: str = "",
                    notes: str = "") -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Escriba el nombre de la especie.")
        if re.match(r"(?i)^NI-\d+$", name):
            raise ValueError("«NI-…» es el código de las no identificadas.")
        old = self.query_one("SELECT * FROM scout_species WHERE section=? AND name=?", (section, name))
        if old:
            if not old["active"]:
                self.execute("UPDATE scout_species SET active=1 WHERE id=?", (old["id"],))
                return old["id"]
            raise ValueError(f"«{name}» ya está en el catálogo.")
        cur = self.execute("INSERT INTO scout_species(section, name, scientific, kind, notes, created_at) "
                           "VALUES (?,?,?,?,?,?)", (section, name, (scientific or "").strip(), kind,
                                                    (notes or "").strip(), _now()))
        self.log("create", "scout_species", cur.lastrowid, f"{section}: {name}")
        return cur.lastrowid

    def update_species(self, species_id: int, scientific: str | None = None, notes: str | None = None,
                       kind: str | None = None) -> None:
        for col, val in (("scientific", scientific), ("notes", notes), ("kind", kind)):
            if val is not None:
                self.execute(f"UPDATE scout_species SET {col}=? WHERE id=?", ((val or "").strip(), species_id))

    def new_unidentified(self, section: str) -> int:
        """Nueva «No identificada» con el código siguiente (NI-001, NI-002…, por sección)."""
        n = 0
        for r in self.query("SELECT name FROM scout_species WHERE section=? AND unidentified=1", (section,)):
            m = re.match(r"NI-(\d+)", r["name"])
            if m:
                n = max(n, int(m[1]))
        name = f"NI-{n + 1:03d}"
        cur = self.execute("INSERT INTO scout_species(section, name, unidentified, created_at) VALUES (?,?,1,?)",
                           (section, name, _now()))
        return cur.lastrowid

    # ------------------------------------------------------------- capturas
    def add_record(self, section: str, species_id: int, stage: str = "", organ: str = "",
                   abundance: str = "", crop: str = "", place_kind: str = "", place: str = "",
                   place_code: str = "", sector: str = "", notes: str = "",
                   latitude: float | None = None, longitude: float | None = None,
                   taken_at: str | None = None) -> int:
        if section not in SECTIONS:
            raise ValueError("Sección desconocida.")
        if not self.get_species(species_id):
            raise ValueError("Elija la especie (o «No identificada»).")
        cur = self.execute(
            "INSERT INTO scout_records(section, species_id, stage, organ, abundance, crop, place_kind, place, "
            "place_code, sector, notes, latitude, longitude, taken_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (section, species_id, stage, organ, abundance, crop, place_kind, place, place_code, sector,
             (notes or "").strip(), latitude, longitude, taken_at or _now(), _now()))
        return cur.lastrowid

    def get_record(self, record_id: int) -> dict | None:
        return self.query_one("SELECT * FROM scout_records WHERE id=?", (record_id,))

    def records(self, species_id: int) -> list[dict]:
        rows = self.query("SELECT * FROM scout_records WHERE species_id=? ORDER BY taken_at DESC", (species_id,))
        for r in rows:
            r["photos"] = self.photos(r["id"])
        return rows

    def photos(self, record_id: int) -> list[dict]:
        return self.query("SELECT * FROM scout_photos WHERE record_id=? ORDER BY id", (record_id,))

    def photo_dir(self, section: str) -> str:
        path = os.path.join(self.base_dir, "fotos", section)
        os.makedirs(path, exist_ok=True)
        return path

    def photo_basename(self, record: dict, crop_code: str = "") -> str:
        """«20261102_MZ_Correhuela_Floracion_FR» (fecha, sección, especie, estadio, cultivo)."""
        sp = self.get_species(record["species_id"])
        day = (record.get("taken_at") or _now())[:10].replace("-", "")
        parts = [day, SECTIONS[record["section"]][2], slug(sp["name"]), slug(record.get("stage") or "")]
        if crop_code:
            parts.append(crop_code)
        return "_".join(p for p in parts if p and p != "x")

    def remote_name(self, record: dict, path: str) -> str:
        """Ruta en Drive (dentro de «AeonCrop/AeonScout»)."""
        sp = self.get_species(record["species_id"])
        sec = SECTIONS[record["section"]][1]
        who = f"{UNIDENTIFIED}/{sp['name']}" if sp["unidentified"] else folder_name(sp["name"])
        stage = folder_name(record.get("stage") or "Sin estadio")
        return f"{sec}/{who}/{stage}/{os.path.basename(path)}"

    def add_photo(self, record_id: int, path: str, view: str = "", enqueue: bool = True) -> int:
        """Agrega la foto (ya guardada en photo_dir) a la captura y la deja en la cola de Drive."""
        rec = self.get_record(record_id)
        queue_id = None
        if enqueue:
            queue_id = self.execute("INSERT INTO drive_queue(photo_id, path, name, created_at) VALUES (NULL,?,?,?)",
                                    (path, self.remote_name(rec, path), _now())).lastrowid
        cur = self.execute("INSERT INTO scout_photos(record_id, path, view, queue_id, created_at) "
                           "VALUES (?,?,?,?,?)", (record_id, path, view, queue_id, _now()))
        return cur.lastrowid

    def delete_record(self, record_id: int) -> None:
        """Borra la captura y sus fotos del teléfono (en Drive quedan)."""
        for p in self.photos(record_id):
            if p["queue_id"]:
                self.execute("UPDATE drive_queue SET status='skipped', error='Captura eliminada' "
                             "WHERE id=? AND status='pending'", (p["queue_id"],))
            try:
                os.remove(p["path"])
            except OSError:
                pass
        self.execute("DELETE FROM scout_records WHERE id=?", (record_id,))

    def missing_view(self, section: str, species_id: int) -> str | None:
        """La vista (dorsal, hoja envés…) con menos fotos de la especie: la que conviene sacar."""
        have = {r["view"]: r["n"] for r in self.query(
            "SELECT p.view, COUNT(*) AS n FROM scout_photos p JOIN scout_records r ON r.id = p.record_id "
            "WHERE r.species_id=? GROUP BY p.view", (species_id,))}
        views = VIEWS.get(section, [])
        return min(views, key=lambda v: have.get(v, 0)) if views else None

    # ------------------------------------------------------------- identificar
    def identify(self, ni_id: int, species_id: int) -> dict:
        """La no identificada `ni_id` resultó ser `species_id`: sus capturas y fotos pasan a
        esa especie; en Drive, las fotos ya subidas se MUEVEN a la carpeta de la especie
        (estado «move» en la cola, ver ScoutDrive) y las pendientes suben directo allá."""
        ni, sp = self.get_species(ni_id), self.get_species(species_id)
        if not ni or not ni["unidentified"]:
            raise ValueError("Solo se identifica una «No identificada».")
        if not sp or sp["unidentified"] or sp["section"] != ni["section"]:
            raise ValueError("Elija una especie del catálogo de la misma sección.")
        recs = self.query("SELECT * FROM scout_records WHERE species_id=?", (ni_id,))
        self.execute("UPDATE scout_records SET species_id=? WHERE species_id=?", (species_id, ni_id))
        n_photos = 0
        for rec in recs:
            rec = self.get_record(rec["id"])
            for p in self.photos(rec["id"]):
                n_photos += 1
                new_path = p["path"]
                base = os.path.basename(p["path"])
                if ni["name"] in base:     # el nombre del archivo lleva la especie
                    cand = os.path.join(os.path.dirname(p["path"]), base.replace(ni["name"], slug(sp["name"])))
                    if not os.path.exists(cand):
                        try:
                            os.rename(p["path"], cand)
                            new_path = cand
                        except OSError:
                            pass
                if new_path != p["path"]:
                    self.execute("UPDATE scout_photos SET path=? WHERE id=?", (new_path, p["id"]))
                if not p["queue_id"]:
                    continue
                q = self.query_one("SELECT * FROM drive_queue WHERE id=?", (p["queue_id"],))
                if not q:
                    continue
                remote = self.remote_name(rec, new_path)
                status = "move" if q["status"] == "done" and q["drive_id"] else q["status"]
                self.execute("UPDATE drive_queue SET path=?, name=?, status=? WHERE id=?",
                             (new_path, remote, status, q["id"]))
        self.execute("UPDATE scout_species SET active=0 WHERE id=?", (ni_id,))
        self.log("update", "scout_identify", species_id, f"{ni['name']} -> {sp['name']}: {n_photos} fotos")
        return {"records": len(recs), "photos": n_photos}

    # ------------------------------------------------------------- resumen
    def counts(self) -> dict:
        """{sección: {"species", "records", "photos", "pending"}} (pending = no identificadas)."""
        out = {}
        for sec in SECTIONS:
            row = self.query_one(
                "SELECT COUNT(DISTINCT r.id) AS records, COUNT(p.id) AS photos FROM scout_records r "
                "LEFT JOIN scout_photos p ON p.record_id = r.id WHERE r.section=?", (sec,))
            sp = self.query_one("SELECT COUNT(*) AS n FROM scout_species WHERE section=? AND active=1 "
                                "AND unidentified=0", (sec,))["n"]
            pend = self.query_one("SELECT COUNT(*) AS n FROM scout_species s WHERE section=? AND active=1 "
                                  "AND unidentified=1 AND EXISTS (SELECT 1 FROM scout_records r "
                                  "WHERE r.species_id = s.id)", (sec,))["n"]
            out[sec] = {"species": sp, "records": row["records"], "photos": row["photos"], "pending": pend}
        return out

    def stage_counts(self, species_id: int) -> dict[str, int]:
        """Fotos por estadio de una especie (para el avance hacia la meta)."""
        return {r["stage"] or "Sin estadio": r["n"] for r in self.query(
            "SELECT r.stage, COUNT(p.id) AS n FROM scout_records r JOIN scout_photos p ON p.record_id = r.id "
            "WHERE r.species_id=? GROUP BY r.stage", (species_id,))}

    def export_csv(self, path: str | None = None) -> str:
        """Todas las capturas en una planilla (una fila por foto): respaldo y base del
        conjunto de entrenamiento."""
        path = path or os.path.join(self.base_dir, "registro.csv")
        rows = self.query(
            "SELECT r.*, s.name AS species, s.scientific, s.unidentified, p.path, p.view FROM scout_records r "
            "JOIN scout_species s ON s.id = r.species_id LEFT JOIN scout_photos p ON p.record_id = r.id "
            "ORDER BY r.taken_at, p.id")
        cols = [("Fecha", "taken_at"), ("Sección", "section"), ("Especie", "species"),
                ("Nombre científico", "scientific"), ("Estadio", "stage"), ("Órgano", "organ"),
                ("Abundancia", "abundance"), ("Cultivo", "crop"), ("Tipo de lugar", "place_kind"),
                ("Lugar", "place"), ("Código", "place_code"), ("Sector", "sector"), ("Latitud", "latitude"),
                ("Longitud", "longitude"), ("Vista", "view"), ("Foto", "path"), ("Notas", "notes")]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([h for h, _k in cols])
            for r in rows:
                vals = []
                for _h, k in cols:
                    v = r.get(k)
                    if k == "path" and v:
                        v = os.path.basename(v)
                    if k == "section":
                        v = SECTIONS.get(v, (v,))[0]
                    vals.append("" if v is None else v)
                w.writerow(vals)
        return path


# ----------------------------------------------------------------- dónde (cultivo y lugar)
def places(base_dir: str, crop_id: str) -> list[dict]:
    """Ensayos y predios del cultivo (sin abrir su módulo: se leen sus bases en modo
    lectura). [{"kind": "ensayo"|"predio", "name", "code", "file"}]."""
    import crops
    crop = crops.get(crop_id)
    root = os.path.join(base_dir, crop.subdir) if crop.subdir else base_dir
    common = os.path.join(root, "comun.sqlite3")
    if not os.path.exists(common):
        return []
    try:
        con = sqlite3.connect(f"file:{common}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM workspaces WHERE archived=0 ORDER BY profile, sort_order, id").fetchall()
        con.close()
    except sqlite3.Error:
        return []
    return [{"kind": "predio" if r["profile"] == "predio" else "ensayo", "name": r["name"], "code": r["code"],
             "file": os.path.join(root, r["file"])} for r in rows]


def sectors(place: dict) -> list[str]:
    """Sectores o unidades de un predio (o parcelas/variedades de un ensayo)."""
    path = place.get("file") or ""
    if not os.path.exists(path):
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cols = {r[1] for r in con.execute("PRAGMA table_info(varieties)")}
        where = "active=1" + (" AND pheno_unit=0" if "pheno_unit" in cols else "")
        rows = [dict(r) for r in con.execute(f"SELECT * FROM varieties WHERE {where} ORDER BY sort_order, name")]
        con.close()
    except sqlite3.Error:
        return []
    import phenology as ph
    out = []
    for v in rows:
        if place["kind"] == "predio" and (v.get("sector") or v.get("irrigation")):
            label = ph.unit_place(v) or v["name"]
            label = f"{label} · {ph.unit_main(v)}" if ph.is_unit(v) else label
            out.append(label[:1].upper() + label[1:])
        else:
            out.append(v["name"])
    return out


# ----------------------------------------------------------------- Drive
class ScoutDrive:
    """Respaldo en Drive de AeonScout: la cola de fotos (DriveBackup con la carpeta
    «AeonCrop/AeonScout»), las fotos que se mueven al identificar y la planilla."""

    def __init__(self, db: ScoutDB, backup=None):
        self.db = db
        if backup is None:
            from drive_backup import DriveBackup
            backup = DriveBackup(db, crop=MODULE)
        self.backup = backup

    @property
    def enabled(self) -> bool:
        return self.backup.enabled

    def move_pending(self) -> int:
        """Fotos ya subidas cuya especie cambió (identificadas): se mueven y renombran en
        Drive (nada se vuelve a subir)."""
        n = 0
        for r in self.db.query("SELECT * FROM drive_queue WHERE status='move'"):
            try:
                self.backup.move_file(r["drive_id"], r["name"])
                self.db.execute("UPDATE drive_queue SET status='done' WHERE id=?", (r["id"],))
                n += 1
            except Exception as exc:  # noqa: BLE001 (sin red: se reintenta la próxima vez)
                if getattr(exc, "status", None) in (403, 404):   # ya no está: se sube de nuevo
                    self.db.execute("UPDATE drive_queue SET status='pending', drive_id=NULL WHERE id=?", (r["id"],))
                else:
                    break
        return n

    def run(self) -> int:
        """Mueve, sube lo pendiente y reemplaza «registro.csv». Devuelve fotos subidas."""
        if not self.enabled:
            return 0
        self.move_pending()
        n = self.backup.flush()
        try:
            self.backup.put_file(self.db.export_csv(), "registro.csv")
        except Exception:  # noqa: BLE001 (la planilla se repone en la próxima subida)
            pass
        return n
