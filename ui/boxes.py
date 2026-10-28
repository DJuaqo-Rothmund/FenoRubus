"""
ui/boxes.py
===========
IA+ (botón junto al candado del Entrenador de IA): marcar con cajas las yemas, brotes,
laterales, botones, flores y frutos en las fotos de detalle de todos los ensayos y predios,
para entrenar el detector. Usa el mismo archivo de Drive que la web («Entrenar IA»), así se
puede marcar en el teléfono o en el PC (ver training_labels.py).

Pantalla casi independiente del resto de la app, para que abra rápido:
* las marcas se leen del archivo local al instante y se suman con Drive en segundo plano
  (también al abrir la app, apenas se sabe la cuenta: `preload`);
* las fotos que aún no están en el teléfono se bajan directo de Drive desde aquí
  (`fetch_photos`), sin esperar la sincronización general;
* miniaturas livianas (dibujadas en el canvas, sin widgets por texto) y creadas por tandas.

* `BoxEditor`: la foto a pantalla completa. Un dedo crea una caja (o mueve la que toca;
  las esquinas de la elegida la ajustan), dos dedos acercan y mueven.
"""
from __future__ import annotations

import math
import os
import threading

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Rectangle
from kivy.graphics.texture import Texture
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen

from training_labels import CLASSES, COLORS, GOAL, NAMES, LabelStore, detail_photos, is_marked
from ui.theme import c

PAGE = 60                     # miniaturas por tanda («Ver más» agrega otras tantas)
CHUNK = 12                    # miniaturas creadas por cuadro (la lista aparece de inmediato)
_store: LabelStore | None = None


def app():
    return MDApp.get_running_app()


def store() -> LabelStore:
    global _store
    if _store is None:
        from platform_utils import get_data_dir
        _store = LabelStore(get_data_dir())
    return _store


def drive_ready() -> bool:
    a = app()
    return bool(a.db.get_setting("drive_enabled", False) and a.drive.available)


def sync_now(done=None, quiet=True):
    """Suma las marcas de Drive (PC u otro teléfono) y sube las de aquí, en segundo plano.
    done(llegaron) se llama al terminar (en el hilo de la interfaz)."""
    a = app()
    if not drive_ready():
        if not quiet:
            a.toast("Conecte Google Drive para compartir las marcas con el PC.")
        return
    if getattr(a, "_boxes_syncing", False):
        return
    a._boxes_syncing = True

    def work():
        msg, got = None, 0
        try:
            got = store().sync(a.sync)
            msg = f"Marcas al día ({got} foto(s) nuevas desde Drive)" if got else "Marcas al día con Drive"
        except Exception as exc:  # noqa: BLE001
            msg = f"No se pudieron sincronizar las marcas: {exc}"
        a._boxes_syncing = False

        def end(*_):
            if not quiet or "No se pudieron" in msg:
                a.toast(msg)
            if done:
                done(got)
        Clock.schedule_once(end)

    threading.Thread(target=work, daemon=True).start()


def preload():
    """Al abrir la app (con la cuenta de Google ya conocida): marcas de Drive a la memoria
    local, para que IA+ abra al día sin esperar."""
    store()
    sync_now()


def fetch_photos(items: list, progress=None, done=None):
    """Baja de Drive las fotos de la lista que no están en el teléfono (de a varias a la
    vez), sin esperar la sincronización general. progress(bajadas, total); done(bajadas,
    no_encontradas)."""
    a = app()
    items = [p for p in items if not os.path.exists(p["path"])]
    if not items:
        if done:
            done(0, 0)
        return
    if not drive_ready():
        a.toast("Conecte Google Drive para bajar las fotos.")
        return

    def work():
        got, missing = 0, 0
        try:
            sync = a.sync
            ids = sync._find(sorted({p["name"] for p in items}))
            dbs = {ws["code"]: a.open_db(ws) for ws in a.workspaces.list()}
            todo = [(p, ids[p["name"]]) for p in items if p["name"] in ids]
            missing = len(items) - len(todo)
            for i in range(0, len(todo), 8):
                chunk = todo[i:i + 8]
                datas = sync._parallel(lambda t: sync._get(t[1]), chunk)
                for (p, fid), data in zip(chunk, datas):
                    db = dbs.get(p["code"])
                    if db is not None:
                        sync._store(db, p["path"], fid, data)
                    else:
                        os.makedirs(os.path.dirname(p["path"]), exist_ok=True)
                        with open(p["path"], "wb") as f:
                            f.write(data)
                    p["exists"] = True
                    got += 1
                if progress:
                    Clock.schedule_once(lambda *_, g=got, n=len(todo): progress(g, n))
        except Exception as exc:  # noqa: BLE001
            Clock.schedule_once(lambda *_: a.toast(f"No se pudieron bajar las fotos: {exc}"))
        if done:
            Clock.schedule_once(lambda *_: done(got, missing))

    threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------------------------- lista
