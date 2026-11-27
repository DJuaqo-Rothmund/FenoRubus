"""
ui/plantas_ui.py
================
Pantallas del módulo Plantas (datos en plantas.py, mapas en ui/plant_maps.py):

* `PlantsHome`   — hileras del campo y los ensayos de plantas (y armar los incluidos).
* `FieldScreen`  — mapa de TODAS las hileras sobre el plano del predio: destacar ensayos,
  «Por revisar» (recorrer una a una, quitar repetidas), buscar por número, tocar un sector
  (resumen) o una hilera (su ficha corta → corregir o ver sus plantas).
* `RowEdit`      — corregir una hilera: número, subtítulo N/S (o A/B), sector, equipo,
  largo, plantas, variedad, año, nota; unir con otro tramo, repetida, no es hilera.
* `TrialScreen`  — mapa de plantas del ensayo (sur abajo), color por variedad, estado o
  medición; tocar una planta abre su tarjeta.
* `PlantScreen`  — ficha de la planta: datos, última medición e historial (eventos con
  fotos y mediciones); corregir el hoyo.
* `EventScreen`  — nuevo evento (o editar): tipo, nombre con sugerencias, severidad,
  fecha, nota y fotos.
* `FieldMode`    — modo terreno: mediciones con teclado numérico propio, planta por planta
  hacia el norte o el sur, por fecha o por temporada.

Se carga recién al entrar.
"""
from __future__ import annotations

import datetime as dt
import os
import threading

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

import plantas as P
from ui import theme
from ui.theme import c

ACCENT = "#A8184A"
GREEN = "#1E4A3A"
PREDIO = "AM"


def app():
    return MDApp.get_running_app()


def db() -> P.PlantDB:
    import crops
    from platform_utils import get_data_dir
    return P.open_db(get_data_dir(), crops.current().id)


def _date(iso: str) -> str:
    if iso and iso.startswith("T"):
        return f"Temporada {iso[1:]}"
    return "-".join(reversed((iso or "")[:10].split("-")))


def _num(text: str, cast=float):
    t = (text or "").strip()
    if cast is float and "," in t:          # «1.234,5» o «386,3»; con punto solo: decimal
        t = t.replace(".", "").replace(",", ".")
    if t == "":
        return None
    try:
        return cast(t)
    except ValueError:
        return None


KV = """
#:import c ui.theme.c
#:import theme ui.theme
<PlScreen>:
    md_bg_color: 0, 0, 0, 0
    MDBoxLayout:
        orientation: "vertical"
        TopBar:
            id: bar
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back()]]
            right_action_items: root.actions
        ScrollView:
            id: scroll
            do_scroll_x: False
            MDBoxLayout:
                id: body
                orientation: "vertical"
                adaptive_height: True
                padding: dp(14), dp(10), dp(14), dp(28)
                spacing: dp(10)

<PlMapScreen>:
    md_bg_color: 0, 0, 0, 0
    MDBoxLayout:
        orientation: "vertical"
        TopBar:
            id: bar
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back()]]
            right_action_items: root.actions
        MDBoxLayout:
            id: top
            orientation: "vertical"
            adaptive_height: True
            padding: dp(10), dp(6), dp(10), dp(4)
            spacing: dp(6)
        FloatLayout:
            id: stage
        MDBoxLayout:
            id: sheet
            orientation: "vertical"
            adaptive_height: True
            padding: dp(14), dp(10), dp(14), dp(12)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0, 0, 0, .12
                RoundedRectangle:
                    pos: self.x, self.y + dp(2)
                    size: self.size
                    radius: [dp(22), dp(22), 0, 0]
                Color:
                    rgba: c("#FFFFFF", .97)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(22), dp(22), 0, 0]

<PlCard@MDBoxLayout>:
    orientation: "vertical"
    adaptive_height: True
    padding: dp(14), dp(12), dp(14), dp(12)
    spacing: dp(6)
    canvas.before:
        Color:
            rgba: c("#FFFFFF", .9)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(18)]

<PlRow>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(root.h)
    padding: dp(4), dp(4), dp(6), dp(4)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: c("#000000", .05 if self.state == "down" else 0)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    Widget:
        size_hint: None, None
        size: dp(8), dp(root.h) - dp(16)
        pos_hint: {"center_y": .5}
        canvas:
            Color:
                rgba: root.swatch
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(3)]
    MDBoxLayout:
        orientation: "vertical"
        pos_hint: {"center_y": .5}
        adaptive_height: True
        MDLabel:
            text: root.title
            markup: True
            bold: True
            adaptive_height: True
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: c(theme.INK)
        MDLabel:
            text: root.subtitle
            markup: True
            font_style: "Caption"
            size_hint_y: None
            height: self.texture_size[1] if root.subtitle else 0
            theme_text_color: "Custom"
            text_color: c(theme.MUTED)
            opacity: 1 if root.subtitle else 0
    MDLabel:
        text: root.value
        markup: True
        bold: True
        halign: "right"
        size_hint_x: None
        width: dp(root.value_w)
        theme_text_color: "Custom"
        text_color: c(theme.INK_2)
"""


class PlScreen(MDScreen):
    title = StringProperty("Plantas")
    actions = ListProperty()

    def clear(self):
        self.ids.body.clear_widgets()
        return self.ids.body


class PlMapScreen(MDScreen):
    title = StringProperty("Plantas")
    actions = ListProperty()


class PlRow(ButtonBehavior, MDBoxLayout):
    title = StringProperty()
    subtitle = StringProperty()
    value = StringProperty()
    swatch = ListProperty([0, 0, 0, 0])
    h = NumericProperty(60)
    value_w = NumericProperty(96)


# ------------------------------------------------------------------ piezas
def card():
    return Factory.PlCard()


def lbl(text, size=14, bold=False, color=None, halign="left", **kw):
    w = MDLabel(text=text, markup=True, bold=bold, adaptive_height=True, halign=halign,
                font_size=sp(size), theme_text_color="Custom", text_color=c(color or theme.INK), **kw)
    return w


def ic(name, color=None, size=13):
    """Ícono de Material Design dentro de un texto con markup (la fuente no trae ● ★ ▲)."""
    from ui.sheet_keypad import _icon_markup
    m = _icon_markup(name, size)
    return f"[color={color}]{m}[/color]" if color else m


def section(text):
    return lbl(text.upper(), 11, True, theme.MUTED)


def pill(text, on_release=None, selected=False, width=None, color=ACCENT, height=36, font=13):
    from ui.common import PillButton
    b = PillButton(text=text, size_hint=(None, None) if width else (1, None), height=dp(height),
                   font_size=sp(font), bold=True)
    if width:
        b.width = dp(width) if width > 1 else width
    b.bg_on = c(color)
    b.selected = selected
    if on_release:
        b.bind(on_release=lambda *_: on_release())
    return b


def pills_row(items, height=36, spacing=6):
    """items: [(texto, callback, elegido, ancho dp | None, color)] en una fila con scroll horizontal."""
    from kivy.uix.scrollview import ScrollView
    row = MDBoxLayout(adaptive_width=True, size_hint_y=None, height=dp(height), spacing=dp(spacing))
    for it in items:
        text, cb, sel = it[:3]
        width = it[3] if len(it) > 3 and it[3] else max(56, len(text) * 7.6 + 26)
        col = it[4] if len(it) > 4 else ACCENT
        row.add_widget(pill(text, cb, sel, width, col, height))
    sv = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(height), bar_width=0)
    sv.add_widget(row)
    return sv


def buttons(items, height=46):
    """Botones grandes en fila: [(texto, callback, estilo «p» berry | «g» claro | «d» verde)]."""
    from ui.common import PillButton
    row = MDBoxLayout(size_hint_y=None, height=dp(height), spacing=dp(8))
    for text, cb, style in items:
        b = PillButton(text=text, size_hint=(1, None), height=dp(height), font_size=sp(14), bold=True)
        b.selected = style in ("p", "d")
        b.bg_on = c(ACCENT if style == "p" else GREEN)
        b.bind(on_release=lambda *_, cb=cb: cb())
        row.add_widget(b)
    return row


def field(hint, text="", input_filter=None, multiline=False):
    return Factory.Field(hint_text=hint, text="" if text is None else str(text), input_filter=input_filter,
                         multiline=multiline, size_hint_y=None, height=dp(56), write_tab=False)


