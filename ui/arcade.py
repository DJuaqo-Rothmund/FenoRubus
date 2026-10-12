"""
ui/arcade.py
============
Estética de videojuego para el desafío de la IA (todo dibujado en el canvas, liviano):

* `PixelText`: texto en letras de píxeles (fuente 5×7 propia, con sombra).
* `PixelArena`: fondo con píxeles que cruzan en «dash» (estelas) y un orbe central
  pulsante con anillo de píxeles que gira; se toca para aceptar el desafío.
* `burst(x, y)`: explosión de píxeles (acierto).
* `countdown(on_done)`: 3 · 2 · 1 · ¡YA! a pantalla completa.

Las animaciones corren a 30 cuadros por segundo y solo mientras se ven.
"""
from __future__ import annotations

import math
import random
import unicodedata

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Rectangle
from kivy.metrics import dp
from kivy.properties import ColorProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

from ui import theme
from ui.theme import c

NEON = ["#4FC3F7", "#F472B6", "#FDE047", "#34D399", "#A78BFA"]

# Fuente 5×7: cada letra son 7 filas de 5 bits.
_F = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01111 10000 10000 10000 10000 10000 01111", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01111 10000 10000 10011 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "11111 00100 00100 00100 00100 00100 11111", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 11001 10101 10011 10001 10001 10001",
    "Ñ": "01110 00000 11001 10101 10011 10001 10001", "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000", "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001", "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100", "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100", "W": "10001 10001 10001 10101 10101 10101 01010",
    "X": "10001 10001 01010 00100 01010 10001 10001", "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    "?": "01110 10001 00001 00010 00100 00000 00100", "¿": "00100 00000 00100 01000 10000 10001 01110",
    "!": "00100 00100 00100 00100 00100 00000 00100", "¡": "00100 00000 00100 00100 00100 00100 00100",
    "+": "00000 00100 00100 11111 00100 00100 00000", "-": "00000 00000 00000 11111 00000 00000 00000",
    ".": "00000 00000 00000 00000 00000 01100 01100", "·": "00000 00000 00000 01100 01100 00000 00000",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}
GLYPHS = {k: [row for row in v.split()] for k, v in _F.items()}


def _glyph(ch: str):
    ch = ch.upper()
    if ch not in GLYPHS:   # «Í» -> «I», «É» -> «E»…
        ch = "".join(x for x in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(x))
    return GLYPHS.get(ch, GLYPHS["?"])


class PixelText(Widget):
    """Texto en píxeles; cada «píxel» mide `px`. Líneas separadas por \\n."""
    text = StringProperty("")
    px = NumericProperty(dp(3))
    color = ColorProperty(c(theme.MIND_TEXT))
    shadow = ColorProperty(c("#000000", .45))

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint = (None, None)
        self._tr = None
        self.bind(text=self._redraw, px=self._redraw, color=self._redraw)
        self.bind(pos=self._move)
        self._redraw()

    def _move(self, *_):
        if self._tr is not None:
            self._tr.xy = self.pos

    def _redraw(self, *_):
        """Dibuja en coordenadas locales; mover el texto solo cambia una traslación."""
        from kivy.graphics import PopMatrix, PushMatrix, Translate
        lines = self.text.split("\n")
        px = self.px
        w = max((len(l) * 6 - 1) for l in lines) * px if lines else 0
        h = (len(lines) * 9 - 2) * px
        self.canvas.clear()
        with self.canvas:
            PushMatrix()
            self._tr = Translate(*self.pos)
            for col, off in ((self.shadow, px * .6), (self.color, 0)):
                Color(*col)
                for li, line in enumerate(lines):
                    lw = (len(line) * 6 - 1) * px
                    x0 = (w - lw) / 2 + off
                    y0 = h - (li * 9 + 7) * px - off
                    for ci, ch in enumerate(line):
                        for r, bits in enumerate(_glyph(ch)):
                            for k, b in enumerate(bits):
                                if b == "1":
                                    Rectangle(pos=(x0 + (ci * 6 + k) * px, y0 + (6 - r) * px),
                                              size=(px * .9, px * .9))
            PopMatrix()
        self.size = (w, h)


