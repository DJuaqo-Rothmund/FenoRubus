"""
ui/measures_fab.py
==================
Botón flotante de Mediciones (el contador manual) en el muestreo: va ENCIMA de todo (antes
colgaba de la franja del ensayo y las tarjetas lo tapaban). Tocar abre las mediciones;
mantenerlo presionado HOLD_S segundos (se ve un anillo que se llena) lo suelta para
arrastrarlo, y queda donde se deje (posición guardada en el teléfono) hasta moverlo de nuevo.
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget

from platform_utils import global_get, global_set

HOLD_S = 5.0                 # mantener presionado para moverlo
POS_KEY = "measures_fab_pos"   # (x, y) como fracción del ancho y alto de la pantalla


def clamp_pos(fx: float, fy: float, w: float, h: float, size: float, margin: float) -> tuple[float, float]:
    """Posición en píxeles (esquina inferior izquierda) dentro de la pantalla."""
    x = min(max(fx * w, margin), max(margin, w - size - margin))
    y = min(max(fy * h, margin), max(margin, h - size - margin))
    return x, y


class MeasuresFab(ButtonBehavior, Widget):
    hold = NumericProperty(0)          # 0-1: avance del «mantener presionado» (anillo)
    dragging = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._ev = None
        self._t = 0.0
        self.bind(parent=self._place)

    # ------------------------------------------------------------ posición
    def _place(self, *_):
        if self.parent is not None:
            self.parent.bind(size=self._place_now)
            Clock.schedule_once(self._place_now, 0)

    def _place_now(self, *_):
        p = self.parent
        if p is None or p.width < 10 or self.dragging:
            return
        saved = global_get(POS_KEY, None)
        if saved:
            fx, fy = saved
        else:   # como antes: a la derecha, justo bajo la franja del ensayo
            fx = (p.width - self.width - dp(14)) / p.width
            fy = (p.height - dp(56) - dp(36) - self.height * .62) / p.height
        self.pos = clamp_pos(fx, fy, p.width, p.height, self.width, dp(6))

    # ------------------------------------------------------------ toques
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or self.disabled:
            return super().on_touch_down(touch)
        touch.grab(self)
        self._t = 0.0
        self._ev = Clock.schedule_interval(self._tick, 1 / 30)
        self._grab = (touch.x - self.x, touch.y - self.y)
        return super().on_touch_down(touch)

    def _tick(self, dt):
        self._t += dt
        self.hold = min(1.0, self._t / HOLD_S)
        if self._t >= HOLD_S:
            self.dragging = True
            self._stop()
            return False

    def _stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def on_touch_move(self, touch):
        if touch.grab_current is self and self.dragging and self.parent is not None:
            p = self.parent
            gx, gy = self._grab
            self.pos = clamp_pos((touch.x - gx) / p.width, (touch.y - gy) / p.height,
                                 p.width, p.height, self.width, dp(6))
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._stop()
            if self.dragging:
                p = self.parent
                if p is not None and p.width and p.height:
                    global_set(POS_KEY, [self.x / p.width, self.y / p.height])
                self.dragging = False
                self.hold = 0
                self.state = "normal"
                return True                  # moverlo no abre las mediciones
            self.hold = 0
        return super().on_touch_up(touch)
