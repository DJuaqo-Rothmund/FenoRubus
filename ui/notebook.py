"""
ui/notebook.py
==============
Cuaderno de campo (bitácora diaria) de cada ensayo o predio.

* `NotebookScreen`: línea de tiempo (lo más reciente arriba) con una tarjeta por día:
  fecha, extracto del texto y miniaturas de las fotos. Tocar una abre la página.
* `NoteScreen`: la página del día: texto largo (se guarda solo), fotos desde la cámara o
  la galería y cambio de fecha. En pantallas anchas (tablet) texto y fotos van lado a lado.
* `AnnotateView`: dibujar a mano alzada (dedo o S-Pen, con presión si el lápiz la entrega)
  sobre una foto, con zoom de dos dedos, colores, grosores y deshacer. Al guardar se crea
  una imagen nueva con los trazos (Pillow) y la original queda en el teléfono.

Todo se guarda en la base del ensayo (tablas notebook_*) y viaja con la sincronización.
"""
from __future__ import annotations

import datetime as _dt
import math
import os

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, InstructionGroup, Line, PopMatrix, PushMatrix, Rectangle, Scale, Translate
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.modalview import ModalView
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen

import phenology as ph
from ui import theme
from ui.theme import c

BROWN = "#6B4423"        # tinta del cuaderno
OCHRE = "#C8963E"
OCHRE_SOFT = "#EEDAB8"
PAPER = "#FBF6EC"
PEN_COLORS = ["#E53935", "#FFD54F", "#FFFFFF", "#212121", "#43A047"]
PEN_WIDTHS = [("Fino", 2.5), ("Medio", 5), ("Grueso", 10)]
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def app():
    return MDApp.get_running_app()


def nice_day(day: str, weekday: bool = True) -> str:
    d = _dt.date.fromisoformat(day[:10])
    txt = f"{d.day} de {ph.MESES[d.month - 1]} de {d.year}"
    return f"{WEEKDAYS[d.weekday()].capitalize()} {txt}" if weekday else txt


def excerpt(text: str, n: int = 170) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def monday(day: str) -> str:
    """Lunes de la semana del día: las fotos van a la carpeta de esa semana en Drive (como la web)."""
    d = _dt.date.fromisoformat(day[:10])
    return (d - _dt.timedelta(days=d.weekday())).isoformat()


def notebook_db():
    """Base del ensayo/predio con el que se trabaja (el mismo del resto de la app)."""
    a = app()
    if getattr(a, "workspace", None) is None or getattr(a, "db", None) is None:
        a.open_workspace(a.workspaces.last()["id"], target=None)
    return a.db


# --------------------------------------------------------------------------- tarjetas
class NoteCard(ButtonBehavior, BoxLayout):
    """Tarjeta de un día en la línea de tiempo (fecha, extracto y miniaturas)."""
    day = StringProperty("")
    day_num = StringProperty("")
    month = StringProperty("")
    weekday = StringProperty("")
    text = StringProperty("")
    count = StringProperty("")
    thumbs = ListProperty([])

    def on_thumbs(self, *_):
        from kivymd.uix.fitimage import FitImage
        strip = self.ids.strip
        strip.clear_widgets()
        for src in self.thumbs:
            strip.add_widget(FitImage(source=src, radius=[dp(10)], size_hint=(None, None), size=(dp(56), dp(56))))


class NoteThumb(ButtonBehavior, FloatLayout):
    """Miniatura de una foto de la página (tocar: anotar; ✕: quitar)."""
    source = StringProperty("")
    annotated = BooleanProperty(False)
    photo = ObjectProperty(None, allownone=True)