class PixelOrb(ButtonBehavior, Widget):
    """Orbe central: núcleo que late y anillo de píxeles que gira."""
    phase = NumericProperty(0)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self._redraw, size=self._redraw, phase=self._redraw, state=self._redraw)

    def _redraw(self, *_):
        self.canvas.before.clear()
        cx, cy = self.center
        r = min(self.width, self.height) / 2
        beat = 1 + .06 * math.sin(self.phase * 3)
        press = .9 if self.state == "down" else 1
        with self.canvas.before:
            for i, a in enumerate((.10, .16, .24)):        # halo
                Color(*c(theme.MIND_ACCENT, a))
                rr = r * (1.05 - i * .14) * beat * press
                Ellipse(pos=(cx - rr, cy - rr), size=(rr * 2, rr * 2))
            Color(*c("#0B1630"))
            rr = r * .66 * press
            Ellipse(pos=(cx - rr, cy - rr), size=(rr * 2, rr * 2))
            n, s = 28, dp(5)
            for i in range(n):                              # anillo de píxeles que gira
                ang = self.phase * .9 + i * 2 * math.pi / n
                Color(*c(NEON[i % len(NEON)], .55 + .45 * (math.sin(self.phase * 4 + i) > 0)))
                x = cx + math.cos(ang) * r * .82 * press
                y = cy + math.sin(ang) * r * .82 * press
                Rectangle(pos=(x - s / 2, y - s / 2), size=(s, s))


# Frambuesa de 8 bits (7×8): G hoja, R fruto, r brillo, D sombra.
RASPBERRY = ["..G.G..",
             ".GGGGG.",
             ".RRRRR.",
             "RRrRRrR",
             "RRRRRRR",
             "DRrRRRD",
             ".DRRRD.",
             "..DRD.."]
SPRITE_COLORS = {"G": "#4CAF50", "R": "#D81B60", "r": "#F8BBD0", "D": "#8E1240"}
_sprite_tex = None


def raspberry_texture():
    """Textura de la frambuesa pixelada (una sola, ampliada sin suavizar)."""
    global _sprite_tex
    if _sprite_tex is None:
        from kivy.graphics.texture import Texture
        from kivy.utils import get_color_from_hex
        h, w = len(RASPBERRY), len(RASPBERRY[0])
        buf = bytearray()
        for row in reversed(RASPBERRY):           # la textura va de abajo hacia arriba
            for ch in row:
                if ch == ".":
                    buf += bytes((0, 0, 0, 0))
                else:
                    r, g, b, _a = get_color_from_hex(SPRITE_COLORS[ch])
                    buf += bytes((int(r * 255), int(g * 255), int(b * 255), 255))
        tex = Texture.create(size=(w, h), colorfmt="rgba")
        tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
        tex.mag_filter = tex.min_filter = "nearest"
        _sprite_tex = tex
    return _sprite_tex


