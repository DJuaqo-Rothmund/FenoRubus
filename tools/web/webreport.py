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


def _db(code: str, workspace: dict) -> tuple[Database, set]:
    if code not in _dbs:
        db = Database(os.path.join(DATA, f"{code}.sqlite3"), seed=False, code=code, workspace=workspace)
        for c, label, desc, kw in ph.BBCH_RUBUS:          # escala BBCH, sin variedades de ejemplo
            db.upsert_bbch(c, label, desc, kw, source="base")
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('seeded', '1')")
        db.refresh_bbch_scale()
        _dbs[code] = (db, set())
    return _dbs[code]


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
        row = db.query_one("SELECT MAX(treatment) AS t, MAX(rep) AS r FROM varieties WHERE treatment IS NOT NULL")
        if row and row["t"]:
            db.set_setting("trial_treatments", int(row["t"]))
            db.set_setting("trial_reps", int(row["r"] or 1))
    return n


def _week_id(db, start: str) -> int:
    row = db.query_one("SELECT id FROM sampling_weeks WHERE start_date=?", (start,))
    if not row:
        raise ValueError("No hay registros en esa semana.")
    return row["id"]


def photos(code: str, kind: str, arg: str, season: int) -> str:
    """Rutas de fotos (relativas a la carpeta de datos) que usa el informe: se bajan antes."""
    db, _ = _dbs[code]
    q = ("SELECT p.path FROM photos p JOIN observations o ON o.id = p.observation_id "
         "JOIN sampling_weeks w ON w.id = o.week_id WHERE p.is_primary = 1 AND w.season = ?")
    params: list = [season]
    if kind == "weekly":
        q += " AND w.start_date = ?"
        params.append(arg)
    elif kind == "month":
        q += " AND substr(w.start_date, 1, 7) = ?"
        params.append(arg)
    elif kind == "variety":
        q += " AND o.variety_id = (SELECT id FROM varieties WHERE uid = ?)"
        params.append(arg)
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


def report(code: str, kind: str, arg: str, season: int) -> str:
    """Genera el PDF y devuelve su ruta."""
    db, _ = _dbs[code]
    r = ReportGenerator(db, os.path.join(DATA, "reports"))
    if kind == "weekly":
        res = r.weekly(_week_id(db, arg), "pdf")
    elif kind == "month":
        y, m = (int(x) for x in arg.split("-"))
        res = r.monthly(season, y, m, package="pdf")
    elif kind == "variety":
        row = db.query_one("SELECT id FROM varieties WHERE uid=?", (arg,))
        res = r.variety(row["id"], season, "pdf")
    elif kind == "treatments":
        res = r.treatments(season, "pdf")
    else:
        res = r.matrix(season, package="pdf")
    return res.path
