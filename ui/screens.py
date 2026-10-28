"""
Pantallas y widgets de la app (lógica de UI). El layout está en ui/layout.kv.
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import re
import threading
import time

from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.layout import Layout
from kivy.uix.widget import Widget
from kivy.properties import (BooleanProperty, ColorProperty, ListProperty, NumericProperty,
                             ObjectProperty, StringProperty)
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton, MDRectangleFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.fitimage import FitImage
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.toolbar import MDTopAppBar

import phenology as ph
from android_bridge import request_runtime_permissions, store_photo
from notifications import FREQUENCIES, can_schedule_exact, request_exact_alarm_permission
from platform_utils import IS_ANDROID, app_version, data_subdir
from ui import theme
from ui.arcade import MindSky  # noqa: F401 - registra la clase para el KV
from ui.splash_anim import LogoAnim  # noqa: F401 - logo animado de la apertura
from ui.pending import PostIt  # noqa: F401 - post-it de pendientes del inicio (KV)
from ui.theme import c


DIALOG_BG = (0.985, 0.992, 0.985, 1)


def app() -> "MDApp":
    return MDApp.get_running_app()


def fast_clear(container) -> None:
    """
    Vacía un contenedor sin pasar por ThemableBehavior.remove_widget de KivyMD 1.2,
    que recorre todos los observadores del tema (lista que crece con cada widget
    creado) y vuelve cada refresco más lento que el anterior. Las suscripciones de
    Kivy a métodos son referencias débiles, así que no quedan widgets retenidos.
    """
    remove = Layout.remove_widget if isinstance(container, Layout) else Widget.remove_widget
    for child in list(container.children):
        remove(container, child)


# ===========================================================================
# Widgets comunes
# ===========================================================================
class GlassCard(BoxLayout):
    """
    Tarjeta de vidrio liviana (BoxLayout + 2 instrucciones de canvas).

    Reemplaza a MDCard, que arrastra comportamientos de elevación, ripple, foco
    y tema: crear una MDCard cuesta ~15-20 ms; esta, <1 ms. Acepta las mismas
    propiedades usadas en las reglas KV (md_bg_color, line_color, radius,
    adaptive_height, elevation, ripple_behavior).
    """
    md_bg_color = ColorProperty(c(theme.GLASS))
    line_color = ColorProperty(c(theme.GLASS_EDGE))
    radius = ListProperty([dp(20)])
    adaptive_height = BooleanProperty(False)
    elevation = NumericProperty(0)            # compatibilidad (sin sombra)
    ripple_behavior = BooleanProperty(False)  # compatibilidad (sin ripple)

    def on_adaptive_height(self, *_):
        if self.adaptive_height:
            self.size_hint_y = None
            self.bind(minimum_height=self.setter("height"))
            self.height = self.minimum_height


class GlassButton(ButtonBehavior, GlassCard):
    """Tarjeta pulsable con realce al tocar (sin animación de ripple)."""

class Tag(MDLabel):
    bg = ColorProperty(c(theme.LEAF_SOFT))
    fg = ColorProperty(c(theme.LEAF_DARK))


class UnitButton(MDRectangleFlatButton):
    options = ListProperty([])

    def on_options(self, *_):
        if self.options and self.text not in self.options:
            self.text = self.options[0]

    def on_release(self):
        if self.options:
            i = self.options.index(self.text) if self.text in self.options else -1
            self.text = self.options[(i + 1) % len(self.options)]


class PillButton(ButtonBehavior, Label):
    """Botón píldora dibujado con UNA forma redondeada (sin la sombra rectangular de los
    botones con relieve de KivyMD, que en algunos teléfonos se veía desplazada junto con
    el color de «presionado»)."""
    selected = BooleanProperty(False)
    bg_on = ColorProperty(c(theme.BERRY))
    bg_off = ColorProperty(c("#FFFFFF", .55))
    fg_on = ColorProperty(c("#FFFFFF"))
    fg_off = ColorProperty(c(theme.LEAF_DARK))
    edge = ColorProperty(c(theme.GLASS_EDGE))
    press_tint = ColorProperty(c("#000000", .10))


class SegButton(PillButton):
    pass


class DialBubble(ButtonBehavior, FloatLayout):
    """Botón redondo translúcido del acceso rápido a Drive (con globo de cantidad)."""
    icon = StringProperty()
    color = ColorProperty([0, 0, 0, 1])
    badge = StringProperty("")


class DialPill(ButtonBehavior, Label):
    """Etiqueta de estado junto a cada burbuja (también se puede tocar)."""
    warn = BooleanProperty(False)


class DriveDial(FloatLayout):
    """Burbujas en cascada bajo el ícono de Drive: respaldo (cuánto falta) y sincronizar
    (cuándo fue la última vez). Un toque fuera las cierra."""

    def __init__(self, anchor, items, **kw):
        super().__init__(**kw)
        self.opacity = 0
        x, y = anchor                       # centro inferior del ícono, en la ventana
        for i, (icon, color, badge, text, warn, action) in enumerate(items):
            top = y - dp(10) - i * dp(70)
            b = DialBubble(icon=icon, color=c(color), badge=badge,
                           pos=(x - dp(28), top - dp(56)))
            p = DialPill(text=text, warn=warn)
            p.bind(texture_size=lambda w, ts, b=b: setattr(
                w, "pos", (b.x - dp(10) - w.width, b.center_y - w.height / 2)))
            for w in (b, p):
                w.bind(on_release=lambda *_, f=action: self.run(f))
                self.add_widget(w)

    def open(self):
        from kivy.animation import Animation
        from kivy.core.window import Window
        Window.add_widget(self)
        Window.bind(on_keyboard=self._back)
        Animation(opacity=1, d=.15).start(self)

    def _back(self, _w, key, *_):
        if key == 27:                       # botón Atrás del celular: solo cierra las burbujas
            self.dismiss()
            return True
        return False

    def dismiss(self, *_):
        from kivy.core.window import Window
        Window.unbind(on_keyboard=self._back)
        if self.parent:
            self.parent.remove_widget(self)

    def run(self, action):
        self.dismiss()
        action()

    def on_touch_down(self, touch):
        if not super().on_touch_down(touch):
            self.dismiss()                  # toque fuera de las burbujas: cerrar
        return True


def when_text(stamp: str) -> str:
    """«20/10 15:16» -> «hoy 15:16», «ayer 15:16» o igual."""
    import datetime as _d
    try:
        day, hm = stamp.split(" ")
        d, m = (int(x) for x in day.split("/"))
        today = _d.date.today()
        ref = _d.date(today.year, m, d)
        if ref == today:
            return f"hoy {hm}"
        if ref == today - _d.timedelta(days=1):
            return f"ayer {hm}"
    except Exception:  # noqa: BLE001
        pass
    return stamp


class PickRow(GlassButton):
    title = StringProperty()
    subtitle = StringProperty()
    accent = ColorProperty(c(theme.LEAF_SOFT))
    action = ObjectProperty(None, allownone=True)   # lo asigna la lista reciclable
    trash = ObjectProperty(None, allownone=True)    # basurero opcional a la derecha

    def on_release(self, *_):
        if self.action is not None:
            self.action()


_pick_open = None   # diálogo de selección abierto (evita abrir varios con toques repetidos)


def pick_dialog(title: str, items: list[tuple], dark: bool = False):
    """
    Lista de selección en un diálogo CENTRADO y a lo ancho (reemplaza al menú
    desplegable, que se abría desplazado y cortaba los nombres largos).
    items: (título, subtítulo, callback) o (título, subtítulo, callback, color_acento)
    o (título, subtítulo, callback, color_acento | None, al_tocar_basurero).

    Usa una lista RECICLABLE (RecycleView): solo se crean las filas visibles (~8) en vez
    de todas (la escala BBCH tiene 34), así abre al instante también en teléfonos básicos.
    """
    global _pick_open
    if _pick_open is not None:
        return _pick_open
    from kivy.uix.recycleboxlayout import RecycleBoxLayout
    from kivy.uix.recycleview import RecycleView
    dialog = None

    def wrap(cb):
        def run():
            dialog.dismiss()
            cb()
        return run

    data = []
    for it in items:
        row = {"title": it[0], "subtitle": it[1] or "", "action": wrap(it[2]),
               "trash": wrap(it[4]) if len(it) > 4 and it[4] else None}
        row["accent"] = it[3] if len(it) > 3 and it[3] is not None else c(theme.LEAF_SOFT)
        data.append(row)
    rv = RecycleView(size_hint_y=None, do_scroll_x=False, bar_width=dp(4),
                     height=min(dp(440), dp(64) * len(items) + dp(8)))
    layout = RecycleBoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6),
                              padding=(0, dp(4)), default_size=(None, dp(58)),
                              default_size_hint=(1, None))
    layout.bind(minimum_height=layout.setter("height"))
    rv.add_widget(layout)
    rv.viewclass = "PickRow"
    rv.data = data
    dialog = MDDialog(title=title, type="custom", content_cls=rv, md_bg_color=DIALOG_BG,
                      buttons=[MDFlatButton(text="CERRAR", on_release=lambda *_: dialog.dismiss())])

    def closed(*_):
        global _pick_open
        _pick_open = None

    dialog.bind(on_dismiss=closed)
    _pick_open = dialog
    dialog.open()
    return dialog


def bbch_pick_items(db, callback, extra: list | None = None) -> list[tuple]:
    items = list(extra or [])
    for r in db.list_bbch():
        bg, _fg = theme.stage_colors(r["code"])
        items.append((f"BBCH {ph.code_str(r['code'])} · {r['label']}",
                      ph.MACRO_STAGES.get(ph.macro_of(r["code"]), ""),
                      lambda code=r["code"]: callback(code), bg))
    return items


class ScaleGroup(ButtonBehavior, GlassCard):
    title = StringProperty()
    count = StringProperty()
    accent = ColorProperty(c(theme.LEAF_SOFT))
    expanded = BooleanProperty(False)
    macro = NumericProperty(0)


class ScaleRow(ButtonBehavior, GlassCard):
    code = StringProperty()
    text = StringProperty()
    accent = ColorProperty(c(theme.LEAF_SOFT))
    current = BooleanProperty(False)


def bbch_dialog(title: str, db, callback, extra: list | None = None, current: int | None = None):
    """Escala BBCH casi a todo el ancho, agrupada por macroestadio en desplegables
    (se abre el del estado actual). Cada estado muestra su texto completo
    (cañas anuales y brotes laterales en líneas separadas)."""
    global _pick_open
    if _pick_open is not None:
        return _pick_open
    from kivy.core.window import Window
    from kivy.uix.scrollview import ScrollView
    from kivy.utils import escape_markup
    dialog = None
    stages = db.list_bbch()
    groups: dict[int, list] = {}
    for r in stages:
        groups.setdefault(ph.macro_of(r["code"]), []).append(r)
    opened = {ph.macro_of(current)} if current is not None else set()
    state = {}
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6), padding=(0, dp(2)))
    scroll = ScrollView(size_hint_y=None, height=Window.height * .64, do_scroll_x=False, bar_width=dp(4))
    scroll.add_widget(box)

    def pick(code):
        dialog.dismiss()
        callback(code)

    def toggle(head):
        if head.macro in opened:
            opened.discard(head.macro)
        else:
            opened.clear()          # acordeón: un macroestadio abierto a la vez
            opened.add(head.macro)
        build()
        Clock.schedule_once(lambda *_: scroll.scroll_to(head, padding=dp(4), animate=False), 0)

    def body(r) -> str:
        label = (escape_markup(r["label"]).replace(" · Laterales: ", "\n[b]Laterales:[/b] ")
                 .replace(" · Cañas: ", "\n[b]Cañas:[/b] "))
        for k in ("Cañas: ", "Cañas anuales: ", "Brotes laterales: ", "Laterales: "):
            if label.startswith(k):
                return f"[b]{k.strip()}[/b] " + label[len(k):]
        return label

    def build():
        box.clear_widgets()
        for t, sub, cb, *rest in (extra or []):
            row = PickRow(title=t, subtitle=sub or "", accent=rest[0] if rest else c(theme.LEAF_SOFT))
            row.action = lambda cb=cb: (dialog.dismiss(), cb())
            box.add_widget(row)
        for macro in sorted(groups):
            rows = groups[macro]
            bg, _fg = theme.stage_colors(rows[0]["code"])
            head = ScaleGroup(title=f"{macro} · {ph.MACRO_STAGES.get(macro, '')}", macro=macro,
                              count=f"{len(rows)} estados", accent=bg, expanded=macro in opened)
            head.bind(on_release=toggle)
            box.add_widget(head)
            if macro not in opened:
                continue
            for r in rows:
                row = ScaleRow(code=ph.code_str(r["code"]), text=body(r), accent=bg,
                               current=r["code"] == current)
                row.bind(on_release=lambda _w, code=r["code"]: pick(code))
                box.add_widget(row)
                if row.current:
                    state["current_row"] = row

    build()
    dialog = MDDialog(title=title, type="custom", content_cls=scroll, md_bg_color=DIALOG_BG,
                      size_hint=(.96, None),
                      buttons=[MDFlatButton(text="CERRAR", on_release=lambda *_: dialog.dismiss())])

    def closed(*_):
        global _pick_open
        _pick_open = None

    dialog.bind(on_dismiss=closed)
    _pick_open = dialog
    dialog.open()
    if state.get("current_row") is not None:   # mostrar el estado actual sin buscarlo
        Clock.schedule_once(lambda *_: scroll.scroll_to(state["current_row"], padding=dp(60),
                                                        animate=False), .15)
    return dialog


def current_profile() -> str:
    return (getattr(app(), "workspace", None) or {}).get("profile") or "id"


def pick_catalog(on_pick, profile: str | None = None, allow_none: str = ""):
    """Desplegable con el catálogo de variedades (I+D o Predio) + «Nueva variedad…».
    on_pick(nombre, código). allow_none: texto de la opción «sin variedad» (si se ofrece)."""
    import catalog
    a = app()
    profile = profile or current_profile()
    shared = a.workspaces.shared

    def new():
        from kivy.factory import Factory
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                           padding=(0, dp(8), 0, 0))
        f_name = Factory.Field(hint_text="Nombre de la variedad (ej.: Meeker)")
        f_code = Factory.Field(hint_text="Código para las fotos (opcional, ej.: MEE)")
        form.add_widget(f_name)
        form.add_widget(f_code)

        def ok(_f):
            if not catalog.add(shared, profile, f_name.text, f_code.text.upper()):
                a.toast("Escriba el nombre real de la variedad (no «Código n»).")
                return False
            on_pick(f_name.text.strip(), f_code.text.strip().upper())

        form_dialog("Nueva variedad", form, ok, "AGREGAR")

    items = []
    if allow_none:
        items.append((allow_none, "", lambda: on_pick("", "")))
    items += [(e["name"], f"Código {e['code']}" if e["code"] else "", lambda e=e: on_pick(e["name"], e["code"] or ""))
              for e in catalog.entries(shared, profile)]
    items.append(("+ Nueva variedad…", "Se guarda en el catálogo para la próxima vez", new))
    pick_dialog(f"Variedades · {'Predio' if profile == 'predio' else 'I+D'}", items)


def manage_catalog(on_change=None):
    """Ajustes › Registros: ver, agregar, cambiar el código o quitar variedades del catálogo."""
    import catalog
    a = app()
    profile = current_profile()
    shared = a.workspaces.shared

    def options(e):
        def set_code():
            from kivy.factory import Factory
            form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
            f = Factory.Field(hint_text="Código para las fotos", text=e["code"] or "")
            form.add_widget(f)

            def ok(_f):
                catalog.add(shared, profile, e["name"], f.text.upper())
                if on_change:
                    on_change()
            form_dialog(e["name"], form, ok)

        def remove():
            catalog.remove(shared, profile, e["name"])
            a.toast(f"«{e['name']}» quitada del catálogo (los registros no cambian)")
            if on_change:
                on_change()

        pick_dialog(e["name"], [("Cambiar código", e["code"] or "sin código", set_code),
                                ("Quitar del catálogo", "Los registros existentes no cambian", remove)])

    items = [(e["name"], f"Código {e['code']}" if e["code"] else "sin código", lambda e=e: options(e))
             for e in catalog.entries(shared, profile)]
    items.append(("+ Nueva variedad…", "", lambda: pick_catalog(lambda *_: on_change and on_change(),
                                                                profile)))
    pick_dialog(f"Catálogo de variedades · {'Predio' if profile == 'predio' else 'I+D'}", items)


def remember_variety(name: str, code: str = "", profile: str | None = None) -> None:
    """Variedad escrita a mano al crear un registro: queda en el catálogo (si es un nombre real)."""
    import catalog
    try:
        catalog.add(app().workspaces.shared, profile or current_profile(), name, code)
    except Exception:  # noqa: BLE001
        pass


class RoundThumb(Widget):
    """Miniatura con esquinas redondeadas dibujada con UNA instrucción (RoundedRectangle
    con textura, recortada «cover»). FitImage de KivyMD usa un stencil por imagen, que en
    GPUs modestas se paga en cada cuadro al desplazar listas."""
    source = StringProperty("")
    radius = NumericProperty(dp(10))

    def __init__(self, **kw):
        super().__init__(**kw)
        from kivy.graphics import Color, RoundedRectangle
        with self.canvas:
            self._bg = Color(*c(theme.LEAF_SOFT, .8))
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
        self.bind(pos=self._layout, size=self._layout, source=self._load)
        self._tex = None
        self._load()

    def _load(self, *_):
        self._tex = None
        if self.source:
            try:
                from kivy.core.image import Image as CoreImage
                self._tex = CoreImage(self.source).texture   # Kivy guarda la textura en caché
            except Exception:  # noqa: BLE001 - archivo dañado: queda el fondo suave
                self._tex = None
        self._bg.rgba = (1, 1, 1, 1) if self._tex else c(theme.LEAF_SOFT, .8)
        self._layout()

    def _layout(self, *_):
        r = self._rect
        r.pos, r.size, r.radius = self.pos, self.size, [self.radius]
        tex = self._tex
        if tex is None or not self.width or not self.height:
            r.texture = None
            return
        tw, th = tex.size
        scale = max(self.width / tw, self.height / th)
        cw, ch = self.width / scale, self.height / scale          # recorte centrado
        r.texture = tex.get_region((tw - cw) / 2, (th - ch) / 2, cw, ch)


def thumb_widget(path: str | None, size: int = 320, icon: str = "image-off-outline"):
    """Marcador inmediato (fondo suave con ícono); la miniatura se genera en segundo plano."""
    thumb = RoundThumb()
    from kivy.uix.label import Label
    from kivymd.icon_definitions import md_icons
    from kivymd import fonts_path
    # Ícono chico y nítido (fuente vectorial a su tamaño real, no una imagen estirada).
    mark = Label(text=md_icons.get(icon, ""), font_name=os.path.join(fonts_path, "materialdesignicons-webfont.ttf"),
                 font_size=dp(20), color=c(theme.LEAF, .45), size_hint=(None, None), size=(dp(28), dp(28)))
    thumb.add_widget(mark)
    # Centrado en el cuadro siguiente (con los valores finales de la lista ya armada).
    recenter = Clock.create_trigger(lambda dt: setattr(mark, "center", thumb.center))
    thumb.bind(pos=recenter, size=recenter)

    state = {"async": False}

    def ready(src):
        if src:
            thumb.remove_widget(mark)
            thumb.source = src
            if state["async"]:   # recién generada: aparece suave, sin salto
                from kivy.animation import Animation
                thumb.opacity = 0
                Animation(opacity=1, d=.15).start(thumb)

    if path and os.path.exists(path):
        app().thumb_async(path, size, ready)   # en caché: se dibuja ya, sin marcador
        state["async"] = True
    return thumb


def text_dialog(title: str, lines: list[str], highlight: str = "", actions=(), small=False):
    """Diálogo con texto largo que se ajusta (diagnósticos, errores)."""
    from kivymd.uix.scrollview import MDScrollView
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                      padding=(0, 0, 0, dp(8)))
    for text in lines:
        box.add_widget(MDLabel(text=text, font_style="Caption" if small else "Body2",
                               adaptive_height=True, theme_text_color="Custom",
                               text_color=c(theme.BERRY if highlight and highlight in text else theme.INK)))
    sv = MDScrollView(size_hint_y=None, height=dp(380))
    sv.add_widget(box)
    dialog = None

    def run(cb):
        return lambda *_: (dialog.dismiss(), cb())

    buttons = [MDFlatButton(text=t.upper(), on_release=run(cb)) for t, cb in actions]
    buttons.append(MDFlatButton(text="CERRAR", on_release=lambda *_: dialog.dismiss()))
    dialog = MDDialog(title=title, type="custom", content_cls=sv, md_bg_color=DIALOG_BG,
                      buttons=buttons)
    dialog.open()
    return dialog


def confirm(title: str, text: str, actions: list[tuple[str, callable]]):
    dialog = None

    def wrap(cb):
        def _run(*_):
            dialog.dismiss()
            if cb:
                cb()
        return _run

    buttons = [MDFlatButton(text="CANCELAR" if actions else "CERRAR", on_release=wrap(None))]
    buttons += [MDFlatButton(text=t.upper(), theme_text_color="Custom",
                             text_color=c(theme.BERRY if "ELIMIN" in t.upper() else theme.LEAF_DARK),
                             on_release=wrap(cb)) for t, cb in actions]
    dialog = MDDialog(title=title, text=text, buttons=buttons, md_bg_color=DIALOG_BG)
    dialog.open()
    return dialog


def form_dialog(title: str, content, on_ok, ok_text: str = "GUARDAR"):
    dialog = None

    def _ok(*_):
        if on_ok(content) is not False:
            dialog.dismiss()

    dialog = MDDialog(title=title, type="custom", content_cls=content, md_bg_color=DIALOG_BG, buttons=[
        MDFlatButton(text="CANCELAR", on_release=lambda *_: dialog.dismiss()),
        MDFlatButton(text=ok_text, theme_text_color="Custom", text_color=c(theme.LEAF_DARK),
                     on_release=_ok)])

    def fit(*_):
        # KivyMD 1.2 mide el diálogo una sola vez al abrir, antes de que los campos tomen
        # su alto final: el título quedaba encima del formulario. Se vuelve a medir.
        dialog.update_height()
        Clock.schedule_once(lambda *_: setattr(dialog, "height", dialog.ids.container.height), 0)

    content.bind(height=fit)
    dialog.open()
    Clock.schedule_once(fit, .05)
    return dialog


def list_dialog(title: str, rows: list[tuple[str, str]]):
    box = MDBoxLayout(orientation="vertical", adaptive_height=True)
    for a, b in rows:
        box.add_widget(TwoLineListItem(text=a, secondary_text=b))
    from kivymd.uix.scrollview import MDScrollView
    sv = MDScrollView(size_hint_y=None, height=dp(420))
    sv.add_widget(box)
    dialog = MDDialog(title=title, type="custom", content_cls=sv, md_bg_color=DIALOG_BG,
                      buttons=[MDFlatButton(text="CERRAR", on_release=lambda *_: dialog.dismiss())])
    dialog.open()


def bbch_tag_colors(code: int | None):
    """Del verde vegetativo al rojo frambuesa de la maduración."""
    return theme.stage_colors(code)


class TopBar(MDTopAppBar):
    """Barra superior translúcida con texto e iconos verde profundo."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Se asigna tras construir los ids internos (en la regla KV falla en KivyMD 1.2).
        Clock.schedule_once(lambda *_: setattr(self, "specific_text_color", c(theme.LEAF_DARK)))


class NavTile(ButtonBehavior, BoxLayout):
    name = StringProperty()
    text = StringProperty()
    active = BooleanProperty(False)


# ===========================================================================
# Home
# ===========================================================================
class SplashScreen(MDScreen):
    """Pantalla de apertura: logo animado, nombre y firma, igual que la pantalla de carga
    nativa de Android. La animación la maneja la app (main.on_start)."""


class HomeScreen(MDScreen):
    TITLES = {"sampling": "Muestreo semanal", "reports": "Informes", "preview": "Vista previa"}

    def on_tab(self, name: str):
        self.ids.tabs.current = name
        self.ids.bar.title = self.TITLES[name]
        getattr(self.ids, name).refresh()

    def refresh(self):
        for tab in self.TITLES:
            getattr(self.ids, tab).refresh()

    def refresh_current(self):
        self.update_banner()
        getattr(self.ids, self.ids.tabs.current or "sampling").refresh()
        Clock.schedule_once(lambda *_: self.update_drive_icon(), 0)

    # ------------------------------------------------- acceso rápido a Drive
    def _action(self, sources) -> object | None:
        for btn in self.ids.bar.ids.right_actions.children:
            if getattr(btn, "icon", None) in sources:
                return btn
        return None

    def _style_actions(self):
        if getattr(self, "_styled", False):
            return
        ai = self._action((theme.AI_BAR,))
        if ai is not None and ai.ids.lbl_ic._size[0]:   # el cerebro, más grande que el resto
            lbl = ai.ids.lbl_ic
            grow = dp(31) - lbl._size[0]
            lbl._size = [dp(31), dp(31)]
            lbl.y -= grow / 2
            self._styled = True

    def update_drive_icon(self, *_):
        """Drive con flecha (hay algo por subir), con check (al día) o tachado (sin cuenta)."""
        self._style_actions()
        if getattr(self, "_spin_ev", None):
            return   # subiendo: lo actualiza la animación
        btn = self._action([theme.DRIVE_UP, theme.DRIVE_OK, theme.DRIVE_OFF])
        if btn is None:
            return
        try:
            st = app().drive.status()
        except Exception:  # noqa: BLE001
            return
        btn.icon = (theme.DRIVE_OFF if not st["enabled"] else
                    theme.DRIVE_UP if st["pending"] or st["errors"] else theme.DRIVE_OK)

    def drive_quick(self):
        a = app()
        drive = a.drive
        if not drive.available:
            a.toast("El respaldo en Google Drive funciona en el teléfono (Android).")
            return
        if not drive.enabled:
            a.toast("Elija su cuenta de Google para respaldar en Drive")
            drive.connect(lambda ok, msg: Clock.schedule_once(lambda *_: (a.toast(msg), self.update_drive_icon())))
            return
        st = drive.status()
        todo = st["pending"] + st["errors"]
        backup = "Todo respaldado" if not todo else (f"{todo} foto por respaldar" if todo == 1
                                                     else f"{todo} fotos por respaldar")
        raw = a.workspaces.shared.get_setting("sync_last") or ""
        stamp, _, msg = raw.partition(" · ")
        failed = msg.startswith("No se pudo")
        sync = ("Sin sincronizar aún" if not raw else
                f"Falló {when_text(stamp)}" if failed else f"Sincronizado {when_text(stamp)}")
        btn = self._action([theme.DRIVE_UP, theme.DRIVE_OK, theme.DRIVE_OFF] + theme.DRIVE_SPIN)
        if btn is not None:
            anchor = btn.to_window(btn.center_x, btn.y)
        else:
            from kivy.core.window import Window
            anchor = (Window.width - dp(70), Window.height - dp(60))
        DriveDial(anchor, [
            ("cloud-upload-outline" if todo else "cloud-check-outline", theme.BERRY,
             str(todo) if todo else "", backup, bool(st["errors"]), self.drive_backup_now),
            ("sync", theme.LEAF, "", sync, failed, self.drive_sync_now),
        ]).open()

    def drive_backup_now(self):
        a = app()
        if getattr(self, "_spin_ev", None):
            a.toast("Trabajando con Google Drive…")
            return
        st = a.drive.status()
        if not st["pending"] and not st["errors"]:
            a.toast("Todo está respaldado en Google Drive ✓")
        a.drive.retry_errors()   # reintenta errores y sube lo pendiente (en segundo plano)
        self._start_spin()

    def drive_sync_now(self):
        """Recibe lo hecho en el PC, la web u otro teléfono y envía lo de aquí (y baja todas
        las fotos pendientes)."""
        a = app()
        if getattr(a, "_syncing", False):
            a.toast("Ya se está sincronizando…")
            return
        a.toast("Sincronizando con sus otros dispositivos…")
        a.run_sync(manual=True)
        self._start_spin(report=False)

    def _start_spin(self, report: bool = True):
        import time as _t
        btn = self._action([theme.DRIVE_UP, theme.DRIVE_OK, theme.DRIVE_OFF] + theme.DRIVE_SPIN)
        if btn is None:
            return
        state = {"k": 0, "t0": _t.monotonic()}

        def tick(_dt):
            state["k"] = (state["k"] + 1) % len(theme.DRIVE_SPIN)
            btn.icon = theme.DRIVE_SPIN[state["k"]]
            drive = app().drive
            if _t.monotonic() - state["t0"] > 1.2 and not drive.running \
                    and not getattr(app(), "_syncing", False):
                self._spin_ev.cancel()
                self._spin_ev = None
                st = drive.status()
                btn.icon = theme.DRIVE_UP if st["pending"] or st["errors"] else theme.DRIVE_OK
                if report:     # la sincronización avisa su propio resumen
                    app().toast("Todo respaldado en Google Drive ✓" if btn.icon == theme.DRIVE_OK else
                                st.get("message") or "Quedan archivos por subir")

        self._spin_ev = Clock.schedule_interval(tick, .1)

    def update_banner(self):
        """Franja bajo la barra: en qué ensayo o predio se está trabajando."""
        ws = getattr(app(), "workspace", None)
        if ws:
            from workspaces import Workspaces
            self.ids.ws_banner.text = f"{Workspaces.title(ws)}  ·  {ws['code']}"
            self.ids.ws_banner.icon = "flask-outline" if ws["profile"] == "id" else "barn"