class PixelArena(FloatLayout):
    """Fondo de juego: frambuesas de 8 bits que cruzan en «dash» (con estela) y el orbe."""
    streaks = ListProperty([])

    def __init__(self, **kw):
        super().__init__(**kw)
        self._ev = None
        self._t = 0.0
        rnd = random.Random(7)
        self.streaks = [{"y": rnd.random(), "x": rnd.random(), "v": rnd.uniform(.22, .6),
                         "len": rnd.randint(3, 6), "s": rnd.choice((dp(2.5), dp(3), dp(3.5))),
                         "bob": rnd.uniform(0, 6.3)} for _ in range(12)]
        self.orb = None

    def start(self):
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._step, 1 / 30)

    def stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def on_parent(self, *_):
        if self.parent is None:
            self.stop()

    def _step(self, dt):
        if self.get_root_window() is None:    # ya no se ve: se detiene sola
            self.stop()
            return
        self._t += dt
        if self.orb is not None:
            self.orb.phase = self._t
        for ch in self.children:            # textos de píxeles: siempre en su lugar
            if isinstance(ch, PixelText) and ch._tr is not None:
                ch._tr.xy = ch.pos
        tex = raspberry_texture()
        self.canvas.before.clear()
        w, h = self.size
        with self.canvas.before:
            Color(*c("#060C1A", .55))
            Rectangle(pos=self.pos, size=self.size)
            for st in self.streaks:
                st["x"] -= st["v"] * dt
                s = st["s"]
                sw, sh = 7 * s, 8 * s
                if st["x"] * w < -sw * 3:
                    st["x"] = 1.05
                    st["y"] = random.random()
                x = self.x + st["x"] * w
                # Saltito de 8 bits: sube y baja en escalones de un píxel.
                y = self.y + st["y"] * (h - sh) + round(math.sin(self._t * 6 + st["bob"])) * s
                for k in range(1, st["len"] + 1):          # estela: píxeles frambuesa que se apagan
                    px = x + sw + k * s * 1.6
                    if self.x <= px <= self.right - s:
                        Color(*c(SPRITE_COLORS["R"], max(.08, .7 - k / (st["len"] + 1))))
                        Rectangle(pos=(px, y + sh * .45), size=(s, s))
                if self.x <= x and x + sw <= self.right:
                    Color(1, 1, 1, 1)
                    Rectangle(texture=tex, pos=(x, y), size=(sw, sh))


def burst(x: float, y: float, n: int = 36):
    """Explosión de píxeles en (x, y) de la ventana (≈0,8 s)."""
    layer = Widget(size=Window.size)
    rnd = random.Random()
    parts = [{"x": x, "y": y, "vx": rnd.uniform(-1, 1) * dp(260), "vy": rnd.uniform(-.4, 1.2) * dp(300),
              "col": rnd.choice(NEON), "s": rnd.choice((dp(4), dp(5), dp(6)))} for _ in range(n)]
    state = {"t": 0.0}

    def step(dt):
        state["t"] += dt
        t = state["t"]
        layer.canvas.clear()
        with layer.canvas:
            for p in parts:
                p["vy"] -= dp(900) * dt
                p["x"] += p["vx"] * dt
                p["y"] += p["vy"] * dt
                Color(*c(p["col"], max(0, 1 - t / .8)))
                Rectangle(pos=(p["x"], p["y"]), size=(p["s"], p["s"]))
        if t >= .8:
            ev.cancel()
            Window.remove_widget(layer)

    Window.add_widget(layer)
    ev = Clock.schedule_interval(step, 1 / 30)


def countdown(on_done, steps=("3", "2", "1", "¡YA!")):
    """Cuenta regresiva de videojuego a pantalla completa; al final llama on_done()."""
    layer = FloatLayout(size=Window.size)
    with layer.canvas.before:
        Color(*c("#050A16", .78))
        Rectangle(pos=(0, 0), size=Window.size)
    Window.add_widget(layer)
    txt = PixelText(text="", px=dp(14), color=c(theme.MIND_ACCENT))
    layer.add_widget(txt)

    def show(i):
        if i >= len(steps):
            Window.remove_widget(layer)
            on_done()
            return
        txt.text = steps[i]
        txt.color = c(NEON[i % len(NEON)])
        txt.px = dp(6)
        txt.center = (Window.width / 2, Window.height / 2)

        def grow(*_):
            txt.center = (Window.width / 2, Window.height / 2)

        txt.unbind(size=grow)
        txt.bind(size=grow)
        Animation(px=dp(16) if len(steps[i]) == 1 else dp(9), d=.22, t="out_back").start(txt)
        if i == len(steps) - 1:
            burst(Window.width / 2, Window.height / 2, 48)
        Clock.schedule_once(lambda *_: show(i + 1), .62)

    show(0)
    return layer


