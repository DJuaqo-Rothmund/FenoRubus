"""
ui/pending.py
=============
Tareas pendientes de hoy en la pantalla de inicio.

* `today_tasks()`: escribir el cuaderno de campo (basta una página de hoy con algo),
  subir lo pendiente a Drive y completar el muestreo de la semana.
* `PostIt`: post-it amarillo, escrito a mano, pegado arriba a la derecha junto al logo;
  solo aparece si queda algo por hacer.
* `TasksSheet`: al tocar el post-it, el mismo post-it en grande (amarillo, con su cinta)
  con la lista a mano y un botón para resolver cada tarea. Se cierra tocando fuera.
"""
from __future__ import annotations

import datetime as _dt

from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.graphics import Color, Line, PopMatrix, PushMatrix, Rectangle, Rotate, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget
from kivymd.app import MDApp

import phenology as ph
from ui import theme
from ui.theme import c

LabelBase.register("Hand", theme.HAND_FONT)

INK = "#2B3A67"             # tinta de lápiz pasta
BROWN = "#6B4423"
RULE = "#B9CDE3"            # renglón celeste de cuaderno
MARGIN = "#E59AA9"          # línea roja del margen
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def app():
    return MDApp.get_running_app()


def note_written(db, day: str) -> bool:
    """Hay página del cuaderno de ese día con texto, fotos o escritura a mano."""
    e = db.note_for_day(day)
    return bool(e and ((e.get("text") or "").strip() or e["photos"] or (e.get("ink") or "").strip("[] ")))


def today_tasks() -> list[dict]:
    """[{key, title, short, detail, done, action, run}] (lo hecho queda tachado)."""
    a = app()
    db = a.db
    today = _dt.date.today().isoformat()
    tasks = []
    try:
        done = note_written(db, today)
        tasks.append({"key": "notebook", "title": "Escribir el cuaderno", "short": "cuaderno", "done": done,
                      "detail": "Página de hoy lista" if done else "Aún no hay página de hoy",
                      "action": "Escribir", "run": open_today_page})
    except Exception as exc:  # noqa: BLE001
        _quiet(exc, "pendientes: cuaderno")
    try:
        st = a.drive.status()
        if st["enabled"]:
            todo = st["pending"] + st["errors"]
            tasks.append({"key": "backup", "title": "Respaldar en Drive", "short": "respaldo", "done": not todo,
                          "detail": "Todo respaldado" if not todo else
                          f"{todo} archivo{'s' if todo != 1 else ''} por subir",
                          "action": "Subir", "run": backup_now})
    except Exception as exc:  # noqa: BLE001
        _quiet(exc, "pendientes: respaldo")
    try:
        units = db.pheno_units()
        if units:
            ids = {v["id"] for v in units}
            n = sum(1 for r in db.query("SELECT variety_id FROM observations WHERE week_id=? "
                                        "AND bbch_code IS NOT NULL", (a.week["id"],))
                    if r["variety_id"] in ids)
            tasks.append({"key": "sampling", "title": f"Muestreo semana {ph.week_of_year(a.week)}",
                          "short": "muestreo", "done": n >= len(units),
                          "detail": f"{n} de {len(units)} registrados", "action": "Ir", "run": a.enter_home})
    except Exception as exc:  # noqa: BLE001
        _quiet(exc, "pendientes: muestreo")
    return tasks


def open_today_page():
    a = app()
    a.open_notebook()
    a.notebook.open_day(_dt.date.today().isoformat())


def backup_now():
    a = app()
    if not a.drive.available:
        a.toast("El respaldo en Google Drive funciona en el teléfono (Android).")
        return
    a.drive.retry_errors()        # reintenta errores y sube lo pendiente (en segundo plano)
    a.toast("Subiendo lo pendiente a Google Drive…")