class StartIcon(ButtonBehavior, BoxLayout):
    """Botón de forma libre (ícono a línea sobre su burbuja) con su nombre debajo."""
    source = StringProperty()
    bubble = StringProperty("")
    glow = StringProperty("")
    glow_level = NumericProperty(.55)   # brillo que «respira» (Entrenador IA)
    label = StringProperty()
    color = ColorProperty([0, 0, 0, 1])
    diameter = NumericProperty(dp(130))
    lift = NumericProperty(0)           # animación de entrada (desplazamiento hacia abajo)
    reveal = NumericProperty(1)         # animación de entrada (opacidad)
    bob = NumericProperty(0)            # flotación suave mientras se ve el inicio
    pulse = NumericProperty(1)          # la sombra (burbuja) «respira» al flotar


class StatusPill(Widget):
    text = StringProperty()
    color = ColorProperty([0, 0, 0, 1])


class GoogleButton(ButtonBehavior, FloatLayout):
    """Botón «Inicia sesión con Google» (blanco, con la G de colores)."""
    text = StringProperty("Inicia sesión con Google")


class StartScreen(MDScreen):
    """Lo primero que se ve al abrir la app: I+D, Predio, Entrenador IA y la cuenta de Google."""
    _animated = False
    sync_angle = NumericProperty(0)    # giro del botón sincronizar mientras trabaja

    def sync_now(self):
        """Botón junto al engranaje: trae ya lo de la cuenta de Google (otros equipos)."""
        a = app()
        if not (a.db.get_setting("drive_enabled", False) and a.drive.available):
            a.run_sync(manual=True)        # avisa que falta conectar Google Drive
            return
        if not getattr(a, "_syncing", False):
            a.toast("Sincronizando con Google Drive…")
        a.run_sync(manual=True)
        if getattr(self, "_spin_ev", None) is None:
            self._spin_ev = Clock.schedule_interval(self._spin, 1 / 30)

    def _spin(self, *_):
        if getattr(app(), "_syncing", False):
            self.sync_angle = (self.sync_angle - 9) % 360
            return
        self.sync_angle = 0
        self._spin_ev.cancel()
        self._spin_ev = None
        self.refresh()

    def on_pre_enter(self, *_):
        if not StartScreen._animated:      # animación de entrada: solo la primera vez
            StartScreen._animated = True
            self._prepare_intro()
        # La pantalla aparece al instante; los textos (consultas a la base) justo después.
        Clock.schedule_once(lambda *_: self.refresh(), 0)

    def on_enter(self, *_):
        delay = 0
        if getattr(self, "_intro_ready", False):
            self._intro_ready = False
            self._play_intro()
            delay = 1.0
        self._breath_ev = Clock.schedule_once(lambda *_: self._breathe(), delay)

        self._t0 = time.monotonic()
        self._float_ev = Clock.schedule_interval(self._float, 1 / 30)

    FLOAT = ((0.0, "ic_id"), (1.6, "ic_predio"), (3.2, "ic_ai"), (4.8, "ic_nb"))   # desfase de cada ícono

    def _float(self, *_):
        """Flotación suave y continua de los íconos (30 cuadros por segundo: liviano)."""
        t = time.monotonic() - self._t0
        for phase, key in self.FLOAT:
            w = self.ids[key]
            k = math.sin(t * 1.5 + phase)
            w.bob = dp(4) * k
            w.pulse = 1 + .035 * math.sin(t * 1.5 + phase - .9)

    def on_leave(self, *_):
        if getattr(self, "_float_ev", None):
            self._float_ev.cancel()
        if getattr(self, "_breath_ev", None):
            self._breath_ev.cancel()
        if getattr(self, "_breath", None):
            self._breath.cancel(self.ids.ic_ai)
            self._breath = None

    # ------------------------------------------------------------ animación
    def _prepare_intro(self):
        for w in (self.ids.ic_id, self.ids.ic_predio, self.ids.ic_ai, self.ids.ic_nb):
            w.reveal, w.lift = 0, dp(46)
        self.ids.logo.opacity = 0
        self._intro_ready = True

    def _play_intro(self):
        from kivy.animation import Animation
        logo = self.ids.logo
        h = logo.height
        logo.height = h * .7
        (Animation(opacity=1, height=h * 1.06, d=.32, t="out_cubic")
         + Animation(height=h, d=.16, t="in_out_sine")).start(logo)
        for i, w in enumerate((self.ids.ic_id, self.ids.ic_predio, self.ids.ic_ai, self.ids.ic_nb)):
            anim = Animation(d=.12 + .11 * i) + Animation(reveal=1, lift=0, d=.38, t="out_back")
            anim.start(w)

    def _breathe(self):
        from kivy.animation import Animation
        if getattr(self, "_breath", None):
            return
        # Tres «respiraciones» y queda quieto: una animación sin fin obliga a redibujar la
        # pantalla completa 60 veces por segundo y resta fluidez al resto.
        step = Animation(glow_level=1, d=1.4, t="in_out_sine") + Animation(glow_level=.5, d=1.4, t="in_out_sine")
        anim = step + step + step + Animation(glow_level=.8, d=.8)
        self._breath = anim
        anim.start(self.ids.ic_ai)

    # --------------------------------------------------------------- textos
    @staticmethod
    def _greeting() -> str:
        h = _dt.datetime.now().hour
        return "Buenos días" if 5 <= h < 12 else "Buenas tardes" if 12 <= h < 20 else "Buenas noches"

    def refresh(self):
        a = app()
        from workspaces import Workspaces
        name = (a.db.get_setting("user_name") or "").strip()
        self.ids.greeting.text = f"{self._greeting()}, {name}" if name else f"{self._greeting()} · toque para poner su nombre"
        ws = getattr(a, "workspace", None)
        try:
            units = a.db.list_varieties()
            done = a.db.query_one(
                "SELECT COUNT(*) AS n FROM observations o JOIN varieties v ON v.id=o.variety_id "
                "WHERE o.week_id=? AND o.bbch_code IS NOT NULL AND v.active=1", (a.week["id"],))["n"]
            what = {"predio": "sectores", "tratamientos": "parcelas"}.get(
                (ws or {}).get("kind") if (ws or {}).get("kind") == "tratamientos" else (ws or {}).get("profile"),
                "registros")
            self.ids.week_lbl.text = (f"Semana {ph.week_of_year(a.week)} · {done} de {len(units)} "
                                      f"{what} · {Workspaces.title(ws)}" if ws and units else
                                      (f"Último usado: {Workspaces.title(ws)} ({ws['code']})" if ws else ""))
            self.ids.week_bar.progress = done / len(units) if units else 0
        except Exception:  # noqa: BLE001 - nunca bloquear el inicio
            self.ids.week_lbl.text = ""
        self._pills()
        self._postit()
        drive = a.drive
        st = drive.status()
        if st["enabled"]:
            self.ids.google_btn.text = "Cambiar cuenta de Google"
        else:
            self.ids.google_btn.text = "Inicia sesión con Google"

    def _pills(self):
        a = app()
        box = self.ids.pills
        box.clear_widgets()
        pills = []
        try:
            st = a.drive.status()
            if not st["enabled"]:
                pills.append(("Drive sin conectar", theme.MUTED))
            elif st["errors"]:
                pills.append((f"Drive: {st['errors']} con error", theme.WARN))
            elif st["pending"]:
                pills.append((f"Drive: {st['pending']} por subir", theme.WARN))
            else:
                pills.append(("Drive al día", theme.LEAF))
            last = a.db.query_one("SELECT MAX(observed_at) AS t FROM observations WHERE bbch_code IS NOT NULL")
            if last and last["t"]:
                days = (_dt.date.today() - _dt.date.fromisoformat(last["t"][:10])).days
                when = "hoy" if days <= 0 else "ayer" if days == 1 else f"hace {days} días"
                pills.append((f"Último registro: {when}", theme.BERRY))
            n_ai = sum(a.db.reference_counts().values())
            pills.append((f"IA: {n_ai} fotos", "#3A6BFF"))
        except Exception:  # noqa: BLE001
            pass
        for text, col in pills:
            pill = StatusPill(text=text, color=c(col))
            pill.ids.lbl.texture_update()
            pill.width = dp(26) + pill.ids.lbl.texture_size[0]
            box.add_widget(pill)
        box.width = sum(p.width for p in box.children) + dp(6) * max(0, len(box.children) - 1)

    def ask_name(self):
        from kivy.factory import Factory
        a = app()
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
        field = Factory.Field(hint_text="Su nombre (para el saludo)", text=a.db.get_setting("user_name") or "")
        form.add_widget(field)

        def ok(_f):
            a.db.set_setting("user_name", field.text.strip())
            self.refresh()

        form_dialog("¿Cómo se llama?", form, ok)

    def open_profile(self, profile: str):
        app().open_workspaces(profile)

    # ------------------------------------------------------------ pendientes de hoy
    def _postit(self):
        from ui.pending import today_tasks
        try:
            self._tasks = today_tasks()
        except Exception:  # noqa: BLE001 - nunca bloquear el inicio
            self._tasks = []
        post = self.ids.postit
        lines = [t["short"] for t in self._tasks if not t["done"]]
        was = bool(post.lines)
        post.lines = lines
        if lines and not was:
            post.wobble()

    def open_tasks(self):
        from ui.pending import TasksSheet, today_tasks
        TasksSheet(today_tasks(), on_close=self._postit).open()

    def open_ai(self):
        app().open_ai_lab()

    def connect_google(self):
        a = app()
        if not a.drive.available:
            a.toast("La cuenta de Google se conecta en el teléfono (Android).")
            return
        a.toast("Elija la cuenta de Google y acepte el permiso")

        def done(ok, msg):
            Clock.schedule_once(lambda *_: (a.toast(msg), self.refresh()))

        a.drive.connect(done)

    def continue_local(self):
        app().enter_home()


class SectorRow(GlassButton):
    variety_id = NumericProperty(0)
    badge = StringProperty()
    title = StringProperty()
    subtitle = StringProperty()
    done = BooleanProperty(False)
    screen = ObjectProperty(None, allownone=True)


def sector_map_block(box, plan, status, selected, on_select):
    """Plano del predio con los equipos de riego arriba, centrados: son la leyenda de
    colores y, al tocarlos, acercan el equipo entero en el mismo plano (ahí se toca el
    sector); tocar de nuevo el equipo elegido vuelve a la vista general. Devuelve el plano."""
    from kivy.uix.anchorlayout import AnchorLayout
    from ui.sector_map import SectorMap, equipo_chip
    equipos = sorted({s["equipo"] for s in plan["sectors"]})
    from ui.mapview import default_layer, remember_layer
    mp = SectorMap(plan, on_select=on_select, size_hint_y=None, height=dp(200), zoomable=True)
    mp.status, mp.selected = status, selected
    mp.satellite = bool(plan.get("geo")) and default_layer() == "sat"
    mp.bind(width=lambda w, v: setattr(w, "height", max(dp(200), v * plan["h"] / plan["w"] * 1.1)))

    row = BoxLayout(size_hint=(None, None), height=dp(34), spacing=dp(6))
    chips = {}

    def show(eq):
        eq = 0 if mp.focused == f"E{eq}" else eq          # tocar el elegido: vista general
        mp.focus(f"E{eq}" if eq else "")
        for k, chip in chips.items():
            if k != "sat":
                chip.selected = k == eq

    for eq in equipos:
        col, light = equipo_chip(eq)
        chip = PillButton(text=f"Equipo {eq}", font_size="13sp", bold=True,
                          size_hint=(None, None), height=dp(34),
                          bg_on=col, fg_on=c("#FFFFFF") if light else c(theme.INK),
                          bg_off=[*col[:3], .28], fg_off=c(theme.INK), edge=[*col[:3], .9])
        chip.text_size = (None, None)
        chip.texture_update()
        chip.width = chip.texture_size[0] + dp(22)
        chip.bind(on_release=lambda *_, eq=eq: show(eq))
        chips[eq] = chip
        row.add_widget(chip)
    if plan.get("geo"):              # fondo: imagen satelital o plano solo (se recuerda)
        sat = PillButton(text="Satélite", font_size="13sp", bold=True, size_hint=(None, None), height=dp(34),
                         bg_on=c(theme.LEAF_DARK), fg_on=c("#FFFFFF"), bg_off=c("#FFFFFF", .6),
                         fg_off=c(theme.LEAF_DARK), edge=c(theme.LEAF_DARK, .6))
        sat.selected = mp.satellite
        sat.text_size = (None, None)
        sat.texture_update()
        sat.width = sat.texture_size[0] + dp(22)

        def flip(*_):
            mp.satellite = not mp.satellite
            sat.selected = mp.satellite
            remember_layer("sat" if mp.satellite else "osm")
        sat.bind(on_release=flip)
        chips["sat"] = sat
        row.add_widget(sat)
    row.width = sum(ch.width for ch in chips.values()) + row.spacing * max(0, len(chips) - 1)
    holder = AnchorLayout(anchor_x="center", size_hint_y=None, height=dp(34))
    holder.add_widget(row)
    box.add_widget(holder)
    box.add_widget(mp)
    full = AnchorLayout(anchor_x="right", size_hint_y=None, height=dp(34))
    full_btn = PillButton(text="Pantalla completa", font_size="13sp", size_hint=(None, None), height=dp(32),
                          width=dp(150), bg_off=c("#FFFFFF", .7), fg_off=c(theme.LEAF_DARK),
                          edge=c(theme.LEAF_DARK, .4))
    full_btn.bind(on_release=lambda *_: sector_map_fullscreen(plan, mp, on_select))
    full.add_widget(full_btn)
    box.add_widget(full)
    return mp


def sector_map_fullscreen(plan, small, on_select):
    """Plano a pantalla completa: zoom con dos dedos, girar el teléfono (horizontal) y tocar
    sectores; lo elegido vuelve al plano de la vista previa."""
    from kivy.uix.modalview import ModalView
    from kivymd.uix.button import MDIconButton
    from android_bridge import allow_rotation
    from ui.sector_map import SectorMap
    view = ModalView(size_hint=(1, 1), auto_dismiss=True, background_color=(0, 0, 0, .85))
    root = MDBoxLayout(orientation="vertical", md_bg_color=DIALOG_BG)
    head = MDBoxLayout(adaptive_height=True, padding=(dp(14), dp(6)), spacing=dp(8))
    title = MDLabel(text=plan.get("name") or "Plano de sectores", font_style="H6", bold=True,
                    adaptive_height=True, pos_hint={"center_y": .5})
    head.add_widget(title)
    head.add_widget(MDIconButton(icon="close", pos_hint={"center_y": .5}, on_release=lambda *_: view.dismiss()))
    root.add_widget(head)
    info = MDLabel(text="Dos dedos para acercar · toque un sector · gire el teléfono para verlo horizontal",
                   font_style="Caption", adaptive_height=True, padding=(dp(14), dp(2)),
                   theme_text_color="Custom", text_color=c(theme.MUTED))
    root.add_widget(info)

    def pick(sid):
        s = next((x for x in plan["sectors"] if x["id"] == sid), None)
        if s:
            info.text = f"{s['nombre']} · {s.get('ha') or '?'} ha · {', '.join(s.get('variedades') or [])}"
        small.selected = sid
        if on_select:
            on_select(sid)

    big = SectorMap(plan, on_select=pick, zoomable=True)
    big.status, big.selected, big.satellite = small.status, small.selected, small.satellite
    root.add_widget(big)
    view.add_widget(root)
    allow_rotation(True)
    view.bind(on_dismiss=lambda *_: allow_rotation(False))
    view.open()
    if small.selected:
        Clock.schedule_once(lambda *_: big.focus(small.selected), .2)


def no_map_card(box, name: str) -> None:
    """Predio sin plano cargado: aviso amable (el resto de la pantalla sigue igual)."""
    card = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(4),
                       padding=(dp(14), dp(12)), md_bg_color=c(theme.LEAF_SOFT, .35),
                       radius=[dp(16)])
    card.add_widget(MDIcon(icon="map-search-outline", font_size="34sp", halign="center",
                           size_hint_y=None, height=dp(40), theme_text_color="Custom",
                           text_color=c(theme.LEAF)))
    card.add_widget(MDLabel(text=f"El plano de {name} aún va en camino", halign="center",
                            font_style="Subtitle1", bold=True, adaptive_height=True,
                            theme_text_color="Custom", text_color=c(theme.LEAF_DARK)))
    card.add_widget(MDLabel(text="Todavía no hay mapa cargado para este predio. Estamos "
                                 "trazando sus sectores: llegará en una próxima actualización. "
                                 "Mientras tanto, todo funciona con la lista de siempre.",
                            halign="center", font_style="Caption", adaptive_height=True,
                            theme_text_color="Custom", text_color=c(theme.MUTED)))
    box.add_widget(card)


def year_field(after, text=""):
    """Campo «Año de plantación» justo debajo de `after` (fichas de predio)."""
    from kivy.factory import Factory
    f = Factory.Field(hint_text="Año de plantación (opcional)", input_filter="int",
                      max_text_length=4, text=str(text or ""))
    box = after.parent
    box.add_widget(f, index=box.children.index(after))
    return f


def unit_dialog(on_saved=None, sector: int = 0, irrigation: int = 0):
    """Nuevo sector de predio: se guarda como «Equipo de riego n, sector m» con su
    variedad, año de plantación y código. Desde el plano llega con equipo y sector."""
    a = app()
    form = VarietyForm()
    form.ids.name.hint_text = "Variedad"
    form.ids.code.hint_text = "Código (opcional, va en las fotos)"
    year = year_field(form.ids.code)
    form.sector, form.irrigation = sector or 0, irrigation or 0
    form._sync_location_buttons()

    def ok(f):
        try:
            a.db.save_unit(f.ids.name.text, f.ids.code.text.strip(),
                           f.sector or None, f.irrigation or None,
                           plant_year=year.text.strip() or None)
        except ValueError as exc:
            a.toast(str(exc))
            return False
        remember_variety(f.ids.name.text, f.ids.code.text.strip(), "predio")
        a.toast(f"Agregado: {ph.unit_name(f.sector, f.irrigation)} · {f.ids.name.text.strip()}")
        if on_saved:
            on_saved()
        a.refresh_home()

    form_dialog("Crear sector" if sector and irrigation else "Nuevo sector", form, ok, "AGREGAR")


