"""
ui/scout_ui.py
==============
Pantallas de AeonScout (Plagas, Malezas, Enfermedades): ver scout.py.

* `ScoutHome`     — los tres botones, lo que falta identificar y el respaldo en Drive.
* `ScoutSection`  — nueva captura, «Por identificar» y el catálogo de la sección.
* `ScoutSpecies`  — ficha de una especie: avance por estadio (meta para la IA) y galería.
* `ScoutCapture`  — nueva captura: fotos, especie (o «No identificada»), estadio, órgano,
  abundancia, DÓNDE (cultivo, ensayo o predio, sector) y GPS.

Se carga recién al entrar (no pesa en la apertura de la app).
"""
from __future__ import annotations

import datetime as _dt
import os
import threading

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.screen import MDScreen

import scout
from platform_utils import resource_path
from ui import theme
from ui.theme import c

CROP_CODES = {"frambuesa": "FR", "arandano": "AR", "cranberry": "CR"}


def app():
    return MDApp.get_running_app()


def icon(key: str) -> str:
    return resource_path("assets", "ui", f"scout_{key}.png")


def bubble(key: str) -> str:
    return resource_path("assets", "ui", f"blob_scout_{key}.png")


def db() -> scout.ScoutDB:
    return app().scout


KV = """
#:import c ui.theme.c
#:import theme ui.theme
<SpeciesRow>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(68)
    padding: dp(8), dp(6), dp(12), dp(6)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: c(theme.SURFACE, .78 if self.state == "normal" else .5)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(16)]
        Color:
            rgba: c(root.accent, .35)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(16))
            width: dp(1)
    Image:
        source: root.thumb or root.placeholder
        size_hint: None, None
        size: dp(54), dp(54)
        pos_hint: {"center_y": .5}
        fit_mode: "cover" if root.thumb else "contain"
        opacity: 1 if root.thumb else .45
    MDBoxLayout:
        orientation: "vertical"
        pos_hint: {"center_y": .5}
        adaptive_height: True
        MDLabel:
            text: root.title
            bold: True
            adaptive_height: True
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: c(theme.INK)
        MDLabel:
            text: root.subtitle
            markup: True
            font_style: "Caption"
            adaptive_height: True
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: c(theme.MUTED)
    MDLabel:
        text: root.count
        bold: True
        halign: "right"
        size_hint_x: None
        width: dp(64)
        theme_text_color: "Custom"
        text_color: c(root.accent)

<ScoutScreenBase>:
    md_bg_color: 0, 0, 0, 0
    MDBoxLayout:
        orientation: "vertical"
        TopBar:
            id: bar
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back()]]
        ScrollView:
            do_scroll_x: False
            MDBoxLayout:
                id: body
                orientation: "vertical"
                adaptive_height: True
                padding: dp(14), dp(10), dp(14), dp(28)
                spacing: dp(10)
"""


class SpeciesRow(ButtonBehavior, MDBoxLayout):
    title = StringProperty()
    subtitle = StringProperty()
    count = StringProperty()
    thumb = StringProperty()
    placeholder = StringProperty()
    accent = StringProperty("#2E6B34")


class ScoutScreenBase(MDScreen):
    title = StringProperty("AeonScout")

    def clear(self):
        self.ids.body.clear_widgets()
        return self.ids.body

    def gap(self, h=8):
        self.ids.body.add_widget(Widget(size_hint_y=None, height=dp(h)))


def _card(title: str = ""):
    card = Factory.PaperCard()
    if title:
        card.add_widget(Factory.SectionLabel(text=title))
    return card


def _last_photo(species_id: int) -> str:
    row = db().query_one("SELECT p.path FROM scout_photos p JOIN scout_records r ON r.id = p.record_id "
                         "WHERE r.species_id=? ORDER BY p.id DESC LIMIT 1", (species_id,))
    return row["path"] if row and os.path.exists(row["path"]) else ""


def _set_thumb(widget, path: str, size: int = 160):
    if path:
        app().thumb_async(path, size, lambda t: setattr(widget, "thumb", t))


