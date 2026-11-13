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