def swatch(hex_color, alpha=1.0):
    return c(hex_color, alpha)


def _screen(cls, name):
    a = app()
    if not a.sm.has_screen(name):
        a.sm.add_widget(cls(name=name))
    return a.sm.get_screen(name)


def backup_photos():
    """Sube las fotos pendientes de los eventos (en segundo plano)."""
    a = app()

    def work():
        try:
            import crops
            d = P.PlantDrive(db(), crop=crops.current())
            if d.enabled and d.backup.available:
                d.run()
        except Exception as exc:  # noqa: BLE001 (se reintenta en la próxima sincronización)
            print("fotos de plantas:", exc)
    try:
        a.workers.submit(work)
    except Exception:  # noqa: BLE001
        threading.Thread(target=work, daemon=True).start()


# ============================================================================ inicio
class PlantsHome(PlScreen):
    def on_pre_enter(self, *_):
        self.title = "Plantas"
        self.refresh()

    def refresh(self):
        d = db()
        body = self.clear()
        rows = d.field_rows(PREDIO)
        if rows:
            k = card()
            k.add_widget(section("Hileras del campo"))
            live = [r for r in rows if not r["hidden"]]
            rev = sum(1 for r in rows if r["rev"])
            edited = sum(1 for r in rows if r["edited"])
            item = PlRow(title=f"{P.load_field(PREDIO)['name'] or 'El Amanecer'} · {len(live):,} hileras".replace(",", "."),
                         subtitle=f"Plano + planilla · [color=#C62828]{rev} por revisar[/color] · {edited} corregidas",
                         value="Mapa ›", swatch=swatch("#7CB342"))
            item.bind(on_release=lambda *_: open_field())
            k.add_widget(item)
            body.add_widget(k)
        k = card()
        k.add_widget(section("Mis ensayos"))
        trials = d.trials()
        for t in trials:
            nrows = len(d.rows_of(t["id"]))
            item = PlRow(title=t["name"], subtitle=f"{nrows} hileras · {t['plants']} plantas vivas",
                         value="Abrir ›", swatch=swatch(t["color"] or ACCENT))
            item.bind(on_release=lambda *_, tid=t["id"]: open_trial(tid))
            k.add_widget(item)
        have = {t["code"] for t in trials}
        for a in P.trial_assets():
            if a["code"] in have:
                continue
            item = PlRow(title=f"Armar «{a['name']}»",
                         subtitle=f"Desde la hoja Mapeo incluida · hileras {', '.join(a['rows'])}",
                         value="Armar", swatch=swatch("#C9CFC4"))
            item.bind(on_release=lambda *_, a=a: self._build(a))
            k.add_widget(item)
        if not trials and not P.trial_assets():
            k.add_widget(Factory.Muted(text="Todavía no hay ensayos de plantas."))
        body.add_widget(k)
        body.add_widget(Factory.Muted(
            text="Cada planta tiene su ficha: eventos (enfermedades, plagas, daños, replantes, poda) con "
                 "fotos y mediciones por fecha o por temporada. Todo se sincroniza por Drive."))

    def _build(self, a):
        try:
            tid = db().import_trial(a["path"])
        except Exception as exc:  # noqa: BLE001
            app().toast(f"No se pudo armar el ensayo: {exc}")
            return
        app().toast(f"«{a['name']}» listo")
        self.refresh()
        open_trial(tid)