# ============================================================================ inicio
class ScoutHome(ScoutScreenBase):
    def on_pre_enter(self, *_):
        self.title = "AeonScout"
        self.refresh()

    def refresh(self):
        body = self.clear()
        head = MDBoxLayout(adaptive_height=True, spacing=dp(12))
        head.add_widget(Image(source=theme.SCOUT_LOGO, size_hint=(None, None), size=(dp(84), dp(84)),
                              fit_mode="contain", mipmap=True))
        head.add_widget(Factory.Muted(
            text="Banco de imágenes del campo: saque fotos de plagas, malezas y enfermedades en sus "
                 "distintos estadios. Si no sabe qué es, guárdela como «No identificada» y la "
                 "identifica después. Con esto se entrenará la IA que las reconozca.",
            pos_hint={"center_y": .5}))
        body.add_widget(head)
        counts = db().counts()
        row = MDBoxLayout(adaptive_height=True)
        for key, (name, _f, _code, color) in scout.SECTIONS.items():
            holder = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(2))
            anchor = AnchorLayout(size_hint_y=None, height=dp(132))
            b = Factory.StartIcon(source=icon(key), bubble=bubble(key), label=name, color=c(color),
                                  diameter=dp(80))
            b.bind(on_release=lambda *_, k=key: open_section(k))
            anchor.add_widget(b)
            holder.add_widget(anchor)
            n = counts[key]
            holder.add_widget(MDLabel(
                text=f"{n['photos']} foto(s)" + (f"\n{n['pending']} por identificar" if n["pending"] else ""),
                halign="center", font_style="Caption", adaptive_height=True,
                theme_text_color="Custom", text_color=c(theme.MUTED)))
            row.add_widget(holder)
        body.add_widget(row)
        self.gap(4)
        pending = [(k, n["pending"]) for k, n in counts.items() if n["pending"]]
        if pending:
            card = _card("POR IDENTIFICAR")
            for key, n in pending:
                b = Factory.GhostButton(icon="help-circle-outline",
                                        text=f"{scout.SECTIONS[key][0]}: {n} sin identificar")
                b.bind(on_release=lambda *_, k=key: open_section(k))
                card.add_widget(b)
            body.add_widget(card)
        card = _card("RESPALDO EN GOOGLE DRIVE")
        from platform_utils import global_get
        on = bool(global_get("drive_enabled", False))
        st = db().query_one("SELECT COUNT(*) AS n FROM drive_queue WHERE status IN ('pending', 'move')")["n"]
        card.add_widget(Factory.Body(
            text=("Carpeta [b]AeonCrop/AeonScout[/b] › Plagas, Malezas y Enfermedades (una carpeta por "
                  "especie y estadio) y la planilla «registro.csv». " if on else
                  "Sin cuenta de Google: todo queda guardado en el teléfono hasta conectarla "
                  "(pantalla principal). ")
            + (f"{st} archivo(s) por subir (nube de arriba a la izquierda: respaldar ahora)." if st
               else "Todo respaldado." if on else ""), markup=True))
        body.add_widget(card)
        # Respaldo: botoncito arriba a la izquierda (como en los demás módulos)
        self.ids.bar.left_action_items = [["arrow-left", lambda x: app().back()],
                                          [theme.DRIVE_UP, lambda x: app().scout_backup(manual=True),
                                           "Respaldar en Google Drive"]]


