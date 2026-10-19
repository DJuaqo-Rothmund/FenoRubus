"""
sync.py
=======
Sincronización entre equipos de una misma cuenta (celular ↔ PC), etapa 1: el motor, sin
transporte. Cada ensayo o predio intercambia «paquetes» de cambios; la etapa 2 los lleva
por Google Drive y la 3 baja las fotos.

* Identificador común (`uid`) en cada registro sincronizado: el mismo registro tiene el
  mismo uid en todos los equipos (los ids numéricos de SQLite son locales). Las semanas
  usan su fecha de inicio; los tratamientos, «T<n>».
* Disparadores de SQLite anotan cada alta, cambio o borrado en `sync_dirty`: ninguna
  pantalla tiene que avisar nada.
* `export_changes` arma el paquete con lo pendiente (claves foráneas como uid y rutas de
  foto relativas a la carpeta de datos); `apply_changes` lo aplica en otro equipo. Si los
  dos cambiaron lo mismo, gana el cambio más reciente.
* Registros creados por separado en cada equipo (una misma variedad, la observación de una
  variedad en una semana…) se reconocen por su clave natural y quedan unificados.

Puro Python (sin Kivy) para probarlo en el PC.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid

FORMAT = 1

# tabla -> (columna de id, expresión SQL del uid nuevo, {columna FK: tabla}, clave natural)
TABLES: dict[str, dict] = {
    "varieties": {"uid": "lower(hex(randomblob(16)))", "fk": {}, "natural": ("name",)},
    "sampling_weeks": {"uid": "NEW.start_date", "fk": {}, "natural": ("start_date",)},
    "treatments": {"pk": "num", "uid": "'T' || NEW.num", "fk": {}, "natural": ("num",)},
    "measures": {"uid": "lower(hex(randomblob(16)))", "fk": {}, "natural": ("name",)},
    "observations": {"uid": "lower(hex(randomblob(16)))",
                     "fk": {"variety_id": "varieties", "week_id": "sampling_weeks"},
                     "natural": ("variety_id", "week_id")},
    "photos": {"uid": "lower(hex(randomblob(16)))", "fk": {"observation_id": "observations"},
               "natural": ("observation_id", "path")},
    "variety_attachments": {"uid": "lower(hex(randomblob(16)))",
                            "fk": {"variety_id": "varieties", "week_id": "sampling_weeks"},
                            "natural": ("variety_id", "path")},
    "measure_entries": {"uid": "lower(hex(randomblob(16)))",
                        "fk": {"measure_id": "measures", "week_id": "sampling_weeks",
                               "variety_id": "varieties"},
                        "natural": ()},
    "variety_metrics": {"uid": "lower(hex(randomblob(16)))", "fk": {"variety_id": "varieties"},
                        "natural": ("variety_id", "season")},
    "custom_fields": {"uid": "lower(hex(randomblob(16)))", "fk": {"variety_id": "varieties"},
                      "natural": ("variety_id", "season", "key")},
}
# Orden de aplicación: primero lo que otros referencian.
ORDER = ["varieties", "sampling_weeks", "treatments", "measures", "observations", "photos",
         "variety_attachments", "measure_entries", "variety_metrics", "custom_fields"]
PATH_COLUMNS = {"photos": "path", "variety_attachments": "path", "measure_entries": "path"}
# Ajustes del ensayo que también viajan (semana de referencia, primera semana fijada…).
SETTING_PREFIXES = ("season_start:", "first_week:", "treatment_")

_NOW = "strftime('%Y-%m-%dT%H:%M:%f', 'now')"


def _pk(table: str) -> str:
    return TABLES[table].get("pk", "id")


def _now() -> str:
    return _dt.datetime.utcnow().isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------- instalación
def install(conn, settings_get=None, settings_set=None) -> None:
    """Agrega uid, la tabla de pendientes y los disparadores (idempotente). Los registros
    existentes reciben su uid y quedan pendientes: el primer envío los manda todos."""
    conn.execute("CREATE TABLE IF NOT EXISTS sync_dirty (entity TEXT NOT NULL, uid TEXT NOT NULL, "
                 "ts TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (entity, uid))")
    conn.execute("CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS sync_seen (name TEXT PRIMARY KEY)")   # paquetes leídos
    conn.execute("INSERT OR IGNORE INTO sync_state(key, value) VALUES ('applying', '0')")
    if not conn.execute("SELECT value FROM sync_state WHERE key='device'").fetchone():
        conn.execute("INSERT INTO sync_state(key, value) VALUES ('device', ?)", (uuid.uuid4().hex[:12],))
    quiet = "(SELECT value FROM sync_state WHERE key='applying') = '0'"
    for table, cfg in TABLES.items():
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not cols:
            continue
        pk = _pk(table)
        fresh = "uid" not in cols
        if fresh:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN uid TEXT")
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uid ON {table}(uid)")
        expr = cfg["uid"].replace("NEW.", "")
        conn.execute(f"UPDATE {table} SET uid = {expr} WHERE uid IS NULL")
        if fresh:
            conn.execute(f"INSERT OR IGNORE INTO sync_dirty(entity, uid, ts) "
                         f"SELECT '{table}', uid, {_NOW} FROM {table}")
        conn.execute(f"DROP TRIGGER IF EXISTS sync_{table}_ins")
        conn.execute(f"DROP TRIGGER IF EXISTS sync_{table}_upd")
        conn.execute(f"DROP TRIGGER IF EXISTS sync_{table}_del")
        mark = (lambda uid: f"DELETE FROM sync_dirty WHERE entity='{table}' AND uid={uid}; "
                f"INSERT INTO sync_dirty(entity, uid, ts, deleted) ")
        conn.execute(
            f"CREATE TRIGGER sync_{table}_ins AFTER INSERT ON {table} BEGIN "
            f"UPDATE {table} SET uid = COALESCE(NEW.uid, {cfg['uid']}) WHERE {pk} = NEW.{pk}; "
            + mark(f"(SELECT uid FROM {table} WHERE {pk} = NEW.{pk})")
            + f"SELECT '{table}', uid, {_NOW}, 0 FROM {table} WHERE {pk} = NEW.{pk} AND {quiet}; END")
        conn.execute(
            f"CREATE TRIGGER sync_{table}_upd AFTER UPDATE ON {table} WHEN NEW.uid IS NOT NULL AND {quiet} "
            f"BEGIN " + mark("NEW.uid") + f"VALUES ('{table}', NEW.uid, {_NOW}, 0); END")
        conn.execute(
            f"CREATE TRIGGER sync_{table}_del AFTER DELETE ON {table} WHEN OLD.uid IS NOT NULL AND {quiet} "
            f"BEGIN " + mark("OLD.uid") + f"VALUES ('{table}', OLD.uid, {_NOW}, 1); END")


def device_id(db) -> str:
    return db.query_one("SELECT value FROM sync_state WHERE key='device'")["value"]


# ---------------------------------------------------------------------- rutas
def _rel_path(path: str | None, data_dir: str) -> str | None:
    if not path:
        return path
    try:
        rel = os.path.relpath(path, data_dir)
    except ValueError:            # otra unidad (Windows)
        rel = ".."
    if rel.startswith(".."):
        return "photos/sincronizadas/" + os.path.basename(path)
    return rel.replace(os.sep, "/")


def _abs_path(rel: str | None, data_dir: str) -> str | None:
    return os.path.join(data_dir, *rel.split("/")) if rel else rel


# ---------------------------------------------------------------------- exportar
def export_changes(db, data_dir: str, settings: dict | None = None) -> dict:
    """Paquete con todo lo pendiente de enviar. `settings`: ajustes del ensayo a incluir
    (por defecto, los de SETTING_PREFIXES)."""
    pending = db.query("SELECT * FROM sync_dirty ORDER BY ts")
    uid_of = _uid_lookup(db)
    changes = []
    for d in pending:
        table = d["entity"]
        if table not in TABLES:
            continue
        row = None if d["deleted"] else db.query_one(f"SELECT * FROM {table} WHERE uid=?", (d["uid"],))
        if row is None:
            changes.append({"entity": table, "uid": d["uid"], "ts": d["ts"], "deleted": 1})
            continue
        data = {k: v for k, v in row.items() if k not in ("id", "uid")}
        for col, ref in TABLES[table]["fk"].items():
            data[col] = uid_of(ref, data.get(col))
        if table in PATH_COLUMNS:
            col = PATH_COLUMNS[table]
            data[col] = _rel_path(data.get(col), data_dir)
        changes.append({"entity": table, "uid": d["uid"], "ts": d["ts"], "deleted": 0, "data": data})
    if settings is None:
        settings = {r["key"]: r["value"] for r in db.query("SELECT key, value FROM settings")
                    if r["key"].startswith(SETTING_PREFIXES)}
    upto = pending[-1]["ts"] if pending else None
    return {"format": FORMAT, "device": device_id(db), "workspace": getattr(db, "code", ""),
            "created": _now(), "upto": upto, "changes": changes, "settings": settings}


def mark_exported(db, bundle: dict) -> None:
    """Tras subir el paquete: quita de pendientes lo enviado (lo que cambió después sigue)."""
    if bundle.get("upto"):
        db.execute("DELETE FROM sync_dirty WHERE ts <= ?", (bundle["upto"],))


def _uid_lookup(db):
    cache: dict = {}

    def get(table, local_id):
        if local_id is None:
            return None
        key = (table, local_id)
        if key not in cache:
            row = db.query_one(f"SELECT uid FROM {table} WHERE {_pk(table)}=?", (local_id,))
            cache[key] = row["uid"] if row else None
        return cache[key]
    return get


# ---------------------------------------------------------------------- aplicar
def apply_changes(db, bundle: dict, data_dir: str, week_for_date=None) -> dict:
    """Aplica un paquete de otro equipo. Si aquí hay un cambio pendiente MÁS NUEVO del mismo
    registro, se conserva el de aquí. Devuelve {"applied", "skipped", "missing_files"}."""
    if bundle.get("device") == device_id(db):
        return {"applied": 0, "skipped": 0, "missing_files": []}
    stats = {"applied": 0, "skipped": 0, "missing_files": []}
    rank = {t: i for i, t in enumerate(ORDER)}
    # Altas y cambios: primero los registros que otros referencian; borrados: al revés.
    changes = sorted(bundle.get("changes", []), key=lambda c: (
        c["deleted"], -rank.get(c["entity"], 99) if c["deleted"] else rank.get(c["entity"], 99), c["ts"]))
    db.execute("UPDATE sync_state SET value='1' WHERE key='applying'")
    try:
        for key, value in (bundle.get("settings") or {}).items():
            if key.startswith(SETTING_PREFIXES):
                db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))
        for ch in changes:
            table = ch["entity"]
            if table not in TABLES:
                continue
            mine = db.query_one("SELECT ts FROM sync_dirty WHERE entity=? AND uid=?", (table, ch["uid"]))
            if mine and mine["ts"] > ch["ts"]:
                stats["skipped"] += 1
                continue
            if ch["deleted"]:
                db.execute(f"DELETE FROM {table} WHERE uid=?", (ch["uid"],))
            elif not _upsert(db, table, ch, data_dir, week_for_date, stats):
                stats["skipped"] += 1
                continue
            if mine:
                db.execute("DELETE FROM sync_dirty WHERE entity=? AND uid=?", (table, ch["uid"]))
            stats["applied"] += 1
    finally:
        db.execute("UPDATE sync_state SET value='0' WHERE key='applying'")
    return stats


def _local_id(db, table, uid):
    if uid is None:
        return None
    row = db.query_one(f"SELECT {_pk(table)} AS id FROM {table} WHERE uid=?", (uid,))
    return row["id"] if row else None


def _upsert(db, table, ch, data_dir, week_for_date, stats) -> bool:
    cfg = TABLES[table]
    pk = _pk(table)
    data = dict(ch["data"])
    for col, ref in cfg["fk"].items():
        ref_uid = data.get(col)
        data[col] = _local_id(db, ref, ref_uid)
        if ref_uid is not None and data[col] is None:
            if ref == "sampling_weeks" and week_for_date:
                week = week_for_date(_dt.date.fromisoformat(ref_uid[:10]))
                data[col] = week["id"]
            elif col in ("variety_id",) and table == "measure_entries":
                data[col] = None           # la variedad ya no existe: la medición queda suelta
            else:
                return False               # su registro padre todavía no llega
    if table in PATH_COLUMNS:
        col = PATH_COLUMNS[table]
        data[col] = _abs_path(data.get(col), data_dir)
        if data[col] and not os.path.exists(data[col]):
            stats["missing_files"].append(data[col])
    if table == "sampling_weeks":
        return _upsert_week(db, ch, data, week_for_date)
    cols = {r["name"] for r in db.query(f"PRAGMA table_info({table})")}
    data = {k: v for k, v in data.items() if k in cols and k not in (pk, "uid")}
    if table == "treatments":
        data["num"] = ch["data"]["num"]
    current = _local_id(db, table, ch["uid"])
    if current is None and cfg["natural"]:
        where = " AND ".join(f"{k} IS ?" for k in cfg["natural"])
        row = db.query_one(f"SELECT {pk} AS id FROM {table} WHERE {where}",
                           tuple(data.get(k) for k in cfg["natural"]))
        if row:                            # el mismo registro creado aquí: queda unificado
            current = row["id"]
            db.execute(f"DELETE FROM sync_dirty WHERE entity=? AND uid=(SELECT uid FROM {table} "
                       f"WHERE {pk}=?)", (table, current))
            db.execute(f"UPDATE {table} SET uid=? WHERE {pk}=?", (ch["uid"], current))
    if current is None:
        names = list(data) + ["uid"]
        db.execute(f"INSERT INTO {table}({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                   (*data.values(), ch["uid"]))
    else:
        sets = ", ".join(f"{k}=?" for k in data if k != "num")
        vals = [v for k, v in data.items() if k != "num"]
        if sets:
            db.execute(f"UPDATE {table} SET {sets} WHERE {pk}=?", (*vals, current))
    return True


def _upsert_week(db, ch, data, week_for_date) -> bool:
    """Las semanas se reconocen por su fecha de inicio: el número interno puede ser otro en
    cada equipo (depende de su semana de referencia)."""
    row = db.query_one("SELECT id FROM sampling_weeks WHERE start_date=?", (ch["uid"],))
    if row is None:
        if week_for_date is None:
            return False
        row = week_for_date(_dt.date.fromisoformat(ch["uid"][:10]))
    db.execute("UPDATE sampling_weeks SET skipped=?, uid=? WHERE id=?",
               (data.get("skipped") or 0, ch["uid"], row["id"]))
    return True


# ---------------------------------------------------------------------- paquetes
def dumps(bundle: dict) -> bytes:
    return json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def loads(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))