# ============================================================================ hileras del campo
class FieldScreen(PlMapScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.map = None
        self.review_i = 0
        self.sel = None          # hilera elegida
        self.sector = ""

    def on_pre_enter(self, *_):
        self.title = "Hileras del campo"
        self.actions = [["magnify", lambda x: self.search()],
                        ["satellite-variant", lambda x: self.toggle_sat()]]
        if self.map is None:
            self._build_map()
        self.reload()

    def _build_map(self):
        from ui.plant_maps import RowMap
        from ui.sector_map import load_map
        from ui.mapview import default_layer
        plan = load_map(PREDIO)
        self.map = RowMap(plan, on_row=self.pick_row, on_sector=self.pick_sector,
                          size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        self.map.satellite = bool(plan.get("geo")) and default_layer() == "sat"
        self.map.highlight = bool(db().get_setting("plantas_highlight", True))
        self.map.trials_on = db().get_setting("plantas_trials_on", []) or []
        self.ids.stage.add_widget(self.map)

    def reload(self, keep_sel=True):
        d = db()
        rows = d.field_rows(PREDIO)
        trials = d.trials()
        from ui.plant_maps import TRIAL_COLOR
        self.map.trial_colors = {t["code"]: t["color"] or TRIAL_COLOR for t in trials}
        self.map.trial_names = {t["code"]: t["name"] for t in trials}
        self.map.rows = rows
        if keep_sel and self.sel:
            self.sel = next((r for r in rows if r["key"] == self.sel["key"]), None)
        self.top_controls()
        self.show_sheet()

    # ------------------------------------------------------------------ controles
    def top_controls(self):
        top = self.ids.top
        top.clear_widgets()
        rows = self.map.rows
        rev = [r for r in rows if r["rev"]]
        row = MDBoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        from kivymd.uix.selectioncontrol import MDSwitch
        sw = MDSwitch(active=self.map.highlight, size_hint=(None, None), size=(dp(52), dp(32)),
                      pos_hint={"center_y": .5})
        sw.bind(active=lambda w, v: self.set_highlight(v))
        row.add_widget(sw)
        name = lbl(f"{ic('star', ACCENT, 14)} Destacar ensayos", 13, True, GREEN)
        name.pos_hint = {"center_y": .5}
        name.size_hint_x = None
        name.width = dp(146)
        row.add_widget(name)
        from kivymd.uix.button import MDIconButton
        tune = MDIconButton(icon="tune-variant", pos_hint={"center_y": .5}, theme_icon_color="Custom",
                            icon_color=c(GREEN))
        tune.bind(on_release=lambda *_: self.pick_trials())
        row.add_widget(tune)
        row.add_widget(Widget())
        row.add_widget(pill(f"Por revisar {len(rev)}", self.toggle_review, self.map.review, 124, "#C62828"))
        top.add_widget(row)

    def set_highlight(self, on):
        self.map.highlight = on
        db().set_setting("plantas_highlight", bool(on))

    def pick_trials(self):
        """Qué ensayos destacar (se recuerda)."""
        from kivymd.uix.selectioncontrol import MDCheckbox
        from ui.common import form_dialog
        trials = db().trials()
        if not trials:
            app().toast("Todavía no hay ensayos de plantas")
            return
        on = set(self.map.trials_on or [t["code"] for t in trials])
        box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(4))
        checks = {}
        for t in trials:
            r = MDBoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
            cb = MDCheckbox(active=t["code"] in on, size_hint=(None, None), size=(dp(40), dp(40)))
            checks[t["code"]] = cb
            r.add_widget(cb)
            sw_ = Widget(size_hint=(None, None), size=(dp(10), dp(24)), pos_hint={"center_y": .5})
            from kivy.graphics import Color, RoundedRectangle
            with sw_.canvas:
                Color(*c(t["color"] or ACCENT))
                rr = RoundedRectangle(pos=sw_.pos, size=sw_.size, radius=[dp(3)])
            sw_.bind(pos=lambda w, v, rr=rr: setattr(rr, "pos", v), size=lambda w, v, rr=rr: setattr(rr, "size", v))
            r.add_widget(sw_)
            r.add_widget(lbl(f"{t['name']}  [size=12sp][color=#6E7E75]{t['plants']} plantas[/color][/size]", 14, True))
            box.add_widget(r)

        def ok(_c):
            sel = [k for k, cb in checks.items() if cb.active]
            self.map.trials_on = [] if len(sel) == len(trials) else sel
            db().set_setting("plantas_trials_on", self.map.trials_on)
            if sel and not self.map.highlight:
                self.set_highlight(True)
                self.top_controls()
        form_dialog("¿Qué ensayos destacar?", box, ok, ok_text="LISTO")

    def toggle_sat(self):
        from ui.mapview import remember_layer
        self.map.satellite = not self.map.satellite
        try:
            remember_layer("sat" if self.map.satellite else "osm")
        except Exception:  # noqa: BLE001
            pass

    def toggle_review(self):
        self.map.review = not self.map.review
        self.review_i = 0
        self.top_controls()
        if self.map.review:
            self.goto_review(0)
        else:
            self.show_sheet()

    def _review_list(self):
        rows = [r for r in self.map.rows if r["rev"]]
        return sorted(rows, key=lambda r: (r["e"], r["s"], r["x0"]))

    def goto_review(self, step):
        lst = self._review_list()
        if not lst:
            self.map.review = False
            self.top_controls()
            app().toast("¡No queda nada por revisar!")
            self.show_sheet()
            return
        self.review_i = (self.review_i + step) % len(lst)
        r = lst[self.review_i]
        self.sel = r
        self.map.focus_row(r, span=.4)
        self.show_sheet()

    # ------------------------------------------------------------------ elegir
    def pick_row(self, r):
        self.sel = r
        self.sector = ""
        if self.map.review:
            lst = self._review_list()
            keys = [x["key"] for x in lst]
            if r["key"] in keys:
                self.review_i = keys.index(r["key"])
        self.show_sheet()

    def pick_sector(self, sid):
        self.sel = None
        self.map.selected_row = ""
        self.sector = sid
        self.map.focus(sid)
        self.show_sheet()

    def search(self):
        from ui.common import form_dialog
        box = MDBoxLayout(orientation="vertical", adaptive_height=True)
        f = field("Número de hilera", input_filter="int")
        box.add_widget(f)

        def ok(_c):
            n = _num(f.text, int)
            hits = [r for r in self.map.rows if r["n"] == n and not r["hidden"]]
            if not hits:
                app().toast(f"No hay hilera {f.text} en el plano")
                return False
            hits.sort(key=lambda r: -r["y1"])
            if len(hits) == 1:
                self.show_row(hits[0])
                return
            from ui.common import pick_dialog
            pick_dialog(f"Hilera {n}: {len(hits)} tramos (de norte a sur)",
                        [(f"{r['label']} · Sector {r['s']} · Equipo {r['e']}" + (" · ensayo" if r["trial"] else ""),
                          f"{P.fmt(r['L'])} m · {r['pl'] or '—'} plantas · {r['var']} {r['anio']}",
                          lambda r=r: self.show_row(r)) for r in hits])
        form_dialog("Buscar hilera", box, ok, ok_text="BUSCAR")
        Clock.schedule_once(lambda *_: setattr(f, "focus", True), .3)

    def show_row(self, r):
        self.sel = r
        self.sector = ""
        self.map.focus_row(r)
        self.show_sheet()

    # ------------------------------------------------------------------ hoja inferior
    def show_sheet(self):
        sh = self.ids.sheet
        sh.clear_widgets()
        if self.map.review:
            lst = self._review_list()
            nav = MDBoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
            nav.add_widget(pill("‹ Anterior", lambda: self.goto_review(-1), True, 110, GREEN))
            nav.add_widget(lbl(f"[b]{min(self.review_i + 1, len(lst))}[/b] de {len(lst)}", 14, False, GREEN, "center"))
            nav.add_widget(pill("Siguiente ›", lambda: self.goto_review(1), True, 110, GREEN))
            sh.add_widget(nav)
            dups = sum(1 for r in self.map.rows if r["flag"] == 2 and r["estado"] == "")
            if dups:
                sh.add_widget(buttons([(f"Quitar las {dups} líneas repetidas del plano", self.remove_dups, "p")], 40))
        r = self.sel
        if r is not None:
            self._row_card(sh, r)
        elif self.sector:
            self._sector_card(sh, self.sector)
        elif not self.map.review:
            sh.add_widget(lbl("Toca un sector para acercarlo, o una hilera para ver su ficha. "
                              "Pellizca para acercar; doble toque acerca.", 12.5, False, theme.MUTED))

    def _row_card(self, sh, r):
        base = P.load_field(PREDIO)["by_key"][r["key"]]
        head = MDBoxLayout(adaptive_height=True, spacing=dp(8))
        tag = ""
        if r["trial"]:
            tag = f"  [size=11sp][color={ACCENT}]{ic('star', None, 11)} {self.map.trial_names.get(r['trial'], r['trial'])}[/color][/size]"
        elif r["rev"]:
            tag = "  [size=11sp][color=#C62828]por revisar[/color][/size]"
        elif r["hidden"]:
            tag = "  [size=11sp][color=#6E7E75]" + {"dup": "repetida", "no": "no es hilera",
                                                   "unida": "unida a otra"}.get(r["estado"], "") + "[/color][/size]"
        head.add_widget(lbl(f"Hilera {r['label']}{tag}", 19, True, GREEN))
        sh.add_widget(head)
        sh.add_widget(lbl(f"Sector {r['s']} · Equipo {r['e']} · {r['var'] or 'sin variedad'} {r['anio']}",
                          12.5, False, theme.INK_2))

        def val(cur, old, unit=""):
            if r["edited"] and old not in (None, "") and str(old) != str(cur):
                return f"[s][color=#9AA39C]{P.fmt(old)}[/color][/s] [b]{P.fmt(cur)}{unit}[/b]"
            return f"[b]{P.fmt(cur)}{unit}[/b]"
        info = (f"Largo {val(r['L'], base['L'], ' m')}  ·  Plantas {val(r['pl'], base['pl'])}"
                f"  ·  en el plano {P.fmt(r['L_plano'])} m")
        sh.add_widget(lbl(info, 12.5, False, theme.INK))
        if r["nota"]:
            sh.add_widget(lbl(r["nota"], 12, False, theme.MUTED))
        items = []
        if r["trial"]:
            t = next((t for t in db().trials() if t["code"] == r["trial"]), None)
            if t:
                items.append(("Ver plantas", lambda tid=t["id"]: open_trial(tid), "p"))
        items.append(("Corregir", lambda: open_row_edit(r["key"], self.map.review), "g"))
        if r["rev"]:
            items.append(("Revisada", lambda: self._mark_ok(r), "d"))
        sh.add_widget(buttons(items))

    def _mark_ok(self, r):
        db().edit_row(PREDIO, r["key"], estado="ok")
        self.reload()
        if self.map.review:
            self.goto_review(0)

    def _sector_card(self, sh, sid):
        eq, se = (int(x) for x in sid[1:].split("-S"))
        rows = [r for r in self.map.rows if r["e"] == eq and r["s"] == se and not r["hidden"]]
        km = sum(float(r["L"] or 0) for r in rows) / 1000
        pl = sum(int(r["pl"] or 0) for r in rows)
        nums = [r["n"] for r in rows if r["n"]]
        sh.add_widget(lbl(f"{sid}  ·  Sector {se} · Equipo {eq}", 18, True, GREEN))
        sh.add_widget(lbl(f"[b]{len(rows)}[/b] hileras" + (f" ({min(nums)}–{max(nums)})" if nums else "") +
                          f"  ·  [b]{P.fmt(km, 2)}[/b] km  ·  [b]{P.fmt(pl, 0)}[/b] plantas", 13, False, theme.INK))
        rev = sum(1 for r in rows if r["rev"])
        if rev:
            sh.add_widget(lbl(f"[color=#C62828]{rev} por revisar[/color]", 12, False))
        sh.add_widget(buttons([("Lista de hileras", lambda: self.sector_list(sid, rows), "d"),
                               ("Ver todo el campo", self.whole, "g")]))

    def whole(self):
        self.sector = ""
        self.map.selected = ""
        self.map.focus("")
        self.show_sheet()

    def sector_list(self, sid, rows):
        from ui.common import pick_dialog
        rows = sorted(rows, key=lambda r: (r["n"], r["y0"]))
        pick_dialog(f"{sid} · {len(rows)} hileras",
                    [(f"{r['label']}" + (" · ensayo" if r["trial"] else "") + (" · por revisar" if r["rev"] else ""),
                      f"{P.fmt(r['L'])} m · {r['pl'] or '—'} plantas · {r['var']} {r['anio']}",
                      lambda r=r: self.show_row(r)) for r in rows])

    def remove_dups(self):
        from ui.common import confirm

        def go():
            n = db().remove_duplicates(PREDIO)
            app().toast(f"{n} líneas repetidas quitadas")
            self.reload()
            if self.map.review:
                self.goto_review(0)
        confirm("Quitar repetidas", "Las líneas dibujadas dos veces en el plano quedan marcadas como "
                "repetidas (se pueden recuperar desde «Corregir»).", [("Quitar", go)])


# ============================================================================ corregir hilera
class RowEdit(PlScreen):
    key = StringProperty("")
    from_review = False

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        d = db()
        r = d.field_row(PREDIO, self.key)
        if r is None:
            app().back()
            return
        base = P.load_field(PREDIO)["by_key"][self.key]
        self.title = f"Corregir hilera {r['label']}"
        self.actions = [["backup-restore", lambda x: self.undo()]] if r["edited"] else []
        body = self.clear()
        k = card()
        k.add_widget(section("Planilla y plano"))
        if base["flag"] == 0:
            k.add_widget(lbl(f"Planilla: [b]{P.fmt(base['L'])} m · {base['pl'] or '—'} plantas[/b] · "
                             f"{base['var']} {base['anio']}  ·  Plano: [b]{P.fmt(base['L_plano'])} m[/b]", 12.5,
                             False, theme.INK_2))
        else:
            k.add_widget(lbl(f"Plano: [b]{P.fmt(base['L_plano'])} m[/b] · sector {base['s']} · equipo {base['e']} "
                             "(por su ubicación)", 12.5, False, theme.INK_2))
        if base["flag"] == 1:
            k.add_widget(lbl("[color=#C62828]Esta línea del plano no calzó con ninguna fila de la planilla.[/color]",
                             12, False))
        elif base["flag"] == 2:
            k.add_widget(lbl("[color=#C62828]Esta línea está dibujada dos veces en el plano.[/color]", 12, False))
        body.add_widget(k)

        k = card()
        k.add_widget(section("Hilera"))
        self.f_n = field("Número de hilera", r["n"], "int")
        k.add_widget(self.f_n)
        k.add_widget(lbl("Subtítulo (sector dividido en dos partes)", 12, True, theme.MUTED))
        self.ns = r["ns"] or ""
        self.ns_box = MDBoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        self._ns_pills()
        k.add_widget(self.ns_box)
        self.f_ns = field("Otro subtítulo (opcional)", self.ns if self.ns not in P.SUBTITLES else "")
        k.add_widget(self.f_ns)
        two = MDBoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        self.f_s = field("Sector", r["s"], "int")
        self.f_e = field("Equipo de riego", r["e"], "int")
        two.add_widget(self.f_s)
        two.add_widget(self.f_e)
        k.add_widget(two)
        two = MDBoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        self.f_L = field("Largo con plantas (m)", P.fmt(r["L"]) if r["L"] else "")
        self.f_pl = field("Plantas", r["pl"] or "", "int")
        two.add_widget(self.f_L)
        two.add_widget(self.f_pl)
        k.add_widget(two)
        k.add_widget(buttons([("Plantas = largo ÷ 0,7 m", self._calc, "g")], 38))
        two = MDBoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        self.f_var = field("Variedad", r["var"])
        self.f_anio = field("Año de plantación", r["anio"])
        two.add_widget(self.f_var)
        two.add_widget(self.f_anio)
        k.add_widget(two)
        self.f_nota = field("Nota", r["nota"])
        k.add_widget(self.f_nota)
        body.add_widget(k)

        nb = d.neighbors(PREDIO, self.key)
        if nb:
            k = card()
            k.add_widget(section("Otros tramos de esta columna, de sur a norte"))
            for o in nb:
                item = PlRow(title=f"{o['label']} · Sector {o['s']} · Equipo {o['e']}",
                             subtitle=f"{P.fmt(o['L_plano'])} m en el plano · {o['var']} {o['anio']}"
                                      + (" · por revisar" if o["rev"] else ""),
                             value="Unir", swatch=swatch("#C9CFC4"), h=54, value_w=60)
                item.bind(on_release=lambda *_, o=o: self.merge(o))
                k.add_widget(item)
            k.add_widget(lbl("«Unir»: la hilera queda con el largo de los dos tramos y el otro se oculta "
                             "(sirve cuando un obstáculo la corta en dos).", 11.5, False, theme.MUTED))
            body.add_widget(k)

        k = card()
        k.add_widget(section("No es una hilera aparte"))
        k.add_widget(buttons([("Es repetida", lambda: self.state("dup"), "g"),
                              ("No es hilera", lambda: self.state("no"), "g")], 42))
        body.add_widget(k)
        items = [("Guardar", self.save, "p")]
        if self.from_review:
            items.append(("Guardar y siguiente ›", lambda: self.save(nxt=True), "d"))
        body.add_widget(buttons(items))

    def _ns_pills(self):
        self.ns_box.clear_widgets()
        for v in P.SUBTITLES:
            self.ns_box.add_widget(pill(v or "—", lambda v=v: self._set_ns(v), self.ns == v, 54, GREEN))

    def _set_ns(self, v):
        self.ns = v
        self.f_ns.text = ""
        self._ns_pills()

    def _calc(self):
        L = _num(self.f_L.text)
        if L:
            self.f_pl.text = str(int(round(L / P.SPACING)))

    def save(self, nxt=False):
        ns = (self.f_ns.text.strip().upper() or self.ns)[:6]
        db().edit_row(PREDIO, self.key, n=_num(self.f_n.text, int), ns=ns, sector=_num(self.f_s.text, int),
                      equipo=_num(self.f_e.text, int), largo=_num(self.f_L.text), plantas=_num(self.f_pl.text, int),
                      variedad=self.f_var.text.strip(), anio=self.f_anio.text.strip(), nota=self.f_nota.text.strip(),
                      estado="ok")
        app().toast("Hilera corregida")
        self._back(nxt)

    def state(self, estado):
        db().edit_row(PREDIO, self.key, estado=estado)
        app().toast({"dup": "Marcada como repetida", "no": "Marcada: no es hilera"}[estado])
        self._back(self.from_review)

    def merge(self, other):
        from ui.common import confirm

        def go():
            r = db().merge_rows(PREDIO, self.key, other["key"])
            app().toast(f"Unidas: {P.fmt(r['L'])} m · {r['pl']} plantas")
            self.refresh()
        confirm("Unir tramos", f"La hilera {other['label']} ({P.fmt(other['L_plano'])} m) se une a esta: queda un "
                "solo registro con el largo de los dos.", [("Unir", go)])

    def undo(self):
        from ui.common import confirm

        def go():
            db().undo_row(PREDIO, self.key)
            app().toast("Vuelve al dato del plano y la planilla")
            self.refresh()
        confirm("Deshacer correcciones", "Se borran las correcciones de esta hilera.", [("Deshacer", go)])

    def _back(self, nxt):
        app().back()
        if app().sm.has_screen("plantas_campo"):
            fs = app().sm.get_screen("plantas_campo")
            if fs.map is not None:
                fs.reload()
                if nxt and fs.map.review:
                    Clock.schedule_once(lambda *_: fs.goto_review(0), .1)


# ============================================================================ mapa del ensayo
class TrialScreen(PlMapScreen):
    trial_id = NumericProperty(0)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.map = None
        self._built_for = None
        self.mode = "variedad"
        self.sel = None

    def on_pre_enter(self, *_):
        t = db().trial(self.trial_id)
        if not t:
            app().back()
            return
        self.title = t["name"]
        self.actions = [["magnify", lambda x: self.goto()], ["keyboard-outline", lambda x: self.terreno()],
                        ["file-export-outline", lambda x: self.export()]]
        if self._built_for != self.trial_id or self.map is None:
            self.build()
        else:
            self.reload_plants()
        self.controls()
        self.show_sheet()

    def _rows(self):
        d = db()
        out = []
        for r in d.rows_of(self.trial_id):
            out.append(dict(r, plants=d.plants_of(r["id"])))
        return out

    def build(self):
        from ui.plant_maps import PlantMap
        st = self.ids.stage
        st.clear_widgets()
        self.map = PlantMap(self._rows(), on_plant=self.pick, size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        st.add_widget(self.map)
        self._built_for = self.trial_id
        self.sel = None
        self.apply_mode()

    def reload_plants(self):
        sel = self.map.selected
        self.map.rows = self._rows()
        self.apply_mode()
        if sel:
            self.sel = db().plant(sel)
        self.map._redraw()

    def controls(self):
        top = self.ids.top
        top.clear_widgets()
        items = [("Variedad / bloque", lambda: self.set_mode("variedad"), self.mode == "variedad", None, GREEN),
                 ("Estado", lambda: self.set_mode("estado"), self.mode == "estado", None, GREEN)]
        for k, name, _u, _d in P.MEASURES:
            items.append((name.split(" (")[0], lambda k=k: self.set_mode(k), self.mode == k, None, GREEN))
        top.add_widget(pills_row(items, 34))
        if self.mode == "variedad":
            from ui.plant_maps import var_color
            seen = []
            for r in self.map.rows:
                for p in r["plants"]:
                    if p["kind"] == "planta" and p["variety"] not in seen:
                        seen.append(p["variety"])
            txt = "  ".join(f"{ic('circle', var_color(v), 11)} {P.short_var(v)}" for v in seen)
            top.add_widget(lbl(txt + f"   {ic('minus-thick', '#64B5F6', 13)} drenaje   {ic('circle-outline', '#8F978F', 11)} falla",
                               11.5, False, theme.INK_2))
        elif self.mode == "estado":
            top.add_widget(lbl("  ".join(f"{ic('circle', col, 11)} {name}" for col, name in (
                ("#43A047", "sana"), ("#8E24AA", "enfermedad"), ("#E65100", "plaga"), ("#6D4C41", "daño"),
                ("#00ACC1", "replante"), ("#37474F", "muerta"))), 11.5, False, theme.INK_2))
        else:
            vals = [v for v in self.map.values.values() if v is not None]
            name = next(n for k, n, *_ in P.MEASURES if k == self.mode)
            top.add_widget(lbl(f"{name}: " + (f"de {P.fmt(min(vals))} (claro) a {P.fmt(max(vals))} (oscuro) · "
                                              f"{len(vals)} plantas medidas" if vals else "sin mediciones todavía"),
                               11.5, False, theme.INK_2))

    def set_mode(self, m):
        self.mode = m
        self.apply_mode()
        self.controls()

    def apply_mode(self):
        d = db()
        self.map.mode = self.mode
        if self.mode == "estado":
            self.map.events = d.last_events(self.trial_id)
        elif self.mode != "variedad":
            self.map.values = d.last_values(self.trial_id, self.mode)

    def pick(self, p):
        self.sel = db().plant(p["id"])
        self.show_sheet()

    def show_sheet(self):
        sh = self.ids.sheet
        sh.clear_widgets()
        p = self.sel
        if p is None:
            sh.add_widget(lbl("Toca una planta para ver su tarjeta. Arrastra para recorrer la hilera, pellizca "
                              "para acercar.", 12.5, False, theme.MUTED))
            return
        d = db()
        if p["kind"] == "planta":
            status = {"": "Sana", "muerta": "Muerta", "replante": "Replante"}.get(p["status"], p["status"])
            ev = d.events(p["id"])
            if ev and p["status"] == "" and ev[0]["kind"] in P.NAMED_KINDS:
                status = ev[0]["name"] or P.KIND_NAME[ev[0]["kind"]]
            sh.add_widget(lbl(f"{d.plant_title(p)}   [size=12sp][color={ACCENT}]{status}[/color][/size]", 19, True, GREEN))
            sh.add_widget(lbl(f"{p['variety']} · bloque {p['bloque']} · hoyo {p['hoyo']} · {P.fmt(p['pos'], 2)} m del sur",
                              12.5, False, theme.INK_2))
            prev = d.query_one("SELECT * FROM plants WHERE row_id=? AND hoyo=?", (p["row_id"], p["hoyo"] - 1))
            if prev and prev["kind"] != "planta":
                sh.add_widget(lbl(f"Hoyo anterior ({prev['hoyo']}): {P.HOLE_KINDS.get(prev['kind'], prev['kind']).lower()}",
                                  12, False, theme.MUTED))
            sh.add_widget(buttons([("Ver ficha", lambda: open_plant(p["id"]), "g"),
                                   ("+ Evento", lambda: open_event(p["id"]), "p"),
                                   ("+ Medición", lambda: open_terreno(p["id"]), "d")]))
        else:
            sh.add_widget(lbl(f"{p.get('field_n') or p['label']} · hoyo {p['hoyo']} · "
                              f"{P.HOLE_KINDS.get(p['kind'], p['kind'])}", 18, True, GREEN))
            sh.add_widget(lbl(f"{P.fmt(p['pos'], 2)} m del sur" + (f" · {p['variety']} bloque {p['bloque']}"
                                                                  if p["variety"] else ""), 12.5, False, theme.INK_2))
            sh.add_widget(buttons([("Corregir hoyo", lambda: hole_dialog(p["id"], self.reload_and_sheet), "g"),
                                   ("+ Replante", lambda: open_event(p["id"], "replante"), "p"),
                                   ("Ficha", lambda: open_plant(p["id"]), "d")]))

    def reload_and_sheet(self):
        self.reload_plants()
        self.show_sheet()

    def goto(self):
        """Ir a una planta por hilera, variedad·bloque y número."""
        from ui.common import form_dialog
        rows = db().rows_of(self.trial_id)
        st = {"label": rows[0]["label"] if rows else ""}
        box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6))
        prow = MDBoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))

        def draw():
            prow.clear_widgets()
            for r in rows:
                prow.add_widget(pill(f"{r['field_n']} · {r['label']}", lambda r=r: (st.update(label=r["label"]), draw()),
                                     st["label"] == r["label"], 110, GREEN))
        draw()
        box.add_widget(prow)
        fv = field("Variedad (opcional: CH, W, M, L, #24…)")
        fb = field("Bloque (opcional)", "", "int")
        fn = field("Número de planta", "", "int")
        for f in (fv, fb, fn):
            box.add_widget(f)

        def ok(_c):
            n = _num(fn.text, int)
            if not n:
                return False
            var = self._var_from(fv.text)
            p = db().find_plant(self.trial_id, st["label"], var, _num(fb.text, int), n)
            if not p:
                app().toast("No encontré esa planta")
                return False
            self.map.focus_plant(p)
            self.pick(p)
        form_dialog("Ir a una planta", box, ok, ok_text="IR")

    def _var_from(self, text):
        t = (text or "").strip()
        if not t:
            return None
        names = {r["variety"] for row in self.map.rows for r in row["plants"] if r["variety"]}
        for v in names:
            if P.fold(v) == P.fold(t) or P.fold(P.short_var(v)) == P.fold(t.lstrip("#")) or P.fold(v) == P.fold("#" + t):
                return v
        return None

    def terreno(self):
        p = self.sel if self.sel and self.sel["kind"] == "planta" else None
        if p is None:
            rows = db().rows_of(self.trial_id)
            p = db().query_one("SELECT * FROM plants WHERE row_id=? AND kind='planta' ORDER BY pos LIMIT 1",
                               (rows[0]["id"],)) if rows else None
        if p:
            open_terreno(p["id"])

    def export(self):
        d = db()
        t = d.trial(self.trial_id)
        from platform_utils import data_subdir
        path = os.path.join(data_subdir("exports"), f"Plantas {t['code']} {P.today()}.csv")
        try:
            d.export_csv(self.trial_id, path)
            share = getattr(app().media, "share", None)
            if share:
                share(path, "text/csv", f"Plantas · {t['name']}")
            else:
                app().toast(f"Guardado: {path}")
        except Exception as exc:  # noqa: BLE001
            app().toast(f"No se pudo exportar: {exc}")