# --------------------------------------------------------------------------- timeline
class NotebookScreen(MDScreen):
    ws_title = StringProperty("")
    empty = BooleanProperty(False)

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        a = app()
        db = notebook_db()
        ws = a.workspace
        from workspaces import Workspaces
        self.ws_title = f"{Workspaces.title(ws)} · {ws['code']}"
        box = self.ids.timeline
        box.clear_widgets()
        days = db.note_days()
        self.empty = not days
        for d in days:
            date = _dt.date.fromisoformat(d["day"])
            card = NoteCard(day=d["day"], day_num=str(date.day), month=ph.MESES[date.month - 1][:3].upper(),
                            weekday=f"{WEEKDAYS[date.weekday()].capitalize()} · {date.year}",
                            text=(excerpt(d["text"]) or ("Escrito a mano" if (d.get("ink") or "").strip() else "Sin texto")),
                            count=(f"{len(d['photos'])} foto{'s' if len(d['photos']) != 1 else ''}"
                                   if d["photos"] else ""))
            card.bind(on_release=lambda w: self.open_day(w.day))
            box.add_widget(card)
            for p in d["photos"][:4]:
                if os.path.exists(p["path"]):
                    a.thumb_async(p["path"], 200, lambda src, card=card: card.thumbs.append(src))

    def pick_workspace(self, caller=None):
        """Elegir de qué ensayo o predio es el cuaderno."""
        from ui.screens import pick_dialog
        from workspaces import Workspaces
        a = app()
        cur = (a.workspace or {}).get("id")
        items = [(f"{Workspaces.title(w)} · {w['code']}", "Actual" if w["id"] == cur else "",
                  lambda w=w: self._switch(w)) for w in a.workspaces.list()]
        pick_dialog("Cuaderno de campo de…", items)

    def _switch(self, ws):
        app().open_workspace(ws["id"], target=None)
        self.refresh()

    def new_today(self):
        self.open_day(_dt.date.today().isoformat())

    def open_day(self, day: str):
        a = app()
        a.note_page.load(day)
        a.go("note_page")



# --------------------------------------------------------------------------- escritura a mano
INK_COLORS = ["#1E3A8A", "#212121", "#C62828", "#2E7D32"]


# Plumas del modo lápiz: grosor en renglones, opacidad y si usa la presión del lápiz.
# Los trazos guardan "k" solo si no son de lápiz ("pl" plumón, "hl" destacador).
PENS = {
    "lapiz": {"w": .06, "a": 1.0, "pressure": True},
    "pl": {"w": .13, "a": 1.0, "pressure": False},
    "hl": {"w": .55, "a": .35, "pressure": False},
}
HL_COLORS = ["#FFEB3B", "#76FF03", "#FF4081", "#40C4FF"]


def stroke_alpha(stroke: dict) -> float:
    return PENS.get(stroke.get("k") or "lapiz", PENS["lapiz"])["a"]


