"""
ui/photo_viewer.py
==================
Foto a pantalla completa (al tocar la foto principal de un registro):

* pellizcar para acercar (hasta 6×) y arrastrar para moverse; doble toque: 2,5× ↔ entera;
* deslizar a los lados (sin zoom) o ‹ › para recorrer las demás fotos de esa casilla;
* la foto se dibuja derecha (orientación de la cámara) y reducida a ~2000 px (memoria).
"""
from __future__ import annotations

import os

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scatter import Scatter

MAX_SIDE = 2000


def _texture(path: str):
    """Textura derecha (EXIF) y reducida; None si no se puede leer."""
    try:
        from PIL import Image as PImage, ImageOps
        from kivy.graphics.texture import Texture
        img = PImage.open(path)
        img.draft("RGB", (MAX_SIDE, MAX_SIDE))
        img = ImageOps.exif_transpose(img).convert("RGB")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE))
        tex = Texture.create(size=img.size, colorfmt="rgb")
        tex.blit_buffer(img.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
        tex.flip_vertical()
        return tex
    except Exception:  # noqa: BLE001
        return None


def _icon(name: str, size=22) -> str:
    from kivymd import fonts_path
    from kivymd.icon_definitions import md_icons
    font = os.path.join(fonts_path, "materialdesignicons-webfont.ttf")
    return f"[font={font}][size={int(sp(size))}]{md_icons.get(name, '?')}[/size][/font]"


class _RoundBtn(ButtonBehavior, Label):
    def __init__(self, icon, **kw):
        super().__init__(text=_icon(icon), markup=True, size_hint=(None, None), size=(dp(46), dp(46)),
                         color=(1, 1, 1, 1), **kw)
        self.bind(pos=self._bg, size=self._bg, state=self._bg)

    def _bg(self, *_):
        from kivy.graphics import RoundedRectangle
        self.canvas.before.clear()
        with self.canvas.before:
            Color(1, 1, 1, .28 if self.state == "down" else .14)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.height / 2])


class _Zoom(Scatter):
    """La foto: pellizco (zoom), arrastre con zoom, doble toque y deslizar para cambiar."""

    def __init__(self, viewer, **kw):
        super().__init__(do_rotation=False, scale_min=1, scale_max=6, auto_bring_to_front=False, **kw)
        self.viewer = viewer
        self.img = Image(fit_mode="contain", size_hint=(None, None))
        self.add_widget(self.img)

    def fit(self, size):
        self.scale = 1
        self.size = self.img.size = size
        self.pos = (0, 0)

    def on_touch_down(self, touch):
        if touch.is_double_tap and self.collide_point(*touch.pos):
            if self.scale > 1.05:
                self.fit(self.parent.size)
            else:
                px, py = touch.pos
                self.apply_transform_scale(2.5, (px, py))
            return True
        return super().on_touch_down(touch)

    def apply_transform_scale(self, k, anchor):
        from kivy.graphics.transformation import Matrix
        self.apply_transform(Matrix().scale(k, k, k), anchor=anchor)

    def on_touch_up(self, touch):
        handled = super().on_touch_up(touch)
        if self.scale <= 1.02 and touch.grab_current is None:
            dx, dy = touch.x - touch.ox, touch.y - touch.oy
            if abs(dx) > dp(70) and abs(dx) > abs(dy) * 1.5:
                self.viewer.step(-1 if dx > 0 else 1)
                return True
            if self.scale <= 1.02:
                self.pos = (0, 0)            # sin zoom la foto vuelve a su lugar
        return handled


class PhotoViewer(ModalView):
    """photos: [{"path", "title"(opcional)}…] · index: la que se muestra primero."""

    def __init__(self, photos: list[dict], index: int = 0, title: str = "", **kw):
        super().__init__(size_hint=(1, 1), background_color=(0, 0, 0, 1), overlay_color=(0, 0, 0, 1),
                         auto_dismiss=True, **kw)
        self.photos, self.i, self.title = [p for p in photos if p.get("path")], index, title
        root = FloatLayout()
        with root.canvas.before:
            Color(0, 0, 0, 1)
            self._bg = Rectangle()
        root.bind(pos=lambda *_: setattr(self._bg, "pos", root.pos), size=self._layout)
        self.stage = FloatLayout()
        self.zoom = _Zoom(self)
        self.stage.add_widget(self.zoom)
        root.add_widget(self.stage)
        top = BoxLayout(size_hint=(1, None), height=dp(64), pos_hint={"top": 1}, padding=(dp(12), dp(9)),
                        spacing=dp(10))
        with top.canvas.before:                       # franja oscura: el texto se lee sobre fotos claras
            Color(0, 0, 0, .45)
            self._top_bg = Rectangle()
        top.bind(pos=lambda w, v: setattr(self._top_bg, "pos", v), size=lambda w, v: setattr(self._top_bg, "size", v))
        self.cap = Label(text="", color=(1, 1, 1, .9), font_size=sp(14), halign="left", valign="middle",
                         shorten=True, shorten_from="right")
        self.cap.bind(size=lambda w, s: setattr(w, "text_size", s))
        close = _RoundBtn("close")
        close.bind(on_release=lambda *_: self.dismiss())
        top.add_widget(self.cap)
        top.add_widget(close)
        root.add_widget(top)
        self.prev_b = _RoundBtn("chevron-left", pos_hint={"x": .02, "center_y": .5})
        self.next_b = _RoundBtn("chevron-right", pos_hint={"right": .98, "center_y": .5})
        self.prev_b.bind(on_release=lambda *_: self.step(-1))
        self.next_b.bind(on_release=lambda *_: self.step(1))
        root.add_widget(self.prev_b)
        root.add_widget(self.next_b)
        self.hint = Label(text="Pellizque para acercar · doble toque · deslice para ver las demás",
                          font_size=sp(11.5), color=(1, 1, 1, .5), size_hint=(1, None), height=dp(30),
                          pos_hint={"y": .01})
        root.add_widget(self.hint)
        Clock.schedule_once(lambda *_: setattr(self.hint, "opacity", 0), 4)
        self.add_widget(root)
        self.root_box = root
        Clock.schedule_once(lambda *_: self.show(), 0)

    def _layout(self, root, size):
        self._bg.size = size
        self.stage.size = size
        self.zoom.fit(size)

    def show(self):
        if not self.photos:
            return
        self.i %= len(self.photos)
        p = self.photos[self.i]
        tex = _texture(p["path"])
        self.zoom.img.texture = tex
        self.zoom.fit(self.root_box.size)
        n = len(self.photos)
        label = p.get("title") or self.title
        self.cap.text = f"{label}  ·  {self.i + 1} de {n}" if n > 1 else label
        many = n > 1
        for b in (self.prev_b, self.next_b):
            b.opacity, b.disabled = (1, False) if many else (0, True)

    def step(self, d: int):
        if len(self.photos) > 1:
            self.i += d
            self.show()


def open_viewer(photos: list[dict], index: int = 0, title: str = ""):
    v = PhotoViewer(photos, index, title)
    v.open()
    return v
