"""
ui/splash_timeline.py
=====================
La animación del logo como funciones del tiempo, sin Kivy: la usan el logo de Kivy
(ui/splash_anim.py) y el generador de la animación nativa de Android (Lottie,
tools/make_splash_lottie.py). Al ser las mismas cuentas, cuando la app quita la
animación nativa y sigue la de Kivy, ambas muestran exactamente el mismo cuadro.

Coordenadas en el cuadrado del logo: (u, v) de 0 a 1, v hacia arriba; ángulos en grados
en sentido antihorario desde las 3 en punto.

* 0 – 1,2 s: el círculo punteado aparece girando y los cinco dibujos del ciclo recorren
  el círculo hasta su lugar; el minutero da una vuelta (9:10 → 10:10).
* Después el reloj sigue andando (acelerado): el minutero salta 1/12 de vuelta cada
  TICK_S y la hora avanza como en un reloj real (12 veces más lenta).
"""
from __future__ import annotations

import json
import math
import os

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ui", "splash")

TICK_S = .105                    # un «salto» del minutero (1/12 de vuelta)
INTRO_S = (11 + .45) * TICK_S    # primera vuelta: el reloj llega a las 10:10 (≈1,2 s)
RING_S = 1.0                     # el círculo aparece girando
RING_TURN = 120                  # grados que gira el círculo al aparecer
ICON_DELAY, ICON_STAGGER, ICON_S = .1, .09, .75   # el último dibujo llega a ≈1,2 s
ICON_SWEEP = 300                 # grados que recorre cada dibujo por el círculo
HAND_THICK = 1.2                 # grosor de las manijas (× hand_w del logo)
LOTTIE_FPS = 60                  # cuadros por segundo de la animación nativa (Lottie)


def load_layout() -> dict:
    with open(os.path.join(DIR, "layout.json"), encoding="utf-8") as f:
        return json.load(f)


def out_cubic(x):
    return 1 - (1 - x) ** 3


def out_back(x, s=1.7):
    x -= 1
    return 1 + x * x * ((s + 1) * x + s)


def minute_steps(t: float) -> float:
    """Saltos del minutero hasta t: cada salto es rápido y rebota un poco al llegar."""
    step, frac = divmod(max(0.0, t) / TICK_S, 1)
    return step + min(1.0, out_back(min(1.0, frac / .45)))


def hands(L: dict, t: float) -> tuple[float, float]:
    """(minutero, hora) en grados: 9:10 en t=0 y 10:10 al terminar la primera vuelta."""
    n = minute_steps(t)
    return L["minute"]["deg"] - 30 * n, L["hour"]["deg"] + 30 - 2.5 * n


def ring(t: float) -> tuple[float, float]:
    """(giro en grados, opacidad) del círculo punteado."""
    k = min(1.0, max(0.0, t) / RING_S)
    return -RING_TURN * (1 - out_cubic(k)), min(1.0, k * 2)


def icons(L: dict, t: float) -> list:
    """Por dibujo: (u, v, escala, opacidad) o None si todavía no aparece."""
    rc = L["ring"]
    out = []
    for i, ic in enumerate(L["icons"]):
        x = (t - ICON_DELAY - i * ICON_STAGGER) / ICON_S
        if x <= 0:
            out.append(None)
            continue
        x = min(1.0, x)
        e = out_cubic(x)
        final = math.degrees(math.atan2(ic["v"] - rc["v"], ic["u"] - rc["u"]))
        ang = math.radians(final + ICON_SWEEP * (1 - e))
        dist = math.hypot(ic["u"] - rc["u"], ic["v"] - rc["v"])
        out.append((rc["u"] + math.cos(ang) * dist, rc["v"] + math.sin(ang) * dist,
                    .35 + .65 * out_back(x), min(1.0, x * 3)))
    return out