class InkLayer(StencilView):
    """Escritura a mano sobre la hoja (modo lápiz). Los trazos se guardan en renglones
    (x, y desde el borde superior izquierdo del texto) y siguen al texto al desplazarlo.
    Con el lápiz activo: un dedo o el S-Pen escribe (con presión), dos dedos desplazan la
    hoja; con la goma, tocar un trazo lo borra. Con el botón del S-Pen apretado (o su
    punta de goma) también borra, solo mientras se aprieta.

    Dibujo: los trazos quedan en coordenadas de la hoja y el desplazamiento solo mueve un
    Translate (no se reconstruye nada al desplazar ni al escribir: el trazo en curso es
    una sola Line a la que se le agregan puntos)."""
    active = BooleanProperty(False)
    eraser = BooleanProperty(False)
    color = StringProperty(INK_COLORS[0])
    pen = StringProperty("lapiz")         # lapiz · pl (plumón) · hl (destacador)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.strokes: list = []
        self._cur = None
        self._cur_line = None
        self._erasing = False
        self._touches: dict = {}
        self.ti = None
        self.on_change = None
        self._built_step = None
        with self.canvas:
            PushMatrix()
            self._move = Translate(0, 0)
            self._ink = InstructionGroup()
            self._live = InstructionGroup()
            PopMatrix()
        self.bind(pos=self._place, size=self._place)

    def attach(self, ti):
        self.ti = ti
        ti.bind(scroll_y=self._place, pos=self._place, size=self._place,
                line_height=self.redraw, line_spacing=self.redraw)
        self.redraw()

    # geometría: renglones <-> pantalla
    def _step(self):
        return (self.ti.line_height + self.ti.line_spacing) if self.ti else dp(24)

    def _origin(self):
        ti = self.ti
        return ti.x + ti.padding[0], ti.top - ti.padding[1] + ti.scroll_y

    def to_lines(self, x, y):
        ox, oy = self._origin()
        st = self._step()
        return round((x - ox) / st, 3), round((oy - y) / st, 3)

    def _place(self, *_):
        """Desplazar o mover la hoja: solo cambia el Translate."""
        if self.ti is None:
            return
        if self._built_step != self._step():
            self.redraw()
            return
        self._move.xy = self._origin()

    def redraw(self, *_):
        """Reconstruye los trazos guardados (al cargar, borrar, deshacer o cambiar la letra)."""
        self._ink.clear()
        if not self.ti:
            return
        st = self._built_step = self._step()
        self._move.xy = self._origin()
        # El destacador va debajo de la tinta.
        order = [s for s in self.strokes if s.get("k") == "hl"] + \
                [s for s in self.strokes if s.get("k") != "hl"]
        for s in order:
            if not s.get("p"):
                continue
            self._ink.add(Color(*c(s["c"], stroke_alpha(s))))
            p = s["p"]
            pts = [v * st if i % 2 == 0 else -v * st for i, v in enumerate(p)]
            if len(pts) == 2:
                pts += [pts[0] + .5, pts[1]]
            self._ink.add(Line(points=pts, width=max(.8, s["w"] * st),
                               cap="square" if s.get("k") == "hl" else "round", joint="round"))

    def _live_start(self):
        st = self._step()
        s = self._cur
        self._live.clear()
        self._live.add(Color(*c(s["c"], stroke_alpha(s))))
        x, y = s["p"][0] * st, -s["p"][1] * st
        self._cur_line = Line(points=[x, y, x + .5, y], width=max(.8, s["w"] * st),
                              cap="square" if s.get("k") == "hl" else "round", joint="round")
        self._live.add(self._cur_line)

    def _live_add(self, x, y):
        st = self._step()
        pts = self._cur_line.points
        if len(self._cur["p"]) == 4:       # el segundo punto reemplaza el punto inicial doble
            pts = pts[:2]
        self._cur_line.points = pts + [x * st, -y * st]

    def _live_end(self):
        self._live.clear()
        self._cur_line = None

    def load(self, ink: str):
        import json
        try:
            self.strokes = json.loads(ink) if ink else []
        except ValueError:
            self.strokes = []
        self.redraw()

    def dumps(self) -> str:
        import json
        return json.dumps(self.strokes, separators=(",", ":")) if self.strokes else ""

    def _changed(self):
        self.redraw()
        if self.on_change:
            self.on_change()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self._changed()

    # toques
    def _stylus_erasing(self) -> bool:
        from android_bridge import stylus_erasing
        return stylus_erasing()

    def on_touch_down(self, touch):
        if not self.active or not self.collide_point(*touch.pos) or self.ti is None:
            return False
        touch.grab(self)
        self._touches[touch.uid] = touch.pos
        if len(self._touches) > 1:          # dos dedos: desplazar la hoja
            self._cur = None
            self._live_end()
            return True
        self._erasing = self.eraser or self._stylus_erasing()
        if self._erasing:
            self._erase(touch.pos)
            return True
        pen = PENS.get(self.pen, PENS["lapiz"])
        pressure = touch.pressure if pen["pressure"] and "pressure" in (touch.profile or []) else None
        k = .55 + pressure * .9 if pressure else 1.0
        x, y = self.to_lines(*touch.pos)
        self._cur = {"c": self.color, "w": round(pen["w"] * k, 3), "p": [x, y]}
        if self.pen != "lapiz":
            self._cur["k"] = self.pen
        self._live_start()
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        prev = self._touches.get(touch.uid, touch.pos)
        self._touches[touch.uid] = touch.pos
        if len(self._touches) > 1:
            n = len(self._touches)
            self._scroll((touch.pos[1] - prev[1]) / n)
        elif self._erasing:
            self._erase(touch.pos)
        elif self._cur is not None:
            x, y = self.to_lines(*touch.pos)
            px, py = self._cur["p"][-2:]
            if math.hypot(x - px, y - py) * self._step() >= 1.5:
                self._cur["p"] += [x, y]
                self._live_add(x, y)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        self._touches.pop(touch.uid, None)
        if not self._touches:
            self._erasing = False
        if self._cur is not None and not self._touches:
            self.strokes.append(self._cur)
            self._cur = None
            self._live_end()
            self._changed()
        return True

    def _scroll(self, dy):
        ti = self.ti
        bottom = max([max(s["p"][1::2]) for s in self.strokes if s["p"]] + [0]) * self._step()
        content = max(ti.minimum_height - ti.height, bottom - ti.height * .5, 0) + ti.height * .5
        ti.scroll_y = max(0, min(content, ti.scroll_y + dy))

    def _erase(self, pos):
        x, y = self.to_lines(*pos)
        keep = []
        for s in self.strokes:
            r = .35 + (s["w"] / 2 if s.get("k") == "hl" else 0)
            p = s["p"]
            if not any(abs(p[i] - x) < r and abs(p[i + 1] - y) < r for i in range(0, len(p) - 1, 2)):
                keep.append(s)
        if len(keep) != len(self.strokes):
            self.strokes = keep
            self._changed()

