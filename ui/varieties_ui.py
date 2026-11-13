"""
ui/varieties_ui.py
==================
Variedades y parcelas: catálogo, formularios, línea de tiempo y ficha.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.properties import (BooleanProperty, ColorProperty, ListProperty, NumericProperty,
                             ObjectProperty, StringProperty)
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton, MDRectangleFlatButton
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.screen import MDScreen
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import (DIALOG_BG, GlassButton, SegButton, Tag, app, confirm, current_profile,
    fast_clear, form_dialog, manage_catalog, pick_catalog, pick_dialog, remember_variety,
    thumb_widget)


# ===========================================================================
# Variedades
# ===========================================================================
class VarietyCatalogRow(GlassButton):
    title = StringProperty()
    code = StringProperty()
    summary = StringProperty()
    variety_id = NumericProperty()
    tab = ObjectProperty()


def check_row(text: str, active: bool = False, on_change=None):
    """Casilla de verificación con su texto (tocar el texto también la marca).
    Devuelve (fila, casilla)."""
    from kivy.uix.behaviors import ButtonBehavior
    from kivymd.uix.selectioncontrol import MDCheckbox

    class _Tap(ButtonBehavior, MDLabel):
        pass

    row = MDBoxLayout(adaptive_height=True, spacing=dp(4))
    cb = MDCheckbox(active=active, size_hint=(None, None), size=(dp(40), dp(40)),
                    pos_hint={"center_y": .5})
    lbl = _Tap(text=text, adaptive_height=True, pos_hint={"center_y": .5})
    lbl.bind(on_release=lambda *_: setattr(cb, "active", not cb.active))
    if on_change:
        cb.bind(active=lambda _w, v: on_change(v))
    row.add_widget(cb)
    row.add_widget(lbl)
    return row, cb


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
            if a.db.is_parcel(v):
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
    def unified_dialog(self):
        """Fenología unificada: activar, para todo el ensayo o en cada tratamiento, cuántos
        puntos y el nombre de cada uno."""
        from kivy.factory import Factory
        from kivy.uix.scrollview import ScrollView
        a = app()
        db = a.db
        cfg = db.pheno_config()
        st = {"scope": cfg["scope"], "fields": []}
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                           padding=(0, dp(12), 0, 0))
        on_row, on_cb = check_row("Usar fenología unificada", db.unified_pheno)
        form.add_widget(on_row)
        seg = MDBoxLayout(adaptive_height=True, spacing=dp(8))
        b_all = SegButton(text="Para todo\nel ensayo", height=dp(50), shorten=False, font_size="13sp")
        b_trt = SegButton(text="En cada\ntratamiento", height=dp(50), shorten=False, font_size="13sp")
        seg.add_widget(b_all)
        seg.add_widget(b_trt)
        form.add_widget(seg)
        f_n = Factory.Field(hint_text="N.º de puntos (plantas o grupos)", input_filter="int",
                            text=str(len(cfg["names"])))
        form.add_widget(f_n)
        names_box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6))
        scroll = ScrollView(size_hint_y=None, height=0, do_scroll_x=False, bar_width=dp(3))
        scroll.add_widget(names_box)
        form.add_widget(scroll)
        # «En cada tratamiento»: cuántos puntos lleva CADA uno (0 = sin fenología), p. ej.
        # 3 en el de más cañas, 3 en el de menos y 0 en el intermedio.
        counts_box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(4))
        form.add_widget(counts_box)
        info = MDLabel(font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                       text_color=c(theme.MUTED))
        form.add_widget(info)
        old = list(cfg["names"])
        cur_counts = db.unit_counts(cfg)
        labels = {t["num"]: t["label"] for t in db.list_treatments()}
        st["counts"] = {}

        def counts_ui():
            fast_clear(counts_box)
            st["counts"] = {}
            if st["scope"] != "treatment":
                return
            counts_box.add_widget(MDLabel(text="Puntos en cada tratamiento (0 = sin fenología en ese tratamiento)",
                                          font_style="Caption", adaptive_height=True, theme_text_color="Custom",
                                          text_color=c(theme.LEAF_DARK)))
            grid = MDGridLayout(cols=3, adaptive_height=True, spacing=dp(6))
            for t in db.trial_nums():
                f = Factory.Field(hint_text=labels.get(t) or f"T{t}", input_filter="int",
                                  text=str(cur_counts.get(t, max_n())))
                f.bind(text=lambda *_: build(from_counts=True))
                grid.add_widget(f)
                st["counts"][t] = f
            counts_box.add_widget(grid)

        def max_n():
            try:
                return max(1, min(int(f_n.text or 1), db.MAX_REPS))
            except ValueError:
                return 1

        def read_counts() -> dict:
            out = {}
            for t, f in st["counts"].items():
                try:
                    out[t] = max(0, min(int(f.text or 0), db.MAX_REPS))
                except ValueError:
                    out[t] = 0
            return out

        def build(*_, from_counts=False):
            n = max_n()
            if st["scope"] == "treatment" and st["counts"]:
                n = max([n] + list(read_counts().values()))     # nombres para el que tiene más puntos
            keep = [f.text for f in st["fields"]] or old
            fast_clear(names_box)
            st["fields"] = []
            if n > 1 or st["scope"] == "treatment":
                for i in range(n):
                    f = Factory.Field(hint_text=f"Punto {i + 1} (ej.: {('Caña gruesa', 'Caña media', 'Caña delgada')[i % 3]})",
                                      text=keep[i] if i < len(keep) else "")
                    names_box.add_widget(f)
                    st["fields"].append(f)
            Clock.schedule_once(lambda *_: setattr(scroll, "height", min(dp(200), names_box.height)), 0)
            nt, nr = db.trial_size()
            if st["scope"] == "treatment":
                cnt = read_counts() or {t: n for t in db.trial_nums()}
                total = sum(cnt.values())
                detail = " (" + ", ".join(f"T{t}: {k}" for t, k in cnt.items()) + ")"
            else:
                total, detail = n, ""
            info.text = (f"{total} registro(s) de fenología por semana" + detail
                         + f". Las mediciones siguen en las {nt * nr} parcelas ({nt} tratamientos × {nr} repeticiones).")

        def set_scope(scope):
            st["scope"] = scope
            b_all.selected, b_trt.selected = scope == "trial", scope == "treatment"
            counts_ui()
            build()

        def n_changed(*_):
            # Cambiar «N.º de puntos» lleva a ese número a los tratamientos que lo tenían igual.
            prev = st.get("n_prev", len(old))
            for f in st["counts"].values():
                if f.text in ("", str(prev)):
                    f.text = str(max_n())
            st["n_prev"] = max_n()
            build()

        b_all.bind(on_release=lambda *_: set_scope("trial"))
        b_trt.bind(on_release=lambda *_: set_scope("treatment"))
        f_n.bind(text=n_changed)
        set_scope(st["scope"])

        def ok(_f):
            names = [f.text.strip() for f in st["fields"]] or [""]
            counts = read_counts() if st["scope"] == "treatment" else {}
            if on_cb.active and st["scope"] == "treatment" and counts and not any(counts.values()):
                a.toast("Ponga al menos un punto en algún tratamiento.")
                return False
            db.set_unified_pheno(on_cb.active, st["scope"], names, counts)
            if on_cb.active:
                n = len(db.pheno_units())
                a.toast(f"Fenología unificada: {n} registro(s) por semana")
            else:
                a.toast("Fenología por parcela: un registro por tratamiento y repetición")
            self.refresh()
            if a.home is not None:
                a.refresh_home()

        form_dialog("Fenología del ensayo", form, ok)

    def _move_to_units(self):
        a = app()
        info = a.db.parcels_to_units_summary()
        cfg = a.db.pheno_config()
        rule = ("Van al punto de la fenología del ensayo" if len(a.db.pheno_units()) == 1 else
                "Cada parcela va al punto de su tratamiento con el mismo número que su repetición "
                "(R1 → punto 1…; si hay menos puntos, al primero)" if cfg["scope"] == "treatment" else
                "Cada parcela va al punto con el número de su repetición (R1 → punto 1…; si hay "
                "menos puntos, al primero)")

        def go():
            res = a.db.move_parcels_to_units()
            a.toast(f"Pasadas {res['photos']} foto(s); estado BBCH puesto en {res['states']} registro(s)")
            self.refresh()
            if a.home is not None:
                a.refresh_home()
        confirm("Pasar fotos a la fenología unificada",
                f"{info['photos']} foto(s) de {info['records']} registro(s) por parcela "
                f"({info['weeks']} semana(s)). {rule}, en la misma semana. Si el punto no tiene "
                "estado BBCH, se le pone el más repetido de sus parcelas. Los registros por parcela "
                "conservan su estado y notas.",
                [("Pasar fotos", go)])

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
        nums = db.trial_nums()
        card.add_widget(Factory.Body(text=f"{nt} tratamientos (T{nums[0]} a T{nums[-1]}) × {nr} repeticiones "
                                          f"= {nt * nr} parcelas" if nt else "Aún sin definir"))
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
        # Fenología unificada: la fenología se registra en puntos propios (uno para todo el
        # ensayo, varios comunes o varios por tratamiento); las parcelas T×R siguen para las
        # mediciones.
        card = Factory.PaperCard()
        card.add_widget(Factory.SectionLabel(text="FENOLOGÍA DEL ENSAYO"))
        on = db.unified_pheno
        cfg = db.pheno_config()
        n = len(cfg["names"])
        labels = ", ".join(x or f"Punto {i}" for i, x in enumerate(cfg["names"], 1))
        if not on:
            state = "[b]Por parcela[/b]: el estado BBCH se registra en cada tratamiento y repetición."
        elif cfg["scope"] == "treatment":
            cnt = db.unit_counts(cfg)
            per = (f"{n} punto(s) en cada tratamiento" if len(set(cnt.values())) <= 1 else
                   "puntos por tratamiento: " + ", ".join(f"T{t} {k}" for t, k in cnt.items()))
            state = f"[b]Unificada[/b]: {per} ({labels}) = {sum(cnt.values())} registros por semana."
        elif n == 1:
            state = "[b]Unificada[/b]: un solo estado BBCH por semana para todo el ensayo."
        else:
            state = f"[b]Unificada[/b]: {n} puntos comunes a todo el ensayo ({labels})."
        card.add_widget(Factory.Body(text=state, markup=True))
        b4 = Factory.GhostButton(icon="tune-variant", text="Configurar fenología")
        b4.bind(on_release=lambda *_: self.unified_dialog())
        card.add_widget(b4)
        if on:
            info = db.parcels_to_units_summary()
            if info["photos"] or info["records"]:
                b5 = Factory.GhostButton(icon="image-move",
                                         text=f"Pasar fotos de las parcelas ({info['photos']})")
                b5.bind(on_release=lambda *_: self._move_to_units())
                card.add_widget(b5)
        card.add_widget(Factory.Muted(
            text="Unificada: la fenología se registra en puntos propios (uno para todo el ensayo, "
                 "varios comunes o varios en cada tratamiento, p. ej. caña gruesa, media y "
                 "delgada). Las mediciones siguen por tratamiento y repetición (con ANOVA). "
                 "Nada se borra al cambiar."))
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
        t0_row, t0_cb = check_row("El ensayo tiene T0 (tratamiento 0): T0 … Tn-1", a.db.trial_has_t0)
        form.add_widget(t0_row)
        form.add_widget(MDLabel(
            text="Con T0, 7 tratamientos son T0 a T6. Si reduce el número, las parcelas que sobran se archivan con sus registros "
                 "(no se borra nada); si lo vuelve a aumentar, reaparecen.",
            font_style="Caption", adaptive_height=True, theme_text_color="Custom", text_color=c(theme.MUTED)))

        def ok(_f):
            try:
                res = a.db.setup_trial(int(f_t.text or 0), int(f_r.text or 0), t0=t0_cb.active)
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


# Referencias a otras pantallas (al final: así no hay importaciones circulares).
from ui.sectors_ui import unit_dialog, year_field  # noqa: E402