class SectorsScreen(MDScreen):
    """Predio: sectores (variedad + sector + equipo de riego) a muestrear esta semana.
    Con plano (El Amanecer) se trabaja sobre el mapa: los sectores creados se ven con su
    color; tocar uno muestra sus variedades (para registrarlas) y tocar uno vacío lo crea
    (variedad, año de plantación y código). Sin plano, la lista de siempre."""
    sel = StringProperty("")

    def on_pre_enter(self, *_):
        self.refresh()

    def delete_sector(self, variety_id: int):
        """Quitar una variedad del sector: archivar (conserva registros y fotos) o eliminar."""
        a = app()
        v = a.db.get_variety(variety_id)
        if not v:
            return
        label = f"{v['name']} · {ph.unit_label(v)}" if v.get("cultivar") else v["name"]

        def done(msg):
            a.toast(msg)
            self.refresh()
            a.refresh_home()

        def archive():
            a.db.delete_variety(variety_id)
            done(f"«{label}» archivada (historial conservado)")

        def purge():
            a.db.delete_variety(variety_id, purge=True)
            done(f"«{label}» eliminada")

        confirm(f"Quitar «{label}»",
                "Archivar la saca del plano y del muestreo, pero conserva sus registros y fotos "
                "(recomendado). Eliminar borra definitivamente todos sus registros.",
                [("Archivar", archive), ("Eliminar", purge)])

    def _units(self):
        a = app()
        units = sorted(a.db.list_varieties(),
                       key=lambda v: (v["irrigation"] or 99, v["sector"] or 99, v["name"].lower()))
        done = {}
        for v in units:
            obs = a.db.get_observation(v["id"], a.week["id"])
            done[v["id"]] = obs["bbch_code"] if obs else None
        return units, done

    def _row(self, v, code, title=None):
        a = app()
        where = "" if title else (ph.unit_place(v) or "")
        row = SectorRow(variety_id=v["id"], screen=self, done=code is not None,
                        badge=ph.location_tag(v) or "—", title=title or ph.unit_main(v),
                        subtitle=(f"{where} · " if where else "") + (
                            f"BBCH {ph.code_str(code)} registrado" if code is not None
                            else "sin registro esta semana"))
        row.bind(on_release=lambda w: a.open_observation(w.variety_id, a.week["id"]))
        return row

    def refresh(self):
        from ui.sector_map import load_map
        a = app()
        ws = a.workspace or {}
        self.ids.bar.title = ws.get("name", "Sectores")
        units, done = self._units()
        self.ids.week_note.text = ph.week_long(a.week)    # la semana, al pie
        mbox, box = self.ids.map_box, self.ids.rows
        fast_clear(mbox)
        fast_clear(box)
        plan = load_map(ws.get("code"))
        self._plan = plan
        if not plan:
            no_map_card(mbox, ws.get("name") or "este predio")
            for v in units:
                box.add_widget(self._row(v, done[v["id"]]))
            self.ids.add_btn.text = "+ Nuevo sector"
            if not units:
                box.add_widget(MDLabel(text="Aún no hay sectores: cree el primero con «+ Nuevo "
                                            "sector» (variedad, sector y equipo de riego).",
                                       font_style="Body2", adaptive_height=True,
                                       theme_text_color="Custom", text_color=c(theme.MUTED)))
            return
        known = {s["id"]: s for s in plan["sectors"]}
        self._by_sector = {sid: [] for sid in known}
        loose = []
        for v in units:
            sid = f"E{v['irrigation'] or 0}-S{v['sector'] or 0}"
            (self._by_sector[sid] if sid in known else loose).append(v)
        self._done = done
        status = {sid: {"data": True, "dot": any(done[v["id"]] is not None for v in vs)}
                  for sid, vs in self._by_sector.items() if vs}

        if self.sel not in known:
            self.sel = ""
        self._map = sector_map_block(mbox, plan, status, self.sel, self.pick)
        self._fill(self.sel)
        if loose:
            box.add_widget(MDLabel(text="Otros (sin ubicar en el plano)", font_style="Caption",
                                   bold=True, adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))
            for v in loose:
                box.add_widget(self._row(v, done[v["id"]]))
        self.ids.add_btn.text = "+ Nuevo sector (sin plano)"

    def pick(self, sid):
        """Toque en el plano: muestra el sector y, si aún no existe, abre su creación."""
        self.sel = sid
        self._fill(sid)
        if not self._by_sector.get(sid):
            self.add_here(sid)

    def _fill(self, sid):
        box = getattr(self, "_panel", None)
        if box is None:
            box = self._panel = MDBoxLayout(orientation="vertical", adaptive_height=True,
                                            spacing=dp(8))
        if box.parent is not None:
            box.parent.remove_widget(box)
        self.ids.map_box.add_widget(box)
        fast_clear(box)
        sec = next((s for s in self._plan["sectors"] if s["id"] == sid), None)
        if sec is None:
            box.add_widget(MDLabel(text="Toque un sector del plano (tocando un equipo arriba del plano se acerca) para "
                                        "registrarlo o crearlo.", font_style="Body2",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))
            return
        box.add_widget(MDLabel(text=f"Equipo de riego {sec['equipo']} · sector {sec['sector']}",
                               font_style="Subtitle1", bold=True, adaptive_height=True,
                               theme_text_color="Custom", text_color=c(theme.LEAF_DARK)))
        info = []
        if sec.get("ha"):
            info.append(f"{sec['ha']:.2f} ha".replace(".", ","))
        if sec.get("hileras"):
            info.append(f"{sec['hileras']} hileras")
        if sec.get("variedades"):
            info.append("plano: " + ", ".join(sec["variedades"]))
        if info:
            box.add_widget(MDLabel(text=" · ".join(info), font_style="Caption", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
        vs = self._by_sector.get(sid) or []
        for v in vs:
            box.add_widget(self._row(v, self._done.get(v["id"]), title=ph.unit_label(v)))
        if not vs:
            box.add_widget(MDLabel(text="Este sector aún no está creado.", font_style="Body2",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.BERRY)))
        from kivy.factory import Factory
        add = Factory.GhostButton(icon="plus", text="Crear este sector" if not vs else
                                  "Agregar otra variedad a este sector")
        add.bind(on_release=lambda *_: self.add_here(sid))
        box.add_widget(add)

    def add_here(self, sid):
        sec = next(s for s in self._plan["sectors"] if s["id"] == sid)
        unit_dialog(on_saved=self.refresh, sector=sec["sector"], irrigation=sec["equipo"])

    def add_sector(self):
        unit_dialog(on_saved=self.refresh)

    def edit_sector(self, variety_id: int):
        app().open_variety(variety_id)


class WorkspaceBanner(GlassButton):
    text = StringProperty()
    icon = StringProperty("flask-outline")


class WorkspaceRow(GlassButton):
    title = StringProperty()
    subtitle = StringProperty()
    code = StringProperty()
    profile = StringProperty("id")
    current = BooleanProperty(False)
    ws = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


class WorkspaceTile(GlassButton):
    """Vista en cuadrícula: el mismo ensayo/predio como baldosa (código en un círculo)."""
    title = StringProperty()
    subtitle = StringProperty()
    code = StringProperty()
    profile = StringProperty("id")
    current = BooleanProperty(False)
    ws = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


class WorkspacesScreen(MDScreen):
    """Menú inicial: perfil I+D (ensayos) o Predio, y la lista para elegir dónde trabajar."""
    profile = StringProperty("id")
    show_archived = BooleanProperty(False)
    view_mode = StringProperty("list")   # «list» o «grid» (se recuerda)

    def on_kv_post(self, *_):
        try:
            self.view_mode = app().db.get_setting("workspaces_view", "list") or "list"
        except Exception:  # noqa: BLE001
            pass

    def toggle_view(self):
        self.view_mode = "grid" if self.view_mode == "list" else "list"
        app().db.set_setting("workspaces_view", self.view_mode)
        self.refresh()

    menu_mode = BooleanProperty(False)   # abierto desde el inicio: solo I+D o solo Predio

    def on_pre_enter(self, *_):
        ws = getattr(app(), "workspace", None)
        if not self.menu_mode and ws:
            self.profile = ws["profile"]
        self.show_archived = False
        self.refresh()

    def set_profile(self, profile: str):
        self.profile = profile
        self.show_archived = False
        self.refresh()

    def toggle_archived(self):
        self.show_archived = not self.show_archived
        self.refresh()

    def _stats(self, ws) -> str:
        from workspaces import KINDS
        a = app()
        parts = [KINDS.get(ws["kind"], ws["kind"])]
        try:
            db = a.open_db(ws)
            n = db.query_one("SELECT COUNT(*) AS n FROM varieties WHERE active=1")["n"]
            one, many = {"tratamientos": ("parcela", "parcelas"), "predio": ("sector", "sectores")
                         }.get(ws["kind"], ("variedad", "variedades"))
            parts.append(f"{n} {one if n == 1 else many}")
            last = db.query_one("SELECT w.start_date FROM observations o JOIN sampling_weeks w "
                                "ON w.id = o.week_id WHERE o.bbch_code IS NOT NULL "
                                "ORDER BY w.start_date DESC LIMIT 1")
            if last:
                parts.append(f"último registro: {ph.week_title(last['start_date'])}")
        except Exception:  # noqa: BLE001 - nunca bloquear el menú por una base dañada
            pass
        return " · ".join(parts)

    def refresh(self):
        a = app()
        box = self.ids.ws_list
        fast_clear(box)
        items = a.workspaces.list(self.profile, archived=self.show_archived)
        cur = getattr(a, "workspace", None) or {}
        from workspaces import KINDS
        rows = []
        for ws in items:
            cls = WorkspaceTile if self.view_mode == "grid" else WorkspaceRow
            row = cls(title=ws["name"], code=ws["code"], profile=ws["profile"],
                               subtitle=KINDS.get(ws["kind"], ws["kind"]),
                               current=ws["id"] == cur.get("id"), ws=ws, screen=self)
            row.bind(on_release=lambda w: self.choose(w.ws))
            box.add_widget(row)
            rows.append(row)
        # Las estadísticas abren la base de cada ensayo: una por cuadro, ya con la lista a la vista.
        def fill(i=0):
            if i < len(rows) and rows[i].parent is box:
                rows[i].subtitle = self._stats(rows[i].ws)
                Clock.schedule_once(lambda *_: fill(i + 1), 0)
        Clock.schedule_once(lambda *_: fill(), 0.05)
        if not items:
            box.add_widget(MDLabel(text="No hay archivados." if self.show_archived else
                                   "Aún no hay nada aquí: toque + para crear el primero.",
                                   font_style="Caption", adaptive_height=True, halign="center",
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
        is_id = self.profile == "id"
        self.ids.hint.text = ("Ensayos de investigación y desarrollo: cada uno con sus variedades, "
                              "semanas, fotos, mediciones e informes por separado." if is_id else
                              "Predios comerciales: fenología por variedad, sector y equipo de riego.")
        if self.show_archived:
            self.ids.hint.text = "Archivados: no aparecen en la lista, pero sus datos se conservan."
        self.ids.add_btn.opacity, self.ids.add_btn.disabled = (0, True) if self.show_archived else (1, False)
        self.ids.archived_btn.text = "Volver a la lista" if self.show_archived else "Ver archivados"

    def choose(self, ws):
        if ws["archived"]:
            app().toast("Está archivado: desarchívelo con ⋮ para trabajar en él.")
            return
        # Predio: primero la lista de sectores a muestrear; ensayo: el muestreo semanal.
        app().open_workspace(ws["id"], target="sectors" if ws["profile"] == "predio" else "home")

    def item_menu(self, ws):
        a = app()

        def rename():
            from kivy.factory import Factory
            form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
            form.add_widget(Factory.Field(hint_text="Nombre", text=ws["name"]))

            def ok(f):
                try:
                    a.workspaces.rename(ws["id"], f.children[0].text)
                except ValueError as exc:
                    a.toast(str(exc))
                    return False
                a.workspace_renamed(ws["id"])
                self.refresh()

            form_dialog("Cambiar nombre", form, ok)

        def archive(flag):
            if flag and ws["id"] == (a.workspace or {}).get("id"):
                a.toast("Primero cambie a otro ensayo o predio.")
                return
            a.workspaces.set_archived(ws["id"], flag)
            self.refresh()

        def move():
            predios = a.workspaces.list("predio")
            if not predios:
                a.toast("No hay predios: cree uno primero en el menú Predio.")
                return

            def pick(dst):
                if a.workspaces.records(dst):
                    a.toast(f"«{dst['name']}» ya tiene registros: solo se traspasa a un predio vacío.")
                    return
                text = (f"Todo lo de «{ws['name']}» ({ws['code']}) pasa al predio «{dst['name']}» "
                        f"({dst['code']}): sectores, registros, fotos y mediciones, sin copiar ni "
                        f"volver a subir nada.\n\nLas fotos cambian su código a {dst['code']} en el "
                        f"teléfono, en la galería y en Google Drive (en el próximo respaldo). "
                        f"«{ws['name']}» queda vacío en I+D.")
                Clock.schedule_once(lambda *_: confirm(
                    f"Mover a {dst['name']}", text,
                    [("Mover", lambda: a.move_to_predio(ws, dst))]), .3)

            # El menú anterior se está cerrando: el siguiente diálogo, un instante después.
            Clock.schedule_once(lambda *_: pick_dialog("¿A qué predio?", [
                (p["name"], f"Código {p['code']}", lambda p=p: pick(p)) for p in predios]), .3)

        items = [("Cambiar nombre", f"Código {ws['code']} (no cambia)", rename)]
        if ws["profile"] == "id" and not ws["archived"]:
            items.append(("Mover a Predio…", "Si estos datos son de un predio (p. ej. tras actualizar)",
                          move))
        if ws["archived"]:
            items.append(("Desarchivar", "Vuelve a la lista", lambda: archive(False)))
        else:
            items.append(("Archivar", "Ocultar de la lista; los datos se conservan", lambda: archive(True)))
        pick_dialog(f"{ws['name']} · {ws['code']}", items)

    def new_item(self):
        a = app()
        from kivy.factory import Factory
        from workspaces import suggest_code
        is_id = self.profile == "id"
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                           padding=(0, dp(12), 0, 0))
        name = Factory.Field(hint_text="Nombre del ensayo" if is_id else "Nombre del predio")
        code = Factory.Field(hint_text="Código (2 a 4 letras, va en el nombre de las fotos)")
        state = {"auto": True}

        def on_name(_w, text):
            if state["auto"]:
                code.text = suggest_code(text, a.workspaces.codes())

        def on_code(_w, text):
            up = text.upper()[:4]
            if up != text:
                code.text = up
            if code.focus:
                state["auto"] = False

        name.bind(text=on_name)
        code.bind(text=on_code)
        form.add_widget(name)
        form.add_widget(code)
        state["kind"] = "variedades" if is_id else "predio"
        if is_id:
            seg = MDBoxLayout(adaptive_height=True, spacing=dp(8))
            # Altos y en dos líneas: «Tratamientos × repeticiones» se leía cortado («…»).
            b_var = SegButton(text="Variedades", selected=True, height=dp(54), shorten=False,
                              font_size="14sp")
            b_trt = SegButton(text="Tratamientos\n× repeticiones", height=dp(54), shorten=False,
                              font_size="14sp", line_height=1.05)
            seg.add_widget(b_var)
            seg.add_widget(b_trt)
            trt = MDBoxLayout(adaptive_height=True, spacing=dp(8))
            n_t = Factory.Field(hint_text="N.º tratamientos", input_filter="int", text="4")
            n_r = Factory.Field(hint_text="N.º repeticiones", input_filter="int", text="4")
            trt.add_widget(n_t)
            trt.add_widget(n_r)
            # Alto fijo: el diálogo no cambia de tamaño al elegir el tipo (KivyMD no lo reajusta).
            info = MDLabel(font_style="Caption", size_hint_y=None, height=dp(48), valign="top",
                           theme_text_color="Custom", text_color=c(theme.MUTED))
            info.bind(width=lambda w, v: setattr(w, "text_size", (v, dp(48))))
            form.add_widget(MDLabel(text="Tipo de ensayo", font_style="Caption", adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(theme.MUTED)))
            form.add_widget(seg)
            form.add_widget(trt)
            form.add_widget(info)
            # Qué es cada tratamiento (T1 = Testigo…): opcional, también en Ajustes › Registros.
            from kivy.uix.scrollview import ScrollView
            meanings = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6))
            m_title = MDLabel(text="Qué es cada tratamiento (opcional)", font_style="Caption",
                              bold=True, adaptive_height=True, theme_text_color="Custom",
                              text_color=c(theme.LEAF_DARK))
            m_scroll = ScrollView(size_hint_y=None, height=0, do_scroll_x=False, bar_width=dp(3))
            m_scroll.add_widget(meanings)
            form.add_widget(m_title)
            form.add_widget(m_scroll)
            state["meanings"] = []

            def build_meanings(*_):
                show = state["kind"] == "tratamientos"
                try:
                    t = min(int(n_t.text or 0), 20) if show else 0
                except ValueError:
                    t = 0
                old = [f.text for f in state["meanings"]]
                fast_clear(meanings)
                state["meanings"] = []
                for i in range(1, t + 1):
                    f = Factory.Field(hint_text=f"T{i} = (ej.: {'Testigo' if i == 1 else 'producto, dosis…'})",
                                      text=old[i - 1] if i <= len(old) else "")
                    meanings.add_widget(f)
                    state["meanings"].append(f)
                m_title.opacity = 1 if t else 0
                m_title.height = m_title.texture_size[1] if t else 0
                Clock.schedule_once(lambda *_: setattr(
                    m_scroll, "height", min(dp(190), meanings.height) if t else 0), 0)

            def set_kind(kind):
                state["kind"] = kind
                b_var.selected, b_trt.selected = kind == "variedades", kind == "tratamientos"
                trt.disabled = kind != "tratamientos"
                trt.opacity = 1 if kind == "tratamientos" else .35
                update_info()
                build_meanings()

            def update_info(*_):
                if state["kind"] == "variedades":
                    info.text = ("Ensayo de variedades: cada variedad se registra por separado y los "
                                 "informes comparan variedades.")
                    return
                try:
                    t, r = int(n_t.text or 0), int(n_r.text or 0)
                except ValueError:
                    t = r = 0
                info.text = (f"Se crearán {t * r} parcelas: T1R1 … T{t}R{r}. Los informes promedian las "
                             "repeticiones y comparan los tratamientos (ANOVA)." if t and r else
                             "Indique cuántos tratamientos y repeticiones tiene el ensayo.")

            b_var.bind(on_release=lambda *_: set_kind("variedades"))
            b_trt.bind(on_release=lambda *_: set_kind("tratamientos"))
            n_t.bind(text=update_info)
            n_t.bind(text=build_meanings)
            n_r.bind(text=update_info)
            set_kind("variedades")

        def ok(_f):
            kind = state["kind"]
            size = None
            if kind == "tratamientos":
                try:
                    size = int(n_t.text or 0), int(n_r.text or 0)
                except ValueError:
                    size = (0, 0)
                from database import Database
                if not (1 <= size[0] <= Database.MAX_TREATMENTS and 1 <= size[1] <= Database.MAX_REPS):
                    a.toast(f"Tratamientos: 1 a {Database.MAX_TREATMENTS} · repeticiones: 1 a {Database.MAX_REPS}.")
                    return False
            try:
                ws = a.workspaces.create(self.profile, kind, name.text, code.text)
            except ValueError as exc:
                a.toast(str(exc))
                return False
            named = 0
            if size:
                db = a.open_db(ws)
                db.setup_trial(*size)
                for i, f in enumerate(state.get("meanings", [])[:size[0]], 1):
                    if f.text.strip():
                        db.update_treatment(i, f.text)
                        named += 1
            a.open_workspace(ws["id"], target="sectors" if ws["profile"] == "predio" else "home")
            if size:
                a.toast(f"«{ws['name']}» creado con {size[0] * size[1]} parcelas"
                        + ("" if named == size[0] else
                           ". Defina qué es cada tratamiento en Ajustes › Registros"))
            else:
                a.toast(f"«{ws['name']}» creado: agregue sus "
                        + ("variedades en Ajustes › Registros" if is_id
                           else "sectores con «+ Nuevo sector»"))

        form_dialog("Nuevo ensayo" if is_id else "Nuevo predio", form, ok, "CREAR")


class SettingsScreen(MDScreen):
    """Ajustes con dos pestañas: «General» y «Registros». Desde la pantalla de inicio se
    abre solo «General» (general_only), sin entrar a un ensayo o predio."""
    general_only = BooleanProperty(False)

    def on_general_only(self, _w, only):
        """Solo «General»: la fila de pestañas se SACA (oculta y desactivada seguía tomando
        los toques junto a la flecha de volver)."""
        row = self.ids.tabs
        if only and row.parent:
            self._tabs_box = row.parent
            row.parent.remove_widget(row)
        elif not only and not row.parent and getattr(self, "_tabs_box", None):
            self._tabs_box.add_widget(row, index=len(self._tabs_box.children) - 1)

    def on_pre_enter(self, *_):
        self.ids.var_seg.text = "Registros"
        self.show("general" if self.general_only else (self.ids.pages.current or "general"), defer=False)

    def on_enter(self, *_):
        # La lista de variedades se arma en un momento libre, no al tocar la pestaña.
        if not getattr(self.ids.varieties, "_rows", None):
            Clock.schedule_once(lambda *_: self.ids.varieties.refresh(), 0.4)

    def show(self, page: str, defer: bool = True):
        self.ids.pages.current = page   # el cambio de pestaña se ve al instante
        tab = self.ids.settings if page == "general" else self.ids.varieties
        if defer:
            Clock.schedule_once(lambda *_: tab.refresh(), 0)
        else:
            tab.refresh()


class VarietyRow(GlassButton):
    kicker = StringProperty()      # parcela «T1R1» (chica) cuando el tratamiento tiene nombre
    title = StringProperty()
    subtitle = StringProperty()
    photos = NumericProperty(0)
    photo_tag = StringProperty()
    code_tag = StringProperty()
    code_bg = ColorProperty(c(theme.BERRY_SOFT))
    code_fg = ColorProperty(c(theme.LEAF_DARK))
    done = BooleanProperty(False)
    variety_id = NumericProperty()
    thumb_src = StringProperty("")


def season_dialog(on_done=None):
    """Elegir temporada (abril-marzo): cambia la temporada de toda la app."""
    a = app()
    items = []
    for s in a.db.season_list():
        first, last = s["first"], s["last"]
        n = s["records"]
        sub = (f"{first.day} {ph.MESES[first.month - 1][:3]} {first.year} – "
               f"{last.day} {ph.MESES[last.month - 1][:3]} {last.year} · "
               + (f"{n} registro{'s' if n != 1 else ''}" if n else "sin registros")
               + (" · en curso" if s["current"] else ""))

        def choose(season=s["season"]):
            a.set_season(season)
            if on_done:
                on_done()
        accent = c(theme.LEAF) if s["season"] == a.season else None
        items.append((s["title"], sub, choose, accent))
    pick_dialog("Temporada", items)


class SamplingTab(MDBoxLayout):
    def pick_season(self):
        season_dialog(self.refresh)

    def refresh(self):
        a = app()
        week = a.week
        self.ids.season_chip.text = ph.season_title(a.season)
        start = _dt.date.fromisoformat(week["start_date"])
        end = start + _dt.timedelta(days=6)
        self.ids.week_kicker.text = ph.week_title(week).upper()
        self.ids.week_title.text = week["label"]
        self.ids.week_range.text = (f"{start.day} {ph.MESES[start.month - 1][:3]} – "
                                    f"{end.day} {ph.MESES[end.month - 1][:3]} {end.year}")
        rows = a.db.week_overview(week["id"])
        box = self.ids.rows
        # Las filas se reutilizan: crear/destruir widgets KivyMD es lo más costoso.
        cache = getattr(self, "_rows", {})
        if not rows:
            fast_clear(box)
            self._rows = {}
            is_predio = (getattr(a, "workspace", None) or {}).get("profile") == "predio"
            box.add_widget(MDLabel(
                text=("Aún no hay sectores en este predio. Agréguelos en Ajustes › Registros "
                      "(variedad, sector y equipo de riego)." if is_predio else
                      "Aún no hay variedades en este ensayo. Agréguelas en Ajustes › Registros."),
                font_style="Body2", adaptive_height=True, halign="center",
                theme_text_color="Custom", text_color=c(theme.MUTED)))
        elif list(cache) != [r["variety"]["id"] for r in rows]:
            fast_clear(box)
            cache = {}
            for r in rows:
                row = VarietyRow(variety_id=r["variety"]["id"])
                row.bind(on_release=lambda w: a.open_observation(w.variety_id, a.week["id"]))
                cache[r["variety"]["id"]] = row
                box.add_widget(row)
            self._rows = cache
        complete = 0
        names = a.db.bbch_names()
        trt_names = a.db.treatment_names() if a.db.is_trial else {}
        for r in rows:
            obs, photos, v = r["observation"], r["photos"], r["variety"]
            code = obs["bbch_code"] if obs else None
            n = len(photos)
            complete += code is not None and n >= 1   # basta una foto (canopia o detalle)
            bg, fg = bbch_tag_colors(code)
            row = cache[v["id"]]
            row.title, row.kicker = a.db.parcel_labels(v, trt_names)
            if ph.is_unit(v):   # predio: la variedad (y su año) grande; equipo y sector, chico
                row.title, row.kicker = ph.unit_main(v), ph.unit_place(v)
            row.subtitle = (obs["bbch_label"] or ph.bbch_label(code, names)) if code is not None \
                else ("Foto sin estado asignado" if n else "Pendiente de registro")
            row.photos, row.photo_tag = n, ("SIN FOTOS" if not n else f"{n} FOTO" + ("S" if n > 1 else ""))
            row.code_tag = f"BBCH {ph.code_str(code)}" if code is not None else "BBCH —"
            row.code_bg, row.code_fg, row.done = bg, fg, code is not None
            thumb = photos.get("detail") or photos.get("canopy")
            src = thumb["path"] if thumb else ""
            if src != row.thumb_src or not row.ids.thumb_box.children:
                row.thumb_src = src
                fast_clear(row.ids.thumb_box)
                row.ids.thumb_box.add_widget(thumb_widget(src or None, icon="sprout-outline"))
        total = max(1, len(rows))
        self.ids.progress.value = complete / total
        self.ids.progress_text.text = f"{complete}/{len(rows)} completas"
        # Semana no muestreada: casilla marcada, aviso y lista atenuada.
        skipped = bool(week.get("skipped"))
        self._loading_skip = True
        self.ids.skip_box.active = skipped
        self._loading_skip = False
        if skipped:
            self.ids.week_kicker.text += " · NO MUESTREADA"
            self.ids.progress_text.text = "omitida"
        box.opacity = .45 if skipped else 1
        # Semana recién completada (pasó de incompleta a completa mientras se registraba):
        # serpentinas y «SEMANA x · COMPLETADA». Abrir una semana ya completa no lo repite.
        done = bool(rows) and complete == len(rows) and not skipped
        state = self.__dict__.setdefault("_week_done", {})
        key = (getattr(a.db, "code", ""), week["id"])
        if done and state.get(key) is False:
            from ui import celebrate
            Clock.schedule_once(lambda *_: celebrate.week_completed(
                str(ph.iso_week(_dt.date.fromisoformat(week["start_date"]))[0])), .25)
        state[key] = done
        n_meas = sum(1 for m in a.db.list_measures(week["id"]) if m["n"])
        self.ids.measures_btn.text = ("Mediciones de la semana" if not n_meas
                                      else f"Mediciones de la semana · {n_meas} con datos")

    def set_skipped(self, active: bool):
        """Marca/desmarca la semana como «no muestreada»: se excluye de los informes de
        período, por variedad y matriz (los datos, si los hubiera, no se borran)."""
        if getattr(self, "_loading_skip", False):
            return
        a = app()
        if bool(a.week.get("skipped")) == bool(active):
            return
        a.db.set_week_skipped(a.week["id"], active)
        a.week = a.db.get_week(a.week["id"])
        a.toast(f"{ph.week_title(a.week)} marcada como no muestreada: no aparecerá en los informes"
                if active else f"{ph.week_title(a.week)} vuelve a incluirse en los informes")
        self.refresh()

    def open_measures(self):
        open_measures_menu()

    def shift_week(self, delta: int):
        """Semana anterior / siguiente sin tope (2020-2050): al cruzar el 1 de abril pasa
        sola a la temporada que corresponde."""
        a = app()
        start = _dt.date.fromisoformat(a.week["start_date"]) + _dt.timedelta(days=7 * delta)
        if start + _dt.timedelta(days=6) < ph.FIRST_BROWSE or start > ph.LAST_BROWSE:
            a.toast("Las semanas van de 2020 a 2050.")
            return
        a.week = a.db.week_for_date(start)
        a.season = a.week["season"]
        self.refresh()

    def pick_week_date(self):
        """Tocar «Semana del …»: calendario; cualquier día lleva a la semana que lo contiene
        (el título muestra su primer día)."""
        a = app()
        from android_bridge import pick_date
        start = _dt.date.fromisoformat(a.week["start_date"])

        def go(day):
            if day < ph.FIRST_BROWSE or day > ph.LAST_BROWSE:
                a.toast("Las semanas van de 2020 a 2050.")
                return
            a.week = a.db.week_for_date(day)
            a.season = a.week["season"]
            self.refresh()
        pick_date(start, go, "Ir a la semana de…")

    def go_current(self):
        a = app()
        a.week = a.db.current_week()
        a.season = a.week["season"]
        self.refresh()


# ===========================================================================
# Variedades
# ===========================================================================
class VarietyCatalogRow(GlassButton):
    title = StringProperty()
    code = StringProperty()
    summary = StringProperty()
    variety_id = NumericProperty()
    tab = ObjectProperty()


def pick_number(title: str, values, current, callback):
    """Diálogo centrado para elegir un número opcional («Sin definir» = None)."""
    items = [("Sin definir", "No se incluye en el nombre de las fotos", lambda: callback(None))]
    items += [(f"{title} {n}", "Seleccionado" if n == current else "", lambda n=n: callback(n))
              for n in values]
    pick_dialog(title, items)


def map_dialog(start: tuple, zoom: int, on_pick):
    """Mapa a pantalla completa con pin central. on_pick(lat, lon)."""
    from kivy.uix.floatlayout import FloatLayout
    from kivy.uix.modalview import ModalView
    from kivymd.uix.button import MDIconButton
    import geo
    from ui.mapview import MapPicker

    a = app()
    view = ModalView(size_hint=(1, 1), auto_dismiss=True, background_color=(0, 0, 0, .6))
    root = MDBoxLayout(orientation="vertical", md_bg_color=DIALOG_BG)
    head = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(dp(16), dp(12)),
                       spacing=dp(2))
    head.add_widget(MDLabel(text="Marque la ubicación de la muestra", font_style="H6", bold=True,
                            adaptive_height=True))
    coords = MDLabel(text="", font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                     text_color=c(theme.MUTED))
    head.add_widget(coords)
    root.add_widget(head)

    area = FloatLayout()
    mp = MapPicker(start[0], start[1], zoom, workers=a.workers, size_hint=(1, 1),
                   pos_hint={"x": 0, "y": 0})
    area.add_widget(mp)
    pin = MDIcon(icon="map-marker", theme_text_color="Custom", text_color=c(theme.BERRY),
                 halign="center", valign="bottom", size_hint=(None, None), size=(dp(52), dp(52)),
                 pos_hint={"center_x": .5, "y": .5})   # la punta del pin marca el centro
    area.add_widget(pin)
    Clock.schedule_once(lambda *_: setattr(pin, "font_size", dp(52)), 0)  # tras el estilo de KivyMD
    zoom_box = MDBoxLayout(orientation="vertical", size_hint=(None, None), size=(dp(52), dp(168)),
                           pos_hint={"right": .98, "top": .98}, spacing=dp(4))
    for icon, step in (("plus", 1), ("minus", -1)):
        zoom_box.add_widget(MDIconButton(icon=icon, md_bg_color=(1, 1, 1, .92),
                                         on_release=lambda *_, s=step: mp.zoom_by(s)))
    # Satélite ↔ calles (la atribución la dibuja el mapa).
    layer_btn = MDIconButton(icon="map-outline" if mp.layer == "sat" else "satellite-variant",
                             md_bg_color=(1, 1, 1, .92))
    layer_btn.bind(on_release=lambda b: setattr(
        b, "icon", "map-outline" if mp.toggle_layer() == "sat" else "satellite-variant"))
    zoom_box.add_widget(layer_btn)
    area.add_widget(zoom_box)
    root.add_widget(area)

    def update(*_):
        lat, lon = mp.center_latlon
        coords.text = f"{geo.fmt(lat, lon)} · arrastre el mapa y deje el pin sobre la planta"
    mp.bind(cx=update, cy=update, zoom=update)
    update()

    state = {"req": None}

    def here(*_):
        def progress(lat, lon, acc):
            mp.center_on(lat, lon, max(int(mp.zoom), 17))
            coords.text = f"{geo.fmt(lat, lon)} · GPS ±{acc:.0f} m (afinando…)"

        def done(lat, lon, acc):
            state["req"] = None
            mp.center_on(lat, lon, max(int(mp.zoom), 18))
            a.toast(f"Centrado en su ubicación (±{acc:.0f} m)")

        def fail(msg):
            state["req"] = None
            a.toast(msg)

        def granted(ok):
            if not ok:
                a.toast("Sin permiso de ubicación")
                return

            def go(*_):
                state["req"] = geo.LocationRequest(done, fail, progress)
                state["req"].start()
            Clock.schedule_once(go, 0)
        geo.request_location_permission(granted)

    def stop_gps(*_):
        if state["req"] is not None:
            state["req"].cancel()
    view.bind(on_dismiss=stop_gps)
    from android_bridge import allow_rotation
    allow_rotation(True)                         # el mapa se puede ver horizontal
    view.bind(on_dismiss=lambda *_: allow_rotation(False))

    def use(*_):
        lat, lon = mp.center_latlon
        view.dismiss()
        on_pick(lat, lon)
        a.toast("Ubicación marcada en el mapa")

    bar = MDBoxLayout(adaptive_height=True, padding=(dp(12), dp(10)), spacing=dp(8))
    bar.add_widget(MDRectangleFlatButton(text="Cancelar", on_release=lambda *_: view.dismiss()))
    bar.add_widget(MDRectangleFlatButton(text="Mi ubicación", on_release=here))
    bar.add_widget(MDRaisedButton(text="Usar este punto", md_bg_color=c(theme.BERRY), on_release=use))
    root.add_widget(bar)
    view.add_widget(root)
    view.open()
    return view


class SectorIrrigationMixin:
    """Botones «Sector (1-10)» y «Equipo de riego (1-4)» de la identificación."""
    sector = NumericProperty(0)
    irrigation = NumericProperty(0)

    def _sync_location_buttons(self):
        self.ids.sector_btn.text = f"Sector: {self.sector or '—'}"
        self.ids.irrigation_btn.text = f"Riego: {'ER' + str(self.irrigation) if self.irrigation else '—'}"
        if hasattr(self, "update_photo_hint"):
            self.update_photo_hint()

    def pick_sector(self):
        def done(n):
            self.sector = n or 0
            self._sync_location_buttons()
        pick_number("Sector", ph.SECTORS, self.sector, done)

    def pick_irrigation(self):
        def done(n):
            self.irrigation = n or 0
            self._sync_location_buttons()
        pick_number("Equipo de riego", ph.IRRIGATION_UNITS, self.irrigation, done)


class VarietyForm(SectorIrrigationMixin, MDBoxLayout):
    pass

    def pick_catalog(self):
        def chosen(name, code):
            import catalog
            a = app()
            self.ids.name.text = name
            # Siempre con código: el del catálogo o, si falta, uno conocido o derivado.
            self.ids.code.text = code or catalog.code_for(a.workspaces.shared, name, a.db,
                                                          current_profile())
        pick_catalog(chosen)