# --------------------------------------------------------------------------- página
class NoteScreen(MDScreen):
    pen = BooleanProperty(False)           # modo lápiz (escritura a mano)
    pen_palette = ListProperty(INK_COLORS)  # colores de la pluma elegida
    day = StringProperty("")
    title = StringProperty("")
    wide = BooleanProperty(False)
    saved_text = StringProperty("")

    def on_kv_post(self, *_):
        # Se escribe directo en la hoja, sin el cuadro de texto nativo de Android (native_input).
        ti = self.ids.text
        ti.native_edit = False
        self._pen_colors = {}
        ink = self.ids.ink
        ink.attach(ti)
        ink.on_change = self._ink_changed
        ti.bind(pos=self._rule, size=self._rule, scroll_y=self._rule, line_height=self._rule)
        self._rule()

    def _rule(self, *_):
        """Renglones de cuaderno bajo el texto (siguen al texto al desplazarlo)."""
        from kivy.graphics import InstructionGroup
        ti = self.ids.text
        group = getattr(self, "_rules", None)
        if group is None:
            group = self._rules = InstructionGroup()
            ti.canvas.before.insert(0, group)     # debajo de todo (el color no se hereda al texto)
        group.clear()
        step = ti.line_height + ti.line_spacing
        if step <= 0:
            return
        group.add(Color(*c(OCHRE, .28)))
        y = ti.top - ti.padding[1] + ti.scroll_y - step
        while y > ti.y:
            if y < ti.top:
                group.add(Rectangle(pos=(ti.x, y - dp(2)), size=(ti.width, dp(1))))
            y -= step

    def load(self, day: str):
        self.day = day[:10]
        self.entry = notebook_db().note_for_day(self.day, create=True)
        self.title = nice_day(self.day)
        self._loading = True
        self.ids.text.text = self.entry["text"]
        self._loading = False
        self.ids.ink.load(self.entry.get("ink") or "")
        self.saved_text = "Guardado"
        self._layout()
        self.refresh_photos()

    kb_pad = NumericProperty(0)           # espacio del teclado del teléfono bajo la hoja

    def on_pre_enter(self, *_):
        from android_bridge import stylus_install
        stylus_install()      # botón del S-Pen: borra mientras se aprieta
        Window.bind(size=self._layout)
        self._layout()
        self.ids.text.bind(focus=self._on_focus)

    def on_leave(self, *_):
        Window.unbind(size=self._layout)
        self.ids.text.unbind(focus=self._on_focus)
        self._kb_watch(False)
        self.save_now()
        # Lo escrito viaja enseguida a los otros equipos y su PDF queda en Drive
        # («Cuaderno de campo»), sin esperar a la próxima sincronización.
        app().run_sync()

    # La hoja se acorta sobre el teclado (así lo escrito nunca queda tapado).
    def _on_focus(self, _w, focused):
        self._kb_watch(focused)

    def _kb_watch(self, on: bool):
        ev = getattr(self, "_kb_ev", None)
        if ev:
            ev.cancel()
            self._kb_ev = None
        if on:
            self._kb_ev = Clock.schedule_interval(self._kb_poll, .25)
        else:
            self.kb_pad = 0

    def _kb_poll(self, *_):
        from android_bridge import keyboard_height
        self.kb_pad = keyboard_height()

    def _layout(self, *_):
        """Tablet u horizontal: texto y fotos lado a lado; teléfono: uno sobre otro."""
        self.wide = Window.width > dp(720)

    # ------------------------------------------------------------ texto
    def on_text(self, *_):
        if getattr(self, "_loading", False):
            return
        self.saved_text = "Escribiendo…"
        ev = getattr(self, "_save_ev", None)
        if ev:
            ev.cancel()
        self._save_ev = Clock.schedule_once(lambda *_: self.save_now(), 1.0)

    def save_now(self):
        if not getattr(self, "entry", None):
            return
        db = notebook_db()
        db.save_note_text(self.entry["id"], self.ids.text.text)
        db.save_note_ink(self.entry["id"], self.ids.ink.dumps())
        self.saved_text = "Guardado"

    # ------------------------------------------------------------ lápiz
    def set_pen(self, on: bool):
        self.pen = on
        ink = self.ids.ink
        ink.active = on
        ink.eraser = False
        if on:
            self.ids.text.focus = False

    def set_ink_color(self, col: str):
        self.ids.ink.color = col
        self.ids.ink.eraser = False
        self._pen_colors[self.ids.ink.pen] = col

    def set_pen_kind(self, kind: str):
        """Lápiz, plumón o destacador (cada uno recuerda su último color)."""
        ink = self.ids.ink
        ink.pen = kind
        ink.eraser = False
        default = HL_COLORS[0] if kind == "hl" else INK_COLORS[0]
        ink.color = self._pen_colors.get(kind, default)
        self.pen_palette = HL_COLORS if kind == "hl" else INK_COLORS

    def _ink_changed(self):
        self.on_text()

    # ------------------------------------------------------------ fotos
    def refresh_photos(self):
        a = app()
        self.entry = notebook_db().note_for_day(self.day, create=True)
        grid = self.ids.photos
        grid.clear_widgets()
        for p in self.entry["photos"]:
            th = NoteThumb(photo=p, annotated=bool(p["annotated"]))
            th.bind(on_release=lambda w: self.annotate(w.photo))
            grid.add_widget(th)
            if os.path.exists(p["path"]):
                a.thumb_async(p["path"], 360, lambda src, th=th: setattr(th, "source", src))
        self.ids.no_photos.opacity = 0 if self.entry["photos"] else 1

    def add_photos(self, source: str):
        a = app()
        from android_bridge import store_photo
        from platform_utils import data_subdir
        code = f"{a.db.code}-" if getattr(a.db, "code", "") else ""
        base = f"{ph.photo_date(self.day)}-{code}cuaderno"
        entry_id, day = self.entry["id"], self.day

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            a.toast("Guardando foto…" if len(paths) == 1 else f"Guardando {len(paths)} fotos…")

            def work():
                error = None
                try:
                    dest = data_subdir("photos", "cuaderno")
                    for tmp in paths:
                        path = store_photo(tmp, dest, base, exact=True)
                        notebook_db().add_note_photo(entry_id, path)
                        a.backup_notebook(path)
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: (self.refresh_photos(),
                                                error and a.toast(f"No se pudo guardar la foto: {error}")))

            a.workers.submit(work)

        if source == "camera":
            a.media.take_photo(done, base, exact=True)
        else:
            a.media.pick_images(done)

    def annotate(self, photo):
        if not os.path.exists(photo["path"]):
            app().toast("La foto aún no llega a este teléfono (se baja al sincronizar).")
            return
        AnnotateView(photo, on_saved=lambda *_: self.refresh_photos(), on_delete=self._delete_photo).open()

    def _delete_photo(self, photo):
        notebook_db().delete_note_photo(photo["id"])
        self.refresh_photos()
        app().toast("Foto quitada de la página (el archivo queda en el teléfono)")

    # ------------------------------------------------------------ fecha y borrar
    def pick_date(self):
        from kivymd.uix.pickers import MDDatePicker
        d = _dt.date.fromisoformat(self.day)
        picker = MDDatePicker(year=d.year, month=d.month, day=d.day, title="FECHA DE LA PÁGINA",
                              primary_color=c(BROWN), accent_color=c(PAPER), selector_color=c(OCHRE),
                              text_toolbar_color=c("#FFFFFF"), text_button_color=c(BROWN))
        picker.bind(on_save=lambda _w, value, _r: self._move(value))
        picker.open()

    def _move(self, value):
        try:
            notebook_db().move_note(self.entry["id"], value.isoformat())
        except ValueError as exc:
            app().toast(str(exc))
            return
        self.load(value.isoformat())

    def delete_page(self):
        from ui.screens import confirm

        def go():
            notebook_db().delete_note(self.entry["id"])
            self.entry = None
            app().back()

        confirm("Borrar página", f"¿Borrar la página del {nice_day(self.day, False)} con su texto y "
                                 "fotos? (los archivos de fotos quedan en el teléfono)", [("Borrar", go)])


