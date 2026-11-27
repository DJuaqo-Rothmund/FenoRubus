"""
plantas.py
==========
Módulo «Plantas»: cada planta de un ensayo con su ficha (como la de un paciente).

* **Hileras del campo** (`assets/maps/<predio>_hileras.json`, hecho con
  tools/make_rows.py desde el plano DWG/DXF y la planilla de código de hileras): número,
  sector, equipo, N/S, largo, plantas teóricas, variedad y año. Lo que se corrige en la app
  (número, subtítulo N/S/A/B, largo, plantas…, unir tramos, quitar repetidas) queda en
  `field_row_edits` encima del dato teórico y se sincroniza.
* **Ensayos de plantas**: sus hileras, y en cada hilera sus hoyos de sur (0 m) a norte
  (assets/plantas/<código>.json, de la hoja «Mapeo», tools/make_trial_plants.py). Cada hoyo
  es una planta, una falla, una separación o una planta eliminada; los drenajes son los
  huecos entre posiciones. El número de cada planta va dentro de su tramo (variedad ·
  bloque) y una falla no corre la numeración de las demás.
* **Historial** de cada planta: eventos (enfermedad, plaga, daño mecánico, planta muerta,
  replante, poda, nota) con severidad, nombre (con sugerencias para escribir siempre igual
  «Botrytis») y fotos; y mediciones (cañas, primocañas, laterales, largo de laterales,
  rendimiento) por fecha o por temporada.

Base propia por cultivo («plantas/plantas.sqlite3» en la carpeta de datos del cultivo),
sincronizada entre equipos por paquetes en «AeonCrop/<módulo>/Plantas/Sincronización»; las
fotos van a «…/Plantas/<ensayo>/<hilera>-P<n>/». Puro Python (sin Kivy).
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import os
import re
import unicodedata
from pathlib import Path

from database import Database

DIR = "plantas"
DB_FILE = "plantas.sqlite3"
DRIVE_DIR = "Plantas"
SYNC_DIR = "Sincronización"
ASSETS = Path(__file__).resolve().parent / "assets"
SPACING = .7                       # m entre hoyos (plantas teóricas = largo ÷ 0,7)

EVENT_KINDS = [                    # (clave, nombre, ícono, color)
    ("enfermedad", "Enfermedad", "virus-outline", "#8E24AA"),
    ("plaga", "Plaga", "bug-outline", "#E65100"),
    ("dano", "Daño mecánico", "hammer-wrench", "#6D4C41"),
    ("muerta", "Planta muerta", "skull-outline", "#37474F"),
    ("replante", "Replante", "sprout-outline", "#2E7D32"),
    ("poda", "Poda", "content-cut", "#00838F"),
    ("nota", "Nota", "note-text-outline", "#546E7A"),
]
KIND_NAME = {k: n for k, n, _i, _c in EVENT_KINDS}
NAMED_KINDS = ("enfermedad", "plaga", "dano")        # llevan nombre (con sugerencias)
SEVERITY = ["", "Leve", "Moderada", "Severa"]
BASE_NAMES = {
    "enfermedad": ["Botrytis", "Phytophthora", "Agrobacterium", "Roya", "Oídio", "Antracnosis",
                   "Verticilium", "Didymella", "Virus"],
    "plaga": ["Arañita roja", "Burrito", "Pulgón", "Trips", "Cabrito", "Drosophila suzukii",
              "Chanchito blanco", "Gusano blanco"],
    "dano": ["Máquina", "Viento", "Helada", "Granizo", "Conejo", "Riego"],
}
MEASURES = [                       # (clave, nombre, unidad, decimales)
    ("canas", "Cañas (floricañas)", "", 0),
    ("primocanas", "Primocañas", "", 0),
    ("lat_arriba", "Laterales arriba", "", 0),
    ("lat_abajo", "Laterales abajo", "", 0),
    ("largo_lat", "Largo de laterales", "cm", 1),
    ("rend", "Rendimiento", "kg", 2),
]
HOLE_KINDS = {"planta": "Planta", "falla": "Falla (hoyo vacío)", "separacion": "Separación",
              "eliminada": "Eliminada"}
SUBTITLES = ["", "N", "S", "A", "B"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS field_row_edits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    predio      TEXT NOT NULL,
    row_key     TEXT NOT NULL,
    n           INTEGER,
    ns          TEXT,                       -- subtítulo: N, S, A, B…
    sector      INTEGER,
    equipo      INTEGER,
    largo       REAL,
    plantas     INTEGER,
    variedad    TEXT,
    anio        TEXT,
    estado      TEXT NOT NULL DEFAULT '',   -- '' | ok (revisada) | dup | no (no es hilera) | unida
    unida_a     TEXT NOT NULL DEFAULT '',   -- clave de la hilera con la que se unió
    nota        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL,
    UNIQUE (predio, row_key)
);
CREATE TABLE IF NOT EXISTS plant_trials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    predio      TEXT NOT NULL DEFAULT '',
    spacing     REAL NOT NULL DEFAULT 0.7,
    color       TEXT NOT NULL DEFAULT '#E0306A',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plant_rows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id    INTEGER NOT NULL REFERENCES plant_trials(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,              -- H1, H2…
    field_key   TEXT NOT NULL DEFAULT '',   -- hilera del campo (AM_hileras.json)
    field_n     INTEGER,
    sector      INTEGER,
    equipo      INTEGER,
    largo       REAL,
    segments    TEXT NOT NULL DEFAULT '[]', -- tramos del Mapeo (para mostrar drenajes)
    ord         INTEGER NOT NULL DEFAULT 0,
    UNIQUE (trial_id, label)
);
CREATE TABLE IF NOT EXISTS plants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id      INTEGER NOT NULL REFERENCES plant_rows(id) ON DELETE CASCADE,
    hoyo        INTEGER NOT NULL,
    pos         REAL NOT NULL,              -- m desde la cabecera sur
    kind        TEXT NOT NULL DEFAULT 'planta',
    variety     TEXT NOT NULL DEFAULT '',
    bloque      INTEGER NOT NULL DEFAULT 0,
    num         INTEGER NOT NULL DEFAULT 0, -- número dentro de su tramo (variedad · bloque)
    status      TEXT NOT NULL DEFAULT '',   -- '' (viva) | muerta | replante
    tag         TEXT NOT NULL DEFAULT '',   -- etiqueta física, si tiene
    note        TEXT NOT NULL DEFAULT '',
    UNIQUE (row_id, hoyo)
);
CREATE INDEX IF NOT EXISTS idx_plants_row ON plants(row_id, pos);
CREATE TABLE IF NOT EXISTS plant_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id    INTEGER NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    severity    INTEGER NOT NULL DEFAULT 0,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plant_events ON plant_events(plant_id, day);
CREATE TABLE IF NOT EXISTS plant_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES plant_events(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    queue_id    INTEGER,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plant_measures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id    INTEGER NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,              -- aaaa-mm-dd, o «T2025-26» (toda la temporada)
    canas       REAL, primocanas REAL, lat_arriba REAL, lat_abajo REAL, largo_lat REAL, rend REAL,
    note        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL,
    UNIQUE (plant_id, day)
);
"""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return _dt.date.today().isoformat()


