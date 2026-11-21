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


_LABELS: dict = {}


def set_labels(labels_json: str) -> int:
    """Marcas de cajas del cultivo (marcas.json de IA+): el Excel de mediciones cuenta las
    estructuras de cada foto. Devuelve cuántas fotos marcadas llegaron."""
    global _LABELS
    try:
        _LABELS = (json.loads(labels_json or "{}") or {}).get("photos") or {}
    except ValueError:
        _LABELS = {}
    return len(_LABELS)


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


def _cfg(db, cfg_json: str = "") -> dict:
    import report_config as rc
    if cfg_json:
        try:
            return rc.normalize(json.loads(cfg_json), rc.default(db))
        except ValueError:
            pass
    return rc.load(db)


def photos(code: str, kind: str, arg: str, season: int, cfg_json: str = "") -> str:
    """Rutas de fotos (relativas a la carpeta de datos) que usa el informe: se bajan antes."""
    db, _ = _dbs[_key(code)]
    cfg = _cfg(db, cfg_json)
    sec = set(cfg["sections"])
    q = ("SELECT p.path FROM photos p JOIN observations o ON o.id = p.observation_id "
         "JOIN sampling_weeks w ON w.id = o.week_id WHERE w.season = ?")
    if not (kind == "weekly" and cfg["all_photos"]):
        q += " AND p.is_primary = 1"
    params: list = [season]
    if kind == "weekly":
        if "gallery" in sec:      # galería paralela: las semanas hasta esta
            q += " AND w.start_date <= ?"
        else:
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
    if kind in ("excel", "degree_days"):
        return "[]"
    if kind == "season_compare":     # fotos de detalle de esta temporada y de las de referencia
        return json.dumps([os.path.relpath(r["path"], DATA) if os.path.isabs(r["path"]) else r["path"] for r in db.query(
            "SELECT p.path FROM photos p JOIN observations o ON o.id = p.observation_id JOIN sampling_weeks w "
            "ON w.id = o.week_id WHERE p.is_primary = 1 AND w.season BETWEEN ? AND ?", (season - 5, season))])
    paths = [r["path"] for r in db.query(q, params)]
    if kind == "weekly":
        wid = _week_id(db, arg)
        paths += [r["path"] for r in db.query(      # primocaña (opcional): su foto en la tarjeta
            "SELECT f.path FROM primo_photos f JOIN primo_obs p ON p.id = f.primo_id "
            "WHERE p.week_id=? AND f.is_primary=1", (wid,))]
        paths += [r["path"] for r in db.query(
            "SELECT path FROM measure_entries WHERE week_id=? AND path IS NOT NULL "
            "UNION SELECT path FROM variety_attachments WHERE week_id=? AND path IS NOT NULL", (wid, wid))]
        if "notebook" in sec:
            import datetime as _dt
            end = (_dt.date.fromisoformat(arg[:10]) + _dt.timedelta(days=6)).isoformat()
            paths += [r["path"] for r in db.query(
                "SELECT p.path FROM notebook_photos p JOIN notebook_entries e ON e.id = p.entry_id "
                "WHERE e.day BETWEEN ? AND ?", (arg[:10], end))]
    elif kind == "variety":
        paths += [r["path"] for r in db.query(
            "SELECT path FROM variety_attachments WHERE variety_id=(SELECT id FROM varieties WHERE uid=?) "
            "AND path IS NOT NULL", (arg,))]
    return json.dumps([os.path.relpath(p, DATA) if os.path.isabs(p) else p for p in paths if p])


# ====================================================================== temperaturas (días grado)
def _get_url(url: str) -> bytes:
    """Pedido HTTP síncrono desde el Web Worker (aquí no hay urllib)."""
    from js import XMLHttpRequest
    x = XMLHttpRequest.new()
    x.open("GET", url, False)
    x.send()
    if x.status != 200:
        raise OSError(f"Open-Meteo respondió {x.status}")
    return str(x.responseText).encode("utf-8")


def _predio(code: str, predio_code: str = "") -> tuple:
    """(base del predio, {code, name}) del ensayo: el predio elegido en el ensayo (ajuste
    «trial_predio»), el mismo si ya es un predio, o el que la página cargó."""
    import degree_days as gd
    db, _ = _dbs[_key(code)]
    ws = getattr(db, "workspace", None) or {}
    if ws.get("profile") == "predio" and not predio_code:
        return db, ws
    pc = predio_code or db.get_setting(gd.SETTING_PREDIO, "") or ""
    if pc and _key(pc) in _dbs:
        pdb = _dbs[_key(pc)][0]
        return pdb, getattr(pdb, "workspace", None) or {"code": pc, "name": pc}
    raise ValueError("El ensayo no tiene predio con temperaturas (elíjalo en la app: «Predio del ensayo…»).")


