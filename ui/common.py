"""
ui/common.py
============
Base compartida de la interfaz: utilidades, widgets y diálogos comunes.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import os
from kivy.clock import Clock
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
from kivymd.uix.button import MDFlatButton, MDRectangleFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.toolbar import MDTopAppBar
import phenology as ph
from ui import theme
from ui.arcade import MindSky  # noqa: F401 - registra la clase para el KV
from ui.splash_anim import LogoAnim  # noqa: F401 - registra la clase para el KV
from ui.pending import PostIt  # noqa: F401 - registra la clase para el KV
from ui.theme import c


_DIALOG_LIGHT = (0.985, 0.992, 0.985, 1)


def dialog_bg():
    """Fondo de los diálogos según el estilo: claro, o la superficie del estilo oscuro (antes
    era siempre blanco y en los estilos oscuros el título y los botones no se veían)."""
    from ui import theme as _t
    return c(_t.SURFACE) if _t.is_dark() else _DIALOG_LIGHT


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
def themed(**props):
    """Colores por defecto que dependen del estilo de la app (Ajustes › Estilo): el valor
    de la clase se fijó al importar; cada widget nuevo toma el del estilo actual, salvo que
    la regla KV o quien lo crea haya dado otro."""
    def deco(cls):
        at_import = {n: c(getattr(theme, t), a) for n, (t, a) in props.items()}
        orig = cls.__init__

        def __init__(self, **kw):
            orig(self, **kw)
            for name, (token, alpha) in props.items():
                if name not in kw and list(getattr(self, name)) == list(at_import[name]):
                    setattr(self, name, c(getattr(theme, token), alpha))
        cls.__init__ = __init__
        return cls
    return deco


@themed(md_bg_color=("GLASS", None), line_color=("GLASS_EDGE", None))
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


class NeonCard(GlassCard):
    """Tarjeta de la IA: borde morado neón que respira, con un destello que recorre el borde.
    Solo se anima mientras está en pantalla (30 cuadros/s; se detiene al salir)."""
    NEON = "#B14DFF"       # = ui.ai_style.PURPLE
    NEON_2 = "#3D5AFE"     # = ui.ai_style.INDIGO (violeta → azulado)

    def __init__(self, **kw):
        super().__init__(**kw)
        from kivy.graphics import Color, Ellipse, Line
        import random as _r
        rnd = _r.Random(11)
        self._stars = []                       # cielo estelar tenue (sobre el vidrio, bajo el texto)
        with self.canvas.before:
            for _ in range(16):
                col = Color(1, 1, 1, 0)
                self._stars.append((rnd.random(), rnd.random(), rnd.uniform(.7, 1.8), rnd.random() * 6, col,
                                    Ellipse(size=(1, 1))))
        with self.canvas.after:
            self._halo_c = Color(0, 0, 0, 0)
            self._halo = Line(width=dp(4))
            self._edge_c = Color(0, 0, 0, 0)
            self._edge = Line(width=dp(1.6))
            self._tail_c = Color(0, 0, 0, 0)
            self._tail = Line(width=dp(4.5), cap="round")
            self._spark_c = Color(0, 0, 0, 0)
            self._spark = Line(width=dp(2), cap="round")
        self._path, self._t, self._ev = [], 0.0, None
        self.bind(pos=self._shape, size=self._shape, radius=self._shape, parent=self._watch)

    def _watch(self, *_):
        if self.parent is not None and self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 1 / 30)
        elif self.parent is None and self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def _shape(self, *_):
        """Puntos del borde redondeado (sentido horario), para que el destello lo recorra."""
        import math
        x, y, w, h = self.x + dp(1), self.y + dp(1), self.width - dp(2), self.height - dp(2)
        if w < 10 or h < 10:
            self._path = []
            return
        r = min(self.radius[0] if self.radius else dp(20), w / 2.1, h / 2.1)
        rr = (x, y, w, h, r)
        self._halo.rounded_rectangle = rr
        self._edge.rounded_rectangle = rr
        pts = []
        corners = [(x + w - r, y + h - r, 0), (x + w - r, y + r, -90), (x + r, y + r, -180), (x + r, y + h - r, -270)]
        for cx, cy, a0 in corners:                      # 4 esquinas unidas por rectas
            for i in range(9):
                a = math.radians(90 + a0 - i * 90 / 8)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        pts.append(pts[0])
        dens = []                                       # remuestreo uniforme
        total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        step = total / 160
        acc, i, cur = 0.0, 0, pts[0]
        dens.append(cur)
        while len(dens) < 160 and i < len(pts) - 1:
            seg = math.dist(cur, pts[i + 1])
            if acc + seg >= step:
                k = (step - acc) / seg if seg else 0
                cur = (cur[0] + (pts[i + 1][0] - cur[0]) * k, cur[1] + (pts[i + 1][1] - cur[1]) * k)
                dens.append(cur)
                acc = 0.0
            else:
                acc += seg
                cur = pts[i + 1]
                i += 1
        self._path = dens

    def _tick(self, dt):
        import math
        if self.get_root_window() is None or not self._path:
            return
        self._t = (self._t + dt) % 1000
        pulse = .5 + .5 * math.sin(self._t * 2.4)
        a, b = c(self.NEON), c(self.NEON_2)
        mix = .5 + .5 * math.sin(self._t * .9)
        col = [a[i] + (b[i] - a[i]) * mix for i in range(3)]
        self._halo_c.rgba = (*col, .10 + .14 * pulse)
        self._edge_c.rgba = (*col, .65 + .3 * pulse)
        n = len(self._path)
        head = int((self._t * .22 % 1) * n)
        tail = [self._path[(head - k) % n] for k in range(int(n * .16), -1, -1)]
        spark = tail[-int(n * .06):]
        self._tail.points = [v for p in tail for v in p]
        self._spark.points = [v for p in spark for v in p]
        self._tail_c.rgba = (*col, .28)
        self._spark_c.rgba = (1, .92, 1, .95)
        dark = theme.is_dark()
        for fx, fy, sz, ph, cc, el in self._stars:
            d = dp(sz)
            el.pos = (self.x + dp(8) + fx * (self.width - dp(16)) - d / 2, self.y + dp(8) + fy * (self.height - dp(16)) - d / 2)
            el.size = (d, d)
            tw = .5 + .5 * math.sin(self._t * 1.6 + ph)
            cc.rgba = (1, 1, 1, .15 + .55 * tw) if dark else (*c(self.NEON)[:3], .10 + .35 * tw)


class LongPress:
    """Mezcla para botones: mantener presionado HOLD s = on_long_press (y entonces no se
    dispara el toque normal). Se cancela si el dedo se mueve (desplazar la lista)."""
    HOLD = 3.0
    __events__ = ("on_long_press",)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._hold = None
        self._fired = False

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not self.disabled:
            self._fired = False
            self._cancel()
            self._hold = Clock.schedule_once(lambda *_: self._fire(touch), self.HOLD)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._hold and touch.grab_current is self and \
                (abs(touch.x - touch.ox) > dp(16) or abs(touch.y - touch.oy) > dp(16)):
            self._cancel()           # se está desplazando la pantalla
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        self._cancel()
        if self._fired and touch.grab_current is self:   # fue un mantener presionado: sin toque
            self._fired = False
            touch.ungrab(self)
            self.state = "normal"
            return True
        return super().on_touch_up(touch)

    def _cancel(self):
        if self._hold:
            self._hold.cancel()
            self._hold = None

    def _fire(self, _touch):
        self._hold = None
        self._fired = True
        self.dispatch("on_long_press")

    def on_long_press(self):
        pass


class WeekTitle(LongPress, ButtonBehavior, MDLabel):
    """Título «Semana del …»: tocar = calendario; mantener presionado 3 s = on_long_press
    (y entonces no se abre el calendario)."""


class GlassButton(ButtonBehavior, GlassCard):
    """Tarjeta pulsable con realce al tocar (sin animación de ripple)."""

@themed(bg=("LEAF_SOFT", None), fg=("LEAF_DARK", None))
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


@themed(bg_on=("BERRY", None), bg_off=("SURFACE", .55), fg_on=("ON_BERRY", None), fg_off=("LEAF_DARK", None),
        edge=("GLASS_EDGE", None))
class PillButton(ButtonBehavior, Label):
    """Botón píldora dibujado con UNA forma redondeada (sin la sombra rectangular de los
    botones con relieve de KivyMD, que en algunos teléfonos se veía desplazada junto con
    el color de «presionado»)."""
    selected = BooleanProperty(False)
    bg_on = ColorProperty(c(theme.BERRY))
    bg_off = ColorProperty(c(theme.SURFACE, .55))
    fg_on = ColorProperty(c(theme.ON_BERRY))
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


@themed(accent=("LEAF_SOFT", None))
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


def pick_dialog(title: str, items: list[tuple], dark: bool = False, subtitle: str = "",
                footer: list[tuple] | None = None, empty: str = "", image: str | None = None):
    """
    Lista de selección en un diálogo CENTRADO y a lo ancho (reemplaza al menú
    desplegable, que se abría desplazado y cortaba los nombres largos).
    items: (título, subtítulo, callback) o (título, subtítulo, callback, color_acento)
    o (título, subtítulo, callback, color_acento | None, al_tocar_basurero).
    subtitle: línea chica bajo el título · footer: botones aparte bajo la lista
    [(ícono, texto, callback)] · empty: texto si la lista está vacía.

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
                     height=min(dp(440) if not footer else dp(330), dp(64) * len(items) + dp(8)))
    layout = RecycleBoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6),
                              padding=(0, dp(4)), default_size=(None, dp(58)),
                              default_size_hint=(1, None))
    layout.bind(minimum_height=layout.setter("height"))
    rv.add_widget(layout)
    rv.viewclass = "PickRow"
    rv.data = data
    content = rv
    if subtitle or footer or (empty and not items):
        from kivy.factory import Factory
        content = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(10))
        if subtitle:
            sub = MDLabel(text=subtitle, font_style="Body2", adaptive_height=True,
                          theme_text_color="Custom", text_color=c(theme.MUTED))
            if image:                   # dibujo del módulo junto a la bajada (p. ej. Mediciones)
                from kivy.uix.image import Image
                head = MDBoxLayout(adaptive_height=True, spacing=dp(10))
                head.add_widget(Image(source=image, size_hint=(None, None), size=(dp(52), dp(52)),
                                      fit_mode="contain", mipmap=True))
                sub.pos_hint = {"center_y": .5}
                head.add_widget(sub)
                content.add_widget(head)
            else:
                content.add_widget(sub)
        if items:
            content.add_widget(rv)
        elif empty:
            content.add_widget(MDLabel(text=empty, font_style="Caption", adaptive_height=True,
                                       theme_text_color="Custom", text_color=c(theme.MUTED)))
        if footer:
            from kivy.uix.stacklayout import StackLayout
            row = StackLayout(size_hint_y=None, spacing=dp(8), padding=(0, dp(6), 0, 0))
            row.bind(minimum_height=row.setter("height"))
            for icon, text, cb in footer:
                b = Factory.GhostButton(icon=icon, text=text, on_release=lambda *_, cb=cb: wrap(cb)())
                b.size_hint = (1, None)
                row.add_widget(b)
            content.add_widget(row)
    dialog = MDDialog(title=title, type="custom", content_cls=content, md_bg_color=dialog_bg(),
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


@themed(accent=("LEAF_SOFT", None))
class ScaleGroup(ButtonBehavior, GlassCard):
    title = StringProperty()
    count = StringProperty()
    accent = ColorProperty(c(theme.LEAF_SOFT))
    expanded = BooleanProperty(False)
    macro = NumericProperty(0)


@themed(accent=("LEAF_SOFT", None))
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
    dialog = MDDialog(title=title, type="custom", content_cls=scroll, md_bg_color=dialog_bg(),
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
    except Exception as exc:  # noqa: BLE001
        import crashguard
        crashguard.quiet(exc, "catálogo: guardar variedad")


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
        self._crop_key = None
        self._bg.rgba = (1, 1, 1, 1) if self.source and os.path.exists(self.source) else c(theme.LEAF_SOFT, .8)
        self._layout()

    def _layout(self, *_):
        r = self._rect
        r.pos, r.size, r.radius = self.pos, self.size, [self.radius]
        if not self.source or self.width < 2 or self.height < 2:
            r.texture = None
            return
        # RoundedRectangle no respeta las coordenadas de una región de textura (estiraba la foto
        # entera al cuadro): se recorta la imagen «cover» a la proporción exacta del cuadro.
        key = (self.source, round(self.width / self.height, 2))
        if key != getattr(self, "_crop_key", None):
            self._crop_key = key
            self._tex = _cover_texture(*key)
            self._bg.rgba = (1, 1, 1, 1) if self._tex else c(theme.LEAF_SOFT, .8)
        r.texture = self._tex


_COVER: dict = {}


def _cover_texture(source: str, aspect: float):
    """Textura de la imagen recortada al centro con la proporción `aspect` (ancho/alto). En caché."""
    key = (source, aspect)
    tex = _COVER.get(key)
    if tex is not None:
        return tex
    try:
        from PIL import Image
        from kivy.graphics.texture import Texture
        img = Image.open(source)
        img.draft("RGB", (900, 900))
        img = img.convert("RGB")
        w, h = img.size
        if w / h > aspect:                       # más ancha: se recortan los lados
            cw = max(1, round(h * aspect))
            img = img.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
        else:                                    # más alta: arriba y abajo
            ch = max(1, round(w / aspect))
            img = img.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch))
        if max(img.size) > 900:
            img.thumbnail((900, 900))
        img = img.transpose(Image.FLIP_TOP_BOTTOM)   # Kivy dibuja de abajo hacia arriba
        tex = Texture.create(size=img.size, colorfmt="rgb")
        tex.blit_buffer(img.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
    except Exception:  # noqa: BLE001 - archivo dañado: queda el fondo suave
        return None
    if len(_COVER) > 240:
        _COVER.pop(next(iter(_COVER)))
    _COVER[key] = tex
    return tex


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


def text_dialog(title: str, lines: list[str], highlight: str = "", actions=(), small=False,
                markup: bool = False):
    """Diálogo con texto largo que se ajusta (diagnósticos, errores)."""
    from kivymd.uix.scrollview import MDScrollView
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                      padding=(0, 0, 0, dp(8)))
    for text in lines:
        box.add_widget(MDLabel(text=text, font_style="Caption" if small else "Body2", markup=markup,
                               adaptive_height=True, theme_text_color="Custom",
                               text_color=c(theme.BERRY if highlight and highlight in text else theme.INK)))
    sv = MDScrollView(size_hint_y=None, height=dp(380))
    sv.add_widget(box)
    dialog = None

    def run(cb):
        return lambda *_: (dialog.dismiss(), cb())

    content = sv
    if len(actions) > 1:
        # Varias acciones: arriba del texto, en filas que se acomodan al ancho (abajo, en
        # una sola fila, no cabían y quedaban cortadas: «…TODO ENVIAR TIEMPOS…»).
        from kivy.uix.stacklayout import StackLayout
        from kivymd.uix.button import MDRectangleFlatButton
        row = StackLayout(size_hint_y=None, spacing=dp(6), padding=(0, 0, 0, dp(8)))
        row.bind(minimum_height=row.setter("height"))
        for t, cb in actions:
            row.add_widget(MDRectangleFlatButton(text=t, on_release=run(cb), theme_text_color="Custom",
                                                 text_color=c(theme.LEAF_DARK), line_color=c(theme.LEAF_DARK, .4)))
        content = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(2))
        content.add_widget(row)
        content.add_widget(sv)
        buttons = [MDFlatButton(text="CERRAR", on_release=lambda *_: dialog.dismiss())]
    else:
        buttons = [MDFlatButton(text=t.upper(), on_release=run(cb)) for t, cb in actions]
        buttons.append(MDFlatButton(text="CERRAR", on_release=lambda *_: dialog.dismiss()))
    dialog = MDDialog(title=title, type="custom", content_cls=content, md_bg_color=dialog_bg(),
                      buttons=buttons)
    dialog.open()
    if content is not sv:
        def fit(*_):
            dialog.update_height()
            Clock.schedule_once(lambda *_: setattr(dialog, "height", dialog.ids.container.height), 0)
        content.bind(height=fit)
        Clock.schedule_once(fit, .05)
    return dialog


