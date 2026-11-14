"""
ui/degree_days_ui.py
====================
Fenología y días grado: predio de cada ensayo, temperaturas (y lluvia) del predio e informe.

Las temperaturas viven en la base del PREDIO (se sincronizan con él); un ensayo de I+D usa
las de su predio (ajuste «trial_predio»; si no se eligió, el primer predio).
"""
from __future__ import annotations

import datetime as _dt
import os

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel

import degree_days as gd
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import app, confirm, form_dialog, pick_dialog

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


# ====================================================================== predio del ensayo
def _db_of(ws: dict):
    a = app()
    return a.db if ws.get("id") == (a.workspace or {}).get("id") else a.open_db(ws)


def predio_of(ws: dict | None = None) -> dict | None:
    """Predio cuyas temperaturas usa el ensayo (el mismo, si ya es un predio)."""
    a = app()
    ws = ws or a.workspace or {}
    if ws.get("profile") == "predio":
        return ws
    predios = [p for p in a.workspaces.list("predio")]
    try:
        code = _db_of(ws).get_setting(gd.SETTING_PREDIO, "") if ws else ""
    except Exception:  # noqa: BLE001
        code = ""
    chosen = next((p for p in predios if p["code"] == code), None)
    return chosen or (predios[0] if predios else None)


def predio_name(ws: dict | None = None) -> str:
    p = predio_of(ws)
    return p["name"] if p else ""


def weather_db(ws: dict | None = None):
    p = predio_of(ws)
    return _db_of(p) if p else None


def pick_predio(ws: dict, on_done=None):
    """Elegir el predio de un ensayo de I+D (queda en el ensayo y viaja con la sync)."""
    a = app()
    predios = a.workspaces.list("predio")
    if not predios:
        a.toast("Primero cree el predio en el perfil Predio.")
        return
    cur = predio_of(ws) or {}

    def choose(p):
        _db_of(ws).set_setting(gd.SETTING_PREDIO, p["code"])
        a.toast(f"«{ws['name']}» queda en el predio {p['name']}")
        if on_done:
            on_done()
    pick_dialog(f"Predio de «{ws['name']}»",
                [(("En uso · " if p["code"] == cur.get("code") else "") + p["name"], f"Código {p['code']}",
                  lambda p=p: choose(p), c(theme.BERRY) if p["code"] == cur.get("code") else None)
                 for p in predios],
                subtitle="Sus temperaturas se usan en el informe «Fenología y días grado».")


# ====================================================================== temperaturas
def _row_text(r: dict, acc: dict) -> tuple[str, str]:
    d = _dt.date.fromisoformat(r["day"])
    t = gd.tmean_of(r)
    title = f"{DIAS[d.weekday()].capitalize()} {d.day}/{d.month}/{d.year % 100:02d} · " + (
        f"{gd.fmt(t)} °C" if t is not None else "sin T media")
    sub = []
    if r.get("tmin") is not None or r.get("tmax") is not None:
        sub.append(f"mín {gd.fmt(r.get('tmin'))} · máx {gd.fmt(r.get('tmax'))}")
    if r.get("rain") is not None:
        sub.append(f"lluvia {gd.fmt(r['rain'])} mm")
    if d in acc:
        sub.append(f"{gd.fmt(acc[d], 0)} °C·día acum.")
    return title, " · ".join(sub)


# ------------------------------------------------------------- fuente: Open-Meteo o propios
_om_busy: set = set()
_om_tried: dict = {}          # código -> hora del último intento fallido (no reintentar en bucle)


def mode_of(p: dict) -> str:
    return gd.get_mode(_db_of(p))


def _cache(p: dict) -> gd.OmCache:
    from platform_utils import data_subdir
    return gd.OmCache(os.path.join(data_subdir("clima"), f"openmeteo_{p['code']}.json"))


def rows_for(p: dict, start: _dt.date | None, end: _dt.date | None) -> list[dict]:
    """Temperaturas del predio según su fuente elegida."""
    if mode_of(p) == gd.MODE_OM:
        return _cache(p).rows(start, end)
    return gd.own_days(_db_of(p), start, end)


def season_rows(p: dict, season: int) -> tuple[list[dict], list[dict]]:
    """(esta temporada, la anterior) desde el 1 de septiembre."""
    return (rows_for(p, gd.biofix(season), gd.season_end(season)),
            rows_for(p, gd.biofix(season - 1), gd.season_end(season - 1)))