def _coords(pdb, code: str):
    import degree_days as gd
    plan = None
    try:
        with open(os.path.join(os.path.dirname(__file__), "assets", "maps", f"{pdb.code}.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError, AttributeError):
        pass
    ll = gd.map_center(plan)
    if ll:
        return ll
    for base in (pdb, _dbs[_key(code)][0]):
        row = base.query_one("SELECT AVG(latitude) AS lat, AVG(longitude) AS lon FROM observations "
                             "WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
        if row and row["lat"] is not None:
            return row["lat"], row["lon"]
    return None


def _rows(code: str, seasons: list[int], predio_code: str = "") -> dict:
    """{temporada: días} según la fuente del predio (Open-Meteo, se baja aquí, o datos propios)."""
    import datetime as _dt
    import degree_days as gd
    pdb, p = _predio(code, predio_code)
    if gd.get_mode(pdb) == gd.MODE_OM:
        ll = _coords(pdb, code)
        if not ll:
            raise ValueError(f"No sé dónde está {p.get('name')}: falta su plano o registros con GPS.")
        os.makedirs(os.path.join(DATA, "clima"), exist_ok=True)
        cache = gd.OmCache(os.path.join(DATA, "clima", f"openmeteo_{p.get('code')}.json"))
        first = gd.biofix(min(seasons))
        if cache.stale(ll[0], ll[1], first=first):
            cache.update(ll[0], ll[1], first,
                         fetch=lambda la, lo, a, b: gd.fetch_open_meteo(la, lo, a, b, get=_get_url),
                         today=_dt.date.today())
        get = lambda a, b: cache.rows(a, b)   # noqa: E731
    else:
        get = lambda a, b: gd.own_days(pdb, a, b)   # noqa: E731
    return {s: get(gd.biofix(s), gd.season_end(s)) for s in seasons}


def weather_info(code: str, season: int, predio_code: str = "") -> str:
    """Resumen para la página: predio, fuente, días propios cargados y los últimos."""
    import degree_days as gd
    try:
        pdb, p = _predio(code, predio_code)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    own = gd.own_days(pdb, gd.biofix(season - 1), None)
    return json.dumps({"predio": {"code": p.get("code"), "name": p.get("name")}, "mode": gd.get_mode(pdb),
                       "own": len(own), "first": own[0]["day"] if own else None,
                       "last": own[-1]["day"] if own else None,
                       "recent": [{k: r.get(k) for k in ("day", "tmean", "tmin", "tmax", "rain")} for r in own[-7:]]},
                      ensure_ascii=False)


def parse_weather(path: str, text: str = "") -> str:
    """Archivo (CSV, TXT o Excel) o texto pegado de la estación -> días y avisos."""
    import degree_days as gd
    rows = gd.split_text(text) if text else gd.read_file(path)
    days, warnings = gd.parse_rows(rows)
    return json.dumps({"days": days, "warnings": warnings}, ensure_ascii=False, default=str)


def report(code: str, kind: str, arg: str, season: int, plain: bool = False, cfg_json: str = "") -> str:
    """Genera el PDF y devuelve su ruta. plain: PDF simple (sin logo ni marca); cfg_json: la
    «Configuración de informes» (si no, la del ensayo)."""
    db, _ = _dbs[_key(code)]
    r = ReportGenerator(db, os.path.join(DATA, "reports"))
    cfg = _cfg(db, cfg_json)
    if not cfg_json:
        cfg["plain"] = bool(plain) or cfg["plain"]
    r.set_config(cfg)
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
    elif kind == "degree_days":
        import degree_days as gd
        _pdb, p = _predio(code, arg)
        w = _rows(code, [season, season - 1], arg)
        if not w[season]:
            raise ValueError(f"No hay temperaturas de {p.get('name')} desde el 1 de septiembre.")
        res = r.degree_days(season, w[season], w[season - 1], predio=p.get("name", ""), package="pdf")
    elif kind == "season_compare":
        import season_compare as sc
        pc, mode = (arg.split("|") + ["prev"])[:2]
        avail = sc.available_seasons(db, season)
        refs = avail if mode == "all" else avail[:1]
        if not refs:
            raise ValueError("Para comparar se necesitan estados BBCH de la temporada anterior en este ensayo.")
        _pdb, p = _predio(code, pc)
        w = _rows(code, [season] + refs, pc)
        if not w[season]:
            raise ValueError(f"No hay temperaturas de {p.get('name')} desde el 1 de septiembre.")
        res = r.season_compare(season, w, refs, predio=p.get("name", ""), package="pdf")
    elif kind == "excel":
        import training_labels
        from measures_export import export_measures
        training_labels.set_crop(_crop)
        ids = [m["id"] for m in db.list_measures()]
        return export_measures(db, ids, season, os.path.join(DATA, "reports"), labels=_LABELS)
    else:
        res = r.matrix(season, package="pdf")
    return res.path