# ============================================================================ sección
class ScoutSection(ScoutScreenBase):
    section = StringProperty("malezas")

    def on_pre_enter(self, *_):
        self.title = scout.SECTIONS[self.section][0]
        self.ids.bar.right_action_items = [["plus", lambda x: add_species_dialog(self.section, self.refresh),
                                            "Agregar especie"]]
        self.refresh()

    def refresh(self):
        body = self.clear()
        sec = self.section
        color = scout.SECTIONS[sec][3]
        from ui.photo_buttons import photo_buttons      # nueva captura: cámara o galería
        body.add_widget(photo_buttons(lambda: open_capture(sec), lambda: open_capture(sec, source="gallery"),
                                      "Nueva captura", "Desde la galería"))
        unknown = [s for s in db().species(sec, unidentified=True) if s["records"]]
        if unknown:
            body.add_widget(Factory.SectionLabel(text="POR IDENTIFICAR"))
            for s in unknown:
                body.add_widget(self._row(s, color))
        body.add_widget(Factory.SectionLabel(text="CATÁLOGO · tocar para ver sus fotos"))
        for s in db().species(sec, unidentified=False):
            body.add_widget(self._row(s, color))
        body.add_widget(Factory.Muted(
            text="Las especies con más fotos van primero. «+» arriba agrega una especie al catálogo."))

    def _row(self, s: dict, color: str):
        sub = f"[i]{s['scientific']}[/i]" if s["scientific"] else ""
        if s["kind"] == "benefico":
            sub = ("Benéfico · " + sub) if sub else "Benéfico"
        if s["unidentified"]:
            sub = f"{s['records']} captura(s) · tocar para identificar"
        w = SpeciesRow(title=s["name"], subtitle=sub, count=f"{s['photos']} fotos" if s["photos"] else "—",
                       placeholder=icon(self.section), accent=color)
        _set_thumb(w, _last_photo(s["id"]))
        w.bind(on_release=lambda *_, sid=s["id"]: open_species(sid))
        return w