_om_back = {"n": 1}            # temporadas hacia atrás que necesita Open-Meteo (comparación)


def _om_first() -> _dt.date:
    """Desde dónde bajar Open-Meteo: la temporada anterior (o más, si la comparación usa
    varias temporadas de referencia)."""
    return gd.biofix(app().season - max(1, _om_back["n"]))


def om_update_sync(p: dict, force: bool = False) -> int:
    """Actualiza la caché de Open-Meteo (en un hilo de trabajo). Lanza si no hay internet."""
    ll = predio_coords(p, _db_of(p))
    if ll is None:
        raise ValueError("el predio no tiene plano ni registros con GPS: no se sabe dónde está")
    cache = _cache(p)
    if not force and not cache.stale(*ll, first=_om_first()):
        return 0
    return cache.update(ll[0], ll[1], _om_first())


def om_refresh(p: dict, on_done=None, force: bool = False, quiet: bool = True):
    """Actualiza Open-Meteo en segundo plano; on_done(n_días) en el hilo de Kivy."""
    import time
    a = app()
    code = p["code"]
    if code in _om_busy or (not force and time.time() - _om_tried.get(code, 0) < 600):
        return
    try:
        ll = predio_coords(p, _db_of(p))
        if ll is None:
            if not quiet:
                a.toast("El predio no tiene plano ni registros con GPS: no sé dónde está.")
            return
        if not force and not _cache(p).stale(*ll, first=_om_first()):
            return
    except Exception:  # noqa: BLE001
        return
    _om_busy.add(code)
    if not quiet:
        a.toast("Actualizando Open-Meteo…")

    def work():
        n, err = 0, None
        try:
            n = om_update_sync(p, force=True)
            _om_tried.pop(code, None)
        except Exception as exc:  # noqa: BLE001
            err = exc
            _om_tried[code] = time.time()
        finally:
            _om_busy.discard(code)

        def done(*_):
            if err is not None:
                if not quiet:
                    a.toast(f"No se pudo actualizar Open-Meteo (¿sin internet?): {err}")
                return
            if not quiet:
                a.toast(f"Open-Meteo al día ({n} día{'s' if n != 1 else ''} nuevo{'s' if n != 1 else ''})")
            if on_done:
                on_done(n)
        Clock.schedule_once(done, 0)
    a.workers.submit(work)


def pick_mode(p: dict, on_done=None):
    """Elegir la fuente de las temperaturas del predio."""
    a = app()
    cur = mode_of(p)
    db = _db_of(p)
    own = gd.own_days(db)

    def choose(m):
        gd.set_mode(db, m)
        a.toast(f"{p['name']}: temperaturas de {gd.MODES[m][0]}")
        if m == gd.MODE_OM:
            om_refresh(p, on_done=lambda _n: on_done and on_done(), force=False, quiet=False)
        if on_done:
            on_done()
    items = []
    for m, (name, desc) in gd.MODES.items():
        extra = f" · {len(own)} días cargados" if m == gd.MODE_OWN and own else ""
        items.append((("En uso · " if m == cur else "") + name, desc + extra, lambda m=m: choose(m),
                      c(theme.BERRY) if m == cur else None))
    pick_dialog(f"Fuente de temperaturas · {p['name']}", items,
                subtitle="Se guardan por separado: puede cambiar cuando quiera sin perder nada.")


