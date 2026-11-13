"""
ui/start_tech.py
================
Inicio de los estilos «Aurora» (oscuro) y «Cristal» (claro): las mismas funciones del inicio
de siempre (ui/screens.StartBase), dibujadas como tarjetas con datos.

* arriba: el fruto del logo (sin la órbita), el nombre del módulo, sincronizar y ajustes;
* tarjeta principal: avance del muestreo de la semana (toque: ir al muestreo);
* «Hoy falta»: lo que era el post-it, como una franja del estilo (toque: lista de pendientes);
* cuatro tarjetas: I+D, Predio, Cuaderno de campo y Rendimiento, con su dato del momento.
"""
from __future__ import annotations

import datetime as _dt

from kivy.clock import Clock
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget
from kivymd.app import MDApp

import crops
from ui import theme
from ui.screens import StartBase
from ui.theme import c


def app():
    return MDApp.get_running_app()


def dark() -> bool:
    return theme.style == "aurora"


# Colores propios de estas pantallas (lo demás sale de la paleta del estilo).
def card_bg():
    return (1, 1, 1, .065) if dark() else (1, 1, 1, 1)


def card_edge():
    return (1, 1, 1, .16) if dark() else c("#10131A", .07)


def hero_bg():
    return (1, 1, 1, .085) if dark() else c("#10131A")


def hero_fg():
    return c("#E8F1FF") if dark() else (1, 1, 1, 1)


def hero_muted():
    return c("#9DB0CC") if dark() else c("#B9C0CF")


def accent():
    return c("#3DF0B4") if dark() else c(theme.FRUIT_GLOW.get(theme.crop_id, theme.FRUIT_GLOW["frambuesa"])["BERRY"])


