"""
database.py
===========
Persistencia local SQLite (offline-first) con trazabilidad.

Entidades
---------
varieties        Catálogo dinámico de variedades (CRUD, archivado suave).
variety_metrics  Parámetros biométricos por variedad y temporada.
custom_fields    Campos personalizados llave-valor por variedad y temporada.
variety_attachments  Fotos adjuntas a un registro semanal de la variedad (con descripción).
measures         Mediciones definidas por el usuario: registro de imágenes o planilla.
measure_entries  Imágenes o filas de planilla de cada medición, por semana.
sampling_weeks   Semanas de muestreo (Semana 1 = semana del 7 de septiembre).
observations     Registro fenológico variedad × semana (BBCH, IA, notas).
photos           Fotos asociadas a una observación (canopy / detail).
bbch_stages      Catálogo BBCH editable (enriquecible con documentos técnicos).
ai_references    Base de referencia del clasificador (embeddings etiquetados).
documents        Documentos técnicos cargados en el módulo de calibración.
settings         Preferencias (JSON).
audit_log        Bitácora de cambios (trazabilidad de campo).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import threading
from typing import Any, Iterable

import phenology as ph
from platform_utils import GLOBAL_KEYS, global_get, global_set

SCHEMA_VERSION = 3

DEFAULT_VARIETIES: list[tuple[str, str]] = [
    ("Código 11", "C11"),
    ("Código 31", "C31"),
    ("Código 24", "C24"),
    ("Código 55", "C55"),
    ("Código 81", "C81"),
    ("Cascade Harvest", "CH"),
    ("Lagorai", "LAG"),
    ("Meeker", "MEE"),
    ("Regina", "REG"),
    ("Wakefield", "WAK"),
]

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS varieties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    code        TEXT,
    sector      INTEGER,              -- opcional (1-10)
    irrigation  INTEGER,              -- equipo de riego, opcional (1-4)
    notes       TEXT DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variety_metrics (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    variety_id             INTEGER NOT NULL REFERENCES varieties(id) ON DELETE CASCADE,
    season                 INTEGER NOT NULL,
    historical_yield       REAL,
    historical_yield_unit  TEXT DEFAULT 'kg/planta',
    historical_note        TEXT DEFAULT '',
    projected_yield        REAL,
    projected_yield_unit   TEXT DEFAULT 'kg/planta',
    basal_canes            REAL,
    basal_canes_unit       TEXT DEFAULT 'por planta',
    laterals               REAL,
    laterals_unit          TEXT DEFAULT 'por caña',
    updated_at             TEXT NOT NULL,
    UNIQUE (variety_id, season)
);

CREATE TABLE IF NOT EXISTS custom_fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    variety_id  INTEGER NOT NULL REFERENCES varieties(id) ON DELETE CASCADE,
    season      INTEGER NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT DEFAULT '',
    unit        TEXT DEFAULT '',
    updated_at  TEXT NOT NULL,
    UNIQUE (variety_id, season, key)
);

CREATE TABLE IF NOT EXISTS variety_attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    variety_id   INTEGER NOT NULL REFERENCES varieties(id) ON DELETE CASCADE,
    season       INTEGER NOT NULL,
    path         TEXT NOT NULL,
    caption      TEXT DEFAULT '',
    source       TEXT DEFAULT 'camera',
    captured_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS treatments (     -- ensayos de tratamientos × repeticiones
    num          INTEGER PRIMARY KEY,         -- 1, 2, 3… (T1, T2, T3…)
    name         TEXT NOT NULL DEFAULT '',    -- opcional: «Testigo», «N 120 kg/ha»…
    description  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS measures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('images', 'table')),
    columns     TEXT NOT NULL DEFAULT '[]',     -- planilla: nombres de columnas (JSON)
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measure_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    measure_id  INTEGER NOT NULL REFERENCES measures(id) ON DELETE CASCADE,
    week_id     INTEGER NOT NULL REFERENCES sampling_weeks(id) ON DELETE CASCADE,
    variety_id  INTEGER REFERENCES varieties(id) ON DELETE SET NULL,
    path        TEXT,                           -- imagen
    caption     TEXT DEFAULT '',
    data        TEXT NOT NULL DEFAULT '{}',     -- fila de planilla {columna: valor}
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sampling_weeks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    season      INTEGER NOT NULL,
    week_number INTEGER NOT NULL,
    start_date  TEXT NOT NULL,
    label       TEXT NOT NULL,
    UNIQUE (season, week_number)
);

CREATE TABLE IF NOT EXISTS observations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    variety_id     INTEGER NOT NULL REFERENCES varieties(id) ON DELETE CASCADE,
    week_id        INTEGER NOT NULL REFERENCES sampling_weeks(id) ON DELETE CASCADE,
    bbch_code      INTEGER,
    bbch_label     TEXT DEFAULT '',
    ai_code        INTEGER,
    ai_confidence  REAL,
    ai_detail      TEXT DEFAULT '',
    ai_accepted    INTEGER,
    notes          TEXT DEFAULT '',
    observed_at    TEXT,
    latitude       REAL,              -- ubicación de la muestra (opcional)
    longitude      REAL,
    gps_accuracy   REAL,              -- metros
    gps_source     TEXT,              -- gps | foto | mapa
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (variety_id, week_id)
);

CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id  INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('canopy', 'detail')),
    path            TEXT NOT NULL,
    source          TEXT DEFAULT 'camera',
    captured_at     TEXT NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0   -- foto que aparece en los informes
);

CREATE TABLE IF NOT EXISTS drive_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id     INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    path         TEXT NOT NULL,
    name         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | done | error
    attempts     INTEGER NOT NULL DEFAULT 0,
    drive_id     TEXT,
    error        TEXT DEFAULT '',
    created_at   TEXT NOT NULL,
    uploaded_at  TEXT
);

CREATE TABLE IF NOT EXISTS challenges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    kind        TEXT NOT NULL,          -- capture | identify
    payload     TEXT NOT NULL,          -- JSON
    status      TEXT NOT NULL DEFAULT 'open',   -- open | done | skipped
    answer      TEXT DEFAULT '',
    correct     INTEGER,
    created_at  TEXT NOT NULL,
    UNIQUE (day, idx)
);

CREATE TABLE IF NOT EXISTS bbch_stages (
    code         INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    description  TEXT DEFAULT '',
    keywords     TEXT DEFAULT '',
    source       TEXT DEFAULT 'base'
);

CREATE TABLE IF NOT EXISTS ai_references (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bbch_code    INTEGER NOT NULL,
    extractor    TEXT NOT NULL,
    embedding    BLOB NOT NULL,
    dim          INTEGER NOT NULL,
    image_path   TEXT,
    photo_id     INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    path        TEXT,
    text        TEXT DEFAULT '',
    stages_found INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebook_entries (  -- cuaderno de campo: una página por día
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT NOT NULL UNIQUE,           -- AAAA-MM-DD
    text        TEXT NOT NULL DEFAULT '',
    ink         TEXT NOT NULL DEFAULT '',       -- escritura a mano (JSON, en renglones)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebook_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,                  -- la versión vigente (con dibujos si se anotó)
    caption     TEXT DEFAULT '',
    annotated   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    detail     TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_obs_week ON observations(week_id);
CREATE INDEX IF NOT EXISTS idx_obs_variety ON observations(variety_id);
CREATE INDEX IF NOT EXISTS idx_ref_code ON ai_references(bbch_code);
CREATE INDEX IF NOT EXISTS idx_photos_obs ON photos(observation_id, kind);
CREATE INDEX IF NOT EXISTS idx_drive_status ON drive_queue(status);
"""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class Database:
    """Acceso thread-safe (una conexión + lock) a la base SQLite local."""

    # Ajustes que valen para todo el teléfono (no para un ensayo): viven en la base
    # común cuando la hay (cuenta de Drive, PIN, recordatorio, informes…).
    SHARED_SETTING_PREFIXES = ("drive_", "report_", "ai_pin", "ai_auto_learn", "ai_game",
                               "ai_last_eval", "reminder",
                               "public_names", "last_workspace", "workspaces_", "user_name")

    def __init__(self, path: str, seed: bool = True, shared: "Database | None" = None,
                 code: str = "", workspace: dict | None = None, seed_crop: str | None = None):
        """shared: base común del teléfono (registro de ensayos, memoria de la IA, escala
        BBCH, documentos y ajustes globales). code / workspace: ensayo o predio de esta base."""
        self.path = path
        self.seed_crop = seed_crop        # cultivo de las variedades iniciales (None: el activo)
        self.shared = shared
        self.code = code
        self.workspace = workspace or {}
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        # WAL + NORMAL: escrituras mucho más rápidas en memorias flash lentas,
        # sin riesgo de corrupción (solo podría perderse la última transacción ante un corte).
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.init_schema()
        self._migrate_seasons_apr()
        self.renumber_weeks()              # repara semanas repetidas o desalineadas (ver ahí)
        with self._lock:
            import sync
            sync.install(self.conn)        # uid común + registro de cambios (celular ↔ PC)
            self.conn.commit()
        if seed:
            self.seed_defaults()
        if shared is None and seed:
            self.refresh_bbch_scale()
        self._remap_bbch_codes()

    # ------------------------------------------------------------------ core
    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def init_schema(self) -> None:
        with self._lock:
            self._migrate_photos_v2()
            self.conn.executescript(SCHEMA)
            self._add_missing_columns()
            self.conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),))
            self.conn.commit()

    NEW_COLUMNS = {  # v3: columnas opcionales agregadas a tablas existentes
        "varieties": [("sector", "INTEGER"), ("irrigation", "INTEGER"),
                      ("treatment", "INTEGER"), ("rep", "INTEGER"),   # parcela T1R1…
                      ("cultivar", "TEXT"),                           # predio: variedad de la unidad
                      ("plant_year", "INTEGER"),                      # predio: año de plantación
                      ("pheno_unit", "INTEGER NOT NULL DEFAULT 0")],  # punto de fenología unificada
        "observations": [("latitude", "REAL"), ("longitude", "REAL"),
                         ("gps_accuracy", "REAL"), ("gps_source", "TEXT")],
        "sampling_weeks": [("skipped", "INTEGER NOT NULL DEFAULT 0")],   # semana no muestreada
        "variety_attachments": [("week_id", "INTEGER")],                # foto adjunta semanal
        "ai_references": [("workspace", "TEXT")],                       # ensayo de la foto
        "treatments": [("cultivar", "TEXT")],                           # variedad del tratamiento
        "notebook_entries": [("ink", "TEXT NOT NULL DEFAULT ''"),        # escritura a mano
                             ("pages", "TEXT NOT NULL DEFAULT ''")],     # hojas 2, 3… (JSON)
        # Foto pegada en la hoja: en qué hoja y dónde (JSON {x, y, w, r} en renglones).
        "notebook_photos": [("page", "INTEGER NOT NULL DEFAULT 0"), ("place", "TEXT NOT NULL DEFAULT ''")],
    }

    def _add_missing_columns(self) -> None:
        for table, cols in self.NEW_COLUMNS.items():
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        # «Fenología del ensayo»: antes tratamiento 0 (ahora el 0 es T0). Las parcelas
        # siempre tienen repetición ≥ 1.
        self.conn.execute("UPDATE varieties SET treatment=-1 WHERE treatment=0 AND rep=0")
        # Y luego (antes de los puntos configurables) tratamiento -1: ahora pheno_unit = 1.
        self.conn.execute("UPDATE varieties SET pheno_unit=1, treatment=NULL, rep=1 WHERE treatment=-1")
        self.conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))

    def _migrate_seasons_apr(self) -> None:
        """
        Temporada julio-junio -> abril-marzo (una sola vez, sin tocar registros ni fotos).

        * Cada temporada con semanas conserva su Semana 1 (7 de septiembre o la elegida en
          Ajustes): así ninguna semana se renumera.
        * Las semanas que en el esquema nuevo caen en otra temporada (abril-junio) se
          pasan a esa temporada con su número recalculado (si son anteriores a su Semana 1,
          esta se adelanta); antes se guarda una copia de la base (…pre-temporadas.bak).
          Los registros, fotos y fechas no cambian: cuelgan del id de la semana.
        """
        if self.conn.execute("SELECT 1 FROM meta WHERE key='season_scheme'").fetchone():
            return
        seasons = [r[0] for r in self.conn.execute("SELECT DISTINCT season FROM sampling_weeks")]
        for season in seasons:
            if self.get_setting(f"season_start:{season}") is None:
                self.set_setting(f"season_start:{season}", ph.legacy_season_start(season).isoformat())
        rows = self.query("SELECT id, season, week_number, start_date FROM sampling_weeks")
        moves = []
        for w in rows:
            target = ph.season_of(_dt.date.fromisoformat(w["start_date"][:10]))
            if target != w["season"]:
                moves.append((w, target))
        if moves:
            try:
                bak = sqlite3.connect(self.path + ".pre-temporadas.bak")
                with bak:
                    self.conn.backup(bak)
                bak.close()
            except Exception as exc:  # noqa: BLE001 (sin copia no se mueve nada)
                print("temporadas: sin copia de seguridad:", exc)
                moves = []
        with self._lock:
            for target in sorted({t for _, t in moves}):
                mine = [w for w, t in moves if t == target]
                raw = self.get_setting(f"season_start:{target}")
                first = _dt.date.fromisoformat(raw) if raw else ph.default_season_start(target)
                earliest = min(_dt.date.fromisoformat(w["start_date"][:10]) for w in mine)
                if earliest < first:
                    # La Semana 1 se adelanta a la semana más antigua que llega: las que ya
                    # estaban solo corren su número interno (fechas y semana del año iguales).
                    k = -(-(first - earliest).days // 7)
                    self.conn.execute("UPDATE sampling_weeks SET week_number=-week_number WHERE season=?",
                                      (target,))
                    self.conn.execute("UPDATE sampling_weeks SET week_number=-week_number+? WHERE season=?",
                                      (k, target))
                    first = first - _dt.timedelta(days=7 * k)
                    self.conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                                      (f"season_start:{target}", json.dumps(first.isoformat())))
                for w in mine:
                    n = ph.week_number_for(_dt.date.fromisoformat(w["start_date"][:10]), first)
                    taken = self.conn.execute(
                        "SELECT 1 FROM sampling_weeks WHERE season=? AND week_number=?", (target, n)).fetchone()
                    if n >= 1 and not taken:
                        self.conn.execute("UPDATE sampling_weeks SET season=?, week_number=? WHERE id=?",
                                          (target, n, w["id"]))
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('season_scheme', 'abr-mar')")
            self.conn.commit()

    def _migrate_photos_v2(self) -> None:
        """
        v1 -> v2: la tabla photos permitía una sola foto por tipo (UNIQUE). Se
        recrea sin esa restricción y con «is_primary», conservando ids (las
        referencias de la IA siguen apuntando a la misma foto).
        """
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='photos'").fetchone()
        if not row or "is_primary" in row[0]:
            return
        c = self.conn
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.executescript("""
                BEGIN;
                CREATE TABLE photos_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK (kind IN ('canopy', 'detail')),
                    path TEXT NOT NULL,
                    source TEXT DEFAULT 'camera',
                    captured_at TEXT NOT NULL,
                    is_primary INTEGER NOT NULL DEFAULT 0);
                INSERT INTO photos_v2(id, observation_id, kind, path, source, captured_at, is_primary)
                    SELECT id, observation_id, kind, path, source, captured_at, 1 FROM photos;
                DROP TABLE photos;
                ALTER TABLE photos_v2 RENAME TO photos;
                UPDATE meta SET value='2' WHERE key='schema_version';
                COMMIT;
            """)
        finally:
            c.execute("PRAGMA foreign_keys = ON")

    def refresh_bbch_scale(self) -> int:
        """Pone al día la escala BASE (versión ph.BBCH_SCALE_VERSION) sin tocar los estados
        editados por el usuario o enriquecidos con documentos. Devuelve cuántos cambió."""
        ai = self.ai_db
        row = ai.query_one("SELECT value FROM meta WHERE key='bbch_scale'")
        if row and int(row["value"] or 0) >= ph.BBCH_SCALE_VERSION:
            return 0
        # Códigos corregidos (553 -> 53): fuera la entrada base antigua y la memoria de la IA
        # pasa al código nuevo.
        for old, new in ph.BBCH_RENAMED.items():
            ai.execute("DELETE FROM bbch_stages WHERE code=? AND source='base'", (old,))
            ai.execute("UPDATE ai_references SET bbch_code=? WHERE bbch_code=?", (new, old))
        for old in ph.BBCH_REMOVED:
            ai.execute("DELETE FROM bbch_stages WHERE code=? AND source='base'", (old,))
        have = {r["code"]: r for r in ai.query("SELECT code, source FROM bbch_stages")}
        n = 0
        for code, label, desc, kw in ph.BBCH_SCALE:
            cur = have.get(code)
            if cur is None or cur["source"] == "base":
                ai.upsert_bbch(code, label, desc, kw, source="base")
                n += 1
        ai.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('bbch_scale', ?)",
                   (str(ph.BBCH_SCALE_VERSION),))
        return n

    def _remap_bbch_codes(self) -> None:
        """Registros guardados con un código corregido de la escala (553 -> 53)."""
        for old, new in ph.BBCH_RENAMED.items():
            for col in ("bbch_code", "ai_code"):
                self.execute(f"UPDATE observations SET {col}=? WHERE {col}=?", (new, old))

    def seed_defaults(self) -> None:
        """Carga variedades y escala BBCH iniciales (solo la primera vez)."""
        seeded = self.query_one("SELECT value FROM meta WHERE key='seeded'")
        if seeded:
            return
        import crops
        # Las del cultivo de ESTA base (no el abierto en pantalla: al sincronizar los otros
        # cultivos se abren sus bases en segundo plano).
        crop = crops.get(self.seed_crop) if self.seed_crop else crops.current()
        for i, (name, code) in enumerate(crop.varieties):
            self.add_variety(name, code=code, sort_order=i, log=False)
        for code, label, desc, kw in ph.BBCH_SCALE:
            self.upsert_bbch(code, label, desc, kw, source="base")
        self.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('seeded', ?)", (_now(),))
        self.log("seed", "database", None, "Variedades y escala BBCH iniciales")

    # --------------------------------------------------------------- audit
    def log(self, action: str, entity: str, entity_id: int | None, detail: str = "") -> None:
        self.execute(
            "INSERT INTO audit_log(ts, action, entity, entity_id, detail) VALUES (?,?,?,?,?)",
            (_now(), action, entity, entity_id, detail))

    def audit_trail(self, limit: int = 200) -> list[dict]:
        return self.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------ settings
    def _settings_db(self, key: str) -> "Database":
        if self.shared is not None and key.startswith(self.SHARED_SETTING_PREFIXES):
            return self.shared
        return self

    @property
    def ai_db(self) -> "Database":
        """Base donde vive la memoria de la IA (común a todos los ensayos si la hay)."""
        return self.shared if self.shared is not None else self

    def get_setting(self, key: str, default: Any = None) -> Any:
        if key in GLOBAL_KEYS:          # cuenta de Drive: una sola para todos los cultivos
            return global_get(key, default)
        if self._settings_db(key) is not self:
            return self.shared.get_setting(key, default)
        row = self.query_one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        if key in GLOBAL_KEYS:
            global_set(key, value)
            return
        if self._settings_db(key) is not self:
            self.shared.set_setting(key, value)
            return
        self.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                     (key, json.dumps(value)))

    # ------------------------------------------------------------ varieties
    def list_varieties(self, include_archived: bool = False) -> list[dict]:
        """Variedades, sectores o parcelas (sin los puntos de la fenología unificada, que
        son solo para la fenología: ver pheno_units)."""
        sql = "SELECT * FROM varieties WHERE pheno_unit = 0"
        if not include_archived:
            sql += " AND active = 1"
        sql += " ORDER BY sort_order, name"
        return self.query(sql)

    # ----------------------------------------------- fenología unificada (ensayos T×R)
    # La fenología se registra en PUNTOS propios (no en las parcelas T×R, que siguen para
    # las mediciones): uno para todo el ensayo, varios comunes (p. ej. «Caña gruesa»,
    # «Caña media», «Caña delgada») o esos mismos en cada tratamiento.
    UNIT_NAME = "Fenología del ensayo"

    @property
    def unified_pheno(self) -> bool:
        """Ensayo de tratamientos con fenología unificada: el estado BBCH se registra en los
        puntos de fenología; las mediciones siguen por tratamiento y repetición."""
        return self.is_trial and bool(self.get_setting("trial_unified", False))

    def pheno_config(self) -> dict:
        """{"scope": "trial" | "treatment", "names": [nombre de cada punto]}.
        scope trial: los puntos valen para todo el ensayo; treatment: se repiten en cada
        tratamiento. Un solo punto sin nombre = «Fenología del ensayo»."""
        scope = self.get_setting("trial_unit_scope", "trial")
        names = [str(n).strip() for n in (self.get_setting("trial_unit_names", None) or [""])]
        scope = scope if scope in ("trial", "treatment") else "trial"
        names = names or [""]
        # Puntos de CADA tratamiento (solo «en cada tratamiento»): p. ej. 3 en T1, 0 en T2 y
        # 3 en T3. Los que no se indican llevan tantos como nombres.
        raw = self.get_setting("trial_unit_counts", None) or {}
        counts = {}
        if scope == "treatment" and isinstance(raw, dict):
            for k, v in raw.items():
                try:
                    counts[int(k)] = max(0, min(int(v), self.MAX_REPS))
                except (TypeError, ValueError):
                    continue
        return {"scope": scope, "names": names, "counts": counts}

    def unit_counts(self, cfg: dict | None = None) -> dict:
        """{tratamiento: n.º de puntos} con la fenología «en cada tratamiento»."""
        cfg = cfg or self.pheno_config()
        return {t: cfg["counts"].get(t, len(cfg["names"])) for t in self.trial_nums()}

    @property
    def unified_single(self) -> bool:
        """Fenología unificada con un solo punto para todo el ensayo (una curva)."""
        cfg = self.pheno_config()
        return self.unified_pheno and cfg["scope"] == "trial" and len(cfg["names"]) == 1

    def _unit_name(self, scope: str, names: list[str], t: int | None, i: int) -> str:
        label = (names[i - 1] if i <= len(names) else "") or (f"Punto {i}" if len(names) > 1 else "")
        if scope == "trial":
            return f"Ensayo · {label}" if label else self.UNIT_NAME
        return f"T{t} · {label}" if label else f"T{t} · Fenología"

    def _want_units(self) -> dict:
        """{(tratamiento o None, n.º de punto): nombre} de los puntos vigentes."""
        cfg = self.pheno_config()
        if cfg["scope"] == "trial":
            return {(None, i): self._unit_name("trial", cfg["names"], None, i)
                    for i in range(1, len(cfg["names"]) + 1)}
        counts = self.unit_counts(cfg)
        top = max(counts.values(), default=0)
        names = cfg["names"] + [""] * (top - len(cfg["names"]))   # más puntos que nombres: «Punto n»
        return {(t, i): self._unit_name("treatment", names, t, i)
                for t, n in counts.items() for i in range(1, n + 1)}

    def sync_pheno_units(self) -> list[dict]:
        """Crea, renombra, activa o archiva los puntos según la configuración (nada se
        borra: los puntos que sobran se archivan con sus registros)."""
        on = self.unified_pheno
        want = self._want_units() if on else {}
        have = self.query("SELECT * FROM varieties WHERE pheno_unit=1")
        by_key = {(v["treatment"], v["rep"]): v for v in have}
        # Fuera del camino los nombres que van a cambiar (el nombre es único).
        for key, v in by_key.items():
            if key in want and v["name"] != want[key]:
                self.execute("UPDATE varieties SET name=? WHERE id=?", (f"~{v['id']}~{v['name']}", v["id"]))
        for (t, i), name in want.items():
            sort = (-100 if t is None else t * 100 - 50) + i
            v = by_key.get((t, i))
            if v is None:
                clash = self.query_one("SELECT id, pheno_unit FROM varieties WHERE name=?", (name,))
                if clash and clash["pheno_unit"]:
                    v = self.get_variety(clash["id"])
                else:
                    if clash:   # una parcela o variedad con ese nombre: el punto lleva otro
                        name = f"{name} (fenología)"
                    cur = self.execute(
                        "INSERT INTO varieties(name, code, notes, sort_order, created_at, updated_at, pheno_unit) "
                        "VALUES (?,?,?,?,?,?,1)", (name, "ENS", "", sort, _now(), _now()))
                    v = {"id": cur.lastrowid}
            self.execute("UPDATE varieties SET name=?, treatment=?, rep=?, active=1, sort_order=?, "
                         "pheno_unit=1, updated_at=? WHERE id=?", (name, t, i, sort, _now(), v["id"]))
        for key, v in by_key.items():
            if key not in want and v["active"]:
                self.execute("UPDATE varieties SET active=0, updated_at=? WHERE id=?", (_now(), v["id"]))
        return self.pheno_units()

    def trial_unit(self, create: bool = True) -> dict | None:
        """El primer punto de fenología (con un solo punto: «Fenología del ensayo»)."""
        units = self.query("SELECT * FROM varieties WHERE pheno_unit=1 AND active=1 ORDER BY sort_order")
        if not units and create and self.unified_pheno:
            units = self.sync_pheno_units()
        return units[0] if units else None

    def set_unified_pheno(self, on: bool, scope: str | None = None, names: list[str] | None = None,
                          counts: dict | None = None) -> None:
        """Activa o quita la fenología unificada (y, si se indican, sus puntos). Nada se
        borra: los registros por parcela y los de los puntos se conservan."""
        self.set_setting("trial_unified", bool(on))
        if scope is not None:
            self.set_setting("trial_unit_scope", scope)
        if names is not None:
            names = [str(n).strip() for n in names][:self.MAX_REPS] or [""]
            self.set_setting("trial_unit_names", names)
        if counts is not None:     # {tratamiento: puntos}; 0 = ese tratamiento sin fenología
            self.set_setting("trial_unit_counts", {str(int(t)): max(0, min(int(n), self.MAX_REPS))
                                                   for t, n in counts.items()})
        self.sync_pheno_units()
        cfg = self.pheno_config()
        detail = (", ".join(f"T{t}: {n}" for t, n in self.unit_counts(cfg).items())
                  if cfg["scope"] == "treatment" else f"{len(cfg['names'])} punto(s) del ensayo")
        self.log("update", "trial", None, f"Fenología unificada: {detail}" if on else "Fenología por parcela")

    def parcel_unit_map(self) -> dict[int, dict]:
        """{parcela: punto de fenología} para pasar lo registrado por parcela a la fenología
        unificada: el punto de su tratamiento (si van por tratamiento) con el mismo n.º que la
        repetición (R1 → 1.er punto…); si hay menos puntos que repeticiones, el primero."""
        units = self.pheno_units() if self.unified_pheno else []
        if not units:
            return {}
        by = {}
        for u in units:
            by.setdefault(u["treatment"], {})[u["rep"]] = u
        out = {}
        for p in self.list_varieties():
            if not self.is_parcel(p):
                continue
            group = by.get(None) or by.get(p["treatment"])
            if group:
                out[p["id"]] = group.get(p["rep"]) or group[min(group)]
        return out

    def parcels_to_units_summary(self) -> dict:
        """Cuánto hay por parcela que se puede pasar: {"photos", "records", "weeks"}."""
        ids = list(self.parcel_unit_map())
        if not ids:
            return {"photos": 0, "records": 0, "weeks": 0}
        q = ",".join(str(i) for i in ids)
        photos = self.query_one(f"SELECT COUNT(*) AS n FROM photos p JOIN observations o ON o.id = p.observation_id "
                                f"WHERE o.variety_id IN ({q})")["n"]
        recs = self.query_one(f"SELECT COUNT(*) AS n, COUNT(DISTINCT week_id) AS w FROM observations o "
                              f"WHERE o.variety_id IN ({q}) AND {self._OBS_FILLED}")
        return {"photos": photos, "records": recs["n"], "weeks": recs["w"]}

    def move_parcels_to_units(self) -> dict:
        """Pasa las FOTOS de los registros por parcela a los puntos de la fenología unificada
        (misma semana). El estado BBCH del punto, si no tenía, queda en el más repetido de sus
        parcelas esa semana (a igualdad, el más avanzado). Los registros por parcela
        conservan su estado y notas (si vuelve a la fenología por parcela, siguen ahí)."""
        mapping = self.parcel_unit_map()
        if not mapping:
            raise ValueError("Active primero la fenología unificada.")
        q = ",".join(str(i) for i in mapping)
        obs = self.query(f"SELECT * FROM observations o WHERE o.variety_id IN ({q}) AND {self._OBS_FILLED}")
        moved = units_set = 0
        codes: dict[tuple, list] = {}
        for o in obs:
            u = mapping[o["variety_id"]]
            target = self.get_or_create_observation(u["id"], o["week_id"])
            if o["bbch_code"] is not None:
                codes.setdefault((target["id"], target["bbch_code"]), []).append(o)
            for p in self.query("SELECT * FROM photos WHERE observation_id=?", (o["id"],)):
                primary = p["is_primary"] and not self.query_one(
                    "SELECT 1 FROM photos WHERE observation_id=? AND kind=? AND is_primary=1",
                    (target["id"], p["kind"]))
                self.execute("UPDATE photos SET observation_id=?, is_primary=? WHERE id=?",
                             (target["id"], int(bool(primary)), p["id"]))
                moved += 1
        for (tid, current), rows in codes.items():
            if current is not None:
                continue
            count: dict[int, int] = {}
            for r in rows:
                count[r["bbch_code"]] = count.get(r["bbch_code"], 0) + 1
            code = max(count, key=lambda c: (count[c], ph.bbch_value(c) or 0))
            label = next(r["bbch_label"] for r in rows if r["bbch_code"] == code)
            self.execute("UPDATE observations SET bbch_code=?, bbch_label=?, updated_at=? WHERE id=?",
                         (code, label or "", _now(), tid))
            units_set += 1
        self.log("update", "trial", None, f"Fotos de las parcelas a la fenología unificada: {moved}")
        return {"photos": moved, "states": units_set}

    def pheno_units(self, include_archived: bool = False) -> list[dict]:
        """Lo que se registra en el muestreo y muestran la vista previa y los informes de
        fenología: los puntos de la fenología unificada o cada variedad/sector/parcela."""
        if self.unified_pheno:
            sql = "SELECT * FROM varieties WHERE pheno_unit=1"
            if not include_archived:
                sql += " AND active=1"
            units = self.query(sql + " ORDER BY sort_order, name")
            if not units and not include_archived:
                units = self.sync_pheno_units()
            return units
        return self.list_varieties(include_archived=include_archived)

    def get_variety(self, variety_id: int) -> dict | None:
        return self.query_one("SELECT * FROM varieties WHERE id=?", (variety_id,))

    def add_variety(self, name: str, code: str | None = None, notes: str = "",
                    sort_order: int | None = None, log: bool = True,
                    sector: int | None = None, irrigation: int | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("El nombre de la variedad no puede estar vacío.")
        existing = self.query_one("SELECT * FROM varieties WHERE name=?", (name,))
        if existing:
            if not existing["active"]:
                self.execute("UPDATE varieties SET active=1, updated_at=? WHERE id=?",
                             (_now(), existing["id"]))
                self.log("restore", "variety", existing["id"], name)
                return existing["id"]
            raise ValueError(f"La variedad «{name}» ya existe.")
        if sort_order is None:
            row = self.query_one("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM varieties")
            sort_order = row["n"]
        cur = self.execute(
            "INSERT INTO varieties(name, code, notes, sort_order, sector, irrigation, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (name, code or "", notes, sort_order, sector, irrigation, _now(), _now()))
        if log:
            self.log("create", "variety", cur.lastrowid, name)
        return cur.lastrowid

    def update_variety(self, variety_id: int, **fields: Any) -> None:
        allowed = {"name", "code", "notes", "sort_order", "active", "sector", "irrigation",
                   "treatment", "rep", "cultivar", "plant_year"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k}=?" for k in sets)
        self.execute(f"UPDATE varieties SET {cols}, updated_at=? WHERE id=?",
                     (*sets.values(), _now(), variety_id))
        self.log("update", "variety", variety_id, json.dumps(sets, ensure_ascii=False))

    # ---------------------------------------------------- predio: unidades
    @property
    def is_predio(self) -> bool:
        return (self.workspace or {}).get("profile") == "predio"

    _KEEP = object()

    def save_unit(self, cultivar: str, code: str = "", sector: int | None = None,
                  irrigation: int | None = None, variety_id: int | None = None,
                  plant_year=_KEEP) -> int:
        """Unidad de predio: se llama «Equipo de riego n, sector m» y la variedad va aparte
        (la misma variedad puede estar en varios sectores y un sector puede tener varias
        variedades, o la misma variedad plantada en años distintos). plant_year: año de
        plantación (sin indicarlo, al editar se conserva el que tenía)."""
        cultivar = (cultivar or "").strip()
        if not cultivar:
            raise ValueError("Indique la variedad.")
        if not sector and not irrigation:
            raise ValueError("Elija el sector y/o el equipo de riego.")
        if plant_year is self._KEEP:
            old = self.get_variety(variety_id) if variety_id else None
            plant_year = old.get("plant_year") if old else None
        plant_year = int(plant_year) if plant_year else None
        if plant_year is not None and not 1950 <= plant_year <= 2100:
            raise ValueError("El año de plantación no es válido.")
        base = ph.unit_name(sector, irrigation)
        dup = self.query_one(
            "SELECT id FROM varieties WHERE active=1 AND IFNULL(sector,0)=? AND IFNULL(irrigation,0)=? "
            "AND lower(IFNULL(cultivar,''))=lower(?) AND IFNULL(plant_year,0)=? AND id IS NOT ?",
            (sector or 0, irrigation or 0, cultivar, plant_year or 0, variety_id))
        if dup:
            raise ValueError(f"Ya existe «{base}» con la variedad {cultivar}"
                             + (f" ({plant_year})." if plant_year else "."))
        name = base
        cands = [base, f"{base} · {cultivar}"] + ([f"{base} · {cultivar} {plant_year}"] if plant_year else [])
        for cand in cands:
            other = self.query_one("SELECT id, active FROM varieties WHERE name=?", (cand,))
            if other is None or other["id"] == variety_id or (not other["active"] and variety_id is None):
                name = cand
                break
        else:
            raise ValueError(f"Ya existe «{base}» con la variedad {cultivar}.")
        if variety_id is None:
            variety_id = self.add_variety(name, code=code, sector=sector, irrigation=irrigation)
        self.update_variety(variety_id, name=name, code=code or "", cultivar=cultivar,
                            sector=sector, irrigation=irrigation, plant_year=plant_year, active=1)
        return variety_id

    def migrate_predio_units(self) -> int:
        """Unidades creadas antes con el nombre de la variedad -> «Equipo de riego n, sector m»."""
        import re as _re
        n = 0
        for v in self.query("SELECT * FROM varieties WHERE (cultivar IS NULL OR cultivar='') "
                            "AND (sector IS NOT NULL OR irrigation IS NOT NULL)"):
            cultivar = _re.sub(r"\s+S\d+(ER\d+)?$|\s+ER\d+$", "", v["name"]).strip() or v["name"]
            try:
                self.save_unit(cultivar, v["code"] or "", v["sector"], v["irrigation"], v["id"])
                n += 1
            except ValueError:
                self.update_variety(v["id"], cultivar=cultivar)
        return n

    # --------------------------------------------- tratamientos × repeticiones
    MAX_TREATMENTS, MAX_REPS = 30, 12

    @property
    def is_trial(self) -> bool:
        """Ensayo de tratamientos × repeticiones (sus «variedades» son parcelas T1R1…)."""
        return (self.workspace or {}).get("kind") == "tratamientos" or bool(
            self.get_setting("trial_treatments", 0))

    def trial_size(self) -> tuple[int, int]:
        return int(self.get_setting("trial_treatments", 0) or 0), int(self.get_setting("trial_reps", 0) or 0)

    @property
    def trial_has_t0(self) -> bool:
        """El ensayo numera los tratamientos desde T0 (T0 … Tn-1) en vez de T1 … Tn."""
        return bool(self.get_setting("trial_t0", False))

    def trial_nums(self) -> list[int]:
        """Números de los tratamientos vigentes: [0 … n-1] con T0, si no [1 … n]."""
        nt, _nr = self.trial_size()
        first = 0 if self.trial_has_t0 else 1
        return list(range(first, first + nt))

    @staticmethod
    def is_parcel(v: dict | None) -> bool:
        """¿Es una parcela TxRy de un ensayo (incluida T0)? (no la «Fenología del ensayo»)."""
        t = (v or {}).get("treatment")
        return t is not None and t >= 0 and not (v or {}).get("pheno_unit")

    def setup_trial(self, n_treatments: int, n_reps: int, t0: bool | None = None) -> dict:
        """Crea (o ajusta) las parcelas T1R1 … TnRm (con `t0`: T0R1 … Tn-1Rm). Al reducir, las
        parcelas que sobran se ARCHIVAN (sus registros se conservan); al volver a aumentar,
        reaparecen."""
        nt, nr = int(n_treatments), int(n_reps)
        if not (1 <= nt <= self.MAX_TREATMENTS) or not (1 <= nr <= self.MAX_REPS):
            raise ValueError(f"Tratamientos: 1 a {self.MAX_TREATMENTS} · repeticiones: 1 a {self.MAX_REPS}.")
        t0 = self.trial_has_t0 if t0 is None else bool(t0)
        first, last = (0, nt - 1) if t0 else (1, nt)
        added = restored = archived = 0
        for t in range(first, last + 1):
            self.execute("INSERT OR IGNORE INTO treatments(num, name) VALUES (?, '')", (t,))
            for r in range(1, nr + 1):
                name = f"T{t}R{r}"
                cur = self.query_one("SELECT * FROM varieties WHERE treatment=? AND rep=? AND pheno_unit=0",
                                     (t, r)) \
                    or self.query_one("SELECT * FROM varieties WHERE name=? AND pheno_unit=0", (name,))
                if cur is None:
                    vid = self.add_variety(name, code=name, sort_order=t * 100 + r, log=False)
                    added += 1
                else:
                    vid = cur["id"]
                    if not cur["active"]:
                        restored += 1
                self.execute("UPDATE varieties SET treatment=?, rep=?, active=1, sort_order=?, "
                             "updated_at=? WHERE id=?", (t, r, t * 100 + r, _now(), vid))
        for v in self.query("SELECT id FROM varieties WHERE active=1 AND treatment >= 0 AND pheno_unit=0 "
                            "AND (treatment<? OR treatment>? OR rep>?)", (first, last, nr)):
            self.execute("UPDATE varieties SET active=0, updated_at=? WHERE id=?", (_now(), v["id"]))
            archived += 1
        self.set_setting("trial_treatments", nt)
        self.set_setting("trial_reps", nr)
        self.set_setting("trial_t0", t0)
        self.log("update", "trial", None, f"{nt} tratamientos (T{first}–T{last}) × {nr} repeticiones "
                                          f"(+{added}, restauradas {restored}, archivadas {archived})")
        if self.unified_pheno:      # puntos de fenología por tratamiento: siguen a los tratamientos
            self.sync_pheno_units()
        return {"added": added, "restored": restored, "archived": archived}

    @staticmethod
    def treatment_label(t: dict) -> str:
        return f"T{t['num']} · {t['name']}" if (t.get("name") or "").strip() else f"T{t['num']}"

    def treatment_names(self) -> dict[int, str]:
        """{número: significado} de los tratamientos con nombre («Testigo», «N 120 kg/ha»…)."""
        return {r["num"]: r["name"].strip() for r in self.query("SELECT num, name FROM treatments")
                if (r["name"] or "").strip()}

    @staticmethod
    def parcel_labels(v: dict, names: dict | None = None) -> tuple[str, str]:
        """(título, etiqueta chica) de una fila: en un ensayo de tratamientos con el
        tratamiento definido, («Testigo», «T1R1»); si no, (nombre, «»)."""
        t = v.get("treatment")
        if t is not None and t >= 0 and names and names.get(t):
            return names[t], v["name"]
        return v["name"], ""

    def display_name(self, v: dict, names: dict | None = None) -> str:
        """Nombre para informes: «Testigo (T1R1)» o el nombre tal cual."""
        title, tag = self.parcel_labels(v, self.treatment_names() if names is None else names)
        return f"{title} ({tag})" if tag else title

    @property
    def trial_cultivar(self) -> str:
        """Variedad de todo el ensayo (opcional; cada tratamiento puede tener otra)."""
        return self.get_setting("trial_cultivar", "") or ""

    def list_treatments(self) -> list[dict]:
        nums = self.trial_nums()
        if not nums:
            return []
        for n in nums:   # T0 (o un número nuevo) llega a existir aunque nadie lo haya nombrado
            self.execute("INSERT OR IGNORE INTO treatments(num, name) VALUES (?, '')", (n,))
        out = []
        default = self.trial_cultivar
        for t in self.query("SELECT * FROM treatments WHERE num BETWEEN ? AND ? ORDER BY num",
                            (nums[0], nums[-1])):
            t["label"] = self.treatment_label(t)
            t["variety"] = (t.get("cultivar") or "").strip() or default
            t["parcels"] = self.query("SELECT * FROM varieties WHERE active=1 AND pheno_unit=0 AND treatment=? "
                                      "ORDER BY rep", (t["num"],))
            out.append(t)
        return out

    def update_treatment(self, num: int, name: str = "", description: str = "",
                         cultivar: str | None = None) -> None:
        self.execute("INSERT OR IGNORE INTO treatments(num, name) VALUES (?, '')", (num,))
        self.execute("UPDATE treatments SET name=?, description=? WHERE num=?",
                     ((name or "").strip(), (description or "").strip(), num))
        if cultivar is not None:   # "" = usa la variedad del ensayo
            self.execute("UPDATE treatments SET cultivar=? WHERE num=?", ((cultivar or "").strip(), num))
        self.log("update", "treatment", num, (name or "").strip())

    def drop_foreign_defaults(self, crop_id: str) -> list[str]:
        """Quita las variedades iniciales de OTRO cultivo (p. ej. Duke o Legacy en una base
        de frambuesa) que quedaron por error al sincronizar los cultivos desde la pantalla
        principal. Solo las que no tienen ningún registro, foto ni medición. Devuelve sus
        nombres."""
        import crops
        mine = {n.lower() for n, _c in crops.get(crop_id).varieties}
        foreign = {(n.lower(), (c or "").lower()) for cr in crops.CROPS.values() if cr.id != crop_id
                   for n, c in cr.varieties if n.lower() not in mine}
        if not foreign:
            return []
        tables = [t for t in ("observations", "variety_attachments", "measure_entries", "variety_metrics",
                              "custom_fields")
                  if self.query_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,))]
        out = []
        for v in self.query("SELECT id, name, code FROM varieties"):
            if ((v["name"] or "").lower(), (v["code"] or "").lower()) not in foreign:
                continue
            if any(self.query_one(f"SELECT 1 FROM {t} WHERE variety_id=? LIMIT 1", (v["id"],)) for t in tables):
                continue
            self.execute("DELETE FROM varieties WHERE id=?", (v["id"],))
            self.log("delete", "variety", v["id"], f"{v['name']} (de otro cultivo, sin registros)")
            out.append(v["name"])
        return out

    def delete_variety(self, variety_id: int, purge: bool = False) -> None:
        """
        purge=False  -> archiva (conserva historial y fotos: trazabilidad).
        purge=True   -> elimina definitivamente con sus registros (cascade).
        """
        v = self.get_variety(variety_id)
        if not v:
            return
        if purge:
            self.execute("DELETE FROM varieties WHERE id=?", (variety_id,))
            self.log("delete", "variety", variety_id, v["name"])
        else:
            self.execute("UPDATE varieties SET active=0, updated_at=? WHERE id=?",
                         (_now(), variety_id))
            self.log("archive", "variety", variety_id, v["name"])

    # --------------------------------------------------------------- metrics
    METRIC_FIELDS = ("historical_yield", "historical_yield_unit", "historical_note",
                     "projected_yield", "projected_yield_unit", "basal_canes",
                     "basal_canes_unit", "laterals", "laterals_unit")

    def get_metrics(self, variety_id: int, season: int) -> dict:
        row = self.query_one(
            "SELECT * FROM variety_metrics WHERE variety_id=? AND season=?",
            (variety_id, season))
        if row:
            return row
        return {"variety_id": variety_id, "season": season, "historical_yield": None,
                "historical_yield_unit": "kg/planta", "historical_note": "",
                "projected_yield": None, "projected_yield_unit": "kg/planta",
                "basal_canes": None, "basal_canes_unit": "por planta",
                "laterals": None, "laterals_unit": "por caña"}

    def save_metrics(self, variety_id: int, season: int, **values: Any) -> None:
        data = {k: values[k] for k in self.METRIC_FIELDS if k in values}
        current = self.get_metrics(variety_id, season)
        current.update(data)
        cols = list(self.METRIC_FIELDS)
        self.execute(
            f"INSERT INTO variety_metrics(variety_id, season, {', '.join(cols)}, updated_at) "
            f"VALUES (?, ?, {', '.join('?' for _ in cols)}, ?) "
            f"ON CONFLICT(variety_id, season) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in cols) + ", updated_at=excluded.updated_at",
            (variety_id, season, *[current.get(c) for c in cols], _now()))
        self.log("update", "metrics", variety_id, json.dumps(data, ensure_ascii=False))

    # ---------------------------------------------------------- custom fields
    def list_custom_fields(self, variety_id: int, season: int) -> list[dict]:
        return self.query(
            "SELECT * FROM custom_fields WHERE variety_id=? AND season=? ORDER BY key",
            (variety_id, season))

    def set_custom_field(self, variety_id: int, season: int, key: str,
                         value: str, unit: str = "") -> None:
        key = key.strip()
        if not key:
            raise ValueError("El nombre del campo no puede estar vacío.")
        self.execute(
            "INSERT INTO custom_fields(variety_id, season, key, value, unit, updated_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(variety_id, season, key) DO UPDATE SET "
            "value=excluded.value, unit=excluded.unit, updated_at=excluded.updated_at",
            (variety_id, season, key, str(value), unit, _now()))
        self.log("set", "custom_field", variety_id, f"{key}={value} {unit}".strip())

    def delete_custom_field(self, field_id: int) -> None:
        self.execute("DELETE FROM custom_fields WHERE id=?", (field_id,))
        self.log("delete", "custom_field", field_id)

    # ------------------------------------------------- fotos adjuntas (ficha)
    def add_attachment(self, variety_id: int, season: int, path: str, caption: str = "",
                       source: str = "camera", week_id: int | None = None) -> int:
        cur = self.execute(
            "INSERT INTO variety_attachments(variety_id, season, path, caption, source, captured_at, "
            "week_id) VALUES (?,?,?,?,?,?,?)",
            (variety_id, season, path, caption.strip(), source, _now(), week_id))
        self.log("create", "attachment", cur.lastrowid, os.path.basename(path))
        return cur.lastrowid

    def list_attachments(self, variety_id: int, season: int | None = None,
                         week_id: int | None = None, general: bool = False) -> list[dict]:
        """Fotos adjuntas de la variedad: de una semana (week_id), de la temporada o solo
        las generales (sin semana, versiones anteriores)."""
        sql, params = "SELECT * FROM variety_attachments WHERE variety_id=?", [variety_id]
        if season is not None:
            sql += " AND season=?"
            params.append(season)
        if week_id is not None:
            sql += " AND week_id=?"
            params.append(week_id)
        elif general:
            sql += " AND week_id IS NULL"
        return self.query(sql + " ORDER BY captured_at, id", tuple(params))

    def set_attachment_caption(self, attachment_id: int, caption: str) -> None:
        self.execute("UPDATE variety_attachments SET caption=? WHERE id=?",
                     (caption.strip(), attachment_id))

    def delete_attachment(self, attachment_id: int) -> None:
        self.execute("DELETE FROM variety_attachments WHERE id=?", (attachment_id,))
        self.log("delete", "attachment", attachment_id)

    # ------------------------------------------- cuaderno de campo (bitácora)
    def note_days(self) -> list[dict]:
        """Páginas del cuaderno, de la más reciente a la más antigua, con sus fotos."""
        rows = self.query("SELECT * FROM notebook_entries ORDER BY day DESC")
        photos: dict = {}
        for p in self.query("SELECT * FROM notebook_photos ORDER BY created_at, id"):
            photos.setdefault(p["entry_id"], []).append(p)
        for r in rows:
            r["photos"] = photos.get(r["id"], [])
        return rows

    def note_for_day(self, day: str, create: bool = False) -> dict | None:
        row = self.query_one("SELECT * FROM notebook_entries WHERE day=?", (day[:10],))
        if row is None and create:
            now = _now()
            self.execute("INSERT INTO notebook_entries(day, text, created_at, updated_at) VALUES (?,?,?,?)",
                         (day[:10], "", now, now))
            row = self.query_one("SELECT * FROM notebook_entries WHERE day=?", (day[:10],))
        if row is not None:
            row["photos"] = self.query("SELECT * FROM notebook_photos WHERE entry_id=? ORDER BY created_at, id",
                                       (row["id"],))
        return row

    def save_note_ink(self, entry_id: int, ink: str) -> None:
        """Escritura a mano de la página: JSON [{"c": color, "w": grosor, "p": [x, y, …]}] con
        x, y en renglones desde el borde superior izquierdo del texto (igual en app y web)."""
        cur = self.query_one("SELECT ink FROM notebook_entries WHERE id=?", (entry_id,))
        if cur is not None and (cur["ink"] or "") != ink:
            self.execute("UPDATE notebook_entries SET ink=?, updated_at=? WHERE id=?", (ink, _now(), entry_id))

    def save_note_text(self, entry_id: int, text: str) -> None:
        cur = self.query_one("SELECT text FROM notebook_entries WHERE id=?", (entry_id,))
        if cur is not None and cur["text"] != text:
            self.execute("UPDATE notebook_entries SET text=?, updated_at=? WHERE id=?", (text, _now(), entry_id))

    # Hojas del día: la 1 son las columnas text/ink de siempre (así la web y los PDF
    # anteriores la siguen leyendo); las siguientes, una lista JSON [{"text", "ink"}] en pages.
    @staticmethod
    def note_pages(entry: dict) -> list[dict]:
        """Todas las hojas del día: [{"text", "ink"}, …] (al menos una)."""
        try:
            extra = json.loads(entry.get("pages") or "[]")
        except ValueError:
            extra = []
        return [{"text": entry.get("text") or "", "ink": entry.get("ink") or ""}] + [
            {"text": p.get("text") or "", "ink": p.get("ink") or ""} for p in extra if isinstance(p, dict)]

    def save_note_page(self, entry_id: int, index: int, text: str, ink: str) -> None:
        """Guarda la hoja `index` (0 = la primera) del día."""
        if index == 0:
            self.save_note_text(entry_id, text)
            self.save_note_ink(entry_id, ink)
            return
        row = self.query_one("SELECT * FROM notebook_entries WHERE id=?", (entry_id,))
        if row is None:
            return
        pages = self.note_pages(row)[1:]
        while len(pages) < index:
            pages.append({"text": "", "ink": ""})
        if pages[index - 1] == {"text": text, "ink": ink}:
            return
        pages[index - 1] = {"text": text, "ink": ink}
        self.execute("UPDATE notebook_entries SET pages=?, updated_at=? WHERE id=?",
                     (json.dumps(pages, ensure_ascii=False), _now(), entry_id))

    def add_note_page(self, entry_id: int) -> int:
        """Agrega una hoja en blanco al final; devuelve su índice."""
        row = self.query_one("SELECT * FROM notebook_entries WHERE id=?", (entry_id,))
        pages = self.note_pages(row)[1:] + [{"text": "", "ink": ""}]
        self.execute("UPDATE notebook_entries SET pages=?, updated_at=? WHERE id=?",
                     (json.dumps(pages, ensure_ascii=False), _now(), entry_id))
        return len(pages)

    def delete_note_page(self, entry_id: int, index: int) -> None:
        """Quita la hoja `index` (si es la 1, la 2 pasa a ser la 1). Sus fotos se quitan y las
        de las hojas siguientes se corren una hoja."""
        row = self.query_one("SELECT * FROM notebook_entries WHERE id=?", (entry_id,))
        pages = self.note_pages(row)
        if len(pages) <= 1:
            return
        pages.pop(index)
        first, rest = pages[0], pages[1:]
        self.execute("UPDATE notebook_entries SET text=?, ink=?, pages=?, updated_at=? WHERE id=?",
                     (first["text"], first["ink"], json.dumps(rest, ensure_ascii=False) if rest else "",
                      _now(), entry_id))
        self.execute("DELETE FROM notebook_photos WHERE entry_id=? AND page=?", (entry_id, index))
        self.execute("UPDATE notebook_photos SET page=page-1 WHERE entry_id=? AND page>?", (entry_id, index))

    def place_note_photo(self, photo_id: int, page: int, place: dict) -> None:
        """Dónde quedó la foto pegada en la hoja (x, y del centro y ancho en renglones; giro)."""
        self.execute("UPDATE notebook_photos SET page=?, place=? WHERE id=?",
                     (int(page), json.dumps({k: round(float(v), 3) for k, v in place.items()}), photo_id))

    def move_note(self, entry_id: int, day: str) -> None:
        """Cambia la fecha de una página (si ese día ya tenía página, se rechaza)."""
        if self.query_one("SELECT 1 FROM notebook_entries WHERE day=? AND id<>?", (day[:10], entry_id)):
            raise ValueError("Ese día ya tiene una página en el cuaderno.")
        self.execute("UPDATE notebook_entries SET day=?, updated_at=? WHERE id=?", (day[:10], _now(), entry_id))

    def delete_note(self, entry_id: int) -> None:
        self.execute("DELETE FROM notebook_photos WHERE entry_id=?", (entry_id,))
        self.execute("DELETE FROM notebook_entries WHERE id=?", (entry_id,))
        self.log("delete", "note", entry_id)

    def add_note_photo(self, entry_id: int, path: str, caption: str = "", page: int = 0,
                       place: dict | None = None) -> int:
        cur = self.execute("INSERT INTO notebook_photos(entry_id, path, caption, annotated, created_at, page, place) "
                           "VALUES (?,?,?,0,?,?,?)", (entry_id, path, caption, _now(), int(page),
                                                       json.dumps(place) if place else ""))
        self.execute("UPDATE notebook_entries SET updated_at=? WHERE id=?", (_now(), entry_id))
        return cur.lastrowid

    def set_note_photo(self, photo_id: int, path: str, annotated: bool = True) -> None:
        self.execute("UPDATE notebook_photos SET path=?, annotated=? WHERE id=?", (path, int(annotated), photo_id))

    def delete_note_photo(self, photo_id: int) -> None:
        self.execute("DELETE FROM notebook_photos WHERE id=?", (photo_id,))

    # ------------------------------------------- mediciones personalizadas
    MEASURE_KINDS = {"images": "Registro de imágenes", "table": "Planilla de datos"}

    @staticmethod
    def _measure(row: dict | None) -> dict | None:
        if row is not None:
            row["columns"] = json.loads(row.get("columns") or "[]")
        return row

    def add_measure(self, name: str, kind: str, columns: list[str] | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Póngale un nombre a la medición.")
        if kind not in self.MEASURE_KINDS:
            raise ValueError("Tipo de medición desconocido.")
        cols = [c.strip() for c in (columns or []) if c and c.strip()]
        if kind == "table" and not cols:
            cols = list(self.DEFAULT_COLUMNS)   # planilla nueva: se nombran luego en la grilla
        order = (self.query_one("SELECT MAX(sort_order) AS m FROM measures") or {}).get("m") or 0
        cur = self.execute(
            "INSERT INTO measures(name, kind, columns, sort_order, created_at) VALUES (?,?,?,?,?)",
            (name, kind, json.dumps(list(dict.fromkeys(cols)), ensure_ascii=False), order + 1, _now()))
        self.log("create", "measure", cur.lastrowid, f"{name} ({kind})")
        return cur.lastrowid

    def update_measure(self, measure_id: int, name: str | None = None,
                       columns: list[str] | None = None) -> None:
        if name is not None:
            if not name.strip():
                raise ValueError("Póngale un nombre a la medición.")
            self.execute("UPDATE measures SET name=? WHERE id=?", (name.strip(), measure_id))
        if columns is not None:
            cols = list(dict.fromkeys(c.strip() for c in columns if c and c.strip()))
            if not cols:
                raise ValueError("La planilla necesita al menos una columna.")
            self.execute("UPDATE measures SET columns=? WHERE id=?",
                         (json.dumps(cols, ensure_ascii=False), measure_id))

    DEFAULT_COLUMNS = ["Columna 1", "Columna 2", "Columna 3"]

    def add_measure_column(self, measure_id: int, name: str | None = None) -> str:
        """Agrega una columna al final (nombre automático «Columna N» si no se indica)."""
        m = self.get_measure(measure_id)
        cols = m["columns"]
        if name is None or not name.strip():
            n = len(cols) + 1
            while f"Columna {n}" in cols:
                n += 1
            name = f"Columna {n}"
        name = name.strip()
        if name in cols:
            raise ValueError(f"Ya existe la columna «{name}».")
        self.update_measure(measure_id, columns=cols + [name])
        return name

    def rename_measure_column(self, measure_id: int, old: str, new: str) -> None:
        """Renombra la columna y mueve sus datos en todas las semanas."""
        new = (new or "").strip()
        m = self.get_measure(measure_id)
        if not new:
            raise ValueError("El nombre de la columna no puede quedar vacío.")
        if new == old:
            return
        if new in m["columns"]:
            raise ValueError(f"Ya existe la columna «{new}».")
        cols = [new if col == old else col for col in m["columns"]]
        with self._lock:
            self.update_measure(measure_id, columns=cols)
            for e in self.query("SELECT id, data FROM measure_entries WHERE measure_id=?", (measure_id,)):
                data = json.loads(e["data"] or "{}")
                if old in data:
                    data = {(new if k == old else k): v for k, v in data.items()}
                    self.execute("UPDATE measure_entries SET data=? WHERE id=?",
                                 (json.dumps(data, ensure_ascii=False), e["id"]))

    def delete_measure_column(self, measure_id: int, name: str) -> None:
        """Elimina la columna y sus datos (debe quedar al menos una)."""
        m = self.get_measure(measure_id)
        cols = [col for col in m["columns"] if col != name]
        if not cols:
            raise ValueError("La planilla debe tener al menos una columna.")
        with self._lock:
            self.update_measure(measure_id, columns=cols)
            for e in self.query("SELECT id, data FROM measure_entries WHERE measure_id=?", (measure_id,)):
                data = json.loads(e["data"] or "{}")
                if name in data:
                    data.pop(name)
                    self.execute("UPDATE measure_entries SET data=? WHERE id=?",
                                 (json.dumps(data, ensure_ascii=False), e["id"]))

    def delete_measure(self, measure_id: int) -> None:
        self.execute("DELETE FROM measures WHERE id=?", (measure_id,))
        self.log("delete", "measure", measure_id)

    def get_measure(self, measure_id: int) -> dict | None:
        return self._measure(self.query_one("SELECT * FROM measures WHERE id=?", (measure_id,)))

    def list_measures(self, week_id: int | None = None) -> list[dict]:
        """Mediciones definidas; con week_id agrega «n» = registros de esa semana."""
        rows = self.query(
            "SELECT m.*, (SELECT COUNT(*) FROM measure_entries e WHERE e.measure_id = m.id "
            "AND e.week_id = ? AND (e.path IS NOT NULL OR e.data NOT IN ('', '{}'))) AS n "
            "FROM measures m ORDER BY m.sort_order, m.id", (week_id or 0,))
        return [self._measure(r) for r in rows]

    def measure_counts(self, season: int) -> dict:
        """{variety_id: registros de mediciones en la temporada} (mapa del predio)."""
        rows = self.query(
            "SELECT e.variety_id AS vid, COUNT(*) AS n FROM measure_entries e "
            "JOIN sampling_weeks w ON w.id = e.week_id WHERE w.season = ? "
            "AND e.variety_id IS NOT NULL AND (e.path IS NOT NULL OR e.data NOT IN ('', '{}')) "
            "GROUP BY e.variety_id", (season,))
        return {r["vid"]: r["n"] for r in rows}

    def add_entry(self, measure_id: int, week_id: int, variety_id: int | None = None,
                  path: str | None = None, caption: str = "", data: dict | None = None) -> int:
        cur = self.execute(
            "INSERT INTO measure_entries(measure_id, week_id, variety_id, path, caption, data, "
            "created_at) VALUES (?,?,?,?,?,?,?)",
            (measure_id, week_id, variety_id, path, (caption or "").strip(),
             json.dumps(data or {}, ensure_ascii=False), _now()))
        return cur.lastrowid

    def update_entry(self, entry_id: int, **fields) -> None:
        allowed = {"variety_id", "caption", "data"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(k)
            if k == "data":
                v = json.dumps(v or {}, ensure_ascii=False)
            elif k == "caption":
                v = (v or "").strip()
            sets.append(f"{k}=?")
            vals.append(v)
        if sets:
            self.execute(f"UPDATE measure_entries SET {', '.join(sets)} WHERE id=?", (*vals, entry_id))

    def delete_week_entries(self, measure_id: int, week_id: int) -> int:
        """Borra lo registrado en UNA semana para una medición (la medición sigue)."""
        n = self.execute("DELETE FROM measure_entries WHERE measure_id=? AND week_id=?",
                         (measure_id, week_id)).rowcount
        self.log("delete", "measure_week", measure_id, f"semana {week_id}: {n} registro(s)")
        return n

    def delete_entry(self, entry_id: int) -> None:
        self.execute("DELETE FROM measure_entries WHERE id=?", (entry_id,))

    def list_entries(self, measure_id: int, week_id: int | None = None,
                     season: int | None = None) -> list[dict]:
        """Registros de la medición (de una semana o de toda la temporada), con la
        semana y el nombre de la variedad."""
        sql = ("SELECT e.*, w.season, w.week_number, w.start_date, w.label AS week_label, "
               "v.name AS variety_name FROM measure_entries e "
               "JOIN sampling_weeks w ON w.id = e.week_id "
               "LEFT JOIN varieties v ON v.id = e.variety_id WHERE e.measure_id=?")
        params: list = [measure_id]
        if week_id is not None:
            sql += " AND e.week_id=?"
            params.append(week_id)
        if season is not None:
            sql += " AND w.season=?"
            params.append(season)
        rows = self.query(sql + " ORDER BY w.start_date, e.created_at, e.id", tuple(params))
        for r in rows:
            r["data"] = json.loads(r.get("data") or "{}")
        return rows

    def custom_field_keys(self) -> list[str]:
        return [r["key"] for r in self.query(
            "SELECT DISTINCT key FROM custom_fields ORDER BY key")]

    # ---------------------------------------------------------------- season
    def current_season(self, today: _dt.date | None = None) -> int:
        forced = self.get_setting("active_season")
        if forced:
            return int(forced)
        return ph.season_of(today or _dt.date.today())

    def season_start(self, season: int) -> _dt.date:
        raw = self.get_setting(f"season_start:{season}")
        if raw:
            return _dt.date.fromisoformat(raw)
        return ph.default_season_start(season)

    def set_season_start(self, season: int, start: _dt.date) -> None:
        """Redefine la Semana 1. Re-etiqueta las semanas ya creadas."""
        self.set_setting(f"season_start:{season}", start.isoformat())
        weeks = self.query("SELECT * FROM sampling_weeks WHERE season=?", (season,))
        old_start = {w["week_number"]: _dt.date.fromisoformat(w["start_date"][:10]) for w in weeks}
        for w in weeks:
            n = float(w["week_number"])
            ws = ph.week_start(start, int(n))
            if n % 1:     # muestreo extra: el mismo día de la semana, dentro de su semana
                base = old_start.get(int(n))
                if base is not None:
                    ws += min(_dt.timedelta(days=6), max(_dt.timedelta(days=1), old_start[w["week_number"]] - base))
                else:
                    ws += _dt.timedelta(days=3)
            self.execute("UPDATE sampling_weeks SET start_date=?, label=? WHERE id=?",
                         (ws.isoformat(), ph.week_label(ws, extra=bool(n % 1)), w["id"]))
        self.log("update", "season_start", season, start.isoformat())

    # ---------------------------------------------------------------- weeks
    WEEK_TABLES = ("observations", "measure_entries", "variety_attachments")

    def renumber_weeks(self, season: int | None = None) -> int:
        """Pone a cada semana el número que le toca por su fecha de inicio y la Semana 1
        vigente de su temporada. Hace falta cuando la Semana 1 llega de otro equipo (la
        sincronización trae el ajuste, pero las semanas ya creadas aquí seguían numeradas
        desde la fecha anterior: al recorrerlas se saltaba, p. ej., de la 36 a la 14).
        Si dos semanas quedan con el mismo número, sus registros se juntan. No viaja a los
        otros equipos. Devuelve cuántas semanas cambió."""
        seasons = [season] if season is not None else \
            [r["season"] for r in self.query("SELECT DISTINCT season FROM sampling_weeks")]
        fixed = 0
        with self._lock:
            has_state = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_state'").fetchone()
            row = self.conn.execute("SELECT value FROM sync_state WHERE key='applying'").fetchone() \
                if has_state else None
            before = row[0] if row else None
            if before is not None:
                self.conn.execute("UPDATE sync_state SET value='1' WHERE key='applying'")
            try:
                for s in seasons:
                    fixed += self._dedupe_weeks(s)
                    start = self.season_start(s)
                    rows = self.query("SELECT id, week_number, start_date FROM sampling_weeks WHERE season=?", (s,))
                    # El muestreo extra (n + 0,5) va con la semana que contiene su fecha.
                    want = {r["id"]: ph.week_number_for(_dt.date.fromisoformat(r["start_date"][:10]), start)
                            + (.5 if float(r["week_number"]) % 1 else 0) for r in rows}
                    wrong = [r for r in rows if want[r["id"]] != r["week_number"]]
                    if not wrong:
                        continue
                    # Fuera del camino primero (número único por temporada), luego a su lugar;
                    # las semanas con registros eligen número antes que las vacías.
                    self.conn.execute(f"UPDATE sampling_weeks SET week_number = -1000000 - id "
                                      f"WHERE id IN ({','.join(str(r['id']) for r in wrong)})")
                    taken = {want[r["id"]]: r["id"] for r in rows if r not in wrong}
                    for r in sorted(wrong, key=lambda r: not self._week_has_data(r["id"])):
                        n = want[r["id"]]
                        if n in taken:
                            self._merge_week(r["id"], taken[n])
                        else:
                            self.conn.execute("UPDATE sampling_weeks SET week_number=? WHERE id=?", (n, r["id"]))
                            taken[n] = r["id"]
                        fixed += 1
            finally:
                if before is not None:
                    self.conn.execute("UPDATE sync_state SET value=? WHERE key='applying'", (before,))
                self.conn.commit()
        return fixed

    def _dedupe_weeks(self, season: int) -> int:
        """Semanas repetidas (misma fecha con dos números: quedaban así al llegar otra
        Semana 1, y la siguiente apertura de la app se caía): se juntan en una. Se queda la
        que ya viaja (tiene uid) o la que tiene registros."""
        dup = self.query("SELECT start_date FROM sampling_weeks WHERE season=? "
                         "GROUP BY start_date HAVING COUNT(*) > 1", (season,))
        n = 0
        for d in dup:
            rows = self.query("SELECT id, uid FROM sampling_weeks WHERE season=? AND start_date=?",
                              (season, d["start_date"]))
            rows.sort(key=lambda r: (r["uid"] is None, not self._week_has_data(r["id"]), r["id"]))
            keep = rows[0]["id"]
            for r in rows[1:]:
                self._merge_week(r["id"], keep)
                n += 1
        return n

    # ------------------------------------------------- muestreo extra («Semana 44.5»)
    def extra_week(self, week: dict) -> dict | None:
        """Muestreo extra de la semana `week` (None si no tiene)."""
        n = float(week["week_number"])
        if n % 1:
            return week
        return self.query_one("SELECT * FROM sampling_weeks WHERE season=? AND week_number=?",
                              (week["season"], n + .5))

    def regular_week(self, week: dict) -> dict:
        """La semana normal de un muestreo extra (o la misma semana)."""
        n = float(week["week_number"])
        if not n % 1:
            return week
        return self.ensure_week(week["season"], int(n))

    def add_extra_week(self, week: dict, day: _dt.date) -> dict:
        """Segundo muestreo de la semana, el día `day` (dentro de la semana, después de su
        primer día). Uno por semana: si ya existe, le cambia la fecha. Viaja a los otros
        equipos como cualquier registro."""
        base = self.regular_week(week)
        start = _dt.date.fromisoformat(base["start_date"][:10])
        if not start < day <= start + _dt.timedelta(days=6):
            raise ValueError("La fecha del muestreo extra debe caer dentro de la semana, después de su primer día.")
        n = float(base["week_number"]) + .5
        old = self.extra_week(base)
        if old:
            # La fecha es su identidad entre equipos (uid): cambia junto con ella.
            self.execute("UPDATE sampling_weeks SET start_date=?, label=?, uid=? WHERE id=?",
                         (day.isoformat(), ph.week_label(day, extra=True), day.isoformat(), old["id"]))
            self.log("update", "extra_week", old["id"], day.isoformat())
            return self.get_week(old["id"])
        self.execute("INSERT INTO sampling_weeks(season, week_number, start_date, label) VALUES (?,?,?,?)",
                     (base["season"], n, day.isoformat(), ph.week_label(day, extra=True)))
        row = self.query_one("SELECT * FROM sampling_weeks WHERE season=? AND week_number=?", (base["season"], n))
        self.log("create", "extra_week", row["id"], day.isoformat())
        return row

    def delete_extra_week(self, week: dict) -> None:
        """Quita el muestreo extra con todo lo registrado en él."""
        if not ph.is_extra(week):
            raise ValueError("Solo se puede quitar un muestreo extra.")
        self.execute("DELETE FROM variety_attachments WHERE week_id=?", (week["id"],))
        self.execute("DELETE FROM sampling_weeks WHERE id=?", (week["id"],))
        self.log("delete", "extra_week", week["id"], week["start_date"])

    def week_end(self, week: dict) -> _dt.date:
        """Último día de la semana (también del muestreo extra: el de su semana)."""
        return _dt.date.fromisoformat(self.regular_week(week)["start_date"][:10]) + _dt.timedelta(days=6)

    def next_week(self, week: dict, delta: int) -> dict:
        """Semana siguiente (+1) o anterior (-1), pasando por el muestreo extra si lo hay:
        44 → 44.5 → 45 y al revés."""
        base = self.regular_week(week)
        start = _dt.date.fromisoformat(base["start_date"][:10])
        extra = ph.is_extra(week)
        if delta > 0:
            if not extra:
                ex = self.extra_week(base)
                if ex:
                    return ex
            return self.week_for_date(start + _dt.timedelta(days=7))
        if extra:
            return base
        prev = self.week_for_date(start - _dt.timedelta(days=7))
        return self.extra_week(prev) or prev

    def _week_has_data(self, week_id: int) -> bool:
        return any(self.conn.execute(f"SELECT 1 FROM {t} WHERE week_id=? LIMIT 1", (week_id,)).fetchone()
                   for t in self.WEEK_TABLES)

    def _merge_week(self, src: int, dst: int) -> None:
        """Registros de la semana `src` a `dst` (lo que ya está en `dst` se conserva) y se
        borra `src`."""
        for t in self.WEEK_TABLES:
            self.conn.execute(f"UPDATE OR IGNORE {t} SET week_id=? WHERE week_id=?", (dst, src))
        self.conn.execute("DELETE FROM sampling_weeks WHERE id=?", (src,))

    # ------------------------------------- mover los datos de una semana a otra
    _OBS_FILLED = ("(o.bbch_code IS NOT NULL OR o.ai_code IS NOT NULL OR IFNULL(o.notes, '') != '' "
                   "OR o.latitude IS NOT NULL OR EXISTS (SELECT 1 FROM photos p WHERE p.observation_id = o.id))")

    def observation_is_empty(self, obs_id: int) -> bool:
        """Registro creado al abrir la ficha, sin estado, nota, ubicación ni fotos."""
        return not self.query_one(f"SELECT 1 FROM observations o WHERE o.id=? AND {self._OBS_FILLED}",
                                  (obs_id,))

    def week_data_summary(self, week_id: int) -> dict:
        """Lo registrado en una semana: {"records", "photos", "entries", "attachments",
        "total", "names"} (names: las parcelas/variedades con registro)."""
        recs = self.query(f"SELECT o.id, v.name FROM observations o JOIN varieties v ON v.id = o.variety_id "
                          f"WHERE o.week_id=? AND {self._OBS_FILLED} ORDER BY v.sort_order, v.name", (week_id,))
        photos = self.query_one("SELECT COUNT(*) AS n FROM photos p JOIN observations o ON o.id = p.observation_id "
                                "WHERE o.week_id=?", (week_id,))["n"]
        entries = self.query_one("SELECT COUNT(*) AS n FROM measure_entries WHERE week_id=?", (week_id,))["n"]
        att = self.query_one("SELECT COUNT(*) AS n FROM variety_attachments WHERE week_id=?", (week_id,))["n"]
        return {"records": len(recs), "photos": photos, "entries": entries, "attachments": att,
                "total": len(recs) + entries + att, "names": [r["name"] for r in recs]}

    def move_week_data(self, src_id: int, dst_id: int) -> dict:
        """Pasa TODO lo registrado en la semana `src_id` (estados, fotos, notas, mediciones y
        adjuntos) a la semana `dst_id` (p. ej. se muestreó esta semana pero se anotó en la
        hoja de la siguiente). Nada se borra ni queda atrás: si una parcela ya tiene un
        registro con datos en la semana de destino, los dos se JUNTAN (las fotos se suman; el
        estado BBCH, la ubicación y la IA se completan si allá faltaban; las notas se agregan;
        se cuenta en "merged"). Los registros vacíos del destino se reemplazan. Viaja a los
        otros equipos."""
        if src_id == dst_id:
            raise ValueError("Elija una semana distinta.")
        src, dst = self.get_week(src_id), self.get_week(dst_id)
        if not src or not dst:
            raise ValueError("Semana no encontrada.")
        moved = merged = 0
        photo_ids = []
        for o in self.query("SELECT * FROM observations WHERE week_id=?", (src_id,)):
            other = self.get_observation(o["variety_id"], dst_id)
            src_empty = self.observation_is_empty(o["id"])
            if other is not None:
                if self.observation_is_empty(other["id"]):
                    self.execute("DELETE FROM observations WHERE id=?", (other["id"],))
                elif src_empty:
                    self.execute("DELETE FROM observations WHERE id=?", (o["id"],))
                    continue
                else:
                    photo_ids += self._merge_observation(o, other)
                    merged += 1
                    continue
            self.execute("UPDATE observations SET week_id=?, updated_at=? WHERE id=?", (dst_id, _now(), o["id"]))
            if not src_empty:
                moved += 1
            photo_ids += [p["id"] for p in self.query("SELECT id FROM photos WHERE observation_id=?", (o["id"],))]
        # Archivos que cambian de semana: (tabla, id, ruta, subcarpeta en Drive).
        files = [("photos", r["id"], r["path"], "") for r in self.query(
            f"SELECT id, path FROM photos WHERE id IN ({','.join(str(i) for i in photo_ids) or '0'})")]
        files += [("variety_attachments", r["id"], r["path"], "Adjuntas") for r in self.query(
            "SELECT id, path FROM variety_attachments WHERE week_id=? AND path IS NOT NULL", (src_id,))]
        files += [("measure_entries", r["id"], r["path"], r["mname"]) for r in self.query(
            "SELECT e.id, e.path, m.name AS mname FROM measure_entries e JOIN measures m ON m.id = e.measure_id "
            "WHERE e.week_id=? AND e.path IS NOT NULL AND e.path != ''", (src_id,))]
        entries = self.execute("UPDATE measure_entries SET week_id=? WHERE week_id=?", (dst_id, src_id)).rowcount
        att = self.execute("UPDATE variety_attachments SET week_id=? WHERE week_id=?", (dst_id, src_id)).rowcount
        # Las fotos llevan la fecha de su semana en el nombre (20261012-C11G.jpg): pasa a la de
        # la nueva semana (también en la cola de Drive). En el próximo respaldo, lo ya subido
        # se MUEVE y renombra en Drive (DriveBackup.relocate_weeks), aunque lo haya subido
        # otro equipo; lo pendiente sube directo a la carpeta nueva.
        d1 = _dt.date.fromisoformat(src["start_date"][:10]).strftime(ph.PHOTO_DATE_FMT)
        d2 = _dt.date.fromisoformat(dst["start_date"][:10]).strftime(ph.PHOTO_DATE_FMT)
        todo = [m for m in (self.get_setting("week_moves_drive") or []) if isinstance(m, dict)]
        for table, rid, path, sub in files:
            old_base = os.path.basename(path or "")
            new_path = path
            if old_base.startswith(d1) and d1 != d2:
                folder, rest = os.path.dirname(path), old_base[len(d1):]
                stem, ext = os.path.splitext(d2 + rest)
                cand, n = os.path.join(folder, stem + ext), 2
                while os.path.exists(cand) or self.query_one(f"SELECT 1 FROM {table} WHERE path=?", (cand,)):
                    cand, n = os.path.join(folder, f"{stem}-{n}{ext}"), n + 1
                try:
                    if os.path.exists(path):
                        os.rename(path, cand)
                    new_path = cand
                except OSError:
                    new_path = path
                if new_path != path:
                    self.execute(f"UPDATE {table} SET path=? WHERE id=?", (new_path, rid))
                    self.execute("UPDATE drive_queue SET path=? WHERE path=?", (new_path, path))
            todo.append({"old": old_base, "path": new_path, "src": src["start_date"][:10],
                         "dst": dst["start_date"][:10], "sub": sub})
        self.set_setting("week_moves_drive", todo)
        self.log("update", "week_move", dst_id, f"{src['start_date']} → {dst['start_date']}: "
                                                f"{moved} registros, {entries} mediciones, {att} adjuntos")
        return {"records": moved, "entries": entries, "attachments": att, "merged": merged}

    def _merge_observation(self, o: dict, dst: dict) -> list[int]:
        """Junta el registro `o` en `dst` (misma parcela, otra semana) y borra `o`. Devuelve
        las fotos que pasaron."""
        ids = []
        for p in self.query("SELECT * FROM photos WHERE observation_id=? ORDER BY id", (o["id"],)):
            primary = p["is_primary"] and not self.query_one(
                "SELECT 1 FROM photos WHERE observation_id=? AND kind=? AND is_primary=1", (dst["id"], p["kind"]))
            self.execute("UPDATE photos SET observation_id=?, is_primary=? WHERE id=?",
                         (dst["id"], int(bool(primary)), p["id"]))
            ids.append(p["id"])
        sets = {}
        for col in ("bbch_code", "bbch_label", "ai_code", "ai_confidence", "ai_detail", "ai_accepted",
                    "observed_at", "latitude", "longitude", "gps_accuracy", "gps_source"):
            if dst.get(col) in (None, "") and o.get(col) not in (None, ""):
                sets[col] = o[col]
        extra = (o.get("notes") or "").strip()
        if o.get("bbch_code") is not None and dst.get("bbch_code") not in (None, o["bbch_code"]):
            extra = (f"Estado del registro movido: BBCH {ph.code_str(o['bbch_code'])}" + (f". {extra}" if extra else ""))
        notes = [n for n in ((dst.get("notes") or "").strip(), extra) if n]
        if len(notes) == 2 and notes[1] not in notes[0]:
            sets["notes"] = notes[0] + "\n" + notes[1]
        elif notes and not (dst.get("notes") or "").strip():
            sets["notes"] = notes[0]
        if sets:
            self.execute(f"UPDATE observations SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?",
                         (*sets.values(), _now(), dst["id"]))
        self.execute("DELETE FROM observations WHERE id=?", (o["id"],))
        return ids

    def fix_week_names(self) -> int:
        """Una vez: fotos (de registros, adjuntas y de mediciones) cuyo nombre lleva la fecha
        de OTRA semana (movidas antes de que «Mover datos de semana» las renombrara): toman
        la fecha de su semana y quedan en la lista para moverlas y renombrarlas en Drive."""
        if self.get_setting("week_names_fixed_v2"):
            return 0
        rows = [("photos", r) for r in self.query(
            "SELECT p.id, p.path, w.start_date, '' AS sub FROM photos p JOIN observations o "
            "ON o.id = p.observation_id JOIN sampling_weeks w ON w.id = o.week_id")]
        rows += [("variety_attachments", r) for r in self.query(
            "SELECT a.id, a.path, w.start_date, 'Adjuntas' AS sub FROM variety_attachments a "
            "JOIN sampling_weeks w ON w.id = a.week_id WHERE a.path IS NOT NULL")]
        rows += [("measure_entries", r) for r in self.query(
            "SELECT e.id, e.path, w.start_date, m.name AS sub FROM measure_entries e JOIN measures m "
            "ON m.id = e.measure_id JOIN sampling_weeks w ON w.id = e.week_id "
            "WHERE e.path IS NOT NULL AND e.path != ''")]
        todo = [m for m in (self.get_setting("week_moves_drive") or []) if isinstance(m, dict)]
        n = 0
        for table, r in rows:
            base = os.path.basename(r["path"])
            want = _dt.date.fromisoformat(r["start_date"][:10]).strftime(ph.PHOTO_DATE_FMT)
            m = re.match(r"(\d{8})(?=\D)", base)
            if not m or m[1] == want:
                continue
            try:
                old_day = _dt.datetime.strptime(m[1], ph.PHOTO_DATE_FMT).date()
            except ValueError:
                continue                                  # otro formato (p. ej. ddmmaaaa antiguo)
            if not 2020 <= old_day.year <= 2050:
                continue
            folder = os.path.dirname(r["path"])
            stem, ext = os.path.splitext(want + base[8:])
            cand, k = os.path.join(folder, stem + ext), 2
            while os.path.exists(cand) or self.query_one(f"SELECT 1 FROM {table} WHERE path=?", (cand,)):
                cand, k = os.path.join(folder, f"{stem}-{k}{ext}"), k + 1
            try:
                if os.path.exists(r["path"]):
                    os.rename(r["path"], cand)
            except OSError:
                continue
            self.execute(f"UPDATE {table} SET path=? WHERE id=?", (cand, r["id"]))
            self.execute("UPDATE drive_queue SET path=? WHERE path=?", (cand, r["path"]))
            todo.append({"old": base, "path": cand, "src": old_day.isoformat(),
                         "dst": r["start_date"][:10], "sub": r["sub"]})
            n += 1
        if todo:
            self.set_setting("week_moves_drive", todo)
        self.set_setting("week_names_fixed_v2", True)
        return n

    def ensure_week(self, season: int, number: int) -> dict:
        """Semana n.º `number` de la temporada (se crea si no existe). Puede ser 0 o negativa:
        semanas anteriores a la semana de referencia (las flechas recorren 2020-2050)."""
        row = self.query_one(
            "SELECT * FROM sampling_weeks WHERE season=? AND week_number=?", (season, number))
        if row:
            return row
        start = ph.week_start(self.season_start(season), number)
        if self.query_one("SELECT 1 FROM sampling_weeks WHERE season=? AND start_date=?",
                          (season, start.isoformat())):
            # Ya existe con otro número (cambió la Semana 1): se renumera, no se duplica.
            self.renumber_weeks(season)
            row = self.query_one(
                "SELECT * FROM sampling_weeks WHERE season=? AND week_number=?", (season, number))
            if row:
                return row
        self.execute(
            "INSERT OR IGNORE INTO sampling_weeks(season, week_number, start_date, label) "
            "VALUES (?,?,?,?)", (season, number, start.isoformat(), ph.week_label(start)))
        # Una semana creada sola (al navegar o en un equipo recién instalado) no viaja: así
        # no pisa en los otros equipos la marca «no muestreada». Si se cambia, sí viaja.
        self.execute("DELETE FROM sync_dirty WHERE entity='sampling_weeks' AND uid=?", (start.isoformat(),))
        return self.query_one(
            "SELECT * FROM sampling_weeks WHERE season=? AND week_number=?", (season, number))

    def ensure_weeks(self, season: int, up_to: int) -> list[dict]:
        for n in range(1, max(1, up_to) + 1):
            self.ensure_week(season, n)
        return self.list_weeks(season)

    def list_weeks(self, season: int, include_skipped: bool = True,
                   trim_empty: bool | None = None) -> list[dict]:
        """Semanas de la temporada. include_skipped=False quita las marcadas como
        «no muestreada» (los informes de varias semanas no las muestran).
        trim_empty (por defecto, igual que en los informes): quita las semanas vacías del
        comienzo (la temporada parte en abril aunque se muestree desde más tarde)."""
        sql = "SELECT * FROM sampling_weeks WHERE season=?"
        if not include_skipped:
            sql += " AND COALESCE(skipped, 0) = 0"
        weeks = self.query(sql + " ORDER BY week_number", (season,))
        if trim_empty if trim_empty is not None else not include_skipped:
            last = self._data_week_bound(season, "MAX")
            if last is not None:
                first = self.report_first_week(season)
                weeks = [w for w in weeks if first <= w["week_number"] <= last] or weeks
        return weeks

    # Primera semana de muestreo: por defecto, la primera con datos; en Ajustes se puede fijar
    # otra. Solo decide desde dónde muestran la matriz y los informes: no cambia ninguna fecha.
    def first_week_date(self, season: int) -> _dt.date | None:
        raw = self.get_setting(f"first_week:{season}")
        return _dt.date.fromisoformat(raw) if raw else None

    def set_first_week(self, season: int, start: _dt.date | None) -> None:
        if start is None:
            self.execute("DELETE FROM settings WHERE key=?", (f"first_week:{season}",))
        else:
            self.set_setting(f"first_week:{season}", start.isoformat())
        self.log("update", "first_week", season, start.isoformat() if start else "automática")

    def report_first_week(self, season: int) -> int | None:
        """N.º de la semana desde la que parten matriz e informes."""
        fixed = self.first_week_date(season)
        if fixed is not None:
            return ph.week_number_for(fixed, self.season_start(season))
        return self.first_week_with_data(season)

    def first_week_with_data(self, season: int) -> int | None:
        """N.º de la primera semana con algún registro (estado, foto, nota, medición o
        foto adjunta); None si la temporada está vacía."""
        return self._data_week_bound(season, "MIN")

    def _data_week_bound(self, season: int, fn: str) -> int | None:
        row = self.query_one(
            f"SELECT {fn}(w.week_number) AS n FROM sampling_weeks w WHERE w.season=? AND ("
            " EXISTS (SELECT 1 FROM observations o WHERE o.week_id=w.id AND (o.bbch_code IS NOT NULL"
            "   OR COALESCE(o.notes, '') <> '' OR EXISTS (SELECT 1 FROM photos p WHERE p.observation_id=o.id)))"
            " OR EXISTS (SELECT 1 FROM measure_entries e WHERE e.week_id=w.id)"
            " OR EXISTS (SELECT 1 FROM variety_attachments a WHERE a.week_id=w.id))", (season,))
        return row["n"] if row else None

    def season_list(self, today: _dt.date | None = None) -> list[dict]:
        """Temporadas de este ensayo (la más nueva primero) con cuántos registros tiene
        cada una; siempre incluye la temporada en curso."""
        now = ph.season_of(today or _dt.date.today())
        found = {r["season"] for r in self.query("SELECT DISTINCT season FROM sampling_weeks")}
        out = []
        for s in sorted(found | {now}, reverse=True):
            first, last = ph.season_bounds(s)
            out.append({"season": s, "title": ph.season_title(s), "current": s == now,
                        "records": self.count_observations(s), "first": first, "last": last})
        return out

    def last_week(self, season: int) -> dict | None:
        """Última semana con registros de la temporada (o la última creada)."""
        row = self.query_one(
            "SELECT w.* FROM sampling_weeks w JOIN observations o ON o.week_id=w.id "
            "WHERE w.season=? AND (o.bbch_code IS NOT NULL OR EXISTS "
            "(SELECT 1 FROM photos p WHERE p.observation_id=o.id)) "
            "ORDER BY w.week_number DESC LIMIT 1", (season,))
        return row or self.query_one(
            "SELECT * FROM sampling_weeks WHERE season=? ORDER BY week_number DESC LIMIT 1", (season,))

    def set_week_skipped(self, week_id: int, skipped: bool) -> None:
        self.execute("UPDATE sampling_weeks SET skipped=? WHERE id=?", (int(bool(skipped)), week_id))
        self.log("update", "week", week_id, "omitida" if skipped else "incluida")

    def get_week(self, week_id: int) -> dict | None:
        return self.query_one("SELECT * FROM sampling_weeks WHERE id=?", (week_id,))

    def week_for_date(self, date: _dt.date, season: int | None = None) -> dict:
        season = season if season is not None else ph.season_of(date)
        n = ph.week_number_for(date, self.season_start(season))
        return self.ensure_week(season, n)

    def current_week(self, today: _dt.date | None = None) -> dict:
        today = today or _dt.date.today()
        season = self.current_season(today)
        week = self.week_for_date(today, season)
        # Garantiza que existan las semanas previas desde la de referencia.
        if week["week_number"] >= 1:
            self.ensure_weeks(season, week["week_number"])
        return week

    # ----------------------------------------------------------- observations
    def photo_locations(self, season: int, week_id: int | None = None) -> tuple[list[dict], int]:
        """Registros con fotos y ubicación (mapa de calor): [{lat, lon, weight=n.º de fotos,
        variety_id, week_id, …}] y cuántas fotos de la temporada no tienen ubicación."""
        where = "w.season=? AND COALESCE(w.skipped, 0) = 0"
        params: list = [season]
        if week_id is not None:
            where += " AND w.id=?"
            params.append(week_id)
        rows = self.query(
            "SELECT o.id, o.variety_id, o.week_id, o.latitude AS lat, o.longitude AS lon, o.bbch_code, "
            "o.gps_source, w.start_date, COUNT(p.id) AS weight FROM observations o "
            "JOIN sampling_weeks w ON w.id = o.week_id JOIN photos p ON p.observation_id = o.id "
            f"WHERE {where} GROUP BY o.id", params)
        located = [r for r in rows if r["lat"] is not None and r["lon"] is not None]
        missing = sum(r["weight"] for r in rows if r["lat"] is None or r["lon"] is None)
        return located, missing

    def get_observation(self, variety_id: int, week_id: int) -> dict | None:
        return self.query_one(
            "SELECT * FROM observations WHERE variety_id=? AND week_id=?", (variety_id, week_id))

    def get_or_create_observation(self, variety_id: int, week_id: int) -> dict:
        obs = self.get_observation(variety_id, week_id)
        if obs:
            return obs
        now = _now()
        self.execute(
            "INSERT OR IGNORE INTO observations(variety_id, week_id, created_at, updated_at) "
            "VALUES (?,?,?,?)", (variety_id, week_id, now, now))
        obs = self.get_observation(variety_id, week_id)
        self.log("create", "observation", obs["id"], f"variety={variety_id} week={week_id}")
        return obs

    def update_observation(self, observation_id: int, **fields: Any) -> None:
        allowed = {"bbch_code", "bbch_label", "ai_code", "ai_confidence", "ai_detail",
                   "ai_accepted", "notes", "observed_at", "latitude", "longitude",
                   "gps_accuracy", "gps_source"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k}=?" for k in sets)
        self.execute(f"UPDATE observations SET {cols}, updated_at=? WHERE id=?",
                     (*sets.values(), _now(), observation_id))
        self.log("update", "observation", observation_id,
                 json.dumps({k: v for k, v in sets.items() if k != "ai_detail"},
                            ensure_ascii=False))

    def previous_observation(self, variety_id: int, season: int, week_number: int) -> dict | None:
        """Última observación con BBCH de la variedad antes de `week_number`."""
        return self.query_one(
            "SELECT o.*, w.week_number FROM observations o "
            "JOIN sampling_weeks w ON w.id = o.week_id "
            "WHERE o.variety_id=? AND w.season=? AND w.week_number<? AND o.bbch_code IS NOT NULL "
            "ORDER BY w.week_number DESC LIMIT 1", (variety_id, season, week_number))

    def count_observations(self, season: int) -> int:
        row = self.query_one(
            "SELECT COUNT(*) AS n FROM observations o JOIN sampling_weeks w ON w.id=o.week_id "
            "WHERE w.season=? AND (o.bbch_code IS NOT NULL OR EXISTS "
            "(SELECT 1 FROM photos p WHERE p.observation_id=o.id))", (season,))
        return row["n"]

    # ----------------------------------------------------------------- photos
    def add_photo(self, observation_id: int, kind: str, path: str, source: str = "camera",
                  captured_at: str | None = None, primary: bool | None = None) -> int:
        """Agrega una foto; la primera de cada tipo queda como principal."""
        with self._lock:
            has_primary = self.query_one(
                "SELECT 1 FROM photos WHERE observation_id=? AND kind=? AND is_primary=1",
                (observation_id, kind))
            make_primary = (not has_primary) if primary is None else primary
            cur = self.execute(
                "INSERT INTO photos(observation_id, kind, path, source, captured_at, is_primary) "
                "VALUES (?,?,?,?,?,0)", (observation_id, kind, path, source, captured_at or _now()))
            if make_primary:
                self.set_primary(cur.lastrowid)
        self.log("add", "photo", cur.lastrowid, f"{kind} <- {os.path.basename(path)} ({source})")
        return cur.lastrowid

    def set_photo(self, observation_id: int, kind: str, path: str,
                  source: str = "camera", captured_at: str | None = None) -> int:
        """Agrega la foto y la deja como principal (compatibilidad con v1)."""
        return self.add_photo(observation_id, kind, path, source, captured_at, primary=True)

    def set_primary(self, photo_id: int) -> None:
        p = self.query_one("SELECT observation_id, kind FROM photos WHERE id=?", (photo_id,))
        if not p:
            return
        with self._lock:
            self.conn.execute("UPDATE photos SET is_primary=0 WHERE observation_id=? AND kind=?",
                              (p["observation_id"], p["kind"]))
            self.conn.execute("UPDATE photos SET is_primary=1 WHERE id=?", (photo_id,))
            self.conn.commit()

    def get_photos(self, observation_id: int) -> dict[str, dict]:
        """Foto PRINCIPAL de cada tipo: {'canopy': fila, 'detail': fila}. Si la principal
        no está en el teléfono (aún no se baja de Drive) o ningún tipo tiene principal, va
        otra foto de ese tipo que sí esté (la más reciente)."""
        out: dict[str, dict] = {}
        for r in self.query("SELECT * FROM photos WHERE observation_id=? "
                            "ORDER BY is_primary DESC, captured_at DESC, id DESC", (observation_id,)):
            cur = out.get(r["kind"])
            if cur is None or (not os.path.exists(cur["path"] or "") and os.path.exists(r["path"] or "")):
                out[r["kind"]] = r
        return out

    def register_missing_photos(self) -> int:
        """Fotos de registros cuyo archivo no está en el teléfono: quedan en la lista para
        bajarlas de Drive (sincronización). Devuelve cuántas faltan."""
        n = 0
        has = self.query_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_missing'")
        for r in self.query("SELECT path FROM photos"):
            if r["path"] and not os.path.exists(r["path"]):
                n += 1
                if has:
                    self.execute("INSERT OR IGNORE INTO sync_missing(path) VALUES (?)", (r["path"],))
        return n

    def list_photos(self, observation_id: int, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM photos WHERE observation_id=?"
        params: tuple = (observation_id,)
        if kind:
            sql += " AND kind=?"
            params += (kind,)
        return self.query(sql + " ORDER BY is_primary DESC, captured_at, id", params)

    def delete_photo(self, photo_id: int) -> None:
        p = self.query_one("SELECT * FROM photos WHERE id=?", (photo_id,))
        # Si aún no se había subido a Drive, ya no hay nada que subir.
        self.execute("UPDATE drive_queue SET status='skipped', error='Foto eliminada en la app' "
                     "WHERE photo_id=? AND status IN ('pending', 'error')", (photo_id,))
        self.execute("DELETE FROM photos WHERE id=?", (photo_id,))
        if p and p["is_primary"]:  # promover la siguiente como principal
            nxt = self.query_one("SELECT id FROM photos WHERE observation_id=? AND kind=? "
                                 "ORDER BY captured_at DESC, id DESC LIMIT 1",
                                 (p["observation_id"], p["kind"]))
            if nxt:
                self.set_primary(nxt["id"])
        self.log("delete", "photo", photo_id)

    def list_detail_photos(self, season: int | None = None) -> list[dict]:
        """Fotos de detalle con su BBCH asignado (para etiquetado en la calibración)."""
        sql = ("SELECT p.*, o.bbch_code, o.variety_id, v.name AS variety_name, "
               "w.week_number, w.start_date, w.label AS week_label, w.season, "
               "0 AS in_reference "
               "FROM photos p JOIN observations o ON o.id = p.observation_id "
               "JOIN varieties v ON v.id = o.variety_id "
               "JOIN sampling_weeks w ON w.id = o.week_id WHERE p.kind='detail'")
        params: tuple = ()
        if season is not None:
            sql += " AND w.season=?"
            params = (season,)
        rows = self.query(sql + " ORDER BY w.week_number DESC, v.sort_order", params)
        in_ref = self.referenced_photo_ids()
        for r in rows:
            r["in_reference"] = int(r["id"] in in_ref)
        return rows

    # ---------------------------------------------------------- aggregations
    def week_overview(self, week_id: int, include_archived: bool = False) -> list[dict]:
        """Una fila por variedad con su observación y fotos para la semana indicada."""
        out = []
        for v in self.pheno_units(include_archived=include_archived):
            obs = self.get_observation(v["id"], week_id)
            photos = self.get_photos(obs["id"]) if obs else {}
            out.append({"variety": v, "observation": obs, "photos": photos})
        return out

    def variety_timeline(self, variety_id: int, season: int) -> list[dict]:
        rows = self.query(
            "SELECT o.*, w.week_number, w.start_date, w.label AS week_label "
            "FROM observations o JOIN sampling_weeks w ON w.id=o.week_id "
            "WHERE o.variety_id=? AND w.season=? AND COALESCE(w.skipped, 0) = 0 "
            "ORDER BY w.week_number",
            (variety_id, season))
        for r in rows:
            r["photos"] = self.get_photos(r["id"])
        return rows

    def phenology_matrix(self, season: int) -> dict[tuple[int, int], dict]:
        """{(variety_id, week_number): observación} para la temporada."""
        rows = self.query(
            "SELECT o.*, w.week_number FROM observations o "
            "JOIN sampling_weeks w ON w.id=o.week_id WHERE w.season=?", (season,))
        return {(r["variety_id"], r["week_number"]): r for r in rows}

    def seasons(self) -> list[int]:
        rows = self.query("SELECT DISTINCT season FROM sampling_weeks ORDER BY season DESC")
        return [r["season"] for r in rows]

    # ------------------------------------------------------------------ BBCH
    def list_bbch(self) -> list[dict]:
        """Escala ordenada por su posición (los subestadios 89-1… van entre 89 y 91)."""
        return ph.bbch_sorted(self.ai_db.query("SELECT * FROM bbch_stages"))

    def bbch_names(self) -> dict[int, str]:
        return {r["code"]: r["label"] for r in self.list_bbch()}

    def upsert_bbch(self, code: int, label: str, description: str = "",
                    keywords: str = "", source: str = "user") -> None:
        self.ai_db.execute(
            "INSERT INTO bbch_stages(code, label, description, keywords, source) "
            "VALUES (?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET label=excluded.label, "
            "description=excluded.description, keywords=excluded.keywords, "
            "source=excluded.source", (int(code), label, description, keywords, source))

    # --------------------------------------------------------- AI references
    def add_reference(self, bbch_code: int, extractor: str, embedding: bytes, dim: int,
                      image_path: str | None = None, photo_id: int | None = None) -> int:
        """La referencia se guarda en la memoria común; photo_id se refiere a una foto de
        ESTE ensayo (se distingue por el código del ensayo)."""
        ai = self.ai_db
        if photo_id is not None:
            # Una foto solo aporta una referencia por extractor (re-etiquetar la reemplaza).
            ai.execute("DELETE FROM ai_references WHERE photo_id=? AND extractor=? "
                       "AND COALESCE(workspace, '')=?", (photo_id, extractor, self.code))
        cur = ai.execute(
            "INSERT INTO ai_references(bbch_code, extractor, embedding, dim, image_path, "
            "photo_id, created_at, workspace) VALUES (?,?,?,?,?,?,?,?)",
            (int(bbch_code), extractor, embedding, dim, image_path, photo_id, _now(), self.code))
        self.log("create", "ai_reference", cur.lastrowid, f"BBCH {bbch_code}")
        return cur.lastrowid

    def list_references(self, extractor: str | None = None) -> list[dict]:
        if extractor:
            return self.ai_db.query("SELECT * FROM ai_references WHERE extractor=? ORDER BY id",
                                    (extractor,))
        return self.ai_db.query("SELECT * FROM ai_references ORDER BY id")

    def referenced_photo_ids(self) -> set[int]:
        """Fotos de este ensayo que ya están en la memoria de la IA."""
        return {r["photo_id"] for r in self.ai_db.query(
            "SELECT photo_id FROM ai_references WHERE photo_id IS NOT NULL "
            "AND COALESCE(workspace, '')=?", (self.code,))}

    def delete_reference(self, ref_id: int) -> None:
        self.ai_db.execute("DELETE FROM ai_references WHERE id=?", (ref_id,))
        self.log("delete", "ai_reference", ref_id)

    def reference_counts(self) -> dict[int, int]:
        return {r["bbch_code"]: r["n"] for r in self.ai_db.query(
            "SELECT bbch_code, COUNT(*) AS n FROM ai_references GROUP BY bbch_code")}

    # -------------------------------------------------------------- documents
    def add_document(self, title: str, path: str | None, text: str, stages_found: int) -> int:
        cur = self.ai_db.execute(
            "INSERT INTO documents(title, path, text, stages_found, created_at) "
            "VALUES (?,?,?,?,?)", (title, path, text, stages_found, _now()))
        self.log("create", "document", cur.lastrowid, title)
        return cur.lastrowid

    def list_documents(self) -> list[dict]:
        return self.ai_db.query("SELECT id, title, path, stages_found, created_at, "
                                "LENGTH(text) AS chars FROM documents ORDER BY id DESC")

    def documents_text(self) -> str:
        return "\n".join(r["text"] for r in self.ai_db.query("SELECT text FROM documents"))

    def delete_document(self, doc_id: int) -> None:
        self.ai_db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        self.log("delete", "document", doc_id)


def default_db_path() -> str:
    from platform_utils import get_data_dir
    return os.path.join(get_data_dir(), "fenorubus.sqlite3")