def hole_dialog(plant_id, on_done=None):
    """Corregir un hoyo: planta / falla / separación / eliminada, variedad, bloque, número,
    etiqueta física y nota."""
    from ui.common import form_dialog
    d = db()
    p = d.plant(plant_id)
    st = {"kind": p["kind"]}
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6))
    krow = MDBoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))

    def draw():
        krow.clear_widgets()
        for k, name in P.HOLE_KINDS.items():
            krow.add_widget(pill(name.split(" (")[0], lambda k=k: (st.update(kind=k), draw()), st["kind"] == k, None,
                                 GREEN, 34, 11.5))
    draw()
    box.add_widget(krow)
    fv = field("Variedad", p["variety"])
    two = MDBoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
    fb = field("Bloque", p["bloque"] or "", "int")
    fn = field("N.º de planta", p["num"] or "", "int")
    two.add_widget(fb)
    two.add_widget(fn)
    ft = field("Etiqueta física (si tiene)", p["tag"])
    fo = field("Nota", p["note"])
    for w in (fv, two, ft, fo):
        box.add_widget(w)
    box.add_widget(lbl("Cambiar el número de una planta no corre la numeración de las demás.", 11.5, False, theme.MUTED))

    def ok(_c):
        d.update_plant(plant_id, kind=st["kind"], variety=fv.text.strip(), bloque=_num(fb.text, int) or 0,
                       num=_num(fn.text, int) or 0, tag=ft.text.strip(), note=fo.text.strip())
        app().toast("Hoyo corregido")
        if on_done:
            on_done()
    form_dialog(f"Hoyo {p['hoyo']} · {P.fmt(p['pos'], 2)} m", box, ok)