_TEXT: dict = {}


def text_texture(text: str, size: float = 11, bold: bool = True):
    """Textura de un texto corto (se guarda: códigos y cantidades se repiten mucho)."""
    key = (text, size, bold)
    tex = _TEXT.get(key)
    if tex is None:
        lab = CoreLabel(text=text, font_size=sp(size), bold=bold, color=(1, 1, 1, 1))
        lab.refresh()
        tex = _TEXT[key] = lab.texture
    return tex


class BoxThumb(ButtonBehavior, Widget):
    """Miniatura liviana: todo en el canvas (foto recortada, código, cantidad y variedad)."""

    def __init__(self, photo: dict, **kw):
        super().__init__(size_hint_y=None, height=dp(112), **kw)
        self.photo = photo
        self._tex = None
        with self.canvas:
            Color(*c("#1F2A5C"))
            self._bg = Rectangle()
            self._img_col = Color(1, 1, 1, 0)
            self._img = Rectangle()
            Color(0, 0, 0, .35)
            self._bar_top = Rectangle()
            self._bar_bottom = Rectangle()
            Color(1, 1, 1, 1)
            self._code = Rectangle()
            self._count = Rectangle()
            self._variety = Rectangle()
            self._cloud = Rectangle()
            self._mark_col = Color(*c("#7CF2B0", 0))
            self._mark = Line(width=dp(1.4))
        self.update_marks()
        self.bind(pos=self._place, size=self._place)

    def update_marks(self):
        rec = store().get(self.photo["name"])
        n = len((rec or {}).get("boxes") or [])
        marked = is_marked(rec)
        self._mark_col.a = 1 if marked else 0
        self._set_text(self._code, self.photo["code"])
        self._set_text(self._count, (str(n) if n else "vacía") if marked else "")
        self._set_text(self._variety, (self.photo["variety"] or "")[:22], bold=False)
        self._set_text(self._cloud, "" if self.photo["exists"] else "En Drive", bold=False, size=12)
        self._place()

    def _set_text(self, rect, text, bold=True, size=11):
        tex = text_texture(text, size, bold) if text else None
        rect.texture = tex
        rect.size = tex.size if tex else (0, 0)

    def _place(self, *_):
        x, y, w, h = self.x, self.y, self.width, self.height
        self._bg.pos, self._bg.size = (x, y), (w, h)
        self._img.pos, self._img.size = (x, y), (w, h)
        self._fit_image()
        bh = dp(22)
        self._bar_top.pos, self._bar_top.size = (x, y + h - bh), (w, bh)
        self._bar_bottom.pos, self._bar_bottom.size = (x, y), (w, bh)
        self._code.pos = (x + dp(6), y + h - bh + (bh - self._code.size[1]) / 2)
        self._count.pos = (x + w - dp(6) - self._count.size[0], y + h - bh + (bh - self._count.size[1]) / 2)
        self._variety.pos = (x + dp(6), y + (bh - self._variety.size[1]) / 2)
        self._cloud.pos = (x + (w - self._cloud.size[0]) / 2, y + (h - self._cloud.size[1]) / 2)
        self._mark.rectangle = (x + 1, y + 1, w - 2, h - 2)

    def _fit_image(self):
        """Recorte tipo «cover» (una región de la textura; sin widget Image)."""
        tex = self._tex
        if tex is None or not self.width or not self.height:
            return
        tw, th = tex.size
        k = max(self.width / tw, self.height / th)
        cw, ch = min(tw, self.width / k), min(th, self.height / k)
        self._img.texture = tex.get_region((tw - cw) / 2, (th - ch) / 2, cw, ch)

    def load(self):
        if self.photo["exists"]:
            app().thumb_async(self.photo["path"], 240, self._set)

    def _set(self, src):
        from kivy.core.image import Image as CoreImage
        try:
            self._tex = CoreImage(src).texture
        except Exception:  # noqa: BLE001
            return
        self._img_col.a = 1
        self._fit_image()


