"""
ui/sheet_keypad.py
==================
Teclado numérico propio de la planilla (los datos son números): aparece abajo al tocar una
celda, sin abrir el teclado del teléfono.

    1  2  3  4  5  ⌫
    6  7  8  9  0  ,
    🎨 Color · Aa Texto · ↓ · → · ✓ Listo

* 🎨 pinta el número de la celda con un color de la LEYENDA que crea la persona
  («Planta enferma» en rojo, «Remedir» en azul…): la leyenda es del ensayo y la comparten
  todas sus planillas.
* «Aa Texto» abre el teclado del teléfono solo para esa celda (para escribir una palabra).
"""
from __future__ import annotations

import os

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label

from ui.theme import c

PANEL = "#123A2C"          # = encabezado de la planilla
KEY = "#FFFFFF"
KEY_INK = "#1B2A23"
ACCENT = "#A8184A"

# Colores para la leyenda (se leen bien sobre la celda blanca).
SWATCHES = ["#E53935", "#FB8C00", "#C99A00", "#43A047", "#00897B", "#1E88E5", "#8E24AA", "#6D4C41"]


def _icon_markup(icon: str, size: float) -> str:
    from kivymd import fonts_path
    from kivymd.icon_definitions import md_icons
    font = os.path.join(fonts_path, "materialdesignicons-webfont.ttf")
    return f"[font={font}][size={int(sp(size))}]{md_icons.get(icon, '?')}[/size][/font]"


class Key(ButtonBehavior, Label):
    """Tecla redondeada: un dígito o un ícono con texto corto."""
    kind = StringProperty("digit")      # digit · tool · main

    def __init__(self, text="", icon="", kind="digit", **kw):
        label = text
        if icon:
            label = _icon_markup(icon, 20 if kind == "digit" else 18) + (f"  {text}" if text else "")
        super().__init__(text=label, markup=True, bold=True, halign="center", valign="middle",
                         font_size=sp(22 if kind == "digit" and not icon else 14), **kw)
        self.kind = kind
        self.color = c("#FFFFFF") if kind == "main" else c(KEY_INK if kind == "digit" else "#E8F5EE")
        self.bind(pos=self._draw, size=self._draw, state=self._draw)

    def _draw(self, *_):
        self.text_size = self.size
        self.canvas.before.clear()
        down = self.state == "down"
        with self.canvas.before:
            if self.kind == "digit":
                Color(*c(KEY, .78 if down else 1))
            elif self.kind == "main":
                Color(*c(ACCENT, .8 if down else 1))
            else:
                Color(1, 1, 1, .26 if down else .12)
            RoundedRectangle(pos=(self.x + dp(2), self.y + dp(2)), size=(self.width - dp(4), self.height - dp(4)),
                             radius=[dp(12)])