def show_error_log():
    """Ajustes › Registro de errores: lo último de cada error, con «Copiar todo» (el texto
    completo, para pegarlo en un chat) y «Enviar archivo» (.txt por WhatsApp, correo…)."""
    import crashguard
    from platform_utils import app_version
    lines = crashguard.entries()

    def copy_all():
        from kivy.core.clipboard import Clipboard
        try:
            Clipboard.copy(crashguard.full_text())
            app().toast("Registro copiado: péguelo en el chat")
        except Exception as exc:  # noqa: BLE001
            app().toast(f"No se pudo copiar: {exc}")

    def send_file():
        try:
            path = crashguard.export_file()
            app().media.share(path, "text/plain", title="Enviar registro de errores",
                              subject=os.path.basename(path))
        except Exception as exc:  # noqa: BLE001
            app().toast(f"No se pudo enviar: {exc}")

    def times():
        # Tiempos de la app (para optimizar): resumen de esta apertura, con copiar.
        import perf
        perf.flush()

        def copy_times():
            from kivy.core.clipboard import Clipboard
            try:
                Clipboard.copy(f"{app().title or 'AeonCrop'} {app_version()}\n" + perf.full_text())
                app().toast("Tiempos copiados: péguelos en el chat")
            except Exception as exc:  # noqa: BLE001
                app().toast(f"No se pudo copiar: {exc}")
        text_dialog("Tiempos de la app", perf.summary()[:40] or ["Aún sin mediciones."],
                    actions=[("Copiar tiempos", copy_times), ("Enviar", send_file)], small=True)

    actions = [("Copiar todo", copy_all), ("Enviar", send_file), ("Tiempos", times)]
    if lines:
        actions.append(("Borrar", lambda: confirm(
            "Borrar registro", "Se borran los errores guardados en el teléfono.",
            [("Borrar", lambda: (crashguard.clear(), app().toast("Registro borrado")))])))
    text_dialog("Registro de errores",
                [f"{app().title or 'AeonCrop'} {app_version()}"] + (lines or ["Sin errores registrados."]),
                highlight="Error", actions=actions, small=True)


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
    dialog = MDDialog(title=title, text=text, buttons=buttons, md_bg_color=dialog_bg())
    dialog.open()
    return dialog


def form_dialog(title: str, content, on_ok, ok_text: str = "GUARDAR"):
    dialog = None

    def _ok(*_):
        if on_ok(content) is not False:
            dialog.dismiss()

    dialog = MDDialog(title=title, type="custom", content_cls=content, md_bg_color=dialog_bg(), buttons=[
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
    dialog = MDDialog(title=title, type="custom", content_cls=sv, md_bg_color=dialog_bg(),
                      buttons=[MDFlatButton(text="CERRAR", on_release=lambda *_: dialog.dismiss())])
    dialog.open()


def _crop():
    import crops
    return crops.current()


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


# Piezas de IA (AIButton, AIGhost, AIBar…): se registran para usarlas en las reglas KV.
from ui import ai_style  # noqa: E402,F401