KV = """
#:import theme ui.theme
#:import c ui.theme.c
#:import st ui.start_tech

<TechTile>:
    opacity: root.reveal
    canvas.before:
        PushMatrix
        Translate:
            xy: 0, -root.lift
        # sombra suave (Cristal) / borde luminoso (Aurora)
        Color:
            rgba: (0, 0, 0, 0) if st.dark() else c("#10131A", .05)
        RoundedRectangle:
            pos: self.x, self.y - dp(4)
            size: self.size
            radius: [dp(24)]
        Color:
            rgba: st.card_bg() if root.state == "normal" else (c(root.accent, .16) if st.dark() else c(root.accent, .10))
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(22)]
        # brillo del color del módulo, arriba a la derecha
        Color:
            rgba: c(root.accent, .10 if st.dark() else .0)
        Ellipse:
            pos: self.x + dp(4), self.top - dp(114)
            size: dp(108), dp(108)
        Color:
            rgba: c(root.accent, .10 if st.dark() else .0)
        Ellipse:
            pos: self.x + dp(13), self.top - dp(105)
            size: dp(90), dp(90)
        Color:
            rgba: st.card_edge()
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(22))
            width: dp(1)
    canvas.after:
        PopMatrix
    # ícono ilustrado sobre su ficha clara
    Widget:
        id: chip
        size_hint: None, None
        size: dp(80), dp(80)
        pos: root.x + dp(18), root.top - dp(100)
        canvas:
            Color:
                rgba: c(root.accent, .18) if st.dark() else c(root.accent, .12)
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(24)]
            Color:
                rgba: (1, 1, 1, .92) if st.dark() else (1, 1, 1, 0)
            RoundedRectangle:
                pos: self.x + dp(3), self.y + dp(3)
                size: self.width - dp(6), self.height - dp(6)
                radius: [dp(21)]
    Image:
        source: root.source
        size_hint: None, None
        size: dp(70), dp(70)
        pos: chip.x + dp(5), chip.y + dp(5)
        fit_mode: "contain"
        mipmap: True
    Label:
        text: root.label
        bold: True
        font_size: "16sp"
        color: c(theme.INK)
        size_hint: None, None
        size: root.width - dp(28), dp(22)
        text_size: self.size
        halign: "left"
        valign: "middle"
        shorten: True
        pos: root.x + dp(14), root.y + dp(32)
    Label:
        text: root.sub
        font_size: "12sp"
        color: c(theme.MUTED)
        size_hint: None, None
        size: root.width - dp(28), dp(18)
        text_size: self.size
        halign: "left"
        valign: "middle"
        shorten: True
        pos: root.x + dp(14), root.y + dp(13)

<TechPending>:
    size_hint_y: None
    height: dp(46) if root.lines else 0
    opacity: 1 if root.lines else 0
    disabled: not root.lines
    canvas.before:
        Color:
            rgba: (c("#FFC062", .14) if st.dark() else c("#FFF4DC")) if root.lines else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(16)]
        Color:
            rgba: (c("#FFC062", .55 + .45 * root.glow) if st.dark() else c("#E0B354", .6 + .4 * root.glow)) if root.lines else (0, 0, 0, 0)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(16))
            width: dp(1.1)
        Color:
            rgba: c("#FFC062") if root.lines else (0, 0, 0, 0)
        Ellipse:
            pos: self.x + dp(14), self.center_y - dp(4)
            size: dp(8), dp(8)
    Label:
        text: root.text
        markup: True
        font_size: "13sp"
        color: c("#FFE2AE") if st.dark() else c("#6A4A12")
        text_size: self.width - dp(54), None
        halign: "left"
        valign: "middle"
        shorten: True
        padding: dp(30), 0, 0, 0
    Label:
        text: "›"
        font_size: "22sp"
        bold: True
        size_hint_x: None
        width: dp(30)
        color: c("#FFE2AE") if st.dark() else c("#6A4A12")

<TechHero>:
    size_hint_y: None
    height: dp(132)
    canvas.before:
        Color:
            rgba: st.hero_bg()
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(26)]
        # velo del color de la fruta (Cristal) en la esquina
        Color:
            rgba: c(theme.BERRY, .0 if st.dark() else .30)
        Ellipse:
            pos: self.right - dp(118), self.y + dp(14)
            size: dp(104), dp(104)
        Color:
            rgba: c(theme.BERRY, .0 if st.dark() else .22)
        Ellipse:
            pos: self.right - dp(96), self.y + dp(36)
            size: dp(60), dp(60)
        Color:
            rgba: (1, 1, 1, .18) if st.dark() else (0, 0, 0, 0)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(26))
            width: dp(1)
        # anillo de avance
        Color:
            rgba: (1, 1, 1, .12) if st.dark() else (1, 1, 1, .16)
        Line:
            circle: self.x + dp(62), self.center_y, dp(38)
            width: dp(5)
        Color:
            rgba: st.accent()
        Line:
            circle: self.x + dp(62), self.center_y, dp(38), 0, 360 * max(.004, root.progress)
            width: dp(5)
            cap: "round"
    Label:
        text: root.count
        bold: True
        font_size: "20sp"
        color: st.hero_fg()
        size_hint: None, None
        size: dp(76), dp(30)
        pos: root.x + dp(24), root.center_y - dp(15)
    Label:
        text: root.kicker
        bold: True
        font_size: "10.5sp"
        color: st.accent()
        size_hint: None, None
        size: root.width - dp(132), dp(16)
        text_size: self.size
        halign: "left"
        valign: "middle"
        shorten: True
        pos: root.x + dp(116), root.center_y + dp(26)
    Label:
        text: root.title
        bold: True
        font_size: "17sp"
        color: st.hero_fg()
        size_hint: None, None
        size: root.width - dp(132), dp(44)
        text_size: self.size
        halign: "left"
        valign: "middle"
        max_lines: 2
        shorten: True
        shorten_from: "right"
        pos: root.x + dp(116), root.center_y - dp(20)
    Label:
        text: root.sub
        font_size: "12sp"
        color: st.hero_muted()
        size_hint: None, None
        size: root.width - dp(132), dp(18)
        text_size: self.size
        halign: "left"
        valign: "middle"
        shorten: True
        pos: root.x + dp(116), root.center_y - dp(42)

<TechRound@MDIconButton>:
    icon_size: "22sp"
    theme_icon_color: "Custom"
    icon_color: c(theme.INK)
    size_hint: None, None
    size: dp(42), dp(42)
    pos_hint: {"center_y": .5}
    canvas.before:
        Color:
            rgba: (1, 1, 1, .08) if st.dark() else (1, 1, 1, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)] if st.dark() else [dp(21)]
        Color:
            rgba: st.card_edge()
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(14) if st.dark() else dp(21))
            width: dp(1)

<StartTech>:
    md_bg_color: 0, 0, 0, 0
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        Rectangle:
            source: theme.START_BG
            pos: self.pos
            size: self.size
    MDBoxLayout:
        orientation: "vertical"
        padding: dp(20), dp(14), dp(20), dp(18)
        spacing: dp(10)
        BoxLayout:
            size_hint_y: None
            height: dp(54)
            spacing: dp(8)
            Image:
                id: logo
                source: theme.FRUIT_SIMPLE
                fit_mode: "contain"
                mipmap: True
                size_hint: None, None
                size: dp(48), dp(48)
                height: dp(48)
                pos_hint: {"center_y": .5}
            Label:
                text: root.brand
                markup: True
                bold: True
                font_size: "24sp"
                color: c(theme.INK)
                text_size: self.size
                halign: "left"
                valign: "middle"
                shorten: True
            TechRound:
                id: syncbtn
                icon: "sync"
                on_release: root.sync_now()
                canvas.before:
                    PushMatrix
                    Rotate:
                        angle: root.sync_angle
                        origin: self.center
                canvas.after:
                    PopMatrix
            TechRound:
                id: gear
                icon: "cog-outline"
                on_release: app.open_settings(general_only=True)
        MDLabel:
            id: greeting
            font_style: "Body2"
            adaptive_height: True
            theme_text_color: "Custom"
            text_color: c(theme.MUTED)
            on_touch_down: root.ask_name() if self.collide_point(*args[1].pos) else None
        TechHero:
            id: hero
            on_release: root.open_sampling()
        AnchorLayout:
            size_hint_y: None
            height: dp(26)
            anchor_x: "left"
            BoxLayout:
                id: pills
                size_hint: None, None
                height: dp(24)
                spacing: dp(6)
        TechPending:
            id: postit
            on_release: root.open_tasks()
        GridLayout:
            cols: 2
            spacing: dp(12)
            TechTile:
                id: ic_id
                source: theme.START_ID
                label: "I+D"
                accent: "#FF2D82"
                on_release: root.open_profile("id")
            TechTile:
                id: ic_predio
                source: theme.START_PREDIO
                label: "Predio"
                accent: "#19C98A"
                on_release: root.open_profile("predio")
            TechTile:
                id: ic_nb
                source: theme.START_NOTEBOOK
                label: "Cuaderno de campo"
                accent: "#F2A72E"
                on_release: app.open_notebook()
            TechTile:
                id: ic_yield
                source: theme.START_YIELD
                label: "Rendimiento"
                accent: "#3C78FF"
                on_release: app.open_yield()
        GhostButton:
            id: crops_btn
            icon: "home-variant-outline"
            text: "AeonCrop · todos los cultivos"
            height: dp(46)
            on_release: app.open_crops()
"""


