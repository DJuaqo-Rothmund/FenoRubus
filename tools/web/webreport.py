"""
webreport.py
============
Puente de PhenoRubus Web (Pyodide) con el generador de informes de la app: arma una
base SQLite a partir de los paquetes de sincronización (los mismos que lee el celular)
y produce los PDF con reporter.py / pdf_report.py, idénticos a los de la app.
"""
from __future__ import annotations

import json
import os

import phenology as ph
import sync
from database import Database
from reporter import ReportGenerator

DATA = os.environ.setdefault("FENORUBUS_DATA", "/data")
_dbs: dict[str, tuple[Database, set]] = {}
_crop = "frambuesa"


def use_crop(module: str) -> str:
    """Cultivo de los informes (AeonCrop Web): «PhenoBlue» -> arándano (su escala BBCH)."""
    global _crop
    import crops
    _crop = next((c.id for c in crops.CROPS.values() if c.app == module), "frambuesa")
    crops._current = _crop          # nombre del módulo en los informes (sin cambiar carpetas)
    ph.set_crop(_crop)
    return _crop


def _key(code: str) -> str:
    return code if _crop == "frambuesa" else f"{_crop}-{code}"


def _db(code: str, workspace: dict) -> tuple[Database, set]:
    key = _key(code)
    if key not in _dbs:
        db = Database(os.path.join(DATA, f"{key}.sqlite3"), seed=False, code=code, workspace=workspace)
        for c, label, desc, kw in ph.BBCH_SCALE:          # escala BBCH, sin variedades de ejemplo
            db.upsert_bbch(c, label, desc, kw, source="base")
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('seeded', '1')")
        db.refresh_bbch_scale()
        _dbs[key] = (db, set())
    return _dbs[key]


def load(code: str, workspace_json: str, bundles_json: str) -> int:
    """Aplica los paquetes nuevos ([[nombre, paquete], …], en orden). Devuelve cuántos."""
    db, seen = _db(code, json.loads(workspace_json))
    n = 0
    for name, bundle in json.loads(bundles_json):
        if name in seen:
            continue
        seen.add(name)
        sync.apply_changes(db, bundle, DATA, week_for_date=db.week_for_date)
        n += 1
    nt, nr = db.trial_size()
    if not nt:   # paquetes de una app sin «trial_*»: el tamaño sale de las parcelas
        row = db.query_one("SELECT COUNT(DISTINCT treatment) AS t, MIN(treatment) AS t0, MAX(rep) AS r "
                           "FROM varieties WHERE treatment >= 0 AND rep >= 1 AND IFNULL(pheno_unit, 0) = 0")
        if row and row["t"]:
            db.set_setting("trial_treatments", int(row["t"]))
            db.set_setting("trial_t0", row["t0"] == 0)
            db.set_setting("trial_reps", int(row["r"] or 1))
    return n


def _week_id(db, start: str) -> int:
    row = db.query_one("SELECT id FROM sampling_weeks WHERE start_date=?", (start,))
    if not row:
        raise ValueError("No hay registros en esa semana.")
    return row["id"]


def _week_number(db, start: str) -> int:
    row = db.query_one("SELECT week_number FROM sampling_weeks WHERE start_date=?", (start,))
    if not row:
        raise ValueError("No hay registros en esa semana.")
    return row["week_number"]


def photos(code: str, kind: str, arg: str, season: int) -> str:
    """Rutas de fotos (relativas a la carpeta de datos) que usa el informe: se bajan antes."""
    db, _ = _dbs[_key(code)]
    q = ("SELECT p.path FROM photos p JOIN observations o ON o.id = p.observation_id "
         "JOIN sampling_weeks w ON w.id = o.week_id WHERE p.is_primary = 1 AND w.season = ?")
    params: list = [season]
    if kind == "weekly":
        q += " AND w.start_date = ?"
        params.append(arg)
    elif kind == "month":
        q += " AND substr(w.start_date, 1, 7) = ?"
        params.append(arg)
    elif kind == "period":
        a, b = sorted(arg.split("|"))
        q += " AND w.start_date BETWEEN ? AND ?"
        params += [a, b]
    elif kind == "variety":
        q += " AND o.variety_id = (SELECT id FROM varieties WHERE uid = ?)"
        params.append(arg)
    if kind == "excel":
        return "[]"
    paths = [r["path"] for r in db.query(q, params)]
    if kind == "weekly":
        wid = _week_id(db, arg)
        paths += [r["path"] for r in db.query(
            "SELECT path FROM measure_entries WHERE week_id=? AND path IS NOT NULL "
            "UNION SELECT path FROM variety_attachments WHERE week_id=? AND path IS NOT NULL", (wid, wid))]
    elif kind == "variety":
        paths += [r["path"] for r in db.query(
            "SELECT path FROM variety_attachments WHERE variety_id=(SELECT id FROM varieties WHERE uid=?) "
            "AND path IS NOT NULL", (arg,))]
    return json.dumps([os.path.relpath(p, DATA) if os.path.isabs(p) else p for p in paths if p])


def report(code: str, kind: str, arg: str, season: int, plain: bool = False) -> str:
    """Genera el PDF y devuelve su ruta. plain: PDF simple (sin logo ni marca)."""
    db, _ = _dbs[_key(code)]
    r = ReportGenerator(db, os.path.join(DATA, "reports"))
    r.plain_pdf = bool(plain)
    if kind == "weekly":
        res = r.weekly(_week_id(db, arg), "pdf")
    elif kind == "month":
        y, m = (int(x) for x in arg.split("-"))
        res = r.monthly(season, y, m, package="pdf")
    elif kind == "variety":
        row = db.query_one("SELECT id FROM varieties WHERE uid=?", (arg,))
        res = r.variety(row["id"], season, "pdf")
    elif kind == "period":
        a, b = sorted(arg.split("|"))
        res = r.period(season, _week_number(db, a), _week_number(db, b), "pdf")
    elif kind == "treatments":
        res = r.treatments(season, "pdf")
    elif kind == "excel":
        from measures_export import export_measures
        ids = [m["id"] for m in db.list_measures()]
        return export_measures(db, ids, season, os.path.join(DATA, "reports"))
    else:
        res = r.matrix(season, package="pdf")
    return res.path
