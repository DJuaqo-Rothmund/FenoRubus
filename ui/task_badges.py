"""
ui/task_badges.py
=================
Insignias flotantes de SINCRONIZAR y RESPALDO (Google Drive), al costado derecho de la
pantalla, encima de todo: así se puede seguir trabajando mientras corren.

* Aparecen solo cuando el usuario pide sincronizar o respaldar (no en lo automático).
* Anillo con el avance y el porcentaje: rojo → amarillo → verde.
* Al tocarla mientras corre: el porcentaje, en qué va y el tiempo estimado que falta.
* Al terminar quedan en «Listo» (verde) o «Nada» (azul: no había nada que sincronizar o
  respaldar), o «Error» (rojo), y NO desaparecen hasta que se tocan (muestran el detalle).

Se pueden llamar desde cualquier hilo: `start`, `update` y `finish` pasan al hilo de Kivy.
"""
from __future__ import annotations

import time

from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.floatlayout import FloatLayout
from kivymd.app import MDApp

RED, YELLOW, GREEN, BLUE = "#D64545", "#E3A919", "#2E9E50", "#2F7FD6"
KINDS = {   # tipo -> (ícono, nombre, posición vertical desde abajo en dp)
    "sync": ("sync", "Sincronización", 210),
    "backup": ("cloud-upload-outline", "Respaldo", 290),
}

KV = """
#:import c ui.theme.c
<TaskBadge>:
    size_hint: None, None
    size: dp(66), dp(66)
    canvas.before:
        Color:
            rgba: 0, 0, 0, .18
        Ellipse:
            pos: self.x + dp(2), self.y - dp(3)
            size: self.size
        Color:
            rgba: 1, 1, 1, .97
        Ellipse:
            pos: self.pos
            size: self.size
        Color:
            rgba: c(root.ring, .18)
        Line:
            circle: self.center_x, self.center_y, self.width / 2 - dp(4)
            width: dp(3.2)
        Color:
            rgba: c(root.ring)
        Line:
            circle: self.center_x, self.center_y, self.width / 2 - dp(4), 0, 360 * max(.01, root.frac)
            width: dp(3.2)
            cap: "round"
    MDIcon:
        icon: root.icon
        theme_text_color: "Custom"
        text_color: c(root.ring)
        font_size: "22sp"
        halign: "center"
        size_hint: None, None
        size: dp(26), dp(26)
        pos: root.center_x - dp(13), root.center_y - dp(4)
        canvas.before:
            PushMatrix
            Rotate:
                angle: root.angle
                origin: self.center
        canvas.after:
            PopMatrix
    Label:
        text: root.label
        bold: True
        font_size: "11.5sp"
        color: c("#22261C")
        size_hint: None, None
        size: root.width, dp(16)
        pos: root.x, root.center_y - dp(20)
"""


def remaining(started: float, frac: float, now: float | None = None, samples: list | None = None) -> str:
    """«quedan ~3 min»: lo que falta al ritmo RECIENTE (vacío al principio, cuando aún no se sabe).

    samples: [(hora, fracción)] de los últimos avances. Con ellos se mide el ritmo de los
    últimos minutos; así una pausa larga (teléfono dormido, sin señal un rato) no infla el
    cálculo, como pasaba al dividir por todo el tiempo desde que se empezó."""
    now = time.time() if now is None else now
    spent = now - started
    if not started or frac < .05 or spent < 3:
        return "calculando el tiempo restante…"
    left = spent * (1 - frac) / frac
    if samples and now - samples[-1][0] > STALL_S:
        return "sin avance hace un rato (¿sin señal?)"
    if samples and len(samples) >= 2:
        t0, f0 = samples[0]
        t1, f1 = samples[-1]
        if f1 - f0 > .004 and t1 - t0 >= 3:
            left = (t1 - t0) * (1 - f1) / (f1 - f0)
        elif len(samples) < 3:
            return "calculando el tiempo restante…"
    if left < 45:
        return "queda menos de 1 min"
    mins = round(left / 60)
    return f"quedan ~{mins} min" if mins < 60 else f"quedan ~{mins // 60} h {mins % 60:02d} min"


