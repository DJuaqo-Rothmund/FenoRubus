"""
ui/onboarding.py
================
Guía de inicio ilustrada (ilustraciones del usuario hechas en Flow: assets/ui/inicio).

Tarjetas que se pasan con el dedo: primero un recorrido por las funciones de la app y después
cómo sacar las fotos de fenología (láminas «así / así no»). Se abre sola la primera vez que
se usa la app en el teléfono y siempre desde Ajustes › «Ver la guía de inicio».
"""
from __future__ import annotations

from kivy.metrics import dp
from kivy.uix.carousel import Carousel
from kivy.uix.image import Image
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from platform_utils import global_set, resource_path
from ui import theme
from ui.theme import c

SEEN_KEY = "onboarding_seen"

# (imagen, título, texto). «sec» marca el comienzo de una sección.
SLIDES = [
    ("i_bienvenida", "Bienvenido a AeonCrop",
     "Su campo en el teléfono: fenología, mediciones, rendimiento, sanidad y cuaderno de campo "
     "de frambuesa, arándano y cranberry. Funciona sin señal."),
    ("i_cultivo", "Elija el cultivo",
     "En la pantalla principal toque frambuesa (PhenoRubus), arándano (PhenoBlue) o cranberry "
     "(PhenoCran). Cada cultivo guarda sus datos aparte."),
    ("i_ensayo", "Ensayos y predios",
     "Cree un ensayo (I+D) con sus tratamientos y parcelas, o un predio con sus sectores. Tocando "
     "el nombre arriba cambia de uno a otro."),
    ("i_muestreo", "Muestreo semanal",
     "Cada semana recorra las parcelas y registre cómo está cada una. Tocando «Semana del …» "
     "elige la fecha en el calendario."),
    ("i_fotos", "Foto 1 general y Foto 2 detalle",
     "La general muestra la caña o planta completa; la de detalle, el racimo más avanzado. Con "
     "ellas se arman los informes y aprende la IA."),
    ("i_bbch", "Estado fenológico (BBCH)",
     "Elija el estado en la escala BBCH, de yema a fruta madura. La app le sugiere el que ve en "
     "la foto de detalle."),
    ("i_mediciones", "Mediciones",
     "El botón del contador abre las mediciones de la parcela: largos, conteos, frutos y lo que "
     "configure para el ensayo."),
    ("i_rendimiento", "Rendimiento",
     "Estime la producción por sector con conteos y fotos, y véala en el mapa de colores del "
     "predio."),
    ("i_cuaderno", "Cuaderno de campo",
     "Escriba, dibuje y pegue fotos como en un cuaderno de papel. Queda respaldado en Drive."),
    ("i_scout", "AeonScout",
     "Fotografíe plagas, malezas y enfermedades. La IA le sugiere qué es y la guía le enseña a "
     "sacar las fotos."),
    ("i_informes", "Informes",
     "PDF de fenología, días grado y comparación entre temporadas, con vista previa en el "
     "teléfono antes de compartirlos."),
    ("i_drive", "Respaldo y equipo",
     "Conecte su cuenta de Google: todo se respalda en Drive y puede compartir un ensayo con otra "
     "persona para trabajarlo juntos."),
    ("i_ia", "Una IA que aprende con usted",
     "Cada foto con su estado enseña a la IA a reconocer la fenología. Funciona en el teléfono, "
     "sin internet."),
    ("f_semanas", "Fotos de fenología: la misma caña, cada semana",
     "Fotografíe siempre las mismas cañas, desde la misma distancia y ángulo: así se ve el avance "
     "semana a semana.", "sec"),
    ("f_marcada", "Marque sus cañas",
     "Amarre una cinta o etiqueta a las cañas que va a seguir y fotografíe siempre esas."),
    ("f_general", "Foto 1 · General",
     "Dé un paso atrás: que salga la caña completa, de la base a la punta."),
    ("f_detalle", "Foto 2 · Detalle",
     "Acérquese al racimo hasta que llene la foto, y toque la pantalla para enfocarlo."),
    ("f_luz", "Luz",
     "Con el sol a su espalda o con el día nublado. A contraluz los colores se pierden."),
    ("f_fondo", "Fondo y sombra",
     "Ponga la mano detrás del racimo como fondo y cuide que su sombra no lo tape."),
    ("f_avanzada_ok", "Lo más avanzado manda",
     "En el detalle, enfoque la estructura más avanzada (la fruta más adelantada): esa define el "
     "estado de la caña."),
]