# --------------------------------------------------------------------------- dibujo
class DrawingCanvas(Widget):
    """Foto ajustada al área con trazos encima. Un dedo (o el S-Pen) dibuja; dos dedos
    acercan y mueven. Los trazos se guardan en coordenadas de la imagen (píxeles), así
    se ven igual con cualquier zoom y se pueden pasar tal cual a Pillow."""
    color = StringProperty(PEN_COLORS[0])
    width_px = NumericProperty(5)              # grosor del lápiz en pantalla (dp)

    def __init__(self, texture, img_size, **kw):
        super().__init__(**kw)
        self.texture = texture
        self.iw, self.ih = img_size
        self.strokes: list = []                # [{"color", "width" (px de imagen), "pts": [x, y, …]}]
        self._current = None
        self._touches: dict = {}
        self._pinch = None
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.bind(pos=self.redraw, size=self.redraw)

    # ----------------------------------------------------------- geometría
    def _fit(self) -> float:
        return min(self.width / self.iw, self.height / self.ih) if self.iw and self.ih else 1.0

    def _scale(self) -> float:
        return self._fit() * self.zoom          # px de pantalla por px de imagen

    def _origin(self):
        s = self._scale()
        return (self.center_x - self.iw * s / 2 + self.pan[0], self.center_y - self.ih * s / 2 + self.pan[1])

    def to_image(self, x, y):
        ox, oy = self._origin()
        s = self._scale()
        return (x - ox) / s, self.ih - (y - oy) / s      # y de imagen crece hacia abajo

    def redraw(self, *_):
        self.canvas.clear()
        ox, oy = self._origin()
        s = self._scale()
        with self.canvas:
            Color(.12, .1, .08, 1)
            Rectangle(pos=self.pos, size=self.size)
            Color(1, 1, 1, 1)
            Rectangle(texture=self.texture, pos=(ox, oy), size=(self.iw * s, self.ih * s))
            PushMatrix()
            Translate(ox, oy + self.ih * s)
            Scale(s, -s, 1)                      # coordenadas de imagen (y hacia abajo)
            for st in self.strokes + ([self._current] if self._current else []):
                Color(*c(st["color"]))
                pts = st["pts"]
                if len(pts) == 2:
                    pts = pts + [pts[0] + .01, pts[1]]
                Line(points=pts, width=max(.6, st["width"]), cap="round", joint="round")
            PopMatrix()

    # ----------------------------------------------------------- toques
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if touch.is_mouse_scrolling:
            self._zoom_at(1.15 if touch.button == "scrolldown" else 1 / 1.15, touch.pos)
            return True
        touch.grab(self)
        self._touches[touch.uid] = touch.pos
        if len(self._touches) == 1:
            pressure = touch.pressure if "pressure" in (touch.profile or []) else None
            k = .5 + pressure if pressure else 1.0      # S-Pen: más presión, trazo más grueso
            x, y = self.to_image(*touch.pos)
            self._current = {"color": self.color, "width": dp(self.width_px) * k / self._scale(), "pts": [x, y]}
        else:                                      # segundo dedo: es zoom, no dibujo
            self._current = None
            (x0, y0), (x1, y1) = list(self._touches.values())[:2]
            self._pinch = (math.hypot(x1 - x0, y1 - y0) or 1, ((x0 + x1) / 2, (y0 + y1) / 2))
        self.redraw()
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self or touch.uid not in self._touches:
            return False
        self._touches[touch.uid] = touch.pos
        if len(self._touches) >= 2 and self._pinch:
            (x0, y0), (x1, y1) = list(self._touches.values())[:2]
            d = math.hypot(x1 - x0, y1 - y0) or 1
            mid = ((x0 + x1) / 2, (y0 + y1) / 2)
            d0, mid0 = self._pinch
            self._zoom_at(d / d0, mid)
            self.pan[0] += mid[0] - mid0[0]
            self.pan[1] += mid[1] - mid0[1]
            self._pinch = (d, mid)
            self.redraw()
        elif self._current is not None:
            x, y = self.to_image(*touch.pos)
            px, py = self._current["pts"][-2:]
            if math.hypot(x - px, y - py) * self._scale() >= 1.5:
                self._current["pts"] += [x, y]
                self.redraw()
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        self._touches.pop(touch.uid, None)
        if self._current is not None and not self._touches:
            self.strokes.append(self._current)
            self._current = None
            self.redraw()
        if len(self._touches) < 2:
            self._pinch = None
        return True

    def _zoom_at(self, factor, pos):
        new = max(1.0, min(8.0, self.zoom * factor))
        k = new / self.zoom
        self.pan[0] = (pos[0] - self.center_x) - (pos[0] - self.center_x - self.pan[0]) * k
        self.pan[1] = (pos[1] - self.center_y) - (pos[1] - self.center_y - self.pan[1]) * k
        self.zoom = new
        self.redraw()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self.redraw()

    def clear(self):
        self.strokes = []
        self.redraw()

    def reset_view(self):
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.redraw()