# ============================================================================ ficha de la planta
class PlantScreen(PlScreen):
    plant_id = NumericProperty(0)

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        d = db()
        p = d.plant(self.plant_id)
        if not p:
            app().back()
            return
        self.title = d.plant_title(p)
        self.actions = [["chevron-down", lambda x: self.step(-1)], ["chevron-up", lambda x: self.step(1)]]
        body = self.clear()
        k = card()
        head = MDBoxLayout(size_hint_y=None, height=dp(78), spacing=dp(12))
        if p["kind"] == "planta":
            head.add_widget(Image(source=theme.berry_art(p["variety"]), size_hint=(None, None), size=(dp(70), dp(70)),
                                  pos_hint={"center_y": .5}))
        info = MDBoxLayout(orientation="vertical", adaptive_height=True, pos_hint={"center_y": .5}, spacing=dp(2))
        status = {"": "Sana", "muerta": "Muerta", "replante": "Replante"}.get(p["status"], p["status"])
        last = d.events(p["id"])
        if last and p["status"] == "" and last[0]["kind"] in P.NAMED_KINDS:
            status = last[0]["name"] or P.KIND_NAME[last[0]["kind"]]
        if p["kind"] != "planta":
            status = P.HOLE_KINDS.get(p["kind"], p["kind"])
        info.add_widget(lbl(f"{d.plant_title(p)}", 18, True, GREEN))
        info.add_widget(lbl(f"{p['variety'] or '—'} · bloque {p['bloque']} · hoyo {p['hoyo']}", 12.5, False, theme.INK_2))
        info.add_widget(lbl(f"[color={ACCENT}][b]{status}[/b][/color] · {P.fmt(p['pos'], 2)} m del sur · hilera "
                            f"{p['field_n']} ({p['label']}) · S{p['sector']}·E{p['equipo']}", 12, False, theme.MUTED))
        head.add_widget(info)
        k.add_widget(head)
        if p["tag"] or p["note"]:
            k.add_widget(lbl(" · ".join(x for x in (f"Etiqueta {p['tag']}" if p["tag"] else "", p["note"]) if x),
                             12.5, False, theme.INK_2))
        k.add_widget(buttons([("+ Evento", lambda: open_event(p["id"]), "p"),
                              ("+ Medición", lambda: open_terreno(p["id"]), "d"),
                              ("Corregir", lambda: hole_dialog(p["id"], self.refresh), "g")]))
        body.add_widget(k)

        ms = d.measures(p["id"])
        k = card()
        k.add_widget(section("Última medición" + (f" · {_date(ms[0]['day'])}" if ms else "")))
        if ms:
            grid = GridLayout(cols=3, size_hint_y=None, spacing=dp(6))
            grid.bind(minimum_height=grid.setter("height"))
            for key, name, unit, dec in P.MEASURES:
                v = next((m[key] for m in ms if m[key] is not None), None)
                cell = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(62))
                cell.add_widget(lbl(f"{P.fmt(v, dec)}{(' ' + unit) if unit and v is not None else ''}", 18, True,
                                    GREEN, "center"))
                cell.add_widget(lbl(name.split(" (")[0], 10.5, False, theme.MUTED, "center"))
                cell.add_widget(Widget())
                grid.add_widget(cell)
            k.add_widget(grid)
        else:
            k.add_widget(lbl("Sin mediciones todavía.", 12.5, False, theme.MUTED))
        body.add_widget(k)

        k = card()
        hist = d.history(p["id"])
        k.add_widget(section(f"Historial ({len(hist)})"))
        if not hist:
            k.add_widget(lbl("Sin eventos. Aquí queda todo lo que le pase a la planta: enfermedades, plagas, "
                             "daños, poda, replante, notas y mediciones.", 12.5, False, theme.MUTED))
        kinds = {kk: (n, ic, col) for kk, n, ic, col in P.EVENT_KINDS}
        for h in hist:
            if h["_type"] == "event":
                n, _ic, col = kinds.get(h["kind"], (h["kind"], "", "#546E7A"))
                sev = P.SEVERITY[h["severity"]] if 0 < h["severity"] < len(P.SEVERITY) else ""
                title = f"{n}" + (f": {h['name']}" if h["name"] else "")
                sub = " · ".join(x for x in (_date(h["day"]), sev, h["note"],
                                             f"{len(h['photos'])} foto(s)" if h["photos"] else "") if x)
                item = PlRow(title=title, subtitle=sub, value="", swatch=swatch(col), h=58, value_w=4)
                item.bind(on_release=lambda *_, h=h: open_event(p["id"], event_id=h["id"]))
                k.add_widget(item)
                if h["photos"]:
                    k.add_widget(self._thumbs(h["photos"]))
            else:
                vals = " · ".join(f"{name.split(' (')[0]} {P.fmt(h[key], dec)}{unit}"
                                  for key, name, unit, dec in P.MEASURES if h[key] is not None)
                item = PlRow(title=f"Medición · {_date(h['day'])}", subtitle=vals or "—", value="",
                             swatch=swatch("#1B5E20"), h=58, value_w=4)
                item.bind(on_release=lambda *_, h=h: open_terreno(p["id"], h["day"]))
                k.add_widget(item)
        body.add_widget(k)

    def _thumbs(self, photos):
        from kivy.uix.scrollview import ScrollView
        from ui.common import thumb_widget
        row = MDBoxLayout(adaptive_width=True, size_hint_y=None, height=dp(84), spacing=dp(6), padding=(dp(18), 0, 0, 0))
        for ph in photos:
            holder = ButtonImage(size_hint=(None, None), size=(dp(84), dp(84)))
            holder.add_widget(thumb_widget(ph["path"], 240))
            holder.bind(on_release=lambda *_, path=ph["path"]: _view_photo(path))
            row.add_widget(holder)
        sv = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(84), bar_width=0)
        sv.add_widget(row)
        return sv

    def step(self, direction):
        nxt = db().step(self.plant_id, direction)
        if nxt:
            self.plant_id = nxt["id"]
            self.refresh()
        else:
            app().toast("Fin de la hilera")


