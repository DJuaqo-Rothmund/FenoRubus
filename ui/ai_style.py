"""
ui/ai_style.py
==============
Todo lo que es IA en la app comparte una identidad: púrpura, violeta y azul índigo, con brillo
neón y un toque estelar (puntos de luz que titilan). Así se distingue de un vistazo qué hizo o
propone la IA (por confirmar) y qué registró la persona.

* AIButton  — acción principal de IA: píldora con degradado violeta → índigo y aura que respira.
* AIGhost   — acción secundaria de IA: borde neón fino y texto violeta.
* AIChip    — alternativa propuesta (p. ej. «BBCH 69 · 19 %»).
* AIBar     — confianza de la IA (degradado violeta → índigo).
* Stars     — capa de estrellas que titilan (dentro de las tarjetas de IA).
* review_markup() — «IA · falta confirmar» con el mismo color en todas las pantallas.

Todo en el canvas (liviano) y con colores para estilos claros y oscuros.
"""
from __future__ import annotations

import math
import random

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from ui import theme
from ui.theme import c

# Paleta IA (igual en todos los estilos; el texto cambia según claro/oscuro).
VIOLET = "#7C4DFF"
PURPLE = "#B14DFF"
INDIGO = "#3D5AFE"
MAGENTA = "#E040FB"
SOFT = "#EEE6FF"          # fondo lavanda (celdas o datos puestos por la IA, claro)
SOFT_DARK = "#2E2363"     # lo mismo en estilos oscuros


def ink() -> str:
    """Texto violeta legible sobre el fondo del estilo."""
    return "#D7C9FF" if theme.is_dark() else "#4B2BB3"


def soft() -> str:
    return SOFT_DARK if theme.is_dark() else SOFT


def review_markup(text: str = "IA · falta confirmar") -> str:
    return f"[color={'B9A2FF' if theme.is_dark() else '6A3DE8'}][b]{text}[/b][/color]"


def _grad(c1: str, c2: str):
    from ui.ws_cards import gradient
    return gradient(c1, c2)


class _Pulse:
    """Mezcla: `pulse` 0..1 que respira mientras el widget está en pantalla."""
    pulse = NumericProperty(0)

    def _start_pulse(self):
        self._pev = None
        self.bind(parent=self._watch_pulse)

    def _watch_pulse(self, *_):
        if self.parent is not None and self._pev is None:
            self._t0 = random.random() * 6
            self._pev = Clock.schedule_interval(self._beat, 1 / 24)
        elif self.parent is None and self._pev is not None:
            self._pev.cancel()
            self._pev = None

    def _beat(self, dt):
        if self.get_root_window() is None:
            return
        self._t0 += dt
        self.pulse = .5 + .5 * math.sin(self._t0 * 2.2)


class AIButton(_Pulse, ButtonBehavior, Label):
    """Acción principal de IA (degradado violeta → índigo, aura neón y un destello ✦)."""
    icon = StringProperty("creation")

    def __init__(self, text="", icon="creation", on_press_cb=None, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(46))
        super().__init__(text=text, bold=True, font_size=sp(14.5), color=(1, 1, 1, 1), halign="center",
                         valign="middle", shorten=True, shorten_from="right", **kw)
        self.icon = icon
        if on_press_cb:
            self.bind(on_release=lambda *_: on_press_cb())
        self.bind(pos=self._draw, size=self._draw, state=self._draw, pulse=self._draw, disabled=self._draw,
                  text=self._pad, icon=self._pad)
        self._start_pulse()
        self._pad()

    def _pad(self, *_):
        from kivymd.icon_definitions import md_icons
        g = md_icons.get(self.icon, "")
        self.markup = True
        from kivymd import fonts_path
        import os
        font = os.path.join(fonts_path, "materialdesignicons-webfont.ttf")
        base = self.text.split("[/font]  ", 1)[-1]
        self.text = f"[font={font}][size={int(sp(18))}]{g}[/size][/font]  {base}" if g else base

    def _draw(self, *_):
        self.text_size = (self.width - dp(24), None)
        r = self.height / 2
        self.canvas.before.clear()
        with self.canvas.before:
            if not self.disabled:                                    # aura neón que respira
                for k, a in ((dp(7), .07), (dp(4), .12), (dp(2), .2)):
                    Color(*c(PURPLE)[:3], a * (.6 + .6 * self.pulse))
                    RoundedRectangle(pos=(self.x - k, self.y - k), size=(self.width + 2 * k, self.height + 2 * k),
                                     radius=[r + k])
            Color(1, 1, 1, .45 if self.disabled else (.85 if self.state == "down" else 1))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[r], texture=_grad(PURPLE, INDIGO))
            Color(1, 1, 1, .18)                                      # brillo de vidrio arriba
            RoundedRectangle(pos=(self.x + dp(3), self.center_y), size=(self.width - dp(6), self.height / 2 - dp(3)),
                             radius=[r - dp(3)])
            if not self.disabled:                                    # destello estelar
                s = dp(3) + dp(1.5) * self.pulse
                Color(1, 1, 1, .5 + .5 * self.pulse)
                Ellipse(pos=(self.right - r - s / 2, self.top - dp(9) - s / 2), size=(s, s))