class TechTile(ButtonBehavior, FloatLayout):
    """Tarjeta de un módulo: su ícono ilustrado, el nombre y un dato del momento."""
    source = StringProperty()
    label = StringProperty()
    sub = StringProperty("")
    accent = StringProperty("#FF2D82")
    lift = NumericProperty(0)       # animación de entrada
    reveal = NumericProperty(1)
    bob = NumericProperty(0)        # (los íconos flotantes del inicio de siempre; aquí quietos)
    pulse = NumericProperty(1)


class TechHero(ButtonBehavior, FloatLayout):
    kicker = StringProperty("")
    title = StringProperty("")
    sub = StringProperty("")
    count = StringProperty("—")
    progress = NumericProperty(0)


class TechPending(ButtonBehavior, BoxLayout):
    """Lo que falta hoy (el post-it de los otros estilos): una franja que se toca."""
    lines = ListProperty([])
    text = StringProperty("")
    glow = NumericProperty(0)

    def on_lines(self, *_):
        self.text = "[b]HOY FALTA[/b]   " + "  ·  ".join(self.lines)

    def wobble(self):
        """Destello al aparecer (el balanceo del post-it)."""
        from kivy.animation import Animation
        Animation.cancel_all(self, "glow")
        self.glow = 1
        Animation(glow=0, d=1.1, t="out_quad").start(self)