class ButtonImage(ButtonBehavior, BoxLayout):
    pass


class MeasureCell(ButtonBehavior, BoxLayout):
    """Una medición en el modo terreno: nombre y valor; la activa, en frambuesa."""

    def __init__(self, name, value, on, cb, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(10),
                         padding=(dp(4), 0, dp(8), 0), **kw)
        from kivy.graphics import Color, RoundedRectangle
        with self.canvas.before:
            Color(*c(ACCENT, .10) if on else (0, 0, 0, 0))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        self.bind(pos=lambda *_: setattr(self._bg, "pos", self.pos), size=lambda *_: setattr(self._bg, "size", self.size))
        bar = Widget(size_hint=(None, None), size=(dp(6), dp(30)), pos_hint={"center_y": .5})
        with bar.canvas:
            Color(*c(ACCENT if on else "#C9CFC4"))
            rr = RoundedRectangle(pos=bar.pos, size=bar.size, radius=[dp(3)])
        bar.bind(pos=lambda w, v: setattr(rr, "pos", v), size=lambda w, v: setattr(rr, "size", v))
        self.add_widget(bar)
        a = lbl(name, 15, on, ACCENT if on else theme.INK)
        a.pos_hint = {"center_y": .5}
        self.add_widget(a)
        b = lbl(value, 19, True, ACCENT if on else GREEN, "right")
        b.size_hint_x, b.width, b.pos_hint = None, dp(110), {"center_y": .5}
        self.add_widget(b)
        self.bind(on_release=lambda *_: cb())


def _view_photo(path):
    try:
        from ui.photo_viewer import open_viewer
        open_viewer([{"path": path, "title": os.path.basename(path)}], 0)
    except Exception as exc:  # noqa: BLE001
        app().toast(f"No se pudo abrir la foto: {exc}")


