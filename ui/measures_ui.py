"""
ui/measures_ui.py
=================
Mediciones: planillas de datos y registros de imágenes.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
from kivy.clock import Clock
from kivy.metrics import dp
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
    for m in measures:
        unit = ("foto(s)" if m["kind"] == "images" else "fila(s)")
        kind = "Imágenes" if m["kind"] == "images" else "Planilla"
        items.append((m["name"], f"{kind} · {m['n']} {unit} esta semana",
                      lambda m=m: a.open_measure(m["id"], week["id"]), None,
                      lambda m=m: delete_measure_dialog(m, week)))
    footer = [("plus", "Nueva medición", new_measure_dialog)]
    if measures:
        footer.append(("microsoft-excel", "Exportar todas a Excel",
                       lambda: export_measures_xlsx([m["id"] for m in measures])))
    start = _dt.date.fromisoformat(week["start_date"][:10])
    end = a.db.week_end(week)
    span = (f"{start.day} {ph.MESES[start.month - 1][:3]} – "
            f"{end.day} {ph.MESES[end.month - 1][:3]} {end.year}")
    pick_dialog("Mediciones", items, subtitle=f"{ph.week_title(week)} · {span}", footer=footer,
                empty="Aún no hay mediciones en este ensayo.")


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


def export_measures_xlsx(measure_ids: list[int]):
    a = app()
    a.toast("Generando planilla Excel…")

    def work():
        try:
            from measures_export import export_measures
            path = export_measures(a.db, measure_ids, a.season)
            Clock.schedule_once(lambda *_: a.report_actions(
                path, "Planilla Excel (.xlsx)", "Mediciones de toda la temporada", viewable=False))
        except Exception as exc:  # noqa: BLE001
            error = exc
            Clock.schedule_once(lambda *_: a.toast(f"No se pudo exportar: {error}"))

    a.workers.submit(work)


def _measure_form(measure: dict | None = None):
    """Formulario: nombre y tipo (planilla / imágenes). Las columnas se crean en la grilla."""
    from kivy.factory import Factory
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                      padding=(0, dp(8), 0, 0))
    box.name = Factory.Field(hint_text="Nombre de la medición")
    box.add_widget(box.name)
    box.kind = measure["kind"] if measure else "table"
    if measure:
        box.name.text = measure["name"]
        return box
    row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
    hint = MDLabel(font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                   text_color=c(theme.MUTED))
    buttons = {}

    def choose(kind):
        box.kind = kind
        for k, b in buttons.items():
            on = k == kind
            b.md_bg_color = c(theme.LEAF_DARK) if on else c("#FFFFFF", 0)
            b.text_color = c("#FFFFFF") if on else c(theme.LEAF_DARK)
        hint.text = ("Una planilla como Excel: agregue filas y columnas y nombre cada columna."
                     if kind == "table" else "Fotos con descripción y, si quiere, la variedad.")

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
            mid = a.db.add_measure(form.name.text, form.kind)
        except ValueError as exc:
            a.toast(str(exc))
            return False
        a.open_measure(mid, a.week["id"])

    form_dialog("Nueva medición", _measure_form(), ok, "CREAR")


def _cell_button(text, width, bold=False, bg=None, fg=None, on_release=None):
    """Celda-botón de la grilla (encabezados, n.º de fila, variedad). Un texto en dos
    líneas va más chico y sin cortar."""
    from kivy.uix.button import Button
    two = "\n" in text
    b = Button(text=text, size_hint=(None, None), size=(width, dp(42)),
               font_size="11.5sp" if two else "13sp", line_height=.95 if two else 1,
               bold=bold, background_normal="", background_down="",
               background_color=bg or c(theme.LEAF_SOFT), color=fg or c(theme.INK),
               halign="center", valign="middle", shorten=not two, shorten_from="right")
    b.bind(size=lambda w, sz: setattr(w, "text_size", (sz[0] - dp(8), sz[1])))
    if on_release:
        b.bind(on_release=on_release)
    return b


class MeasureScreen(MDScreen):
    """Registros de UNA medición en UNA semana: fotos con descripción o filas de planilla."""

    def load(self, measure_id: int, week_id: int):
        a = app()
        self.measure = a.db.get_measure(measure_id)
        self.week = a.db.get_week(week_id)
        self.ids.bar.title = self.measure["name"]
        kind = "PLANILLA DE DATOS" if self.measure["kind"] == "table" else "REGISTRO DE IMÁGENES"
        self.ids.kicker.text = f"{kind} · {ph.week_title(self.week).upper()}"
        self.ids.columns_text.text = (
            "Toque una celda o un encabezado para escribir · los 3 puntos mueven o eliminan la columna · "
            "toque el n.º de fila para eliminarla." if self.measure["kind"] == "table"
            else "Cada foto con su descripción y, si quiere, la variedad.")
        actions = self.ids.actions
        fast_clear(actions)
        from kivy.factory import Factory
        if self.measure["kind"] == "table":
            actions.add_widget(Factory.GhostButton(icon="table-row-plus-after", text="Agregar fila",
                                                   on_release=lambda *_: self.add_row()))
            actions.add_widget(Factory.GhostButton(icon="table-column-plus-after", text="Agregar columna",
                                                   on_release=lambda *_: self.add_column()))
        else:
            actions.add_widget(Factory.GhostButton(icon="camera-outline", text="Tomar foto",
                                                   on_release=lambda *_: self.add_images("camera")))
            actions.add_widget(Factory.GhostButton(icon="image-multiple-outline", text="Desde galería",
                                                   on_release=lambda *_: self.add_images("gallery")))
        self.refresh()

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
        for e in entries:
            row = EntryRow(title=e["caption"] or "Sin descripción",
                           subtitle=_variety_label(e["variety_id"], varieties), item=e,
                           screen=self, has_thumb=True)
            row.ids.thumb_box.add_widget(thumb_widget(e["path"], 160))
            box.add_widget(row)
        if not entries:
            box.add_widget(MDLabel(text="Sin registros esta semana.", font_style="Caption",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))

    # ------------------------------------------------------ planilla (grilla)
    COL_W, NUM_W, VAR_W = dp(118), dp(40), dp(118)

    def _build_grid(self, entries):
        """Grilla editable: n.º | Variedad | columnas… · celdas = TextInput que se guardan
        al salir de ellas. Desplazamiento horizontal si hay muchas columnas."""
        from kivy.uix.gridlayout import GridLayout
        from kivy.uix.scrollview import ScrollView
        from kivy.uix.textinput import TextInput
        a = app()
        cols = list(self.measure["columns"])
        varieties = a.db.list_varieties(include_archived=True)
        self._rows = {e["id"]: dict(e["data"]) for e in entries}
        self._cells = []
        grid = GridLayout(cols=len(cols) + 2, size_hint=(None, None), spacing=dp(2), padding=dp(2))
        grid.bind(minimum_width=grid.setter("width"), minimum_height=grid.setter("height"))
        head_bg, head_fg = c(theme.LEAF_DARK), c("#FFFFFF")
        grid.add_widget(_cell_button("#", self.NUM_W, True, head_bg, head_fg))
        self.var_w = dp(150) if a.db.is_predio else self.VAR_W   # predio: variedad y año
        self._first = a.db.sheet_first()
        names = a.db.treatment_names()
        vmap = {v["id"]: v for v in varieties}
        self._heads = []
        grid.add_widget(self._head_cell(self._first["title"], self.var_w, None))
        for col in cols:
            grid.add_widget(self._head_cell(col, self.COL_W, col))
        for i, e in enumerate(entries):
            grid.add_widget(_cell_button(str(i + 1), self.NUM_W, bg=c(theme.LEAF_SOFT),
                                         on_release=lambda *_, e=e, n=i + 1: self.row_menu(e, n)))
            v = vmap.get(e["variety_id"])
            if not v:
                label = "—"
            elif a.db.is_trial:
                label = a.db.sheet_label(v, names, self._first, two_lines=True)
            else:
                label = _variety_label(e["variety_id"], varieties, two_lines=True)
            grid.add_widget(_cell_button(label, self.var_w, bg=c("#FFFFFF"), fg=c(theme.LEAF_DARK),
                                         on_release=lambda *_, e=e: self.pick_row_variety(e)))
            row_cells = []
            for col in cols:
                ti = TextInput(text=str(e["data"].get(col, "")), multiline=False, write_tab=False,
                               size_hint=(None, None), size=(self.COL_W, dp(42)), font_size="14sp",
                               padding=(dp(8), dp(11)), background_normal="", background_active="",
                               background_color=c("#FFFFFF"), foreground_color=c(theme.INK),
                               cursor_color=c(theme.LEAF_DARK))
                ti.entry_id, ti.col = e["id"], col
                ti.native_edit = False   # planilla: se escribe de corrido con el teclado de la app
                ti.bind(focus=self._cell_focus)
                ti.bind(on_text_validate=self._cell_next)
                grid.add_widget(ti)
                row_cells.append(ti)
            self._cells.append(row_cells)
        sv = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint=(1, None),
                        bar_width=dp(4), scroll_type=["bars", "content"])
        grid.bind(height=lambda g, h: setattr(sv, "height", h + dp(8)))
        sv.add_widget(grid)
        self.ids.entries.add_widget(sv)
        if not entries:
            self.ids.entries.add_widget(MDLabel(
                text="Sin filas esta semana: toque «Agregar fila».", font_style="Caption",
                adaptive_height=True, theme_text_color="Custom", text_color=c(theme.MUTED)))

    def _head_cell(self, text: str, width, col):
        """Encabezado editable en el lugar: se toca y se escribe el nombre. «⋮» = mover,
        eliminar (columnas) o qué mostrar (1.ª columna). col=None: la 1.ª columna."""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.textinput import TextInput
        from kivymd.icon_definitions import md_icons
        head_bg, head_fg = c(theme.LEAF_DARK), c("#FFFFFF")
        box = BoxLayout(size_hint=(None, None), size=(width, dp(42)))
        ti = TextInput(text=text, multiline=False, write_tab=False, font_size="13sp",
                       halign="center", padding=(dp(4), dp(12)), background_normal="",
                       background_active="", background_color=head_bg, foreground_color=head_fg,
                       cursor_color=head_fg, selection_color=c("#FFFFFF", .35))
        ti.native_edit = False        # se escribe directo sobre el encabezado
        ti.col = col
        ti.bind(focus=self._head_focus)
        ti.bind(on_text_validate=lambda t: setattr(t, "focus", False))
        dots = Button(text=md_icons["dots-vertical"], font_name="Icons", font_size="18sp",
                      size_hint_x=None, width=dp(24), background_normal="", background_down="",
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
        have = {e["variety_id"] for e in a.db.list_entries(self.measure["id"], week_id=self.week["id"])}
        units = [v for v in a.db.list_varieties()
                 if (a.db.is_parcel(v) if a.db.is_trial else not v.get("pheno_unit"))]
        n = 0
        with a.db.batch():
            for v in units:
                if v["id"] not in have:
                    a.db.add_entry(self.measure["id"], self.week["id"], v["id"], data={})
                    n += 1
        a.toast(f"{n} fila(s) agregada(s)" if n else "Ya hay una fila por cada una")
        self.refresh()

    def _cell_focus(self, ti, focused):
        if focused:
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
        """Enter: baja a la celda de la fila siguiente (misma columna)."""
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
        """Columna nueva con nombre provisorio y el cursor en su encabezado para escribirlo."""
        self.commit_cells()
        a = app()
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

    def add_images(self, source: str):
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
        self.commit_cells()
        export_measures_xlsx([self.measure["id"]])