class StartTech(StartBase):
    brand = StringProperty("")
    FLOAT = ()                      # sin flotación: tarjetas quietas

    def __init__(self, **kw):
        _load()
        super().__init__(**kw)
        name = crops.current().app
        head, tail = (name[:5], name[5:]) if name.startswith("Pheno") else (name, "")
        col = theme.FRUIT_GLOW[theme.crop_id]["BERRY"] if dark() else theme.BERRY
        self.brand = f"{head}[color={col}]{tail}[/color]"

    # La animación de entrada del inicio de siempre agranda el logo: aquí solo aparece.
    def _play_intro(self):
        from kivy.animation import Animation
        Animation(opacity=1, d=.3).start(self.ids.logo)
        for i, w in enumerate((self.ids.ic_id, self.ids.ic_predio, self.ids.ic_nb, self.ids.ic_yield)):
            (Animation(d=.06 + .07 * i) + Animation(reveal=1, lift=0, d=.32, t="out_cubic")).start(w)

    def _show_week(self, info):
        hero = self.ids.hero
        if not info or not info.get("ws"):
            hero.kicker, hero.title, hero.sub, hero.count, hero.progress = "MUESTREO", "Elija un ensayo o predio", "", "—", 0
            return
        prof = "PREDIO" if info["ws"].get("profile") == "predio" else "I+D"
        hero.kicker = f"SEMANA {info['week']} · {prof}"
        hero.title = info["ws"].get("name") or info["title"]
        total, done = info["total"], info["done"]
        if not total:
            hero.sub, hero.count, hero.progress = "Sin registros que muestrear aún", "0", 0
            return
        left = total - done
        hero.sub = "Muestreo de la semana completo" if left <= 0 else f"Faltan {left} {info['what']} · toque para muestrear"
        hero.count = f"{done}/{total}"
        hero.progress = done / total

    def refresh(self):
        super().refresh()
        a = app()
        ids = self.ids

        def n(count, one, many):
            return f"{count} {one if count == 1 else many}"
        try:
            ids.ic_id.sub = n(len(a.workspaces.list("id")), "ensayo", "ensayos")
            ids.ic_predio.sub = n(len(a.workspaces.list("predio")), "predio", "predios")
        except Exception:  # noqa: BLE001 - nunca bloquear el inicio
            pass
        try:
            from ui.pending import note_written
            ids.ic_nb.sub = "Hoy: página escrita" if note_written(a.db, _dt.date.today().isoformat()) else "Hoy sin escribir"
        except Exception:  # noqa: BLE001
            ids.ic_nb.sub = ""
        try:
            k = a.yields.query_one("SELECT COUNT(*) AS n FROM yield_sets")["n"]
            ids.ic_yield.sub = n(k, "estimación", "estimaciones") if k else "Sin estimaciones aún"
        except Exception:  # noqa: BLE001
            ids.ic_yield.sub = ""

    def open_sampling(self):
        a = app()
        if getattr(a, "workspace", None) is None:
            a.open_workspaces("id")
            return
        a.enter_home()

    def open_tasks(self):
        from ui.pending import today_tasks
        TechTasks(today_tasks(), on_close=self._postit).open()


# --------------------------------------------------------------------------- pendientes
class _Row(ButtonBehavior, BoxLayout):
    pass


