"""
ui/extra.py
===========
Pestaña «Fotos extra» del Entrenador de IA: fotos que no son de ningún ensayo ni predio,
solo para entrenar IA+ (ver extra_photos.py).

* Cámara y Galería: la foto se sube sola a «IA+ Conocimiento ampliado» en Drive.
* La lista es la de Drive (miniaturas de Drive: en el teléfono no se guardan las fotos).
  Las subidas desde la web, con sus subcarpetas, aparecen aquí y se filtran por carpeta.
* Tocar una foto la abre en IA+ para marcarla (en la app Lab); al pasar a otra se borra
  del teléfono.
"""
from __future__ import annotations

import os
import threading

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.app import MDApp

import extra_photos as ex
from ui.theme import c

PAGE = 60
CHUNK = 12


def app():
    return MDApp.get_running_app()


def drive_ready() -> bool:
    a = app()
    return bool(a.db.get_setting("drive_enabled", False) and a.drive.available)


def has_iaplus() -> bool:
    try:
        import ui.boxes  # noqa: F401  (solo en la app Lab)
        return True
    except ImportError:
        return False


def marked_names() -> set:
    """Fotos ya marcadas en IA+ (marcas.json local)."""
    try:
        from training_labels import is_marked
        from ui.boxes import store
    except ImportError:
        return set()
    st = store()
    return {k for k, v in st.data.get("photos", {}).items() if is_marked(v)}


class ExtraThumb(ButtonBehavior, Widget):
    """Miniatura de Drive dibujada en el canvas (recorte «cover»)."""

    def __init__(self, photo: dict, marked: bool, **kw):
        super().__init__(size_hint_y=None, height=dp(104), **kw)
        self.photo = photo
        self._tex = None
        with self.canvas:
            Color(*c("#1F2A5C"))
            self._bg = Rectangle()
            self._img_col = Color(1, 1, 1, 0)
            self._img = Rectangle()
            Color(*c("#7CF2B0", 1 if marked else 0))
            self._mark = Line(width=dp(1.4))
        self.bind(pos=self._place, size=self._place)

    def _place(self, *_):
        self._bg.pos = self._img.pos = self.pos
        self._bg.size = self._img.size = self.size
        self._mark.rectangle = (self.x + 1, self.y + 1, self.width - 2, self.height - 2)
        self._fit()

    def _fit(self):
        tex = self._tex
        if tex is None or not self.width:
            return
        tw, th = tex.size
        k = max(self.width / tw, self.height / th)
        cw, ch = min(tw, self.width / k), min(th, self.height / k)
        self._img.texture = tex.get_region((tw - cw) / 2, (th - ch) / 2, cw, ch)

    def set_image(self, path):
        if not path:
            return
        try:
            self._tex = CoreImage(path).texture
        except Exception:  # noqa: BLE001
            return
        self._img_col.a = 1
        self._fit()


class _Loader:
    """Baja miniaturas de Drive de a pocas en un hilo (sin trabar la interfaz)."""

    def __init__(self):
        self.queue: list = []
        self.busy = False

    def add(self, photo, cb):
        dest = ex.thumb_path(photo)
        if os.path.exists(dest):
            cb(dest)
            return
        self.queue.append((photo, cb))
        if not self.busy and drive_ready():
            self.busy = True
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        drive = app().drive
        while self.queue:
            photo, cb = self.queue.pop(0)
            path = ex.fetch_thumb(drive, photo)
            Clock.schedule_once(lambda *_, cb=cb, path=path: cb(path))
        self.busy = False


_loader = _Loader()