# ============================================================================ especie
class ScoutSpecies(ScoutScreenBase):
    species_id = NumericProperty(0)

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        sp = db().get_species(self.species_id)
        if not sp:
            return
        self.title = sp["name"]
        sec = sp["section"]
        color = scout.SECTIONS[sec][3]
        body = self.clear()
        card = _card()
        info = [f"[i]{sp['scientific']}[/i]" if sp["scientific"] else "",
                "Benéfico" if sp["kind"] == "benefico" else "",
                scout.SECTIONS[sec][0]]
        card.add_widget(Factory.Body(text=" · ".join(x for x in info if x), markup=True))
        if sp["notes"]:
            card.add_widget(Factory.Muted(text=sp["notes"]))
        b = Factory.PrimaryButton(text="Nueva captura de esta especie")
        b.bind(on_release=lambda *_: open_capture(sec, species_id=sp["id"]))
        card.add_widget(b)
        if sp["unidentified"]:
            b = Factory.GhostButton(icon="tag-search-outline", text="Identificar (ya sé qué es)")
            b.bind(on_release=lambda *_: identify_dialog(sp, self._identified))
        else:
            b = Factory.GhostButton(icon="pencil-outline", text="Editar ficha")
            b.bind(on_release=lambda *_: edit_species_dialog(sp, self.refresh))
        card.add_widget(b)
        body.add_widget(card)
        stages = db().stage_counts(sp["id"])
        card = _card(f"AVANCE PARA LA IA · meta {scout.GOAL} fotos por estadio")
        for st in scout.STAGES[sec]:
            n = stages.get(st, 0)
            line = MDBoxLayout(adaptive_height=True, spacing=dp(8))
            line.add_widget(MDLabel(text=st, font_style="Caption", adaptive_height=True, size_hint_x=.48,
                                    theme_text_color="Custom", text_color=c(theme.INK)))
            bar = MDProgressBar(max=scout.GOAL, value=min(n, scout.GOAL), color=c(color),
                                back_color=c(color, .15), size_hint=(.36, None), height=dp(6),
                                pos_hint={"center_y": .5})
            line.add_widget(bar)
            line.add_widget(MDLabel(text=str(n), font_style="Caption", halign="right", adaptive_height=True,
                                    size_hint_x=.16, theme_text_color="Custom", text_color=c(theme.MUTED)))
            card.add_widget(line)
        body.add_widget(card)
        recs = db().records(sp["id"])
        if not recs:
            body.add_widget(Factory.Muted(text="Aún sin fotos de esta especie."))
        for r in recs:
            body.add_widget(self._record(r))

    def _record(self, r: dict):
        import crops
        card = _card()
        when = r["taken_at"][:10].split("-")
        crop = crops.CROPS[r["crop"]].name if r["crop"] in crops.CROPS else r["crop"]
        where = " · ".join(x for x in (crop, r["place"], r["sector"]) if x)
        head = MDBoxLayout(adaptive_height=True)
        head.add_widget(Factory.Body(
            text=f"[b]{'-'.join(reversed(when))}[/b] · {r['stage'] or 'sin estadio'}"
                 + (f" · {r['organ']}" if r["organ"] else "") + (f" · {r['abundance']}" if r["abundance"] else ""),
            markup=True))
        from kivymd.uix.button import MDIconButton
        rm = MDIconButton(icon="delete-outline", theme_icon_color="Custom", icon_color=c(theme.BERRY),
                          pos_hint={"center_y": .5})
        rm.bind(on_release=lambda *_: self._delete(r))
        head.add_widget(rm)
        card.add_widget(head)
        if where:
            card.add_widget(Factory.Muted(text=where))
        if r["notes"]:
            card.add_widget(Factory.Muted(text=r["notes"]))
        grid = GridLayout(cols=4, spacing=dp(6), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for p in r["photos"]:
            t = _Thumb(size_hint=(1, None), height=dp(78))
            _set_thumb(t, p["path"], 240)
            t.bind(on_release=lambda *_, path=p["path"]: app().media.open(path, "image/jpeg"))
            grid.add_widget(t)
        card.add_widget(grid)
        return card

    def _delete(self, r):
        from ui.screens import confirm

        def go():
            db().delete_record(r["id"])
            app().toast("Captura eliminada del teléfono (en Drive queda)")
            self.refresh()
        confirm("Eliminar captura", f"Se borran del teléfono sus {len(r['photos'])} foto(s).",
                [("Eliminar", go)])

    def _identified(self, species_id: int):
        self.species_id = species_id
        self.refresh()
        app().scout_backup()


class _Thumb(ButtonBehavior, Image):
    thumb = StringProperty()

    def on_thumb(self, *_):
        self.source = self.thumb
        self.fit_mode = "cover"


# ============================================================================ captura
class ScoutCapture(ScoutScreenBase):
    """Nueva captura. Lo último usado (cultivo, lugar, sector, estadio) queda elegido."""
    section = StringProperty("malezas")

    def start(self, section: str, species_id: int | None = None, source: str = "camera"):
        self.section = section
        last = db().get_setting(f"scout_last_{section}") or {}
        from platform_utils import global_get
        self.st = {
            "species": species_id, "stage": last.get("stage", ""), "organ": last.get("organ", ""),
            "abundance": "", "crop": last.get("crop") or global_get("crop", "frambuesa"),
            "place": last.get("place"), "sector": last.get("sector", ""), "photos": [],
            "lat": None, "lon": None, "acc": None, "view": "",
        }
        if species_id:
            self.st["view"] = db().missing_view(section, species_id) or ""
        self.title = f"Nueva captura · {scout.SECTIONS[section][0]}"
        self._first = source

    def on_pre_enter(self, *_):
        self.refresh()

    def on_enter(self, *_):
        self._start_gps()
        if getattr(self, "_first", None):
            src, self._first = self._first, None
            Clock.schedule_once(lambda *_: self.add_photos(src), .2)

    def on_leave(self, *_):
        gps = getattr(self, "_gps", None)
        if gps is not None:
            try:
                gps.cancel()
            except Exception:  # noqa: BLE001
                pass
            self._gps = None

    # ------------------------------------------------------------------ GPS
    def _start_gps(self):
        import geo
        st = self.st

        def done(lat, lon, acc=None):
            st["lat"], st["lon"], st["acc"] = lat, lon, acc
            self._gps_label()

        def fail(_msg=""):
            self._gps_label()

        def granted(ok):
            if not ok:
                return fail()
            try:
                self._gps = geo.LocationRequest(done, fail, lambda la, lo, ac: done(la, lo, ac), target=15)
                self._gps.start()
            except Exception:  # noqa: BLE001 (sin GPS: se usa el de la foto, si trae)
                fail()
        try:
            geo.request_location_permission(granted)
        except Exception:  # noqa: BLE001
            pass

    def _gps_label(self):
        lbl = getattr(self, "_gps_lbl", None)
        if lbl is None:
            return
        st = self.st
        lbl.text = (f"GPS: {st['lat']:.5f}, {st['lon']:.5f}" + (f" (±{st['acc']:.0f} m)" if st["acc"] else "")
                    if st["lat"] is not None else "GPS: buscando… (si no hay, se usa el de la foto)")

    # ------------------------------------------------------------------ formulario
    def refresh(self):
        import crops
        st, sec = self.st, self.section
        body = self.clear()
        # Fotos
        card = _card("FOTOS DEL INDIVIDUO")
        grid = GridLayout(cols=4, spacing=dp(6), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for i, (path, view, _o) in enumerate(st["photos"]):
            t = _Thumb(size_hint=(1, None), height=dp(78))
            _set_thumb(t, path, 240)
            t.bind(on_release=lambda *_, i=i: self._photo_menu(i))
            grid.add_widget(t)
        card.add_widget(grid)
        from ui.photo_buttons import photo_buttons      # dos botones redondos
        card.add_widget(photo_buttons(lambda: self.add_photos("camera"), lambda: self.add_photos("gallery"),
                                      "Sacar fotos" if not st["photos"] else "Sacar más", "Galería"))
        views = scout.VIEWS.get(sec, [])
        if views:
            b = Factory.GhostButton(icon="camera-iris",
                                    text=f"Vista de la próxima foto: {st['view'] or 'sin indicar'}")
            b.bind(on_release=lambda *_: self._pick("Vista de la próxima foto",
                                                    [("Sin indicar", "")] + [(v, v) for v in views], "view"))
            card.add_widget(b)
            card.add_widget(Factory.Muted(
                text="Para la IA sirven varias vistas del mismo individuo ("
                     + ", ".join(v.lower() for v in views) + ") y, si puede, una moneda o regla al lado."))
        body.add_widget(card)
        # Qué es
        card = _card("QUÉ ES")
        sp = db().get_species(st["species"]) if st["species"] else None
        b = Factory.GhostButton(icon="tag-outline",
                                text=f"Especie: {sp['name']}" if sp else "Especie: No identificada (nueva)")
        b.bind(on_release=lambda *_: self._pick_species())
        card.add_widget(b)
        b = Factory.GhostButton(icon="progress-clock", text=f"Estadio: {st['stage'] or '(elegir)'}")
        b.bind(on_release=lambda *_: self._pick("Estadio", [(s, s) for s in scout.STAGES[sec]], "stage"))
        card.add_widget(b)
        row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
        b = Factory.GhostButton(icon="leaf", text=f"Órgano: {st['organ'] or '—'}", size_hint_x=.5)
        b.bind(on_release=lambda *_: self._pick("Órgano", [("Sin indicar", "")] + [(o, o) for o in scout.ORGANS],
                                                "organ"))
        row.add_widget(b)
        b = Factory.GhostButton(icon="chart-bar", text=f"Abundancia: {st['abundance'] or '—'}", size_hint_x=.5)
        b.bind(on_release=lambda *_: self._pick("Abundancia",
                                                [("Sin indicar", "")] + [(x, x) for x in scout.ABUNDANCE],
                                                "abundance"))
        row.add_widget(b)
        card.add_widget(row)
        body.add_widget(card)
        # Dónde
        card = _card("DÓNDE")
        crop_name = crops.CROPS[st["crop"]].name if st["crop"] in crops.CROPS else (st["crop"] or "—")
        b = Factory.GhostButton(icon="sprout-outline", text=f"Cultivo: {crop_name}")
        b.bind(on_release=lambda *_: self._pick_crop())
        card.add_widget(b)
        pl = st["place"]
        b = Factory.GhostButton(icon="map-marker-outline",
                                text=(f"{'Predio' if pl['kind'] == 'predio' else 'Ensayo' if pl['kind'] == 'ensayo' else 'Lugar'}: "
                                      f"{pl['name']}") if pl else "Ensayo o predio: (elegir)")
        b.bind(on_release=lambda *_: self._pick_place())
        card.add_widget(b)
        if pl and pl.get("kind") in ("predio", "ensayo"):
            what = "Sector" if pl["kind"] == "predio" else "Parcela / variedad"
            b = Factory.GhostButton(icon="vector-square", text=f"{what}: {st['sector'] or 'todo'}")
            b.bind(on_release=lambda *_: self._pick_sector())
            card.add_widget(b)
        self._gps_lbl = Factory.Muted(text="")
        card.add_widget(self._gps_lbl)
        self._gps_label()
        body.add_widget(card)
        # Notas y guardar
        card = _card("NOTAS")
        self._notes = Factory.Field(hint_text="Notas (opcional)", multiline=True,
                                    text=getattr(self, "_notes_text", ""))
        self._notes.bind(text=lambda w, t: setattr(self, "_notes_text", t))
        card.add_widget(self._notes)
        body.add_widget(card)
        b = Factory.PrimaryButton(text="Guardar captura")
        b.bind(on_release=lambda *_: self.save())
        body.add_widget(b)

    # ------------------------------------------------------------------ elecciones
    def _set(self, key, value):
        self.st[key] = value
        self.refresh()

    def _pick(self, title, options, key):
        from ui.screens import pick_dialog
        pick_dialog(title, [(label, "Elegido" if self.st.get(key) == val and val else "",
                             lambda v=val: self._set(key, v)) for label, val in options])

    def _pick_species(self):
        from ui.screens import pick_dialog
        sec = self.section
        items = [("No identificada (nueva)", "Recibe un código NI-…; la identifica después",
                  lambda: self._set_species(None))]
        for s in db().species(sec, unidentified=True):
            if s["records"]:
                items.append((s["name"], f"No identificada · {s['photos']} foto(s): sumar a esta",
                              lambda sid=s["id"]: self._set_species(sid)))
        for s in sorted(db().species(sec, unidentified=False), key=lambda s: s["name"].lower()):
            items.append((s["name"], s["scientific"] or "", lambda sid=s["id"]: self._set_species(sid)))
        items.append(("+ Nueva especie…", "Agregarla al catálogo",
                      lambda: add_species_dialog(sec, None, on_added=self._set_species)))
        pick_dialog("¿Qué es?", items)

    def _set_species(self, sid):
        self.st["species"] = sid
        if sid:
            self.st["view"] = db().missing_view(self.section, sid) or self.st["view"]
        self.refresh()

    def _pick_crop(self):
        import crops
        from ui.screens import pick_dialog
        items = [(cr.name, cr.app, lambda cid=cid: self._set_crop(cid)) for cid, cr in crops.CROPS.items()]
        items.append(("Otro cultivo…", "Escribir el nombre", self._other_crop))
        pick_dialog("Cultivo", items)

    def _set_crop(self, cid):
        if cid != self.st["crop"]:
            self.st["place"], self.st["sector"] = None, ""
        self._set("crop", cid)

    def _other_crop(self):
        from ui.screens import form_dialog
        f = Factory.Field(hint_text="Cultivo (ej.: Frutilla)")
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(12), 0, 0))
        form.add_widget(f)

        def ok(_f):
            if f.text.strip():
                self._set_crop(f.text.strip())
        form_dialog("Otro cultivo", form, ok, "LISTO")

    def _pick_place(self):
        from platform_utils import get_base_dir
        from ui.screens import pick_dialog
        items = []
        for p in scout.places(get_base_dir(), self.st["crop"]) if self.st["crop"] in CROP_CODES else []:
            items.append((p["name"], f"{'Predio' if p['kind'] == 'predio' else 'Ensayo I+D'} · {p['code']}",
                          lambda p=p: self._set_place(p)))
        items.append(("Otro lugar…", "Escribir (campo, sector, potrero…)", self._other_place))
        items.append(("Sin especificar", "", lambda: self._set_place(None)))
        pick_dialog("¿Dónde?", items)

    def _set_place(self, p):
        self.st["sector"] = ""
        self._set("place", p)

    def _other_place(self):
        from ui.screens import form_dialog
        f = Factory.Field(hint_text="Lugar (ej.: Campo norte, potrero 3)")
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(12), 0, 0))
        form.add_widget(f)

        def ok(_f):
            if f.text.strip():
                self._set_place({"kind": "otro", "name": f.text.strip(), "code": ""})
        form_dialog("Otro lugar", form, ok, "LISTO")

    def _pick_sector(self):
        from ui.screens import pick_dialog
        pl = self.st["place"]
        names = scout.sectors(pl)
        items = [("Todo el " + ("predio" if pl["kind"] == "predio" else "ensayo"), "", lambda: self._set("sector", ""))]
        items += [(n, "", lambda n=n: self._set("sector", n)) for n in names]
        pick_dialog("Sector" if pl["kind"] == "predio" else "Parcela / variedad", items)

    # ------------------------------------------------------------------ fotos
    def add_photos(self, source: str):
        a = app()

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            for p in paths:
                self.st["photos"].append((p, self.st["view"], origin))
            # Siguiente vista sugerida (la que viene en la lista).
            views = scout.VIEWS.get(self.section, [])
            if self.st["view"] in views and source == "camera":
                i = views.index(self.st["view"])
                self.st["view"] = views[(i + 1) % len(views)]
            self.refresh()

        if source == "camera":
            from ui import camera_burst          # varias seguidas, hasta «Listo»
            camera_burst.burst(done, "AeonScout", title="AeonScout")
        else:
            a.media.pick_images(done)

    def _photo_menu(self, i):
        from ui.screens import pick_dialog
        path, view, origin = self.st["photos"][i]

        def remove():
            self.st["photos"].pop(i)
            self.refresh()

        def set_view(v):
            self.st["photos"][i] = (path, v, origin)
            self.refresh()
        items = [("Ver", "", lambda: app().media.open(path, "image/jpeg")),
                 ("Quitar de la captura", "", remove)]
        items += [(f"Vista: {v}", "Elegida" if v == view else "", lambda v=v: set_view(v))
                  for v in scout.VIEWS.get(self.section, [])]
        pick_dialog("Foto", items)

    # ------------------------------------------------------------------ guardar
    def save(self):
        a = app()
        st, sec = self.st, self.section
        if not st["photos"]:
            a.toast("Saque al menos una foto.")
            return
        notes = getattr(self, "_notes_text", "")
        pl = st["place"] or {}
        d = db()
        species = st["species"] or d.new_unidentified(sec)
        lat, lon = st["lat"], st["lon"]
        if lat is None:
            import geo
            for path, _v, _o in st["photos"]:
                gps = geo.exif_gps(path)
                if gps:
                    lat, lon = gps
                    break
        rec = d.add_record(sec, species, stage=st["stage"], organ=st["organ"], abundance=st["abundance"],
                           crop=st["crop"] or "", place_kind=pl.get("kind", ""), place=pl.get("name", ""),
                           place_code=pl.get("code", ""), sector=st["sector"], notes=notes,
                           latitude=lat, longitude=lon)
        d.set_setting(f"scout_last_{sec}", {"stage": st["stage"], "organ": st["organ"], "crop": st["crop"],
                                            "place": st["place"], "sector": st["sector"]})
        photos = list(st["photos"])
        record = d.get_record(rec)
        base = d.photo_basename(record, CROP_CODES.get(st["crop"], ""))
        dest = d.photo_dir(sec)
        name = d.get_species(species)["name"]
        a.toast(f"Guardando {len(photos)} foto(s) · {name}…")

        def work():
            from android_bridge import store_photo
            err = None
            for path, view, _o in photos:
                try:
                    stored = store_photo(path, dest, base, exact=True)
                    d.add_photo(rec, stored, view=view)
                except Exception as exc:  # noqa: BLE001
                    err = exc
            Clock.schedule_once(lambda *_: finished(err))

        def finished(err):
            if err:
                a.toast(f"No se pudo guardar alguna foto: {err}")
            else:
                a.toast(f"Captura guardada: {name}" + (" (identifíquela después)" if not st["species"] else ""))
            a.scout_backup()
            self._notes_text = ""
            a.back()

        a.workers.submit(work)