def party(title: str, subtitle: str = "", duration: float = 3.6):
    """Serpentinas y papel picado EN PÍXELES con un letrero de videojuego al centro
    (desafío completado). Se cierra sola o al tocarla."""
    from kivy.uix.label import Label
    layer = FloatLayout(size=Window.size)
    W, H = Window.size
    rnd = random.Random()
    s = dp(5)
    bits = [{"x": rnd.uniform(0, W), "y": H + rnd.uniform(0, H * .6), "v": rnd.uniform(dp(150), dp(290)),
             "col": rnd.choice(NEON + [SPRITE_COLORS["R"]]), "s": rnd.choice((dp(4), dp(5), dp(6)))}
            for _ in range(60)]
    snakes = [{"x": rnd.uniform(dp(10), W - dp(10)), "y": H + rnd.uniform(0, H * .5),
               "v": rnd.uniform(dp(130), dp(220)), "col": rnd.choice(NEON + [SPRITE_COLORS["R"]]),
               "ph": rnd.uniform(0, 6.3), "n": rnd.randint(12, 18)} for _ in range(10)]
    berries = [{"x": rnd.uniform(0, W), "y": H + rnd.uniform(0, H * .7), "v": rnd.uniform(dp(120), dp(200))}
               for _ in range(8)]
    state = {"t": 0.0, "closing": False}
    tex = raspberry_texture()

    def step(dt):
        state["t"] += dt
        t = state["t"]
        layer.canvas.before.clear()
        with layer.canvas.before:
            Color(*c("#050A16", .55))
            Rectangle(pos=(0, 0), size=(W, H))
            for b in bits:
                b["y"] -= b["v"] * dt
                Color(*c(b["col"]))
                # en una grilla: cae «a saltos» como en una consola antigua
                Rectangle(pos=(round(b["x"] / s) * s, round(b["y"] / s) * s), size=(b["s"], b["s"]))
            for sn in snakes:
                sn["y"] -= sn["v"] * dt
                Color(*c(sn["col"]))
                for k in range(sn["n"]):                   # serpentina: zigzag de cuadritos
                    off = round(math.sin(k * .7 + sn["ph"] + t * 5) * 2) * s
                    Rectangle(pos=(round((sn["x"] + off) / s) * s, round((sn["y"] + k * s) / s) * s),
                              size=(s, s))
            Color(1, 1, 1, 1)
            for br in berries:
                br["y"] -= br["v"] * dt
                Rectangle(texture=tex, pos=(br["x"], br["y"]), size=(7 * dp(4), 8 * dp(4)))
        if t >= duration:
            close()

    def close(*_):
        if state["closing"]:
            return
        state["closing"] = True
        ev.cancel()
        Window.remove_widget(layer)

    # Letrero central (estilo pantalla de victoria)
    card_w, card_h = min(W - dp(40), dp(330)), dp(180)
    with layer.canvas:
        Color(*c("#0B1630", .96))
        Rectangle(pos=((W - card_w) / 2, (H - card_h) / 2), size=(card_w, card_h))
        Color(*c(theme.MIND_ACCENT))
        for i in range(0, int(card_w), int(s * 2)):         # borde punteado de píxeles
            Rectangle(pos=((W - card_w) / 2 + i, (H - card_h) / 2), size=(s, s))
            Rectangle(pos=((W - card_w) / 2 + i, (H + card_h) / 2 - s), size=(s, s))
    txt = PixelText(text=title, px=dp(4.5), color=c("#FDE047"))
    txt.pos = ((W - txt.width) / 2, H / 2 - txt.height / 2 + (dp(18) if subtitle else 0))
    layer.add_widget(txt)
    if subtitle:
        lb = Label(text=subtitle, font_size="13sp", color=c(theme.MIND_TEXT), size_hint=(None, None),
                   halign="center")
        lb.texture_update()
        lb.size = lb.texture_size
        lb.pos = ((W - lb.width) / 2, H / 2 - card_h / 2 + dp(18))
        layer.add_widget(lb)
    layer.bind(on_touch_down=lambda *_: close() or True)
    Window.add_widget(layer)
    burst(W / 2, H / 2, 40)
    ev = Clock.schedule_interval(step, 1 / 30)
    return layer
