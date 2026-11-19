"""
ui/measures_ui.py
=================
Mediciones: planillas de datos y registros de imágenes.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
import os
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.metrics import sp as sp_
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRectangleFlatButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import phenology as ph
from android_bridge import store_photo
from platform_utils import data_subdir
from ui import theme
from ui.theme import c
from ui.common import app, confirm, fast_clear, form_dialog, pick_dialog, thumb_widget


# ===========================================================================
# Mediciones personalizadas (registro de imágenes o planilla de datos)
# ===========================================================================
class EntryRow(MDBoxLayout):
    title = StringProperty()
    subtitle = StringProperty()
    counts = StringProperty()               # conteo con cajas (fotos de mediciones)
    can_count = BooleanProperty(False)      # botón «Contar estructuras»
    has_thumb = BooleanProperty(False)
    item = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


def _variety_label(variety_id, varieties, two_lines: bool = False) -> str:
    """Nombre de la variedad de un registro. Predio: «Meeker 2019 · E1-S1» (o en dos
    líneas para la celda angosta de la planilla)."""
    v = next((v for v in varieties if v["id"] == variety_id), None)
    if not v:
        return "General"
    if two_lines and ph.is_unit(v):
        main, _sep, where = ph.unit_compact(v).rpartition(" · ")
        return f"{main}\n{where}"
    return ph.unit_compact(v)


def _variety_choices(varieties, choose):
    """Filas de un selector de variedad: predio = variedad y año, con equipo y sector abajo."""
    return [(ph.unit_main(v), " · ".join(x for x in (ph.unit_place(v), v["code"] or "") if x),
             lambda v=v: choose(v["id"])) for v in varieties]


def open_measures_menu():
    """Lista de mediciones de la semana actual; abajo, aparte, «Nueva» y «Exportar a Excel»."""
    a = app()
    week = a.week
    items = []
    measures = a.db.list_measures(week["id"])
    due = [m for m in measures if a.db.measure_due(m, week)]
    rest = [m for m in measures if m not in due]

    def row(m, note=""):
        unit = ("foto(s)" if m["kind"] == "images" else "fila(s)")
        kind = "Imágenes" if m["kind"] == "images" else "Planilla"
        sched = a.db.schedule_text(m)
        sub = f"{kind} · {m['n']} {unit} esta semana" + ("" if sched == "Todas las semanas" else f" · {sched}")
        return (m["name"], note + sub, lambda m=m: a.open_measure(m["id"], week["id"]), None,
                lambda m=m: delete_measure_dialog(m, week))

    items = [row(m) for m in due]
    footer = [("plus", "Nueva medición", new_measure_dialog)]
    if rest:       # una sola vez o semanas elegidas: no tocan esta semana, pero se pueden abrir
        footer.insert(0, ("calendar-blank-outline", f"Otras mediciones ({len(rest)}) · no tocan esta semana",
                          lambda: pick_dialog("Otras mediciones", [row(m) for m in rest],
                                              subtitle="Se toman una sola vez o en otras semanas")))
    if measures:
        footer.append(("microsoft-excel", "Exportar todas a Excel",
                       lambda: export_measures_xlsx([m["id"] for m in measures])))
    start = _dt.date.fromisoformat(week["start_date"][:10])
    end = a.db.week_end(week)
    span = (f"{start.day} {ph.MESES[start.month - 1][:3]} – "
            f"{end.day} {ph.MESES[end.month - 1][:3]} {end.year}")
    pick_dialog("Mediciones", items, subtitle=f"{ph.week_title(week)} · {span}", footer=footer,
                empty="Aún no hay mediciones en este ensayo." if not rest else "Ninguna medición toca esta semana.",
                image=theme.MEASURES_ICON)


def delete_measure_dialog(m: dict, week: dict):
    """Basurero de la lista: borrar lo registrado ESTA semana o la medición completa."""
    a = app()
    total = len(a.db.list_entries(m["id"]))

    def done(msg):
        a.toast(msg)
        a.refresh_home()
        Clock.schedule_once(lambda *_: open_measures_menu(), .3)

    def this_week():
        n = a.db.delete_week_entries(m["id"], week["id"])
        done(f"«{m['name']}»: {n} registro(s) de esta semana eliminados")

    def everything():
        a.db.delete_measure(m["id"])
        done(f"Medición «{m['name']}» eliminada")

    actions = []
    if m["n"]:
        actions.append(("Esta semana", this_week))
    actions.append(("Eliminar todo", everything))
    text = (f"«{m['name']}» tiene {m['n']} registro(s) en {ph.week_title(week)} y {total} en "
            f"total.\n\n• Esta semana: borra solo lo de esta semana (la medición sigue "
            f"para las demás).\n• Eliminar todo: quita la medición de todas las semanas.\n\n"
            f"Las fotos quedan en el teléfono.")
    Clock.schedule_once(lambda *_: confirm(f"Eliminar «{m['name']}»", text, actions), .3)


def export_measures_xlsx(measure_ids: list[int], week: dict | None = None):
    """Excel de toda la temporada o, con `week`, solo de esa semana."""
    a = app()
    a.toast("Generando planilla Excel…")
    what = f"Mediciones · {ph.week_title(week)}" if week else "Mediciones de toda la temporada"

    def work():
        try:
            from measures_export import export_measures
            path = export_measures(a.db, measure_ids, a.season, week=week)
            Clock.schedule_once(lambda *_: a.report_actions(
                path, "Planilla Excel (.xlsx)", what, viewable=False))
        except Exception as exc:  # noqa: BLE001
            error = exc
            Clock.schedule_once(lambda *_: a.toast(f"No se pudo exportar: {error}"))

    a.workers.submit(work)


def _freq_row(box, measure: dict | None = None):
    """Frecuencia: todas las semanas, una sola vez (esta semana) o semanas elegidas."""
    a = app()
    week = a.week
    box.freq = a.db.measure_schedule(measure) if measure else {"mode": "weekly", "weeks": []}
    box.add_widget(MDLabel(text="[b]¿Cuándo se toma?[/b]", markup=True, adaptive_height=True))
    row = MDBoxLayout(adaptive_height=True, spacing=dp(6))
    note = MDLabel(font_style="Caption", adaptive_height=True, theme_text_color="Custom", text_color=c(theme.MUTED))
    buttons = {}

    def show():
        for k, b in buttons.items():
            on = k == box.freq["mode"]
            b.md_bg_color = c(theme.LEAF_DARK) if on else c("#FFFFFF", 0)
            b.text_color = c("#FFFFFF") if on else c(theme.LEAF_DARK)
        if box.freq["mode"] == "weekly":
            note.text = "Aparece todas las semanas."
        else:
            nums = [str(ph.iso_week(w)[0]) for w in box.freq["weeks"]]
            note.text = ("Solo en la semana " if box.freq["mode"] == "once" else "Solo en las semanas ") + \
                ", ".join(nums) + ". En las demás queda en «Otras mediciones»."

    def choose(mode):
        if mode == "weekly":
            box.freq = {"mode": "weekly", "weeks": []}
        elif mode == "once":
            keep = box.freq["weeks"][:1] if box.freq["mode"] == "once" else []
            box.freq = {"mode": "once", "weeks": keep or [week["start_date"][:10]]}
        else:
            pick_weeks(box.freq["weeks"] or [week["start_date"][:10]],
                       lambda got: (box.freq.update(mode="weeks", weeks=got), show()))
            return
        show()

    for mode, label in (("weekly", "Semanal"), ("once", "Una vez"), ("weeks", "Semanas…")):
        b = MDRectangleFlatButton(text=label, theme_text_color="Custom", line_color=c(theme.LEAF_DARK),
                                  on_release=lambda *_, k=mode: choose(k))
        buttons[mode] = b
        row.add_widget(b)
    box.add_widget(row)
    box.add_widget(note)
    Clock.schedule_once(lambda *_: show())


def pick_weeks(selected: list[str], on_done):
    """Elegir semanas (casillas): de 12 semanas atrás a 30 adelante de la semana abierta."""
    from kivy.uix.scrollview import ScrollView
    from kivymd.uix.selectioncontrol import MDCheckbox
    a = app()
    start = _dt.date.fromisoformat(a.week["start_date"][:10])
    chosen = set(selected)
    box = MDBoxLayout(orientation="vertical", adaptive_height=True)
    for k in range(-12, 31):
        d = start + _dt.timedelta(weeks=k)
        key = d.isoformat()
        r = MDBoxLayout(adaptive_height=True, spacing=dp(6))
        cb = MDCheckbox(size_hint=(None, None), size=(dp(40), dp(40)), active=key in chosen)
        cb.bind(active=lambda w, v, key=key: chosen.add(key) if v else chosen.discard(key))
        r.add_widget(cb)
        r.add_widget(MDLabel(text=f"Semana {ph.iso_week(d)[0]} · {d.day} {ph.MESES[d.month - 1][:3]} {d.year}"
                                  + ("  (esta)" if k == 0 else ""), adaptive_height=True, pos_hint={"center_y": .5}))
        box.add_widget(r)
    sv = ScrollView(size_hint_y=None, height=dp(340))
    sv.add_widget(box)
    form = MDBoxLayout(orientation="vertical", adaptive_height=True)
    form.add_widget(sv)
    Clock.schedule_once(lambda *_: sv.scroll_to(box.children[-13], animate=False), .1)

    def ok(_f):
        if not chosen:
            a.toast("Elija al menos una semana")
            return False
        on_done(sorted(chosen))

    form_dialog("Semanas en que se toma", form, ok, "LISTO")


def _measure_form(measure: dict | None = None):
    """Formulario: nombre, tipo (planilla / imágenes) y cuándo se toma. Las columnas se crean
    en la grilla."""
    from kivy.factory import Factory
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                      padding=(0, dp(8), 0, 0))
    box.name = Factory.Field(hint_text="Nombre de la medición")
    box.add_widget(box.name)
    box.kind = measure["kind"] if measure else "table"
    if measure:
        box.name.text = measure["name"]
        _freq_row(box, measure)
        return box
    _freq_row(box)
    row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
    hint = MDLabel(font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                   text_color=c(theme.MUTED))
    buttons = {}
    box.struct = _structure_box(app().db)

    def choose(kind):
        box.kind = kind
        for k, b in buttons.items():
            on = k == kind
            b.md_bg_color = c(theme.LEAF_DARK) if on else c("#FFFFFF", 0)
            b.text_color = c("#FFFFFF") if on else c(theme.LEAF_DARK)
        hint.text = ("Una planilla como Excel. Diga cómo tomará los datos y queda ordenada y lista "
                     "para llenar (si deja las evaluaciones vacías, se crea con 3 columnas para nombrar)."
                     if kind == "table" else "Fotos con descripción y, si quiere, la variedad.")
        if kind == "table" and box.struct.parent is None:
            box.add_widget(box.struct)
        elif kind != "table" and box.struct.parent is not None:
            box.remove_widget(box.struct)

    for kind, label in (("table", "Planilla de datos"), ("images", "Imágenes")):
        b = MDRectangleFlatButton(text=label, theme_text_color="Custom", line_color=c(theme.LEAF_DARK),
                                  on_release=lambda *_, k=kind: choose(k))
        buttons[kind] = b
        row.add_widget(b)
    box.add_widget(row)
    box.add_widget(hint)
    Clock.schedule_once(lambda *_: choose("table"))
    return box


def new_measure_dialog():
    a = app()

    def ok(form):
        try:
            if form.kind == "table" and form.struct.has_vars():
                cols, reps = form.struct.result()
                mid = a.db.add_measure(form.name.text, "table", cols)
                a.db.fill_sheet_rows(mid, a.week["id"], reps)
            else:
                mid = a.db.add_measure(form.name.text, form.kind)
            if form.freq["mode"] != "weekly":
                a.db.set_measure_schedule(a.db.get_measure(mid), form.freq["mode"], form.freq["weeks"])
        except ValueError as exc:
            a.toast(str(exc))
            return False
        a.open_measure(mid, a.week["id"])

    form_dialog("Nueva medición", _measure_form(), ok, "CREAR")


def _structure_box(db, cols: list[str] | None = None):
    """Cómo se tomarán los datos: filas (tratamientos × repeticiones o variedades), muestras
    por parcela (plantas, cañas…) y evaluaciones de cada muestra (subcolumnas)."""
    import sheet_layout as SL
    from kivy.factory import Factory
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(4))
    muted = lambda t: MDLabel(text=t, font_style="Caption", adaptive_height=True,  # noqa: E731
                              theme_text_color="Custom", text_color=c(theme.MUTED))
    box.add_widget(MDLabel(text="[b]Cómo tomará los datos[/b]", markup=True, adaptive_height=True))
    reps = None
    if db.is_trial:
        nt, nr = db.trial_size()
        box.add_widget(muted(f"Filas: {nt} tratamiento(s) × {nr} repetición(es) = {nt * nr} parcelas "
                             "(las del ensayo; se cambian en los ajustes del ensayo)."))
    else:
        nv = len(db.sheet_units())
        box.add_widget(muted(f"Filas: una por variedad ({nv})."))
        reps = Factory.Field(hint_text="Repeticiones por variedad", text="1", input_filter="int")
        if cols is not None and SL.REP_COL not in cols:
            reps.text = "1"
        box.add_widget(reps)
    row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
    samples = Factory.Field(hint_text="Muestras por parcela", text="1", input_filter="int")
    sname = Factory.Field(hint_text="Cada muestra es una…", text="Planta")
    row.add_widget(samples)
    row.add_widget(sname)
    box.add_widget(row)
    evals = Factory.Field(hint_text="Evaluaciones (una por línea)", multiline=True)
    box.add_widget(evals)
    preview = muted("Ej.: N.º laterales · Largo laterales (cm) · Largo entrenudos (cm)")
    box.add_widget(preview)
    if cols:                                    # planilla ya hecha: se parte de lo que tiene
        gs = [(g, cs) for g, cs in SL.groups([x for x in cols if x != SL.REP_COL]) if g]
        if gs:
            samples.text = str(len(gs))
            head = gs[0][0].rpartition(" ")
            sname.text = head[0] if head[2].isdigit() else gs[0][0]
            evals.text = "\n".join(SL.split(x)[1] for x in gs[0][1])
        else:
            evals.text = "\n".join(x for x in cols if x != SL.REP_COL and not x.startswith("Columna "))

    def _int(f, default=1):
        try:
            return max(1, int(f.text or default))
        except ValueError:
            return default

    def result():
        r = _int(reps) if reps is not None else None
        out = SL.build(SL.parse_vars(evals.text), _int(samples), sname.text, reps_col=bool(r and r > 1))
        return out, r

    def show(*_):
        try:
            out, r = result()
            rows = (f"{len(db.sheet_units())} × {r} filas · " if r and r > 1 else "")
            preview.text = rows + SL.describe([x for x in out if x != SL.REP_COL])
        except ValueError:
            preview.text = "Ej.: N.º laterales · Largo laterales (cm) · Largo entrenudos (cm)"

    for f in (samples, sname, evals) + ((reps,) if reps is not None else ()):
        f.bind(text=show)
    Clock.schedule_once(show, 0)
    box.result = result
    box.has_vars = lambda: bool(SL.parse_vars(evals.text))
    return box


# Planilla con colores propios (como una hoja de cálculo), iguales en todos los estilos: con los
# del estilo, en los oscuros quedaba texto claro sobre celdas blancas (no se leía).
SHEET_HEAD, SHEET_HEAD_FG = "#1E5A45", "#FFFFFF"     # encabezados
SHEET_NUM, SHEET_NUM_FG = "#DCEFE4", "#1B2A23"       # n.º de fila
SHEET_CELL, SHEET_INK = "#FFFFFF", "#1B2A23"         # celdas
SHEET_FIRST_FG = "#1E5A45"                           # 1.ª columna (tratamiento / variedad)
SHEET_GROUP = "#123A2C"
SHEET_IA = "#FFF1C9"                                 # dato puesto por la IA (por confirmar)                              # grupos («Planta 1») sobre las subcolumnas


def rename_entry_photo(entry_id: int) -> None:
    """Foto de medición con su nombre nuevo (tratamiento + descripción): archivo, marcas de
    cajas (IA+) y, al respaldar, Drive."""
    a = app()
    try:
        got = a.db.rename_measure_photo(entry_id)
    except OSError as exc:
        a.toast(f"No se pudo renombrar la foto: {exc}")
        return
    if got:
        from ui import boxes
        if boxes.store().rename(*got):
            boxes.sync_now()


def rename_all_photos(db) -> int:
    """Una vez por ensayo: las fotos de mediciones que ya tenían tratamiento o descripción toman
    su nombre nuevo (antes «…-30.jpg»)."""
    if db.get_setting("measure_names_v1"):
        return 0
    n = 0
    for r in db.query("SELECT id FROM measure_entries WHERE path IS NOT NULL AND path <> ''"):
        got = db.rename_measure_photo(r["id"])
        if got:
            n += 1
            try:
                from ui import boxes
                boxes.store().rename(*got)
            except Exception:  # noqa: BLE001
                pass
    db.set_setting("measure_names_v1", True)
    return n


def _cell_button(text, width, bold=False, bg=None, fg=None, on_release=None, z: float = 1.0):
    """Celda-botón de la grilla (encabezados, n.º de fila, variedad). Un texto en dos
    líneas va más chico y sin cortar. z: zoom de la planilla (letra y alto)."""
    from kivy.uix.button import Button
    two = "\n" in text
    b = Button(text=text, size_hint=(None, None), size=(width, dp(38) * z),
               font_size=f"{(11 if two else 12.5) * z:.1f}sp", line_height=.95 if two else 1,
               bold=bold, background_normal="", background_down="",
               background_color=bg or c(SHEET_NUM), color=fg or c(SHEET_NUM_FG),
               halign="center", valign="middle", shorten=not two, shorten_from="right")
    b.bind(size=lambda w, sz: setattr(w, "text_size", (sz[0] - dp(8), sz[1])))
    if on_release:
        b.bind(on_release=on_release)
    return b


from kivy.uix.textinput import TextInput  # noqa: E402


class SheetCell(TextInput):
    """Celda de planilla: al mantenerla presionada abre el menú propio (en español) de copiar /
    pegar, en vez de los cuadritos «Cut / Copy / Paste» de Kivy."""
    HOLD_S = .5

    def __init__(self, **kw):
        super().__init__(**kw)
        self.use_bubble = self.use_handles = False
        self.on_hold = None
        self._hold = None

    def _cancel(self):
        if self._hold is not None:
            self._hold.cancel()
            self._hold = None

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not getattr(touch, "is_mouse_scrolling", False):
            self._cancel()
            self._hold = Clock.schedule_once(lambda *_: self._fire(), self.HOLD_S)
            self._origin = touch.pos
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        o = getattr(self, "_origin", None)
        if self._hold is not None and o and (abs(touch.x - o[0]) > dp(10) or abs(touch.y - o[1]) > dp(10)):
            self._cancel()
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        self._cancel()
        return super().on_touch_up(touch)

    def _fire(self):
        self._hold = None
        if self.on_hold:
            self.on_hold(self)


def _stack(top, below):
    """Caja vertical de tamaño fijo: `top` arriba y `below` abajo (sigue su tamaño)."""
    from kivy.uix.boxlayout import BoxLayout
    box = BoxLayout(orientation="vertical", size_hint=(None, None))
    box.add_widget(top)
    box.add_widget(below)

    def fit(*_):
        box.size = (max(top.width, below.width), top.height + below.height)

    below.bind(size=fit)
    top.bind(size=fit)
    fit()
    return box


def _round_action(icon, cb, bg=None, fg=None):
    """Botón redondo solo con ícono (la barra de abajo de la planilla)."""
    from kivymd.uix.button import MDIconButton
    return MDIconButton(icon=icon, on_release=lambda *_: cb(), md_bg_color=c(bg) if bg else c(theme.SURFACE, .92),
                        theme_icon_color="Custom", icon_color=c(fg) if fg else c(theme.LEAF_DARK),
                        icon_size=dp(26), size_hint=(None, None), size=(dp(56), dp(56)), pos_hint={"center_y": .5})


class MeasureScreen(MDScreen):
    """Registros de UNA medición en UNA semana: fotos con descripción o filas de planilla."""

    def load(self, measure_id: int, week_id: int):
        a = app()
        self.measure = a.db.get_measure(measure_id)
        self.week = a.db.get_week(week_id)
        self.ids.title.text = self.measure["name"]
        self._top_actions()
        try:
            rename_all_photos(a.db)               # una vez: nombres con tratamiento y descripción
            for e in a.db.list_entries(measure_id, week_id=week_id):   # lo cambiado en la web u otro equipo
                if e["path"]:
                    rename_entry_photo(e["id"])
        except Exception as exc:  # noqa: BLE001 (nunca impide abrir la medición)
            print("renombrar fotos de mediciones:", exc)
        kind = "PLANILLA DE DATOS" if self.measure["kind"] == "table" else "REGISTRO DE IMÁGENES"
        self.ids.kicker.text = f"{kind} · {ph.week_title(self.week).upper()}"
        self.ids.columns_text.text = (
            "Toque una celda o un encabezado para escribir · mantenga presionada una celda para copiar o "
            "pegar · los 3 puntos mueven o eliminan la columna · toque el n.º de fila para eliminarla · "
            "las lupas de arriba agrandan o achican la letra."
            if self.measure["kind"] == "table"
            else "Cada foto con su descripción y, si quiere, la variedad.")
        self.show_hint(getattr(self, "_hint_on", False))
        actions = self.ids.actions
        fast_clear(actions)
        self._ac_btn = None
        from kivy.factory import Factory
        if getattr(self, "_ia_key", None) != (measure_id, week_id):
            self._ia, self._pick, self._ia_key = {}, None, (measure_id, week_id)
            self._dict_rec = None
            if self.measure["kind"] == "table":       # el último dictado de la semana, a la vista
                got = self.dictations.for_measure(self.measure.get("uid") or str(measure_id),
                                                  self.week["start_date"][:10])
                self._dict_rec = got[-1] if got else None
        if self.measure["kind"] == "table":
            from ui.dictation_ui import GOLD, GOLD_INK
            # Solo íconos, centrados: más espacio para la planilla.
            for icon, cb, bg, fg in (("microphone", self.dictate, GOLD, GOLD_INK),
                                     ("table-row-plus-after", self.add_row, None, None),
                                     ("table-column-plus-after", self.add_column, None, None),
                                     ("table-cog", self.structure, None, None)):
                actions.add_widget(_round_action(icon, cb, bg, fg))
            import sheet_layout as SL
            if SL.is_grouped(self.measure["columns"]) and not a.db.list_entries(measure_id, week_id=week_id):
                try:   # planilla ordenada: cada semana parte con sus filas (una por parcela)
                    a.db.fill_sheet_rows(measure_id, week_id)
                except Exception as exc:  # noqa: BLE001
                    print("filas de la planilla:", exc)
        else:
            actions.add_widget(Factory.GhostButton(icon="camera-outline", text="Tomar foto",
                                                   on_release=lambda *_: self.add_images("camera")))
            actions.add_widget(Factory.GhostButton(icon="image-multiple-outline", text="Desde galería",
                                                   on_release=lambda *_: self.add_images("gallery")))
            self._ac_btn = Factory.GhostButton(icon="creation", text="",
                                               on_release=lambda *_: self.autocount_menu())
            actions.add_widget(self._ac_btn)
            self._autocount_btn()
        # «Pasar conteos a una planilla»: solo en registros de imágenes (encima de Exportar).
        tt = getattr(self, "_to_table", None)
        if tt is None:
            tt = self._to_table = Factory.GhostButton(icon="table-arrow-right", text="Pasar conteos a una planilla",
                                                      on_release=lambda *_: self.counts_to_table())
        if tt.parent is not None:
            tt.parent.remove_widget(tt)
        if self.measure["kind"] != "table":
            self.ids.body.add_widget(tt)
        self.refresh()

    def _top_actions(self):
        """Arriba a la derecha, en círculos suaves: lupas de la letra (planillas), Excel y guardar."""
        from kivymd.uix.button import MDIconButton
        items = [("file-excel-outline", self.export), ("content-save-outline", self.save)]
        if self.measure["kind"] == "table":
            items = [("magnify-minus", lambda: self.set_zoom(-1)),
                     ("magnify-plus", lambda: self.set_zoom(1))] + items
        box = self.ids.top_tools
        fast_clear(box)
        for icon, cb in items:
            box.add_widget(MDIconButton(icon=icon, on_release=lambda *_, f=cb: f(), icon_size=dp(20),
                                        md_bg_color=c(theme.SURFACE, .85), theme_icon_color="Custom",
                                        icon_color=c(theme.LEAF_DARK), pos_hint={"center_y": .5}))

    def toggle_hint(self):
        self.show_hint(not getattr(self, "_hint_on", False))

    def show_hint(self, on: bool):
        """El bombillo muestra u oculta la ayuda (y el conteo de filas/fotos)."""
        self._hint_on = on
        ids = self.ids
        card = ids.entries.parent
        for w in (ids.columns_text, ids.count_text):
            if on and w.parent is None:
                card.add_widget(w, index=card.children.index(ids.entries) + 1)
            elif not on and w.parent is not None:
                w.parent.remove_widget(w)
        self.ids.hint_btn.icon = "lightbulb-on" if on else "lightbulb-outline"

    def refresh(self):
        a = app()
        box = self.ids.entries
        fast_clear(box)
        entries = a.db.list_entries(self.measure["id"], week_id=self.week["id"])
        unit = "fila(s)" if self.measure["kind"] == "table" else "foto(s)"
        self.ids.count_text.text = f"{len(entries)} {unit} esta semana"
        if self.measure["kind"] == "table":
            self._build_grid(entries)
            return
        varieties = a.db.list_varieties(include_archived=True)
        from training_labels import count_text
        from ui import boxes
        for e in entries:
            rec = boxes.store().get(os.path.basename(e["path"] or ""))
            from training_labels import needs_review
            row = EntryRow(title=e["caption"] or "Sin descripción",
                           subtitle=_variety_label(e["variety_id"], varieties), item=e,
                           screen=self, has_thumb=True, can_count=bool(e["path"]),
                           counts=("[color=#E65100][b]IA · falta confirmar:[/b][/color] " if needs_review(rec) else "")
                           + count_text(rec, markup=True))
            row.ids.thumb_box.add_widget(thumb_widget(e["path"], 160))
            box.add_widget(row)
        if not entries:
            box.add_widget(MDLabel(text="Sin registros esta semana.", font_style="Caption",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))

    # ------------------------------------------------------ planilla (grilla)
    COL_W, NUM_W, VAR_W, SUB_W = dp(118), dp(40), dp(118), dp(104)

    def _build_grid(self, entries):
        """Grilla editable: n.º | Variedad | columnas… · celdas = TextInput que se guardan
        al salir de ellas. Desplazamiento horizontal si hay muchas columnas. Columnas
        «Planta 1 · Largo»: encabezado en dos niveles (Planta 1 arriba, Largo abajo)."""
        import sheet_layout as SL
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.gridlayout import GridLayout
        from kivy.uix.scrollview import ScrollView
        a = app()
        cols = list(self.measure["columns"])
        self._grouped = SL.is_grouped(cols)
        z = self.zoom = self._zoom()
        cw = (self.SUB_W if self._grouped else self.COL_W) * z
        rh = dp(38) * z                         # alto de fila (más compacto que antes)
        num_w = self.NUM_W * (0.85 + 0.15 * z)
        self._build_tools()
        varieties = a.db.list_varieties(include_archived=True)
        self._rows = {e["id"]: dict(e["data"]) for e in entries}
        self._cells = []
        self._row_label = {}
        sp = dp(2)
        # Izquierda fija (n.º y tratamiento) y a la derecha las columnas, que se desplazan
        # hacia el lado: con muchas plantas siempre se ve de qué fila es cada celda.
        left = GridLayout(cols=2, size_hint=(None, None), spacing=sp, padding=(sp, sp, 0, sp))
        grid = GridLayout(cols=max(1, len(cols)), size_hint=(None, None), spacing=sp, padding=sp)
        for g_ in (left, grid):
            g_.bind(minimum_width=g_.setter("width"), minimum_height=g_.setter("height"))
        head_bg, head_fg = c(SHEET_HEAD), c(SHEET_HEAD_FG)
        left.add_widget(_cell_button("#", num_w, True, head_bg, head_fg, z=z))
        self.var_w = (dp(150) if a.db.is_predio else self.VAR_W) * (0.75 + 0.25 * z)   # predio: variedad y año
        self._first = a.db.sheet_first()
        names = a.db.treatment_names()
        vmap = {v["id"]: v for v in varieties}
        self._heads = []
        left.add_widget(self._head_cell(self._first["title"], self.var_w, None, z=z))
        for col in cols:
            grid.add_widget(self._head_cell(SL.split(col)[1], cw, col, small=self._grouped, z=z))
        for i, e in enumerate(entries):
            left.add_widget(_cell_button(str(i + 1), num_w, bg=c(SHEET_NUM), z=z,
                                         on_release=lambda *_, e=e, n=i + 1: self.row_menu(e, n)))
            v = vmap.get(e["variety_id"])
            if not v:
                label = "—"
            elif a.db.is_trial:
                label = a.db.sheet_label(v, names, self._first, two_lines=True)
            else:
                label = _variety_label(e["variety_id"], varieties, two_lines=True)
            self._row_label[e["id"]] = " ".join(label.split())
            left.add_widget(_cell_button(label, self.var_w, bg=c(SHEET_CELL), fg=c(SHEET_FIRST_FG), z=z,
                                         on_release=lambda *_, e=e: self.pick_row_variety(e)))
            row_cells = []
            for col in cols:
                fz = sp_(14 * z)
                ia = (e["id"], col) in self._ia
                ti = SheetCell(text=str(e["data"].get(col, "")), multiline=False, write_tab=False,
                               size_hint=(None, None), size=(cw, rh), font_size=fz, halign="center",
                               padding=(dp(4), max(0, (rh - fz * 1.25) / 2)), background_normal="",
                               background_active="", background_color=c(SHEET_IA if ia else SHEET_CELL),
                               foreground_color=c(SHEET_INK), cursor_color=c(SHEET_HEAD))
                ti.entry_id, ti.col = e["id"], col
                ti.native_edit = False   # planilla: se escribe de corrido con el teclado de la app
                ti.on_hold = self.cell_menu
                ti.bind(focus=self._cell_focus)
                ti.bind(on_text_validate=self._cell_next)
                grid.add_widget(ti)
                row_cells.append(ti)
            self._cells.append(row_cells)
        content, fixed = grid, left
        if self._grouped:          # fila de arriba: «Planta 1», «Planta 2»… sobre sus subcolumnas
            top_bg = c(SHEET_GROUP)
            top = BoxLayout(size_hint=(None, None), height=dp(32) * z, spacing=sp, padding=(sp, sp, sp, 0))
            for g, cs in SL.groups(cols):
                w = len(cs) * cw + (len(cs) - 1) * sp
                b = _cell_button(g or "", w, bold=True, bg=top_bg, fg=head_fg, z=z,
                                 on_release=(lambda *_, g=g: self.group_menu(g)) if g else None)
                b.height = dp(30) * z
                top.add_widget(b)
            top.bind(minimum_width=top.setter("width"))
            content = _stack(top, grid)
            ltop = BoxLayout(size_hint=(None, None), height=dp(32) * z, padding=(sp, sp, 0, 0))
            corner = _cell_button("", num_w + sp + self.var_w, bg=top_bg, z=z)
            corner.height = dp(30) * z
            ltop.add_widget(corner)
            ltop.width = corner.width + sp
            fixed = _stack(ltop, left)
        # Arrastrar hacia el lado mueve la planilla aunque se empiece sobre una celda: el toque
        # solo entra a la celda si casi no se mueve (antes se «pegaba» y no se desplazaba).
        sv = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint=(1, None),
                        bar_width=dp(4), scroll_type=["bars", "content"], scroll_distance=dp(8),
                        scroll_timeout=250)
        sv.add_widget(content)
        self._sv = sv
        row = BoxLayout(size_hint=(1, None))
        from kivy.uix.widget import Widget
        fixed = _stack(fixed, Widget(size_hint=(None, None), size=(0, dp(8))))   # mismo alto que la barra de abajo
        row.add_widget(fixed)
        row.add_widget(sv)
        fit = lambda *_: (setattr(sv, "height", content.height + dp(8)),  # noqa: E731
                          setattr(row, "height", max(fixed.height, content.height + dp(8))))
        content.bind(height=fit)
        fixed.bind(height=fit)
        self.ids.entries.add_widget(row)
        if not entries:
            self.ids.entries.add_widget(MDLabel(
                text="Sin filas esta semana: toque «Agregar fila».", font_style="Caption",
                adaptive_height=True, theme_text_color="Custom", text_color=c(theme.MUTED)))

    # ------------------------------------------------ tamaño de letra (zoom)
    ZOOMS = (0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.45)

    def _zoom(self) -> float:
        try:
            z = float(app().db.get_setting("sheet_zoom", 1.0) or 1.0)
        except (TypeError, ValueError):
            z = 1.0
        return min(self.ZOOMS, key=lambda x: abs(x - z))

    def set_zoom(self, step: int):
        self.commit_cells()
        i = self.ZOOMS.index(self._zoom())
        z = self.ZOOMS[max(0, min(len(self.ZOOMS) - 1, i + step))]
        app().db.set_setting("sheet_zoom", z)
        app().toast(f"Letra {round(z * 100)} %")
        x = self._sv.scroll_x if getattr(self, "_sv", None) else 0
        self.refresh()
        Clock.schedule_once(lambda *_: setattr(self._sv, "scroll_x", x) if getattr(self, "_sv", None) else None, 0)

    def _build_tools(self):
        """Sobre la grilla: el dictado (si hay). La letra se cambia con las lupas de arriba."""
        from kivy.uix.boxlayout import BoxLayout
        from kivymd.uix.button import MDIconButton
        box = self.ids.entries
        old = getattr(self, "_dict_card", None)
        if old is not None:
            old.stop_audio()
        rec = getattr(self, "_dict_rec", None)
        if rec is not None:
            from ui.dictation_ui import DictationCard
            n = len(self.dictations.for_measure(rec["measure"], rec["week"]))
            self._dict_card = DictationCard(self, rec, n_total=n)
            box.add_widget(self._dict_card)
        else:
            self._dict_card = None

    # ------------------------------------------------ dictar datos (voz)
    @property
    def dictations(self):
        st = getattr(self, "_dstore", None)
        if st is None:
            import voice
            from platform_utils import get_data_dir
            st = self._dstore = voice.Store(get_data_dir())
        return st

    def _mkey(self):
        return self.measure.get("uid") or str(self.measure["id"])

    def dictate(self):
        """Grabar: barra abajo con pausa, terminar, descartar y «modo bolsillo»."""
        import voice
        a = app()
        self.commit_cells()
        if not voice.can_record():
            a.toast("Grabar audio funciona en el teléfono (en la web: suba un archivo de audio).")
            return

        def start(ok):
            if not ok:
                a.toast("Sin permiso para el micrófono: actívelo en los ajustes del teléfono.")
                return
            from platform_utils import slugify
            from ui.dictation_ui import RecordPanel
            path = self.dictations.new_path(slugify(self.measure["name"])[:30] or "dictado")
            panel = RecordPanel(path, self.measure["name"], self._dict_done)
            try:
                panel.start()
            except Exception as exc:  # noqa: BLE001
                a.toast(f"No se pudo grabar: {exc}")
        Clock.schedule_once(lambda *_: voice.ask_mic(lambda ok: Clock.schedule_once(lambda *_: start(ok))), 0)

    def _dict_done(self, path, secs):
        a = app()
        rec = self.dictations.add(self._mkey(), self.week["start_date"][:10], path, secs)
        try:
            a.backup_extra(path, self.week["start_date"], self.measure["name"])     # respaldo en Drive
        except Exception:  # noqa: BLE001
            pass
        self._dict_rec = rec
        self.refresh()
        self.transcribe(rec)

    def transcribe(self, rec):
        a = app()
        import scout_ai
        try:
            key = scout_ai.load_keys(a.scout).get("gemini")
        except Exception:  # noqa: BLE001
            key = None
        if not key:
            a.toast("Falta la clave de Gemini: AeonScout › Claves de IA (es gratis). El audio quedó guardado.")
            return
        rec.update(status="working")
        self.dictations.update(rec["id"], status="working")
        if self._dict_card is not None:
            self._dict_card.render()

        def work():
            import voice
            try:
                text, err = voice.transcribe(key, rec["path"], db=a.scout), None
            except Exception as exc:  # noqa: BLE001
                text, err = "", str(exc)
            Clock.schedule_once(lambda *_: done(text, err))

        def done(text, err):
            fields = {"status": "error", "error": err} if err else {"status": "done", "text": text, "used": []}
            rec.update(fields)
            self.dictations.update(rec["id"], **fields)
            if self._dict_rec is rec:
                self.refresh()
            a.toast("No se pudo transcribir (el audio quedó guardado)." if err else
                    "Transcripción lista: toque un número y luego su celda, o «Ordenar con IA».")
        a.workers.submit(work)

    def pick_number(self, card, chip):
        """Número elegido: el próximo toque en una celda lo pone ahí."""
        prev = self._pick
        if prev is not None:
            prev[1].set(sel=False)
        if prev is not None and prev[1] is chip:
            self._pick = None
            return
        chip.set(sel=True)
        self._pick = (card, chip)
        app().toast(f"«{chip.value}»: toque la celda donde va")

    def _put_pick(self, ti):
        card, chip = self._pick
        self._pick = None
        chip.set(sel=False, used=True)
        card.mark_used(chip.idx)
        ti.text = chip.value
        self._cell_focus(ti, False)

    def arrange(self, rec):
        """La IA ubica los números en la planilla (en amarillo hasta «Confirmar todo»)."""
        a = app()
        import scout_ai
        try:
            key = scout_ai.load_keys(a.scout).get("gemini")
        except Exception:  # noqa: BLE001
            key = None
        if not key:
            a.toast("Falta la clave de Gemini: AeonScout › Claves de IA (es gratis).")
            return
        self.commit_cells()
        rows = {}
        for eid, lab in self._row_label.items():
            name, k = lab, 2
            while name in rows:
                name, k = f"{lab} ({k})", k + 1
            rows[name] = eid
        cols = list(self.measure["columns"])
        a.toast("La IA está ordenando los datos…")

        def work():
            import voice
            try:
                got, err = voice.arrange(key, rec.get("text") or "", list(rows), cols, db=a.scout), None
            except Exception as exc:  # noqa: BLE001
                got, err = [], str(exc)
            Clock.schedule_once(lambda *_: done(got, err))

        def done(got, err):
            if err:
                a.toast(f"IA: {err[:120]}")
                return
            n = 0
            with a.db.batch():
                for it in got:
                    eid = rows[it["row"]]
                    data = self._rows.get(eid)
                    if data is None:
                        continue
                    key_ = (eid, it["col"])
                    if key_ not in self._ia:
                        self._ia[key_] = data.get(it["col"], "")
                    data[it["col"]] = it["value"]
                    a.db.update_entry(eid, data=data)
                    n += 1
            # los números que la IA usó quedan tachados
            import voice
            vals = [v for _a, _b, v in voice.numbers(rec.get("text") or "")]
            used, pool = set(rec.get("used") or []), [it["value"] for it in got]
            for i, v in enumerate(vals):
                if v in pool:
                    used.add(i)
                    pool.remove(v)
            rec["used"] = sorted(used)
            self.dictations.update(rec["id"], used=rec["used"])
            self.refresh()
            a.toast(f"La IA ubicó {n} dato(s): revise los amarillos y toque «Confirmar todo»" if n
                    else "La IA no encontró dónde ubicar los datos")
        a.workers.submit(work)

    def ia_pending(self) -> int:
        return len(getattr(self, "_ia", {}) or {})

    def ia_confirm(self):
        self._ia = {}
        self.refresh()
        app().toast("Datos confirmados")

    def ia_undo(self):
        a = app()
        with a.db.batch():
            for (eid, col), old in self._ia.items():
                data = self._rows.get(eid)
                if data is None:
                    continue
                if old in ("", None):
                    data.pop(col, None)
                else:
                    data[col] = old
                a.db.update_entry(eid, data=data)
        self._ia = {}
        self.refresh()
        a.toast("Se deshizo lo que puso la IA")

    def pick_dictation(self):
        got = self.dictations.for_measure(self._mkey(), self.week["start_date"][:10])
        if not got:
            app().toast("No hay otros dictados esta semana")
            return

        def show(r):
            self._dict_rec, self._pick = r, None
            self.refresh()

        def remove(r):
            def go():
                self.dictations.delete(r["id"])
                if self._dict_rec and self._dict_rec["id"] == r["id"]:
                    self._dict_rec = None
                self.refresh()
            confirm("Borrar dictado", "Se borra el audio y su transcripción del teléfono.", [("Borrar", go)])

        import voice
        from ui.dictation_ui import fmt_time
        items = [(f"{r['created'][11:16]} · {fmt_time(r.get('seconds', 0))}",
                  (r.get("text") or {"pending": "Sin transcribir", "working": "Transcribiendo…",
                                      "error": "Error al transcribir"}.get(r.get("status"), ""))[:70],
                  lambda r=r: show(r), None, lambda r=r: remove(r)) for r in reversed(got)]
        pick_dialog("Dictados de esta semana", items)

    def close_dictation(self):
        if self._dict_card is not None:
            self._dict_card.stop_audio()
        self._dict_rec, self._pick = None, None
        self.refresh()

    def _head_cell(self, text: str, width, col, small: bool = False, z: float = 1.0):
        """Encabezado editable en el lugar: se toca y se escribe el nombre. «⋮» = mover,
        eliminar (columnas) o qué mostrar (1.ª columna). col=None: la 1.ª columna."""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.textinput import TextInput
        from kivymd.icon_definitions import md_icons
        head_bg, head_fg = c(SHEET_HEAD), c(SHEET_HEAD_FG)
        h = dp(38) * z
        fz = sp_((11 if small else 12.5) * z)
        box = BoxLayout(size_hint=(None, None), size=(width, h))
        ti = TextInput(text=text, multiline=False, write_tab=False, font_size=fz,
                       halign="center", padding=(dp(4), max(0, (h - fz * 1.25) / 2)), background_normal="",
                       background_active="", background_color=head_bg, foreground_color=head_fg,
                       cursor_color=head_fg, selection_color=c("#FFFFFF", .35))
        ti.native_edit = False        # se escribe directo sobre el encabezado
        ti.col = col
        ti.bind(focus=self._head_focus)
        ti.bind(on_text_validate=lambda t: setattr(t, "focus", False))
        dots = Button(text=md_icons["dots-vertical"], font_name="Icons", font_size=sp_(17 * z),
                      size_hint_x=None, width=dp(20) * z, background_normal="", background_down="",
                      background_color=head_bg, color=head_fg)
        dots.bind(on_release=lambda *_: self.first_column_menu() if col is None else self.column_menu(ti.col))
        box.add_widget(ti)
        box.add_widget(dots)
        self._heads.append(ti)
        return box

    def _head_focus(self, ti, focused):
        if focused:
            Clock.schedule_once(lambda *_: ti.select_all(), .05)
            return
        a = app()
        new = ti.text.strip()
        if ti.col is None:                               # 1.ª columna (Tratamiento / Variedad)
            if new and new != self._first["title"]:
                self._first = a.db.set_sheet_first(title=new)
            ti.text = self._first["title"]
            return
        old = ti.col
        import sheet_layout as SL
        group, sub = SL.split(old)
        if group is not None:                            # subcolumna: se renombra en todos los grupos
            if not new or new == sub:
                ti.text = sub
                return
            try:
                for o, n in SL.rename_sub(self.measure["columns"], sub, SL.parse_vars(new)[0] if SL.parse_vars(new) else new):
                    a.db.rename_measure_column(self.measure["id"], o, n)
            except ValueError as exc:
                a.toast(str(exc))
                ti.text = sub
                return
            self.measure = a.db.get_measure(self.measure["id"])
            Clock.schedule_once(lambda *_: self.refresh(), 0)
            return
        if not new or new == old:
            ti.text = old
            return
        try:
            a.db.rename_measure_column(self.measure["id"], old, new)
        except ValueError as exc:
            a.toast(str(exc))
            ti.text = old
            return
        self.measure = a.db.get_measure(self.measure["id"])
        ti.col = new
        idx = [h.col for h in self._heads[1:]].index(new)
        for row in self._cells:                          # las celdas siguen a la columna
            row[idx].col = new
        for data in self._rows.values():
            if old in data:
                data[new] = data.pop(old)

    def first_column_menu(self):
        """1.ª columna: qué se muestra en cada fila y llenar una fila por parcela."""
        self.commit_cells()
        a = app()
        trial = a.db.is_trial
        unit = "parcela" if trial else "variedad"

        def show(mode):
            a.db.set_sheet_first(show=mode)
            self.refresh()

        items = []
        if trial:
            now = lambda m, t: ("En uso · " + t) if self._first["show"] == m else t
            on = lambda m: c(theme.LEAF) if self._first["show"] == m else None
            items += [
                ("Descripción del tratamiento", now("desc", "Ej.: 34,5 kg/ha (sin descripción: T3R1)"),
                 lambda: show("desc"), on("desc")),
                ("Código", now("code", "Ej.: T3R1"), lambda: show("code"), on("code")),
                ("Descripción y código", now("both", "Ej.: 34,5 kg/ha · T3R1"), lambda: show("both"),
                 on("both")),
            ]
        items.append((f"Una fila por {unit}", f"Agrega las filas que falten esta semana, una por cada {unit}",
                      self.fill_rows))
        items.append(("Cambiar el nombre", "Toque el encabezado y escriba (ej.: Tratamiento, Parcela)",
                      lambda: Clock.schedule_once(lambda *_: setattr(self._heads[0], "focus", True), .3)))
        pick_dialog(f"Columna «{self._first['title']}»", items)

    def fill_rows(self):
        a = app()
        n = a.db.fill_sheet_rows(self.measure["id"], self.week["id"])
        a.toast(f"{n} fila(s) agregada(s)" if n else "Ya hay una fila por cada una")
        self.refresh()

    def _cell_focus(self, ti, focused):
        if focused and getattr(self, "_pick", None) is not None:      # número del dictado -> celda
            Clock.schedule_once(lambda *_: setattr(ti, "focus", False), 0)
            self._put_pick(ti)
            return
        if focused:
            sv = getattr(self, "_sv", None)
            if sv is not None and ti.parent is not None:
                Clock.schedule_once(lambda *_: sv.scroll_to(ti, padding=dp(30), animate=False), 0)
            return
        data = self._rows.get(ti.entry_id)
        if data is None:
            return
        value = ti.text.strip()
        if str(data.get(ti.col, "")) == value:
            return
        if value:
            data[ti.col] = value
        else:
            data.pop(ti.col, None)
        app().db.update_entry(ti.entry_id, data=data)

    def _cell_next(self, ti):
        """Enter: baja a la celda de la fila siguiente (misma columna). Planilla por plantas:
        pasa a la derecha (laterales → largo → entrenudos → planta siguiente) y luego a la
        fila de abajo."""
        if getattr(self, "_grouped", False):
            flat = [x for row in self._cells for x in row]
            if ti in flat and flat.index(ti) + 1 < len(flat):
                nxt = flat[flat.index(ti) + 1]
                Clock.schedule_once(lambda *_: setattr(nxt, "focus", True), .05)
            return
        for r, row in enumerate(self._cells):
            if ti in row and r + 1 < len(self._cells):
                nxt = self._cells[r + 1][row.index(ti)]
                Clock.schedule_once(lambda *_: setattr(nxt, "focus", True), .05)
                return

    def commit_cells(self):
        """Guarda la celda en edición (al salir de la pantalla o antes de redibujar)."""
        for row in getattr(self, "_cells", []):
            for ti in row:
                if ti.focus:
                    ti.focus = False
                    self._cell_focus(ti, False)

    def on_pre_leave(self, *_):
        self.commit_cells()
        card = getattr(self, "_dict_card", None)
        if card is not None:
            card.stop_audio()

    def save(self):
        """Disquete: guarda lo escrito (también se guarda solo al salir), avisa y vuelve."""
        self.commit_cells()
        from ui import celebrate
        app().back()
        celebrate.saved("Medición guardada")

    def add_row(self):
        self.commit_cells()
        a = app()
        a.db.add_entry(self.measure["id"], self.week["id"], None, data={})
        self.refresh()
        if self._cells:   # foco en la primera celda de la fila nueva
            Clock.schedule_once(lambda *_: setattr(self._cells[-1][0], "focus", True), .15)

    def add_column(self):
        """Columna nueva con nombre provisorio y el cursor en su encabezado para escribirlo.
        Planilla por plantas: otra planta, otra evaluación en todas o una columna suelta."""
        self.commit_cells()
        a = app()
        import sheet_layout as SL
        if SL.is_grouped(self.measure["columns"]) and not getattr(self, "_loose", False):
            nxt = SL.next_group(self.measure["columns"])
            word = SL.unit_word(self.measure["columns"])

            def loose():
                self._loose = True
                try:
                    self.add_column()
                finally:
                    self._loose = False

            pick_dialog("Agregar", [
                (f"Otra: «{nxt[0]}»", "Con las mismas evaluaciones", lambda: self._set_columns(
                    self.measure["columns"] + nxt[1])),
                (f"Otra evaluación en todas las {word}", "Ej.: Diámetro (mm)", self.add_evaluation),
                ("Una columna suelta al final", "Ej.: Observaciones", loose),
            ])
            return
        cols = set(self.measure["columns"])
        n = len(cols) + 1
        while f"Columna {n}" in cols:
            n += 1
        try:
            a.db.add_measure_column(self.measure["id"], f"Columna {n}")
        except ValueError as exc:
            a.toast(str(exc))
            return
        self.measure = a.db.get_measure(self.measure["id"])
        self.refresh()
        Clock.schedule_once(lambda *_: setattr(self._heads[-1], "focus", True), .2)

    def column_menu(self, col: str):
        self.commit_cells()
        a = app()
        mid = self.measure["id"]
        import sheet_layout as SL
        group, sub = SL.split(col)
        if group is not None:
            word = SL.unit_word(self.measure["columns"])
            same = [x for x in self.measure["columns"] if SL.split(x)[0] is not None and SL.split(x)[1] == sub]

            def rename_all():
                ti = next((h for h in self._heads if h.col == col), None)
                if ti is not None:
                    Clock.schedule_once(lambda *_: setattr(ti, "focus", True), .3)

            def drop(which):
                confirm("Eliminar", f"Se eliminará{'n' if len(which) > 1 else ''} {len(which)} columna(s) "
                        "y sus datos en todas las semanas.", [("Eliminar", lambda: self._set_columns(
                            [x for x in self.measure["columns"] if x not in which]))])

            pick_dialog(f"«{sub}» ({group})", [
                ("Cambiar el nombre", f"En todas las {word}", rename_all),
                (f"Eliminar «{sub}» en todas las {word}", f"{len(same)} columna(s) y sus datos",
                 lambda: drop(same)),
                (f"Eliminar solo la de {group}", "Esta columna y sus datos", lambda: drop([col])),
            ])
            return

        def rename():
            ti = next((h for h in self._heads if h.col == col), None)
            if ti is not None:
                Clock.schedule_once(lambda *_: setattr(ti, "focus", True), .3)

        def remove():
            def go():
                try:
                    a.db.delete_measure_column(mid, col)
                except ValueError as exc:
                    a.toast(str(exc))
                    return
                self.measure = a.db.get_measure(mid)
                self.refresh()

            confirm("Eliminar columna", f"Se eliminará la columna «{col}» y sus datos en todas "
                    "las semanas.", [("Eliminar", go)])

        def move(step):
            cols = list(self.measure["columns"])
            i = cols.index(col)
            j = max(0, min(len(cols) - 1, i + step))
            cols[i], cols[j] = cols[j], cols[i]
            a.db.update_measure(mid, columns=cols)
            self.measure = a.db.get_measure(mid)
            self.refresh()

        pick_dialog(f"Columna «{col}»", [
            ("Cambiar el nombre", "También: toque el encabezado y escriba", rename),
            ("Mover a la izquierda", "Cambia el orden de las columnas", lambda: move(-1)),
            ("Mover a la derecha", "Cambia el orden de las columnas", lambda: move(1)),
            ("Eliminar columna", "Borra la columna y sus datos", remove),
        ])

    def _set_columns(self, cols: list[str]) -> None:
        """Nuevas columnas (las que salen pierden sus datos en todas las semanas)."""
        a = app()
        mid = self.measure["id"]
        gone = [x for x in self.measure["columns"] if x not in cols]
        try:
            with a.db.batch():
                for x in gone:
                    a.db.delete_measure_column(mid, x)
                a.db.update_measure(mid, columns=cols)
        except ValueError as exc:
            a.toast(str(exc))
            return
        self.measure = a.db.get_measure(mid)
        self.refresh()

    def add_evaluation(self):
        import sheet_layout as SL
        from kivy.factory import Factory
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
        form.f = Factory.Field(hint_text="Nombre de la evaluación")
        form.add_widget(form.f)

        def ok(f):
            name = (SL.parse_vars(f.f.text) or [""])[0]
            if not name:
                app().toast("Escriba el nombre")
                return False
            if any(SL.split(x)[1] == name for x in self.measure["columns"]):
                app().toast(f"Ya existe «{name}»")
                return False
            self._set_columns(SL.add_sub(self.measure["columns"], name))

        form_dialog(f"Otra evaluación en todas las {SL.unit_word(self.measure['columns'])}", form, ok, "AGREGAR")

    def group_menu(self, group: str):
        """Toque en «Planta 3»: cambiar el nombre, agregar otra o eliminarla."""
        self.commit_cells()
        import sheet_layout as SL
        from kivy.factory import Factory
        cols = self.measure["columns"]
        nxt = SL.next_group(cols)
        mine = [x for x in cols if SL.split(x)[0] == group]

        def rename():
            form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
            form.f = Factory.Field(hint_text="Nombre", text=group)
            form.add_widget(form.f)

            def ok(f):
                new = " ".join(f.f.text.replace(SL.SEP.strip(), " ").split())
                if not new or new == group:
                    return
                if any(SL.split(x)[0] == new for x in cols):
                    app().toast(f"Ya existe «{new}»")
                    return False
                a = app()
                try:
                    with a.db.batch():
                        for x in mine:
                            a.db.rename_measure_column(self.measure["id"], x, SL.join(new, SL.split(x)[1]))
                except ValueError as exc:
                    a.toast(str(exc))
                    return False
                self.measure = a.db.get_measure(self.measure["id"])
                self.refresh()

            form_dialog(f"Cambiar «{group}»", form, ok)

        items = [("Cambiar el nombre", f"Ej.: {group} a «Planta norte»", rename)]
        if nxt:
            items.append((f"Agregar «{nxt[0]}»", "Al final, con las mismas evaluaciones",
                          lambda: self._set_columns(cols + nxt[1])))
        items.append((f"Eliminar «{group}»", f"{len(mine)} columna(s) y sus datos en todas las semanas",
                      lambda: confirm("Eliminar", f"Se eliminará «{group}» con sus datos.",
                                      [("Eliminar", lambda: self._set_columns(
                                          [x for x in cols if x not in mine]))])))
        pick_dialog(group, items)

    def structure(self):
        """«Ordenar planilla»: el mismo asistente de la planilla nueva, sobre esta."""
        self.commit_cells()
        a = app()
        form = _structure_box(a.db, self.measure["columns"])

        def ok(f):
            try:
                cols, reps = f.result()
                a.db.structure_measure(self.measure["id"], cols)
                n = a.db.fill_sheet_rows(self.measure["id"], self.week["id"], reps)
            except ValueError as exc:
                a.toast(str(exc))
                return False
            self.measure = a.db.get_measure(self.measure["id"])
            self.refresh()
            a.toast(f"Planilla ordenada · {n} fila(s) nueva(s)" if n else "Planilla ordenada")

        form_dialog("Ordenar planilla", form, ok, "APLICAR")

    # ------------------------------------------------- copiar / pegar celdas
    def cell_menu(self, ti):
        """Mantener presionada una celda: copiar, cortar, pegar (también un bloque copiado de
        Excel o Sheets), borrar o rellenar hacia abajo. En español y con el portapapeles real."""
        import clip
        self.commit_cells()
        a = app()
        try:
            got = clip.paste()
        except Exception as exc:  # noqa: BLE001
            got = ""
            print("pegar:", exc)
        block = clip.table(got)
        n = sum(len(r) for r in block)
        pos = next(((r, row.index(ti)) for r, row in enumerate(self._cells) if ti in row), None)

        def put(cell, value):
            cell.text = value
            self._cell_focus(cell, False)

        def do_copy(cut=False):
            try:
                clip.copy(ti.text)
                if cut:
                    put(ti, "")
                a.toast("Copiado" if not cut else "Cortado")
            except Exception as exc:  # noqa: BLE001
                a.toast(f"No se pudo copiar: {exc}")

        def do_paste():
            done = self.paste_block(ti, block)
            if n > 1:
                a.toast(f"{done} valor(es) pegado(s)" + ("" if done == n else f" (de {n}: faltan filas o columnas)"))

        def fill_down():
            if pos is None:
                return
            r0, c0 = pos
            with a.db.batch():
                for row in self._cells[r0 + 1:]:
                    put(row[c0], ti.text)

        def copy_row():
            if pos is not None:
                clip.copy("\t".join(x.text for x in self._cells[pos[0]]))
                a.toast("Fila copiada (se pega en Excel o en otra fila)")

        preview = (got[:30] + "…") if len(got) > 30 else got
        items = [("Copiar", ti.text or "(vacía)", do_copy),
                 ("Cortar", "Copia y deja la celda vacía", lambda: do_copy(True))]
        if n > 1:
            items.append((f"Pegar {n} valores desde aquí", "Copiados de Excel, Sheets u otra fila", do_paste))
        elif got:
            items.append(("Pegar", preview.replace("\n", " "), do_paste))
        items += [("Borrar", "Deja la celda vacía", lambda: put(ti, "")),
                  ("Rellenar hacia abajo", "Copia este valor en las filas de abajo", fill_down),
                  ("Copiar la fila", "Todos los valores de esta fila", copy_row)]
        pick_dialog("Celda", items)

    def paste_block(self, ti, block: list[list[str]]) -> int:
        """Pega un bloque (filas × columnas) desde la celda `ti` hacia la derecha y abajo."""
        pos = next(((r, row.index(ti)) for r, row in enumerate(self._cells) if ti in row), None)
        if pos is None:
            return 0
        r0, c0 = pos
        done = 0
        with app().db.batch():
            for dr, vals in enumerate(block):
                if r0 + dr >= len(self._cells):
                    break
                row = self._cells[r0 + dr]
                for dc, v in enumerate(vals):
                    if c0 + dc < len(row):
                        row[c0 + dc].text = v.strip()
                        self._cell_focus(row[c0 + dc], False)
                        done += 1
        return done

    def row_menu(self, entry: dict, n: int):
        self.commit_cells()
        pick_dialog(f"Fila {n}", [
            (f"Elegir {app().db.sheet_first()['title'].lower()}", "Asocia la fila (sale en su informe)",
             lambda: self.pick_row_variety(entry)),
            ("Eliminar fila", "Borra los datos de esta fila", lambda: self.delete_entry(entry)),
        ])

    def pick_row_variety(self, entry: dict):
        self.commit_cells()
        a = app()

        def choose(vid):
            a.db.update_entry(entry["id"], variety_id=vid)
            self.refresh()

        title = a.db.sheet_first()["title"]
        if a.db.is_trial:
            names = a.db.treatment_names()
            choices = []
            for v in a.db.list_varieties():
                if a.db.is_parcel(v):
                    main, tag = a.db.parcel_labels(v, names)
                    choices.append((main, tag, lambda v=v: choose(v["id"])))
        else:
            choices = _variety_choices(a.db.list_varieties(), choose)
        pick_dialog(f"{title} de la fila", [("— General", "Sin asociar", lambda: choose(None))] + choices)

    # ----------------------------------------------------------- registros
    def entry_dialog(self, entry: dict):
        """Descripción y variedad (opcional) de una foto de la medición."""
        a = app()
        from kivy.factory import Factory
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6),
                           padding=(0, dp(22), 0, 0))
        state = {"variety_id": entry["variety_id"]}
        varieties = a.db.list_varieties()
        caption = Factory.Field(hint_text="Descripción", text=entry.get("caption") or "")
        vbtn = Factory.GhostButton(icon="fruit-cherries")

        def set_variety(vid):
            state["variety_id"] = vid
            vbtn.text = f"Variedad: {_variety_label(vid, varieties)}"

        vbtn.bind(on_release=lambda *_: pick_dialog(
            "Variedad", [("General", "Sin variedad específica", lambda: set_variety(None))]
            + _variety_choices(varieties, set_variety)))
        set_variety(state["variety_id"])
        form.add_widget(caption)
        form.add_widget(vbtn)

        def ok(_f):
            a.db.update_entry(entry["id"], caption=caption.text, variety_id=state["variety_id"])
            rename_entry_photo(entry["id"])        # nombre con tratamiento y descripción
            self.refresh()

        form_dialog("Foto", form, ok)

    def edit_entry(self, entry: dict):
        self.entry_dialog(entry)

    def delete_entry(self, entry: dict):
        def go():
            app().db.delete_entry(entry["id"])
            self.refresh()

        what = "esta fila" if self.measure["kind"] == "table" else "esta foto (el archivo queda en el teléfono)"
        confirm("Eliminar registro", f"¿Eliminar {what}?", [("Eliminar", go)])

    # ------------------------------------------- conteo automático con IA
    def _autocount_key(self):
        return f"autocount:{self.measure.get('uid') or self.measure['id']}"

    def autocount_mode(self) -> str:
        """«ask» (preguntar al tomar fotos), «yes» (contar siempre) o «no» en esta medición."""
        return app().db.get_setting(self._autocount_key(), "ask") or "ask"

    def set_autocount(self, mode: str):
        app().db.set_setting(self._autocount_key(), mode)
        self._autocount_btn()

    def _autocount_btn(self):
        b = getattr(self, "_ac_btn", None)
        if b is not None:
            b.text = {"ask": "Conteo con IA: preguntar", "yes": "Conteo con IA: siempre",
                      "no": "Conteo con IA: no"}[self.autocount_mode()]

    def autocount_menu(self):
        from ui.common import pick_dialog
        pending = self._uncounted()
        items = [("Preguntar al tomar fotos", "Cada vez elige si contar o no", lambda: self.set_autocount("ask")),
                 ("Contar siempre en esta medición", "Cada foto nueva se cuenta sola con IA",
                  lambda: self.set_autocount("yes")),
                 ("No contar en esta medición", "Solo fotos (puede contar a mano con el botón contar)",
                  lambda: self.set_autocount("no"))]
        if pending:
            items.append((f"Contar ahora las {len(pending)} foto(s) sin contar de esta semana",
                          "Botones, flores y frutos por estadio · quedan por confirmar",
                          lambda: self.auto_count([e["id"] for e in pending])))
        pick_dialog("Conteo automático de estructuras", items,
                    subtitle="La IA (Gemini) cuenta las estructuras productivas desde el botón floral: "
                             "botones, flores y frutos por estadio. Usted revisa y confirma.")

    def _uncounted(self):
        from training_labels import is_marked
        from ui import boxes
        return [e for e in app().db.list_entries(self.measure["id"], week_id=self.week["id"])
                if e["path"] and not is_marked(boxes.store().get(os.path.basename(e["path"])))]

    def _ask_autocount(self, then):
        """Antes de tomar fotos: ¿contar estructuras con IA? (o lo ya elegido en la medición)."""
        mode = self.autocount_mode()
        if mode != "ask":
            then(mode == "yes")
            return
        from ui.common import pick_dialog
        pick_dialog("¿Contar estructuras con IA?", [
            ("Sí, contar esta vez", "Botones, flores y frutos por estadio de cada foto", lambda: then(True)),
            ("Sí, siempre en esta medición", "No vuelve a preguntar", lambda: (self.set_autocount("yes"), then(True))),
            ("No, solo fotos", "Puede contarlas después con el botón contar o «Conteo con IA»", lambda: then(False)),
            ("No, nunca en esta medición", "No vuelve a preguntar", lambda: (self.set_autocount("no"), then(False))),
        ], subtitle="La IA cuenta las estructuras productivas (desde el botón floral) y quedan por confirmar.")

    def auto_count(self, entry_ids: list[int]):
        """Cuenta con Gemini (en segundo plano) las fotos de esas filas: las marcas quedan
        «por confirmar» en IA+ y el conteo sale en la foto, la planilla y el Excel."""
        a = app()
        import scout_ai
        try:
            key = scout_ai.load_keys(a.scout).get("gemini")
        except Exception:  # noqa: BLE001
            key = None
        if not key:
            a.toast("Falta la clave de Gemini: AeonScout › Claves de IA (es gratis).")
            return
        db = a.db
        items = []
        for eid in entry_ids:
            e = db.query_one("SELECT id, path FROM measure_entries WHERE id=?", (eid,))
            if e and e["path"] and os.path.exists(e["path"]):
                items.append({"name": os.path.basename(e["path"]), "path": e["path"], "entry_id": e["id"]})
        if not items:
            return
        import crops
        from training_labels import ai_record, is_marked, productive_classes
        from ui import boxes
        classes = productive_classes()
        crop_name = crops.current().fruit
        state = {"done": 0}
        a.toast(f"Contando estructuras con IA en {len(items)} foto(s)…")

        def size_of(path):
            try:
                from PIL import Image
                with Image.open(path) as im:
                    return im.size
            except Exception:  # noqa: BLE001
                return 0, 0

        def on_result(it, got, err):
            if got is None:
                return
            w, h = size_of(it["path"])
            Clock.schedule_once(lambda *_: save(it, got, w, h))

        def save(it, got, w, h):
            # La foto pudo cambiar de nombre (tratamiento y descripción) mientras se contaba.
            e = db.query_one("SELECT path FROM measure_entries WHERE id=?", (it["entry_id"],))
            if not e or not e["path"]:
                return
            name = os.path.basename(e["path"])
            if is_marked(boxes.store().get(name)):          # ya contada a mano
                return
            boxes.store().put(name, ai_record(got, w, h), "IA")
            state["done"] += 1
            if self.measure["kind"] == "images" and getattr(self, "week", None):
                self.refresh()

        def work():
            import box_ai
            try:
                res = box_ai.analyze_many(key, items, classes, crop_name, db=a.scout, on_result=on_result)
            except Exception as exc:  # noqa: BLE001
                res = {"stopped": str(exc), "failed": 0}
            Clock.schedule_once(lambda *_: end(res))

        def end(res):
            msg = (f"Conteo con IA listo: {state['done']} foto(s) · revise y confirme cada una con el botón contar"
                   if state["done"] else "La IA no pudo contar las fotos")
            if res.get("stopped"):
                msg += f" · se detuvo: {res['stopped'][:80]}"
            a.toast(msg)
            if state["done"]:
                boxes.sync_now()

        a.workers.submit(work)

    def add_images(self, source: str):
        self._ask_autocount(lambda count: self._add_images(source, count))

    def _add_images(self, source: str, count: bool = False):
        a = app()
        measure, week = self.measure, self.week
        start = _dt.date.fromisoformat(week["start_date"][:10])
        from platform_utils import slugify
        code = f"{a.db.code}-" if a.db.code else ""
        base = f"{ph.photo_date(start)}-{code}{slugify(measure['name'])[:40] or 'medicion'}"

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            a.toast("Guardando foto…" if len(paths) == 1 else f"Guardando {len(paths)} fotos…")

            def work():
                ids, error = [], None
                try:
                    dest_dir = data_subdir("photos", f"T{week['season']}", "mediciones")
                    for tmp in paths:
                        path = store_photo(tmp, dest_dir, base, exact=True)
                        ids.append(a.db.add_entry(measure["id"], week["id"], path=path))
                        a.thumb(path, 160)
                        a.backup_extra(path, week["start_date"], measure["name"])
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: stored(ids, error))

            def stored(ids, error):
                if count and ids:
                    self.auto_count(ids)            # en segundo plano: no frena la cámara
                if self.measure["id"] != measure["id"] or self.week["id"] != week["id"]:
                    return
                self.refresh()
                if error:
                    a.toast(f"No se pudo guardar la foto: {error}")
                elif len(ids) == 1:
                    e = next((x for x in a.db.list_entries(measure["id"], week_id=week["id"])
                              if x["id"] == ids[0]), None)
                    if e:
                        from ui import camera_burst
                        camera_burst.defer(lambda: self.entry_dialog(e))

            a.workers.submit(work)

        if source == "camera":
            from ui import camera_burst          # varias seguidas, hasta «Listo»
            camera_burst.burst(done, base, exact=True, title=f"Medición\n{measure['name']}")
        else:
            a.media.pick_images(done)

    # ------------------------------------------------- conteos -> planilla
    def counts_to_table(self):
        """Los conteos con cajas de las fotos de esta semana a una medición de planilla (una fila
        por foto, con su tratamiento): la nueva «<medición> · conteos» o una que ya exista."""
        a = app()
        from ui import boxes
        tables = [m for m in a.db.list_measures() if m["kind"] == "table"]
        auto = f"{self.measure['name']} · conteos"

        def go(table_id):
            try:
                tid, n = a.db.counts_to_table(self.measure["id"], self.week["id"], boxes.store().data["photos"],
                                              table_id)
            except Exception as exc:  # noqa: BLE001
                a.toast(f"No se pudo: {exc}")
                return
            if not n:
                a.toast("Ninguna foto de esta semana tiene conteo: use «Contar» en cada foto primero.")
                return
            a.toast(f"{n} fila(s) en «{a.db.get_measure(tid)['name']}»")
            a.open_measure(tid, self.week["id"])
        items = [(auto, "Nueva planilla (o la ya creada)" if not any(m["name"] == auto for m in tables)
                  else "La de los conteos (se actualiza)", lambda: go(None))]
        items += [(m["name"], "Planilla existente: se agregan las columnas que falten", lambda m=m: go(m["id"]))
                  for m in tables if m["name"] != auto]
        pick_dialog("Pasar los conteos a una planilla", items,
                    subtitle="Una fila por foto de esta semana: su tratamiento, el detalle (Arriba 1, Medio 3…), cada estructura y el total. "
                             "Si la vuelve a pasar, las filas se actualizan.")

    # ------------------------------------------------- contar estructuras
    def count_entry(self, entry: dict):
        """Cajas sobre la foto (las mismas de IA+: sirven también para entrenar la IA): se
        cuentan botones, flores y frutos por estadio; el conteo sale en el Excel."""
        a = app()
        from ui import boxes
        varieties = a.db.list_varieties(include_archived=True)
        ws = a.db.workspace or {}
        # Todas las fotos de la medición en esta semana: «‹ / Siguiente ›» pasan de una a otra.
        entries = [e for e in a.db.list_entries(self.measure["id"], week_id=self.week["id"]) if e["path"]]
        photos = [{"name": os.path.basename(e["path"]), "path": e["path"], "exists": os.path.exists(e["path"]),
                   "ws": ws.get("code") or "",
                   "variety": " · ".join(x for x in (self.measure["name"], e.get("caption") or (
                       _variety_label(e["variety_id"], varieties) if e["variety_id"] else "")) if x),
                   "week": self.week["start_date"]} for e in entries]
        index = next((i for i, e in enumerate(entries) if e["id"] == entry["id"]), 0)

        def closed():
            self.refresh()
            boxes.sync_now()           # a Drive (y a la web)
        boxes.BoxEditor(photos, index, on_close=closed).open()

    # --------------------------------------------------------- definición
    def edit(self):
        self.commit_cells()
        a = app()
        m = self.measure
        form = _measure_form(m)
        from kivy.factory import Factory
        form.add_widget(Factory.GhostButton(
            icon="delete-outline", text="Eliminar medición",
            on_release=lambda *_: (dialog.dismiss(), self.delete_measure())))

        def ok(f):
            try:
                a.db.update_measure(m["id"], name=f.name.text)
                a.db.set_measure_schedule(m, f.freq["mode"], f.freq["weeks"])
            except ValueError as exc:
                a.toast(str(exc))
                return False
            self.load(m["id"], self.week["id"])

        dialog = form_dialog("Editar medición", form, ok)

    def delete_measure(self):
        a = app()
        n = len(a.db.list_entries(self.measure["id"]))

        def go():
            a.db.delete_measure(self.measure["id"])
            a.toast("Medición eliminada")
            a.back()

        confirm("Eliminar medición",
                f"Se eliminará «{self.measure['name']}» y sus {n} registro(s) de todas las semanas. "
                "Las fotos quedan en el teléfono.", [("Eliminar", go)])

    def export(self):
        """Excel: solo esta semana o toda la temporada."""
        self.commit_cells()
        mid, week = self.measure["id"], self.week
        confirm("Exportar a Excel", f"«{self.measure['name']}»\n\n• Semana: solo {ph.week_title(week)}.\n"
                "• Temporada: todas las semanas.",
                [("Semana", lambda: export_measures_xlsx([mid], week)),
                 ("Temporada", lambda: export_measures_xlsx([mid]))])