class VarietiesTab(MDScreen):
    def refresh(self):
        a = app()
        season = a.season
        trial = a.db.is_trial
        self.ids.season_caption.text = (f"{ph.season_title(season)} · toque una "
                                        f"{'parcela' if trial else 'sector' if a.db.is_predio else 'variedad'} "
                                        f"para editar sus parámetros biométricos")
        self._trial_card(trial)
        box = self.ids.rows
        varieties = a.db.list_varieties()
        cache = getattr(self, "_rows", {})
        if list(cache) != [v["id"] for v in varieties]:  # filas reutilizables
            fast_clear(box)
            cache = {}
            for v in varieties:
                row = VarietyCatalogRow(variety_id=v["id"], tab=self)
                row.bind(on_release=lambda w: self.open_variety(w.variety_id))
                cache[v["id"]] = row
                box.add_widget(row)
            self._rows = cache
        trts = {t["num"]: t for t in a.db.list_treatments()} if trial else {}
        for v in varieties:
            m = a.db.get_metrics(v["id"], season)
            parts = []
            if not ph.is_unit(v):       # predio: equipo y sector ya van al comienzo
                if v["sector"]:
                    parts.append(f"Sector {v['sector']}")
                if v["irrigation"]:
                    parts.append(f"Riego ER{v['irrigation']}")
            if m["historical_yield"] is not None:
                parts.append(f"hist. {m['historical_yield']:g} {m['historical_yield_unit']}")
            if m["projected_yield"] is not None:
                parts.append(f"proy. {m['projected_yield']:g} {m['projected_yield_unit']}")
            if m["basal_canes"] is not None:
                parts.append(f"{m['basal_canes']:g} cañas {m['basal_canes_unit']}")
            if ph.is_unit(v):          # predio: la variedad va en el título
                parts.insert(0, ph.unit_place(v))
            elif v.get("cultivar"):
                parts.insert(0, v["cultivar"])
            if v.get("treatment"):
                t = trts.get(v["treatment"])
                parts.insert(0, f"{t['label'] if t else 'T' + str(v['treatment'])} · Repetición {v['rep']}")
            n_custom = len(a.db.list_custom_fields(v["id"], season))
            if n_custom:
                parts.append(f"{n_custom} campo(s) extra")
            row = cache[v["id"]]
            row.title, row.code = ph.unit_main(v), v["code"] or ""
            row.summary = " · ".join(parts) or "Sin parámetros cargados"

    def open_variety(self, variety_id: int):
        app().open_variety(variety_id)

    # ------------------------------------------- tratamientos × repeticiones
    def _catalog_card(self, box):
        import catalog
        from kivy.factory import Factory
        a = app()
        profile = current_profile()
        names = [e["name"] for e in catalog.entries(a.workspaces.shared, profile)]
        card = Factory.PaperCard()
        card.add_widget(Factory.SectionLabel(
            text=f"CATÁLOGO DE VARIEDADES · {'PREDIO' if profile == 'predio' else 'I+D'}"))
        card.add_widget(Factory.Muted(
            text=(f"{len(names)} variedades: " + ", ".join(names[:8]) + ("…" if len(names) > 8 else ""))
            if names else "Vacío: agregue las variedades que usa para elegirlas de una lista al crear "
                          "registros, sectores o tratamientos."))
        b = Factory.GhostButton(icon="format-list-bulleted", text="Ver y agregar variedades")
        b.bind(on_release=lambda *_: manage_catalog(on_change=self.refresh))
        card.add_widget(b)
        box.add_widget(card)
        box.add_widget(Widget(size_hint_y=None, height=dp(8)))

    def _trial_card(self, trial: bool):
        from kivy.factory import Factory
        box = self.ids.trial_box
        box.clear_widgets()
        self._catalog_card(box)
        if not trial:
            return
        db = app().db
        nt, nr = db.trial_size()
        card = Factory.PaperCard()
        card.add_widget(Factory.SectionLabel(text="TRATAMIENTOS × REPETICIONES"))
        card.add_widget(Factory.Body(text=f"{nt} tratamientos × {nr} repeticiones = {nt * nr} parcelas"
                                     if nt else "Aún sin definir"))
        b1 = Factory.GhostButton(icon="grid", text="Cambiar número")
        b1.bind(on_release=lambda *_: self.trial_size_dialog())
        card.add_widget(b1)
        tv = db.trial_cultivar
        b3 = Factory.GhostButton(icon="sprout-outline",
                                 text=f"Variedad del ensayo: {tv}" if tv else "Variedad del ensayo: (ninguna)")
        b3.bind(on_release=lambda *_: pick_catalog(self._set_trial_variety, "id",
                                                   allow_none="— Sin variedad para todo el ensayo"))
        card.add_widget(b3)
        box.add_widget(card)
        box.add_widget(Widget(size_hint_y=None, height=dp(8)))
        # Qué significa cada tratamiento: se ve en la ficha de muestreo y en los informes.
        card = Factory.PaperCard()
        card.add_widget(Factory.SectionLabel(text="SIGNIFICADO DE LOS TRATAMIENTOS"))
        card.add_widget(Factory.Muted(
            text="Qué es cada T (ej.: T1 = Testigo, T2 = N 120 kg/ha). Se muestra en las tarjetas "
                 "del muestreo y en los informes; T1R1, T1R2… quedan en letra chica."))
        for t in db.list_treatments():
            b = Factory.GhostButton(icon="tag-text-outline" if t["name"] else "tag-plus-outline",
                                    text=f"T{t['num']}: {t['name']}" if t["name"]
                                    else f"T{t['num']}: (sin definir · tocar)")
            b.bind(on_release=lambda *_, t=t: self.edit_treatment(t))
            card.add_widget(b)
        box.add_widget(card)
        box.add_widget(Widget(size_hint_y=None, height=dp(8)))

    def _set_trial_variety(self, name, _code):
        app().db.set_setting("trial_cultivar", name)
        app().toast(f"Variedad del ensayo: {name}" if name else "Ensayo sin variedad común")
        self.refresh()

    def trial_size_dialog(self):
        from kivy.factory import Factory
        a = app()
        nt, nr = a.db.trial_size()
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                           padding=(0, dp(12), 0, 0))
        row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
        f_t = Factory.Field(hint_text="N.º tratamientos", input_filter="int", text=str(nt or 4))
        f_r = Factory.Field(hint_text="N.º repeticiones", input_filter="int", text=str(nr or 4))
        row.add_widget(f_t)
        row.add_widget(f_r)
        form.add_widget(row)
        form.add_widget(MDLabel(
            text="Si reduce el número, las parcelas que sobran se archivan con sus registros "
                 "(no se borra nada); si lo vuelve a aumentar, reaparecen.",
            font_style="Caption", adaptive_height=True, theme_text_color="Custom", text_color=c(theme.MUTED)))

        def ok(_f):
            try:
                res = a.db.setup_trial(int(f_t.text or 0), int(f_r.text or 0))
            except ValueError as exc:
                a.toast(str(exc))
                return False
            msg = [f"{k} {v}" for k, v in (("nuevas", res["added"]), ("restauradas", res["restored"]),
                                           ("archivadas", res["archived"])) if v]
            a.toast("Parcelas: " + (", ".join(msg) if msg else "sin cambios"))
            self.refresh()
            a.refresh_home()

        form_dialog("Tratamientos × repeticiones", form, ok)

    def edit_treatment(self, t: dict):
        """Significado de un tratamiento (nombre corto, descripción y variedad)."""
        from kivy.factory import Factory
        a = app()
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                           padding=(0, dp(12), 0, 0))
        f_n = Factory.Field(hint_text=f"Qué es T{t['num']} (ej.: Testigo)", text=t["name"] or "")
        f_d = Factory.Field(hint_text="Descripción (dosis, producto, momento…)",
                            text=t["description"] or "", multiline=True)
        form.add_widget(f_n)
        form.add_widget(f_d)
        chosen = {"v": (t.get("cultivar") or "").strip()}
        default = a.db.trial_cultivar
        vb = Factory.GhostButton(icon="sprout-outline")

        def label():
            vb.text = (f"Variedad: {chosen['v']}" if chosen["v"] else
                       f"Variedad: la del ensayo ({default})" if default else "Variedad: (ninguna)")

        def pick(name, _code):
            chosen["v"] = name
            label()

        vb.bind(on_release=lambda *_: pick_catalog(pick, "id", allow_none="— La del ensayo / ninguna"))
        label()
        form.add_widget(vb)

        def ok(_f):
            a.db.update_treatment(t["num"], f_n.text, f_d.text, chosen["v"])
            self.refresh()
            a.refresh_home()

        form_dialog(f"Tratamiento T{t['num']}", form, ok)

    def add_dialog(self):
        if app().db.is_trial:
            self.trial_size_dialog()
            return
        if app().db.is_predio:
            unit_dialog(on_saved=self.refresh)
            return
        def ok(form):
            try:
                app().db.add_variety(form.ids.name.text, code=form.ids.code.text.strip(),
                                     sector=form.sector or None, irrigation=form.irrigation or None)
            except ValueError as exc:
                form.ids.name.error = True
                form.ids.name.helper_text = str(exc)
                form.ids.name.helper_text_mode = "on_error"
                return False
            remember_variety(form.ids.name.text, form.ids.code.text.strip())
            app().toast("Variedad agregada")
            self.refresh()
        form_dialog("Nueva variedad", VarietyForm(), ok, "AGREGAR")

    def delete_dialog(self, variety_id: int):
        a = app()
        v = a.db.get_variety(variety_id)

        def archive():
            a.db.delete_variety(variety_id)
            a.toast(f"«{v['name']}» archivada (historial conservado)")
            self.refresh()
            a.refresh_home()

        def purge():
            a.db.delete_variety(variety_id, purge=True)
            a.toast(f"«{v['name']}» eliminada")
            self.refresh()
            a.refresh_home()

        confirm(f"Quitar «{v['name']}»",
                "Archivar la oculta del muestreo pero conserva fotos y registros (recomendado). "
                "Eliminar borra definitivamente todos sus registros.",
                [("Archivar", archive), ("Eliminar", purge)])


class CustomFieldRow(MDBoxLayout):
    key = StringProperty()
    value = StringProperty()
    field_id = NumericProperty()
    field = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


class CustomFieldForm(MDBoxLayout):
    pass


class AttachmentRow(MDBoxLayout):
    caption = StringProperty()
    date = StringProperty()
    item = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


class CaptionForm(MDBoxLayout):
    pass


class StageSparkline(Widget):
    """Curva del estado BBCH semana a semana (puntos con el color de su estadio)."""
    points = ListProperty([])    # [(etiqueta, código)]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(points=self._redraw, pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        from kivy.core.text import Label as CoreLabel
        from kivy.graphics import Color, Ellipse, Line, Rectangle
        self.canvas.clear()
        pts = [(lab, code) for lab, code in self.points if code is not None]
        if not pts:
            return
        vals = [ph.bbch_value(cd) for _l, cd in pts]
        lo, hi = min(vals), max(vals)
        span = max(hi - lo, 4)
        pad_x, pad_top, pad_bot = dp(14), dp(16), dp(18)
        n = len(pts)
        step = (self.width - 2 * pad_x) / max(1, n - 1)

        def xy(i, v):
            x = self.x + pad_x + (i * step if n > 1 else (self.width - 2 * pad_x) / 2)
            y = self.y + pad_bot + (v - lo) / span * (self.height - pad_top - pad_bot)
            return x, y

        with self.canvas:
            Color(*c(theme.LEAF, .25))
            Line(points=[self.x + pad_x, self.y + pad_bot, self.right - pad_x, self.y + pad_bot], width=1)
            Color(*c(theme.BERRY, .8))
            if n > 1:
                Line(points=[k for i, v in enumerate(vals) for k in xy(i, v)], width=dp(1.4))
            for i, ((lab, code), v) in enumerate(zip(pts, vals)):
                x, y = xy(i, v)
                bg, fg = theme.stage_colors(code)
                Color(*fg)
                Ellipse(pos=(x - dp(5), y - dp(5)), size=(dp(10), dp(10)))
                Color(*bg)
                Ellipse(pos=(x - dp(3), y - dp(3)), size=(dp(6), dp(6)))
                if n <= 10 or i % 2 == 0 or i == n - 1:
                    t = CoreLabel(text=lab, font_size=dp(9), bold=True)
                    t.refresh()
                    Color(*c(theme.MUTED))
                    Rectangle(texture=t.texture, size=t.texture.size,
                              pos=(x - t.texture.size[0] / 2, self.y + dp(2)))
                    t = CoreLabel(text=ph.code_str(code), font_size=dp(9), bold=True)
                    t.refresh()
                    Color(*c(theme.LEAF_DARK))
                    Rectangle(texture=t.texture, size=t.texture.size,
                              pos=(x - t.texture.size[0] / 2, y + dp(6)))