def app():
    return MDApp.get_running_app()


def _img(name: str) -> str:
    return resource_path("assets", "ui", "inicio", f"{name}.jpg")


class OnboardingScreen(MDScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.md_bg_color = (0, 0, 0, 0)          # el fondo común de la app (según el estilo)
        root = MDBoxLayout(orientation="vertical", padding=(dp(16), dp(12), dp(16), dp(12)), spacing=dp(8))
        top = MDBoxLayout(size_hint_y=None, height=dp(40))
        self.counter = MDLabel(text="", theme_text_color="Custom", text_color=theme.on_bg(theme.MUTED),
                               font_style="Caption")
        top.add_widget(self.counter)
        top.add_widget(MDFlatButton(text="SALTAR", on_release=lambda *_: self.finish(),
                                    theme_text_color="Custom", text_color=theme.on_bg(theme.MUTED)))
        root.add_widget(top)
        self.carousel = Carousel(direction="right", loop=False)
        for slide in SLIDES:
            self.carousel.add_widget(self._slide(*slide[:3], section=len(slide) > 3))
        self.carousel.bind(index=lambda *_: self._update())
        root.add_widget(self.carousel)
        bottom = MDBoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        self.prev_btn = MDFlatButton(text="ATRÁS", on_release=lambda *_: self.carousel.load_previous(),
                                     theme_text_color="Custom", text_color=theme.on_bg(theme.LEAF_DARK))
        bottom.add_widget(self.prev_btn)
        bottom.add_widget(MDLabel())
        self.next_btn = MDRaisedButton(text="SIGUIENTE", md_bg_color=c(theme.BERRY),
                                       on_release=lambda *_: self._next())
        bottom.add_widget(self.next_btn)
        root.add_widget(bottom)
        self.add_widget(root)
        self._update()

    def _slide(self, img: str, title: str, text: str, section: bool = False):
        box = MDBoxLayout(orientation="vertical", spacing=dp(10))
        if section:
            box.add_widget(MDLabel(text="CÓMO SACAR LAS FOTOS DE FENOLOGÍA", halign="center",
                                   font_style="Caption", bold=True, adaptive_height=True,
                                   theme_text_color="Custom", text_color=theme.on_bg(theme.BERRY)))
        box.add_widget(Image(source=_img(img), fit_mode="contain", mipmap=True, size_hint_y=.62))
        box.add_widget(MDLabel(text=title, halign="center", font_style="H6", bold=True,
                               adaptive_height=True, theme_text_color="Custom",
                               text_color=theme.on_bg(theme.LEAF_DARK)))
        box.add_widget(MDLabel(text=text, halign="center", font_style="Body1", size_hint_y=.24,
                               valign="top", theme_text_color="Custom", text_color=theme.on_bg(theme.INK)))
        return box

    def _update(self):
        i = self.carousel.index or 0
        n = len(SLIDES)
        self.counter.text = f"{i + 1} / {n}"
        self.prev_btn.disabled = i == 0
        self.next_btn.text = "EMPEZAR" if i == n - 1 else "SIGUIENTE"

    def _next(self):
        if (self.carousel.index or 0) >= len(SLIDES) - 1:
            self.finish()
        else:
            self.carousel.load_next()

    def on_pre_enter(self, *_):
        self.carousel.index = 0
        global_set(SEEN_KEY, True)

    def finish(self):
        a = app()
        if getattr(a, "_history", None):
            a.back()
        else:
            a.sm.current = "crops"


def open_screen():
    a = app()
    if not a.sm.has_screen("onboarding"):
        a.sm.add_widget(OnboardingScreen(name="onboarding"))
    a.go("onboarding")
