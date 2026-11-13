"""
ui/idle_anim.py
===============
Animación «decorativa» que ahorra batería: corre a 30 cuadros por segundo (no 60) y se
detiene sola tras IDLE_S segundos sin tocar la pantalla; el siguiente toque la reanuda.
Sin animación Kivy no redibuja nada y el teléfono queda en reposo.

    loop = IdleLoop(self._float)   # fn(t): t = segundos desde start()
    loop.start()                   # al entrar a la pantalla
    loop.stop()                    # al salir
"""
from __future__ import annotations

import time

from kivy.clock import Clock
from kivy.core.window import Window

FPS = 30
IDLE_S = 20.0


class IdleLoop:
    def __init__(self, fn, fps: int = FPS, idle_s: float = IDLE_S):
        self.fn, self.fps, self.idle_s = fn, fps, idle_s
        self._ev = None
        self._t0 = 0.0
        self._last_touch = 0.0
        self._on = False

    @property
    def running(self) -> bool:
        return self._ev is not None

    def start(self) -> None:
        self._on = True
        self._t0 = time.monotonic()
        self._last_touch = self._t0
        Window.bind(on_touch_down=self._touched)
        self._run()

    def stop(self) -> None:
        self._on = False
        Window.unbind(on_touch_down=self._touched)
        self._halt()

    def _run(self) -> None:
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 1 / self.fps)

    def _halt(self) -> None:
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def _touched(self, *_):
        self._last_touch = time.monotonic()
        if self._on:
            self._run()
        return False                       # el toque sigue su curso normal

    def _tick(self, _dt):
        now = time.monotonic()
        self.fn(now - self._t0)
        if now - self._last_touch > self.idle_s:
            self._halt()                   # quieto: deja la última posición dibujada