KV = """
#:import c ui.theme.c
<BoxesScreen>:
    md_bg_color: c("#0B1630")
    MDBoxLayout:
        orientation: "vertical"
        MindTopBar:
            title: "IA+ · Cajas"
            left_action_items: [["arrow-left", lambda x: app.back()]]
            right_action_items: [["cloud-sync-outline", lambda x: root.sync(quiet=False), "Sincronizar marcas"]]
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                id: body
                orientation: "vertical"
                size_hint_y: None
                height: self.minimum_height
                padding: dp(14), dp(8), dp(14), dp(24)
                spacing: dp(10)
                BoxLayout:
                    id: head
                    orientation: "vertical"
                    size_hint_y: None
                    height: self.minimum_height
                GridLayout:
                    id: grid
                    cols: 3
                    spacing: dp(6)
                    size_hint_y: None
                    height: self.minimum_height
                BoxLayout:
                    id: foot
                    orientation: "vertical"
                    size_hint_y: None
                    height: self.minimum_height
"""


class BoxesScreen(MDScreen):
    """IA+: avance, filtros y miniaturas. Abre con lo local y se pone al día en segundo plano."""
    filter = "todo"
    ws = ""               # código del ensayo/predio elegido («» = todos)
    shown = PAGE

    def on_pre_enter(self, *_):
        self.refresh()
        self.sync()

    def sync(self, quiet: bool = True):
        sync_now(lambda got: self.refresh() if got else self._update_marks(), quiet=quiet)

    # ------------------------------------------------------------ datos
    def refresh(self):
        self.photos = detail_photos(app().all_dbs())
        self._header()
        self._grid()

    def _visible(self):
        st = store()
        return [p for p in self.photos if (not self.ws or p["code"] == self.ws) and (
                self.filter == "todo" or (self.filter == "con") == is_marked(st.get(p["name"])))]

    def _header(self):
        from kivy.factory import Factory
        a = app()
        head = self.ids.head
        head.clear_widgets()
        st = store()
        done = [p for p in self.photos if is_marked(st.get(p["name"]))]
        card = Factory.MindCard()
        card.add_widget(Factory.MindSection(text="CAJAS PARA EL DETECTOR · TODOS LOS ENSAYOS"))
        card.add_widget(Factory.MindText(text=f"[b]{len(done)}[/b] fotos marcadas de {len(self.photos)} · meta {GOAL}",
                                         markup=True))
        bar = Widget(size_hint_y=None, height=dp(6))
        k = min(1.0, len(done) / GOAL)
        with bar.canvas:
            Color(1, 1, 1, .1)
            back = Rectangle()
            Color(*c("#7CF2B0"))
            front = Rectangle()

        def place(*_):
            back.pos, back.size = bar.pos, bar.size
            front.pos, front.size = bar.pos, (bar.width * k, bar.height)
        bar.bind(pos=place, size=place)
        card.add_widget(bar)
        tot = st.totals()
        card.add_widget(Factory.MindMuted(
            text="   ".join(f"[color={col}][b]•[/b][/color] {name} {tot.get(key, 0)}" for key, name, col in CLASSES),
            markup=True))
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        for key, label in (("todo", "Todas"), ("sin", "Sin marcar"), ("con", "Marcadas")):
            b = Factory.MindSeg(text=label, selected=self.filter == key)
            b.bind(on_release=lambda _w, key=key: self._filter(key))
            row.add_widget(b)
        card.add_widget(row)
        card.add_widget(Factory.MindSection(text="FOTOS DE DETALLE POR ENSAYO O PREDIO"))
        sv = ScrollView(size_hint_y=None, height=dp(44), do_scroll_y=False, bar_width=0)
        chips = BoxLayout(size_hint_x=None, spacing=dp(6), padding=(0, dp(2)))
        chips.bind(minimum_width=chips.setter("width"))
        counts = {}
        for p in self.photos:
            counts.setdefault(p["code"], [0, 0])
            counts[p["code"]][0] += 1
            counts[p["code"]][1] += 1 if p["exists"] else 0
        entries = [("", f"Todos ({len(self.photos)})")]
        for w in a.workspaces.list():
            n, here = counts.get(w["code"], [0, 0])
            entries.append((w["code"], f"{w['code']} ({n})" + (f" · {here} aquí" if here < n else "")))
        for code, label in entries:
            b = Factory.MindSeg(text=label, selected=self.ws == code, size_hint_x=None)
            b.width = max(dp(70), len(label) * dp(8) + dp(24))
            b.bind(on_release=lambda _w, code=code: self._ws(code))
            chips.add_widget(b)
        sv.add_widget(chips)
        card.add_widget(sv)
        missing = [p for p in self._visible() if not p["exists"]]
        if missing:
            self._dl = Factory.MindGhost(icon="cloud-download-outline",
                                         text=f"Bajar de Drive {len(missing)} foto(s) de este filtro")
            self._dl.bind(on_release=lambda *_: self._download(missing))
            card.add_widget(self._dl)
        head.add_widget(card)

    def _grid(self):
        grid, foot = self.ids.grid, self.ids.foot
        ev = getattr(self, "_chunk_ev", None)
        if ev:
            ev.cancel()
        grid.clear_widgets()
        foot.clear_widgets()
        self.list = shown = self._visible()
        self._thumbs = []
        todo = list(enumerate(shown[:self.shown]))

        def add_chunk(*_):
            for i, p in todo[:CHUNK]:
                t = BoxThumb(p)
                t.bind(on_release=lambda _w, i=i: self.open(i))
                grid.add_widget(t)
                self._thumbs.append(t)
                t.load()
            del todo[:CHUNK]
            self._chunk_ev = Clock.schedule_once(add_chunk, 0) if todo else None
        add_chunk()
        from kivy.factory import Factory
        if not shown:
            foot.add_widget(Factory.MindMuted(text="No hay fotos de detalle en este filtro." if self.photos
                                              else "Aún no hay fotos de detalle en los ensayos y predios."))
        elif len(shown) > self.shown:
            more = Factory.MindGhost(icon="chevron-down", text=f"Ver más ({len(shown) - self.shown})")
            more.bind(on_release=lambda *_: self._more())
            foot.add_widget(more)

    def _update_marks(self):
        """Tras guardar o sincronizar sin novedades: solo los bordes y el avance."""
        for t in getattr(self, "_thumbs", []):
            t.update_marks()
        self._header()

    # ------------------------------------------------------------ acciones
    def _filter(self, key):
        self.filter, self.shown = key, PAGE
        self._header()
        self._grid()

    def _ws(self, code):
        self.ws, self.shown = code, PAGE
        self._header()
        self._grid()

    def _more(self):
        self.shown += PAGE
        self._grid()

    def _download(self, items):
        dl = getattr(self, "_dl", None)
        if dl is not None:
            dl.disabled = True
            dl.text = "Bajando fotos de Drive…"

        def progress(got, total):
            if dl is not None:
                dl.text = f"Bajando fotos de Drive… {got} de {total}"

        def done(got, missing):
            app().toast(f"{got} foto(s) bajadas" + (f" · {missing} aún no están en Drive" if missing else ""))
            self.refresh()
        fetch_photos(items, progress, done)

    def open(self, i):
        BoxEditor(self.list, i, on_close=lambda: (self._update_marks(), sync_now())).open()