# --------------------------------------------------------------------------- post-it
class PostIt(ButtonBehavior, Widget):
    """Post-it amarillo con cinta, ladeado, con lo que falta escrito a mano."""
    lines = ListProperty([])
    tilt = NumericProperty(-6)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lbl = Label(font_name="Hand", font_size=sp(19), color=c("#5A3D1C"), halign="left", valign="top")
        self.add_widget(self.lbl)
        self.bind(pos=self._draw, size=self._draw, lines=self._draw, tilt=self._draw, state=self._draw)

    def _draw(self, *_):
        self.lbl.text = "Hoy falta:\n" + "\n".join(f"· {t}" for t in self.lines)
        self.lbl.size = (self.width - dp(20), self.height - dp(18))
        self.lbl.text_size = self.lbl.size
        self.lbl.pos = (self.x + dp(12), self.y + dp(6))
        self.canvas.before.clear()
        self.canvas.after.clear()
        k = .96 if self.state == "down" else 1
        with self.canvas.before:
            PushMatrix()
            Rotate(angle=self.tilt, origin=self.center)
            Color(0, 0, 0, .14)
            RoundedRectangle(pos=(self.x + dp(3), self.y - dp(4)), size=(self.width * k, self.height * k), radius=[dp(3)])
            Color(*c("#F6E3A6"))
            RoundedRectangle(pos=self.pos, size=(self.width * k, self.height * k), radius=[dp(2)])
            Color(*c("#EBD38A"))
            Rectangle(pos=(self.x, self.top - dp(4)), size=(self.width * k, dp(4)))
            Color(1, 1, 1, .62)                                  # cinta adhesiva
            Rectangle(pos=(self.center_x - dp(22), self.top - dp(9)), size=(dp(44), dp(17)))
        with self.canvas.after:
            PopMatrix()

    def wobble(self):
        """Pequeño balanceo al aparecer (como un papel recién pegado)."""
        from kivy.animation import Animation
        Animation.cancel_all(self, "tilt")
        self.tilt = 4
        (Animation(tilt=-9, d=.25, t="out_quad") + Animation(tilt=-6, d=.35, t="out_back")).start(self)


# --------------------------------------------------------------------------- hoja
class _Check(Widget):
    def __init__(self, done: bool, **kw):
        super().__init__(size_hint=(None, None), size=(dp(22), dp(22)), **kw)
        self.done = done
        self.bind(pos=self._draw)

    def _draw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(*c(BROWN))
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(4)), width=dp(1.3))
            if self.done:
                Color(*c("#2F6B4F"))
                Line(points=[self.x + dp(4), self.y + dp(11), self.x + dp(9), self.y + dp(5),
                             self.x + dp(19), self.y + dp(19)], width=dp(2), cap="round", joint="round")


class _Action(ButtonBehavior, Label):
    def __init__(self, **kw):
        super().__init__(bold=True, font_size=sp(12.5), color=(1, 1, 1, 1), size_hint=(None, None),
                         height=dp(28), **kw)
        self.texture_update()
        self.width = self.texture_size[0] + dp(24)
        self.bind(pos=self._draw, state=self._draw)

    def _draw(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*c(BROWN, .8 if self.state == "down" else 1))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])


