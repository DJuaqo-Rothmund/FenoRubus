"""
ui/splash_anim.py
=================
Logo animado de la apertura (capas de tools/make_splash_layers.py):

* El presplash de Android muestra solo la frambuesa-reloj; aquí sigue la misma imagen y
  aparecen el círculo punteado (girando) y los dibujos chicos del ciclo, que recorren el
  círculo hasta su lugar, uno tras otro.
* Mientras la app carga, las manijas avanzan a saltitos como un reloj real (la de las
  horas, 12 veces más lenta). El tiempo sale del reloj del sistema: si el teléfono se
  traba un instante, las manijas no se atrasan, saltan a donde deben estar.
* `finish(listo)`: el minutero completa su vuelta hasta las 10:10 del logo y llama a listo.
"""
from __future__ import annotations

import json
import math
import os
import time

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Ellipse, Line, PopMatrix, PushMatrix, Rectangle, Rotate
from kivy.uix.widget import Widget

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ui", "splash")

TICK_S = .1            # un «salto» del minutero (1/12 de vuelta)
RING_S = 1.0           # el círculo aparece girando
ICON_DELAY, ICON_STAGGER, ICON_S = .1, .09, .8
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
        self._t0 = None
        self._ev = None
        self._finish = None
        self.bind(pos=self._draw, size=self._draw)

    # ---------------------------------------------------------------- control
    def start(self):
        self._t0 = time.monotonic()
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._draw, 1 / 60)

    def finish(self, done):
        """Termina la vuelta del minutero en las 10:10 y llama a done()."""
        if self._t0 is None:
            done()
            return
        t = time.monotonic() - self._t0
        self._finish = {"t": t, "end": self.finish_time(t), "done": done,
                        "hour0": self._hour_deg(t)}

    @staticmethod
    def finish_time(t):
        """Cuándo termina el salto que deja al minutero de nuevo en su lugar del logo
        (una vuelta completa = 12 saltos), siempre después de t."""
        end_step = (int(t / TICK_S) // 12 + 1) * 12
        while (end_step - 1 + .45) * TICK_S <= t + .25:      # tiempo para acomodar la hora
            end_step += 12
        return (end_step - 1 + .45) * TICK_S

    def stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    # ---------------------------------------------------------------- tiempo
    def _steps(self, t):
        """Minutero a saltitos: salto rápido con un pequeño rebote al llegar."""
        step, frac = divmod(t / TICK_S, 1)
        return step + min(1.0, _out_back(min(1.0, frac / .45)))

    def _hour_deg(self, t):
        return self.L["hour"]["deg"] - 2.5 * self._steps(t)

    def _hands(self, t):
        m0, h0 = self.L["minute"]["deg"], self.L["hour"]["deg"]
        fin = self._finish
        if fin and t >= fin["end"]:
            return m0, h0, True
        minute = m0 - 30 * self._steps(t)
        hour = self._hour_deg(t)
        if fin:   # la hora se acomoda en el tiempo que le queda al minutero
            k = min(1.0, (t - fin["t"]) / max(.05, fin["end"] - fin["t"]))
            start = fin["hour0"]
            target = start - ((start - h0) % 360)
            hour = start + (target - start) * _out_cubic(k)
        return minute, hour, False

    # ---------------------------------------------------------------- dibujo
    def _draw(self, *_):
        side = min(self.width, self.height)
        if side <= 0:
            return
        ox, oy = self.center_x - side / 2, self.center_y - side / 2
        t = (time.monotonic() - self._t0) if self._t0 is not None else 0.0
        L = self.L
        self.canvas.clear()
        with self.canvas:
            # Círculo punteado: aparece y gira hasta quedar en su lugar.
            k = min(1.0, t / RING_S) if self._t0 is not None else 1.0
            rc = L["ring"]
            cx, cy = ox + rc["u"] * side, oy + rc["v"] * side
            PushMatrix()
            Rotate(angle=-120 * (1 - _out_cubic(k)), origin=(cx, cy))
            Color(1, 1, 1, min(1.0, k * 2))
            Rectangle(texture=self._tex["ring"], pos=(ox, oy), size=(side, side))
            PopMatrix()
            # Dibujos chicos: recorren el círculo (sentido horario) hasta su sitio.
            for i, ic in enumerate(L["icons"]):
                if self._t0 is None:
                    e, a = 1.0, 1.0
                else:
                    x = (t - ICON_DELAY - i * ICON_STAGGER) / ICON_S
                    if x <= 0:
                        continue
                    x = min(1.0, x)
                    e, a = _out_cubic(x), min(1.0, x * 3)
                ang = math.radians(self._icon_deg[i] + ICON_SWEEP * (1 - e))
                dist = math.hypot(ic["u"] - rc["u"], ic["v"] - rc["v"]) * side
                px, py = cx + math.cos(ang) * dist, cy + math.sin(ang) * dist
                sc = .35 + .65 * (_out_back(x) if self._t0 is not None else 1.0)
                w, h = ic["w"] * side * sc, ic["h"] * side * sc
                Color(1, 1, 1, a)
                Rectangle(texture=self._tex[ic["file"]], pos=(px - w / 2, py - h / 2), size=(w, h))
            # La frambuesa-reloj (igual que el presplash).
            Color(1, 1, 1, 1)
            Rectangle(texture=self._tex["berry"], pos=(ox, oy), size=(side, side))
            # Manijas.
            minute, hour, ended = self._hands(t) if self._t0 is not None else (
                L["minute"]["deg"], L["hour"]["deg"], False)
            fx, fy = ox + L["face"]["u"] * side, oy + L["face"]["v"] * side
            Color(*L["hand_rgb"], 1)
            for deg, ln in ((hour, L["hour"]["len"]), (minute, L["minute"]["len"])):
                r = math.radians(deg)
                Line(points=[fx, fy, fx + math.cos(r) * ln * side, fy + math.sin(r) * ln * side],
                     width=max(1.0, L["hand_w"] * side / 2), cap="round")
            d = L["dot_r"] * side
            Ellipse(pos=(fx - d, fy - d), size=(2 * d, 2 * d))
        if ended and self._finish:
            done, self._finish = self._finish["done"], None
            self.stop()
            Clock.schedule_once(lambda *_: done(), .12)