def season_of(day: str | None = None) -> str:
    """Temporada de frambuesa (mayo a abril): «2025-26»."""
    d = _dt.date.fromisoformat(day) if day and not day.startswith("T") else _dt.date.today()
    y = d.year if d.month >= 5 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def fold(text: str) -> str:
    """Para comparar nombres: sin tildes, mayúsculas ni espacios de más."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t).strip().lower()


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", fold(text).title()) or "x"


# ------------------------------------------------------------------ hileras del campo (plano)
_FIELD: dict = {}


def load_field(predio: str) -> dict | None:
    """Hileras del plano: {"rows": [dict…], "by_key": {}, "spacing"} o None si no hay."""
    predio = (predio or "").upper()
    if predio not in _FIELD:
        path = ASSETS / "maps" / f"{predio}_hileras.json"
        if not path.exists():
            _FIELD[predio] = None
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
            names = raw["fields"]
            rows = [dict(zip(names, r)) for r in raw["rows"]]
            _FIELD[predio] = {"rows": rows, "by_key": {r["key"]: r for r in rows},
                              "spacing": raw.get("spacing", SPACING), "name": raw.get("name", "")}
    return _FIELD[predio]


def trial_assets() -> list[dict]:
    """Ensayos incluidos en la app (assets/plantas/*.json), sin sus plantas."""
    out = []
    for p in sorted((ASSETS / "plantas").glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"code": d["code"], "name": d["name"], "predio": d.get("predio", ""),
                        "path": str(p), "rows": [r["label"] for r in d["rows"]]})
        except Exception:  # noqa: BLE001
            continue
    return out


class PlantDB(Database):
    """Base del módulo Plantas de un cultivo (con la maquinaria común: ajustes y cola de Drive)."""

    def __init__(self, data_dir: str, crop_id: str = "frambuesa"):
        self.base_dir = os.path.join(data_dir, DIR)
        self.crop_id = crop_id
        os.makedirs(self.base_dir, exist_ok=True)
        super().__init__(os.path.join(self.base_dir, DB_FILE), seed=False)
        with self._lock:
            self.conn.executescript(SCHEMA)
            import sync
            sync.install(self.conn)
            self.conn.commit()

    @property
    def photo_dir(self) -> str:
        d = os.path.join(self.base_dir, "fotos")
        os.makedirs(d, exist_ok=True)
        return d

    # ============================================================ hileras del campo
    def row_edits(self, predio: str) -> dict:
        return {r["row_key"]: r for r in self.query("SELECT * FROM field_row_edits WHERE predio=?",
                                                    (predio.upper(),))}

    def field_rows(self, predio: str) -> list[dict]:
        """Hileras del plano con lo corregido encima. Cada una: key, n, ns, s, e, L, pl, var,
        anio, x0, y0, x1, y1 (metros del plano del predio), estado, rev (por revisar),
        hidden (repetida, no es hilera o unida a otra), edited, trial (código o '')."""
        f = load_field(predio)
        if not f:
            return []
        edits = self.row_edits(predio)
        trial_of = {r["field_key"]: r["code"] for r in self.query(
            "SELECT r.field_key, t.code FROM plant_rows r JOIN plant_trials t ON t.id=r.trial_id")}
        out = []
        for base in f["rows"]:
            r = dict(base)
            ed = edits.get(r["key"])
            r["edited"] = bool(ed)
            r["estado"] = ""
            r["nota"] = ""
            if ed:
                for col, k in (("n", "n"), ("ns", "ns"), ("sector", "s"), ("equipo", "e"),
                               ("largo", "L"), ("plantas", "pl"), ("variedad", "var"), ("anio", "anio")):
                    if ed[col] is not None:
                        r[k] = ed[col]
                r["estado"], r["nota"], r["unida_a"] = ed["estado"], ed["nota"], ed["unida_a"]
            r["hidden"] = r["estado"] in ("dup", "no", "unida")
            r["rev"] = r["flag"] in (1, 2) and r["estado"] == ""
            r["trial"] = trial_of.get(r["key"], "")
            r["label"] = f"{r['n']}{(' ' + r['ns']) if r['ns'] else ''}"
            out.append(r)
        return out

    def field_row(self, predio: str, key: str) -> dict | None:
        return next((r for r in self.field_rows(predio) if r["key"] == key), None)

    def edit_row(self, predio: str, key: str, **fields) -> None:
        """Corrige una hilera del campo (solo lo que se pasa; None deja el dato del plano)."""
        allowed = ("n", "ns", "sector", "equipo", "largo", "plantas", "variedad", "anio", "estado",
                   "unida_a", "nota")
        sets = {k: v for k, v in fields.items() if k in allowed}
        predio = predio.upper()
        cur = self.query_one("SELECT id FROM field_row_edits WHERE predio=? AND row_key=?", (predio, key))
        if cur:
            if sets:
                self.execute(f"UPDATE field_row_edits SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? "
                             "WHERE id=?", (*sets.values(), _now(), cur["id"]))
        else:
            cols = ["predio", "row_key", "updated_at", *sets]
            self.execute(f"INSERT INTO field_row_edits({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         (predio, key, _now(), *sets.values()))

    def undo_row(self, predio: str, key: str) -> None:
        """Vuelve al dato del plano y la planilla."""
        self.execute("DELETE FROM field_row_edits WHERE predio=? AND row_key=?", (predio.upper(), key))

    def remove_duplicates(self, predio: str) -> int:
        """Marca como repetidas todas las copias (misma línea dibujada dos veces en el plano)."""
        n = 0
        with self.batch():
            for r in self.field_rows(predio):
                if r["flag"] == 2 and r["estado"] == "":
                    self.edit_row(predio, r["key"], estado="dup")
                    n += 1
        return n

    def merge_rows(self, predio: str, key: str, other: str) -> dict:
        """Une dos tramos de la misma hilera (cortada por un obstáculo): la primera suma el
        largo de la otra (con plantas) y la otra queda «unida». Devuelve la hilera unida."""
        rows = {r["key"]: r for r in self.field_rows(predio)}
        a, b = rows[key], rows[other]
        largo = round(float(a["L_plano"]) + float(b["L_plano"]), 1)
        with self.batch():
            self.edit_row(predio, key, largo=largo, plantas=int(round(largo / SPACING)), estado="ok",
                          nota=(f"Unida con el tramo de {fmt(b['L_plano'])} m"))
            self.edit_row(predio, other, estado="unida", unida_a=key)
        return self.field_row(predio, key)

    def neighbors(self, predio: str, key: str) -> list[dict]:
        """Tramos de la misma columna (mismo número en el plano), de sur a norte, sin la propia."""
        base = load_field(predio)["by_key"]
        rows = [r for r in self.field_rows(predio) if not r["hidden"]]
        me = next((r for r in rows if r["key"] == key), None)
        if not me:
            return []
        n = base[key]["n"]                 # la columna del plano (aunque se corrija el número)
        return sorted([r for r in rows if r["key"] != key and base[r["key"]]["n"] == n
                       and abs(r["x0"] - me["x0"]) < 3], key=lambda r: r["y0"])

    # ============================================================ ensayos y plantas
    def trials(self) -> list[dict]:
        out = []
        for t in self.query("SELECT * FROM plant_trials ORDER BY name"):
            n = self.query_one("SELECT COUNT(*) AS n FROM plants p JOIN plant_rows r ON r.id=p.row_id "
                               "WHERE r.trial_id=? AND p.kind='planta' AND p.status<>'muerta'", (t["id"],))
            out.append(dict(t, plants=n["n"]))
        return out

    def trial(self, trial_id: int) -> dict | None:
        return self.query_one("SELECT * FROM plant_trials WHERE id=?", (trial_id,))

    def import_trial(self, path: str) -> int:
        """Arma un ensayo desde su JSON (tools/make_trial_plants.py). Si ya existe, agrega solo
        lo que falte (no pisa correcciones). Devuelve el id del ensayo."""
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        with self.batch():
            t = self.query_one("SELECT id FROM plant_trials WHERE code=?", (d["code"],))
            tid = t["id"] if t else self.execute(
                "INSERT INTO plant_trials(code, name, predio, spacing, created_at) VALUES (?,?,?,?,?)",
                (d["code"], d["name"], d.get("predio", ""), d.get("spacing", SPACING), _now())).lastrowid
            for i, r in enumerate(d["rows"]):
                row = self.query_one("SELECT id FROM plant_rows WHERE trial_id=? AND label=?", (tid, r["label"]))
                rid = row["id"] if row else self.execute(
                    "INSERT INTO plant_rows(trial_id, label, field_key, field_n, sector, equipo, largo, segments, ord) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (tid, r["label"], r["field_key"], r["field_n"], r["sector"], r["equipo"], r["largo"],
                     json.dumps(r.get("segments", []), ensure_ascii=False), i)).lastrowid
                have = {x["hoyo"] for x in self.query("SELECT hoyo FROM plants WHERE row_id=?", (rid,))}
                for hoyo, pos, kind, var, bloque, num in r["holes"]:
                    if hoyo not in have:
                        self.execute("INSERT INTO plants(row_id, hoyo, pos, kind, variety, bloque, num) "
                                     "VALUES (?,?,?,?,?,?,?)", (rid, hoyo, pos, kind, var or "", bloque or 0, num or 0))
                # El largo y las plantas contadas quedan como dato real de la hilera del campo.
                if d.get("predio") and r.get("field_key"):
                    self.edit_row(d["predio"], r["field_key"], largo=r["largo"], plantas=r["plantas"],
                                  variedad=f"Ensayo {d['name']}", estado="ok")
        return tid

    def rows_of(self, trial_id: int) -> list[dict]:
        out = []
        for r in self.query("SELECT * FROM plant_rows WHERE trial_id=? ORDER BY ord, label", (trial_id,)):
            r["segments"] = json.loads(r["segments"] or "[]")
            out.append(r)
        return out

    def plants_of(self, row_id: int) -> list[dict]:
        return self.query("SELECT * FROM plants WHERE row_id=? ORDER BY pos, hoyo", (row_id,))

    def plant(self, plant_id: int) -> dict | None:
        p = self.query_one("SELECT p.*, r.label, r.field_n, r.sector, r.equipo, r.trial_id, r.largo AS row_largo "
                           "FROM plants p JOIN plant_rows r ON r.id=p.row_id WHERE p.id=?", (plant_id,))
        return p

    def plant_title(self, p: dict) -> str:
        """«522 · W·B1 · P21» (hilera del campo, variedad corta, bloque, número)."""
        if p["kind"] != "planta":
            return f"{p.get('field_n') or p.get('label')} · hoyo {p['hoyo']}"
        return f"{p.get('field_n') or p.get('label')} · {short_var(p['variety'])}·B{p['bloque']} · P{p['num']}"

    def update_plant(self, plant_id: int, **fields) -> None:
        allowed = ("kind", "variety", "bloque", "num", "status", "tag", "note")
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            self.execute(f"UPDATE plants SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                         (*sets.values(), plant_id))

    def step(self, plant_id: int, direction: int) -> dict | None:
        """Planta siguiente (+1, hacia el norte) o anterior (-1) de la misma hilera, saltando
        fallas, separaciones y eliminadas (para el modo terreno)."""
        p = self.plant(plant_id)
        if not p:
            return None
        op, order = (">", "ASC") if direction > 0 else ("<", "DESC")
        return self.query_one(f"SELECT * FROM plants WHERE row_id=? AND kind='planta' AND pos {op} ? "
                              f"ORDER BY pos {order} LIMIT 1", (p["row_id"], p["pos"]))

    def find_plant(self, trial_id: int, label: str | None, variety: str | None, bloque: int | None,
                   num: int) -> dict | None:
        """Planta por número (modo terreno): dentro de su hilera y tramo si se indican."""
        sql = ("SELECT p.* FROM plants p JOIN plant_rows r ON r.id=p.row_id WHERE r.trial_id=? "
               "AND p.kind='planta' AND p.num=?")
        args: list = [trial_id, num]
        if label:
            sql += " AND r.label=?"
            args.append(label)
        if variety:
            sql += " AND p.variety=?"
            args.append(variety)
        if bloque:
            sql += " AND p.bloque=?"
            args.append(bloque)
        return self.query_one(sql + " ORDER BY r.ord, p.pos LIMIT 1", args)

    # ============================================================ eventos
    def names(self, kind: str) -> list[str]:
        """Nombres usados (los más frecuentes primero) y luego los de base."""
        used = [r["name"] for r in self.query(
            "SELECT name, COUNT(*) AS n FROM plant_events WHERE kind=? AND name<>'' GROUP BY name "
            "ORDER BY n DESC, name", (kind,))]
        seen = {fold(n) for n in used}
        return used + [n for n in BASE_NAMES.get(kind, []) if fold(n) not in seen]

    def suggest(self, kind: str, text: str, limit: int = 4) -> list[str]:
        """Sugerencias mientras se escribe: los que empiezan o contienen lo escrito, y los
        parecidos (errores de tipeo)."""
        t = fold(text)
        names = self.names(kind)
        if not t:
            return names[:limit]
        starts = [n for n in names if fold(n).startswith(t)]
        contains = [n for n in names if t in fold(n) and n not in starts]
        close = difflib.get_close_matches(t, [fold(n) for n in names], n=limit, cutoff=.6)
        similar = [n for n in names if fold(n) in close and n not in starts and n not in contains]
        return (starts + contains + similar)[:limit]

    def canonical(self, kind: str, text: str) -> tuple[str, str | None]:
        """(nombre a guardar, sugerencia): si ya existe escrito igual salvo tildes/mayúsculas,
        se usa ese; si se parece mucho a uno existente, se sugiere («¿Botrytis?»)."""
        text = re.sub(r"\s+", " ", (text or "").strip())
        if not text:
            return "", None
        names = self.names(kind)
        for n in names:
            if fold(n) == fold(text):
                return n, None
        close = difflib.get_close_matches(fold(text), [fold(n) for n in names], n=1, cutoff=.8)
        if close:
            return text, next(n for n in names if fold(n) == close[0])
        return text[:1].upper() + text[1:], None

    def add_event(self, plant_id: int, kind: str, name: str = "", severity: int = 0, note: str = "",
                  day: str | None = None) -> int:
        eid = self.execute("INSERT INTO plant_events(plant_id, day, kind, name, severity, note, created_at) "
                           "VALUES (?,?,?,?,?,?,?)",
                           (plant_id, day or today(), kind, name, int(severity or 0), note, _now())).lastrowid
        if kind == "muerta":
            self.update_plant(plant_id, status="muerta")
        elif kind == "replante":
            p = self.plant(plant_id)
            self.update_plant(plant_id, status="replante",
                              **({"kind": "planta"} if p and p["kind"] in ("falla", "eliminada") else {}))
        return eid

    def update_event(self, event_id: int, **fields) -> None:
        allowed = ("day", "kind", "name", "severity", "note")
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            self.execute(f"UPDATE plant_events SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                         (*sets.values(), event_id))

    def delete_event(self, event_id: int) -> None:
        for ph in self.photos(event_id):
            self._drop_photo(ph)
        self.execute("DELETE FROM plant_events WHERE id=?", (event_id,))

    def events(self, plant_id: int) -> list[dict]:
        return self.query("SELECT * FROM plant_events WHERE plant_id=? ORDER BY day DESC, id DESC", (plant_id,))

    # ------------------------------------------------------------------ fotos
    def folder(self, plant: dict) -> str:
        t = self.trial(plant["trial_id"]) if plant.get("trial_id") else None
        who = (f"{plant.get('field_n') or plant['label']}-P{plant['num']}" if plant["kind"] == "planta"
               else f"{plant.get('field_n') or plant['label']}-hoyo{plant['hoyo']}")
        return f"{DRIVE_DIR}/{(t or {}).get('name', 'Ensayo').replace('/', '-')}/{who}"

    def photo_basename(self, plant: dict, kind: str) -> str:
        """«20261127-NV-522-WB1P21-Botrytis»."""
        t = self.trial(plant["trial_id"]) or {}
        who = f"{short_var(plant['variety'])}B{plant['bloque']}P{plant['num']}" if plant["kind"] == "planta" \
            else f"h{plant['hoyo']}"
        return "-".join(p for p in (today().replace("-", ""), t.get("code", ""), str(plant.get("field_n") or ""),
                                    re.sub(r"[^A-Za-z0-9]", "", who), slug(kind)) if p)

    def add_photo(self, event_id: int, path: str, enqueue: bool = True) -> int:
        ev = self.query_one("SELECT * FROM plant_events WHERE id=?", (event_id,))
        queue_id = None
        if enqueue and ev:
            pl = self.plant(ev["plant_id"])
            queue_id = self.execute("INSERT INTO drive_queue(photo_id, path, name, created_at) VALUES (NULL,?,?,?)",
                                    (path, f"{self.folder(pl)}/{os.path.basename(path)}", _now())).lastrowid
        return self.execute("INSERT INTO plant_photos(event_id, path, queue_id, created_at) VALUES (?,?,?,?)",
                            (event_id, path, queue_id, _now())).lastrowid

    def photos(self, event_id: int) -> list[dict]:
        return self.query("SELECT * FROM plant_photos WHERE event_id=? ORDER BY id", (event_id,))

    def plant_photos(self, plant_id: int) -> list[dict]:
        return self.query("SELECT ph.* FROM plant_photos ph JOIN plant_events e ON e.id=ph.event_id "
                          "WHERE e.plant_id=? ORDER BY ph.id DESC", (plant_id,))

    def _drop_photo(self, p: dict) -> None:
        if p.get("queue_id"):
            self.execute("DELETE FROM drive_queue WHERE id=? AND status<>'done'", (p["queue_id"],))
        try:
            if p["path"] and os.path.exists(p["path"]):
                os.remove(p["path"])
        except OSError:
            pass
        self.execute("DELETE FROM plant_photos WHERE id=?", (p["id"],))

    # ============================================================ mediciones
    def set_measure(self, plant_id: int, day: str | None = None, note: str | None = None, **vals) -> None:
        """Guarda (o completa) la medición de una planta en una fecha («aaaa-mm-dd») o para toda
        la temporada («T2025-26»). Un valor None deja lo que había."""
        day = day or today()
        keys = [k for k, *_ in MEASURES if k in vals]
        cur = self.query_one("SELECT id FROM plant_measures WHERE plant_id=? AND day=?", (plant_id, day))
        if cur:
            sets = {k: vals[k] for k in keys}
            if note is not None:
                sets["note"] = note
            if sets:
                self.execute(f"UPDATE plant_measures SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? "
                             "WHERE id=?", (*sets.values(), _now(), cur["id"]))
        else:
            cols = ["plant_id", "day", "updated_at", *keys] + (["note"] if note is not None else [])
            self.execute(f"INSERT INTO plant_measures({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         (plant_id, day, _now(), *(vals[k] for k in keys), *([note] if note is not None else [])))

    def measure(self, plant_id: int, day: str) -> dict | None:
        return self.query_one("SELECT * FROM plant_measures WHERE plant_id=? AND day=?", (plant_id, day))

    def measures(self, plant_id: int) -> list[dict]:
        return self.query("SELECT * FROM plant_measures WHERE plant_id=? ORDER BY day DESC", (plant_id,))

    def delete_measure(self, measure_id: int) -> None:
        self.execute("DELETE FROM plant_measures WHERE id=?", (measure_id,))

    def last_values(self, trial_id: int, key: str) -> dict:
        """{plant_id: último valor} de una medición (para pintar el mapa)."""
        if key not in {k for k, *_ in MEASURES}:
            return {}
        rows = self.query(
            f"SELECT m.plant_id, m.{key} AS v, m.day FROM plant_measures m JOIN plants p ON p.id=m.plant_id "
            f"JOIN plant_rows r ON r.id=p.row_id WHERE r.trial_id=? AND m.{key} IS NOT NULL", (trial_id,))
        out: dict = {}
        for r in sorted(rows, key=lambda r: _day_order(r["day"])):
            out[r["plant_id"]] = r["v"]
        return out

    def last_events(self, trial_id: int) -> dict:
        """{plant_id: último evento} del ensayo (estado en el mapa)."""
        rows = self.query("SELECT e.* FROM plant_events e JOIN plants p ON p.id=e.plant_id "
                          "JOIN plant_rows r ON r.id=p.row_id WHERE r.trial_id=? ORDER BY e.day, e.id", (trial_id,))
        return {r["plant_id"]: r for r in rows}

    def history(self, plant_id: int) -> list[dict]:
        """Eventos y mediciones de la planta, lo más reciente primero."""
        items = [dict(e, _type="event", photos=self.photos(e["id"])) for e in self.events(plant_id)]
        items += [dict(m, _type="measure") for m in self.measures(plant_id)]
        items.sort(key=lambda x: (_day_order(x["day"]), x["id"]), reverse=True)
        return items

    def export_csv(self, trial_id: int, path: str) -> str:
        import csv
        t = self.trial(trial_id)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["Ensayo", "Hilera", "Hilera campo", "Hoyo", "Posición (m)", "Variedad", "Bloque", "Planta",
                        "Estado", "Fecha", "Tipo", "Nombre", "Severidad", "Nota",
                        *[n for _k, n, *_ in MEASURES]])
            for r in self.rows_of(trial_id):
                for p in self.plants_of(r["id"]):
                    base = [t["name"], r["label"], r["field_n"], p["hoyo"], str(p["pos"]).replace(".", ","),
                            p["variety"], p["bloque"], p["num"] if p["kind"] == "planta" else "",
                            p["status"] or HOLE_KINDS.get(p["kind"], p["kind"])]
                    for h in reversed(self.history(p["id"])):
                        if h["_type"] == "event":
                            w.writerow(base + [h["day"], KIND_NAME.get(h["kind"], h["kind"]), h["name"],
                                               SEVERITY[h["severity"]] if 0 <= h["severity"] < len(SEVERITY) else "",
                                               h["note"]] + [""] * len(MEASURES))
                        else:
                            w.writerow(base + [h["day"], "Medición", "", "", h["note"]] +
                                       [fmt(h[k], d) if h[k] is not None else "" for k, _n, _u, d in MEASURES])
        return path


def _day_order(day: str) -> str:
    """Las mediciones de temporada («T2025-26») van al final de su temporada."""
    if day and day.startswith("T"):
        y = int(day[1:5])
        return f"{y + 1}-04-30~"
    return day or ""


def short_var(name: str) -> str:
    """«Cascade Harvest» → CH, «Wakefield» → W, «#24» → 24."""
    name = (name or "").strip()
    if not name:
        return "?"
    if name.startswith("#"):
        return name[1:]
    words = [w for w in re.split(r"\s+", name) if w]
    return "".join(w[0].upper() for w in words) if len(words) > 1 else words[0][0].upper()


def fmt(v, d: int = 1) -> str:
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if d == 0 or float(v).is_integer() and d <= 1:
        return f"{int(round(v)):,}".replace(",", ".")
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


_OPEN: dict = {}


def open_db(data_dir: str, crop_id: str) -> PlantDB:
    key = (os.path.abspath(data_dir), crop_id)
    if key not in _OPEN:
        _OPEN[key] = PlantDB(data_dir, crop_id)
    return _OPEN[key]


class PlantDrive:
    """Respaldo en Drive de las fotos de las plantas (y las que cambiaron de carpeta)."""

    def __init__(self, db: PlantDB, backup=None, crop=None):
        self.db = db
        if backup is None:
            from drive_backup import DriveBackup
            backup = DriveBackup(db, crop=crop)
        self.backup = backup

    @property
    def enabled(self) -> bool:
        return self.backup.enabled

    def run(self) -> int:
        if not self.enabled:
            return 0
        return self.backup.flush()
