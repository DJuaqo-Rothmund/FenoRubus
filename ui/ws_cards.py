"""
ui/ws_cards.py
==============
Ensayos y predios en tarjetas modernas (idea A + D):

* ContinueCard: arriba, grande, el ensayo en uso con la semana y su avance («Abrir muestreo»).
* WorkspaceCard: los demás en tarjetas con degradado, el código en un cuadrado redondeado y
  abajo cuántas parcelas/variedades/sectores tiene y la última semana con registros.

Todo se dibuja en el canvas (liviano) con colores propios: se ven iguales en todos los estilos.
"""
from __future__ import annotations

import datetime as _dt

from kivy.clock import Clock
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from ui.theme import c

# Degradados (arriba-izquierda -> abajo-derecha). Ensayos parten en verde; predios en frambuesa.
PALETTE = [("#3E8A63", "#1E4A3A"), ("#C2365F", "#7E1238"), ("#4B7F8C", "#23485A"),
           ("#8A7A3E", "#5A4A1E"), ("#6A5AA8", "#3E2F7E"), ("#B8642E", "#7A3A12")]

_TEX: dict = {}


def gradient(c1: str, c2: str) -> Texture:
    """Textura 2×2 con interpolación: degradado diagonal suave al estirarla."""
    key = (c1, c2)
    if key in _TEX:
        return _TEX[key]
    a, b = [int(x * 255) for x in c(c1)[:3]], [int(x * 255) for x in c(c2)[:3]]
    mid = [(x + y) // 2 for x, y in zip(a, b)]
    # filas de abajo hacia arriba: (abajo-izq, abajo-der), (arriba-izq, arriba-der)
    px = bytes(mid + [255] + b + [255] + a + [255] + mid + [255])
    tex = Texture.create(size=(2, 2), colorfmt="rgba")
    tex.blit_buffer(px, colorfmt="rgba", bufferfmt="ubyte")
    tex.mag_filter = tex.min_filter = "linear"
    tex.uvpos, tex.uvsize = (.25, .25), (.5, .5)
    _TEX[key] = tex
    return tex


def colors_for(index: int, profile: str) -> tuple[str, str]:
    return PALETTE[(index + (1 if profile == "predio" else 0)) % len(PALETTE)]


def _lab(text="", size=13, bold=False, alpha=1.0, lines=1, color=None):
    lb = Label(text=text, font_size=sp(size), bold=bold, color=color or (1, 1, 1, alpha), halign="left",
               valign="middle", max_lines=lines, shorten=lines == 1, shorten_from="right", size_hint_y=None,
               height=0)
    lb.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
            texture_size=lambda w, t: setattr(w, "height", t[1]))
    return lb


class _Card(ButtonBehavior, BoxLayout):
    """Base: degradado, sombra suave, brillo arriba y borde blanco si es el ensayo en uso."""
    c1 = StringProperty("#3E8A63")
    c2 = StringProperty("#1E4A3A")
    current = BooleanProperty(False)
    RADIUS = 26

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, state=self._draw, current=self._draw,
                  c1=self._draw, c2=self._draw)

    def _draw(self, *_):
        r = dp(self.RADIUS)
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0, 0, 0, .10)                                   # sombra
            RoundedRectangle(pos=(self.x + dp(1), self.y - dp(3)), size=self.size, radius=[r])
            Color(1, 1, 1, .86 if self.state == "down" else 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[r], texture=gradient(self.c1, self.c2))
            if self.current:
                Color(1, 1, 1, .95)
                Line(rounded_rectangle=(self.x + dp(1.5), self.y + dp(1.5), self.width - dp(3),
                                        self.height - dp(3), r - dp(1)), width=dp(1.6))


class _Square(Label):
    """Código del ensayo en un cuadrado redondeado translúcido."""

    def __init__(self, min_w=46, **kw):
        self.min_w = dp(min_w)
        super().__init__(size_hint=(None, None), size=(dp(46), dp(46)), bold=True, font_size=sp(14),
                         color=(1, 1, 1, 1), halign="center", valign="middle", **kw)
        self.bind(pos=self._d, size=self._d, text=self._fit)

    def _fit(self, *_):
        self.font_size = sp(14 if len(self.text) <= 3 else 12)
        self.texture_update()
        self.width = max(self.min_w, self.texture_size[0] + dp(18))

    def _d(self, *_):
        self.text_size = self.size
        self.canvas.before.clear()
        with self.canvas.before:
            Color(1, 1, 1, .22)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(15)])


class WorkspaceCard(_Card):
    """Idea A: tarjeta con degradado. Toque: abrir · ⋮: renombrar, archivar…"""
    title = StringProperty()
    subtitle = StringProperty()
    code = StringProperty()
    profile = StringProperty("id")
    stats = StringProperty("")
    ws = ObjectProperty(None, allownone=True)
    screen = ObjectProperty(None, allownone=True)

    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(182), padding=(dp(16), dp(14), dp(6), dp(12)),
                         spacing=dp(2), **kw)
        top = BoxLayout(size_hint_y=None, height=dp(46))
        self.sq = _Square()
        top.add_widget(self.sq)
        top.add_widget(Widget())
        from kivymd.uix.button import MDIconButton
        self.dots = MDIconButton(icon="dots-vertical", theme_icon_color="Custom", icon_color=(1, 1, 1, .9),
                                 pos_hint={"top": 1.1})
        self.dots.bind(on_release=lambda *_: self.screen.item_menu(self.ws) if self.screen else None)
        top.add_widget(self.dots)
        self.add_widget(top)
        self.add_widget(Widget(size_hint_y=None, height=dp(8)))
        self.t = _lab(size=15, bold=True, lines=2)
        self.s = _lab(size=11.5, alpha=.86)
        self.st = _lab(size=11, alpha=.95, lines=2)
        for w in (self.t, self.s, Widget(), self.st):
            if isinstance(w, Label):
                w.padding = (0, 0)
            self.add_widget(w)
        self.t.size_hint_x = self.s.size_hint_x = self.st.size_hint_x = 1
        self.bind(title=self._text, subtitle=self._text, code=self._text, stats=self._text)
        self._text()

    def _text(self, *_):
        self.sq.text = self.code
        self.t.text = self.title
        self.s.text = self.subtitle
        self.st.text = self.stats