class TimelineScreen(MDScreen):
    """Línea de tiempo de una variedad (o sector): cada semana con su estado y TODAS sus
    fotos, en orden. Se abre al tocar una variedad en la vista previa."""
    variety_id = NumericProperty(0)

    def load(self, variety_id: int, week_id: int | None = None):
        a = app()
        self.variety_id = variety_id
        v = a.db.get_variety(variety_id)
        self.ids.bar.title = ph.unit_main(v)
        rows = a.db.variety_timeline(variety_id, a.season)
        codes = [r["bbch_code"] for r in rows if r["bbch_code"] is not None]
        n_photos = 0
        box = self.ids.entries
        fast_clear(box)
        film = self.ids.film
        fast_clear(film)
        self._entries, self._frames = {}, {}
        target = None
        for i, r in enumerate(rows):
            photos = a.db.list_photos(r["id"])
            n_photos += len(photos)
            entry = self._entry(r, photos, first=i == 0, last=i == len(rows) - 1)
            box.add_widget(entry)
            self._entries[r["week_id"]] = entry
            film.add_widget(self._frame(r, photos))
            if week_id is not None and r["week_id"] == week_id:
                target = entry
        self.ids.film_box.height = dp(118) if rows else 0
        self.ids.film_box.opacity = 1 if rows else 0
        if not rows:
            box.add_widget(MDLabel(text="Aún no hay registros de esta variedad en la temporada.",
                                   font_style="Caption", adaptive_height=True, halign="center",
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
        sub = [v.get("cultivar") or "", ph.season_title(a.season)]
        self.ids.sub.text = " · ".join(x for x in sub if x)
        first, last = (codes[0], codes[-1]) if codes else (None, None)
        self.ids.stats.text = (f"{len(rows)} semana(s) · {n_photos} foto(s)"
                               + (f" · BBCH {ph.code_str(first)} a {ph.code_str(last)}" if codes else ""))
        self.ids.spark.points = [(ph.week_short(r), r["bbch_code"]) for r in rows]
        self.ids.spark.opacity = 1 if codes else 0
        self.ids.spark.height = dp(110) if codes else 0
        sv = self.ids.scroll
        sv.scroll_y = 1
        if target is not None:   # abre en la semana tocada
            Clock.schedule_once(lambda *_: self.jump(week_id, animate=False), .15)

    def open_report(self):
        """Informe completo de la variedad (ficha de la temporada), en vista previa."""
        a = app()
        r = a.configured_reports()
        btn = self.ids.report_btn
        btn.disabled, btn.text = True, "Preparando informe…"
        vid = self.variety_id

        def done(res, error):
            btn.disabled, btn.text = False, "Ver informe completo de la variedad"
            if error:
                a.toast(f"No se pudo preparar el informe: {error}")
            else:
                a.media.preview(res.path, res.title)

        def work():
            try:
                res = r.variety(vid, a.season, "preview")
                Clock.schedule_once(lambda *_: done(res, None))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: done(None, error))

        a.workers.submit(work)

    # ---- tira de miniaturas (una por semana)
    def _frame(self, r, photos):
        """Miniatura de la semana (foto de detalle o general) con solo «S38» debajo."""
        main = (next((p for p in photos if p["kind"] == "detail" and p["is_primary"]), None)
                or next((p for p in photos if p["is_primary"]), None) or (photos[0] if photos else None))
        frame = FilmFrame(label=ph.week_short(r), week_id=r["week_id"])
        frame.ids.pic.add_widget(thumb_widget(main["path"] if main else None, 240, icon="camera-off-outline"))
        bg, _fg = theme.stage_colors(r["bbch_code"])
        frame.dot = bg if r["bbch_code"] is not None else c("#FFFFFF", .6)
        frame.bind(on_release=lambda w: self.jump(w.week_id))
        self._frames[r["week_id"]] = frame
        return frame

    def jump(self, week_id, animate=True):
        """Baja (o sube) hasta esa semana en el detalle y la destaca en la tira."""
        entry = getattr(self, "_entries", {}).get(week_id)
        if entry is None:
            return
        for wid, f in self._frames.items():
            f.selected = wid == week_id
        sv = self.ids.scroll
        content = sv.children[0]
        span = content.height - sv.height
        if span > 0:   # la semana arriba de la pantalla (no apenas asomada abajo)
            top = content.to_widget(*entry.to_window(entry.x, entry.top))[1]
            y = max(0.0, min(1.0, (top + dp(8) - sv.height) / span))
            from kivy.animation import Animation
            Animation.cancel_all(sv, "scroll_y")
            if animate:
                Animation(scroll_y=y, d=.35, t="out_cubic").start(sv)
            else:
                sv.scroll_y = y
        frame = self._frames.get(week_id)
        if frame is not None:
            self.ids.film_scroll.scroll_to(frame, padding=dp(40), animate=animate)
        from kivy.animation import Animation
        card = entry.children[0]
        Animation.cancel_all(card, "opacity")
        (Animation(opacity=.55, d=.12) + Animation(opacity=1, d=.35)).start(card)

    def _entry(self, r, photos, first=False, last=False):
        from kivy.uix.scrollview import ScrollView
        code = r["bbch_code"]
        bg, fg = theme.stage_colors(code)
        row = BoxLayout(size_hint_y=None, spacing=dp(8))
        rail = Widget(size_hint_x=None, width=dp(26))

        def draw_rail(w, *_):
            from kivy.graphics import Color, Ellipse, Rectangle
            w.canvas.clear()
            with w.canvas:
                Color(*c(theme.LEAF, .35))
                top = w.top - (dp(22) if first else 0)
                bot = w.y if not last else w.top - dp(22)
                Rectangle(pos=(w.center_x - dp(1.2), bot), size=(dp(2.4), max(0, top - bot)))
                Color(*fg)
                Ellipse(pos=(w.center_x - dp(9), w.top - dp(31)), size=(dp(18), dp(18)))
                Color(*bg)
                Ellipse(pos=(w.center_x - dp(5.5), w.top - dp(27.5)), size=(dp(11), dp(11)))

        # Se dibuja en el cuadro siguiente: durante el armado de la lista el alto y la
        # posición cambian por partes y un dibujo inmediato quedaba con valores viejos.
        redraw = Clock.create_trigger(lambda dt: draw_rail(rail))
        rail.bind(pos=redraw, size=redraw)
        row.add_widget(rail)
        from kivy.factory import Factory
        card = Factory.PaperCard()
        card.padding = (dp(12), dp(10))
        card.spacing = dp(6)
        d = _dt.date.fromisoformat(r["start_date"])
        head = MDBoxLayout(adaptive_height=True, spacing=dp(8))
        head.add_widget(MDLabel(text=f"{ph.week_short(r)} · {d.day} {ph.MESES[d.month - 1][:3]} {d.year}",
                                font_style="Subtitle2", bold=True, adaptive_height=True,
                                theme_text_color="Custom", text_color=c(theme.INK)))
        tag = Tag(text=f"BBCH {ph.code_str(code)}" if code is not None else "Sin estado",
                  bg=bg, fg=fg, pos_hint={"center_y": .5})
        head.add_widget(tag)
        card.add_widget(head)
        if code is not None:
            card.add_widget(MDLabel(text=r["bbch_label"] or ph.bbch_label(code), font_style="Caption",
                                    adaptive_height=True, theme_text_color="Custom",
                                    text_color=c(theme.MUTED)))
        if photos:
            strip = BoxLayout(size_hint_x=None, spacing=dp(6))
            strip.bind(minimum_width=strip.setter("width"))
            for p in photos:
                holder = ButtonBox(size_hint=(None, None), size=(dp(104), dp(104)))
                holder.add_widget(thumb_widget(p["path"], 320))
                holder.bind(on_release=lambda *_, path=p["path"]: app().media.open(path, "image/jpeg"))
                strip.add_widget(holder)
            sv = ScrollView(size_hint_y=None, height=dp(106), do_scroll_y=False, bar_width=dp(3))
            sv.add_widget(strip)
            card.add_widget(sv)
        else:
            card.add_widget(MDLabel(text="Sin fotos esta semana", font_style="Caption", adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(theme.BERRY)))
        if (r["notes"] or "").strip():
            card.add_widget(MDLabel(text=r["notes"].strip(), font_style="Body2", adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(theme.INK)))
        edit = MDFlatButton(text="ABRIR REGISTRO", theme_text_color="Custom", text_color=c(theme.LEAF_DARK),
                            pos_hint={"right": 1})
        edit.bind(on_release=lambda *_: app().open_observation(self.variety_id, r["week_id"]))
        card.add_widget(edit)
        row.add_widget(card)
        card.bind(height=lambda w, h: setattr(row, "height", h + dp(12)))
        return row


class FilmFrame(ButtonBehavior, BoxLayout):
    """Cuadro de la tira de la línea de tiempo: miniatura + semana."""
    label = StringProperty()
    week_id = NumericProperty(0)
    selected = BooleanProperty(False)
    dot = ColorProperty(c("#FFFFFF"))


class ButtonBox(ButtonBehavior, BoxLayout):
    """Contenedor tocable (miniaturas de la línea de tiempo)."""


class VarietyScreen(SectorIrrigationMixin, MDScreen):
    variety_id = NumericProperty(0)
    METRICS = ("historical_yield", "projected_yield", "basal_canes", "laterals")
    UNITS = ("historical_yield_unit", "projected_yield_unit", "basal_canes_unit", "laterals_unit")

    def load(self, variety_id: int):
        a = app()
        self.variety_id = variety_id
        v = a.db.get_variety(variety_id)
        self.ids.bar.title = ph.unit_main(v)
        self.predio = a.db.is_predio
        # Predio: se edita la variedad; el nombre («Equipo de riego n, sector m») sale solo.
        self.ids.name.hint_text = "Variedad" if self.predio else "Nombre de la variedad"
        self.ids.name.text = (v.get("cultivar") or "") if self.predio else v["name"]
        self.ids.code.text = v["code"] or ""
        self.ids.notes.text = v["notes"] or ""
        self.sector, self.irrigation = v["sector"] or 0, v["irrigation"] or 0
        self._sync_location_buttons()
        year = getattr(self, "_year", None)
        if self.predio and year is None:
            self._year = year_field(self.ids.code)
        elif not self.predio and year is not None:
            year.parent.remove_widget(year)
            self._year = None
        if self.predio:
            self._year.text = str(v.get("plant_year") or "")
        self.ids.metrics_title.text = f"PARÁMETROS BIOMÉTRICOS · {ph.season_title(a.season).upper()}"
        m = a.db.get_metrics(variety_id, a.season)
        for k in self.METRICS:
            self.ids[k].text = "" if m[k] is None else f"{m[k]:g}"
        for k in self.UNITS:
            if m.get(k):
                self.ids[k].text = m[k]
        self.ids.historical_note.text = m.get("historical_note") or ""
        self.load_custom()

    def update_photo_hint(self):
        if "photo_hint" not in self.ids:
            return
        v = {"name": self.ids.name.text, "code": self.ids.code.text,
             "sector": self.sector, "irrigation": self.irrigation}
        if getattr(self, "predio", False):
            v["cultivar"] = self.ids.name.text
        a = app()
        g = ph.photo_basename(v, a.week["start_date"], "canopy", trial=a.db.code)
        d = ph.photo_basename(v, a.week["start_date"], "detail", trial=a.db.code)
        self.ids.photo_hint.text = f"Nombre de las fotos: {g}.jpg (general) · {d}.jpg (detalle)"

    def load_custom(self):
        a = app()
        box = self.ids.custom
        fast_clear(box)
        fields = a.db.list_custom_fields(self.variety_id, a.season)
        for f in fields:
            box.add_widget(CustomFieldRow(key=f["key"], value=f"{f['value']} {f['unit']}".strip(),
                                          field_id=f["id"], field=f, screen=self))
        if not fields:
            box.add_widget(MDLabel(text="Sin campos adicionales.", font_style="Caption",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))

    @staticmethod
    def _float(text: str):
        text = (text or "").strip().replace(",", ".")
        try:
            return float(text) if text else None
        except ValueError:
            return None

    def save(self):
        a = app()
        name = self.ids.name.text.strip()
        if not name:
            a.toast("El nombre no puede quedar vacío.")
            return
        try:
            if getattr(self, "predio", False):
                a.db.save_unit(name, self.ids.code.text.strip(), self.sector or None,
                               self.irrigation or None, self.variety_id,
                               plant_year=self._year.text.strip() or None)
                a.db.update_variety(self.variety_id, notes=self.ids.notes.text)
                name = a.db.get_variety(self.variety_id)["name"]
            else:
                a.db.update_variety(self.variety_id, name=name, code=self.ids.code.text.strip(),
                                    notes=self.ids.notes.text, sector=self.sector or None,
                                    irrigation=self.irrigation or None)
        except ValueError as exc:
            a.toast(str(exc))
            return
        except Exception:
            a.toast("Ya existe otra variedad con ese nombre.")
            return
        values = {k: self._float(self.ids[k].text) for k in self.METRICS}
        values.update({k: self.ids[k].text for k in self.UNITS})
        values["historical_note"] = self.ids.historical_note.text
        a.db.save_metrics(self.variety_id, a.season, **values)
        a.toast("Ficha guardada")
        self.ids.bar.title = ph.unit_main(a.db.get_variety(self.variety_id))

    def custom_dialog(self, field: dict | None = None):
        a = app()
        form = CustomFieldForm()
        if field:
            form.ids.key.text, form.ids.value.text, form.ids.unit.text = \
                field["key"], field["value"], field["unit"]
        existing = [k for k in a.db.custom_field_keys()][:4] or \
            ["Diámetro de caña", "Grados Brix", "Incidencia fitosanitaria"]
        for k in existing[:3]:
            form.ids.suggestions.add_widget(MDFlatButton(
                text=k[:18], font_size="11sp", theme_text_color="Custom",
                text_color=c(theme.LEAF_DARK), on_release=lambda b, k=k: setattr(form.ids.key, "text", k)))

        def ok(f):
            try:
                a.db.set_custom_field(self.variety_id, a.season, f.ids.key.text,
                                      f.ids.value.text.strip(), f.ids.unit.text.strip())
            except ValueError as exc:
                a.toast(str(exc))
                return False
            self.load_custom()

        form_dialog("Campo personalizado", form, ok)

    def delete_custom(self, field_id: int):
        app().db.delete_custom_field(field_id)
        self.load_custom()

    def report(self):
        self.save()
        a = app()
        r = a.configured_reports()
        a.run_report(lambda: r.variety(self.variety_id, a.season, "pdf"))


# ===========================================================================
# Registro fenológico (variedad × semana)
# ===========================================================================
class StripThumb(GlassButton):
    primary = BooleanProperty(False)
    photo_id = NumericProperty(0)


class PhotoSlot(GlassCard):
    kind = StringProperty()
    caption = StringProperty()
    meta = StringProperty("Sin foto")
    has_photo = BooleanProperty(False)
    count = NumericProperty(0)
    screen = ObjectProperty()

    def show_busy(self, text: str = "Procesando foto…"):
        from kivymd.uix.spinner import MDSpinner
        box = self.ids.image_box
        fast_clear(box)
        box.add_widget(MDSpinner(size_hint=(None, None), size=(dp(32), dp(32)),
                                 pos_hint={"center_x": .5, "center_y": .5},
                                 color=c(theme.BERRY)))
        self.meta = text

    def show(self, photos: list[dict]):
        """photos: todas las fotos de este tipo, la principal primero."""
        box, strip = self.ids.image_box, self.ids.strip
        fast_clear(box)
        fast_clear(strip)
        self.count = len(photos)
        self.has_photo = bool(photos)
        if not photos:
            box.add_widget(thumb_widget(None, icon="camera-plus-outline"))
            self.meta = "Sin foto · la cámara suma una foto por toma"
            return
        main = photos[0]
        box.add_widget(thumb_widget(main["path"], 640))
        origin = {"camera": "cámara", "gallery": "galería"}.get(main["source"], main["source"])
        self.meta = (f"Principal: {origin} · {main['captured_at'][11:16]}"
                     + (" · toque una miniatura para cambiarla" if len(photos) > 1 else ""))
        if len(photos) > 1:
            for ph_ in photos:
                t = StripThumb(primary=bool(ph_["is_primary"]), photo_id=ph_["id"])
                t.add_widget(thumb_widget(ph_["path"], 160))
                t.bind(on_release=lambda w: self.screen.make_primary(self.kind, w.photo_id))
                strip.add_widget(t)


class ObservationScreen(MDScreen):
    variety_id = NumericProperty(0)
    week_id = NumericProperty(0)
    suggestion = ObjectProperty(None, allownone=True)

    def load(self, variety_id: int, week_id: int):
        a = app()
        self.variety_id, self.week_id = variety_id, week_id
        self.variety = a.db.get_variety(variety_id)
        self.week = a.db.get_week(week_id)
        self.obs = a.db.get_or_create_observation(variety_id, week_id)
        self.ids.bar.title = (a.db.display_name(self.variety) if a.db.is_trial
                              else ph.unit_main(self.variety))
        where = ph.unit_place(self.variety)       # predio: equipo y sector, en la línea de abajo
        self.ids.week_caption.text = (f"{where} · " if where else "") + \
            f"{ph.week_title(self.week)} · {self.week['label']}"
        self._refresh_slot("canopy")
        self._refresh_slot("detail")
        self.load_attachments()
        self.ids.bbch.text = self.obs["bbch_label"] or (
            ph.bbch_label(self.obs["bbch_code"], a.db.bbch_names())
            if self.obs["bbch_code"] is not None else "")
        self.ids.notes.text = self.obs["notes"] or ""
        self.ids.stamp.text = (f"Última modificación: {self.obs['updated_at'].replace('T', ' ')}"
                               if self.obs["bbch_code"] is not None else "Registro nuevo")
        self.suggestion = None
        self._show_ai_from_obs()
        self.refresh_location()

    # ------------------------------------------------ ubicación (opcional)
    GPS_SOURCES = {"gps": "GPS del teléfono", "foto": "desde la foto", "mapa": "marcada en el mapa"}

    def refresh_location(self):
        o = self.obs
        has = o["latitude"] is not None and o["longitude"] is not None
        self.ids.gps_icon.icon = "map-marker-check" if has else "map-marker-off-outline"
        self.ids.gps_icon.text_color = c(theme.BERRY if has else theme.MUTED)
        if has:
            import geo
            self.ids.gps_text.text = geo.fmt(o["latitude"], o["longitude"])
            parts = [self.GPS_SOURCES.get(o["gps_source"] or "", o["gps_source"] or "")]
            if o["gps_accuracy"]:
                parts.append(f"precisión ±{o['gps_accuracy']:.0f} m")
            self.ids.gps_detail.text = " · ".join(p for p in parts if p)
        else:
            self.ids.gps_text.text = "Sin ubicación"
            self.ids.gps_detail.text = ("Opcional: tome la posición actual, márquela en el mapa o "
                                        "se completa sola si la foto trae GPS.")
        self.ids.gps_clear.opacity = 1 if has else 0
        self.ids.gps_clear.disabled = not has

    def set_location(self, lat, lon, accuracy=None, source="gps"):
        a = app()
        a.db.update_observation(self.obs["id"], latitude=lat, longitude=lon,
                                gps_accuracy=accuracy, gps_source=source)
        a.db.set_setting("last_location", [lat, lon])
        self.obs = a.db.get_observation(self.variety_id, self.week_id)
        self.refresh_location()

    def clear_location(self):
        self.set_location(None, None, None, None)

    def locate_gps(self):
        a = app()
        import geo
        gps = getattr(self, "_gps", None)
        if gps is not None and not gps._done:
            gps.finish()   # «Usar ahora»: se queda con la mejor lectura obtenida
            return

        def granted(ok):
            if not ok:
                a.toast("Sin permiso de ubicación: puede marcar el punto en el mapa.")
                return
            Clock.schedule_once(lambda *_: start(), 0)

        def reset_button():
            self.ids.gps_btn.text = "Mi ubicación"
            self.ids.gps_btn.icon = "crosshairs-gps"

        def start():
            obs_id = self.obs["id"]
            self.ids.gps_text.text = "Buscando señal GPS…"
            self.ids.gps_detail.text = (f"Objetivo ±{geo.LocationRequest.TARGET_M:.0f} m · mejor al aire "
                                        "libre, con el teléfono quieto")
            self.ids.gps_btn.text = "Usar ahora"
            self.ids.gps_btn.icon = "check"

            def progress(lat, lon, acc):
                if self.obs["id"] != obs_id:
                    return
                self.ids.gps_text.text = f"{geo.fmt(lat, lon)}"
                self.ids.gps_detail.text = (f"Precisión actual ±{acc:.0f} m · buscando ±"
                                            f"{geo.LocationRequest.TARGET_M:.0f} m…")
                self.ids.gps_btn.text = f"Usar ahora (±{acc:.0f} m)"

            def done(lat, lon, acc):
                self._gps = None
                reset_button()
                if self.obs["id"] != obs_id:
                    return
                self.set_location(lat, lon, acc, "gps")
                if acc <= geo.LocationRequest.TARGET_M:
                    a.toast(f"Ubicación guardada (±{acc:.0f} m)")
                else:
                    a.toast(f"Ubicación guardada con ±{acc:.0f} m (no se logró ±10 m: "
                            "pruebe al aire libre y reintente)")

            def fail(msg):
                self._gps = None
                reset_button()
                self.refresh_location()
                a.toast(msg)

            try:
                self._gps = geo.LocationRequest(done, fail, progress)
                self._gps.start()
            except Exception as exc:  # noqa: BLE001
                fail(f"No se pudo leer el GPS: {exc}")

        geo.request_location_permission(granted)

    def on_leave(self, *_):
        gps = getattr(self, "_gps", None)
        if gps is not None:
            gps.cancel()   # no dejar el GPS encendido al salir del registro
            self._gps = None
            self.ids.gps_btn.text = "Mi ubicación"
            self.ids.gps_btn.icon = "crosshairs-gps"

    def pick_on_map(self):
        a = app()
        o = self.obs
        if o["latitude"] is not None:
            start, zoom = (o["latitude"], o["longitude"]), 18
        elif a.db.get_setting("last_location"):
            start, zoom = tuple(a.db.get_setting("last_location")), 17
        else:
            import geo
            start, zoom = geo.DEFAULT_CENTER, 6
        map_dialog(start, zoom, lambda lat, lon: self.set_location(lat, lon, None, "mapa"))

    def _show_ai_from_obs(self):
        o = self.obs
        fast_clear(self.ids.alternatives)
        if o["ai_code"] is None:
            self.ids.ai_label.text = "Suba la foto de detalle para obtener una sugerencia."
            self.ids.ai_conf.value = 0
            self.ids.ai_conf_text.text = ""
            self.ids.ai_explain.text = ""
            self.ids.accept_btn.disabled = True
            return
        self.ids.ai_label.text = ph.bbch_label(o["ai_code"], app().db.bbch_names())
        conf = o["ai_confidence"] or 0
        self.ids.ai_conf.value = conf
        self.ids.ai_conf_text.text = f"{conf:.0%} confianza"
        try:
            import json
            detail = json.loads(o["ai_detail"] or "{}")
        except ValueError:
            detail = {}
        self.ids.ai_explain.text = detail.get("explanation", "")
        self._alternatives(detail.get("top", []))
        self.ids.accept_btn.disabled = False

    def _alternatives(self, top):
        box = self.ids.alternatives
        fast_clear(box)
        for code, p in top[1:3]:
            box.add_widget(MDRectangleFlatButton(
                text=f"BBCH {ph.code_str(code)} · {p:.0%}", theme_text_color="Custom",
                text_color=c(theme.LEAF_DARK), line_color=c(theme.LINE),
                on_release=lambda b, code=code: self._set_bbch(code)))

    def _set_bbch(self, code: int):
        self.ids.bbch.text = ph.bbch_label(code, app().db.bbch_names())

    # ------------------------------------------------------ fotos adjuntas
    def load_attachments(self):
        a = app()
        box = self.ids.attachments
        fast_clear(box)
        items = a.db.list_attachments(self.variety["id"], week_id=self.week["id"])
        for f in items:
            row = AttachmentRow(caption=f["caption"] or "", item=f, screen=self,
                                date=ph.format_date_es(_dt.date.fromisoformat(f["captured_at"][:10])))
            row.ids.thumb_box.add_widget(thumb_widget(f["path"], 160))
            box.add_widget(row)
        if not items:
            box.add_widget(MDLabel(text="Sin fotos adjuntas.", font_style="Caption",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))

    def attach(self, source: str):
        """Fotos adjuntas a ESTE registro semanal (tomar o elegir de la galería) con descripción."""
        a = app()
        variety, week = self.variety, self.week
        base = ph.photo_basename(variety, week["start_date"], "attachment", trial=a.db.code)

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            a.toast("Guardando foto…" if len(paths) == 1 else f"Guardando {len(paths)} fotos…")

            def work():
                ids, error = [], None
                try:
                    dest_dir = data_subdir("photos", f"T{week['season']}", f"S{week['week_number']:02d}")
                    for tmp in paths:
                        path = store_photo(tmp, dest_dir, base, exact=True)
                        ids.append(a.db.add_attachment(
                            variety["id"], week["season"], path, week_id=week["id"],
                            source="camera" if origin == "camera" else "gallery"))
                        a.thumb(path, 160)
                        a.backup_extra(path, week["start_date"], "Adjuntas")
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: stored(ids, error))

            def stored(ids, error):
                if self.week["id"] != week["id"] or self.variety["id"] != variety["id"]:
                    return
                self.load_attachments()
                if error:
                    a.toast(f"No se pudo guardar la foto: {error}")
                elif len(ids) == 1:
                    self.caption_dialog(a.db.query_one(
                        "SELECT * FROM variety_attachments WHERE id=?", (ids[0],)))

            a.workers.submit(work)

        if source == "camera":
            a.media.take_photo(done, base, exact=True)
        else:
            a.media.pick_images(done)

    def caption_dialog(self, item: dict | None):
        if not item:
            return
        a = app()
        form = CaptionForm()
        form.ids.caption.text = item["caption"] or ""

        def ok(f):
            a.db.set_attachment_caption(item["id"], f.ids.caption.text)
            self.load_attachments()

        form_dialog("Descripción de la foto", form, ok)

    def delete_attachment(self, item: dict):
        def go():
            app().db.delete_attachment(item["id"])
            self.load_attachments()

        confirm("Quitar foto adjunta", "La foto deja de aparecer en el registro y en los informes "
                "(el archivo se conserva en el teléfono).", [("Quitar", go)])

    # -------------------------------------------------------------- fotos
    def _refresh_slot(self, kind: str):
        self.ids[kind].show(app().db.list_photos(self.obs["id"], kind))

    def capture(self, kind: str, source: str):
        """Cada toma (o cada foto elegida de la galería) SE SUMA al registro."""
        a = app()

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            season, n = self.week["season"], self.week["week_number"]
            obs_id = self.obs["id"]
            self.ids[kind].show_busy("Procesando foto…" if len(paths) == 1
                                     else f"Procesando {len(paths)} fotos…")

            def work():  # normalizar y guardar fuera del hilo de la interfaz
                error = None
                try:
                    dest_dir = data_subdir("photos", f"T{season}", f"S{n:02d}")
                    base = ph.photo_basename(self.variety, self.week["start_date"], kind, trial=a.db.code)
                    for tmp in paths:
                        if self.obs["latitude"] is None:
                            import geo
                            gps = geo.exif_gps(tmp)
                            if gps:
                                Clock.schedule_once(lambda *_, g=gps: (
                                    self.set_location(g[0], g[1], None, "foto"),
                                    a.toast("Ubicación tomada de la foto")))
                        path = store_photo(tmp, dest_dir, base, exact=True)
                        pid = a.db.add_photo(obs_id, kind, path, source=origin)
                        a.thumb(path, 640)
                        a.thumb(path, 160)
                        a.backup_photo(pid, path)
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: stored(error))

            def stored(error):
                if self.obs["id"] != obs_id:  # el usuario ya cambió de registro
                    return
                self._refresh_slot(kind)
                if error:
                    a.toast(f"No se pudo guardar la foto: {error}")
                    return
                if origin == "camera":
                    a.toast("Foto agregada · toque la cámara otra vez para sumar más")
                if kind == "detail":
                    self.analyze()

            a.workers.submit(work)

        if source == "camera":
            # Mismo nombre que en la app y en Drive: 20260928-C11G, 20260928-C11G-2…
            seq = len(a.db.list_photos(self.obs["id"], kind)) + 1
            hint = ph.photo_basename(self.variety, self.week["start_date"], kind, seq, trial=a.db.code)
            a.media.take_photo(done, hint, exact=True)
        else:
            a.media.pick_images(done)

    def make_primary(self, kind: str, photo_id: int):
        app().db.set_primary(photo_id)
        self._refresh_slot(kind)
        app().toast("Foto principal actualizada (es la que aparece en los informes)")

    def remove_photo(self, kind: str):
        a = app()
        photo = a.db.get_photos(self.obs["id"]).get(kind)
        if not photo:
            return

        def do():
            a.db.delete_photo(photo["id"])
            self._refresh_slot(kind)

        confirm("Quitar la foto principal",
                "La foto se desvincula del registro (el archivo se conserva en el teléfono). "
                "Si hay otras fotos, la más reciente pasa a ser la principal.", [("Quitar", do)])

    # ----------------------------------------------------------------- IA
    def analyze(self):
        a = app()
        details = [p["path"] for p in a.db.list_photos(self.obs["id"], "detail")]
        if not details:
            a.toast("Primero agregue la foto de detalle (Foto 2).")
            return
        self.ids.spinner.active = True
        self.ids.ai_label.text = ("Analizando foto de detalle…" if len(details) == 1
                                  else f"Analizando {len(details)} fotos de detalle…")
        prev = a.db.previous_observation(self.variety_id, self.week["season"],
                                         self.week["week_number"])
        previous = (prev["bbch_code"], prev["week_number"]) if prev else None
        notes = self.ids.notes.text
        obs_id = self.obs["id"]

        def work():
            try:
                s = a.classifier.suggest(details, self.week["week_number"], previous, notes)
                a.db.update_observation(obs_id, ai_code=s.code, ai_confidence=s.confidence,
                                        ai_detail=s.as_detail_json())
                self._analysis_done(s, None)
            except Exception as exc:  # noqa: BLE001
                self._analysis_done(None, exc)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _analysis_done(self, s, error):
        self.ids.spinner.active = False
        if error:
            self.ids.ai_label.text = "No se pudo analizar la imagen."
            self.ids.ai_explain.text = str(error)
            return
        self.suggestion = s
        self.obs = app().db.get_observation(self.variety_id, self.week_id)
        self._show_ai_from_obs()
        if not self.ids.bbch.text.strip():  # sugerencia pre-cargada en el campo editable
            self.ids.bbch.text = s.label

    def accept_ai(self):
        if self.obs["ai_code"] is not None:
            self._set_bbch(self.obs["ai_code"])

    def open_scale(self, caller):
        bbch_dialog("Escala BBCH · frambueso", app().db, self._set_bbch,
                    current=ph.parse_bbch_code(self.ids.bbch.text or ""))

    # -------------------------------------------------------------- guardar
    def save(self):
        a = app()
        text = self.ids.bbch.text.strip()
        code = ph.parse_bbch_code(text)
        if text and code is None:
            a.toast("Indique un código BBCH (ej. «BBCH 65: Plena floración»).")
            return
        ai_code = self.obs["ai_code"]
        a.db.update_observation(
            self.obs["id"], bbch_code=code, bbch_label=text, notes=self.ids.notes.text,
            observed_at=_dt.date.today().isoformat(),
            ai_accepted=None if ai_code is None or code is None else int(code == ai_code))
        if code is not None and a.db.get_setting("ai_auto_learn", True):
            # Aprendizaje continuo: cada foto de detalle del registro (con su estado
            # confirmado) se suma a la memoria de la IA, en segundo plano.
            photos = [p for p in a.db.list_photos(self.obs["id"], "detail") if os.path.exists(p["path"])]

            def learn():
                for p in photos:
                    a.classifier.add_reference(p["path"], code, photo_id=p["id"])

            if photos:
                a.workers.submit(learn)
        a.toast("Registro guardado")
        a.back()


# ===========================================================================
# Widgets gráficos de la vista previa
# ===========================================================================
class ProgressRing(Widget):
    """Anillo de avance (0..1) con el porcentaje al centro."""
    value = NumericProperty(0)
    thickness = NumericProperty(dp(9))
    color = ColorProperty(c(theme.BERRY))
    track = ColorProperty(c(theme.BERRY_SOFT))


def _muted_label(text: str):
    return MDLabel(text=text, font_style="Caption", adaptive_height=True, halign="center",
                   theme_text_color="Custom", text_color=c(theme.MUTED))


class StageChip(BoxLayout):
    """Etiqueta de estadio (leyenda del mapa)."""
    text = StringProperty()
    bg = ColorProperty(c("#FFFFFF"))
    fg = ColorProperty(c(theme.INK))


class PreviewTile(ButtonBehavior, BoxLayout):
    """Ficha de la vista previa: la frambuesa dibujada de la variedad (gris si esa semana
    no tiene registro), su estado BBCH y nombre. El botón ES la frambuesa: solo responde
    al tocar el fruto (no un recuadro)."""
    title = StringProperty()
    subtitle = StringProperty()
    sub_color = ColorProperty(c(theme.MUTED))
    badge = StringProperty()
    badge_bg = ColorProperty(c("#FFFFFF", .9))
    badge_fg = ColorProperty(c(theme.INK))
    berry = StringProperty()

    def collide_point(self, x, y):
        img = self.ids.get("art")
        if img is None or not img.collide_point(x, y) or not self.berry:
            return False
        w, h = img.norm_image_size
        if not w or not h:
            return False
        u = (x - (img.center_x - w / 2)) / w
        v = (y - (img.center_y - h / 2)) / h
        if not (0 <= u < 1 and 0 <= v < 1):
            return False
        mask = berry_mask(self.berry)
        if mask is None:
            return True
        mw, mh = mask.size
        return mask.getpixel((int(u * mw), int((1 - v) * mh))) > 60


_berry_masks: dict = {}


def berry_mask(path: str):
    """Silueta (canal alfa reducido) de la frambuesa para saber si el toque cae en el
    fruto. Se lee con Pillow, aparte: leerla con Kivy reemplazaba la textura en caché y
    las frambuesas podían verse como cuadros negros."""
    if path not in _berry_masks:
        try:
            from PIL import Image as PILImage
            with PILImage.open(path) as im:
                _berry_masks[path] = im.convert("RGBA").getchannel("A").resize((48, 56))
        except Exception:  # noqa: BLE001
            _berry_masks[path] = None
    return _berry_masks[path]


class StageNames(Widget):
    """Columna fija con el nombre COMPLETO de cada variedad (a la par del mapa)."""
    rows = ListProperty([])
    MAX_W = dp(170)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint = (None, None)
        self.bind(rows=self._layout, pos=self._redraw)
        self._layout()

    def _layout(self, *_):
        from kivy.core.text import Label as CoreLabel
        self._tex = []
        widest = dp(40)
        for r in self.rows:
            lb = CoreLabel(text=r["name"], font_size=dp(11), bold=True)
            lb.refresh()
            tex = lb.texture
            if tex.width > self.MAX_W:   # muy largo: en dos líneas
                lb = CoreLabel(text=r["name"], font_size=dp(10), bold=True,
                               text_size=(self.MAX_W, None), halign="left")
                lb.refresh()
                tex = lb.texture
            self._tex.append(tex)
            widest = max(widest, tex.width)
        self.width = min(widest, self.MAX_W) + dp(8)
        self.height = StageHeatmap.HEAD + len(self.rows) * (StageHeatmap.CELL_H + StageHeatmap.GAP)
        self._redraw()

    def _redraw(self, *_):
        from kivy.graphics import Color, Rectangle
        self.canvas.clear()
        with self.canvas:
            Color(*c(theme.INK))
            for i, tex in enumerate(getattr(self, "_tex", [])):
                y = self.top - StageHeatmap.HEAD - (i + 1) * (StageHeatmap.CELL_H + StageHeatmap.GAP)
                Rectangle(texture=tex, size=tex.size,
                          pos=(self.x, y + (StageHeatmap.CELL_H - tex.height) / 2))


class StageHeatmap(Widget):
    """Mapa variedad × semana coloreado por estadio BBCH (con el código en la celda).
    Tocar una celda abre ese registro (on_cell)."""
    rows = ListProperty([])
    weeks = ListProperty([])
    NAME_W, CELL_W, CELL_H, GAP, HEAD = 0, dp(34), dp(24), dp(3), dp(18)   # nombres: StageNames

    def __init__(self, on_cell=None, **kw):
        super().__init__(**kw)
        self.on_cell = on_cell
        self.size_hint = (None, None)
        self._tex = {}
        self.bind(rows=self._layout, weeks=self._layout, pos=self._redraw)

    def _layout(self, *_):
        self.width = self.NAME_W + max(1, len(self.weeks)) * self.CELL_W
        self.height = self.HEAD + len(self.rows) * (self.CELL_H + self.GAP)
        self._redraw()

    def _text(self, text, size, bold=False):
        key = (text, size, bold)
        if key not in self._tex:
            from kivy.core.text import Label as CoreLabel
            lb = CoreLabel(text=text, font_size=size, bold=bold)
            lb.refresh()
            self._tex[key] = lb.texture
        return self._tex[key]

    def _cell_rect(self, i, j):
        x = self.x + self.NAME_W + j * self.CELL_W + self.GAP / 2
        y = self.top - self.HEAD - (i + 1) * (self.CELL_H + self.GAP)
        return x, y, self.CELL_W - self.GAP, self.CELL_H

    def _redraw(self, *_):
        from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
        self.canvas.clear()
        with self.canvas:
            for j, wk in enumerate(self.weeks):
                t = self._text(wk, dp(10), True)
                Color(*c(theme.MUTED))
                x = self.x + self.NAME_W + j * self.CELL_W + (self.CELL_W - t.size[0]) / 2
                Rectangle(texture=t, size=t.size, pos=(x, self.top - self.HEAD + dp(3)))
            for i, r in enumerate(self.rows):
                for j, cell in enumerate(r["cells"]):
                    x, y, w, h = self._cell_rect(i, j)
                    code = cell["code"]
                    bg, fg = theme.stage_colors(code)
                    if code is None:
                        Color(*c("#FFFFFF", .5))
                        RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(6)])
                        if cell["n_photos"]:   # foto sin estado: punto frambuesa
                            Color(*c(theme.BERRY_LIGHT))
                            RoundedRectangle(pos=(x + w / 2 - dp(3), y + h / 2 - dp(3)),
                                             size=(dp(6), dp(6)), radius=[dp(3)])
                        continue
                    Color(*bg)
                    RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(6)])
                    Color(*c(theme.LEAF_DARK, .18))
                    Line(rounded_rectangle=(x, y, w, h, dp(6)), width=dp(.8))
                    t = self._text(ph.code_str(code), dp(10), True)
                    Color(*fg)
                    Rectangle(texture=t, size=t.size, pos=(x + (w - t.size[0]) / 2, y + (h - t.size[1]) / 2))

    def on_touch_up(self, touch):
        if not self.collide_point(*touch.pos) or self.on_cell is None:
            return False
        if abs(touch.x - touch.ox) > dp(12) or abs(touch.y - touch.oy) > dp(12):
            return False   # fue un desplazamiento, no un toque
        for i, r in enumerate(self.rows):
            for j, cell in enumerate(r["cells"]):
                x, y, w, h = self._cell_rect(i, j)
                if x <= touch.x <= x + w and y <= touch.y <= y + h:
                    self.on_cell(cell)
                    return True
        return False