# ============================================================================ evento
class EventScreen(PlScreen):
    plant_id = NumericProperty(0)
    event_id = NumericProperty(0)

    def setup(self, plant_id, kind="enfermedad", event_id=0):
        self.plant_id, self.event_id = plant_id, event_id
        d = db()
        ev = d.query_one("SELECT * FROM plant_events WHERE id=?", (event_id,)) if event_id else None
        self.st = {"kind": ev["kind"] if ev else kind, "name": ev["name"] if ev else "",
                   "severity": ev["severity"] if ev else 0, "day": ev["day"] if ev else P.today(),
                   "note": ev["note"] if ev else "", "new_photos": []}

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        d = db()
        p = d.plant(self.plant_id)
        self.title = ("Editar evento" if self.event_id else "Nuevo evento") + f" · {d.plant_title(p)}"
        self.actions = [["delete-outline", lambda x: self.delete()]] if self.event_id else []
        body = self.clear()
        st = self.st
        k = card()
        k.add_widget(section("Tipo"))
        grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        for key, name, _ic, col in P.EVENT_KINDS:
            grid.add_widget(pill(name, lambda key=key: self._kind(key), st["kind"] == key, None, col, 38))
        k.add_widget(grid)
        body.add_widget(k)

        if st["kind"] in P.NAMED_KINDS:
            k = card()
            k.add_widget(section({"enfermedad": "¿Qué enfermedad?", "plaga": "¿Qué plaga?",
                                  "dano": "¿Qué lo causó?"}[st["kind"]]))
            self.f_name = field("Nombre", st["name"])
            self.f_name.bind(text=lambda w, t: self._suggest(t))
            k.add_widget(self.f_name)
            self.sugg = MDBoxLayout(size_hint_y=None, height=dp(36))
            k.add_widget(self.sugg)
            self._suggest(st["name"])
            body.add_widget(k)
            k = card()
            k.add_widget(section("Severidad"))
            row = MDBoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
            for i, s in enumerate(P.SEVERITY):
                row.add_widget(pill(s or "—", lambda i=i: self._sev(i), st["severity"] == i, None,
                                    ["#78909C", "#F9A825", "#EF6C00", "#C62828"][i], 36, 12.5))
            k.add_widget(row)
            body.add_widget(k)
        else:
            self.f_name = None

        k = card()
        k.add_widget(section("Fecha"))
        today = dt.date.today()
        opts = [(P.today(), "Hoy"), ((today - dt.timedelta(days=1)).isoformat(), "Ayer")]
        row = MDBoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        for iso, name in opts:
            row.add_widget(pill(name, lambda iso=iso: self._day(iso), st["day"] == iso, None, GREEN, 36))
        other = st["day"] not in [o[0] for o in opts]
        row.add_widget(pill(_date(st["day"]) if other else "Otra fecha…", self._pick_day, other, None, GREEN, 36))
        k.add_widget(row)
        self.f_note = field("Nota", st["note"], multiline=True)
        self.f_note.height = dp(80)
        k.add_widget(self.f_note)
        body.add_widget(k)

        k = card()
        old = d.photos(self.event_id) if self.event_id else []
        k.add_widget(section(f"Fotos ({len(old) + len(st['new_photos'])})"))
        k.add_widget(buttons([("Cámara", lambda: self._photo("camera"), "d"),
                              ("Galería", lambda: self._photo("gallery"), "g")], 42))
        paths = [ph["path"] for ph in old] + st["new_photos"]
        if paths:
            from kivy.uix.scrollview import ScrollView
            from ui.common import thumb_widget
            row = MDBoxLayout(adaptive_width=True, size_hint_y=None, height=dp(90), spacing=dp(6))
            for path in paths:
                row.add_widget(thumb_widget(path, 240))
            sv = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(90), bar_width=0)
            sv.add_widget(row)
            k.add_widget(sv)
        body.add_widget(k)
        body.add_widget(buttons([("Guardar", self.save, "p")], 50))

    def _keep(self):
        st = self.st
        if self.f_name is not None:
            st["name"] = self.f_name.text
        st["note"] = self.f_note.text

    def _kind(self, k):
        self._keep()
        self.st["kind"] = k
        self.refresh()

    def _sev(self, i):
        self._keep()
        self.st["severity"] = i
        self.refresh()

    def _day(self, iso):
        self._keep()
        self.st["day"] = iso
        self.refresh()

    def _pick_day(self):
        from ui.common import pick_dialog
        today = dt.date.today()
        items = []
        for k in range(2, 31):
            d_ = today - dt.timedelta(days=k)
            items.append((_date(d_.isoformat()), "", lambda d_=d_: self._day(d_.isoformat())))
        pick_dialog("Fecha del evento", items)

    def _suggest(self, text):
        box = getattr(self, "sugg", None)
        if box is None:
            return
        box.clear_widgets()
        names = db().suggest(self.st["kind"], text, 4)
        if any(P.fold(n) == P.fold(text) for n in names) and len(names) == 1:
            return
        box.add_widget(pills_row([(n, lambda n=n: self._use(n), False, None, "#5C6BC0") for n in names], 32))

    def _use(self, name):
        self.f_name.text = name
        self.sugg.clear_widgets()

    def _photo(self, source):
        a = app()

        def done(result, origin):
            paths = [x for x in (result if isinstance(result, list) else [result]) if x]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            from android_bridge import store_photo
            d = db()
            p = d.plant(self.plant_id)
            self._keep()
            base = d.photo_basename(p, self.st["name"] or P.KIND_NAME.get(self.st["kind"], ""))
            for x in paths:
                try:
                    self.st["new_photos"].append(store_photo(x, d.photo_dir, base, max_side=2400, exact=True))
                except Exception as exc:  # noqa: BLE001
                    a.toast(f"No se pudo guardar la foto: {exc}")
            self.refresh()

        try:
            if source == "camera":
                a.media.take_photo(done, "planta")
            else:
                a.media.pick_images(done)
        except Exception as exc:  # noqa: BLE001
            a.toast(f"No se pudo abrir: {exc}")

    def save(self, force_name=None):
        self._keep()
        d = db()
        st = self.st
        name = ""
        if st["kind"] in P.NAMED_KINDS:
            name, sugg = d.canonical(st["kind"], force_name if force_name is not None else st["name"])
            if sugg and force_name is None:
                from ui.common import confirm
                confirm("¿Es el mismo nombre?", f"Ya existe «{sugg}». ¿Usarlo en vez de «{name}»? Así el historial "
                        "queda escrito siempre igual.",
                        [(f"Usar «{sugg}»", lambda: self.save(sugg)), (f"Dejar «{name}»", lambda: self.save(name))])
                return
        if self.event_id:
            d.update_event(self.event_id, kind=st["kind"], name=name, severity=st["severity"], day=st["day"],
                           note=st["note"].strip())
            eid = self.event_id
        else:
            eid = d.add_event(self.plant_id, st["kind"], name, st["severity"], st["note"].strip(), st["day"])
        for path in st["new_photos"]:
            d.add_photo(eid, path)
        if st["new_photos"]:
            backup_photos()
        app().toast("Evento guardado")
        app().back()

    def delete(self):
        from ui.common import confirm

        def go():
            db().delete_event(self.event_id)
            app().toast("Evento eliminado")
            app().back()
        confirm("Eliminar evento", "Se borra el evento y sus fotos del teléfono (en Drive quedan).",
                [("Eliminar", go)])


