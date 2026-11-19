"""
ui/reports_ui.py
================
Informes: lista, generación y acciones.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from kivy.clock import Clock
from kivy.properties import BooleanProperty, ListProperty, ObjectProperty, StringProperty
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import GlassButton, app, confirm, fast_clear, pick_dialog


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


# --------------------------------------------- filas de informe (opción B)
from kivy.graphics import Color, RoundedRectangle  # noqa: E402
from kivy.metrics import dp, sp  # noqa: E402
from kivy.uix.behaviors import ButtonBehavior  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.stacklayout import StackLayout  # noqa: E402
from kivy.uix.widget import Widget  # noqa: E402
from ui.common import GlassCard  # noqa: E402


def _glyph(name: str) -> str:
    from kivymd.icon_definitions import md_icons
    return md_icons.get(name, "")


class GradIcon(Widget):
    """Ícono de línea (Material) blanco sobre un cuadrado redondeado con degradado."""
    icon = StringProperty("file-document-outline")
    c1 = StringProperty("#3E8A63")
    c2 = StringProperty("#1E4A3A")

    def __init__(self, **kw):
        super().__init__(size_hint=(None, None), size=(dp(48), dp(48)), **kw)
        self.bind(pos=self._draw, size=self._draw, icon=self._draw, c1=self._draw, c2=self._draw)

    def _draw(self, *_):
        from kivy.core.text import Label as CoreLabel
        from ui.ws_cards import gradient
        self.canvas.clear()
        lab = CoreLabel(text=_glyph(self.icon), font_name="Icons", font_size=sp(25), color=(1, 1, 1, 1))
        lab.refresh()
        t = lab.texture
        with self.canvas:
            Color(0, 0, 0, .10)
            RoundedRectangle(pos=(self.x, self.y - dp(2)), size=self.size, radius=[dp(16)])
            Color(1, 1, 1, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(16)], texture=gradient(self.c1, self.c2))
            RoundedRectangle(texture=t, size=t.size, pos=(self.center_x - t.width / 2, self.center_y - t.height / 2))


class ChipButton(ButtonBehavior, BoxLayout):
    """Pastilla para elegir (semana, rango, parcela…): ícono chico + texto, ancho justo."""
    text = StringProperty("")
    icon = StringProperty("")

    def __init__(self, **kw):
        super().__init__(size_hint=(None, None), height=dp(32), padding=(dp(10), 0, dp(12), 0),
                         spacing=dp(5), **kw)
        col = c(theme.LEAF_DARK)
        self._ic = Label(font_name="Icons", font_size=sp(15), color=col, size_hint=(None, 1), width=dp(16))
        self._lb = Label(font_size=sp(12.5), bold=True, color=col, size_hint=(None, 1), shorten=True,
                         shorten_from="right", halign="left", valign="middle")
        self.add_widget(self._ic)
        self.add_widget(self._lb)
        self.bind(text=self._fit, icon=self._fit, pos=self._bg, size=self._bg, state=self._bg,
                  parent=self._on_parent, disabled=self._bg)
        self._fit()

    def _on_parent(self, *_):
        if self.parent is not None:
            self.parent.bind(width=self._fit)      # al conocer el ancho real, se ajusta
        self._fit()

    def _fit(self, *_):
        self._ic.text = _glyph(self.icon) if self.icon else ""
        self._ic.width = dp(16) if self.icon else 0
        self._lb.text = self.text
        self._lb.text_size = (None, None)
        self._lb.texture_update()
        room = (self.parent.width - dp(4)) if self.parent and self.parent.width > 100 else dp(300)
        w = min(self._lb.texture_size[0] + dp(6), room - self._ic.width - dp(30))   # holgura: sin «…» de más
        self._lb.width = w
        self._lb.text_size = (w, None)
        self.width = w + self._ic.width + dp(27)

    def _bg(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*c(theme.LEAF_DARK)[:3], .16 if self.state == "down" else .08)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.height / 2])


class ReportItem(GlassCard):
    """Fila de un informe: ícono con degradado · título, descripción y pastillas · botón PDF."""
    icon = StringProperty("file-document-outline")
    c1 = StringProperty("#3E8A63")
    c2 = StringProperty("#1E4A3A")
    title = StringProperty("")
    desc = StringProperty("")
    go_text = StringProperty("PDF")
    __events__ = ("on_go",)

    def __init__(self, **kw):
        self._ready = False
        super().__init__(orientation="horizontal", size_hint_y=None, padding=(dp(12), dp(12), dp(10), dp(12)),
                         spacing=dp(12), **kw)
        self.radius = [dp(20)]
        self.gi = GradIcon(pos_hint={"top": 1})
        self.col = BoxLayout(orientation="vertical", size_hint_y=None, height=0, spacing=dp(3))
        self.col.bind(minimum_height=self.col.setter("height"))
        self.t = MDLabel(bold=True, font_style="Subtitle1", adaptive_height=True, theme_text_color="Custom",
                         text_color=c(theme.INK))
        self.d = MDLabel(font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                         text_color=c(theme.MUTED))
        self.extra = BoxLayout(orientation="vertical", size_hint_y=None, height=0, spacing=dp(2))
        self.extra.bind(minimum_height=self.extra.setter("height"))
        self.chips = StackLayout(size_hint_y=None, height=0, spacing=dp(6), padding=(0, dp(4), 0, 0))
        self.chips.bind(minimum_height=self.chips.setter("height"))
        for w in (self.t, self.d, self.extra, self.chips):
            self.col.add_widget(w)
        self.go = Label(text=self.go_text, bold=True, font_size=sp(12), color=(1, 1, 1, 1),
                        size_hint=(None, None), size=(dp(46), dp(46)), pos_hint={"center_y": .5})
        self.go.bind(pos=self._go_bg, size=self._go_bg)
        self.go.bind(on_touch_down=self._go_touch)
        super().add_widget(self.gi)
        super().add_widget(self.col)
        super().add_widget(self.go)
        self.col.bind(height=self._fit)
        self.bind(icon=self._sync, c1=self._sync, c2=self._sync, title=self._sync, desc=self._sync,
                  go_text=self._sync)
        self._ready = True
        self._sync()

    def add_widget(self, widget, *args, **kw):
        if not getattr(self, "_ready", False):
            return super().add_widget(widget, *args, **kw)
        # Lo que se pone en el KV: pastillas abajo; textos extra (avisos) bajo la descripción.
        (self.chips if isinstance(widget, ChipButton) else self.extra).add_widget(widget)

    def _sync(self, *_):
        self.gi.icon, self.gi.c1, self.gi.c2 = self.icon, self.c1, self.c2
        self.t.text, self.d.text = self.title, self.desc
        self.go.text = self.go_text

    def _fit(self, *_):
        self.height = max(dp(72), self.col.height + dp(24))

    def _go_bg(self, *_):
        self.go.canvas.before.clear()
        with self.go.canvas.before:
            Color(*c(theme.BERRY)[:3], 1)
            RoundedRectangle(pos=self.go.pos, size=self.go.size, radius=[self.go.width / 2])

    def _go_touch(self, w, touch):
        if w.collide_point(*touch.pos) and not self.disabled:
            self.dispatch("on_go")
            return True
        return False

    def on_go(self, *_):
        pass


# Grupos de la lista de informes: (prefijo del archivo, título)
REPORT_GROUPS = [("semanal", "Reportes semanales"), ("periodo", "Evolución mensual / rango"),
                 ("variedad", "Fichas por variedad"), ("matriz", "Matriz comparativa"),
                 ("tratamientos", "Comparación de tratamientos"), ("diasgrado", "Fenología y días grado"),
                 ("comparacion", "Comparación entre temporadas"),
                 ("", "Mediciones y otros")]


class ReportsTab(MDScreen):
    sel_week = ObjectProperty(None, allownone=True)
    sel_from = ObjectProperty(None, allownone=True)
    sel_to = ObjectProperty(None, allownone=True)
    sel_variety = ObjectProperty(None, allownone=True)
    sel_month = ObjectProperty(None, allownone=True)

    def open_config(self):
        from ui.report_config_ui import open_sheet
        open_sheet(on_close=self._config_label)

    def _config_label(self):
        import report_config as rc
        self.ids.cfg_summary.text = rc.summary(rc.load(app().db))

    def generate_all_weekly(self):
        """Un ZIP con el informe semanal (PDF) de cada semana con datos de la temporada."""
        a = app()
        r = a.configured_reports()

        def progress(i, n, w):
            Clock.schedule_once(lambda *_: a.toast(f"Semanales: {i + 1} de {n}…"))
        a.run_report(lambda: r.weekly_zip(a.season, progress=progress),
                     on_done=lambda _res: self.list_recent())

    def refresh(self):
        a = app()
        self._config_label()
        weeks = a.db.list_weeks(a.season)
        if not weeks:
            weeks = [a.db.current_week()]
        if self.sel_week is None or self.sel_week["season"] != a.season:
            self.sel_week = a.week
            self.sel_from, self.sel_to = weeks[0], a.week
        if self.sel_variety is None or not a.db.get_variety(self.sel_variety["id"]):
            vs = a.db.pheno_units()
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
        self.ids.variety_title.title = "Ficha completa por parcela" if trial else "Ficha completa por variedad"
        self._labels()
        self._gdd_label()
        self._cmp_label()
        self.list_recent()

    # ------------------------------------------------ 6. fenología y días grado
    def _gdd_label(self):
        from ui import degree_days_ui as gdu
        import degree_days as gd
        a = app()
        ws = a.workspace or {}
        p = gdu.predio_of(ws)
        ids = self.ids
        ids.gdd_predio_btn.opacity = 0 if ws.get("profile") == "predio" else 1
        ids.gdd_predio_btn.disabled = ws.get("profile") == "predio"
        if p is None:
            ids.gdd_info.text = "Sin predio: créelo en el perfil Predio para cargar sus temperaturas."
            return
        ids.gdd_predio_btn.text = f"Predio: {p['name']}"
        try:
            mode = gdu.mode_of(p)
            src = gd.MODES[mode][0]
            s = gd.Series(gdu.season_rows(p, a.season)[0], a.season)
            ids.gdd_info.text = (f"Fuente: {src} · {len(s.days)} días · "
                                 f"{gd.fmt(s.total, 0)} °C·día al {gd.short_date(s.last)}" if s.days else
                                 f"Fuente: {src} · aún sin datos desde el 1 de septiembre.")
            if mode == gd.MODE_OM:
                gdu.om_refresh(p, on_done=lambda n: n and self._gdd_label())
        except Exception as exc:  # noqa: BLE001
            ids.gdd_info.text = f"Temperaturas de {p['name']}"
            print("días grado:", exc)

    def _cmp_label(self):
        from ui import degree_days_ui as gdu
        import season_compare as sc
        try:
            mode, refs, avail = gdu.cmp_refs()
        except Exception as exc:  # noqa: BLE001
            print("comparación:", exc)
            return
        ids = self.ids
        cur = sc.season_label(app().season)
        if not refs:
            ids.cmp_info.text = (f"Aún no hay estados BBCH de temporadas anteriores en este ensayo: "
                                 f"regístrelos o impórtelos para comparar con {cur}.")
            ids.cmp_refs_btn.text = "Comparar contra"
            return
        base = (sc.season_label(refs[0]) if len(refs) == 1 else
                f"promedio de {len(refs)} temporadas")
        ids.cmp_info.text = f"{cur} vs {base}" + (f" · disponibles: {', '.join(sc.season_label(x) for x in avail)}"
                                                   if len(avail) > 1 else "")
        ids.cmp_refs_btn.text = "Contra: " + (sc.season_label(refs[0]) if len(refs) == 1 else "promedio")

    def cmp_pick_refs(self):
        from ui import degree_days_ui as gdu
        gdu.pick_cmp_refs(on_done=self._cmp_label)

    def cmp_preview(self):
        from ui import degree_days_ui as gdu
        app().toast("Preparando vista previa…")
        gdu.generate_compare("preview")

    def cmp_generate(self):
        from ui import degree_days_ui as gdu
        gdu.generate_compare("pdf", on_done=lambda _res: self.list_recent())

    def gdd_weather(self):
        from ui import degree_days_ui as gdu
        gdu.open_weather(on_change=self._gdd_label)

    def gdd_pick_predio(self):
        from ui import degree_days_ui as gdu
        gdu.pick_predio(app().workspace, on_done=self._gdd_label)

    def gdd_generate(self):
        from ui import degree_days_ui as gdu
        gdu.generate("pdf", on_done=lambda _res: self.list_recent())

    def _labels(self):
        ids = self.ids
        ids.week_btn.text = ph.week_title(self.sel_week)
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

        pick_dialog("Mes", [(f"{ph.MESES[m - 1].capitalize()} {y}", "", lambda ym=(y, m): choose(ym))
                            for y, m in months])

    def pick_variety(self, caller):
        def choose(v):
            self.sel_variety = v
            self._labels()
        pick_dialog("Variedad", [(ph.unit_compact(v), "", lambda v=v: choose(v))
                                 for v in app().db.pheno_units()])

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
