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


def open_weather(on_change=None):
    """Lista de días del predio (los más nuevos arriba): tocar edita; importar o pegar."""
    a = app()
    p = predio_of()
    if p is None:
        a.toast("No hay ningún predio: créelo en el perfil Predio.")
        return
    db = _db_of(p)
    season = a.season
    start, end = gd.biofix(season), gd.season_end(season)
    rows = gd.list_days(db, gd.biofix(season - 1), end)
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

    items = []
    for r in reversed(rows):
        title, sub = _row_text(r, acc)
        items.append((title, sub, lambda r=r: edit_day(db, r, changed), None, lambda r=r: delete(r)))
    prev_n = len(rows) - len(cur)
    info = (f"{p['name']} · desde el 1/9: {len(cur)} días"
            + (f", {gd.fmt(series.total, 0)} °C·día al {gd.short_date(series.last)}" if series.days else "")
            + (f" · temporada anterior: {prev_n} días" if prev_n else ""))
    if series.days and series.last < _dt.date.today() - _dt.timedelta(days=1) and season == ph.season_of(_dt.date.today()):
        info += f"\nFaltan días desde el {gd.short_date(series.last + _dt.timedelta(days=1))}."
    pick_dialog("Temperaturas y lluvia", items, subtitle=info,
                footer=[("file-upload-outline", "Importar archivo (CSV o Excel)", lambda: import_file(db, changed)),
                        ("content-paste", "Pegar datos (de Excel o planilla)", lambda: paste(db, changed)),
                        ("plus", "Agregar o corregir un día", lambda: edit_day(db, None, changed))],
                empty="Aún no hay temperaturas. Importe un archivo de la estación, pegue una tabla "
                      "(fecha y T media; opcional T mín, T máx y lluvia) o agréguelas día a día.")


def edit_day(db, row: dict | None, on_done):
    a = app()
    form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6), padding=(0, dp(8), 0, 0))
    last = gd.list_days(db)[-1:] if row is None else []
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
    have = {r["day"] for r in gd.list_days(db)}
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
    wdb = _db_of(p)
    season = a.season
    weather = gd.list_days(wdb, gd.biofix(season), gd.season_end(season))
    prev = gd.list_days(wdb, gd.biofix(season - 1), gd.season_end(season - 1))
    if not weather:
        confirm("Faltan temperaturas",
                f"No hay temperaturas de {p['name']} desde el 1 de septiembre. Cárguelas primero.",
                [("Cargar temperaturas", lambda: open_weather())])
        return
    r = a.configured_reports()
    if package == "preview":
        def work():
            try:
                res = r.degree_days(season, weather, prev, predio=p["name"], package="preview")
                Clock.schedule_once(lambda *_: on_done(res, None) if on_done else a.media.preview(res.path, res.title))
            except Exception as exc:  # noqa: BLE001
                err = exc
                Clock.schedule_once(lambda *_: on_done(None, err) if on_done else
                                    a.toast(f"No se pudo preparar: {err}"))
        a.workers.submit(work)
        return
    a.run_report(lambda: r.degree_days(season, weather, prev, predio=p["name"], package=package),
                 on_done=on_done)


def summary() -> dict | None:
    """Para la vista previa del teléfono: análisis y textos (None si no hay predio)."""
    a = app()
    p = predio_of()
    if p is None:
        return None
    wdb = _db_of(p)
    season = a.season
    weather = gd.list_days(wdb, gd.biofix(season), gd.season_end(season))
    prev = gd.list_days(wdb, gd.biofix(season - 1), gd.season_end(season - 1))
    res = gd.analyze(a.db, season, weather, prev)
    return {"predio": p, "res": res, "d": gd.display(res)}