# ============================================================================ modo terreno
class FieldMode(PlScreen):
    """Mediciones planta por planta con un teclado numérico propio (sin el del teléfono)."""
    plant_id = NumericProperty(0)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.day = P.today()
        self.cur = 0                     # medición activa (índice en P.MEASURES)
        self.buf = {}                    # clave -> texto escrito
        self.dirty = False
        self.pad = None

    def on_pre_enter(self, *_):
        if self.pad is None:
            self._build_pad()
        self.load()

    def on_leave(self, *_):
        self.commit()

    def _build_pad(self):
        from ui.sheet_keypad import Key, PANEL
        root = self.children[0]
        self.pad = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(232),
                             padding=(dp(10), dp(8), dp(10), dp(10)), spacing=dp(4))
        from kivy.graphics import Color, RoundedRectangle

        def bg(*_):
            self.pad.canvas.before.clear()
            with self.pad.canvas.before:
                Color(*c(PANEL))
                RoundedRectangle(pos=self.pad.pos, size=self.pad.size, radius=[dp(22), dp(22), 0, 0])
        self.pad.bind(pos=bg, size=bg)
        self.where = Label(text="", font_size=sp(12.5), color=c("#BFE3CF"), size_hint_y=None, height=dp(26),
                           halign="left", valign="middle", markup=True)
        self.where.bind(size=lambda w, s: setattr(w, "text_size", s))
        self.pad.add_widget(self.where)
        grid = GridLayout(cols=6, size_hint_y=None, height=dp(124))
        for k in "12345":
            grid.add_widget(self._key(Key(k), k))
        grid.add_widget(self._key(Key(icon="backspace-outline", kind="tool"), "back"))
        for k in "67890":
            grid.add_widget(self._key(Key(k), k))
        comma = Key(",", kind="tool")
        comma.font_size = sp(26)
        grid.add_widget(self._key(comma, ","))
        self.pad.add_widget(grid)
        tools = BoxLayout(size_hint_y=None, height=dp(62))
        for text, icon, k, kind, w in (("Sur", "chevron-down", "prev", "tool", 1),
                                       ("Evento", "alert-plus-outline", "event", "tool", 1.15),
                                       ("", "arrow-down", "down", "tool", .7),
                                       ("Norte", "chevron-up", "next", "tool", 1.05),
                                       ("Listo", "check", "done", "main", 1.1)):
            tools.add_widget(self._key(Key(text, icon=icon, kind=kind, size_hint_x=w), k))
        self.pad.add_widget(tools)
        root.add_widget(self.pad)

    def _key(self, btn, k):
        btn.bind(on_release=lambda *_: self.key(k))
        return btn

    def load(self):
        d = db()
        p = d.plant(self.plant_id)
        if not p:
            app().back()
            return
        self.title = f"Terreno · {d.plant_title(p)}"
        self.actions = [["magnify", lambda x: self.goto()]]
        m = d.measure(self.plant_id, self.day) or {}
        self.buf = {k: (P.fmt(m.get(k), dec) if m.get(k) is not None else "") for k, _n, _u, dec in P.MEASURES}
        self.buf = {k: v.replace(".", "") for k, v in self.buf.items()}
        self.dirty = False
        self.fresh = True                # la primera tecla reemplaza el valor (como en una planilla)
        self.draw()

    def draw(self):
        d = db()
        p = d.plant(self.plant_id)
        body = self.clear()
        k = card()
        k.add_widget(lbl(d.plant_title(p), 22, True, GREEN))
        k.add_widget(lbl(f"{p['variety']} · bloque {p['bloque']} · hoyo {p['hoyo']} · {P.fmt(p['pos'], 2)} m del sur"
                         + ("  ·  [color=#C62828]muerta[/color]" if p["status"] == "muerta" else ""), 12.5, False,
                         theme.INK_2))
        season = P.season_of()
        k.add_widget(pills_row([(f"Hoy ({_date(P.today())[:5]})", lambda: self.set_day(P.today()),
                                 self.day == P.today(), None, GREEN),
                                (f"Temporada {season}", lambda: self.set_day(f"T{season}"),
                                 self.day == f"T{season}", None, GREEN)] +
                               ([(_date(self.day), lambda: None, True, None, GREEN)]
                                if self.day not in (P.today(), f"T{season}") else []), 34))
        body.add_widget(k)
        k = card()
        for i, (key, name, unit, _dec) in enumerate(P.MEASURES):
            on = i == self.cur
            val = (self.buf.get(key) or ("_" if on else "—")) + (f" {unit}" if unit and self.buf.get(key) else "")
            k.add_widget(MeasureCell(name, val, on, lambda i=i: self.focus(i)))
        body.add_widget(k)
        prev = d.measures(self.plant_id)
        prev = [m for m in prev if m["day"] != self.day][:1]
        if prev:
            m = prev[0]
            body.add_widget(lbl(f"Anterior ({_date(m['day'])}): " + " · ".join(
                f"{n.split(' (')[0]} {P.fmt(m[kk], dec)}" for kk, n, _u, dec in P.MEASURES if m[kk] is not None),
                12, False, theme.MUTED))
        key, name, unit, _dec = P.MEASURES[self.cur]
        self.where.text = f"{name}{(' (' + unit + ')') if unit else ''}:  [b]{self.buf.get(key) or ''}[/b]"

    def focus(self, i):
        self.cur = i
        self.fresh = True
        self.draw()

    def set_day(self, day):
        self.commit()
        self.day = day
        self.load()

    def key(self, k):
        key = P.MEASURES[self.cur][0]
        t = self.buf.get(key, "")
        if getattr(self, "fresh", False) and (k in "0123456789" or k == ","):
            t = ""
        if k in "0123456789,back":
            self.fresh = False
        if k in "0123456789":
            t += k
        elif k == ",":
            if "," not in t:
                t = (t or "0") + ","
        elif k == "back":
            t = t[:-1]
        elif k == "down":
            self.cur = (self.cur + 1) % len(P.MEASURES)
            self.fresh = True
            self.draw()
            return
        elif k in ("next", "prev"):
            self.commit()
            nxt = db().step(self.plant_id, 1 if k == "next" else -1)
            if nxt:
                self.plant_id = nxt["id"]
                self.cur = 0
                self.load()
            else:
                app().toast("Fin de la hilera")
            return
        elif k == "event":
            self.commit()
            open_event(self.plant_id)
            return
        elif k == "done":
            self.commit()
            app().toast("Medición guardada")
            app().back()
            return
        self.buf[key] = t
        self.dirty = True
        self.draw()

    def commit(self):
        if not self.dirty:
            return
        vals = {}
        for key, *_ in P.MEASURES:
            t = (self.buf.get(key) or "").strip()
            vals[key] = float(t.replace(",", ".")) if t not in ("", ",") else None
        db().set_measure(self.plant_id, self.day, **vals)
        self.dirty = False

    def goto(self):
        from ui.common import form_dialog
        box = MDBoxLayout(orientation="vertical", adaptive_height=True)
        f = field("Número de planta (en esta hilera y tramo)", "", "int")
        box.add_widget(f)

        def ok(_c):
            n = _num(f.text, int)
            d = db()
            p = d.plant(self.plant_id)
            hit = d.query_one("SELECT * FROM plants WHERE row_id=? AND kind='planta' AND num=? AND variety=? "
                              "AND bloque=?", (p["row_id"], n, p["variety"], p["bloque"])) or \
                d.query_one("SELECT * FROM plants WHERE row_id=? AND kind='planta' AND num=? ORDER BY pos",
                            (p["row_id"], n))
            if not hit:
                app().toast("No encontré esa planta en esta hilera")
                return False
            self.commit()
            self.plant_id = hit["id"]
            self.cur = 0
            self.load()
        form_dialog("Ir a la planta", box, ok, ok_text="IR")


# ============================================================================ abrir
def open_home():
    _screen(PlantsHome, "plantas")
    app().go("plantas")


def open_field():
    _screen(FieldScreen, "plantas_campo")
    app().go("plantas_campo")


def open_row_edit(key, from_review=False):
    s = _screen(RowEdit, "plantas_hilera")
    s.key, s.from_review = key, from_review
    if app().sm.current == "plantas_hilera":
        s.refresh()
    app().go("plantas_hilera")


def open_trial(trial_id):
    s = _screen(TrialScreen, "plantas_ensayo")
    s.trial_id = trial_id
    app().go("plantas_ensayo")


def open_plant(plant_id):
    s = _screen(PlantScreen, "plantas_ficha")
    s.plant_id = plant_id
    if app().sm.current == "plantas_ficha":
        s.refresh()
    app().go("plantas_ficha")


def open_event(plant_id, kind="enfermedad", event_id=0):
    s = _screen(EventScreen, "plantas_evento")
    s.setup(plant_id, kind, event_id)
    if app().sm.current == "plantas_evento":
        s.refresh()
    app().go("plantas_evento")


def open_terreno(plant_id, day=None):
    s = _screen(FieldMode, "plantas_terreno")
    s.commit()
    s.plant_id = plant_id
    s.day = day or P.today()
    s.cur = 0
    if app().sm.current == "plantas_terreno":
        s.load()
    app().go("plantas_terreno")


Builder.load_string(KV)