Builder.load_string(KV)


def open_screen():
    """Botón «IA+» del Entrenador de IA."""
    a = app()
    if not a.sm.has_screen("boxes"):
        a.sm.add_widget(BoxesScreen(name="boxes"))
    a.go("boxes")


# --------------------------------------------------------------------------- editor
def load_texture(path: str, max_side: int = 1800):
    """Textura de la foto ya girada según su EXIF (como la ve el navegador) y su tamaño real."""
    from PIL import Image as PILImage, ImageOps
    with PILImage.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        full = im.size
        k = min(1.0, max_side / max(full))
        if k < 1:
            im = im.resize((int(im.width * k), int(im.height * k)), PILImage.BILINEAR)
        tex = Texture.create(size=im.size, colorfmt="rgb")
        tex.blit_buffer(im.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
        tex.flip_vertical()
    return tex, full


_label_cache: dict = {}


def class_label(key: str):
    if key not in _label_cache:
        lb = CoreLabel(text=NAMES.get(key, key), font_size=sp(11), bold=True, color=(1, 1, 1, 1))
        lb.refresh()
        _label_cache[key] = lb.texture
    return _label_cache[key]


class BoxCanvas(StencilView):
    """La foto con sus cajas (coordenadas 0–1, y hacia abajo como en la web)."""

    def __init__(self, editor, **kw):
        super().__init__(**kw)
        self.ed = editor
        self.tex = None
        self.iw = self.ih = 1
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.touches: dict = {}
        self.drag = None
        self.bind(pos=self.redraw, size=self.redraw)

    def set_image(self, tex, size):
        self.tex = tex
        self.iw, self.ih = size
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.redraw()

    # geometría
    def scale(self):
        return min(self.width / self.iw, self.height / self.ih) * .98 * self.zoom

    def origin(self):
        s = self.scale()
        return (self.center_x - self.iw * s / 2 + self.pan[0], self.center_y - self.ih * s / 2 + self.pan[1])

    def to_norm(self, x, y):
        ox, oy = self.origin()
        s = self.scale()
        return (x - ox) / (self.iw * s), 1 - (y - oy) / (self.ih * s)

    def to_scr(self, nx, ny):
        ox, oy = self.origin()
        s = self.scale()
        return ox + nx * self.iw * s, oy + (1 - ny) * self.ih * s

    def box_rect(self, b):
        x0, y1 = self.to_scr(b["x"], b["y"])
        x1, y0 = self.to_scr(b["x"] + b["w"], b["y"] + b["h"])
        return x0, y0, x1, y1

    def redraw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(*c("#15130F"))
            Rectangle(pos=self.pos, size=self.size)
            if not self.tex:
                return
            ox, oy = self.origin()
            s = self.scale()
            Color(1, 1, 1, 1)
            Rectangle(texture=self.tex, pos=(ox, oy), size=(self.iw * s, self.ih * s))
            boxes = list(enumerate(self.ed.rec["boxes"]))
            d = self.drag
            if d and d.get("mode") == "new" and d.get("x1") is not None:
                boxes.append((-1, self.new_box(d)))
            for i, b in boxes:
                x0, y0, x1, y1 = self.box_rect(b)
                r, g, bb, _ = c(COLORS.get(b["c"], "#FFFFFF"))
                Color(r, g, bb, .16)
                Rectangle(pos=(x0, y0), size=(x1 - x0, y1 - y0))
                Color(r, g, bb, 1)
                Line(rectangle=(x0, y0, x1 - x0, y1 - y0), width=dp(1.8 if i == self.ed.sel else 1.1))
                tex = class_label(b["c"])
                Rectangle(pos=(x0, y1), size=(tex.width + dp(8), tex.height + dp(2)))
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, pos=(x0 + dp(4), y1 + dp(1)), size=tex.size)
                if i == self.ed.sel:
                    for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                        Rectangle(pos=(cx - dp(6), cy - dp(6)), size=(dp(12), dp(12)))

    @staticmethod
    def new_box(d):
        cl = lambda v: max(0.0, min(1.0, v))   # noqa: E731
        x0, x1 = sorted((cl(d["x0"]), cl(d["x1"])))
        y0, y1 = sorted((cl(d["y0"]), cl(d["y1"])))
        return {"c": d["c"], "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}

    def hit(self, x, y):
        """(índice de la caja bajo el dedo — la más chica —, esquina de la elegida o None)."""
        best, best_a, corner = None, float("inf"), None
        tol = dp(18)
        for i, b in enumerate(self.ed.rec["boxes"]):
            x0, y0, x1, y1 = self.box_rect(b)
            if i == self.ed.sel:
                for cx, cy, name in ((x0, y1, "nw"), (x1, y1, "ne"), (x0, y0, "sw"), (x1, y0, "se")):
                    if abs(x - cx) < tol and abs(y - cy) < tol:
                        return i, name
            a = (x1 - x0) * (y1 - y0)
            if x0 <= x <= x1 and y0 <= y <= y1 and a < best_a:
                best, best_a = i, a
        return best, corner

    # toques
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or not self.tex:
            return False
        if touch.is_mouse_scrolling:
            self.zoom_at(1.15 if touch.button == "scrolldown" else 1 / 1.15, touch.pos)
            return True
        touch.grab(self)
        self.touches[touch.uid] = touch.pos
        if len(self.touches) == 2:          # dos dedos: acercar y mover (se anula lo empezado)
            if self.drag and self.drag.get("b0") is not None:
                self.ed.rec["boxes"][self.ed.sel].update(self.drag["b0"])
            (xa, ya), (xb, yb) = list(self.touches.values())[:2]
            self.drag = {"mode": "pinch", "d": math.hypot(xb - xa, yb - ya) or 1, "m": ((xa + xb) / 2, (ya + yb) / 2)}
            self.redraw()
            return True
        if len(self.touches) > 2:
            return True
        i, corner = self.hit(*touch.pos)
        if i is not None:
            self.ed.select(i)
            self.drag = {"mode": "resize" if corner else "move", "corner": corner, "start": touch.pos,
                         "b0": dict(self.ed.rec["boxes"][i])}
        else:
            nx, ny = self.to_norm(*touch.pos)
            self.ed.select(None)
            self.drag = {"mode": "new", "c": self.ed.cur, "x0": nx, "y0": ny, "x1": None, "y1": None}
        self.redraw()
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        self.touches[touch.uid] = touch.pos
        d = self.drag
        if not d:
            return True
        if d["mode"] == "pinch":
            if len(self.touches) < 2:
                return True
            (xa, ya), (xb, yb) = list(self.touches.values())[:2]
            dist = math.hypot(xb - xa, yb - ya) or 1
            mid = ((xa + xb) / 2, (ya + yb) / 2)
            self.pan[0] += mid[0] - d["m"][0]
            self.pan[1] += mid[1] - d["m"][1]
            self.zoom_at(dist / d["d"], mid)
            d["d"], d["m"] = dist, mid
            return True
        nx, ny = self.to_norm(*touch.pos)
        cl = lambda v: max(0.0, min(1.0, v))   # noqa: E731
        if d["mode"] == "new":
            d["x1"], d["y1"] = nx, ny
        else:
            b, b0 = self.ed.rec["boxes"][self.ed.sel], d["b0"]
            sx, sy = self.to_norm(*d["start"])
            dx, dy = nx - sx, ny - sy
            if d["mode"] == "move":
                b["x"] = cl(min(1 - b0["w"], b0["x"] + dx))
                b["y"] = cl(min(1 - b0["h"], b0["y"] + dy))
            else:
                x0, y0, x1, y1 = b0["x"], b0["y"], b0["x"] + b0["w"], b0["y"] + b0["h"]
                if "w" in d["corner"]:
                    x0 = cl(x0 + dx)
                else:
                    x1 = cl(x1 + dx)
                if "n" in d["corner"]:
                    y0 = cl(y0 + dy)
                else:
                    y1 = cl(y1 + dy)
                b.update(x=min(x0, x1), y=min(y0, y1), w=abs(x1 - x0), h=abs(y1 - y0))
        self.redraw()
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        self.touches.pop(touch.uid, None)
        d = self.drag
        if d and d["mode"] == "pinch":
            if not self.touches:
                self.drag = None
            return True
        self.drag = None
        if not d:
            return True
        if d["mode"] == "new":
            if d["x1"] is None:
                self.redraw()
                return True
            b = self.new_box(d)
            x0, y0, x1, y1 = self.box_rect(b)
            if x1 - x0 < dp(8) or y1 - y0 < dp(8):         # un toque suelto no crea caja
                self.redraw()
                return True
            self.ed.rec["boxes"].append(b)
            self.ed.sel = None        # la nueva no queda elegida: otra clase es para la próxima caja
        self.ed.changed()
        return True

    def zoom_at(self, factor, pos):
        new = max(1.0, min(10.0, self.zoom * factor))
        k = new / self.zoom
        self.pan[0] = (pos[0] - self.center_x) - (pos[0] - self.center_x - self.pan[0]) * k
        self.pan[1] = (pos[1] - self.center_y) - (pos[1] - self.center_y - self.pan[1]) * k
        self.zoom = new
        self.redraw()

    def fit(self):
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.redraw()


class _Pill(ButtonBehavior, Label):
    def __init__(self, text, color=None, on=False, **kw):
        super().__init__(text=text, font_size=sp(13), color=(1, 1, 1, 1), size_hint=(None, None), height=dp(36), **kw)
        self.texture_update()
        self.width = self.texture_size[0] + dp(28 if color else 22)
        self.dot = color
        self.on = on
        self.bind(pos=self.draw, size=self.draw, state=self.draw)

    def set_on(self, on):
        self.on = on
        self.color = (.08, .07, .06, 1) if on else (1, 1, 1, 1)
        self.draw()

    def draw(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(1, 1, 1, .95 if self.on else (.22 if self.state == "down" else .1))
            from kivy.graphics import RoundedRectangle
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])
            if self.dot:
                Color(*c(self.dot))
                RoundedRectangle(pos=(self.x + dp(9), self.center_y - dp(5)), size=(dp(10), dp(10)), radius=[dp(3)])
        if self.dot:
            self.padding = (dp(16), 0, 0, 0)