# ===========================================================================
# Vista previa de informes (sin enviar)
# ===========================================================================
class PreviewTab(MDScreen):
    """Vista previa: «Por variedad» (la frambuesa de cada variedad; tocarla abre todo su
    informe) y «Matriz global» (estados BBCH de la temporada, o de un mes)."""
    kind = StringProperty("variety")
    KIND_NAMES = {"variety": "Por variedad", "matrix": "Matriz global"}
    sel_month = ObjectProperty(None, allownone=True)   # (año, mes) o None = toda la temporada
    variety_label = StringProperty("Por variedad")    # «Por sector» en predios con plano
    sel_sector = StringProperty("")

    def _plan(self):
        """Plano de sectores del predio activo (None en I+D o si no hay plano)."""
        a = app()
        ws = getattr(a, "workspace", None) or {}
        if ws.get("profile") != "predio":
            return None
        from ui.sector_map import load_map
        return load_map(ws.get("code"))

    def pick_season(self):
        season_dialog(self.refresh)

    def refresh(self):
        a = app()
        if getattr(self, "_season", None) != a.season:
            self._season = a.season
            self.sel_month = None
        self.ids.season_chip.text = ph.season_title(a.season)
        plan = self._plan()
        if plan is not getattr(self, "_plan_on", None):
            self._plan_on, self.sel_sector = plan, ""
        self.variety_label = "Por sector" if plan else "Por variedad"
        self._build_params()
        self._summarize()

    def set_kind(self, kind: str):
        self.kind = kind
        self.refresh()

    # ------------------------------------------------------------ parámetros
    def _months(self):
        out = []
        for w in app().db.list_weeks(app().season, trim_empty=True):
            d = _dt.date.fromisoformat(w["start_date"])
            if (d.year, d.month) not in out:
                out.append((d.year, d.month))
        return out

    def _build_params(self):
        box = self.ids.params
        fast_clear(box)
        if self.kind == "variety":
            box.add_widget(MDLabel(text=("Toque un sector del plano para ver su información; tocando "
                                         "un equipo de riego se acerca." if self._plan() else
                                         "Toque una frambuesa para ver todo el informe de esa variedad."),
                                   font_style="Caption", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            return
        from kivy.factory import Factory
        from kivy.uix.stacklayout import StackLayout
        chips = StackLayout(size_hint_y=None, spacing=dp(6))
        chips.bind(minimum_height=chips.setter("height"))
        options = [(None, "Toda la temporada")] + [
            (ym, f"{ph.MESES[ym[1] - 1].capitalize()} {ym[0]}") for ym in self._months()]
        for ym, label in options:
            b = Factory.SegButton(text=label, selected=self.sel_month == ym, size_hint_x=None,
                                  height=dp(36), font_size="14sp")
            b.text_size = (None, None)          # el ancho lo da el texto (no se corta)
            b.texture_update()
            b.width = b.texture_size[0] + dp(30)
            b.bind(on_release=lambda w, ym=ym: self._set_month(ym))
            chips.add_widget(b)
        box.add_widget(chips)

    def _set_month(self, ym):
        self.sel_month = ym
        self.refresh()

    def _range(self):
        """(desde, hasta) en número de semana de muestreo; None = toda la temporada."""
        if not self.sel_month:
            return None
        ws = [w for w in app().db.list_weeks(app().season)
              if _dt.date.fromisoformat(w["start_date"]).timetuple()[:2] == tuple(self.sel_month)]
        if not ws:
            return None
        return ws[0]["week_number"], ws[-1]["week_number"]

    # --------------------------------------------------------------- resumen
    def _summarize(self):
        from reporter import report_summary
        a = app()
        rng = self._range() if self.kind == "matrix" else None
        if rng:
            sm = report_summary(a.db, "period", a.season, week_from=rng[0], week_to=rng[1])
        else:
            sm = report_summary(a.db, "matrix", a.season)
        ids = self.ids
        ids.sum_title.text = ("Matriz global · " + (f"{ph.MESES[self.sel_month[1] - 1].capitalize()} "
                                                   f"{self.sel_month[0]}" if rng else "toda la temporada")
                              if self.kind == "matrix" else f"{self.variety_label} · toda la temporada")
        ratio = sm["complete"] / sm["cells"] if sm["cells"] else 0
        ids.ring.value = ratio
        ids.ring_text.text = f"{ratio:.0%}"
        ids.metric_photos.text = f"{sm['photos']}/{sm['photos_expected']}"
        ids.metric_bbch.text = f"{sm['bbch']}/{sm['cells']}"
        ids.metric_notes.text = str(sm["notes"])
        self._build_visual(sm)
        lack = []
        if sm["missing_photos"]:
            n = sm["missing_photos"]   # registros sin ninguna foto
            lack.append(f"{n} registro" + ("s" if n != 1 else "") + " sin fotos")
        if sm["missing_bbch"]:
            lack.append(f"{sm['missing_bbch']} estado" + ("s" if sm["missing_bbch"] != 1 else ""))
        ids.lack_text.text = ("Faltan " + " y ".join(lack)) if lack else "Completo"
        ids.lack_text.text_color = c(theme.BERRY) if lack else c(theme.LEAF)
        mb = sm["est_kb"] / 1024
        ids.size_text.text = f"≈ {mb:.1f} MB" if mb >= 1 else f"≈ {sm['est_kb']} KB"
        # «Por variedad»: el informe completo se abre desde cada frambuesa.
        ids.preview_btn.opacity = 1 if self.kind == "matrix" else 0
        ids.preview_btn.disabled = self.kind != "matrix"
        ids.preview_btn.height = dp(48) if self.kind == "matrix" else 0

    # ------------------------------------------------- frambuesas y mapa de estados
    def _open_cell(self, cell):
        """Celda del mapa: la línea de tiempo de esa variedad, en esa semana."""
        app().open_timeline(cell["variety_id"], cell["week_id"])

    def _build_visual(self, sm):
        a = app()
        box = self.ids.visual
        fast_clear(box)
        unit = "sectores" if (a.workspace or {}).get("profile") == "predio" else "variedades"
        codes = [cl["code"] for r in sm["rows"] for cl in r["cells"] if cl["code"] is not None]
        span = ""
        if codes:
            lo, hi = min(codes, key=ph.bbch_value), max(codes, key=ph.bbch_value)
            span = (f"BBCH {ph.code_str(lo)}" if lo == hi
                    else f"BBCH {ph.code_str(lo)} a {ph.code_str(hi)}")
        if self.kind == "variety" and self._plan():
            self._build_map(sm, self._plan(), box, span)
            return
        if self.kind == "variety" and a.db.is_predio:
            no_map_card(box, (a.workspace or {}).get("name") or "este predio")
        if self.kind == "variety":
            started = sum(1 for r in sm["rows"] if any(cl["code"] is not None or cl["n_photos"]
                                                       for cl in r["cells"]))
            self.ids.headline.text = " · ".join(x for x in (
                f"{started} de {len(sm['rows'])} {unit} con registros", span) if x)
            from kivy.uix.gridlayout import GridLayout
            grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
            grid.bind(minimum_height=grid.setter("height"))
            for r in sm["rows"]:
                grid.add_widget(self._tile(r))
            box.add_widget(grid)
            return
        self.ids.headline.text = " · ".join(x for x in (
            f"{len(sm['rows'])} {unit} × {len(sm['week_labels'])} semanas", span) if x) + \
            "  ·  toque una celda para abrir el registro"
        from kivy.uix.scrollview import ScrollView
        rows = [dict(r, name=ph.unit_compact(r)) for r in sm["rows"]]   # predio: «Meeker 2019 · E1-S1»
        names = StageNames(rows=rows)
        hm = StageHeatmap(on_cell=self._open_cell)
        hm.weeks, hm.rows = sm["week_labels"], rows
        row = BoxLayout(size_hint_y=None, height=hm.height)
        row.add_widget(names)
        sv = ScrollView(do_scroll_x=True, do_scroll_y=False, bar_width=dp(3),
                        scroll_type=["bars", "content"])
        sv.add_widget(hm)
        row.add_widget(sv)
        box.add_widget(row)
        if hm.width > dp(200):     # muchas semanas: arrancar en las más recientes
            Clock.schedule_once(lambda *_: setattr(sv, "scroll_x", 1), 0)
        macros = sorted({ph.macro_of(cd) for cd in codes})
        if macros:
            from kivy.uix.stacklayout import StackLayout
            legend = StackLayout(size_hint_y=None, spacing=dp(6))
            legend.bind(minimum_height=legend.setter("height"))
            for m in macros:
                bg, fg = theme.stage_colors(m * 10)
                legend.add_widget(StageChip(text=ph.MACRO_STAGES.get(m, ""), bg=bg, fg=fg))
            box.add_widget(legend)

    # ------------------------------------------------------- plano del predio
    def _sector_data(self, sm, plan):
        """Por sector del plano: sus unidades y totales; y las unidades sin ubicar."""
        counts = app().db.measure_counts(app().season)
        known = {s["id"]: s for s in plan["sectors"]}
        data = {sid: {"plan": s, "rows": [], "records": 0, "photos": 0, "measures": 0,
                      "last": None} for sid, s in known.items()}
        loose = []
        for r in sm["rows"]:
            sid = f"E{r.get('irrigation') or 0}-S{r.get('sector') or 0}"
            if sid not in data:
                loose.append(r)
                continue
            d = data[sid]
            d["rows"].append(r)
            d["records"] += sum(1 for cl in r["cells"] if cl["code"] is not None or cl["n_photos"])
            d["photos"] += sum(cl["n_photos"] for cl in r["cells"])
            d["measures"] += counts.get(r["variety_id"], 0)
            for i, cl in enumerate(r["cells"]):
                if cl["code"] is not None:
                    key = (i, ph.bbch_value(cl["code"]))
                    if d["last"] is None or key > d["last"][0]:
                        d["last"] = (key, cl)
        status = {}
        for sid, d in data.items():
            if d["records"] or d["measures"]:
                status[sid] = {"data": True, "dot": d["measures"] > 0}
        return data, status, loose

    def _build_map(self, sm, plan, box, span):
        data, status, loose = self._sector_data(sm, plan)
        self._sectors = data
        active = [sid for sid in data if sid in status]
        self.ids.headline.text = " · ".join(x for x in (
            f"{len(active)} de {len(data)} sectores con datos", span) if x)
        if self.sel_sector not in data:
            latest = max(active, key=lambda sid: (data[sid]["last"] or ((-1, -1), None))[0],
                         default="")
            self.sel_sector = latest

        self._map = sector_map_block(box, plan, status, self.sel_sector, self._select_sector)
        self._sector_box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8))
        box.add_widget(self._sector_box)
        self._fill_sector(self._sector_box, self.sel_sector)
        if loose:
            box.add_widget(MDLabel(text=f"Sin ubicar en el plano ({len(loose)}): falta su sector o "
                                        "equipo de riego en Ajustes › Variedades.",
                                   font_style="Caption", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            box.add_widget(self._tile_grid(loose))

    def _select_sector(self, sid):
        self.sel_sector = sid
        if getattr(self, "_map", None) is not None:
            self._map.selected = sid
        if getattr(self, "_sector_box", None) is not None:
            self._fill_sector(self._sector_box, sid)

    def _tile_grid(self, rows, before_open=None):
        from kivy.uix.gridlayout import GridLayout
        grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for r in rows:
            grid.add_widget(self._tile(r, before_open))
        return grid

    def _fill_sector(self, box, sid, before_open=None):
        """Ficha del sector elegido: datos del plano, totales y sus unidades (frambuesas)."""
        fast_clear(box)
        d = (getattr(self, "_sectors", None) or {}).get(sid)
        if not d:
            box.add_widget(MDLabel(text="Toque un sector del plano para ver su información.",
                                   font_style="Body2", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            return
        p = d["plan"]
        box.add_widget(MDLabel(text=f"Equipo de riego {p['equipo']} · sector {p['sector']}",
                               font_style="Subtitle1", bold=True, adaptive_height=True,
                               theme_text_color="Custom", text_color=c(theme.LEAF_DARK)))
        info = []
        if p.get("ha"):
            info.append(f"{p['ha']:.2f} ha".replace(".", ","))
        if p.get("hileras"):
            info.append(f"{p['hileras']} hileras")
        if p.get("variedades"):
            info.append("plano: " + ", ".join(p["variedades"]))
        if info:
            box.add_widget(MDLabel(text=" · ".join(info), font_style="Caption", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
        if not d["rows"]:
            box.add_widget(MDLabel(text="Sin unidades en este sector (se agregan en Ajustes › "
                                        "Variedades con este equipo de riego y sector).",
                                   font_style="Body2", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            return
        n = len(d["rows"])
        parts = [f"{n} unidad" + ("es" if n != 1 else ""),
                 f"{d['records']} registro" + ("s" if d["records"] != 1 else ""),
                 f"{d['photos']} foto" + ("s" if d["photos"] != 1 else ""),
                 f"{d['measures']} medici" + ("ones" if d["measures"] != 1 else "ón")]
        if d["last"]:
            cl = d["last"][1]
            parts.append(f"último: {cl['week']} · BBCH {ph.code_str(cl['code'])}")
        box.add_widget(MDLabel(text=" · ".join(parts), font_style="Body2", adaptive_height=True,
                               theme_text_color="Custom", text_color=c(theme.INK)))
        # Lo que se mide en el sector: cada variedad (con su año de plantación y código).
        rows = [dict(r, display=ph.unit_label(r)) for r in d["rows"]]
        box.add_widget(self._tile_grid(rows, before_open))

    def _tile(self, row, before_open=None):
        """Frambuesa de la variedad: a color si tiene registros en la temporada."""
        cells = [cl for cl in row["cells"] if cl["code"] is not None or cl["n_photos"]]
        last = next((cl for cl in reversed(row["cells"]) if cl["code"] is not None), None)
        if last is not None:
            code = last["code"]
            sub, col = f"{last['week']} · {ph.bbch_label(code)}", c(theme.MUTED)
        else:
            code = None
            sub, col = ("Sin estado registrado" if cells else "Sin registros"), c(theme.BERRY)
        bg, fg = bbch_tag_colors(code)
        tile = PreviewTile(title=row.get("display") or ph.unit_main(row), subtitle=sub, sub_color=col,
                           badge=f"BBCH {ph.code_str(code)}" if code is not None else "",
                           badge_bg=bg, badge_fg=fg,
                           berry=theme.berry_art(row.get("cultivar") or "", row["name"],
                                                 gray=not cells))

        def go(*_):
            if before_open:
                before_open()
            app().open_timeline(row["variety_id"])
        tile.bind(on_release=go)
        return tile

    # ----------------------------------------------------------- vista previa
    def open_preview(self):
        """Matriz global completa (de la temporada o del mes elegido)."""
        a = app()
        r = a.configured_reports()
        rng = self._range()
        self.ids.preview_btn.disabled = True
        self.ids.preview_btn.text = "Preparando vista previa…"

        def work():
            try:
                res = (r.matrix(a.season, rng[0], rng[1], package="preview") if rng
                       else r.matrix(a.season, package="preview"))
                Clock.schedule_once(lambda *_: self._ready(res, None))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: self._ready(None, error))

        a.workers.submit(work)

    def _ready(self, res, error):
        self.ids.preview_btn.disabled = False
        self.ids.preview_btn.text = "Ver vista previa completa"
        if error:
            app().toast(f"No se pudo preparar la vista previa: {error}")
            return
        app().media.preview(res.path, res.title)


# ===========================================================================
# Informes
# ===========================================================================
class ReportRow(GlassButton):
    title = StringProperty()
    meta = StringProperty()
    path = StringProperty()
    tab = ObjectProperty(None, allownone=True)


class ReportGroup(GlassButton):
    """Encabezado desplegable de un grupo de informes (semanales, fichas…)."""
    title = StringProperty()
    count = StringProperty()
    key = StringProperty()
    expanded = BooleanProperty(False)
    paths = ListProperty()
    tab = ObjectProperty(None, allownone=True)


# Grupos de la lista de informes: (prefijo del archivo, título)
REPORT_GROUPS = [("semanal", "Reportes semanales"), ("periodo", "Evolución mensual / rango"),
                 ("variedad", "Fichas por variedad"), ("matriz", "Matriz comparativa"),
                 ("tratamientos", "Comparación de tratamientos"), ("", "Mediciones y otros")]


class ReportsTab(MDScreen):
    sel_week = ObjectProperty(None, allownone=True)
    sel_from = ObjectProperty(None, allownone=True)
    sel_to = ObjectProperty(None, allownone=True)
    sel_variety = ObjectProperty(None, allownone=True)
    sel_month = ObjectProperty(None, allownone=True)

    def set_all_photos(self, active: bool):
        app().db.set_setting("report_all_photos", bool(active))

    def refresh(self):
        a = app()
        self.ids.all_photos.active = bool(a.db.get_setting("report_all_photos", False))
        self._photo_mode_label()
        weeks = a.db.list_weeks(a.season)
        if not weeks:
            weeks = [a.db.current_week()]
        if self.sel_week is None or self.sel_week["season"] != a.season:
            self.sel_week = a.week
            self.sel_from, self.sel_to = weeks[0], a.week
        if self.sel_variety is None or not a.db.get_variety(self.sel_variety["id"]):
            vs = a.db.list_varieties()
            self.sel_variety = vs[0] if vs else None
        trial = a.db.is_trial
        # self.ids guarda referencias DÉBILES: al quitar la tarjeta de la pantalla se
        # liberaba y el refresco siguiente fallaba («weakly-referenced object…»).
        card = getattr(self, "_trial_card", None)
        if card is None:
            card = self._trial_card = self.ids.trial_card.__self__
        if trial and card.parent is None:
            self._card_parent.add_widget(card, index=self._card_index)
        elif not trial and card.parent is not None:
            self._card_parent, self._card_index = card.parent, card.parent.children.index(card)
            card.parent.remove_widget(card)
        self.ids.variety_title.text = ("3 · FICHA COMPLETA POR PARCELA" if trial
                                       else "3 · FICHA COMPLETA POR VARIEDAD")
        self._labels()
        self.list_recent()

    def _labels(self):
        ids = self.ids
        ids.week_btn.text = f"{ph.week_title(self.sel_week)} · {self.sel_week['label']}"
        ids.from_btn.text = f"Desde {ph.week_short(self.sel_from)}"
        ids.to_btn.text = f"Hasta {ph.week_short(self.sel_to)}"
        ids.month_btn.text = (f"Mes: {ph.MESES[self.sel_month[1] - 1].capitalize()} {self.sel_month[0]}"
                              if self.sel_month else "Elegir mes (o rango abajo)")
        ids.variety_btn.text = ph.unit_compact(self.sel_variety) if self.sel_variety else "Sin variedades"

    def pick_week(self, caller, target: str):
        a = app()
        weeks = a.db.list_weeks(a.season)

        def choose(w):
            if target == "week":
                self.sel_week = w
            elif target == "from":
                self.sel_from, self.sel_month = w, None
            else:
                self.sel_to, self.sel_month = w, None
            self._labels()

        pick_dialog("Semana de muestreo", [(ph.week_title(w), w["label"], lambda w=w: choose(w))
                                            for w in reversed(weeks)])

    def pick_month(self, caller):
        a = app()
        months = []
        for w in a.db.list_weeks(a.season):
            d = _dt.date.fromisoformat(w["start_date"])
            if (d.year, d.month) not in months:
                months.append((d.year, d.month))

        def choose(ym):
            self.sel_month = ym
            ws = [w for w in a.db.list_weeks(a.season)
                  if _dt.date.fromisoformat(w["start_date"]).timetuple()[:2] == ym]
            self.sel_from, self.sel_to = ws[0], ws[-1]
            self._labels()

        open_menu(caller, [(f"{ph.MESES[m - 1].capitalize()} {y}", lambda ym=(y, m): choose(ym))
                           for y, m in months])

    def pick_variety(self, caller):
        def choose(v):
            self.sel_variety = v
            self._labels()
        open_menu(caller, [(ph.unit_compact(v), lambda v=v: choose(v)) for v in app().db.list_varieties()])

    def pick_photo_mode(self):
        a = app()

        def choose(mode):
            a.db.set_setting("report_photo_mode", mode)
            self._photo_mode_label()

        from reporter import ReportGenerator
        hints = {"both": "La foto general y la de detalle de cada variedad",
                 "detail": "Solo la foto de detalle representativa",
                 "canopy": "Solo la foto general (canopia) representativa"}
        pick_dialog("Fotos en los informes", [(label, hints[mode], lambda m=mode: choose(m))
                                              for mode, label in ReportGenerator.PHOTO_MODES.items()])

    def _photo_mode_label(self):
        from reporter import ReportGenerator
        mode = app().db.get_setting("report_photo_mode", "both")
        self.ids.photo_mode_btn.text = f"Fotos: {ReportGenerator.PHOTO_MODES.get(mode, mode)}"

    def generate(self, kind: str, package: str = "pdf"):
        a = app()
        r = a.configured_reports()
        if kind == "weekly":
            job = lambda: r.weekly(self.sel_week["id"], package)  # noqa: E731
        elif kind == "period":
            if self.sel_month:
                job = lambda: r.monthly(a.season, *self.sel_month, package=package)  # noqa: E731
            else:
                job = lambda: r.period(a.season, self.sel_from["week_number"],  # noqa: E731
                                       self.sel_to["week_number"], package)
        elif kind == "variety":
            if not self.sel_variety:
                return
            job = lambda: r.variety(self.sel_variety["id"], a.season, package)  # noqa: E731
        elif kind == "treatments":
            job = lambda: r.treatments(a.season, package)  # noqa: E731
        else:
            job = lambda: r.matrix(a.season, package=package)  # noqa: E731
        a.run_report(job, on_done=lambda _res: self.list_recent())

    def list_recent(self):
        box = self.ids.recent
        fast_clear(box)
        a = app()
        folder = a.reports.out_dir
        code = a.db.code

        def mine(name: str) -> bool:   # solo los informes de este ensayo o predio
            if not code:
                return True
            if f"_{code}_" in name:
                return True
            # Informes de versiones anteriores (sin código): eran de «Nuevas variedades».
            return code == "NV" and not re.search(r"_[A-Z0-9]{2,4}_\d{4}", name)

        files = sorted((os.path.join(folder, f) for f in os.listdir(folder)
                        if f.endswith((".pdf", ".html", ".zip", ".xlsx")) and mine(f)),
                       key=os.path.getmtime, reverse=True)
        groups = {key: [] for key, _t in REPORT_GROUPS}
        for p in files:
            name = os.path.basename(p)
            key = next((k for k, _t in REPORT_GROUPS if k and name.startswith(k + "_")), "")
            groups[key].append(p)
        opened = getattr(self, "_opened", set())
        self._opened = opened
        trial = a.db.is_trial
        for key, title in REPORT_GROUPS:
            items = groups[key]
            if not items:
                continue
            if key == "variedad" and trial:
                title = "Fichas por parcela"
            head = ReportGroup(title=title, key=key, paths=items, tab=self, expanded=key in opened,
                               count=f"{len(items)} {'informe' if len(items) == 1 else 'informes'}")
            head.bind(on_release=self._toggle_group)
            box.add_widget(head)
            if key not in opened:
                continue
            for p in items:
                ts = _dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d-%m-%Y %H:%M")
                box.add_widget(ReportRow(title=os.path.basename(p), path=p, tab=self,
                                         meta=f"{ts} · {max(1, os.path.getsize(p) // 1024)} KB"))
        if not files:
            box.add_widget(MDLabel(text="Aún no se han generado informes.", font_style="Caption",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))

    def _toggle_group(self, head):
        if head.key in self._opened:
            self._opened.discard(head.key)
        else:
            self._opened.add(head.key)
        self.list_recent()

    def delete_reports(self, paths: list, group: str | None = None):
        """Borra informes del teléfono (con confirmación). Las copias enviadas o subidas a
        Drive no se tocan."""
        a = app()
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            return
        what = (f"«{os.path.basename(paths[0])}»" if len(paths) == 1 and not group
                else f"los {len(paths)} informes de «{group}»" if group else f"{len(paths)} informes")

        def go():
            n = 0
            for p in paths:
                try:
                    os.remove(p)
                    n += 1
                except OSError:
                    pass
            a.db.log("delete", "report", None, ", ".join(os.path.basename(p) for p in paths)[:500])
            a.toast(f"{n} {'informe eliminado' if n == 1 else 'informes eliminados'}")
            self.list_recent()

        confirm("Eliminar informes",
                f"Se eliminará {what} de este teléfono. Las copias que ya envió o subió a "
                "Google Drive no se borran. Siempre puede volver a generarlos.",
                [("Eliminar", go)])


# ===========================================================================
# Ajustes
# ===========================================================================
class SettingsTab(MDScreen):
    _loading = False

    def refresh(self):
        a = app()
        cfg = a.reminders.config()
        self._loading = True
        self.ids.enabled.active = cfg.enabled
        self._loading = False
        self.ids.day_btn.text = ph.DIAS[cfg.weekday].capitalize()
        self.ids.time_btn.text = f"{cfg.hour:02d}:{cfg.minute:02d}"
        self.ids.freq_btn.text = FREQUENCIES.get(cfg.every_weeks, f"Cada {cfg.every_weeks} semanas")
        nxt = a.reminders.next_time()
        self.ids.next_text.text = (f"Próximo aviso: {ph.DIAS[nxt.weekday()]} "
                                   f"{ph.format_date_es(nxt.date())}, {nxt:%H:%M}"
                                   if nxt else "Recordatorios desactivados.")
        box = self.ids.exact_box
        fast_clear(box)
        if IS_ANDROID and cfg.enabled and not can_schedule_exact():
            box.add_widget(MDRectangleFlatButton(
                text="Permitir alarmas exactas", theme_text_color="Custom",
                text_color=c(theme.WARN), line_color=c(theme.WARN),
                on_release=lambda *_: request_exact_alarm_permission()))
        self.ids.season_text.text = (f"{ph.season_title(a.season)} · semana en curso: "
                                     f"{ph.week_title(a.week)} ({a.week['label']})")
        self.ids.first_week_text.text = self._first_week_text(a)
        n = sum(a.db.reference_counts().values())
        # Sin instanciar el clasificador (evita cargar numpy solo por abrir Ajustes).
        ext = a.__dict__.get("classifier")
        engine = f"Extractor: {ext.extractor.name} · " if ext else ""
        self.ids.ai_text.text = (f"{engine}{n} fotos de referencia. "
                                 "Todo el análisis se ejecuta en el teléfono, sin conexión.")
        self.ids.data_text.text = f"PhenoRubus versión {app_version()} · datos locales: {a.db.path}"
        self.refresh_drive()
        self.refresh_sync()

    # ------------------------------------------------ respaldo en Google Drive
    def refresh_drive(self, st=None):
        a = app()
        drive = a.drive
        if not getattr(self, "_drive_hooked", False):
            self._drive_hooked = True
            drive.listeners.append(lambda status: Clock.schedule_once(
                lambda *_: self.refresh_drive(status)))
        st = st or drive.status()
        on = st["enabled"]
        total = st["pending"] + st["done"] + st["errors"]
        if not st["available"]:
            title, icon, col = ("Disponible en el teléfono" if IS_ANDROID else "Requiere la versión instalada"), "cloud-off-outline", theme.MUTED
        elif not on:
            title, icon, col = "Sin conectar", "cloud-off-outline", theme.MUTED
        elif st["running"]:
            title, icon, col = "Subiendo fotos…", "cloud-sync-outline", theme.LEAF
        elif st["errors"] and not st["pending"]:
            title, icon, col = "Con errores", "cloud-alert-outline", theme.WARN
        elif st["pending"]:
            title, icon, col = f"{st['pending']} foto(s) en espera", "cloud-clock-outline", theme.WARN
        else:
            title, icon, col = "Todo respaldado", "cloud-check-outline", theme.LEAF
        self.ids.drive_title.text = title
        self.ids.drive_icon.icon = icon
        self.ids.drive_icon.text_color = c(col)
        parts = []
        if on:
            parts.append(f"{st['done']} de {total} fotos en Drive" if total else "Aún no hay fotos en la cola")
            if st["errors"]:
                parts.append(f"{st['errors']} con error")
            if st["last_sync"]:
                parts.append("última sincronización " + st["last_sync"][5:16].replace("T", " "))
        if st["message"] and (on or not st["available"]):
            parts.append(st["message"])
        if on and st.get("account"):
            parts.insert(0, st["account"])
        self.ids.drive_text.text = " · ".join(parts)
        self.ids.drive_bar.value = 100 * st["done"] / total if on and total else 0
        self.ids.drive_bar_box.opacity = 1 if on and total else 0
        self.ids.drive_connect.text = ("Cambiar de cuenta" if on else "Conectar Google Drive")
        # Referencia FUERTE: al quitar el bloque del árbol, `ids` (referencia débil) lo
        # perdería y el recolector lo borraría → ReferenceError al volver a «General».
        if not hasattr(self, "_drive_slot"):
            opts = self.ids.drive_opts.__self__   # objeto real, no el proxy débil de `ids`
            self._drive_opts = opts
            self._drive_slot = (opts.parent, opts.parent.children.index(opts))
        opts = self._drive_opts
        parent, index = self._drive_slot
        if on and opts.parent is None:
            parent.add_widget(opts, index=index)
        elif not on and opts.parent is not None:
            parent.remove_widget(opts)
        self._loading = True
        self.ids.drive_wifi.active = st["wifi_only"]
        self._loading = False

    def drive_connect(self):
        a = app()
        if not a.drive.available:
            a.toast("Esta copia de la app no trae la credencial de Google (use la versión instalada).")
            return
        a.toast("Elija la cuenta de Google y acepte el permiso" if IS_ANDROID else
                "Se abrirá el navegador: elija su cuenta de Google y acepte el permiso")

        def done(ok, msg):
            Clock.schedule_once(lambda *_: (a.toast(msg), self.refresh_drive()))

        a.drive.connect(done)

    def drive_diagnostics(self):
        from platform_utils import app_version
        lines = app().drive.diagnostics()
        from android_bridge import package_name
        head = f"PhenoRubus {app_version()} · paquete {package_name()}"
        text_dialog("Diagnóstico de Google Drive",
                    [head] + (lines or ["Sin registros: toque «Conectar Google Drive» y vuelva aquí."]),
                    highlight="✗")

    def show_errors(self):
        import crashguard
        from platform_utils import app_version
        lines = crashguard.entries()
        extra = [("Borrar registro", lambda: (crashguard.clear(), app().toast("Registro borrado")))] \
            if lines else []
        text_dialog("Registro de errores",
                    [f"PhenoRubus {app_version()}"] + (lines or ["Sin errores registrados."]),
                    highlight="Error", actions=extra, small=True)

    def drive_disconnect(self):
        confirm("Desconectar Google Drive",
                "Las fotos dejarán de subirse y se quita el permiso de la app en esa cuenta. Lo que ya "
                "está en Drive y en el teléfono se conserva. Para usar otra cuenta, toque después "
                "«Conectar Google Drive» y elíjala de la lista.",
                [("Desconectar", lambda: (app().drive.disconnect(), self.refresh_drive()))])

    def drive_wifi(self, active: bool):
        if not self._loading:
            app().db.set_setting("drive_wifi_only", bool(active))
            if not active:
                app().drive.flush_async()

    def drive_sync(self):
        a = app()
        a.drive.retry_errors()
        a.toast("Sincronizando con Google Drive…")
        a.run_sync(manual=True)

    def refresh_sync(self):
        last = app().workspaces.shared.get_setting("sync_last")
        self.ids.sync_text.text = (f"Última sincronización (celular, PC y web): {last}" if last else
                                   "Los registros y fotos se comparten con el PC, la web y otros "
                                   "teléfonos con esta misma cuenta de Google (al abrir y cada 10 "
                                   "minutos; también desde el ícono de Drive del inicio).")

    def drive_existing(self):
        a = app()

        def work():
            n = a.drive.enqueue_existing()
            Clock.schedule_once(lambda *_: (a.toast(f"{n} foto(s) añadidas a la cola de respaldo"
                                                    if n else "No hay fotos anteriores pendientes"),
                                            self.refresh_drive()))

        a.workers.submit(work)

    def _save(self, **changes):
        a = app()
        cfg = a.reminders.config()
        for k, v in changes.items():
            setattr(cfg, k, v)
        a.reminders.save(cfg)
        self.refresh()

    def on_toggle(self, active: bool):
        if not self._loading:
            self._save(enabled=active)

    def pick_day(self, caller):
        open_menu(caller, [(d.capitalize(), lambda i=i: self._save(weekday=i))
                           for i, d in enumerate(ph.DIAS)])

    def pick_freq(self, caller):
        open_menu(caller, [(t, lambda k=k: self._save(every_weeks=k)) for k, t in FREQUENCIES.items()])

    def pick_time(self):
        cfg = app().reminders.config()
        from kivymd.uix.pickers import MDTimePicker  # import diferido (pesado)
        picker = MDTimePicker(primary_color=c(theme.LEAF), accent_color=c(theme.GLASS),
                              text_button_color=c(theme.LEAF_DARK))
        picker.set_time(_dt.time(cfg.hour, cfg.minute))
        picker.bind(on_save=lambda inst, t: self._save(hour=t.hour, minute=t.minute))
        picker.open()

    @staticmethod
    def _first_week_text(a) -> str:
        fixed = a.db.first_week_date(a.season)
        if fixed:
            return f"Primera semana de muestreo: {ph.format_date_es(fixed)} (fijada)"
        n = a.db.first_week_with_data(a.season)
        if n is None:
            return "Primera semana de muestreo: automática (aún sin datos)"
        start = ph.week_start(a.db.season_start(a.season), n)
        return f"Primera semana de muestreo: automática ({ph.week_title(start.isoformat())})"

    def pick_start(self):
        """Fija desde qué semana parten matriz e informes (no cambia ningún registro)."""
        a = app()
        start = a.db.first_week_date(a.season) or _dt.date.fromisoformat(a.week["start_date"])
        from kivymd.uix.pickers import MDDatePicker  # import diferido (pesado)
        picker = MDDatePicker(year=start.year, month=start.month, day=start.day,
                              primary_color=c(theme.LEAF), selector_color=c(theme.LEAF),
                              text_button_color=c(theme.LEAF_DARK))
        picker.bind(on_save=lambda inst, value, _range: self._set_first_week(value))
        picker.open()

    def reset_start(self):
        a = app()
        a.db.set_first_week(a.season, None)
        self.refresh()
        a.toast("Primera semana de muestreo: automática (la primera con datos)")

    def _set_first_week(self, value: _dt.date):
        a = app()
        season = ph.season_of(value)
        if season != a.season:
            a.toast(f"Esa fecha es de la {ph.season_title(season)}; elija una de la "
                    f"{ph.season_title(a.season)}.")
            return
        week = a.db.week_for_date(value, season)
        a.db.set_first_week(season, _dt.date.fromisoformat(week["start_date"]))
        self.refresh()
        a.toast(f"Matriz e informes parten en la {ph.week_title(week)}")

    def show_audit(self):
        rows = [(f"{r['action']} · {r['entity']}" + (f" #{r['entity_id']}" if r["entity_id"] else ""),
                 f"{r['ts'].replace('T', ' ')} · {r['detail'][:80]}")
                for r in app().db.audit_trail(60)]
        list_dialog("Bitácora de cambios", rows)

    # ---------------------------------------------- copias de seguridad
    def _busy(self, text):
        self.ids.backup_text.text = text

    def optimize_photos(self):
        """Aligera las fotos antiguas (mismo archivo y ruta) en segundo plano."""
        if getattr(self, "_optimizing", False):
            app().toast("Ya se están optimizando las fotos…")
            return
        a = app()
        import photo_optimizer as po
        dbs = a.all_dbs() + ([a.db.shared] if getattr(a.db, "shared", None) is not None else [])
        self.ids.photo_text.text = "Revisando fotos…"

        def show(text):
            Clock.schedule_once(lambda *_: setattr(self.ids.photo_text, "text", text))

        def run(found):
            self._optimizing = True

            def progress(i, n, saved):
                if i == n or i % 5 == 0:
                    show(f"Optimizando fotos: {i} de {n} · {saved / 1e6:.1f} MB liberados")

            def work():
                try:
                    res = po.optimize(found["paths"], progress)
                    msg = (f"Listo: {res['optimized']} fotos optimizadas, "
                           f"{res['saved'] / 1e6:.1f} MB liberados.")
                except Exception as exc:  # noqa: BLE001
                    msg = f"No se pudieron optimizar las fotos: {exc}"
                self._optimizing = False
                show(msg)
                Clock.schedule_once(lambda *_: a.toast(msg))
            a.workers.submit(work)

        def ask(found):
            n, mb = len(found["paths"]), found["bytes"] / 1e6
            if not n:
                self.ids.photo_text.text = (f"Las {found['total']} fotos del teléfono ya están "
                                            "livianas: no hay nada que optimizar.")
                return
            self.ids.photo_text.text = f"{n} fotos pesadas ({mb:.0f} MB)."
            confirm("Optimizar fotos guardadas",
                    f"Hay {n} fotos pesadas ({mb:.0f} MB). Se reducirán a 1600 px y JPEG liviano "
                    f"(quedan en ≈{n * .3:.0f} MB), en el mismo archivo: registros, informes e IA "
                    "siguen igual. Las copias en Drive no se modifican. ¿Continuar?",
                    [("Optimizar", lambda: run(found))])

        def scan():
            found = po.scan(dbs)
            Clock.schedule_once(lambda *_: ask(found))
        a.workers.submit(scan)

    def full_backup(self):
        a = app()
        self._busy("Creando copia de seguridad…")

        def work():
            try:
                from data_transfer import full_backup
                path = full_backup(a.db, workspaces=a.workspaces, open_db=a.open_db)
                a.media.save_public(path, "application/zip")   # una sola copia en Descargas
                if a.db.get_setting("drive_enabled", False):
                    a.drive.enqueue(None, path, remote=f"Respaldos/{os.path.basename(path)}")
                size = os.path.getsize(path) / 1e6
                msg = (f"Copia guardada en Descargas › PhenoRubus: {os.path.basename(path)} "
                       f"({size:.1f} MB)" + (" · también se sube a Drive" if a.db.get_setting(
                           "drive_enabled", False) else ""))
                Clock.schedule_once(lambda *_: (self._busy(msg), a.toast("Copia de seguridad lista"),
                                                self._offer_share(path)))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: (self._busy(f"No se pudo crear la copia: {error}"),))

        a.workers.submit(work)

    def _offer_share(self, path):
        confirm("Copia de seguridad lista",
                "Quedó en Descargas › PhenoRubus. ¿Quiere además enviarla (Drive, correo, WhatsApp…)?",
                [("Compartir", lambda: app().share_file(path, "application/zip"))])

    def restore_backup(self):
        a = app()

        def picked(path, name):
            if not path:
                return
            if not path.lower().endswith((".zip", ".sqlite3", ".db")):
                a.toast("Elija la copia .zip o el archivo .sqlite3")
                return
            from ai_share import is_knowledge_package
            if is_knowledge_package(path):
                a.toast("Ese es un paquete de la IA: impórtelo en el módulo de IA › Modelo")
                return
            confirm("Restaurar copia de seguridad",
                    f"Se reemplazarán los datos actuales por los de «{name or os.path.basename(path)}». "
                    "Antes se guarda automáticamente una copia de lo actual.",
                    [("Restaurar", lambda: self._do_restore(path))])

        a.media.pick_document(picked, exts=(".zip", ".sqlite3", ".db"))

    def _do_restore(self, path):
        a = app()
        self._busy("Restaurando… no cierre la app.")

        def progress(i, n):
            if i % 10 == 0:
                Clock.schedule_once(lambda *_: self._busy(f"Recuperando fotos… {i}/{n}"))

        def work():
            try:
                from data_transfer import restore
                res = restore(a.db, path, progress=progress, workspaces=a.workspaces,
                              open_db=a.open_db)
                Clock.schedule_once(lambda *_: self._restored(res, None))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: self._restored(None, error))

        request_runtime_permissions(lambda _ok: a.workers.submit(work))

    def _restored(self, res, error):
        a = app()
        if error:
            self._busy(f"No se pudo restaurar: {error}")
            return
        a.reload_data()
        self.refresh()
        self._busy("Restaurado: " + res.summary())
        text = res.summary()
        if res.missing:
            text += ("\n\nFotos sin archivo (puede recuperarlas con «Importar informes semanales» "
                     "o volver a adjuntarlas desde la galería):\n• " + "\n• ".join(res.missing[:12]))
            if len(res.missing) > 12:
                text += f"\n… y {len(res.missing) - 12} más"
        confirm("Datos restaurados", text, [])

    def import_reports(self):
        a = app()

        def picked(path, name):
            if not path:
                return
            if not path.lower().endswith((".pdf", ".html", ".htm", ".zip")):
                a.toast("Elija un informe semanal (PDF, o .html/.zip de versiones anteriores)")
                return
            self._busy(f"Leyendo {name or os.path.basename(path)}…")

            def work():
                try:
                    from data_transfer import import_reports
                    res = import_reports(a.db, [path])
                    Clock.schedule_once(lambda *_: self._reports_done(res, None))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: self._reports_done(None, error))

            a.workers.submit(work)

        a.media.pick_document(picked, exts=(".pdf", ".html", ".htm", ".zip"))

    def _reports_done(self, res, error):
        a = app()
        if error:
            self._busy(f"No se pudo importar: {error}")
            return
        a.reload_data()
        self.refresh()
        self._busy("Importado: " + res.summary() + (" · " + "; ".join(res.skipped[:3]) if res.skipped else ""))
        a.toast("Informe importado" if res.reports else "El archivo no es un informe semanal")


# ===========================================================================
# Calibración IA (protegida por PIN)
# ===========================================================================
class PinForm(MDBoxLayout):
    """Campo de PIN que se escribe ahí mismo (sin el cuadro de texto nativo encima: así
    es un solo diálogo) con el teclado numérico, que se abre solo."""

    def on_kv_post(self, *_):
        pin = self.ids.pin
        pin.native_edit = False
        pin.input_type = "number"
        Clock.schedule_once(lambda *_: setattr(pin, "focus", self.autofocus), .35)

    autofocus = True


class MindSeg(PillButton):
    pass


class MindTopBar(MDTopAppBar):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(lambda *_: setattr(self, "specific_text_color", c(theme.MIND_TEXT)))


class MindRow(GlassButton):
    title = StringProperty()
    subtitle = StringProperty()
    value = StringProperty()


class MindOption(GlassButton):
    title = StringProperty()
    subtitle = StringProperty()
    code = NumericProperty(0)
    result = StringProperty("")   # "", "ok", "bad"
    locked = BooleanProperty(False)  # ya respondida (sin atenuar el texto como «disabled»)


def _mind(cls_name: str, **kw):
    from kivy.factory import Factory
    return getattr(Factory, cls_name)(**kw)


class AILabScreen(MDScreen):
    """«Mente del sistema»: desafío diario, etiquetado, modelo y datos históricos."""

    def on_pre_enter(self, *_):
        self.refresh()

    def on_enter(self, *_):
        self.ids.sky.start()       # fondo vivo: destellos y píxeles

    def on_leave(self, *_):
        self.ids.sky.stop()

    def show(self, name: str):
        self.ids.seg.current = name
        self.refresh()

    def open_iaplus(self):
        """IA+: cajas para el detector, en su propia pantalla (ui/boxes.py)."""
        from ui import boxes
        boxes.open_screen()

    def refresh(self):
        getattr(self, f"refresh_{self.ids.seg.current}")()

    # ======================================================= desafío diario
    @property
    def game(self):
        a = app()
        if getattr(self, "_game", None) is None or self._game.db is not a.db:   # cambió de ensayo
            from ai_game import DailyChallenge
            self._game = DailyChallenge(a.db, lambda: a.classifier, a.all_dbs)
        return self._game

    _mode = None          # modo en juego («identify» / «capture»); None = sala de juego
    _pick = "identify"    # modo elegido en la sala

    def refresh_challenge(self):
        if self._mode is None:
            self._render_lobby()
            return
        box = self.ids.task_box
        fast_clear(box)
        box.add_widget(self._mind_note("Cargando el siguiente desafío…"))
        mode, endless = self._mode, self._endless

        def work():
            try:
                # Sin fin: siempre hay otro; si no, solo los desafíos del día de ese modo.
                ch = self.game.next_challenge(mode, create=endless)
                Clock.schedule_once(lambda *_: self._render_challenge(ch))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: (app().toast(f"No se pudo preparar: {error}"),
                                                self._exit_game()))

        app().workers.submit(work)

    # ---- sala de juego: «¿Aceptas el desafío?»
    MODE_TEXT = {"identify": "Ponle nombre (estado BBCH) a fotos que ya están en la app. Si la foto "
                             "ya tenía estado es un quiz; si no, tu respuesta la etiqueta.",
                 "capture": "La IA te pide un estado y tú le muestras una foto (cámara o galería). "
                            "Dice qué vio y aprende con tu ejemplo.",
                 }
    _run = 0              # desafíos respondidos en esta partida
    _endless = False      # casilla «Modo sin fin» (vale para nombrar o para subir fotos)

    def _render_lobby(self):
        from ui import arcade
        self._update_header()
        box = self.ids.task_box
        fast_clear(box)
        card = _mind("MindCard")
        arena = arcade.PixelArena(size_hint_y=None, height=dp(330))
        arena.add_widget(arcade.PixelText(text="¿ACEPTAS\nEL DESAFÍO?", px=dp(4),
                                          pos_hint={"center_x": .5, "top": .95}))
        orb = arcade.PixelOrb(size_hint=(None, None), size=(dp(156), dp(156)),
                              pos_hint={"center_x": .5, "center_y": .36})
        orb.bind(on_release=lambda *_: self._start_game())
        arena.add_widget(orb)
        arena.add_widget(arcade.PixelText(text="GO", px=dp(7), color=c(theme.MIND_ACCENT),
                                          pos_hint={"center_x": .5, "center_y": .36}))
        arena.orb = orb
        card.add_widget(arena)
        card.add_widget(_mind("MindSection", text="ELIGE TU DESAFÍO"))
        row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
        self._mode_btns = {}
        for kind, label in (("identify", "Nombrar fotos"), ("capture", "Subir fotos")):
            b = _mind("MindSeg", text=label, selected=kind == self._pick)
            b.bind(on_release=lambda w, k=kind: self._choose_mode(k))
            self._mode_btns[kind] = b
            row.add_widget(b)
        card.add_widget(row)
        from ui.arcade import AuraCheck
        endless = MDBoxLayout(adaptive_height=True, spacing=dp(10), padding=(dp(4), dp(2)))
        chk = AuraCheck(active=self._endless, pos_hint={"center_y": .5})
        chk.bind(active=lambda w, v: (setattr(self, "_endless", v), self._choose_mode(self._pick)))
        endless.add_widget(chk)
        lbl = MDBoxLayout(orientation="vertical", adaptive_height=True, pos_hint={"center_y": .5})
        lbl.add_widget(_mind("MindText", text="Modo sin fin", bold=True))
        lbl.add_widget(_mind("MindMuted", text="Un desafío tras otro, sin parar · cada 5 seguidos, ronda completada"))
        endless.add_widget(lbl)
        card.add_widget(endless)
        self._mode_desc = _mind("MindMuted", text="")
        card.add_widget(self._mode_desc)
        start = _mind("MindButton", text="COMENZAR")
        start.bind(on_release=lambda *_: self._start_game())
        card.add_widget(start)
        box.add_widget(card)
        self._choose_mode(self._pick)
        arena.start()

    def _choose_mode(self, kind):
        self._pick = kind
        for k, b in getattr(self, "_mode_btns", {}).items():
            b.selected = k == kind
        extra = ""
        if kind == "identify":
            n = self.game.available("identify")
            extra = f"  ·  {n} foto(s) por nombrar" if n else "  ·  no quedan fotos por nombrar"
        if not self._endless:
            extra += "  ·  solo los desafíos de hoy"
        self._mode_desc.text = self.MODE_TEXT[kind] + extra

    def _start_game(self):
        if self._pick == "identify" and not self.game.available("identify"):
            app().toast("No quedan fotos por nombrar: registra fotos en el muestreo o elige «Subir fotos».")
            return
        from ui import arcade

        def go():
            self._mode, self._run = self._pick, 0
            self.refresh_challenge()

        arcade.countdown(go)

    def _exit_game(self):
        self._mode = None
        self.refresh_challenge()

    def _exit_button(self):
        b = MDFlatButton(text="SALIR AL MENÚ DEL DESAFÍO", theme_text_color="Custom",
                         text_color=c(theme.MIND_MUTED), pos_hint={"center_x": .5})
        b.bind(on_release=lambda *_: self._exit_game())
        return b

    def _update_header(self):
        st = self.game.stats()
        done, total = self.game.progress()
        self.ids.ch_ring.value = done / total if total else 0
        self.ids.ch_ring_text.text = f"{done}/{total or 5}"
        today = _dt.date.today().isoformat()
        self.ids.ch_title.text = ("¡Desafío completado!" if st.get("last_day") == today
                                  else "Desafíos cerrados" if total and done == total
                                  else "Entrena a la IA")
        self.ids.streak_text.text = f"{st['streak']} día" + ("s" if st["streak"] != 1 else "")
        acc = f" · {st['accuracy']:.0%} aciertos" if st["accuracy"] is not None else ""
        self.ids.xp_text.text = f"Nivel {st['level']} · {st['xp']} XP{acc}"
        self.ids.level_bar.value = st["level_progress"]

    def _mind_note(self, text):
        card = _mind("MindCard")
        card.add_widget(_mind("MindText", text=text))
        return card

    def _render_challenge(self, ch=None):
        self._update_header()
        box = self.ids.task_box
        fast_clear(box)
        if ch is None:   # sin desafíos de hoy en este modo (o sin fotos para nombrar)
            card = _mind("MindCard")
            card.add_widget(_mind("MindSection", text="¡NIVEL DESPEJADO!"))
            no_photos = self._mode == "identify" and not self.game.available("identify")
            card.add_widget(MDLabel(text="Ya nombraste todas las fotos disponibles." if no_photos
                                    else "Completaste los desafíos de hoy de este modo.",
                                    font_style="H6", bold=True, adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(theme.MIND_TEXT)))
            card.add_widget(_mind("MindMuted", text=(
                "Registra fotos nuevas en el muestreo o cambia a «Subir fotos» para seguir."
                if no_photos else "Activa «Modo sin fin» para seguir jugando, o vuelve mañana.")))
            card.add_widget(self._exit_button())
            box.add_widget(card)
            return
        card = self._identify_card(ch) if ch["kind"] == "identify" else self._capture_card(ch)
        if self._endless:
            card.add_widget(_mind("MindSection", text=f"MODO SIN FIN · {self._run} SEGUIDOS"), index=len(card.children))
        card.add_widget(self._exit_button())
        box.add_widget(card)

    # ---- «¿Qué estado es?»
    def _identify_card(self, ch):
        p = ch["payload"]
        names = app().db.bbch_names()
        card = _mind("MindCard")
        card.add_widget(_mind("MindSection", text="¿QUÉ ESTADO ES?"))
        card.add_widget(_mind("MindMuted", text=f"{p['variety']} · {p['week']}"
                                                + ("" if p.get("truth") is not None
                                                   else " · foto sin estado: tu respuesta la etiqueta")))
        img = MDBoxLayout(size_hint_y=None, height=dp(230))
        img.add_widget(thumb_widget(p["path"], 640))
        card.add_widget(img)
        grid = MDGridLayout(cols=2, spacing=dp(8), adaptive_height=True)
        opts = []
        for code in p["options"]:
            o = MindOption(title=f"BBCH {ph.code_str(code)}", subtitle=names.get(code, ""), code=code)
            o.bind(on_release=lambda w, ch=ch: self._answer(ch, w, opts))
            opts.append(o)
            grid.add_widget(o)
        card.add_widget(grid)
        self._skip = self._skip_button(ch)
        card.add_widget(self._skip)
        return card

    def _answer(self, ch, option, opts):
        if option.locked:
            return
        for o in opts:
            o.locked = True
        if getattr(self, "_skip", None) is not None and self._skip.parent:
            self._skip.parent.remove_widget(self._skip)
        res = self.game.answer_identify(ch["id"], option.code)
        truth = res["truth"]
        for o in opts:
            if truth is not None and o.code == truth:
                o.result = "ok"
            elif o is option:
                o.result = "ok" if res["correct"] in (True, None) else "bad"
            if not o.result:
                o.opacity = .45
        if res["correct"] is not False:   # acierto o etiqueta nueva: explosión de píxeles
            from ui import arcade
            arcade.burst(*option.to_window(*option.center))
        if res["correct"] is None:
            msg = f"Etiquetada como BBCH {ph.code_str(option.code)}. +{res['xp']} XP"
        elif res["correct"]:
            msg = f"¡Correcto! +{res['xp']} XP"
        else:
            msg = f"Era BBCH {ph.code_str(truth)}. La IA lo aprende igual. +{res['xp']} XP"
        if res.get("ai") is not None:
            msg += f" · la IA había pensado BBCH {ph.code_str(res['ai'])}"
        self._feedback(msg, res)

    # ---- «Muéstrame este estado»
    def _capture_card(self, ch):
        a = app()
        code = ch["payload"]["target"]
        row = next((r for r in a.db.list_bbch() if r["code"] == code), None)
        card = _mind("MindCard")
        card.add_widget(_mind("MindSection", text="MUÉSTRAME ESTE ESTADO"))
        card.add_widget(MDLabel(text=f"BBCH {ph.code_str(code)}", font_style="H4", bold=True, adaptive_height=True,
                                theme_text_color="Custom", text_color=c(theme.MIND_ACCENT)))
        card.add_widget(MDLabel(text=row["label"] if row else "", font_style="H6", adaptive_height=True,
                                theme_text_color="Custom", text_color=c(theme.MIND_TEXT)))
        if row and row["description"]:
            card.add_widget(_mind("MindMuted", text=row["description"]))
        card.add_widget(_mind("MindMuted", text=ph.MACRO_STAGES.get(ph.macro_of(code), "")))
        cam = _mind("MindButton", text="Tomar foto")
        cam.bind(on_release=lambda *_: self._capture(ch, "camera"))
        gal = _mind("MindGhost", icon="image-outline", text="Elegir de la galería")
        gal.bind(on_release=lambda *_: self._capture(ch, "gallery"))
        card.add_widget(cam)
        card.add_widget(gal)
        card.add_widget(self._skip_button(ch))
        return card

    def _capture(self, ch, source):
        a = app()

        def done(result, _origin):
            path = result[0] if isinstance(result, list) else result
            if not path:
                return
            fast_clear(self.ids.task_box)
            self.ids.task_box.add_widget(self._mind_note("La IA está mirando la foto…"))

            def work():
                try:
                    stored = store_photo(path, data_subdir("training"), f"desafio_bbch{ph.code_str(ch['payload']['target'])}")
                    res = self.game.complete_capture(ch["id"], stored)
                    res["path"] = stored
                    Clock.schedule_once(lambda *_: self._capture_done(res))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: (a.toast(f"No se pudo procesar: {error}"),
                                                    self.refresh_challenge()))

            a.workers.submit(work)

        if source == "camera":
            a.media.take_photo(done, f"entrenamiento_BBCH{ph.code_str(ch['payload']['target'])}")
        else:
            a.media.pick_image(done)

    def _capture_done(self, res):
        fast_clear(self.ids.task_box)
        card = _mind("MindCard")
        img = MDBoxLayout(size_hint_y=None, height=dp(200))
        img.add_widget(thumb_widget(res["path"], 640))
        card.add_widget(img)
        from kivy.core.window import Window
        from ui import arcade
        arcade.burst(Window.width / 2, Window.height / 2)
        seen = f"La IA vio BBCH {ph.code_str(res['ai'])}"
        verdict = " — ¡coincide con el estadio!" if res["agree"] else " — ahora aprende tu ejemplo"
        self.ids.task_box.add_widget(card)
        self._feedback(f"{seen}{verdict}. +{res['xp']} XP", res, container=card)

    # ---- comunes
    def _skip_button(self, ch):
        b = MDFlatButton(text="SALTAR", theme_text_color="Custom", text_color=c(theme.MIND_MUTED),
                         pos_hint={"center_x": .5})
        b.bind(on_release=lambda *_: (self.game.skip(ch["id"]), self.refresh_challenge()))
        return b

    def _celebrate(self, res):
        """Serpentinas de píxeles: desafío del día completado o ronda del modo sin fin."""
        from ui import arcade
        self._run += 1
        if res.get("day_done"):
            arcade.party("DESAFIO\nCOMPLETADO",
                         f"Racha: {res['stats']['streak']} día(s) · {res['stats']['xp']} XP")
        elif self._endless and self._run % 5 == 0:
            arcade.party(f"RONDA {self._run // 5}\nCOMPLETADA", f"{self._run} desafíos seguidos · ¡sigue!")

    def _feedback(self, msg, res, container=None):
        self._celebrate(res)
        self._update_header()
        card = container or _mind("MindCard")
        card.add_widget(MDLabel(text=msg, font_style="Subtitle1", bold=True, adaptive_height=True,
                                theme_text_color="Custom",
                                text_color=c(theme.MIND_BAD if res.get("correct") is False else theme.MIND_OK)))
        if res.get("day_done"):
            card.add_widget(_mind("MindMuted", text=f"¡Desafío del día completado! Racha: "
                                                    f"{res['stats']['streak']} día(s)."))
        nxt = _mind("MindButton", text="Siguiente")
        nxt.bind(on_release=lambda *_: self.refresh_challenge())
        card.add_widget(nxt)
        if container is None:
            self.ids.task_box.add_widget(card)

    # ============================================================ etiquetado
    def set_auto_learn(self, active: bool):
        app().db.set_setting("ai_auto_learn", bool(active))

    def add_all_labeled(self):
        a = app()
        from ai_game import detail_photos
        todo = [p for p in detail_photos(a.all_dbs()) if p["bbch_code"] is not None
                and not p["in_reference"] and os.path.exists(p["path"])]
        if not todo:
            a.toast("No hay fotos etiquetadas pendientes.")
            return

        def work():
            for p in todo:
                a.classifier.add_reference(p["path"], p["bbch_code"], photo_id=p["id"], db=p["db"])
            Clock.schedule_once(lambda *_: (a.toast(f"{len(todo)} referencias agregadas"),
                                            self.refresh_model()))

        a.workers.submit(work)
        a.toast(f"Procesando {len(todo)} fotos…")

    # ================================================================ modelo
    def refresh_model(self):
        a = app()
        ext = a.classifier.extractor
        counts = a.db.reference_counts()
        self.ids.model_text.text = (f"{ext.name} · {ext.dim} dimensiones · k-NN coseno "
                                    f"(k={a.classifier.K}) + priors · {sum(counts.values())} referencias")
        box = self.ids.counts
        fast_clear(box)
        names = a.db.bbch_names()
        for code in sorted(counts):
            box.add_widget(MindRow(title=f"BBCH {ph.code_str(code)}", subtitle=names.get(code, ""),
                                   value=str(counts[code])))
        if not counts:
            box.add_widget(_mind("MindMuted", text="Sin referencias: la IA usa solo los priors agronómicos."))
        self.ids.auto_learn.active = bool(a.db.get_setting("ai_auto_learn", True))
        self.refresh_data()      # «Modelo y datos»: documentos y temporadas anteriores

    def refresh_extra(self):
        """Fotos extra para IA+ (carpeta «IA+ Conocimiento ampliado»): ui/extra.py."""
        from ui import extra
        extra.build(self)

    def evaluate(self):
        ev = app().classifier.evaluate()
        if ev["exact"] is None:
            self.ids.eval_text.text = "Se necesitan al menos 3 referencias para evaluar."
        else:
            app().db.set_setting("ai_last_eval", ev)
            self.ids.eval_text.text = (f"Validación leave-one-out (n={ev['n']}): código exacto "
                                       f"{ev['exact']:.0%} · estadio principal {ev['macro']:.0%}")

    def retrain(self):
        a = app()

        def progress(i, n):
            Clock.schedule_once(lambda *_: setattr(self.ids.train_progress, "value", i / max(1, n)))

        def work():
            n = a.classifier.rebuild(progress)
            Clock.schedule_once(lambda *_: (a.toast(f"{n} embeddings recalculados"),
                                            self.refresh_model()))

        a.workers.submit(work)

    def try_photo(self):
        a = app()

        def picked(path, _origin):
            if not path:
                return
            self.ids.spinner.active = True
            self.ids.try_label.text = "Analizando…"
            week = a.week["week_number"]

            def work():
                try:
                    preview = a.thumb(path, 640)
                    s = a.classifier.suggest(path, week_number=week)
                    Clock.schedule_once(lambda *_: self._show(preview, s, None))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: self._show(None, None, error))

            a.workers.submit(work)

        a.media.pick_image(picked)

    def _show(self, preview, s, error):
        self.ids.spinner.active = False
        if error:
            self.ids.try_label.text = "No se pudo analizar la imagen."
            self.ids.try_explain.text = str(error)
            return
        box = self.ids.try_box
        fast_clear(box)
        box.add_widget(FitImage(source=preview, radius=[dp(16)]))
        box.height, box.opacity = dp(190), 1
        self.ids.try_label.text = s.label
        self.ids.try_conf.value = s.confidence
        alts = " · ".join(f"BBCH {ph.code_str(code)} {p:.0%}" for code, p in s.top[1:])
        self.ids.try_explain.text = f"Confianza {s.confidence:.0%} · alternativas: {alts}\n{s.explanation}"

    # ------------------------------------------- compartir entre teléfonos
    def export_knowledge(self):
        a = app()
        if not a.db.reference_counts():
            a.toast("Todavía no hay fotos etiquetadas en la memoria de la IA.")
            return
        a.toast("Preparando paquete…")

        def work():
            try:
                from ai_share import export_knowledge
                path, n = export_knowledge(a.db)
                Clock.schedule_once(lambda *_: a.report_actions(
                    path, "Conocimiento de la IA", f"{n} referencias · ábralo en el otro teléfono "
                    "con «Importar conocimiento»", viewable=False))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: a.toast(f"No se pudo exportar: {error}"))

        a.workers.submit(work)

    def import_knowledge(self):
        a = app()

        def picked(path, name):
            if not path:
                return
            a.toast("Sumando conocimiento…")

            def work():
                try:
                    from ai_share import import_knowledge
                    res = import_knowledge(a.db, path, a.classifier)
                    Clock.schedule_once(lambda *_: (self.refresh_model(),
                                                    confirm("Conocimiento importado", res.summary(), [])))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: a.toast(f"No se pudo importar: {error}"))

            a.workers.submit(work)

        a.media.pick_document(picked, exts=(".zip",))

    def change_pin(self):
        a = app()
        form = PinForm()
        form.ids.pin.hint_text = "PIN actual"
        new = PinForm()
        new.ids.pin.hint_text = "Nuevo PIN (4-8 dígitos)"
        new.autofocus = False
        box = MDBoxLayout(orientation="vertical", adaptive_height=True)
        box.add_widget(form)
        box.add_widget(new)

        def ok(_):
            try:
                if not a.pin.change(form.ids.pin.text, new.ids.pin.text):
                    form.ids.msg.text = "PIN actual incorrecto."
                    return False
            except ValueError as exc:
                new.ids.msg.text = str(exc)
                return False
            a.toast("PIN actualizado")

        form_dialog("Cambiar PIN", box, ok)

    # ================================================================= datos
    def refresh_data(self):
        box = self.ids.docs
        fast_clear(box)
        for d in app().db.list_documents():
            row = MindRow(title=d["title"], subtitle=f"{d['created_at'][:10]} · {d['chars']} caracteres",
                          value=f"{d['stages_found']}")
            row.bind(on_release=lambda w, d=d: self._doc_menu(d))
            box.add_widget(row)
        last = app().db.get_setting("last_import")
        if last and not self.ids.import_text.text:
            self.ids.import_text.text = f"Última importación: {last}"

    def _doc_menu(self, doc):
        def delete():
            app().db.delete_document(doc["id"])
            self.refresh_data()
        confirm(doc["title"], "¿Quitar este documento de la base de conocimiento? "
                              "(la escala BBCH enriquecida se mantiene)", [("Eliminar", delete)])

    def import_document(self):
        a = app()

        def done(path, name):
            if not path:
                return
            try:
                _id, n = a.classifier.import_document(path, title=name or os.path.basename(path))
            except Exception as exc:  # noqa: BLE001
                a.toast(f"No se pudo leer el documento: {exc}")
                return
            a.toast(f"Documento cargado: {n} claves BBCH detectadas")
            self.refresh_data()

        a.media.pick_document(done)

    def show_scale(self):
        rows = [(f"BBCH {ph.code_str(r['code'])}: {r['label']}", f"[{r['source']}] {r['description']}")
                for r in app().db.list_bbch()]
        list_dialog("Escala BBCH · frambueso", rows)

    def save_template(self):
        from importer import write_template
        a = app()
        path = write_template(os.path.join(data_subdir("tmp"), "plantilla_historico_phenorubus.csv"))
        try:
            a.media.save_public(path, "text/csv")
            a.toast("Plantilla guardada en Descargas/PhenoRubus")
        except Exception as exc:  # noqa: BLE001
            a.toast(f"No se pudo guardar: {exc}")

    def import_history(self):
        a = app()

        def done(path, name):
            if not path:
                return
            if not path.lower().endswith((".csv", ".zip")):
                a.toast("Elija un archivo .csv o .zip")
                return
            train = self.ids.train_import.active
            self.ids.import_btn.disabled = True
            self.ids.import_text.text = f"Importando {name or os.path.basename(path)}…"

            def progress(i, n):
                Clock.schedule_once(lambda *_: setattr(self.ids.import_progress, "value", i / max(1, n)))

            def work():
                from importer import import_file
                try:
                    res = import_file(a.db, path, classifier=a.classifier if train else None,
                                      train_ai=train, progress=progress)
                    Clock.schedule_once(lambda *_: self._import_done(res, None))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: self._import_done(None, error))

            a.workers.submit(work)

        a.media.pick_document(done)

    def _import_done(self, res, error):
        self.ids.import_btn.disabled = False
        if error:
            self.ids.import_text.text = f"No se pudo importar: {error}"
            return
        summary = res.summary()
        app().db.set_setting("last_import", summary)
        errs = (f"\n{len(res.errors)} advertencia(s): " + "; ".join(res.errors[:3])) if res.errors else ""
        self.ids.import_text.text = f"Importado: {summary}{errs}"
        app().toast("Importación terminada")


