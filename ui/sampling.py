"""
ui/sampling.py
==============
Muestreo semanal: pestaña principal, filas por variedad/parcela, temporada.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
import perf
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ColorProperty, NumericProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import (GlassButton, LongPress, app, bbch_tag_colors, confirm, fast_clear,
    form_dialog, pick_dialog, themed, thumb_widget)


class SettingsScreen(MDScreen):
    """Ajustes con dos pestañas: «General» y «Registros». Desde la pantalla de inicio se
    abre solo «General» (general_only), sin entrar a un ensayo o predio."""
    general_only = BooleanProperty(False)

    def on_general_only(self, _w, only):
        """Solo «General»: la fila de pestañas se SACA (oculta y desactivada seguía tomando
        los toques junto a la flecha de volver)."""
        row = self.ids.tabs
        # Referencia fuerte a la fila: `ids` solo guarda referencias débiles, y al sacarla de
        # la pantalla Kivy la borraba de la memoria (ReferenceError al volver a Ajustes).
        self._tabs_row = row
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


@themed(code_bg=("BERRY_SOFT", None), code_fg=("LEAF_DARK", None))
class VarietyRow(LongPress, GlassButton):
    """Fila del muestreo. Mantener presionado 3 s sobre un punto de la fenología unificada:
    cambiar su nombre."""
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


def rename_unit_dialog(variety_id: int, on_done=None):
    """Nombre propio de un punto de la fenología unificada (p. ej. «T1 · Planta del poste»).
    Vacío = vuelve al nombre automático. Solo los puntos (las parcelas y variedades se
    renombran en Ajustes)."""
    from kivy.factory import Factory
    a = app()
    v = a.db.get_variety(variety_id)
    if not v or not v.get("pheno_unit"):
        a.toast("Solo los puntos de la fenología unificada se renombran aquí (el resto, en Ajustes › Registros).")
        return
    auto = a.db.unit_auto_name(v)
    form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6), padding=(0, dp(8), 0, 0))
    f = Factory.Field(hint_text="Nombre del punto", text=v["name"])
    form.add_widget(f)
    form.add_widget(MDLabel(text=f"Vacío = nombre automático («{auto}»). Los registros y fotos siguen en el punto.",
                            font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                            text_color=c(theme.MUTED)))

    def ok(_f):
        try:
            a.db.rename_pheno_unit(variety_id, f.text)
        except ValueError as exc:
            a.toast(str(exc))
            return False
        a.toast("Nombre del punto guardado")
        if on_done:
            on_done()

    form_dialog("Cambiar nombre del punto", form, ok)


class SamplingTab(MDBoxLayout):
    extra = BooleanProperty(False)        # se ve el muestreo extra («Semana 44.5»)
    extra_text = StringProperty("+ Muestreo extra")

    def pick_season(self):
        season_dialog(self.refresh)

    @perf.timed("muestreo.refrescar lista")
    def refresh(self):
        a = app()
        week = a.week
        self.ids.season_chip.text = ph.season_title(a.season)
        start = _dt.date.fromisoformat(week["start_date"])
        end = a.db.week_end(week)
        self.extra = ph.is_extra(week)
        self.extra_text = ("Muestreo extra…" if self.extra
                           else ("Muestreo extra ›" if a.db.extra_week(week) else "+ Muestreo extra"))
        self.ids.week_kicker.text = ph.week_title(week).upper() + (" · MUESTREO EXTRA" if self.extra else "")
        self.ids.week_title.text = ph.week_label(start, extra=self.extra)
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
                row.bind(on_long_press=lambda w: rename_unit_dialog(w.variety_id, self.refresh))
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
        """Semana anterior / siguiente sin tope (2020-2050), pasando por el muestreo extra
        si lo hay (44 → 44.5 → 45): al cruzar el 1 de abril pasa sola a la temporada que
        corresponde."""
        a = app()
        nxt = a.db.next_week(a.week, delta)
        start = _dt.date.fromisoformat(nxt["start_date"])
        if start + _dt.timedelta(days=6) < ph.FIRST_BROWSE or start > ph.LAST_BROWSE:
            a.toast("Las semanas van de 2020 a 2050.")
            return
        a.week = nxt
        a.season = a.week["season"]
        self.refresh()

    # ------------------------------------------------------- muestreo extra
    def extra_action(self):
        a = app()
        if self.extra:
            week = a.week
            pick_dialog(f"Muestreo extra · {ph.format_date_es(_dt.date.fromisoformat(week['start_date']))}", [
                ("Cambiar la fecha", "Otro día de la misma semana", lambda: self.pick_extra_date(week)),
                (f"Ir a la {ph.week_title(a.db.regular_week(week)).split(',')[0]}", "El primer muestreo de la semana",
                 lambda: self._go(a.db.regular_week(week))),
                ("Quitar el muestreo extra", "Se borra lo registrado en él", self.delete_extra, theme.BERRY),
            ])
            return
        ex = a.db.extra_week(a.week)
        if ex:
            self._go(ex)
        else:
            self.pick_extra_date(a.week)

    def _go(self, week):
        a = app()
        a.week = week
        a.season = week["season"]
        self.refresh()

    def pick_extra_date(self, week):
        """Fecha del segundo muestreo: un día de la misma semana, después del primero."""
        a = app()
        from android_bridge import pick_date
        base = a.db.regular_week(week)
        first = _dt.date.fromisoformat(base["start_date"]) + _dt.timedelta(days=1)
        last = first + _dt.timedelta(days=5)
        today = _dt.date.today()
        cur = _dt.date.fromisoformat(week["start_date"]) if ph.is_extra(week) else \
            (today if first <= today <= last else first)

        def done(day):
            try:
                ex = a.db.add_extra_week(base, day)
            except ValueError as exc:
                a.toast(str(exc))
                return
            a.toast(f"{ph.week_title(ex)}: muestreo extra del {ph.format_date_es(day, False)}")
            self._go(ex)
        pick_date(cur, done, f"Fecha del muestreo extra ({ph.week_title(base).split(',')[0]})",
                  min_day=first, max_day=last)

    def delete_extra(self):
        a = app()
        week = a.week
        n = a.db.query_one("SELECT COUNT(*) AS n FROM observations WHERE week_id=? AND "
                           "(bbch_code IS NOT NULL OR EXISTS (SELECT 1 FROM photos p WHERE p.observation_id=observations.id))",
                           (week["id"],))["n"]

        def go():
            base = a.db.regular_week(week)
            a.db.delete_extra_week(week)
            a.toast(f"Muestreo extra quitado ({ph.week_title(week).split(',')[0]})")
            self._go(base)
        confirm("Quitar el muestreo extra",
                (f"Tiene {n} registro(s) con estado o fotos: se borran junto con el muestreo extra. "
                 if n else "") + "¿Quitar el muestreo extra de esta semana?",
                [("Quitar", go)])

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

    def move_week_dialog(self):
        """Mantener 3 s «Semana del …»: mover TODO lo de esta semana a otra (se muestreó
        esta semana pero se anotó en la hoja de otra)."""
        a = app()
        src = a.week
        info = a.db.week_data_summary(src["id"])
        if not info["total"]:
            a.toast("Esta semana no tiene datos para mover.")
            return

        def name(w):
            return f"{w['label']} · {ph.week_title(w).split(',')[0]}"

        def ask(dst):
            if dst["id"] == src["id"]:
                a.toast("Elija una semana distinta.")
                return
            have = a.db.week_data_summary(dst["id"])
            what = self._week_what(info)
            if not have["total"]:
                confirm("Mover datos de semana",
                        f"Pasar {what} de «{name(src)}» a «{name(dst)}» (que está vacía).",
                        [("Mover", lambda: self._do_move(src, dst))])
                return
            names = ", ".join(have["names"][:6]) + ("…" if len(have["names"]) > 6 else "")
            confirm("¿Está seguro?",
                    f"«{name(dst)}» YA TIENE DATOS: {self._week_what(have)}"
                    + (f" ({names})" if names else "") + ".\n\n"
                    f"Si mueve igual, {what} pasan allá; si una parcela tiene registro en ambas "
                    "semanas, se JUNTAN: las fotos se suman, el estado BBCH se completa si faltaba "
                    "(si ambos tienen, queda el de destino y el otro se anota en las notas). "
                    "No se pierde nada.",
                    [("Revisar destino", lambda: self._go(dst)),
                     ("Mover igual", lambda: self._do_move(src, dst))])

        def pick_other():
            from android_bridge import pick_date
            start = _dt.date.fromisoformat(src["start_date"][:10])

            def go(day):
                if day < ph.FIRST_BROWSE or day > ph.LAST_BROWSE:
                    a.toast("Las semanas van de 2020 a 2050.")
                    return
                ask(a.db.week_for_date(day))
            pick_date(start, go, "Mover a la semana de…")

        prev, nxt = a.db.next_week(src, -1), a.db.next_week(src, 1)

        def sub(w):
            n = a.db.week_data_summary(w["id"])["total"]
            return "Vacía" if not n else f"Tiene {n} dato(s): pedirá confirmación"
        pick_dialog(f"Mover {self._week_what(info)}", [
            (f"A la anterior: {name(prev)}", sub(prev), lambda: ask(prev)),
            (f"A la siguiente: {name(nxt)}", sub(nxt), lambda: ask(nxt)),
            ("Elegir otra semana…", "Calendario: cualquier día de la semana de destino", pick_other),
        ])

    @staticmethod
    def _week_what(info: dict) -> str:
        parts = [f"{info['records']} registro(s)" if info["records"] else "",
                 f"{info['photos']} foto(s)" if info["photos"] else "",
                 f"{info['entries']} medición(es)" if info["entries"] else "",
                 f"{info['attachments']} adjunto(s)" if info["attachments"] else ""]
        return ", ".join(p for p in parts if p) or "sin datos"

    def _do_move(self, src, dst):
        a = app()
        try:
            res = a.db.move_week_data(src["id"], dst["id"])
        except ValueError as exc:
            a.toast(str(exc))
            return
        self._go(a.db.get_week(dst["id"]))
        if a.db.get_setting("drive_enabled", False):
            a.drive.flush_async()      # en Drive, los archivos pasan a la carpeta de la nueva semana
        a.toast(f"Movidos a {dst['label']}: {res['records']} registro(s), {res['entries']} medición(es)"
                + (f". {res['merged']} se juntaron con el registro que ya había" if res["merged"] else ""))
        if a.home is not None:
            a.refresh_home()

    def go_current(self):
        a = app()
        a.week = a.db.current_week()
        a.season = a.week["season"]
        self.refresh()


# Referencias a otras pantallas (al final: así no hay importaciones circulares).
from ui.measures_ui import open_measures_menu  # noqa: E402