# ============================================================================ diálogos
def add_species_dialog(section: str, on_done=None, on_added=None):
    from ui.screens import check_row, form_dialog
    a = app()
    form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8), padding=(0, dp(12), 0, 0))
    f_n = Factory.Field(hint_text="Nombre común (ej.: Hierba azul)")
    f_s = Factory.Field(hint_text="Nombre científico (opcional)")
    form.add_widget(f_n)
    form.add_widget(f_s)
    ben = None
    if section == "plagas":
        row, ben = check_row("Es benéfico (no es plaga)")
        form.add_widget(row)

    def ok(_f):
        try:
            sid = db().add_species(section, f_n.text, f_s.text,
                                   kind=("benefico" if ben and ben.active else "plaga") if section == "plagas" else "")
        except ValueError as exc:
            a.toast(str(exc))
            return False
        a.toast(f"«{f_n.text.strip()}» agregada al catálogo")
        if on_added:
            on_added(sid)
        if on_done:
            on_done()
    form_dialog(f"Nueva especie · {scout.SECTIONS[section][0]}", form, ok, "AGREGAR")


def edit_species_dialog(sp: dict, on_done=None):
    from ui.screens import check_row, form_dialog
    form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8), padding=(0, dp(12), 0, 0))
    f_s = Factory.Field(hint_text="Nombre científico", text=sp["scientific"] or "")
    f_n = Factory.Field(hint_text="Notas (cómo reconocerla, época…)", text=sp["notes"] or "", multiline=True)
    form.add_widget(f_s)
    form.add_widget(f_n)
    ben = None
    if sp["section"] == "plagas":
        row, ben = check_row("Es benéfico (no es plaga)", sp["kind"] == "benefico")
        form.add_widget(row)

    def ok(_f):
        db().update_species(sp["id"], scientific=f_s.text, notes=f_n.text,
                            kind=("benefico" if ben.active else "plaga") if ben else None)
        if on_done:
            on_done()
    form_dialog(sp["name"], form, ok)