# ===========================================================================
# Mediciones personalizadas (registro de imágenes o planilla de datos)
# ===========================================================================
class EntryRow(MDBoxLayout):
    title = StringProperty()
    subtitle = StringProperty()
    has_thumb = BooleanProperty(False)
    item = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


def _variety_label(variety_id, varieties, two_lines: bool = False) -> str:
    """Nombre de la variedad de un registro. Predio: «Meeker 2019 · E1-S1» (o en dos
    líneas para la celda angosta de la planilla)."""
    v = next((v for v in varieties if v["id"] == variety_id), None)
    if not v:
        return "General"
    if two_lines and ph.is_unit(v):
        main, _sep, where = ph.unit_compact(v).rpartition(" · ")
        return f"{main}\n{where}"
    return ph.unit_compact(v)


def _variety_choices(varieties, choose):
    """Filas de un selector de variedad: predio = variedad y año, con equipo y sector abajo."""
    return [(ph.unit_main(v), " · ".join(x for x in (ph.unit_place(v), v["code"] or "") if x),
             lambda v=v: choose(v["id"])) for v in varieties]


def open_measures_menu():
    """Lista de mediciones de la semana actual + crear nueva + exportar todas a Excel."""
    a = app()
    week = a.week
    items = [("+ Nueva medición", "Registro de imágenes o planilla de datos", new_measure_dialog)]
    measures = a.db.list_measures(week["id"])
    for m in measures:
        unit = ("foto(s)" if m["kind"] == "images" else "fila(s)")
        kind = "Imágenes" if m["kind"] == "images" else "Planilla"
        items.append((m["name"], f"{kind} · {m['n']} {unit} esta semana",
                      lambda m=m: a.open_measure(m["id"], week["id"]), None,
                      lambda m=m: delete_measure_dialog(m, week)))
    if measures:
        items.append(("Exportar todas a Excel", "Una hoja por medición · toda la temporada",
                      lambda: export_measures_xlsx([m["id"] for m in measures])))
    pick_dialog(f"Mediciones · {ph.week_title(week)}", items)


