"""
ui/splash_anim.py
=================
Logo animado de la apertura (capas de tools/make_splash_layers.py):

* El presplash de Android muestra la frambuesa-reloj (9:10) mientras la app se arma por
  completo; recién después corre la animación, de corrido y sin tirones:
* el círculo punteado aparece girando y los dibujos chicos del ciclo recorren el círculo
  hasta su lugar, uno tras otro;
* el minutero da una vuelta a saltitos, como un reloj real, y la manija de la hora avanza
  una hora: el reloj termina en las 10:10 del logo, justo cuando llega el último dibujo.

El tiempo de la animación avanza por cuadros dibujados (con tope): si el teléfono se
traba un instante, la animación se pausa en vez de saltar.
"""
from __future__ import annotations

import json
import math
import os

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Ellipse, Line, PopMatrix, PushMatrix, Rectangle, Rotate
from kivy.uix.widget import Widget

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ui", "splash")

TICK_S = .105          # un «salto» del minutero (1/12 de vuelta)
TOTAL_S = (11 + .45) * TICK_S   # la vuelta completa: termina con el último salto (≈1,2 s)
RING_S = 1.0           # el círculo aparece girando
ICON_DELAY, ICON_STAGGER, ICON_S = .1, .09, .75   # el último dibujo llega a ≈1,2 s
MAX_DT = 1 / 24        # una traba larga no adelanta la animación (se pausa)
ICON_SWEEP = 300       # grados que recorre cada dibujo por el círculo antes de quedar quieto


def _out_cubic(x):
    return 1 - (1 - x) ** 3


def _out_back(x, s=1.7):
    x -= 1
    return 1 + x * x * ((s + 1) * x + s)


class LogoAnim(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        with open(os.path.join(DIR, "layout.json"), encoding="utf-8") as f:
            self.L = json.load(f)
        tex = lambda name: CoreImage(os.path.join(DIR, name)).texture  # noqa: E731
        self._tex = {"berry": tex("berry.png"), "ring": tex("ring.png")}
        for ic in self.L["icons"]:
            self._tex[ic["file"]] = tex(ic["file"])
        rc = self.L["ring"]
        self._icon_deg = [math.degrees(math.atan2(ic["v"] - rc["v"], ic["u"] - rc["u"]))
                          for ic in self.L["icons"]]
        self._t = None
        self._ev = None
        self._done = None
        self.bind(pos=self._draw, size=self._draw)

    # ---------------------------------------------------------------- control
    def start(self, done=None):
        """Corre la animación completa y luego llama a done()."""
        self._t, self._done = 0.0, done
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 0)

    def _tick(self, dt):
        self._t = min(TOTAL_S, self._t + min(dt, MAX_DT))
        self._draw()
        if self._t >= TOTAL_S:
            self.stop()
            done, self._done = self._done, None
            if done:
                Clock.schedule_once(lambda *_: done(), .15)

    def stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    # ---------------------------------------------------------------- tiempo
    @staticmethod
    def _steps(t):
        """Saltos del minutero hasta t (0 … 12): salto rápido con un pequeño rebote."""
        step, frac = divmod(t / TICK_S, 1)
        return min(12.0, step + min(1.0, _out_back(min(1.0, frac / .45))))

    def hands(self, t):
        """(minutero, hora) en grados: de 9:10 a 10:10 en una vuelta del minutero."""
        n = self._steps(t)
        return (self.L["minute"]["deg"] - 30 * n,
                self.L["hour"]["deg"] + 30 - 2.5 * n)

    # ---------------------------------------------------------------- dibujo
    def _draw(self, *_):
        side = min(self.width, self.height)
        if side <= 0:
            return
        ox, oy = self.center_x - side / 2, self.center_y - side / 2
        t = self._t or 0.0            # antes de empezar: igual que el presplash
        L = self.L
        self.canvas.clear()
        with self.canvas:
            # Círculo punteado: aparece y gira hasta quedar en su lugar.
            k = min(1.0, t / RING_S)
            rc = L["ring"]
            cx, cy = ox + rc["u"] * side, oy + rc["v"] * side
            PushMatrix()
            Rotate(angle=-120 * (1 - _out_cubic(k)), origin=(cx, cy))
            Color(1, 1, 1, min(1.0, k * 2))
            Rectangle(texture=self._tex["ring"], pos=(ox, oy), size=(side, side))
            PopMatrix()
            # Dibujos chicos: recorren el círculo (sentido horario) hasta su sitio.
            for i, ic in enumerate(L["icons"]):
                x = (t - ICON_DELAY - i * ICON_STAGGER) / ICON_S
                if x <= 0:
                    continue
                x = min(1.0, x)
                e, a = _out_cubic(x), min(1.0, x * 3)
                ang = math.radians(self._icon_deg[i] + ICON_SWEEP * (1 - e))
                dist = math.hypot(ic["u"] - rc["u"], ic["v"] - rc["v"]) * side
                px, py = cx + math.cos(ang) * dist, cy + math.sin(ang) * dist
                sc = .35 + .65 * _out_back(x)
                w, h = ic["w"] * side * sc, ic["h"] * side * sc
                Color(1, 1, 1, a)
                Rectangle(texture=self._tex[ic["file"]], pos=(px - w / 2, py - h / 2), size=(w, h))
            # La frambuesa-reloj (igual que el presplash).
            Color(1, 1, 1, 1)
            Rectangle(texture=self._tex["berry"], pos=(ox, oy), size=(side, side))
            # Manijas.
            minute, hour = self.hands(t)
            fx, fy = ox + L["face"]["u"] * side, oy + L["face"]["v"] * side
            Color(*L["hand_rgb"], 1)
            for deg, ln in ((hour, L["hour"]["len"]), (minute, L["minute"]["len"])):
                r = math.radians(deg)
                Line(points=[fx, fy, fx + math.cos(r) * ln * side, fy + math.sin(r) * ln * side],
                     width=max(1.0, L["hand_w"] * side * .6), cap="round")   # = grosor del presplash
            d = L["dot_r"] * side
            Ellipse(pos=(fx - d, fy - d), size=(2 * d, 2 * d))
