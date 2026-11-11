"""
ui/photo_buttons.py
===================
Dos botones redondos, cámara y galería, con su nombre debajo (sin sombras de KivyMD).

    photo_buttons(on_camera, on_gallery, "Sacar foto", "Galería")
"""
from __future__ import annotations

from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivymd.uix.label import MDIcon, MDLabel

from ui import theme
from ui.theme import c


class RoundPhotoButton(ButtonBehavior, BoxLayout):
    """Círculo con un ícono (relleno o solo borde) y el texto debajo."""

    def __init__(self, icon: str, text: str, filled: bool, **kw):
        super().__init__(orientation="vertical", size_hint=(None, None), size=(dp(112), dp(98)),
                         spacing=dp(4), **kw)
        self.filled = filled
        self.ring = AnchorLayout(size_hint=(1, None), height=dp(68))
        fg = (1, 1, 1, 1) if filled else c(theme.BERRY)
        self.ring.add_widget(MDIcon(icon=icon, theme_text_color="Custom", text_color=fg, font_size="30sp",
                                    halign="center", size_hint=(None, None), size=(dp(40), dp(40))))
        self.add_widget(self.ring)
        self.add_widget(MDLabel(text=text, halign="center", font_style="Caption", bold=True,
                                theme_text_color="Custom", text_color=c(theme.INK), size_hint_y=None,
                                height=dp(24)))
        self.bind(pos=self._draw, size=self._draw, state=self._draw)
        self.ring.bind(pos=self._draw, size=self._draw)   # el círculo sigue al ícono ya acomodado

    def _draw(self, *_):
        r = self.ring
        d = dp(64)
        x, y = r.center_x - d / 2, r.center_y - d / 2
        k = .9 if self.state == "down" else 1
        self.canvas.before.clear()
        with self.canvas.before:
            if self.filled:
                Color(*c(theme.BERRY, k))
                Ellipse(pos=(x, y), size=(d, d))
            else:
                Color(*c(theme.SURFACE, .85 * k))
                Ellipse(pos=(x, y), size=(d, d))
                Color(*c(theme.BERRY, .8))
                Line(circle=(r.center_x, r.center_y, d / 2 - dp(1)), width=dp(1.4))


def photo_buttons(on_camera, on_gallery, camera_text: str = "Cámara", gallery_text: str = "Galería"):
    row = BoxLayout(size_hint=(1, None), height=dp(104), spacing=dp(28), padding=(0, dp(4), 0, 0))
    row.add_widget(BoxLayout())
    cam = RoundPhotoButton("camera-outline", camera_text, True)
    cam.bind(on_release=lambda *_: on_camera())
    gal = RoundPhotoButton("image-multiple-outline", gallery_text, False)
    gal.bind(on_release=lambda *_: on_gallery())
    row.add_widget(cam)
    row.add_widget(gal)
    row.add_widget(BoxLayout())
    return row