class StickyPaper(FloatLayout):
    """El post-it en grande: papel amarillo con sombra, borde superior más oscuro y cinta."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_):
        self.canvas.before.clear()
        x, y, w, h = self.x, self.y, self.width, self.height
        with self.canvas.before:
            PushMatrix()
            Rotate(angle=-1.2, origin=self.center)          # apenas ladeado, como el chico
            Color(0, 0, 0, .16)
            RoundedRectangle(pos=(x + dp(4), y - dp(7)), size=(w, h), radius=[dp(4)])
            Color(*c("#F6E3A6"))
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(3)])
            Color(*c("#EBD38A"))
            Rectangle(pos=(x, y + h - dp(10)), size=(w, dp(10)))
            Color(*c("#EFD993"))                            # esquina levemente levantada
            RoundedRectangle(pos=(x + w - dp(34), y), size=(dp(34), dp(26)), radius=[0, 0, dp(3), dp(14)])
            Color(1, 1, 1, .62)                             # cinta adhesiva
            Rectangle(pos=(x + w / 2 - dp(48), y + h - dp(18)), size=(dp(96), dp(30)))
            PopMatrix()


class TasksSheet(ModalView):
    """Hoja de tareas pendientes con dibujos de frambueso al pie (toque fuera: se cierra)."""

    def __init__(self, tasks: list[dict], on_close=None, **kw):
        super().__init__(size_hint=(.92, None), auto_dismiss=True, background_color=(0, 0, 0, 0),
                         overlay_color=(.08, .12, .1, .45), **kw)
        from kivy.core.window import Window
        step, head = dp(44), dp(96)
        self.height = min(Window.height * .8, head + step * (max(1, len(tasks)) + 1) + dp(24))
        self.on_close = on_close
        paper = StickyPaper()
        self.add_widget(paper)
        top = lambda off: {"x": 0, "top": 1 - off / (self.height or 1)}   # noqa: E731
        d = _dt.date.today()
        ink = c("#5A3D1C")                                   # la tinta del post-it chico
        title = Label(text=f"Hoy falta · {WEEKDAYS[d.weekday()]} {d.day}", font_name="Hand", font_size=sp(30),
                      color=ink, halign="left", valign="bottom", size_hint=(1, None), height=dp(58),
                      shorten=True, pos_hint=top(head - dp(62)), padding=(dp(22), 0))
        title.bind(size=lambda w, s: setattr(w, "text_size", s))
        paper.add_widget(title)
        rows = BoxLayout(orientation="vertical", size_hint=(1, None), pos_hint=top(head),
                         padding=(dp(20), 0, dp(14), 0))
        for t in tasks:
            row = BoxLayout(size_hint_y=None, height=step, spacing=dp(10))
            row.add_widget(AnchorPad(_Check(t["done"])))
            txt = f"[s]{t['title']}[/s]" if t["done"] else t["title"]
            lbl = Label(text=txt, markup=True, font_name="Hand", font_size=sp(24),
                        color=c("#A08A5E") if t["done"] else ink, halign="left", valign="middle",
                        shorten=True, shorten_from="right")
            lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
            row.add_widget(lbl)
            if not t["done"]:
                act = _Action(text=t["action"])
                act.bind(on_release=lambda _w, t=t: self._run(t))
                row.add_widget(AnchorPad(act))
            rows.add_widget(row)
        rows.height = step * max(1, len(tasks))
        paper.add_widget(rows)
        if not tasks:
            rows.add_widget(Label(text="¡Todo al día por hoy!", font_name="Hand", font_size=sp(26), color=ink,
                                  halign="left", valign="middle", text_size=(dp(240), dp(40))))
        hint = Label(text="toca fuera para cerrar", font_name="Hand", font_size=sp(17), color=c("#A08A5E"),
                     size_hint=(1, None), height=dp(30), halign="right", valign="bottom",
                     pos_hint={"x": 0, "y": 0}, padding=(dp(18), dp(10)))
        hint.bind(size=lambda w, s: setattr(w, "text_size", s))
        paper.add_widget(hint)
        self.bind(on_dismiss=lambda *_: on_close and on_close())

    def _run(self, task):
        self.dismiss()
        Clock.schedule_once(lambda *_: task["run"](), .15)


def AnchorPad(widget):   # noqa: N802 - centra un widget de tamaño fijo en la fila
    from kivy.uix.anchorlayout import AnchorLayout
    box = AnchorLayout(size_hint_x=None, width=widget.width, anchor_y="center")
    box.add_widget(widget)
    return box


def _quiet(exc, where):
    import crashguard
    crashguard.quiet(exc, where)