def identify_dialog(ni: dict, on_done):
    from ui.screens import confirm, pick_dialog
    sec = ni["section"]

    def go(sid):
        sp = db().get_species(sid)

        def run():
            res = db().identify(ni["id"], sid)
            app().toast(f"{ni['name']} es {sp['name']}: {res['photos']} foto(s) pasan a su carpeta")
            on_done(sid)
        confirm("Identificar", f"{ni['name']} pasa a ser «{sp['name']}» con todas sus fotos (también en "
                               "Drive, donde se mueven a la carpeta de la especie).", [("Identificar", run)])

    items = [(s["name"], s["scientific"] or "", lambda sid=s["id"]: go(sid))
             for s in sorted(db().species(sec, unidentified=False), key=lambda s: s["name"].lower())]
    items.insert(0, ("+ Nueva especie…", "Agregarla al catálogo y asignarla",
                     lambda: add_species_dialog(sec, on_added=go)))
    pick_dialog(f"¿Qué es {ni['name']}?", items)


# ============================================================================ navegación
def _screen(cls, name):
    a = app()
    if not a.sm.has_screen(name):
        a.sm.add_widget(cls(name=name))
    return a.sm.get_screen(name)


def open_home():
    _screen(ScoutHome, "scout")
    app().go("scout")


def open_section(section: str):
    s = _screen(ScoutSection, "scout_section")
    s.section = section
    if app().sm.current == "scout_section":
        s.on_pre_enter()
    app().go("scout_section")


def open_species(species_id: int):
    s = _screen(ScoutSpecies, "scout_species")
    s.species_id = species_id
    if app().sm.current == "scout_species":
        s.refresh()
    app().go("scout_species")


def open_capture(section: str, species_id: int | None = None, source: str = "camera"):
    s = _screen(ScoutCapture, "scout_capture")
    s._notes_text = ""
    s.start(section, species_id, source)
    app().go("scout_capture")


Builder.load_string(KV)