def open_weather(on_change=None):
    """Temperaturas del predio según su fuente: Open-Meteo (solo lectura, se actualiza sola)
    o datos propios (tocar edita; importar, pegar o agregar)."""
    a = app()
    p = predio_of()
    if p is None:
        a.toast("No hay ningún predio: créelo en el perfil Predio.")
        return
    db = _db_of(p)
    season = a.season
    mode = mode_of(p)
    start, end = gd.biofix(season), gd.season_end(season)
    rows = rows_for(p, gd.biofix(season - 1), end)
    cur = [r for r in rows if r["day"] >= start.isoformat()]
    series = gd.Series(cur, season)
    acc = {r["day"]: r["acc"] for r in series.days}

    def changed():
        if on_change:
            on_change()
        Clock.schedule_once(lambda *_: open_weather(on_change), .2)

    def delete(r):
        confirm("Borrar día", f"¿Borrar las temperaturas del {r['day']}?",
                [("Eliminar", lambda: (gd.delete_day(db, r["day"]), changed()))])

    def om_info(_r):
        a.toast("Estimación de Open-Meteo: para corregir días, cambie a «Datos propios».")

    items = []
    for r in reversed(rows):
        title, sub = _row_text(r, acc)
        if mode == gd.MODE_OM:
            items.append((title, sub + (" · pronóstico" if r.get("fc") else ""), lambda r=r: om_info(r)))
        else:
            items.append((title, sub, lambda r=r: edit_day(db, r, changed), None, lambda r=r: delete(r)))
    prev_n = len(rows) - len(cur)
    name = gd.MODES[mode][0]
    info = (f"Fuente: {name} · {p['name']}\nDesde el 1/9: {len(cur)} días"
            + (f", {gd.fmt(series.total, 0)} °C·día al {gd.short_date(series.last)}" if series.days else "")
            + (f" · temporada anterior: {prev_n} días" if prev_n else ""))
    if mode == gd.MODE_OM:
        ll = predio_coords(p, db)
        info += (f"\nEstimación de la zona ({ll[0]:.3f}, {ll[1]:.3f}); se actualiza sola." if ll else
                 "\nEl predio no tiene plano ni GPS: no se puede descargar.")
    elif series.days and series.last < _dt.date.today() - _dt.timedelta(days=1) and season == ph.season_of(_dt.date.today()):
        info += f"\nFaltan días desde el {gd.short_date(series.last + _dt.timedelta(days=1))}."
    switch = ("swap-horizontal", f"Cambiar fuente (ahora: {name})", lambda: pick_mode(p, on_done=changed))
    if mode == gd.MODE_OM:
        footer = [("refresh", "Actualizar ahora", lambda: om_refresh(p, on_done=lambda _n: changed(),
                                                                    force=True, quiet=False)), switch]
        empty = ("Aún no se han descargado. Toque «Actualizar ahora» (necesita internet).")
        om_refresh(p, on_done=lambda n: n and changed())        # si está desactualizada
    else:
        footer = [("file-upload-outline", "Importar archivo (CSV o Excel)", lambda: import_file(db, changed)),
                  ("content-paste", "Pegar datos (de Excel o planilla)", lambda: paste(db, changed)),
                  ("plus", "Agregar o corregir un día", lambda: edit_day(db, None, changed)), switch]
        empty = ("Aún no hay datos propios. Importe un archivo de la estación, pegue una tabla "
                 "(fecha y T media; opcional T mín, T máx y lluvia) o agréguelos día a día.")
    pick_dialog("Temperaturas y lluvia", items, subtitle=info, footer=footer, empty=empty)


def edit_day(db, row: dict | None, on_done):
    a = app()
    form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6), padding=(0, dp(8), 0, 0))
    last = gd.own_days(db)[-1:] if row is None else []
    if row:
        d = _dt.date.fromisoformat(row["day"])
    elif last:
        d = _dt.date.fromisoformat(last[0]["day"]) + _dt.timedelta(days=1)
    else:
        d = _dt.date.today() - _dt.timedelta(days=1)
    fields = {}
    for key, hint, val in (("day", "Fecha (dd-mm-aaaa)", f"{d.day:02d}-{d.month:02d}-{d.year}"),
                           ("tmean", "T media (°C)", row and row.get("tmean")),
                           ("tmin", "T mínima (°C, opcional)", row and row.get("tmin")),
                           ("tmax", "T máxima (°C, opcional)", row and row.get("tmax")),
                           ("rain", "Lluvia (mm, opcional)", row and row.get("rain"))):
        f = Factory.Field(hint_text=hint, text="" if val in (None, "") else
                          (val if isinstance(val, str) else gd.fmt(float(val), 2).rstrip("0").rstrip(",")))
        if key != "day":
            f.input_filter = lambda s, undo: "".join(ch for ch in s if ch in "0123456789,.-")
        form.add_widget(f)
        fields[key] = f

    def ok(_f):
        day = gd.parse_date(fields["day"].text)
        if day is None:
            a.toast("Fecha no válida (use dd-mm-aaaa)")
            return False
        vals = {k: gd.parse_num(fields[k].text) for k in ("tmean", "tmin", "tmax", "rain")}
        if vals["tmean"] is None and (vals["tmin"] is None or vals["tmax"] is None):
            a.toast("Falta la T media (o la mínima y la máxima)")
            return False
        if row and row["day"] != day.isoformat():
            gd.delete_day(db, row["day"])
        gd.set_day(db, day.isoformat(), **vals)
        Clock.schedule_once(lambda *_: on_done(), .1)
    form_dialog("Temperatura del día" if row is None else f"Día {gd.short_date(d)}", form, ok)