def burn_strokes(src: str, dest: str, strokes: list) -> str:
    """Pinta los trazos (coordenadas de imagen) sobre la foto y la guarda como JPEG liviano."""
    from PIL import Image, ImageDraw, ImageOps
    from photo_optimizer import save_jpeg
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    d = ImageDraw.Draw(img)
    for st in strokes:
        col = tuple(int(v * 255) for v in c(st["color"])[:3])
        w = max(1, int(round(st["width"] * 2)))
        pts = list(zip(st["pts"][0::2], st["pts"][1::2]))
        if len(pts) > 1:
            d.line(pts, fill=col, width=w, joint="curve")
        r = w / 2
        for x, y in (pts[0], pts[-1]) if len(pts) > 1 else pts:
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    save_jpeg(img, dest)
    return dest


def annotated_name(path: str) -> str:
    """«…-cuaderno.jpg» -> «…-cuaderno-a1.jpg», «-a2», … (nombre nuevo: el otro equipo lo baja)."""
    stem, ext = os.path.splitext(path)
    import re
    m = re.match(r"^(.*)-a(\d+)$", stem)
    base, n = (m.group(1), int(m.group(2)) + 1) if m else (stem, 1)
    while os.path.exists(f"{base}-a{n}{ext or '.jpg'}"):
        n += 1
    return f"{base}-a{n}{ext or '.jpg'}"


