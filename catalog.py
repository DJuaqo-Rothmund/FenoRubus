"""
catalog.py
==========
Catálogo de variedades del teléfono, separado por perfil (I+D y Predio). Vive en la
base común (comun.sqlite3) y se usa como desplegable al crear variedades, sectores y
al asignar la variedad a un ensayo de tratamientos o a cada tratamiento.

Solo entran nombres reales: nunca «Código 11» (las variedades por código son propias
del ensayo «Nuevas variedades»), ni parcelas «T1R1», ni nombres de unidades de predio.
"""
from __future__ import annotations

import datetime as _dt
import re

PROFILES = ("id", "predio")
_NOT_A_VARIETY = re.compile(
    r"^\s*(c[oó]d(igo)?\.?\s*(n[°º.]?\s*)?\d+|t\d+\s*r\d+|equipo de riego\b|sector\s*\d+)", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS variety_catalog (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT NOT NULL,            -- id | predio
    name        TEXT NOT NULL,
    code        TEXT DEFAULT '',          -- abreviatura para el nombre de las fotos
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_name ON variety_catalog(profile, name COLLATE NOCASE);
"""


def is_real_variety(name: str | None) -> bool:
    name = (name or "").strip()
    return len(name) >= 2 and not _NOT_A_VARIETY.match(name)


def ensure(shared) -> None:
    shared.conn.executescript(SCHEMA)


def entries(shared, profile: str) -> list[dict]:
    ensure(shared)
    return shared.query("SELECT name, code FROM variety_catalog WHERE profile=? "
                        "ORDER BY name COLLATE NOCASE", (profile,))


def add(shared, profile: str, name: str, code: str = "") -> bool:
    """Agrega (o completa el código de) una variedad. False si el nombre no vale."""
    name, code = (name or "").strip(), (code or "").strip()
    if profile not in PROFILES or not is_real_variety(name):
        return False
    ensure(shared)
    cur = shared.query_one("SELECT id, code FROM variety_catalog WHERE profile=? AND name=? COLLATE NOCASE",
                           (profile, name))
    if cur is None:
        shared.execute("INSERT INTO variety_catalog(profile, name, code, created_at) VALUES (?,?,?,?)",
                       (profile, name, code, _dt.datetime.now().isoformat(timespec="seconds")))
    elif code and code != (cur["code"] or ""):
        shared.execute("UPDATE variety_catalog SET code=? WHERE id=?", (code, cur["id"]))
    return True


def remove(shared, profile: str, name: str) -> None:
    ensure(shared)
    shared.execute("DELETE FROM variety_catalog WHERE profile=? AND name=? COLLATE NOCASE", (profile, name))


def code_for(shared, name: str, db=None, profile: str = "predio") -> str:
    """Código de una variedad para completar el formulario, en este orden: el del catálogo
    de este perfil, el de una unidad/variedad ya creada con ese nombre en esta base, el del
    catálogo del otro perfil y, si no hay, la abreviatura de siempre («Meeker» -> «MEE»)."""
    import phenology as ph
    name = (name or "").strip()
    if not name:
        return ""
    ensure(shared)
    sql = ("SELECT code FROM variety_catalog WHERE name=? COLLATE NOCASE AND IFNULL(code,'')<>'' "
           "AND profile{} ? LIMIT 1")
    row = shared.query_one(sql.format("="), (name, profile))
    if row is None and db is not None:
        row = db.query_one("SELECT code FROM varieties WHERE (lower(IFNULL(cultivar,''))=lower(?) "
                           "OR lower(name)=lower(?)) AND IFNULL(code,'')<>'' LIMIT 1", (name, name))
    if row is None:
        row = shared.query_one(sql.format("<>"), (name, profile))
    return row["code"] if row else ph.variety_tag(name).upper()