class TechTasks(ModalView):
    """Los pendientes de hoy (la hoja del post-it) como una tarjeta del estilo."""

    def __init__(self, tasks: list[dict], on_close=None, **kw):
        super().__init__(size_hint=(.9, None), auto_dismiss=True, background_color=(0, 0, 0, 0),
                         overlay_color=(0, 0, 0, .55), **kw)
        from ui.pending import WEEKDAYS
        step = dp(60)
        self.height = dp(84) + step * max(1, len(tasks)) + dp(16)
        box = BoxLayout(orientation="vertical", padding=(dp(18), dp(16), dp(14), dp(12)), spacing=dp(4))
        bg = c("#141B2B") if dark() else (1, 1, 1, 1)
        ink = c(theme.INK)
        with box.canvas.before:
            Color(*bg)
            self._bg = RoundedRectangle(radius=[dp(24)])
            Color(*card_edge())
            self._edge = Line(width=dp(1))
        box.bind(pos=self._place, size=self._place)
        d = _dt.date.today()
        left = sum(1 for t in tasks if not t["done"])
        head = Label(text=f"[b]Hoy · {WEEKDAYS[d.weekday()]} {d.day}[/b]\n[size={int(sp(12))}][color={_hex(theme.MUTED)}]"
                          f"{'Todo al día' if not left else str(left) + ' pendiente' + ('s' if left != 1 else '')}[/color][/size]",
                     markup=True, font_size=sp(19), color=ink, size_hint_y=None, height=dp(52), halign="left",
                     valign="middle")
        head.bind(size=lambda w, s: setattr(w, "text_size", s))
        box.add_widget(head)
        for t in tasks:
            row = BoxLayout(size_hint_y=None, height=step - dp(4), spacing=dp(10))
            row.add_widget(_Dot(t["done"]))
            txt = Label(text=f"[b]{t['title']}[/b]\n[size={int(sp(11.5))}][color={_hex(theme.MUTED)}]{t['detail']}[/color][/size]",
                        markup=True, font_size=sp(14.5), color=c(theme.MUTED) if t["done"] else ink, halign="left",
                        valign="middle")
            txt.bind(size=lambda w, s: setattr(w, "text_size", s))
            row.add_widget(txt)
            if not t["done"]:
                btn = _Pill(text=t["action"])
                btn.bind(on_release=lambda _w, t=t: self._run(t))
                row.add_widget(btn)
            box.add_widget(row)
        if not tasks:
            box.add_widget(Label(text="¡Todo al día por hoy!", color=ink, font_size=sp(15)))
        self.add_widget(box)
        self.bind(on_dismiss=lambda *_: on_close and on_close())

    def _place(self, w, *_):
        self._bg.pos, self._bg.size = w.pos, w.size
        self._edge.rounded_rectangle = (w.x, w.y, w.width, w.height, dp(24))

    def _run(self, task):
        self.dismiss()
        Clock.schedule_once(lambda *_: task["run"](), .15)


def _hex(color: str) -> str:
    return color[:7]


class _Dot(Widget):
    def __init__(self, done: bool, **kw):
        super().__init__(size_hint=(None, None), size=(dp(26), dp(26)), pos_hint={"center_y": .5}, **kw)
        self.done = done
        self.bind(pos=self._draw)

    def _draw(self, *_):
        self.canvas.clear()
        with self.canvas:
            if self.done:
                Color(*accent())
                RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(13)])
                Color(*(c("#0A0E18") if dark() else (1, 1, 1, 1)))
                Line(points=[self.x + dp(7), self.y + dp(13), self.x + dp(11.5), self.y + dp(8.5),
                             self.x + dp(19), self.y + dp(17.5)], width=dp(1.8), cap="round", joint="round")
            else:
                Color(*c("#FFC062"))
                Line(circle=(self.center_x, self.center_y, dp(11)), width=dp(1.6))


class _Pill(ButtonBehavior, Label):
    def __init__(self, **kw):
        super().__init__(bold=True, font_size=sp(13), size_hint=(None, None), height=dp(34),
                         pos_hint={"center_y": .5}, color=c("#0A0E18") if dark() else (1, 1, 1, 1), **kw)
        self.texture_update()
        self.width = self.texture_size[0] + dp(28)
        self.bind(pos=self._draw, state=self._draw)

    def _draw(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            col = accent() if dark() else c("#10131A")
            Color(col[0], col[1], col[2], .75 if self.state == "down" else 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(17)])


_loaded = False


def _load():
    global _loaded
    if not _loaded:
        Builder.load_string(KV)
        _loaded = True