class AnnotateView(ModalView):
    """Foto a pantalla completa con lápiz: colores, grosores, deshacer, borrar y guardar."""

    def __init__(self, photo: dict, on_saved=None, on_delete=None, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background_color=(0, 0, 0, .92), **kw)
        from kivy.core.image import Image as CoreImage
        from kivy.factory import Factory
        from kivymd.uix.button import MDIconButton
        from kivymd.uix.label import MDLabel
        from ui.screens import PillButton
        self.photo, self.on_saved, self.on_delete = photo, on_saved, on_delete
        img = CoreImage(photo["path"])
        from PIL import Image, ImageOps
        with Image.open(photo["path"]) as im:
            self._size = ImageOps.exif_transpose(im).size
        root = BoxLayout(orientation="vertical")
        head = BoxLayout(size_hint_y=None, height=dp(52), padding=(dp(6), 0), spacing=dp(4))
        head.add_widget(MDIconButton(icon="close", theme_icon_color="Custom", icon_color=(1, 1, 1, 1),
                                     on_release=lambda *_: self.dismiss()))
        head.add_widget(MDLabel(text="Dibujar", bold=True, theme_text_color="Custom",
                                text_color=(1, 1, 1, 1)))
        for icon, fn in (("undo-variant", lambda *_: self.canvas_w.undo()),
                         ("eraser", lambda *_: self.canvas_w.clear()),
                         ("fit-to-screen-outline", lambda *_: self.canvas_w.reset_view()),
                         ("trash-can-outline", lambda *_: self._delete())):
            head.add_widget(MDIconButton(icon=icon, theme_icon_color="Custom", icon_color=(1, 1, 1, 1),
                                         on_release=fn))
        root.add_widget(head)
        self.canvas_w = DrawingCanvas(img.texture, self._size)
        root.add_widget(self.canvas_w)
        tools = BoxLayout(size_hint_y=None, height=dp(58), padding=(dp(10), dp(8)), spacing=dp(8))
        self._swatches = []
        for col in PEN_COLORS:
            sw = Factory.PenSwatch(swatch=c(col))
            sw.bind(on_release=lambda w, col=col: self._color(col))
            self._swatches.append((col, sw))
            tools.add_widget(sw)
        tools.add_widget(MDLabel(text="Un dedo o el lápiz dibuja · dos dedos acercan", font_style="Caption",
                                 theme_text_color="Custom", text_color=(1, 1, 1, .7)))
        root.add_widget(tools)
        save = BoxLayout(size_hint_y=None, height=dp(60), padding=(dp(10), dp(6)), spacing=dp(8))
        self._widths = []
        for label, wv in PEN_WIDTHS:
            b = PillButton(text=label, font_size="13sp", size_hint=(None, None), height=dp(38), width=dp(66),
                           bg_on=c(OCHRE), fg_on=c("#FFFFFF"), bg_off=c("#FFFFFF", .15), fg_off=c("#FFFFFF"))
            b.bind(on_release=lambda w, wv=wv: self._width(wv))
            self._widths.append((wv, b))
            save.add_widget(b)
        save.add_widget(Widget())
        btn = PillButton(text="Guardar", size_hint=(None, None), width=dp(100), height=dp(44),
                         bg_off=c(BROWN), fg_off=c("#FFFFFF"))
        btn.bind(on_release=lambda *_: self._save())
        save.add_widget(btn)
        root.add_widget(save)
        self.add_widget(root)
        self._color(PEN_COLORS[0])
        self._width(PEN_WIDTHS[1][1])
        from android_bridge import allow_rotation
        allow_rotation(True)                 # se puede girar el teléfono para dibujar
        self.bind(on_dismiss=lambda *_: allow_rotation(False))

    def _color(self, col):
        self.canvas_w.color = col
        for k, sw in self._swatches:
            sw.selected = k == col

    def _width(self, wv):
        self.canvas_w.width_px = wv
        for k, b in self._widths:
            b.selected = k == wv

    def _delete(self):
        from ui.screens import confirm

        def go():
            self.dismiss()
            if self.on_delete:
                self.on_delete(self.photo)

        confirm("Quitar foto", "¿Quitar esta foto de la página?", [("Quitar", go)])

    def _save(self):
        a = app()
        strokes = list(self.canvas_w.strokes)
        if not strokes:
            self.dismiss()
            return
        src = self.photo["path"]
        dest = annotated_name(src)
        photo_id, day = self.photo["id"], None
        try:
            burn_strokes(src, dest, strokes)
            db = notebook_db()
            db.set_note_photo(photo_id, dest, True)
            row = db.query_one("SELECT e.day FROM notebook_photos p JOIN notebook_entries e ON e.id = p.entry_id "
                               "WHERE p.id=?", (photo_id,))
            day = row["day"] if row else _dt.date.today().isoformat()
            a.backup_notebook(dest)
        except Exception as exc:  # noqa: BLE001
            a.toast(f"No se pudo guardar el dibujo: {exc}")
            return
        a.toast("Foto con dibujos guardada (la original queda en el teléfono)")
        self.dismiss()
        if self.on_saved:
            self.on_saved(dest)


class PenSwatch(ButtonBehavior, Widget):
    swatch = ListProperty([1, 0, 0, 1])
    ring = ListProperty([1, 1, 1, 1])
    selected = BooleanProperty(False)


def register():
    """Registra las clases para las reglas KV (se llama al cargar la app)."""
    from kivy.factory import Factory
    for cls in (NoteCard, NoteThumb, NotebookScreen, NoteScreen, PenSwatch, InkLayer):
        Factory.register(cls.__name__, cls=cls)


register()
_ = (sp,)   # sp se usa en las reglas KV de este módulo