def _review(db, days, warnings, source, on_done):
    a = app()
    if not days:
        a.toast("No se reconocieron días: " + (warnings[0] if warnings else "revise el formato"))
        return
    have = {r["day"] for r in gd.own_days(db)}
    new = sum(1 for d in days if d["day"] not in have)
    cols = [n for k, n in (("tmean", "T media"), ("tmin", "T mín"), ("tmax", "T máx"), ("rain", "lluvia"))
            if any(d.get(k) is not None for d in days)]
    text = (f"Se leyeron {len(days)} días, del {days[0]['day']} al {days[-1]['day']} "
            f"({', '.join(cols)}).\n{new} son nuevos y {len(days) - new} ya estaban.")
    if warnings:
        text += "\n\n" + "\n".join("• " + w for w in warnings[:5])

    def save(overwrite):
        n = gd.save_days(db, days, source, overwrite=overwrite)
        a.toast(f"Guardados {n} días")
        Clock.schedule_once(lambda *_: on_done(), .1)
    actions = [("Guardar todo", lambda: save(True))]
    if len(days) - new:
        actions.insert(0, ("Solo nuevos", lambda: save(False)))
    confirm("Importar temperaturas", text, actions)


def import_file(db, on_done):
    a = app()

    def picked(path, name):
        if not path:
            return
        try:
            days, warnings = gd.parse_rows(gd.read_file(path))
        except Exception as exc:  # noqa: BLE001
            a.toast(f"No se pudo leer el archivo: {exc}")
            return
        _review(db, days, warnings, f"archivo {name or os.path.basename(path)}"[:60], on_done)
    a.media.pick_document(picked, exts=(".csv", ".txt", ".tsv", ".xlsx"))


def predio_coords(p: dict, db) -> tuple[float, float] | None:
    """Centro del plano del predio; si no tiene plano, el promedio de las ubicaciones GPS de
    sus registros (o los del ensayo actual)."""
    from ui.sector_map import load_map
    ll = gd.map_center(load_map(p.get("code")))
    if ll:
        return ll
    for base in (db, app().db):
        row = base.query_one("SELECT AVG(latitude) AS lat, AVG(longitude) AS lon FROM observations "
                             "WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
        if row and row["lat"] is not None:
            return row["lat"], row["lon"]
    return None


def paste(db, on_done):
    form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6), padding=(0, dp(8), 0, 0))
    form.add_widget(MDLabel(text="Copie las columnas desde Excel o la planilla de la estación y péguelas aquí. "
                                 "Columnas: fecha y T media (opcional T mín, T máx y lluvia), con o sin encabezado.",
                            font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                            text_color=c(theme.MUTED)))
    field = Factory.Field(hint_text="Fecha    T media    Lluvia", multiline=True, max_height=dp(220))
    form.add_widget(field)

    def ok(_f):
        days, warnings = gd.parse_rows(gd.split_text(field.text))
        Clock.schedule_once(lambda *_: _review(db, days, warnings, "pegado", on_done), .2)
    form_dialog("Pegar temperaturas", form, ok, ok_text="LEER")


# ====================================================================== informe
def generate(package: str = "pdf", on_done=None):
    a = app()
    p = predio_of()
    if p is None:
        a.toast("No hay predio con temperaturas: créelo en el perfil Predio.")
        return
    season = a.season
    om = mode_of(p) == gd.MODE_OM
    if not om and not season_rows(p, season)[0]:
        confirm("Faltan temperaturas",
                f"No hay datos propios de {p['name']} desde el 1 de septiembre. Cárguelos o use Open-Meteo.",
                [("Temperaturas", lambda: open_weather())])
        return
    r = a.configured_reports()

    def job():
        if om:
            try:
                om_update_sync(p)            # al día antes del informe (si hay internet)
            except Exception as exc:  # noqa: BLE001
                print("open-meteo:", exc)
        weather, prev = season_rows(p, season)
        if not weather:
            raise ValueError("Sin temperaturas desde el 1 de septiembre (Open-Meteo necesita internet "
                             "la primera vez).")
        return r.degree_days(season, weather, prev, predio=p["name"], package=package)
    if package == "preview":
        def work():
            try:
                res = job()
                Clock.schedule_once(lambda *_: on_done(res, None) if on_done else a.media.preview(res.path, res.title))
            except Exception as exc:  # noqa: BLE001
                err = exc
                Clock.schedule_once(lambda *_: on_done(None, err) if on_done else
                                    a.toast(f"No se pudo preparar: {err}"))
        a.workers.submit(work)
        return
    a.run_report(job, on_done=on_done)