class Panel:
    folder = None          # subcarpeta elegida (None = todas)
    shown = PAGE

    def __init__(self, screen):
        self.screen = screen
        self.photos = ex.load_index()
        self._loading = False

    # ------------------------------------------------------------ datos
    def reload(self, quiet=True):
        """Lista de Drive en segundo plano (la anterior se muestra mientras)."""
        a = app()
        if not drive_ready():
            if not quiet:
                a.toast("Conecte Google Drive para ver las fotos extra.")
            return
        if self._loading:
            return
        self._loading = True

        def work():
            err = None
            try:
                ex.pending_uploads(a.drive)
                photos = ex.refresh(a.drive)
            except Exception as exc:  # noqa: BLE001
                photos, err = None, exc

            def end(*_):
                self._loading = False
                if err is not None:
                    a.toast(f"No se pudo leer la carpeta de Drive: {err}")
                    return
                self.photos = photos
                self.render()
                if not quiet:
                    a.toast(f"{len(photos)} foto(s) en «{ex.FOLDER}»")
            Clock.schedule_once(end)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ vista
    def render(self):
        from kivy.factory import Factory
        a = app()
        box = self.screen.ids.extra_box
        box.clear_widgets()
        done = marked_names()
        folders = sorted({p["folder"] for p in self.photos if p["folder"]})
        card = Factory.MindCard()
        card.add_widget(Factory.MindSection(text="FOTOS EXTRA PARA IA+ · CONOCIMIENTO AMPLIADO"))
        n_marked = sum(1 for p in self.photos if p["key"] in done)
        card.add_widget(Factory.MindText(
            text=f"[b]{len(self.photos)}[/b] foto(s) en Drive" + (f" · {n_marked} marcadas" if has_iaplus() else ""),
            markup=True))
        card.add_widget(Factory.MindMuted(
            text=f"Fotos que no son de un ensayo ni de un predio, solo para entrenar IA+. Se guardan en Drive, "
                 f"carpeta «{ex.FOLDER}». Para subir muchas a la vez (con sus carpetas) use la web: "
                 f"Entrenar IA › Subir fotos extra."))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        for icon, label, src in (("camera-outline", "Cámara", "camera"), ("image-multiple-outline", "Galería", "gallery")):
            b = Factory.MindGhost(icon=icon, text=label)
            b.bind(on_release=lambda _w, src=src: self.add(src))
            row.add_widget(b)
        card.add_widget(row)
        pend = ex.pending_uploads(a.drive) if drive_ready() else []
        used = ex.local_size()
        info = []
        if pend:
            info.append(f"{len(pend)} por subir")
        info.append(f"en el teléfono: {used / 1e6:.1f} MB (miniaturas)")
        card.add_widget(Factory.MindMuted(text=" · ".join(info)))
        sync = Factory.MindGhost(icon="cloud-sync-outline", text="Actualizar desde Drive")
        sync.bind(on_release=lambda *_: self.reload(quiet=False))
        card.add_widget(sync)
        if folders:
            sv = ScrollView(size_hint_y=None, height=dp(44), do_scroll_y=False, bar_width=0)
            chips = BoxLayout(size_hint_x=None, spacing=dp(6), padding=(0, dp(2)))
            chips.bind(minimum_width=chips.setter("width"))
            for f, label in [(None, f"Todas ({len(self.photos)})")] + [
                    (f, f"{f} ({sum(1 for p in self.photos if p['folder'] == f)})") for f in folders]:
                b = Factory.MindSeg(text=label, selected=self.folder == f, size_hint_x=None)
                b.width = max(dp(70), len(label) * dp(8) + dp(24))
                b.bind(on_release=lambda _w, f=f: self._folder(f))
                chips.add_widget(b)
            sv.add_widget(chips)
            card.add_widget(sv)
        box.add_widget(card)
        shown = [p for p in self.photos if self.folder is None or p["folder"] == self.folder]
        self.list = shown
        grid = GridLayout(cols=3, spacing=dp(6), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        box.add_widget(grid)
        todo = list(enumerate(shown[:self.shown]))

        def add_chunk(*_):
            for i, p in todo[:CHUNK]:
                t = ExtraThumb(p, p["key"] in done)
                t.bind(on_release=lambda _w, i=i: self.open(i))
                grid.add_widget(t)
                _loader.add(p, t.set_image)
            del todo[:CHUNK]
            if todo:
                Clock.schedule_once(add_chunk, 0)
        add_chunk()
        if not shown:
            box.add_widget(Factory.MindMuted(text="Aún no hay fotos extra: saque o elija una, o súbalas desde la web."))
        elif len(shown) > self.shown:
            more = Factory.MindGhost(icon="chevron-down", text=f"Ver más ({len(shown) - self.shown})")
            more.bind(on_release=lambda *_: self._more())
            box.add_widget(more)

    def _folder(self, f):
        self.folder, self.shown = f, PAGE
        self.render()

    def _more(self):
        self.shown += PAGE
        self.render()

    # ------------------------------------------------------------ acciones
    def add(self, source: str):
        a = app()
        if not drive_ready():
            a.toast("Conecte Google Drive (Ajustes): las fotos extra se guardan en Drive.")
            return

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return

            def work():
                n, err = 0, None
                for tmp in paths:
                    try:
                        ex.add_local(tmp, a.drive)
                        n += 1
                    except Exception as exc:  # noqa: BLE001
                        err = exc
                Clock.schedule_once(lambda *_: (a.toast(f"{n} foto(s) extra: se suben a Drive"
                                                        + (f" · error: {err}" if err else "")),
                                                Clock.schedule_once(lambda *_: self.reload(), 6)))
            threading.Thread(target=work, daemon=True).start()

        if source == "camera":
            a.media.take_photo(done, "extra")
        else:
            a.media.pick_images(done)

    def open(self, i):
        if not has_iaplus():
            app().toast("Las fotos extra se marcan en IA+ (app Lab) o en la web «Entrenar IA».")
            return
        from ui import boxes
        boxes.open_extra(self.list, i, on_close=self.render)


def build(screen):
    panel = getattr(screen, "_extra_panel", None)
    if panel is None:
        panel = screen._extra_panel = Panel(screen)
    panel.render()
    panel.reload()
