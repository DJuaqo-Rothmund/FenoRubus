"""
ui/sectors_ui.py
================
Sectores y unidades del predio (mapa, lista, unidades).
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.screen import MDScreen
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import (DIALOG_BG, GlassButton, PillButton, app, confirm, fast_clear, form_dialog,
    remember_variety)


class SectorRow(GlassButton):
    variety_id = NumericProperty(0)
    badge = StringProperty()
    title = StringProperty()
    subtitle = StringProperty()
    done = BooleanProperty(False)
    screen = ObjectProperty(None, allownone=True)


def sector_map_block(box, plan, status, selected, on_select, satellite=None):
    """Plano del predio con los equipos de riego arriba, centrados: son la leyenda de
    colores y, al tocarlos, acercan el equipo entero en el mismo plano (ahí se toca el
    sector); tocar de nuevo el equipo elegido vuelve a la vista general. Devuelve el plano."""
    from kivy.uix.anchorlayout import AnchorLayout
    from ui.sector_map import SectorMap, equipo_chip
    equipos = sorted({s["equipo"] for s in plan["sectors"]})
    from ui.mapview import default_layer, remember_layer
    mp = SectorMap(plan, on_select=on_select, size_hint_y=None, height=dp(200), zoomable=True)
    mp.status, mp.selected = status, selected
    mp.satellite = bool(plan.get("geo")) and (default_layer() == "sat" if satellite is None else satellite)
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


# Referencias a otras pantallas (al final: así no hay importaciones circulares).
from ui.varieties_ui import VarietyForm  # noqa: E402