def summary(on_update=None) -> dict | None:
    """Para la vista previa del teléfono: análisis y textos (None si no hay predio). Con
    Open-Meteo desactualizado, lo pone al día en segundo plano y llama on_update()."""
    a = app()
    p = predio_of()
    if p is None:
        return None
    mode = mode_of(p)
    if mode == gd.MODE_OM:
        om_refresh(p, on_done=lambda n: n and on_update and on_update())
    weather, prev = season_rows(p, a.season)
    res = gd.analyze(a.db, a.season, weather, prev)
    return {"predio": p, "res": res, "d": gd.display(res), "mode": mode}


# ====================================================================== comparación entre temporadas
CMP_KEY = "reportcfg_cmp_refs"          # «prev» (la anterior) o «all» (todas las disponibles)


def cmp_refs() -> tuple[str, list[int], list[int]]:
    """(modo, temporadas de referencia elegidas, todas las disponibles)."""
    import season_compare as sc
    a = app()
    avail = sc.available_seasons(a.db, a.season)
    mode = a.db.get_setting(CMP_KEY, "prev") or "prev"
    refs = avail if mode == "all" else avail[:1]
    return mode, refs, avail


def pick_cmp_refs(on_done=None):
    import season_compare as sc
    a = app()
    mode, _refs, avail = cmp_refs()
    if not avail:
        a.toast("Aún no hay estados BBCH de temporadas anteriores en este ensayo.")
        return

    def choose(m):
        a.db.set_setting(CMP_KEY, m)
        if on_done:
            on_done()
    opts = [("prev", f"Solo la anterior ({sc.season_label(avail[0])})", "Compara contra un año")]
    if len(avail) > 1:
        opts.append(("all", f"Promedio de {len(avail)} temporadas",
                     ", ".join(sc.season_label(x) for x in avail) + " · un «año normal»"))
    else:
        opts.append(("all", "Promedio de varias temporadas", "Cuando haya más de una cargada (hoy: 1)"))
    pick_dialog("Comparar contra", [(("En uso · " if m == mode else "") + t, sub, lambda m=m: choose(m),
                                      c(theme.BERRY) if m == mode else None) for m, t, sub in opts])


def generate_compare(package: str = "pdf", on_done=None):
    a = app()
    p = predio_of()
    if p is None:
        a.toast("No hay predio con temperaturas: créelo en el perfil Predio.")
        return
    _mode, refs, _avail = cmp_refs()
    if not refs:
        confirm("Sin temporada anterior",
                "Para comparar se necesitan los estados BBCH de la temporada anterior en este ensayo "
                "(regístrelos o impórtelos en IA › «Base de datos de temporadas anteriores»). Las temperaturas de esa "
                "temporada las pone Open-Meteo o sus datos propios.", [])
        return
    season = a.season
    _om_back["n"] = season - min(refs)
    om = mode_of(p) == gd.MODE_OM
    r = a.configured_reports()

    def job():
        if om:
            try:
                om_update_sync(p)
            except Exception as exc:  # noqa: BLE001
                print("open-meteo:", exc)
        weather = {s: rows_for(p, gd.biofix(s), gd.season_end(s)) for s in [season] + refs}
        if not weather[season]:
            raise ValueError("Sin temperaturas desde el 1 de septiembre (Open-Meteo necesita internet "
                             "la primera vez).")
        return r.season_compare(season, weather, refs, predio=p["name"], package=package)
    if package == "preview":
        def work():
            try:
                res = job()
                Clock.schedule_once(lambda *_: on_done(res, None) if on_done else a.media.preview(res.path, res.title))
            except Exception as exc:  # noqa: BLE001
                err = exc
                Clock.schedule_once(lambda *_: on_done(None, err) if on_done else
                                    a.toast(f"No se pudo preparar: {err}"))
        a.workers.submit(work)
        return
    a.run_report(job, on_done=on_done)