def delete_measure_dialog(m: dict, week: dict):
    """Basurero de la lista: borrar lo registrado ESTA semana o la medición completa."""
    a = app()
    total = len(a.db.list_entries(m["id"]))

    def done(msg):
        a.toast(msg)
        a.refresh_home()
        Clock.schedule_once(lambda *_: open_measures_menu(), .3)

    def this_week():
        n = a.db.delete_week_entries(m["id"], week["id"])
        done(f"«{m['name']}»: {n} registro(s) de esta semana eliminados")

    def everything():
        a.db.delete_measure(m["id"])
        done(f"Medición «{m['name']}» eliminada")

    actions = []
    if m["n"]:
        actions.append(("Esta semana", this_week))
    actions.append(("Eliminar todo", everything))
    text = (f"«{m['name']}» tiene {m['n']} registro(s) en {ph.week_title(week)} y {total} en "
            f"total.\n\n• Esta semana: borra solo lo de esta semana (la medición sigue "
            f"para las demás).\n• Eliminar todo: quita la medición de todas las semanas.\n\n"
            f"Las fotos quedan en el teléfono.")
    Clock.schedule_once(lambda *_: confirm(f"Eliminar «{m['name']}»", text, actions), .3)


def export_measures_xlsx(measure_ids: list[int]):
    a = app()
    a.toast("Generando planilla Excel…")

    def work():
        try:
            from measures_export import export_measures
            path = export_measures(a.db, measure_ids, a.season)
            Clock.schedule_once(lambda *_: a.report_actions(
                path, "Planilla Excel (.xlsx)", "Mediciones de toda la temporada", viewable=False))
        except Exception as exc:  # noqa: BLE001
            error = exc
            Clock.schedule_once(lambda *_: a.toast(f"No se pudo exportar: {error}"))

    a.workers.submit(work)


def _measure_form(measure: dict | None = None):
    """Formulario: nombre y tipo (planilla / imágenes). Las columnas se crean en la grilla."""
    from kivy.factory import Factory
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                      padding=(0, dp(8), 0, 0))
    box.name = Factory.Field(hint_text="Nombre de la medición")
    box.add_widget(box.name)
    box.kind = measure["kind"] if measure else "table"
    if measure:
        box.name.text = measure["name"]
        return box
    row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
    hint = MDLabel(font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                   text_color=c(theme.MUTED))
    buttons = {}

    def choose(kind):
        box.kind = kind
        for k, b in buttons.items():
            on = k == kind
            b.md_bg_color = c(theme.LEAF_DARK) if on else c("#FFFFFF", 0)
            b.text_color = c("#FFFFFF") if on else c(theme.LEAF_DARK)
        hint.text = ("Una planilla como Excel: agregue filas y columnas y nombre cada columna."
                     if kind == "table" else "Fotos con descripción y, si quiere, la variedad.")

    for kind, label in (("table", "Planilla de datos"), ("images", "Imágenes")):
        b = MDRectangleFlatButton(text=label, theme_text_color="Custom", line_color=c(theme.LEAF_DARK),
                                  on_release=lambda *_, k=kind: choose(k))
        buttons[kind] = b
        row.add_widget(b)
    box.add_widget(row)
    box.add_widget(hint)
    Clock.schedule_once(lambda *_: choose("table"))
    return box


def new_measure_dialog():
    a = app()

    def ok(form):
        try:
            mid = a.db.add_measure(form.name.text, form.kind)
        except ValueError as exc:
            a.toast(str(exc))
            return False
        a.open_measure(mid, a.week["id"])

    form_dialog("Nueva medición", _measure_form(), ok, "CREAR")


def _cell_button(text, width, bold=False, bg=None, fg=None, on_release=None):
    """Celda-botón de la grilla (encabezados, n.º de fila, variedad). Un texto en dos
    líneas va más chico y sin cortar."""
    from kivy.uix.button import Button
    two = "\n" in text
    b = Button(text=text, size_hint=(None, None), size=(width, dp(42)),
               font_size="11.5sp" if two else "13sp", line_height=.95 if two else 1,
               bold=bold, background_normal="", background_down="",
               background_color=bg or c(theme.LEAF_SOFT), color=fg or c(theme.INK),
               halign="center", valign="middle", shorten=not two, shorten_from="right")
    b.bind(size=lambda w, sz: setattr(w, "text_size", (sz[0] - dp(8), sz[1])))
    if on_release:
        b.bind(on_release=on_release)
    return b


class MeasureScreen(MDScreen):
    """Registros de UNA medición en UNA semana: fotos con descripción o filas de planilla."""

    def load(self, measure_id: int, week_id: int):
        a = app()
        self.measure = a.db.get_measure(measure_id)
        self.week = a.db.get_week(week_id)
        self.ids.bar.title = self.measure["name"]
        kind = "PLANILLA DE DATOS" if self.measure["kind"] == "table" else "REGISTRO DE IMÁGENES"
        self.ids.kicker.text = f"{kind} · {ph.week_title(self.week).upper()}"
        self.ids.columns_text.text = (
            "Toque una celda para escribir · toque un encabezado para renombrar o eliminar la "
            "columna · toque el n.º de fila para eliminarla." if self.measure["kind"] == "table"
            else "Cada foto con su descripción y, si quiere, la variedad.")
        actions = self.ids.actions
        fast_clear(actions)
        from kivy.factory import Factory
        if self.measure["kind"] == "table":
            actions.add_widget(Factory.GhostButton(icon="table-row-plus-after", text="Agregar fila",
                                                   on_release=lambda *_: self.add_row()))
            actions.add_widget(Factory.GhostButton(icon="table-column-plus-after", text="Agregar columna",
                                                   on_release=lambda *_: self.add_column()))
        else:
            actions.add_widget(Factory.GhostButton(icon="camera-outline", text="Tomar foto",
                                                   on_release=lambda *_: self.add_images("camera")))
            actions.add_widget(Factory.GhostButton(icon="image-multiple-outline", text="Desde galería",
                                                   on_release=lambda *_: self.add_images("gallery")))
        self.refresh()

    def refresh(self):
        a = app()
        box = self.ids.entries
        fast_clear(box)
        entries = a.db.list_entries(self.measure["id"], week_id=self.week["id"])
        unit = "fila(s)" if self.measure["kind"] == "table" else "foto(s)"
        self.ids.count_text.text = f"{len(entries)} {unit} esta semana"
        if self.measure["kind"] == "table":
            self._build_grid(entries)
            return
        varieties = a.db.list_varieties(include_archived=True)
        for e in entries:
            row = EntryRow(title=e["caption"] or "Sin descripción",
                           subtitle=_variety_label(e["variety_id"], varieties), item=e,
                           screen=self, has_thumb=True)
            row.ids.thumb_box.add_widget(thumb_widget(e["path"], 160))
            box.add_widget(row)
        if not entries:
            box.add_widget(MDLabel(text="Sin registros esta semana.", font_style="Caption",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))

    # ------------------------------------------------------ planilla (grilla)
    COL_W, NUM_W, VAR_W = dp(118), dp(40), dp(118)

    def _build_grid(self, entries):
        """Grilla editable: n.º | Variedad | columnas… · celdas = TextInput que se guardan
        al salir de ellas. Desplazamiento horizontal si hay muchas columnas."""
        from kivy.uix.gridlayout import GridLayout
        from kivy.uix.scrollview import ScrollView
        from kivy.uix.textinput import TextInput
        a = app()
        cols = list(self.measure["columns"])
        varieties = a.db.list_varieties(include_archived=True)
        self._rows = {e["id"]: dict(e["data"]) for e in entries}
        self._cells = []
        grid = GridLayout(cols=len(cols) + 2, size_hint=(None, None), spacing=dp(2), padding=dp(2))
        grid.bind(minimum_width=grid.setter("width"), minimum_height=grid.setter("height"))
        head_bg, head_fg = c(theme.LEAF_DARK), c("#FFFFFF")
        grid.add_widget(_cell_button("#", self.NUM_W, True, head_bg, head_fg))
        self.var_w = dp(150) if app().db.is_predio else self.VAR_W   # predio: variedad y año
        grid.add_widget(_cell_button("Variedad", self.var_w, True, head_bg, head_fg))
        for col in cols:
            grid.add_widget(_cell_button(col, self.COL_W, True, head_bg, head_fg,
                                         on_release=lambda *_, col=col: self.column_menu(col)))
        for i, e in enumerate(entries):
            grid.add_widget(_cell_button(str(i + 1), self.NUM_W, bg=c(theme.LEAF_SOFT),
                                         on_release=lambda *_, e=e, n=i + 1: self.row_menu(e, n)))
            grid.add_widget(_cell_button(_variety_label(e["variety_id"], varieties, two_lines=True)
                                         if e["variety_id"] else "—", self.var_w, bg=c("#FFFFFF"),
                                         fg=c(theme.LEAF_DARK),
                                         on_release=lambda *_, e=e: self.pick_row_variety(e)))
            row_cells = []
            for col in cols:
                ti = TextInput(text=str(e["data"].get(col, "")), multiline=False, write_tab=False,
                               size_hint=(None, None), size=(self.COL_W, dp(42)), font_size="14sp",
                               padding=(dp(8), dp(11)), background_normal="", background_active="",
                               background_color=c("#FFFFFF"), foreground_color=c(theme.INK),
                               cursor_color=c(theme.LEAF_DARK))
                ti.entry_id, ti.col = e["id"], col
                ti.native_edit = False   # planilla: se escribe de corrido con el teclado de la app
                ti.bind(focus=self._cell_focus)
                ti.bind(on_text_validate=self._cell_next)
                grid.add_widget(ti)
                row_cells.append(ti)
            self._cells.append(row_cells)
        sv = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint=(1, None),
                        bar_width=dp(4), scroll_type=["bars", "content"])
        grid.bind(height=lambda g, h: setattr(sv, "height", h + dp(8)))
        sv.add_widget(grid)
        self.ids.entries.add_widget(sv)
        if not entries:
            self.ids.entries.add_widget(MDLabel(
                text="Sin filas esta semana: toque «Agregar fila».", font_style="Caption",
                adaptive_height=True, theme_text_color="Custom", text_color=c(theme.MUTED)))

    def _cell_focus(self, ti, focused):
        if focused:
            return
        data = self._rows.get(ti.entry_id)
        if data is None:
            return
        value = ti.text.strip()
        if str(data.get(ti.col, "")) == value:
            return
        if value:
            data[ti.col] = value
        else:
            data.pop(ti.col, None)
        app().db.update_entry(ti.entry_id, data=data)

    def _cell_next(self, ti):
        """Enter: baja a la celda de la fila siguiente (misma columna)."""
        for r, row in enumerate(self._cells):
            if ti in row and r + 1 < len(self._cells):
                nxt = self._cells[r + 1][row.index(ti)]
                Clock.schedule_once(lambda *_: setattr(nxt, "focus", True), .05)
                return

    def commit_cells(self):
        """Guarda la celda en edición (al salir de la pantalla o antes de redibujar)."""
        for row in getattr(self, "_cells", []):
            for ti in row:
                if ti.focus:
                    ti.focus = False
                    self._cell_focus(ti, False)

    def on_pre_leave(self, *_):
        self.commit_cells()

    def save(self):
        """Disquete: guarda lo escrito (también se guarda solo al salir), avisa y vuelve."""
        self.commit_cells()
        from ui import celebrate
        app().back()
        celebrate.saved("Medición guardada")

    def add_row(self):
        self.commit_cells()
        a = app()
        a.db.add_entry(self.measure["id"], self.week["id"], None, data={})
        self.refresh()
        if self._cells:   # foco en la primera celda de la fila nueva
            Clock.schedule_once(lambda *_: setattr(self._cells[-1][0], "focus", True), .15)

    def add_column(self):
        self.commit_cells()
        a = app()
        from kivy.factory import Factory
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
        form.add_widget(Factory.Field(hint_text="Nombre de la columna (ej.: Largo (cm))"))

        def ok(f):
            try:
                a.db.add_measure_column(self.measure["id"], f.children[0].text)
            except ValueError as exc:
                a.toast(str(exc))
                return False
            self.measure = a.db.get_measure(self.measure["id"])
            self.refresh()

        form_dialog("Nueva columna", form, ok, "AGREGAR")

    def column_menu(self, col: str):
        self.commit_cells()
        a = app()
        mid = self.measure["id"]

        def rename():
            from kivy.factory import Factory
            form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
            form.add_widget(Factory.Field(hint_text="Nombre de la columna", text=col))

            def ok(f):
                try:
                    a.db.rename_measure_column(mid, col, f.children[0].text)
                except ValueError as exc:
                    a.toast(str(exc))
                    return False
                self.measure = a.db.get_measure(mid)
                self.refresh()

            form_dialog("Renombrar columna", form, ok)

        def remove():
            def go():
                try:
                    a.db.delete_measure_column(mid, col)
                except ValueError as exc:
                    a.toast(str(exc))
                    return
                self.measure = a.db.get_measure(mid)
                self.refresh()

            confirm("Eliminar columna", f"Se eliminará la columna «{col}» y sus datos en todas "
                    "las semanas.", [("Eliminar", go)])

        def move(step):
            cols = list(self.measure["columns"])
            i = cols.index(col)
            j = max(0, min(len(cols) - 1, i + step))
            cols[i], cols[j] = cols[j], cols[i]
            a.db.update_measure(mid, columns=cols)
            self.measure = a.db.get_measure(mid)
            self.refresh()

        pick_dialog(f"Columna «{col}»", [
            ("Renombrar", "Cambia el nombre (los datos se conservan)", rename),
            ("Mover a la izquierda", "Cambia el orden de las columnas", lambda: move(-1)),
            ("Mover a la derecha", "Cambia el orden de las columnas", lambda: move(1)),
            ("Eliminar columna", "Borra la columna y sus datos", remove),
        ])

    def row_menu(self, entry: dict, n: int):
        self.commit_cells()
        pick_dialog(f"Fila {n}", [
            ("Elegir variedad", "Asocia la fila a una variedad (sale en su informe)",
             lambda: self.pick_row_variety(entry)),
            ("Eliminar fila", "Borra los datos de esta fila", lambda: self.delete_entry(entry)),
        ])

    def pick_row_variety(self, entry: dict):
        self.commit_cells()
        a = app()

        def choose(vid):
            a.db.update_entry(entry["id"], variety_id=vid)
            self.refresh()

        pick_dialog("Variedad de la fila", [("— General", "Sin variedad específica", lambda: choose(None))]
                    + _variety_choices(a.db.list_varieties(), choose))

    # ----------------------------------------------------------- registros
    def entry_dialog(self, entry: dict):
        """Descripción y variedad (opcional) de una foto de la medición."""
        a = app()
        from kivy.factory import Factory
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6),
                           padding=(0, dp(22), 0, 0))
        state = {"variety_id": entry["variety_id"]}
        varieties = a.db.list_varieties()
        caption = Factory.Field(hint_text="Descripción", text=entry.get("caption") or "")
        vbtn = Factory.GhostButton(icon="fruit-cherries")

        def set_variety(vid):
            state["variety_id"] = vid
            vbtn.text = f"Variedad: {_variety_label(vid, varieties)}"

        vbtn.bind(on_release=lambda *_: pick_dialog(
            "Variedad", [("General", "Sin variedad específica", lambda: set_variety(None))]
            + _variety_choices(varieties, set_variety)))
        set_variety(state["variety_id"])
        form.add_widget(caption)
        form.add_widget(vbtn)

        def ok(_f):
            a.db.update_entry(entry["id"], caption=caption.text, variety_id=state["variety_id"])
            self.refresh()

        form_dialog("Foto", form, ok)

    def edit_entry(self, entry: dict):
        self.entry_dialog(entry)

    def delete_entry(self, entry: dict):
        def go():
            app().db.delete_entry(entry["id"])
            self.refresh()

        what = "esta fila" if self.measure["kind"] == "table" else "esta foto (el archivo queda en el teléfono)"
        confirm("Eliminar registro", f"¿Eliminar {what}?", [("Eliminar", go)])

    def add_images(self, source: str):
        a = app()
        measure, week = self.measure, self.week
        start = _dt.date.fromisoformat(week["start_date"][:10])
        from platform_utils import slugify
        code = f"{a.db.code}-" if a.db.code else ""
        base = f"{ph.photo_date(start)}-{code}{slugify(measure['name'])[:40] or 'medicion'}"

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            a.toast("Guardando foto…" if len(paths) == 1 else f"Guardando {len(paths)} fotos…")

            def work():
                ids, error = [], None
                try:
                    dest_dir = data_subdir("photos", f"T{week['season']}", "mediciones")
                    for tmp in paths:
                        path = store_photo(tmp, dest_dir, base, exact=True)
                        ids.append(a.db.add_entry(measure["id"], week["id"], path=path))
                        a.thumb(path, 160)
                        a.backup_extra(path, week["start_date"], measure["name"])
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: stored(ids, error))

            def stored(ids, error):
                if self.measure["id"] != measure["id"] or self.week["id"] != week["id"]:
                    return
                self.refresh()
                if error:
                    a.toast(f"No se pudo guardar la foto: {error}")
                elif len(ids) == 1:
                    e = next((x for x in a.db.list_entries(measure["id"], week_id=week["id"])
                              if x["id"] == ids[0]), None)
                    if e:
                        self.entry_dialog(e)

            a.workers.submit(work)

        if source == "camera":
            a.media.take_photo(done, base, exact=True)
        else:
            a.media.pick_images(done)

    # --------------------------------------------------------- definición
    def edit(self):
        self.commit_cells()
        a = app()
        m = self.measure
        form = _measure_form(m)
        from kivy.factory import Factory
        form.add_widget(Factory.GhostButton(
            icon="delete-outline", text="Eliminar medición",
            on_release=lambda *_: (dialog.dismiss(), self.delete_measure())))

        def ok(f):
            try:
                a.db.update_measure(m["id"], name=f.name.text)
            except ValueError as exc:
                a.toast(str(exc))
                return False
            self.load(m["id"], self.week["id"])

        dialog = form_dialog("Editar medición", form, ok)

    def delete_measure(self):
        a = app()
        n = len(a.db.list_entries(self.measure["id"]))

        def go():
            a.db.delete_measure(self.measure["id"])
            a.toast("Medición eliminada")
            a.back()

        confirm("Eliminar medición",
                f"Se eliminará «{self.measure['name']}» y sus {n} registro(s) de todas las semanas. "
                "Las fotos quedan en el teléfono.", [("Eliminar", go)])

    def export(self):
        self.commit_cells()
        export_measures_xlsx([self.measure["id"]])
