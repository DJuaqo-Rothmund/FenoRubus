"""
ui/splash_anim.py
=================
Logo animado de la apertura en Kivy (capas de tools/make_splash_layers.py). Sigue,
cuadro a cuadro, a la animación nativa de Android (Lottie) que se ve mientras la app
arranca y precarga: ambas salen de ui/splash_timeline.py, así que al quitar la nativa
no se nota el cambio.

* `t`: segundos de la animación. Mientras la nativa está a la vista, la app lo toma de
  ella (`sync(t)`); después avanza por cuadros dibujados, con tope (una traba la pausa,
  no la adelanta).
"""
from __future__ import annotations

import math
import os

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Ellipse, Line, PopMatrix, PushMatrix, Rectangle, Rotate
from kivy.uix.widget import Widget

from ui import splash_timeline as tl

DIR = tl.DIR
MAX_DT = 1 / 24        # una traba larga no adelanta la animación (se pausa)


class LogoAnim(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.L = tl.load_layout()
        tex = lambda name: CoreImage(os.path.join(DIR, name)).texture  # noqa: E731
        self._tex = {"berry": tex("berry.png"), "ring": tex("ring.png")}
        for ic in self.L["icons"]:
            self._tex[ic["file"]] = tex(ic["file"])
        self._t = 0.0
        self._ev = None
        self.bind(pos=self._draw, size=self._draw)

    # ---------------------------------------------------------------- control
    @property
    def t(self) -> float:
        return self._t

    def start(self, t: float = 0.0):
        """Empieza (o sigue) a andar desde t segundos."""
        self._t = t
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 0)
        self._draw()

    def sync(self, t: float):
        """Toma el tiempo de la animación nativa (mismo cuadro que se ve encima)."""
        self._t = t
        self._draw()

    def _tick(self, dt):
        self._t += min(dt, MAX_DT)
        self._draw()

    def stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    # ---------------------------------------------------------------- dibujo
    def _draw(self, *_):
        side = min(self.width, self.height)
        if side <= 0:
            return
        ox, oy = self.center_x - side / 2, self.center_y - side / 2
        t = self._t
        L = self.L
        self.canvas.clear()
        with self.canvas:
            # Círculo punteado: aparece y gira hasta quedar en su lugar.
            ang, alpha = tl.ring(t)
            rc = L["ring"]
            cx, cy = ox + rc["u"] * side, oy + rc["v"] * side
            PushMatrix()
            Rotate(angle=ang, origin=(cx, cy))
            Color(1, 1, 1, alpha)
            Rectangle(texture=self._tex["ring"], pos=(ox, oy), size=(side, side))
            PopMatrix()
            # Dibujos chicos: recorren el círculo (sentido horario) hasta su sitio.
            for ic, st in zip(L["icons"], tl.icons(L, t)):
                if st is None:
                    continue
                u, v, sc, a = st
                w, h = ic["w"] * side * sc, ic["h"] * side * sc
                Color(1, 1, 1, a)
                Rectangle(texture=self._tex[ic["file"]],
                          pos=(ox + u * side - w / 2, oy + v * side - h / 2), size=(w, h))
            # La frambuesa-reloj.
            Color(1, 1, 1, 1)
            Rectangle(texture=self._tex["berry"], pos=(ox, oy), size=(side, side))
            # Manijas.
            minute, hour = tl.hands(L, t)
            fx, fy = ox + L["face"]["u"] * side, oy + L["face"]["v"] * side
            Color(*L["hand_rgb"], 1)
            for deg, ln in ((hour, L["hour"]["len"]), (minute, L["minute"]["len"])):
                r = math.radians(deg)
                # Line.width de Kivy es la mitad del grosor.
                Line(points=[fx, fy, fx + math.cos(r) * ln * side, fy + math.sin(r) * ln * side],
                     width=max(1.0, L["hand_w"] * side * tl.HAND_THICK / 2), cap="round")
            d = L["dot_r"] * side
            Ellipse(pos=(fx - d, fy - d), size=(2 * d, 2 * d))


class CropLogoAnim(Widget):
    """Logo animado simple de PhenoBlue y PhenoCran (mientras tengan su logo definitivo):
    el fruto entra creciendo con un pequeño rebote y luego «respira». Misma interfaz que
    LogoAnim (start, stop, sync, t)."""

    def __init__(self, source: str, **kw):
        super().__init__(**kw)
        self._tex = CoreImage(source, mipmap=True).texture
        self._t = 0.0
        self._ev = None
        self.bind(pos=self._draw, size=self._draw)

    @property
    def t(self) -> float:
        return self._t

    def start(self, t: float = 0.0):
        self._t = t
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 0)
        self._draw()

    def sync(self, t: float):
        self._t = t
        self._draw()

    def stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def _tick(self, dt):
        self._t += min(dt, MAX_DT)
        self._draw()

    @staticmethod
    def _scale(t: float) -> float:
        if t < .7:   # ease-out-back: crece y se pasa un poco
            k = t / .7 - 1
            return .55 + .45 * (1 + 2.2 * k ** 3 + 1.2 * k ** 2)
        return 1 + .025 * math.sin((t - .7) * 3.2)

    def _draw(self, *_):
        side = min(self.width, self.height)
        if side <= 0:
            return
        t = self._t
        sc = self._scale(t)
        s = side * sc
        a = min(1.0, t / .35)
        self.canvas.clear()
        with self.canvas:
            PushMatrix()
            Rotate(angle=-8 * max(0.0, 1 - t / .7), origin=self.center)
            Color(1, 1, 1, a)
            Rectangle(texture=self._tex, pos=(self.center_x - s / 2, self.center_y - s / 2), size=(s, s))
            PopMatrix()