class AIGhost(_Pulse, ButtonBehavior, Label):
    """Acción secundaria de IA: borde neón fino y texto violeta."""

    def __init__(self, text="", icon="creation", on_press_cb=None, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(44))
        super().__init__(bold=True, font_size=sp(14), halign="center", valign="middle", markup=True,
                         shorten=True, shorten_from="right", **kw)
        from kivymd.icon_definitions import md_icons
        from kivymd import fonts_path
        import os
        font = os.path.join(fonts_path, "materialdesignicons-webfont.ttf")
        g = md_icons.get(icon, "")
        self.text = f"[font={font}][size={int(sp(17))}]{g}[/size][/font]  {text}" if g else text
        self.color = c(ink())
        if on_press_cb:
            self.bind(on_release=lambda *_: on_press_cb())
        self.bind(pos=self._draw, size=self._draw, state=self._draw, pulse=self._draw)
        self._start_pulse()

    def _draw(self, *_):
        self.text_size = (self.width - dp(20), None)
        r = self.height / 2
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*c(soft())[:3], .55 if self.state == "normal" else .9)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[r])
            Color(*c(VIOLET)[:3], .10 + .10 * self.pulse)
            Line(rounded_rectangle=(self.x - dp(1.5), self.y - dp(1.5), self.width + dp(3), self.height + dp(3), r + dp(1.5)),
                 width=dp(2.5))
            Color(*c(PURPLE)[:3], .75 + .25 * self.pulse)
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height, r), width=dp(1.2))


class AIChip(ButtonBehavior, Label):
    """Alternativa que propone la IA («BBCH 69 · 19 %»)."""

    def __init__(self, text="", **kw):
        super().__init__(text=text, font_size=sp(13.5), bold=True, size_hint=(None, None), height=dp(36),
                         color=c(ink()), **kw)
        self.texture_update()
        self.width = self.texture_size[0] + dp(28)
        self.bind(pos=self._draw, size=self._draw, state=self._draw)

    def _draw(self, *_):
        r = self.height / 2
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*c(soft())[:3], 1 if self.state == "normal" else .7)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[r])
            Color(*c(VIOLET)[:3], .55)
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height, r), width=dp(1))


class AIBar(Widget):
    """Confianza de la IA: riel tenue y relleno con degradado violeta → índigo."""
    value = NumericProperty(0)     # 0..1

    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(8))
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, value=self._draw)

    def _draw(self, *_):
        r = self.height / 2
        self.canvas.clear()
        with self.canvas:
            Color(*c(VIOLET)[:3], .16)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[r])
            if self.value > 0:
                w = max(self.height, self.width * min(1, self.value))
                Color(1, 1, 1, 1)
                RoundedRectangle(pos=self.pos, size=(w, self.height), radius=[r], texture=_grad(PURPLE, INDIGO))
                Color(1, 1, 1, .9)
                Ellipse(pos=(self.x + w - self.height, self.y), size=(self.height, self.height))


class Stars(Widget):
    """Estrellas que titilan (dentro de una tarjeta de IA). Pocas y tenues: es un acento."""
    count = NumericProperty(14)
    bright = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        rnd = random.Random(7)
        self._pts = [(rnd.random(), rnd.random(), rnd.uniform(.6, 1.6), rnd.random() * 6) for _ in range(40)]
        self._t, self._ev = 0.0, None
        self.bind(pos=self._draw, size=self._draw, parent=self._watch)

    def _watch(self, *_):
        if self.parent is not None and self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 1 / 12)
        elif self.parent is None and self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def _tick(self, dt):
        if self.get_root_window() is not None:
            self._t += dt
            self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        dark = theme.is_dark()
        col = (1, 1, 1) if dark else c(VIOLET)[:3]
        with self.canvas:
            for fx, fy, s, ph in self._pts[:int(self.count)]:
                a = (.25 + .55 * (.5 + .5 * math.sin(self._t * 1.7 + ph))) * (1 if dark else .55)
                Color(*col, a)
                d = dp(s) * (1.4 if self.bright else 1)
                Ellipse(pos=(self.x + fx * self.width - d / 2, self.y + fy * self.height - d / 2), size=(d, d))