WINDOW_S = 180        # el ritmo se mide con los avances de los últimos 3 min
STALL_S = 150         # sin avances en este tiempo: se avisa en vez de inventar una hora


def _color(frac: float) -> str:
    return RED if frac < 1 / 3 else YELLOW if frac < 2 / 3 else GREEN


class TaskBadge(ButtonBehavior, FloatLayout):
    icon = StringProperty("sync")
    label = StringProperty("0%")
    ring = StringProperty(RED)
    frac = NumericProperty(0)
    angle = NumericProperty(0)
    state_ = StringProperty("run")      # run | done | empty | error
    text = StringProperty("")
    started = NumericProperty(0)        # time.time() al empezar (para el tiempo restante)

    def __init__(self, kind: str, **kw):
        super().__init__(**kw)
        self.kind = kind
        self.icon = KINDS[kind][0]
        self._spin = Clock.schedule_interval(self._turn, 1 / 30)

    def _turn(self, *_):
        if self.state_ == "run" and self.kind == "sync":
            self.angle = (self.angle - 8) % 360

    def on_release(self):
        app = MDApp.get_running_app()
        name = KINDS[self.kind][1]
        if self.state_ == "run":
            eta = remaining(self.started, self.frac, samples=getattr(self, "samples", None))
            app.toast(f"{name}: {int(self.frac * 100)} %" + (f" · {self.text}" if self.text else "")
                      + (f" · {eta}" if eta else ""))
            return
        if self.text:
            app.toast(f"{name}: {self.text}")
        _remove(self.kind)


_badges: dict[str, TaskBadge] = {}
_loaded = False


def _place(*_):
    for kind, b in _badges.items():
        b.pos = (Window.width - dp(78), dp(KINDS[kind][2]))


def _remove(kind: str):
    b = _badges.pop(kind, None)
    if b is not None:
        b._spin.cancel()
        if b.parent is not None:
            b.parent.remove_widget(b)


@mainthread
def start(kind: str, text: str = "") -> None:
    """Muestra (o reinicia) la insignia: el usuario pidió sincronizar o respaldar."""
    global _loaded
    if not _loaded:
        Builder.load_string(KV)
        Window.bind(size=_place)
        _loaded = True
    b = _badges.get(kind)
    if b is None:
        b = _badges[kind] = TaskBadge(kind)
        Window.add_widget(b)
    b.state_, b.frac, b.label, b.ring, b.text, b.angle = "run", 0, "0%", RED, text, 0
    b.started = time.time()
    b.samples = [(b.started, 0.0)]
    b.icon = KINDS[kind][0]
    _place()


def active(kind: str) -> bool:
    b = _badges.get(kind)
    return b is not None and b.state_ == "run"


@mainthread
def update(kind: str, frac: float, text: str = "") -> None:
    b = _badges.get(kind)
    if b is None or b.state_ != "run":
        return
    frac = max(b.frac, min(.99, float(frac)))      # no retrocede; 100 % solo al terminar
    now = time.time()
    sm = getattr(b, "samples", None) or []
    if sm and now - sm[-1][0] > STALL_S:           # hubo una pausa: el ritmo se mide desde ahora
        sm = []
    if not sm or frac > sm[-1][1]:
        sm.append((now, frac))
    b.samples = [x for x in sm if now - x[0] <= WINDOW_S][-40:] or sm[-1:]
    b.frac, b.label, b.ring = frac, f"{int(frac * 100)}%", _color(frac)
    if text:
        b.text = text


@mainthread
def finish(kind: str, state: str = "done", text: str = "") -> None:
    """state: done (Listo, verde) | empty (no había nada: azul) | error (rojo)."""
    b = _badges.get(kind)
    if b is None:
        return
    took = time.time() - b.started if b.started else 0
    if took >= 60 and state != "error":
        text = (text + " · " if text else "") + f"demoró {round(took / 60)} min"
    b.state_, b.frac, b.angle, b.text = state, 1, 0, text
    b.label, b.ring = {"done": ("Listo", GREEN), "empty": ("Nada", BLUE),
                       "error": ("Error", RED)}.get(state, ("Listo", GREEN))
    b.icon = {"done": "check-bold", "empty": "check", "error": "alert-circle-outline"}.get(state, "check")