class SheetKeypad(BoxLayout):
    """El panel. `on_key(k)` recibe: «0»…«9», «,», «back», «clear», «color», «text», «down»,
    «right», «done»."""

    def __init__(self, on_key, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(232),
                         padding=(dp(10), dp(8), dp(10), dp(10)), spacing=dp(4), **kw)
        self.on_key = on_key
        self.bind(pos=self._bg, size=self._bg)
        head = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
        self.where = Label(text="", font_size=sp(12.5), color=c("#BFE3CF"), halign="left", valign="middle",
                           shorten=True, shorten_from="left")
        self.where.bind(size=lambda w, s: setattr(w, "text_size", s))
        self.value = Label(text="", font_size=sp(18), bold=True, color=(1, 1, 1, 1), halign="right",
                           valign="middle", size_hint_x=None, width=dp(120))
        self.value.bind(size=lambda w, s: setattr(w, "text_size", s))
        head.add_widget(self.where)
        head.add_widget(self.value)
        self.add_widget(head)
        grid = GridLayout(cols=6, spacing=0, size_hint_y=None, height=dp(124))
        for k in "12345":
            grid.add_widget(self._key(k))
        back = Key(icon="backspace-outline", kind="tool")
        back.bind(on_release=lambda *_: self.on_key("back"))
        self._hold = None
        back.bind(on_press=lambda *_: self._start_hold(), on_release=lambda *_: self._stop_hold())
        grid.add_widget(back)
        for k in "67890":
            grid.add_widget(self._key(k))
        comma = self._key(",", kind="tool")
        comma.font_size = sp(26)
        grid.add_widget(comma)
        self.add_widget(grid)
        tools = BoxLayout(size_hint_y=None, height=dp(62), spacing=0)
        for text, icon, k, kind, w in (("Color", "palette", "color", "tool", 1.25),
                                       ("Texto", "keyboard-outline", "text", "tool", 1.2),
                                       ("", "arrow-down", "down", "tool", .7),
                                       ("", "arrow-right", "right", "tool", .7),
                                       ("Listo", "check", "done", "main", 1.25)):
            b = Key(text, icon=icon, kind=kind, size_hint_x=w)
            b.bind(on_release=lambda _b, k=k: self.on_key(k))
            tools.add_widget(b)
        self.add_widget(tools)

    def _key(self, k, kind="digit"):
        b = Key(k, kind=kind)
        b.bind(on_release=lambda *_: self.on_key(k))
        return b

    def _start_hold(self):            # ⌫ mantenido: vacía la celda
        self._hold = Clock.schedule_once(lambda *_: self.on_key("clear"), .6)

    def _stop_hold(self):
        if self._hold:
            self._hold.cancel()
            self._hold = None

    def show(self, where: str, value: str):
        self.where.text, self.value.text = where, value

    def _bg(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0, 0, 0, .18)
            RoundedRectangle(pos=(self.x, self.y + dp(2)), size=self.size, radius=[dp(22), dp(22), 0, 0])
            Color(*c(PANEL))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(22), dp(22), 0, 0])


def legend_editor(on_save, name: str = "", color: str = ""):
    """Nueva leyenda: nombre + color. on_save(name, color)."""
    from kivymd.uix.boxlayout import MDBoxLayout
    from kivymd.uix.textfield import MDTextField
    from ui.common import form_dialog
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(10))
    field = MDTextField(hint_text="Qué significa (ej.: Planta enferma)", text=name, mode="rectangle")
    box.add_widget(field)
    sw = GridLayout(cols=8, size_hint_y=None, height=dp(40), spacing=dp(6))
    state = {"color": color or SWATCHES[0]}
    dots = []

    def draw(*_):
        for d in dots:
            d.canvas.before.clear()
            with d.canvas.before:
                if d.hex == state["color"]:
                    Color(*c("#1B2A23"))
                    RoundedRectangle(pos=(d.x - dp(3), d.y - dp(3)), size=(d.width + dp(6), d.height + dp(6)),
                                     radius=[(d.width + dp(6)) / 2])
                    Color(1, 1, 1, 1)
                    RoundedRectangle(pos=(d.x - dp(1.5), d.y - dp(1.5)), size=(d.width + dp(3), d.height + dp(3)),
                                     radius=[(d.width + dp(3)) / 2])
                Color(*c(d.hex))
                RoundedRectangle(pos=d.pos, size=d.size, radius=[d.width / 2])

    class Dot(ButtonBehavior, Label):
        pass
    for hx in SWATCHES:
        d = Dot(size_hint=(None, None), size=(dp(30), dp(30)))
        d.hex = hx
        d.bind(pos=draw, size=draw, on_release=lambda d: (state.__setitem__("color", d.hex), draw()))
        dots.append(d)
        sw.add_widget(d)
    box.add_widget(sw)

    def ok(_f):
        if not field.text.strip():
            field.error = True
            return False
        on_save(field.text.strip(), state["color"])

    return form_dialog("Nueva leyenda" if not name else "Editar leyenda", box, ok)