class WorkspaceRowCard(_Card):
    """Vista de lista con el mismo estilo: una fila ancha con degradado (sin «Continuar»)."""
    RADIUS = 22
    title = StringProperty()
    subtitle = StringProperty()
    code = StringProperty()
    profile = StringProperty("id")
    ws = ObjectProperty(None, allownone=True)
    screen = ObjectProperty(None, allownone=True)

    def __init__(self, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(90),
                         padding=(dp(16), dp(10), dp(4), dp(10)), spacing=dp(14), **kw)
        self.sq = _Square(min_w=56, pos_hint={"center_y": .5})
        self.add_widget(self.sq)
        col = BoxLayout(orientation="vertical", spacing=dp(3))
        col.add_widget(Widget())
        self.t = _lab(size=15.5, bold=True)
        self.s = _lab(size=11.5, alpha=.88, lines=2)
        col.add_widget(self.t)
        col.add_widget(self.s)
        col.add_widget(Widget())
        self.add_widget(col)
        from kivymd.uix.button import MDIconButton
        self.dots = MDIconButton(icon="dots-vertical", theme_icon_color="Custom", icon_color=(1, 1, 1, .9),
                                 pos_hint={"center_y": .5})
        self.dots.bind(on_release=lambda *_: self.screen.item_menu(self.ws) if self.screen else None)
        self.add_widget(self.dots)
        self.bind(title=self._text, subtitle=self._text, code=self._text)
        self._text()

    def _text(self, *_):
        self.sq.text = self.code
        self.t.text = self.title
        self.s.text = self.subtitle


class ContinueCard(_Card):
    """Idea D: «Continuar» con el ensayo en uso (semana, avance y botón)."""
    RADIUS = 28
    ws = ObjectProperty(None, allownone=True)

    def __init__(self, ws: dict, **kw):
        super().__init__(size_hint_y=None, height=dp(178), padding=(dp(18), dp(16), dp(18), dp(14)),
                         spacing=dp(3), **kw)
        self.ws = ws
        self.k = _lab("CONTINUAR", size=11, bold=True, alpha=.8)
        self.t = _lab(ws["name"], size=19, bold=True, lines=2)
        self.s = _lab(ws["code"], size=12, alpha=.9)
        for w in (self.k, self.t, self.s):
            self.add_widget(w)
        self.add_widget(Widget())
        self.bar = Widget(size_hint_y=None, height=dp(6))
        self.bar.bind(pos=self._bar, size=self._bar)
        self.add_widget(self.bar)
        self.add_widget(Widget(size_hint_y=None, height=dp(10)))
        row = BoxLayout(size_hint_y=None, height=dp(36))
        self.btn = Label(text="Abrir sectores  ›" if ws.get("profile") == "predio" else "Abrir muestreo  ›", bold=True, font_size=sp(13), size_hint=(None, None),
                         size=(dp(156), dp(36)), color=c("#1E4A3A"))
        self.btn.bind(pos=self._btn, size=self._btn)
        row.add_widget(self.btn)
        row.add_widget(Widget())
        self.add_widget(row)
        self.frac = 0.0

    def set_progress(self, text: str, frac: float):
        self.s.text = text
        self.frac = max(0.0, min(1.0, frac))
        self._bar()

    def _btn(self, *_):
        self.btn.canvas.before.clear()
        with self.btn.canvas.before:
            Color(1, 1, 1, 1)
            RoundedRectangle(pos=self.btn.pos, size=self.btn.size, radius=[self.btn.height / 2])

    def _bar(self, *_):
        b = self.bar
        b.canvas.clear()
        with b.canvas:
            Color(1, 1, 1, .25)
            RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(3)])
            if self.frac > 0:
                Color(1, 1, 1, 1)
                RoundedRectangle(pos=b.pos, size=(max(dp(6), b.width * self.frac), b.height), radius=[dp(3)])


def week_progress(db, profile: str) -> tuple[str, float]:
    """«Semana 47 · 4 de 7 parcelas» y la fracción hecha (estado BBCH registrado esta semana)."""
    today = _dt.date.today().isoformat()
    w = db.query_one("SELECT * FROM sampling_weeks WHERE start_date <= ? ORDER BY start_date DESC LIMIT 1", (today,))
    trial = db.is_trial
    units = [v for v in db.list_varieties() if (db.is_parcel(v) if trial else not v.get("pheno_unit"))]
    one, many = ("parcela", "parcelas") if trial else (("sector", "sectores") if profile == "predio"
                                                         else ("variedad", "variedades"))
    if not w or not units:
        return f"{len(units)} {one if len(units) == 1 else many}", 0.0
    ids = {v["id"] for v in units}
    done = {r["variety_id"] for r in db.query(
        "SELECT DISTINCT variety_id FROM observations WHERE week_id=? AND bbch_code IS NOT NULL", (w["id"],))
        if r["variety_id"] in ids}
    import phenology as ph
    title = ph.week_title(w).split(",")[0]
    return f"{title} · {len(done)} de {len(units)} {many} con estado", len(done) / len(units)


def later(fn):
    Clock.schedule_once(lambda *_: fn(), 0)
