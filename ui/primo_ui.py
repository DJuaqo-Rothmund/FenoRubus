"""
ui/primo_ui.py
==============
Primocaña (brotes del año, desde BBCH 30) dentro del registro semanal: OPCIONAL.

* Sin datos esa semana: solo un botón «＋ Agregar primocaña (opcional)».
* Con datos: tarjeta frambuesa con su foto, los LARGOS de n primocañas (cm; calcula el
  promedio y el máximo, y muestra el máximo de la temporada de esa variedad/parcela), el estado
  BBCH (escala desde 30) y notas. «Quitar primocaña» la borra de esa semana.
* No cuenta para el avance de la semana (la floricaña es la obligatoria).
* Se guarda junto con el registro (disquete); si quedó vacía, no se guarda nada.
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout

import phenology as ph
from ui.common import app, confirm, fast_clear
from ui.theme import c

PRIMO_INK = "#A8184A"
PRIMO_BG = "#FBE6EC"


def _n(v) -> str:
    """120 -> «120» · 117.83 -> «117,8»."""
    return (f"{v:.1f}".rstrip("0").rstrip(".") if v is not None else "").replace(".", ",")


class _SlotProxy:
    """Lo que PhotoSlot le pide a «su pantalla» (capturar, elegir principal, quitar), para
    las fotos de la primocaña."""

    def __init__(self, section):
        self.section = section

    @property
    def ids(self):
        return self.section.screen.ids

    def capture(self, kind, source):
        self.section.capture(kind, source)

    def make_primary(self, kind, photo_id):
        app().db.set_primo_primary(photo_id)
        self.section.refresh_slot(kind)

    def remove_photo(self, kind):
        self.section.remove_photo(kind)


class PrimoSection(MDBoxLayout):
    def __init__(self, screen, **kw):
        super().__init__(orientation="vertical", adaptive_height=True, spacing=dp(10), **kw)
        self.screen = screen
        self.primo = None
        self.slots = {}

    # ------------------------------------------------------------ armar
    def load(self):
        a = app()
        s = self.screen
        self.primo = a.db.get_primo(s.variety_id, s.week_id)
        fast_clear(self)
        self.slots = {}
        if self.primo is None:
            b = Factory.GhostButton(icon="sprout-outline", text="Agregar primocaña (opcional)",
                                    on_release=lambda *_: self.open())
            b.text_color = c(PRIMO_INK)
            b.icon_color = c(PRIMO_INK)
            self.add_widget(b)
            return
        card = Factory.PaperCard()
        card.md_bg_color = c(PRIMO_BG, .85)
        card.line_color = c(PRIMO_INK, .25)
        head = MDBoxLayout(adaptive_height=True, spacing=dp(6))
        lb = Factory.SectionLabel(text="PRIMOCAÑA · brotes del año (desde BBCH 30) · opcional")
        lb.theme_text_color = "Custom"
        lb.text_color = c(PRIMO_INK)
        head.add_widget(lb)
        rm = Factory.MDIconButton(icon="close", theme_icon_color="Custom", icon_color=c(PRIMO_INK),
                                  pos_hint={"center_y": .5}, on_release=lambda *_: self.remove())
        head.add_widget(rm)
        card.add_widget(head)
        grid = Factory.MDGridLayout(cols=2, spacing=dp(10), adaptive_height=True)
        proxy = _SlotProxy(self)
        slot = Factory.PhotoSlot(kind="canopy", caption="PRIMOCAÑA · FOTO", screen=proxy)
        slot.md_bg_color = c("#FFFFFF", .6)
        self.slots["canopy"] = slot
        grid.add_widget(slot)
        grid.add_widget(self._lengths_box())
        card.add_widget(grid)
        self.bbch = Factory.Field(hint_text="Estado BBCH de la primocaña (desde 30)")
        self.bbch.text = self.primo["bbch_label"] or (
            ph.bbch_label(self.primo["bbch_code"], a.db.bbch_names()) if self.primo["bbch_code"] is not None else "")
        card.add_widget(self.bbch)
        card.add_widget(Factory.GhostButton(icon="format-list-numbered", text="Elegir de la escala (desde BBCH 30)",
                                            on_release=lambda *_: self.open_scale()))
        self.notes = Factory.Field(hint_text="Notas de la primocaña (opcional)", multiline=True)
        self.notes.text = self.primo["notes"] or ""
        card.add_widget(self.notes)
        self.add_widget(card)
        for k in self.slots:
            self.refresh_slot(k)

    def _lengths_box(self):
        """LARGOS (cm) de n primocañas: se escriben separados por espacio; calcula al tiro."""
        a = app()
        box = Factory.GlassCard(orientation="vertical", padding=dp(10), spacing=dp(6), size_hint_y=None,
                                height=dp(318), radius=[dp(16)])
        box.md_bg_color = c("#FFFFFF", .6)
        box.add_widget(Factory.SectionLabel(text="LARGO DE PRIMOCAÑAS"))
        self.lengths = Factory.Field(hint_text="cm, ej.: 120 135 98,5", multiline=True)
        self.lengths.input_filter = lambda t, undo: "".join(ch for ch in t if ch in "0123456789,. ;\n")
        vals = a.db.primo_lengths(self.primo)
        self.lengths.text = " ".join(_n(v) for v in vals)
        box.add_widget(self.lengths)
        self.stats = Factory.Body(text="")
        self.stats.markup = True
        box.add_widget(self.stats)
        self.season_max = Factory.Muted(text="")
        box.add_widget(self.season_max)
        from kivy.uix.widget import Widget
        box.add_widget(Widget())
        self.lengths.bind(text=lambda *_: self._show_stats())
        self._show_stats()
        return box

    def _show_stats(self):
        a = app()
        try:
            vals = a.db.parse_lengths(self.lengths.text)
            st = a.db.length_stats(vals)
            self.stats.text = (f"[b]n = {st['n']}[/b]\nPromedio [b]{_n(st['mean'])} cm[/b]\nMáximo [b]{_n(st['max'])} cm[/b]"
                               if st else "Escriba el largo de cada primocaña medida.")
        except ValueError as exc:
            self.stats.text = f"[color=A8184A]{exc}[/color]" if str(exc).startswith("Largo") else \
                "[color=A8184A]Solo números (cm), separados por espacio.[/color]"
        s = self.screen
        prev = a.db.primo_max_lengths(s.week["season"]).get(s.variety_id)
        self.season_max.text = f"Máximo de la temporada: {_n(prev)} cm" if prev else ""

    def open(self):
        s = self.screen
        app().db.get_or_create_primo(s.variety_id, s.week_id)
        self.load()

    def refresh_slot(self, kind):
        if self.primo and kind in self.slots:
            self.slots[kind].show(app().db.list_primo_photos(self.primo["id"], kind))

    def remove(self):
        def go():
            app().db.delete_primo(self.primo["id"])
            self.load()
            app().toast("Primocaña quitada de esta semana")
        if self.primo is None:
            return
        if (app().db.primo_is_empty(self.primo["id"]) and not self.bbch.text.strip() and not self.notes.text.strip()
                and not self.lengths.text.strip()):
            go()
            return
        confirm("Quitar primocaña", "Se borra la primocaña de esta semana (estado y notas). Las fotos "
                "quedan en el teléfono y en Drive.", [("Quitar", go)])

    # ------------------------------------------------------------ fotos
    def capture(self, kind, source):
        from android_bridge import store_photo
        from platform_utils import data_subdir
        a = app()
        s = self.screen
        primo_id = self.primo["id"]
        week, variety = s.week, s.variety

        def base():
            seq = len(a.db.list_primo_photos(primo_id, kind)) + 1
            return ph.photo_basename(variety, week["start_date"], kind, seq, trial=a.db.code) + "-PRIMO"

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            self.slots[kind].show_busy("Procesando foto…")

            def work():
                error = None
                try:
                    dest_dir = data_subdir("photos", f"T{week['season']}", ph.week_dir(week))
                    for tmp in paths:
                        path = store_photo(tmp, dest_dir, base(), exact=True)
                        a.db.add_primo_photo(primo_id, kind, path, source=origin)
                        a.thumb(path, 640)
                        a.thumb(path, 160)
                        a.backup_extra(path, week["start_date"], "Primocaña")
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: stored(error))

            def stored(error):
                if self.primo is None or self.primo["id"] != primo_id:
                    return
                self.refresh_slot(kind)
                if error:
                    a.toast(f"No se pudo guardar la foto: {error}")

            a.workers.submit(work)

        if source == "camera":
            from ui import camera_burst
            what = "Primocaña"
            camera_burst.burst(done, base, exact=True, title=f"{what}\n{a.db.display_name(variety)}")
        else:
            a.media.pick_images(done)

    def remove_photo(self, kind):
        a = app()
        photos = a.db.list_primo_photos(self.primo["id"], kind)
        if not photos:
            return

        def do():
            a.db.delete_primo_photo(photos[0]["id"])
            self.refresh_slot(kind)
        confirm("Quitar la foto principal", "La foto se desvincula de la primocaña (el archivo se conserva "
                "en el teléfono).", [("Quitar", do)])

    # ------------------------------------------------------------ escala
    def open_scale(self):
        from ui.common import bbch_dialog
        a = app()

        def pick(code):
            if code is not None and code < a.db.PRIMO_MIN:
                a.toast("La primocaña parte en BBCH 30.")
                return
            self.bbch.text = ph.bbch_label(code, a.db.bbch_names())
        bbch_dialog("Escala BBCH · primocaña (desde 30)", a.db, pick,
                    current=ph.parse_bbch_code(self.bbch.text or ""), min_code=a.db.PRIMO_MIN)

    # ------------------------------------------------------------ guardar
    def save(self) -> bool:
        """Con el registro (disquete). False si el BBCH no sirve (se avisa)."""
        a = app()
        if self.primo is None:
            return True
        text = self.bbch.text.strip()
        code = ph.parse_bbch_code(text)
        if text and code is None:
            a.toast("Primocaña: indique un código BBCH (ej. «BBCH 35»).")
            return False
        if code is not None and code < a.db.PRIMO_MIN:
            a.toast("Primocaña: el estado parte en BBCH 30.")
            return False
        try:
            lengths = a.db.parse_lengths(self.lengths.text)
        except ValueError as exc:
            a.toast(f"Primocaña: {exc}" if str(exc).startswith("Largo") else
                    "Primocaña: los largos deben ser números (cm) separados por espacio.")
            return False
        a.db.update_primo(self.primo["id"], bbch_code=code, bbch_label=text, notes=self.notes.text,
                          lengths=lengths)
        if a.db.primo_is_empty(self.primo["id"]):          # quedó vacía: no se guarda nada
            a.db.delete_primo(self.primo["id"])
            self.primo = None
        return True
