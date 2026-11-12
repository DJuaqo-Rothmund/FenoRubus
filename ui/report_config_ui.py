"""
ui/report_config_ui.py
======================
«Configuración de informes»: una hoja a pantalla completa con botones que se encienden
(rojo con un brillo en el borde) al elegirlos. Plantillas, formato y las secciones del
informe semanal. Se guarda en el ensayo (report_config.py) y se sincroniza con la web.
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.stacklayout import StackLayout
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView

import report_config as rc
from ui import theme
from ui.theme import c


def app():
    return MDApp.get_running_app()


class _Chip(ButtonBehavior, Label):
    """Botón píldora: blanco con borde fino; elegido, rojo fruta con brillo en el borde."""

    def __init__(self, text: str, on: bool = False, badge: str = "", on_tap=None, **kw):
        super().__init__(text=text + (f"  [size={int(sp(9))}][b]{badge}[/b][/size]" if badge else ""),
                         markup=True, font_size=sp(13.5), size_hint=(None, None), height=dp(38),
                         halign="center", valign="middle", **kw)
        self.on = on
        self._tap = on_tap
        self.bind(texture_size=self._fit, pos=self._draw, size=self._draw)
        self._fit()

    def _fit(self, *_):
        self.texture_update()
        self.width = self.texture_size[0] + dp(28)
        self._draw()

    def set(self, on: bool):
        self.on = on
        self._draw()

    def _draw(self, *_):
        self.color = c(theme.ON_BERRY) if self.on else c(theme.INK)
        self.canvas.before.clear()
        r = dp(19)
        with self.canvas.before:
            if self.on:
                Color(*c(theme.BERRY, .22))           # brillo
                RoundedRectangle(pos=(self.x - dp(3), self.y - dp(3)),
                                 size=(self.width + dp(6), self.height + dp(6)), radius=[r + dp(3)])
                Color(*c(theme.BERRY))
                RoundedRectangle(pos=self.pos, size=self.size, radius=[r])
                Color(*c(theme.BERRY_LIGHT))
                Line(rounded_rectangle=(self.x, self.y, self.width, self.height, r), width=dp(1.3))
            else:
                Color(1, 1, 1, .94)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[r])
                Color(*c(theme.LEAF_DARK, .28))
                Line(rounded_rectangle=(self.x, self.y, self.width, self.height, r), width=dp(1))

    def on_release(self):
        if self._tap:
            self._tap(self)


def _title(text: str) -> MDLabel:
    return MDLabel(text=text, font_style="Subtitle2", bold=True, adaptive_height=True,
                   theme_text_color="Custom", text_color=c(theme.LEAF_DARK), padding=(0, dp(10), 0, dp(2)))


def _hint(text: str) -> MDLabel:
    return MDLabel(text=text, font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                   text_color=c(theme.MUTED))


def _row() -> StackLayout:
    box = StackLayout(size_hint_y=None, spacing=dp(8), padding=(0, dp(4)))
    box.bind(minimum_height=box.setter("height"))
    return box


class ReportConfigSheet(ModalView):
    def __init__(self, on_close=None, **kw):
        super().__init__(size_hint=(1, 1), background_color=(0, 0, 0, .35), auto_dismiss=True, **kw)
        self.db = app().db
        self.cfg = rc.load(self.db)
        self._on_close = on_close
        card = MDBoxLayout(orientation="vertical", md_bg_color=c("#FBF8F1"), padding=(dp(16), dp(8), dp(16), dp(10)),
                           radius=[dp(22), dp(22), 0, 0])
        head = MDBoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        head.add_widget(MDIconButton(icon="arrow-left", on_release=lambda *_: self.dismiss(),
                                     pos_hint={"center_y": .5}))
        head.add_widget(MDLabel(text="Configuración de informes", font_style="H6", bold=True,
                                theme_text_color="Custom", text_color=c(theme.INK)))
        card.add_widget(head)
        self.body = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(2),
                                padding=(0, 0, 0, dp(16)))
        sv = MDScrollView(do_scroll_x=False)
        sv.add_widget(self.body)
        card.add_widget(sv)
        foot = MDBoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8), padding=(0, dp(6), 0, 0))
        self.summary = MDLabel(font_style="Caption", theme_text_color="Custom", text_color=c(theme.MUTED))
        foot.add_widget(self.summary)
        foot.add_widget(MDRaisedButton(text="LISTO", md_bg_color=c(theme.BERRY), elevation=0,
                                       on_release=lambda *_: self.dismiss(), pos_hint={"center_y": .5}))
        card.add_widget(foot)
        self.add_widget(card)
        self.build()
        names = [t["name"] for t in rc.saved_templates(self.db)]
        # Las de la web u otros equipos: aparecen apenas llegan de Drive.
        _push_templates(lambda: [t["name"] for t in rc.saved_templates(self.db)] != names and self.build())

    # ------------------------------------------------------------------ armar
    def build(self):
        b = self.body
        b.clear_widgets()
        cfg = self.cfg
        self._chips = []          # (botón, función cfg -> encendido)

        def Chip(text, _on, on_tap=None, badge="", when=None):   # noqa: N802
            w = _Chip(text, bool(when(cfg)) if when else _on, badge=badge, on_tap=on_tap)
            if when:
                self._chips.append((w, when))
            return w
        saved = rc.saved_templates(self.db)

        b.add_widget(_title("Plantilla"))
        row = _row()
        for key, t in rc.TEMPLATES.items():
            row.add_widget(Chip(t["name"], False, on_tap=lambda _w, k=key: self.use(k),
                                when=lambda c_, k=key: c_.get("template") == k))
        for t in saved:               # plantillas de la cuenta (todos los cultivos y equipos)
            key = f"u:{t['name']}"
            row.add_widget(Chip(t["name"], False, on_tap=lambda _w, k=key: self.use(k),
                                when=lambda c_, k=key: c_.get("template") == k))
        row.add_widget(Chip("+ Guardar la actual", False, on_tap=lambda *_: self.save_as()))
        if saved:
            row.add_widget(Chip("Borrar guardada…", False, on_tap=lambda *_: self.delete_saved()))
        b.add_widget(row)

        b.add_widget(_title("Formato"))
        row = _row()
        row.add_widget(Chip("PDF simple (sin logo ni marca)", False, on_tap=lambda *_: self.flip("plain"),
                            when=lambda c_: c_["plain"]))
        row.add_widget(Chip("Todas las fotos (no solo la principal)", False,
                            on_tap=lambda *_: self.flip("all_photos"), when=lambda c_: c_["all_photos"]))
        row.add_widget(Chip("Sin fecha de generación", False, on_tap=lambda *_: self.flip("no_date"),
                            when=lambda c_: c_["no_date"]))
        b.add_widget(row)
        b.add_widget(_hint("Fotos de cada variedad"))
        row = _row()
        for k, name in rc.PHOTO_MODES.items():
            row.add_widget(Chip(name, False, on_tap=lambda _w, k=k: self.put("photo_mode", k),
                                when=lambda c_, k=k: c_["photo_mode"] == k))
        b.add_widget(row)
        b.add_widget(_hint("Tamaño de las fotos"))
        row = _row()
        for k, name in rc.PHOTO_SIZES.items():
            row.add_widget(Chip(name, False, on_tap=lambda _w, k=k: self.put("photo_size", k),
                                when=lambda c_, k=k: c_["photo_size"] == k))
        b.add_widget(row)

        b.add_widget(_title("Secciones del informe semanal"))
        b.add_widget(_hint("Las secciones sin datos esa semana no salen en el informe."))
        for group in rc.GROUPS:
            b.add_widget(_hint(group.upper()))
            row = _row()
            for key, name, g in rc.SECTIONS:
                if g == group:
                    row.add_widget(Chip(name, False, badge="NUEVO" if key in rc.NEW else "",
                                        on_tap=lambda _w, k=key: self.toggle(k),
                                        when=lambda c_, k=key: k in c_["sections"]))
            b.add_widget(row)
        row = _row()
        row.add_widget(Chip("Todas las secciones", False, on_tap=lambda *_: self.all_sections()))
        row.add_widget(Chip("Ninguna", False, on_tap=lambda *_: self.no_sections()))
        b.add_widget(row)
        self.summary.text = rc.summary(cfg)

    # ---------------------------------------------------------------- cambios
    def _store(self, cfg, rebuild: bool = False):
        self.cfg = rc.save(self.db, cfg)
        if rebuild:
            Clock.schedule_once(lambda *_: self.build(), 0)
            return
        for w, when in self._chips:      # solo cambian los colores (el scroll no salta)
            w.set(bool(when(self.cfg)))
        self.summary.text = rc.summary(self.cfg)

    def use(self, key):
        self._store(rc.apply_template(self.cfg, key, rc.saved_templates(self.db)))

    def flip(self, key):
        self._store(dict(self.cfg, **{key: not self.cfg[key]}, template=""))

    def put(self, key, value):
        self._store(dict(self.cfg, **{key: value}, template=""))

    def toggle(self, key):
        self._store(rc.toggle(self.cfg, key))

    def all_sections(self):
        self._store(dict(self.cfg, sections=list(rc.SECTION_KEYS), template=""))

    def no_sections(self):
        self._store(dict(self.cfg, sections=[], template=""))

    def save_as(self):
        from kivy.factory import Factory
        from ui.screens import form_dialog
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
        f = Factory.Field(hint_text="Nombre de la plantilla (ej.: Gerencia)")
        form.add_widget(f)

        def ok(_f):
            name = f.text.strip()
            if not name:
                return False
            rc.save_template(self.db, name, self.cfg)
            self._store(dict(self.cfg, template=f"u:{name}"), rebuild=True)
            _push_templates()

        form_dialog("Guardar plantilla", form, ok)

    def delete_saved(self):
        from ui.screens import pick_dialog

        def drop(name):
            rc.delete_template(self.db, name)
            self._store(dict(self.cfg, template=""), rebuild=True)
            _push_templates()

        pick_dialog("Borrar plantilla guardada", [(t["name"], "", lambda n=t["name"]: drop(n))
                                                  for t in rc.saved_templates(self.db)])

    def on_dismiss(self):
        if self._on_close:
            self._on_close()


def _push_templates(done=None):
    """Une las plantillas de la cuenta con Drive, en segundo plano (sin Drive, al sincronizar).
    done(): cuando terminó (en el hilo de Kivy)."""
    a = app()
    try:
        if not a.db.get_setting("drive_enabled", False):
            return
    except Exception:  # noqa: BLE001
        return
    import threading

    def work():
        try:
            a.sync.sync_report_templates()
            if done:
                Clock.schedule_once(lambda *_: done(), 0)
        except Exception as exc:  # noqa: BLE001 (sin red: se suben al sincronizar)
            print("plantillas de informes:", exc)
        finally:
            try:
                from drive_backup import _detach
                _detach()
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=work, daemon=True).start()


def open_sheet(on_close=None):
    ReportConfigSheet(on_close=on_close).open()