class BoxEditor(ModalView):
    """Una foto a pantalla completa para marcar sus cajas; ‹ › recorren la lista."""

    def __init__(self, photos: list, index: int, on_close=None, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background_color=(.08, .07, .06, 1), **kw)
        self.photos, self.i, self.on_close = photos, index, on_close
        self.cur = "flor"
        self.sel = None
        root = BoxLayout(orientation="vertical")
        top = BoxLayout(size_hint_y=None, height=dp(54), padding=(dp(6), dp(6)), spacing=dp(6))
        close = _Pill("×")
        close.bind(on_release=lambda *_: self.dismiss())
        top.add_widget(close)
        self.title = Label(text="", bold=True, font_size=sp(14), halign="left", valign="middle", shorten=True,
                           shorten_from="right", color=(1, 1, 1, 1))
        self.title.bind(size=lambda w, s: setattr(w, "text_size", s))
        top.add_widget(self.title)
        self.prev_b = _Pill("‹")
        self.prev_b.bind(on_release=lambda *_: self.go(-1))
        self.next_b = _Pill("Siguiente ›")
        self.next_b.bind(on_release=lambda *_: self.go(1))
        top.add_widget(self.prev_b)
        top.add_widget(self.next_b)
        root.add_widget(top)
        sv = ScrollView(size_hint_y=None, height=dp(46), do_scroll_y=False, bar_width=0)
        bar = BoxLayout(size_hint_x=None, padding=(dp(8), dp(4)), spacing=dp(6))
        bar.bind(minimum_width=bar.setter("width"))
        self.class_btns = {}
        for i, (key, name, col) in enumerate(CLASSES):
            b = _Pill(f"{i} · {name}", color=col)
            b.bind(on_release=lambda _w, key=key: self.set_class(key))
            self.class_btns[key] = b
            bar.add_widget(b)
        sv.add_widget(bar)
        root.add_widget(sv)
        self.canvas_w = BoxCanvas(self)
        root.add_widget(self.canvas_w)
        bottom = ScrollView(size_hint_y=None, height=dp(50), do_scroll_y=False, bar_width=0)
        tools = BoxLayout(size_hint_x=None, padding=(dp(8), dp(6)), spacing=dp(6))
        tools.bind(minimum_width=tools.setter("width"))
        self.count = Label(text="", font_size=sp(12), color=(1, 1, 1, .85), size_hint=(None, 1), width=dp(150),
                           halign="left", valign="middle", markup=True)
        self.count.bind(size=lambda w, s: setattr(w, "text_size", s))
        tools.add_widget(self.count)
        for label, fn in (("Copiar anterior", self.copy_prev), ("Sin estructuras", self.toggle_empty),
                          ("Encuadrar", lambda: self.canvas_w.fit()), ("Borrar caja", self.delete_sel)):
            b = _Pill(label)
            b.bind(on_release=lambda _w, fn=fn: fn())
            tools.add_widget(b)
            if label == "Sin estructuras":
                self.empty_b = b
        bottom.add_widget(tools)
        root.add_widget(bottom)
        root.add_widget(Label(text="Un dedo: crear o mover cajas · dos dedos: acercar y mover · toque una clase arriba",
                              font_size=sp(11), color=(1, 1, 1, .5), size_hint_y=None, height=dp(22)))
        self.add_widget(root)
        self.set_class(self.cur)
        self.bind(on_dismiss=lambda *_: self._closed())
        from android_bridge import allow_rotation
        allow_rotation(True)                 # en horizontal la foto se ve más grande
        Clock.schedule_once(lambda *_: self.show(self.i), 0)

    def _closed(self):
        from android_bridge import allow_rotation
        allow_rotation(False)
        self._commit()
        if self.on_close:
            self.on_close()

    # ---------------------------------------------------------- foto
    def show(self, i):
        self.i = i
        p = self.photos[i]
        self.photo = p
        rec = store().get(p["name"])
        self.rec = {"w": 0, "h": 0, "boxes": [dict(b) for b in (rec or {}).get("boxes") or []],
                    "empty": bool((rec or {}).get("empty"))}
        self._edited = False
        self.sel = None
        import datetime as _dt
        import phenology as ph
        week = ph.week_label(_dt.date.fromisoformat(p["week"][:10])) if p["week"] else ""
        self.title.text = f"{p['ws']} · {p['variety']} · {week}"
        self.prev_b.disabled = i <= 0
        self.next_b.disabled = i >= len(self.photos) - 1
        self.summary()
        if not p["exists"] or not os.path.exists(p["path"]):
            self.canvas_w.tex = None
            self.canvas_w.redraw()
            if not drive_ready():
                app().toast("Esta foto aún no está en el teléfono: conecte Google Drive para bajarla.")
                return
            app().toast("Bajando la foto de Drive…")

            def done(got, _missing):
                if got and self.i == i and self.photos[i] is p:
                    self.show(i)
                elif not got:
                    app().toast("La foto aún no está en Drive (el otro equipo no la ha subido).")
            fetch_photos([p], done=done)
            return
        try:
            tex, size = load_texture(p["path"])
        except Exception as exc:  # noqa: BLE001
            app().toast(f"No se pudo abrir la foto: {exc}")
            return
        self.rec["w"], self.rec["h"] = size
        self.canvas_w.set_image(tex, size)

    def go(self, d):
        j = self.i + d
        if 0 <= j < len(self.photos):
            self._commit()
            self.show(j)

    def _commit(self):
        """Guarda la foto actual si se editó (local; Drive al cerrar)."""
        if getattr(self, "_edited", False):
            r4 = lambda v: round(v, 4)   # noqa: E731
            for b in self.rec["boxes"]:
                b.update(x=r4(b["x"]), y=r4(b["y"]), w=r4(b["w"]), h=r4(b["h"]))
            a = app()
            by = getattr(a.drive, "account", "") or (a.db.get_setting("user_name") or "")
            store().put(self.photo["name"], self.rec, by)
            self._edited = False

    def changed(self):
        self._edited = True
        if self.rec["boxes"]:
            self.rec["empty"] = False
        self.summary()
        self.canvas_w.redraw()

    def summary(self):
        n = {}
        for b in self.rec["boxes"]:
            n[b["c"]] = n.get(b["c"], 0) + 1
        if self.rec.get("empty") and not self.rec["boxes"]:
            self.count.text = "Sin estructuras"
        else:
            self.count.text = "  ".join(f"[color={COLORS[k]}][b]•[/b][/color] {n[k]}" for k, _, _ in CLASSES if n.get(k)) or "Sin cajas"
        self.empty_b.set_on(bool(self.rec.get("empty")))

    # ---------------------------------------------------------- acciones
    def set_class(self, key):
        self.cur = key
        for k, b in self.class_btns.items():
            b.set_on(k == key)
        if self.sel is not None:
            self.rec["boxes"][self.sel]["c"] = key
            self.changed()

    def select(self, i):
        self.sel = i
        if i is not None:
            key = self.rec["boxes"][i]["c"]
            self.cur = key
            for k, b in self.class_btns.items():
                b.set_on(k == key)

    def delete_sel(self):
        if self.sel is not None:
            self.rec["boxes"].pop(self.sel)
            self.sel = None
            self.changed()

    def toggle_empty(self):
        self.rec["empty"] = not self.rec.get("empty")
        if self.rec["empty"]:
            self.rec["boxes"] = []
            self.sel = None
        self.changed()

    def copy_prev(self):
        if self.i <= 0:
            return
        prev = store().get(self.photos[self.i - 1]["name"])
        if not prev or not prev.get("boxes"):
            app().toast("La foto anterior no tiene cajas")
            return
        self.rec["boxes"] = [dict(b) for b in prev["boxes"]]
        self.sel = None
        self.changed()
