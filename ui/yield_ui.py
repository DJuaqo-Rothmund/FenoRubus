"""
ui/yield_ui.py
==============
Estimaciones de rendimiento (ver rendimiento.py), en el inicio de cada cultivo:

* `YieldHome`  — nueva estimación, las hechas (con su resultado) y el respaldo en Drive.
* `YieldSet`   — una estimación: dónde y cuándo, parámetros (peso del fruto, cuaja, parte
  fotografiada, plantas/ha), el set de fotos, el conteo total y el resultado.
* `YieldPhoto` — contar en una foto: botones − y + por estructura (desde botón floral),
  flechas para pasar a la foto anterior o siguiente, y «Contar con las cajas de IA+».

Se carga recién al entrar.
"""
from __future__ import annotations

import os

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

import rendimiento as R
from ui import theme
from ui.theme import c

ACCENT = "#2F7F92"


def app():
    return MDApp.get_running_app()


def db() -> R.YieldDB:
    return app().yields


def _num(v, d=1) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _date(iso: str) -> str:
    return "-".join(reversed((iso or "")[:10].split("-")))


KV = """
#:import c ui.theme.c
#:import theme ui.theme
<YieldScreenBase>:
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

<YieldRow>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(72)
    padding: dp(8), dp(6), dp(12), dp(6)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: c(theme.SURFACE, .8 if self.state == "normal" else .5)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(16)]
        Color:
            rgba: c("#2F7F92", .3)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(16))
            width: dp(1)
    Image:
        source: root.thumb or theme.START_YIELD
        size_hint: None, None
        size: dp(58), dp(58)
        pos_hint: {"center_y": .5}
        fit_mode: "cover" if root.thumb else "contain"
        color: (1, 1, 1, 0) if root.dot[3] else (1, 1, 1, 1)
        canvas.after:
            Color:
                rgba: root.dot
            Ellipse:
                pos: self.x + dp(10), self.y + dp(10)
                size: dp(38), dp(38)
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
            font_style: "Caption"
            adaptive_height: True
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: c(theme.MUTED)
    MDLabel:
        text: root.value
        bold: True
        halign: "right"
        size_hint_x: None
        width: dp(86)
        theme_text_color: "Custom"
        text_color: c("#2F7F92")

<CountRow>:
    size_hint_y: None
    height: dp(52)
    spacing: dp(6)
    padding: dp(10), 0, dp(4), 0
    canvas.before:
        Color:
            rgba: c(root.color, .12)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
    Widget:
        size_hint: None, None
        size: dp(12), dp(12)
        pos_hint: {"center_y": .5}
        canvas:
            Color:
                rgba: c(root.color)
            Ellipse:
                pos: self.pos
                size: self.size
    MDLabel:
        text: root.label
        bold: True
        theme_text_color: "Custom"
        text_color: c(theme.INK)
    MDIconButton:
        icon: "minus-circle-outline"
        theme_icon_color: "Custom"
        icon_color: c(root.color)
        icon_size: "30sp"
        pos_hint: {"center_y": .5}
        on_release: root.add(-1)
    MDLabel:
        text: str(root.n)
        bold: True
        halign: "center"
        font_style: "H6"
        size_hint_x: None
        width: dp(52)
        theme_text_color: "Custom"
        text_color: c(theme.INK)
    MDIconButton:
        icon: "plus-circle"
        theme_icon_color: "Custom"
        icon_color: c(root.color)
        icon_size: "34sp"
        pos_hint: {"center_y": .5}
        on_release: root.add(1)
"""


class YieldScreenBase(MDScreen):
    title = StringProperty("Estimaciones de rendimiento")

    def clear(self):
        self.ids.body.clear_widgets()
        return self.ids.body


class YieldRow(ButtonBehavior, MDBoxLayout):
    title = StringProperty()
    subtitle = StringProperty()
    value = StringProperty()
    thumb = StringProperty()
    dot = ListProperty([0, 0, 0, 0])      # color del sector (mapa de rendimiento) en vez de foto


class CountRow(MDBoxLayout):
    label = StringProperty()
    color = StringProperty("#2E7D32")
    n = NumericProperty(0)
    stage = StringProperty()

    def __init__(self, on_change=None, **kw):
        super().__init__(**kw)
        self.on_change = on_change

    def add(self, d):
        self.n = max(0, self.n + d)
        if self.on_change:
            self.on_change(self.stage, self.n)


class _Thumb(ButtonBehavior, MDBoxLayout):
    """Miniatura con el total contado encima."""

    def __init__(self, path: str, caption: str, counted: bool, **kw):
        super().__init__(orientation="vertical", size_hint=(None, None), height=dp(112), spacing=dp(2), **kw)
        self.img = Image(fit_mode="cover", size_hint_y=None, height=dp(86))
        self.add_widget(self.img)
        self.add_widget(MDLabel(text=caption, font_style="Caption", halign="center", adaptive_height=True,
                                bold=counted, theme_text_color="Custom",
                                text_color=c(ACCENT if counted else theme.MUTED)))
        app().thumb_async(path, 240, lambda t: setattr(self.img, "source", t))


def _card(title: str = ""):
    card = Factory.PaperCard()
    if title:
        card.add_widget(Factory.SectionLabel(text=title))
    return card


def _labels() -> dict:
    """Marcas de IA+ del cultivo (copia local): {nombre de foto: marcas}."""
    try:
        from ui import boxes
        return boxes.store().data["photos"]
    except Exception:  # noqa: BLE001
        return {}


def _crop_id() -> str:
    import crops
    return crops.current().id


# ============================================================================ inicio
class YieldHome(YieldScreenBase):
    def on_pre_enter(self, *_):
        self.title = "Estimaciones de rendimiento"
        # Respaldo: botoncito arriba a la izquierda (como en los demás módulos)
        self.ids.bar.left_action_items = [["arrow-left", lambda x: app().back()],
                                          [theme.DRIVE_UP, lambda x: app().yield_backup(manual=True),
                                           "Respaldar en Google Drive"]]
        db().apply_boxes(_labels())          # lo marcado en IA+ cuenta solo
        self.refresh()

    def refresh(self):
        body = self.clear()
        head = MDBoxLayout(adaptive_height=True, spacing=dp(12))
        head.add_widget(Image(source=theme.START_YIELD, size_hint=(None, None), size=(dp(84), dp(84)),
                              fit_mode="contain", mipmap=True))
        head.add_widget(Factory.Muted(
            text="Saque un set de fotos de detalle de una planta (o un tramo) y cuente en cada una los "
                 "botones, flores y frutos. Con la cuaja, el peso del fruto y las plantas por hectárea "
                 "se estima cuántos frutos y kilos habrá a fin de temporada.",
            pos_hint={"center_y": .5}))
        body.add_widget(head)
        b = Factory.PrimaryButton(text="Nueva estimación")
        b.bind(on_release=lambda *_: new_set())
        body.add_widget(b)
        b = Factory.GhostButton(icon="map-legend", text="Mapa de rendimiento del predio")
        b.bind(on_release=lambda *_: open_map())
        body.add_widget(b)
        sets = db().sets()
        if sets:
            body.add_widget(Factory.SectionLabel(text="ESTIMACIONES"))
        for s in sets:
            where = " · ".join(x for x in (s["place"], s["sector"]) if x) or "Sin lugar"
            sub = f"{s['photos']} foto(s), {s['counted']} contada(s) · {_num(s['per_plant'], 0)} frutos/planta"
            val = f"{_num(s['t_ha'], 1)} t/ha" if s["t_ha"] is not None else (
                f"{_num(s['kg_plant'], 2)} kg/pl" if s["kg_plant"] is not None else "—")
            row = YieldRow(title=f"{_date(s['taken_on'])} · {where}", subtitle=sub, value=val)
            first = db().photos(s["id"])
            if first and os.path.exists(first[0]["path"]):
                app().thumb_async(first[0]["path"], 160, lambda t, r=row: setattr(r, "thumb", t))
            row.bind(on_release=lambda *_, sid=s["id"]: open_set(sid))
            body.add_widget(row)
        if not sets:
            body.add_widget(Factory.Muted(text="Aún no hay estimaciones."))
        card = _card("RESPALDO EN GOOGLE DRIVE")
        from platform_utils import global_get
        on = bool(global_get("drive_enabled", False))
        import crops
        st = db().query_one("SELECT COUNT(*) AS n FROM drive_queue WHERE status IN ('pending', 'move')")["n"]
        card.add_widget(Factory.Body(
            text=(f"Carpeta [b]AeonCrop/{crops.current().app}/{R.DRIVE_DIR}[/b] (aparte de I+D y Predio): "
                  "una carpeta por estimación y la planilla «estimaciones.csv». " if on else
                  "Sin cuenta de Google: todo queda guardado en el teléfono hasta conectarla. ")
            + (f"{st} archivo(s) por subir (nube de arriba a la izquierda: respaldar ahora)." if st
               else "Todo respaldado." if on else ""), markup=True))
        card.add_widget(Factory.Muted(
            text="Las fotos también aparecen en IA+ (app y web) para marcarlas con cajas: lo marcado se "
                 "cuenta solo aquí y sirve para entrenar el detector que contará automáticamente."))
        body.add_widget(card)


# ============================================================================ una estimación
class YieldSet(YieldScreenBase):
    set_id = NumericProperty(0)

    def on_pre_enter(self, *_):
        self.ids.bar.right_action_items = [["delete-outline", lambda x: self._delete(), "Eliminar estimación"]]
        self.refresh()

    def refresh(self):
        d = db()
        s = d.get_set(self.set_id)
        if not s:
            return
        self.title = f"Estimación · {_date(s['taken_on'])}"
        body = self.clear()
        # Dónde y cuándo
        card = _card("DÓNDE Y CUÁNDO")
        b = Factory.GhostButton(icon="map-marker-outline",
                                text=f"{'Predio' if s['place_kind'] == 'predio' else 'Ensayo' if s['place_kind'] == 'ensayo' else 'Lugar'}: "
                                     f"{s['place']}" if s["place"] else "Ensayo o predio: (elegir)")
        b.bind(on_release=lambda *_: self._pick_place())
        card.add_widget(b)
        if s["place_kind"] in ("predio", "ensayo"):
            what = "Sector" if s["place_kind"] == "predio" else "Parcela / variedad"
            b = Factory.GhostButton(icon="vector-square", text=f"{what}: {s['sector'] or '(elegir)'}")
            b.bind(on_release=lambda *_: self._pick_sector())
            card.add_widget(b)
            if self._plan(s):
                b = Factory.GhostButton(icon="crosshairs-gps", text="Detectar el sector con mi GPS")
                b.bind(on_release=lambda *_: self._gps_sector())
                card.add_widget(b)
        b = Factory.GhostButton(icon="calendar", text=f"Fecha: {_date(s['taken_on'])}")
        b.bind(on_release=lambda *_: self._pick_date())
        card.add_widget(b)
        kind = s["kind"] or "foto"
        b = Factory.GhostButton(icon="scale-balance" if kind == "real" else "camera-outline",
                                text=f"Tipo: {R.KINDS[kind]}")
        b.bind(on_release=lambda *_: self._pick_kind())
        card.add_widget(b)
        where = ("Ubicación: " + ("GPS del teléfono" if s["loc_source"] == "gps" else "de la foto")
                 + f" ({s['latitude']:.5f}, {s['longitude']:.5f})") if s["latitude"] is not None else \
            "Ubicación: se toma de la primera foto o del GPS (para el mapa de rendimiento)."
        card.add_widget(Factory.Muted(text=where))
        body.add_widget(card)
        # Fotos
        photos = d.photos(self.set_id)
        card = _card(f"SET DE FOTOS · {len(photos)}")
        grid = GridLayout(cols=3, spacing=dp(6), size_hint_y=None, height=0)
        grid.bind(minimum_height=grid.setter("height"))
        # Cada miniatura, un tercio del ancho (con una sola foto se estiraba a todo el ancho).
        grid.bind(width=lambda g, w: [setattr(ch, "width", (w - 2 * dp(6)) / 3) for ch in g.children])
        for i, p in enumerate(photos):
            cnt = d.counts(p["id"])
            src = d.count_source(p["id"])
            cap = (f"{sum(cnt.values())} contadas" + (" · IA+" if src == "ia" else "")) if cnt else "sin contar"
            t = _Thumb(p["path"], cap, bool(cnt))
            t.bind(on_release=lambda *_, i=i: open_photo(self.set_id, i))
            grid.add_widget(t)
        card.add_widget(grid)
        from ui.photo_buttons import photo_buttons      # dos botones redondos
        card.add_widget(photo_buttons(lambda: self.add_photos("camera"), lambda: self.add_photos("gallery"),
                                      "Sacar fotos" if not photos else "Sacar más", "Galería"))
        card.add_widget(Factory.Muted(
            text="Fotos de detalle sin repetir zonas (que entre todas cubran la planta o el tramo). Toque "
                 "una foto para contar."))
        body.add_widget(card)
        # Conteo y resultado
        res = d.result(self.set_id)
        card = _card(f"CONTEO TOTAL · {res['counted']} de {res['photos']} foto(s) contadas")
        for k, name, color in R.stages(_crop_id()):
            line = MDBoxLayout(adaptive_height=True)
            line.add_widget(MDLabel(text=name, adaptive_height=True, theme_text_color="Custom", text_color=c(color),
                                    bold=True))
            line.add_widget(MDLabel(text=str(res["totals"].get(k, 0)), halign="right", adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(theme.INK)))
            card.add_widget(line)
        body.add_widget(card)
        if kind == "real":
            card = _card("CONTEO REAL (A MANO, EN ESTE MISMO PUNTO)")
            self._real = {}
            for key, hint, val in (("real_per_plant", "Frutos por planta contados", s["real_per_plant"]),
                                   ("real_kg_plant", "kg de fruta por planta (pesados, opcional)",
                                    s["real_kg_plant"])):
                f = Factory.Field(hint_text=hint, input_filter="float", text="" if val is None else f"{val:g}")
                f.bind(text=lambda w, _t, k=key: self._queue_save(k, w),
                       focus=lambda w, foc, k=key: (not foc) and self._save_field(k, w.text))
                card.add_widget(f)
            if res.get("photo_error") is not None:
                card.add_widget(Factory.Body(
                    text=f"Foto: {_num(res['per_plant'], 0)} frutos/planta · real: {_num(s['real_per_plant'], 0)} "
                         f"· la foto {'sobrestimó' if res['photo_error'] > 0 else 'subestimó'} "
                         f"{abs(res['photo_error']):.0f} %"))
            card.add_widget(Factory.Muted(
                text="Saque las fotos antes de tocar la planta; luego cuente (y si puede, pese) los frutos. "
                     "Estos puntos enseñan a la app cuánto corregir lo que ve en las fotos."))
            body.add_widget(card)
        card = _card("PARÁMETROS")
        self._fields = {}
        for key, hint, val in (("fruit_g", "Peso medio del fruto (g)", s["fruit_g"]),
                               ("fruit_set", "Cuaja de botones y flores (%)", s["fruit_set"]),
                               ("coverage", "Parte de la planta fotografiada (%)", s["coverage"]),
                               ("plants_ha", "Plantas por hectárea", s["plants_ha"])):
            f = Factory.Field(hint_text=hint, input_filter="float",
                              text="" if val is None else f"{val:g}")
            # Se guarda al escribir (en el teléfono el número llega desde el cuadro nativo de
            # Android y el campo nunca «pierde el foco»: antes no se guardaba) y al salir.
            f.bind(text=lambda w, _t, k=key: self._queue_save(k, w),
                   focus=lambda w, foc, k=key: (not foc) and self._save_field(k, w.text))
            self._fields[key] = f
            card.add_widget(f)
        card.add_widget(Factory.Muted(
            text="Cuaja: de cada 100 botones o flores, cuántos llegan a fruto. Parte fotografiada: si las "
                 "fotos cubren solo una parte de la planta (p. ej. un lado = 50 %)."))
        body.add_widget(card)
        card = _card("ESTIMACIÓN A FIN DE TEMPORADA")
        lines = [("Frutos ya cuajados (contados)", _num(res["fruits"], 0)),
                 ("Botones y flores (contados)", _num(res["flowers"], 0)),
                 ("Frutos esperados en la muestra", _num(res["sample"], 0)),
                 ("Frutos por planta", _num(res["per_plant"], 0)),
                 ("kg por planta", _num(res["kg_plant"], 2)),
                 ("Rendimiento (kg/ha)", _num(res["kg_ha"], 0)),
                 ("Rendimiento (t/ha)", _num(res["t_ha"], 1))]
        for a, v in lines:
            line = MDBoxLayout(adaptive_height=True)
            line.add_widget(Factory.Body(text=a))
            line.add_widget(MDLabel(text=v, halign="right", bold=True, adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(ACCENT)))
            card.add_widget(line)
        if res["kg_ha"] is None:
            card.add_widget(Factory.Muted(text="Indique el peso del fruto y las plantas por hectárea para ver los kilos."))
        body.add_widget(card)
        card = _card("NOTAS")
        f = Factory.Field(hint_text="Notas (opcional)", multiline=True, text=s["notes"] or "")
        f.bind(text=lambda w, t: d.update_set(self.set_id, notes=t.strip()),
               focus=lambda w, foc: (not foc) and d.update_set(self.set_id, notes=w.text.strip()))
        card.add_widget(f)
        body.add_widget(card)

    def _queue_save(self, key, field):
        ev = getattr(self, "_save_ev", None)
        if ev is not None:
            ev.cancel()
        # Mientras se escribe con el teclado de la app no se rehace la pantalla (se perdería
        # el campo); con el cuadro nativo (sin foco), sí: así el resultado se actualiza.
        self._save_ev = Clock.schedule_once(
            lambda *_: self._save_field(key, field.text, refresh=not field.focus), .7)

    def _save_field(self, key, text, refresh=True):
        try:
            val = float(text.replace(",", ".")) if text.strip() else None
        except ValueError:
            return
        if key in ("fruit_set", "coverage") and val is not None and not 0 < val <= 100:
            app().toast("Debe ser un porcentaje entre 1 y 100.")
            return
        s = db().get_set(self.set_id)
        if s is None:
            return
        changed = s[key] != val
        if changed:
            db().update_set(self.set_id, **{key: val})      # (y la próxima estimación parte igual)
        if refresh and changed:
            Clock.schedule_once(lambda *_: self.refresh(), 0)

    def _pick_kind(self):
        from ui.screens import pick_dialog

        def set_kind(k):
            db().update_set(self.set_id, kind=k)
            self.refresh()
        pick_dialog("Tipo de estimación", [
            ("Foto", "Se estima solo con las fotos", lambda: set_kind("foto")),
            ("Foto + conteo real", "Además se cuentan (y pesan) los frutos a mano en ese punto",
             lambda: set_kind("real"))])

    def _locate(self, paths, from_camera: bool):
        """Ubicación del punto (para el mapa): la de la foto o, si no trae, el GPS."""
        s = db().get_set(self.set_id)
        if not s or s["latitude"] is not None:
            return
        import geo
        for p in paths:
            g = geo.exif_gps(p)
            if g:
                db().update_set(self.set_id, latitude=g[0], longitude=g[1], loc_source="foto")
                self.refresh()
                return
        if not from_camera or getattr(self, "_loc_gps", None) is not None:
            return
        sid = self.set_id

        def done(lat, lon, acc=None):
            self._loc_gps = None
            db().update_set(sid, latitude=lat, longitude=lon, loc_source="gps")
            if self.set_id == sid:
                self.refresh()

        def fail(_msg=""):
            self._loc_gps = None

        def granted(ok):
            if not ok:
                return fail()
            try:
                self._loc_gps = geo.LocationRequest(done, fail, target=25)
                self._loc_gps.start()
            except Exception:  # noqa: BLE001
                fail()
        try:
            geo.request_location_permission(granted)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ lugar y fecha
    def _pick_place(self):
        import scout
        from platform_utils import get_base_dir
        from ui.screens import pick_dialog
        items = [(p["name"], f"{'Predio' if p['kind'] == 'predio' else 'Ensayo I+D'} · {p['code']}",
                  lambda p=p: self._set_place(p)) for p in scout.places(get_base_dir(), _crop_id())]
        items.append(("Otro lugar…", "Escribir (campo, sector, potrero…)", self._other_place))
        pick_dialog("¿Dónde?", items)

    def _set_place(self, p):
        d = db()
        d.update_set(self.set_id, place_kind=p.get("kind", ""), place=p.get("name", ""),
                     place_code=p.get("code", ""), sector="")
        d.set_setting("yield_last_place", {"place": {k: p.get(k, "") for k in ("kind", "name", "code")}, "sector": ""})
        self.refresh()
        if p.get("kind") in ("predio", "ensayo"):        # el sector se pide de inmediato
            Clock.schedule_once(lambda *_: self._pick_sector(), .25)

    # ------------------------------------------------------------ sector por GPS
    @staticmethod
    def _plan(s):
        """Plano del predio (con coordenadas) o None: solo los predios con plano cargado."""
        if not s or s["place_kind"] != "predio":
            return None
        from ui.sector_map import load_map
        plan = load_map(s["place_code"])
        return plan if plan and plan.get("geo") else None

    def _place(self, s):
        import scout
        from platform_utils import get_base_dir
        return next((p for p in scout.places(get_base_dir(), _crop_id()) if p["code"] == s["place_code"]), None)

    def _sector_from(self, lat, lon, source: str, ask: bool = True) -> bool:
        """Busca el sector del plano en (lat, lon) y lo propone. True si cayó en uno."""
        import geo
        import scout
        s = db().get_set(self.set_id)
        plan = self._plan(s)
        hit = geo.sector_at(plan, lat, lon)
        if not hit:
            if ask:
                app().toast(f"{source}: fuera de los sectores de {s['place']}. Elíjalo de la lista.")
            return False
        place = self._place(s)
        name = (scout.sector_for(place, hit["equipo"], hit["sector"]) if place else None) or hit["nombre"]
        vars_ = ", ".join(hit.get("variedades") or [])
        if not ask:
            self._set_sector(name)
            app().toast(f"Sector según {source.lower()}: {hit['nombre']}")
            return True
        from ui.screens import confirm
        confirm("¿Usar este sector?",
                f"{source}: está en {hit['nombre']}" + (f" ({vars_})" if vars_ else "") + ".",
                [("Usar", lambda: self._set_sector(name)), ("Elegir otro", self._pick_sector)])
        return True

    def _gps_sector(self):
        import geo
        a = app()
        if getattr(self, "_gps", None) is not None:
            return
        a.toast("Buscando su ubicación (GPS)…")

        def done(lat, lon, acc=None):
            self._gps = None
            if db().get_set(self.set_id)["latitude"] is None:
                db().update_set(self.set_id, latitude=lat, longitude=lon, loc_source="gps")
            self._sector_from(lat, lon, "Según su GPS")

        def fail(msg=""):
            self._gps = None
            a.toast(f"No se pudo leer el GPS{': ' + msg if msg else ''}. Elija el sector de la lista.")

        def granted(ok):
            if not ok:
                return fail("sin permiso de ubicación")
            try:
                self._gps = geo.LocationRequest(done, fail, target=20)
                self._gps.start()
            except Exception as exc:  # noqa: BLE001
                fail(str(exc))
        try:
            geo.request_location_permission(granted)
        except Exception as exc:  # noqa: BLE001
            fail(str(exc))

    def _sector_from_photos(self, paths):
        """Fotos nuevas con GPS (EXIF) y sin sector elegido: se elige solo."""
        s = db().get_set(self.set_id)
        if not s or s["sector"] or not self._plan(s):
            return
        import geo
        for p in paths:
            gps = geo.exif_gps(p)
            if gps:
                self._sector_from(gps[0], gps[1], "Ubicación de la foto", ask=False)
                return

    def _set_sector(self, name):
        d = db()
        d.update_set(self.set_id, sector=name)
        last = d.get_setting("yield_last_place") or {}
        d.set_setting("yield_last_place", dict(last, sector=name))
        self.refresh()

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
        import scout
        from platform_utils import get_base_dir
        from ui.screens import pick_dialog
        s = db().get_set(self.set_id)
        place = next((p for p in scout.places(get_base_dir(), _crop_id()) if p["code"] == s["place_code"]), None)
        names = scout.sectors(place) if place else []
        items = [(n, "", lambda n=n: self._set_sector(n)) for n in names]
        if self._plan(s):
            items.insert(0, ("Detectar con mi GPS", "Según el plano del predio", self._gps_sector))
        items.append(("Otro…", "Escribir", self._other_sector))
        pick_dialog("Sector" if s["place_kind"] == "predio" else "Parcela / variedad", items)

    def _other_sector(self):
        from ui.screens import form_dialog
        f = Factory.Field(hint_text="Sector, parcela o variedad")
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(12), 0, 0))
        form.add_widget(f)

        def ok(_f):
            self._set_sector(f.text.strip())
        form_dialog("Sector", form, ok, "LISTO")

    def _pick_date(self):
        import datetime as dt
        from ui.screens import pick_dialog
        today = dt.date.today()
        items = []
        for k in range(0, 15):
            d = today - dt.timedelta(days=k)
            label = "Hoy" if k == 0 else "Ayer" if k == 1 else _date(d.isoformat())
            items.append((label, _date(d.isoformat()) if k < 2 else "",
                          lambda d=d: (db().update_set(self.set_id, taken_on=d.isoformat()), self.refresh())))
        pick_dialog("Fecha de las fotos", items)

    # ------------------------------------------------------------------ fotos
    def add_photos(self, source: str):
        a = app()
        sid = self.set_id

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            d = db()
            s = d.get_set(sid)
            base, dest = d.photo_basename(s), d.photo_dir

            def work():
                from android_bridge import store_photo
                err = None
                for p in paths:
                    try:
                        d.add_photo(sid, store_photo(p, dest, base, max_side=2400, exact=True))
                    except Exception as exc:  # noqa: BLE001
                        err = exc
                Clock.schedule_once(lambda *_: finished(err))

            def finished(err):
                if err:
                    a.toast(f"No se pudo guardar alguna foto: {err}")
                self.refresh()
                new = [p["path"] for p in db().photos(sid)][-len(paths):]
                self._sector_from_photos(new)
                self._locate(new, source == "camera")
                a.yield_backup()
            a.workers.submit(work)

        if source == "camera":
            from ui import camera_burst          # varias seguidas, hasta «Listo»
            camera_burst.burst(done, "Estimación")
        else:
            a.media.pick_images(done)

    def _delete(self):
        from ui.screens import confirm
        n = len(db().photos(self.set_id))

        def go():
            db().delete_set(self.set_id)
            app().toast("Estimación eliminada del teléfono (en Drive quedan las fotos)")
            app().back()
        confirm("Eliminar estimación", f"Se borran del teléfono la estimación y sus {n} foto(s).",
                [("Eliminar", go)])


# ============================================================================ contar en una foto
class YieldPhoto(YieldScreenBase):
    set_id = NumericProperty(0)
    index = NumericProperty(0)

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        d = db()
        photos = d.photos(self.set_id)
        if not photos:
            app().back()
            return
        self.index = max(0, min(self.index, len(photos) - 1))
        p = photos[self.index]
        self.photo = p
        self.title = f"Foto {self.index + 1} de {len(photos)}"
        body = self.clear()
        # Foto con flechas a los lados
        stage = MDBoxLayout(size_hint_y=None, height=dp(300), spacing=dp(4))
        prev = MDIconButton(icon="chevron-left-circle", icon_size="40sp", theme_icon_color="Custom",
                            icon_color=c(theme.BERRY), pos_hint={"center_y": .5},
                            opacity=1 if self.index > 0 else 0, disabled=self.index == 0)
        prev.bind(on_release=lambda *_: self.go(-1))
        img = _Big(source=p["path"] if os.path.exists(p["path"]) else "", fit_mode="contain")
        img.bind(on_release=lambda *_: app().media.open(p["path"], "image/jpeg"))
        nxt = MDIconButton(icon="chevron-right-circle", icon_size="40sp", theme_icon_color="Custom",
                           icon_color=c(theme.BERRY), pos_hint={"center_y": .5},
                           opacity=1 if self.index < len(photos) - 1 else 0,
                           disabled=self.index >= len(photos) - 1)
        nxt.bind(on_release=lambda *_: self.go(1))
        stage.add_widget(prev)
        stage.add_widget(img)
        stage.add_widget(nxt)
        body.add_widget(stage)
        body.add_widget(Factory.Muted(text="Toque la foto para verla grande y hacer zoom.", halign="center"))
        # Contadores
        counts = d.counts(p["id"])
        src = d.count_source(p["id"])
        card = _card("CONTEO EN ESTA FOTO" + (" · desde las cajas de IA+" if src == "ia" else ""))
        for k, name, color in R.stages(_crop_id()):
            card.add_widget(CountRow(label=name, color=color, n=counts.get(k, 0), stage=k, on_change=self._changed))
        body.add_widget(card)
        rec = _labels().get(os.path.basename(p["path"]))
        got = R.counts_from_boxes(rec, [k for k, _n, _c in R.stages(_crop_id())])
        if got is not None:
            b = Factory.GhostButton(icon="vector-rectangle",
                                    text=f"Usar las cajas de IA+ ({sum(got.values())} marcadas)")
            b.bind(on_release=lambda *_: (d.set_counts(p["id"], got, "ia"), self.refresh()))
            body.add_widget(b)
        b = Factory.PrimaryButton(text="Siguiente foto" if self.index < len(photos) - 1 else "Listo")
        b.bind(on_release=lambda *_: self.go(1) if self.index < len(photos) - 1 else app().back())
        body.add_widget(b)
        b = Factory.GhostButton(icon="delete-outline", text="Quitar esta foto")
        b.bind(on_release=lambda *_: self._remove())
        body.add_widget(b)

    def _changed(self, stage, n):
        d = db()
        cur = d.counts(self.photo["id"])
        if not cur:          # primera vez: quedan en 0 las demás (la foto queda «contada»)
            for k, _n, _c in R.stages(_crop_id()):
                d.set_count(self.photo["id"], k, 0)
        d.set_count(self.photo["id"], stage, n, "manual")

    def go(self, step):
        self.index += step
        self.refresh()

    def _remove(self):
        from ui.screens import confirm

        def go():
            db().remove_photo(self.photo["id"])
            self.refresh()
        confirm("Quitar foto", "Se quita de la estimación y del teléfono (en Drive queda).", [("Quitar", go)])


# ============================================================================ mapa de rendimiento
class YieldMap(YieldScreenBase):
    """Mapa de rendimiento del predio: cada sector pintado según el rendimiento estimado
    (rojo menos → amarillo → verde más; promedio de sus estimaciones de la temporada) y los
    puntos de muestreo encima: círculo = foto, rombo = foto + conteo real."""
    code = StringProperty("")
    whole = False                 # False: esta temporada; True: todas

    def on_pre_enter(self, *_):
        self.title = "Mapa de rendimiento"
        self.refresh()

    def _places(self):
        import scout
        from platform_utils import get_base_dir
        from ui.sector_map import load_map
        out = []
        for p in scout.places(get_base_dir(), _crop_id()):
            plan = load_map(p["code"]) if p["kind"] == "predio" else None
            if plan:
                out.append((p, plan))
        return out

    def _sets(self, code):
        import phenology as ph
        import datetime as dt
        season = ph.season_of(dt.date.today())
        out = []
        for s in db().sets():
            if s["place_code"] != code:
                continue
            if not self.whole and ph.season_of(dt.date.fromisoformat(s["taken_on"])) != season:
                continue
            out.append(s)
        return out

    def refresh(self):
        from kivy.uix.anchorlayout import AnchorLayout
        from ui.screens import PillButton, sector_map_block
        body = self.clear()
        places = self._places()
        if not places:
            body.add_widget(Factory.Muted(
                text="Ningún predio de este cultivo tiene plano cargado todavía (hoy: El Amanecer)."))
            return
        if self.code not in [p["code"] for p, _ in places]:
            last = (db().get_setting("yield_last_place") or {}).get("place") or {}
            self.code = last.get("code") if last.get("code") in [p["code"] for p, _ in places] else places[0][0]["code"]
        place, plan = next((p, pl) for p, pl in places if p["code"] == self.code)
        # Predio (si hay más de uno) y temporada
        row = MDBoxLayout(adaptive_height=True, spacing=dp(6))
        for p, _pl in places if len(places) > 1 else []:
            b = PillButton(text=p["name"], size_hint=(None, None), height=dp(34), width=dp(130))
            b.selected = p["code"] == self.code
            b.bind(on_release=lambda *_, c=p["code"]: (setattr(self, "code", c), self.refresh()))
            row.add_widget(b)
        for whole, label in ((False, "Esta temporada"), (True, "Todas")):
            b = PillButton(text=label, size_hint=(None, None), height=dp(34), width=dp(128))
            b.selected = self.whole == whole
            b.bind(on_release=lambda *_, w=whole: (setattr(self, "whole", w), self.refresh()))
            row.add_widget(b)
        holder = AnchorLayout(anchor_x="center", size_hint_y=None, height=dp(38))
        row.size_hint_x = None
        row.width = sum(ch.width for ch in row.children) + row.spacing * max(0, len(row.children) - 1)
        holder.add_widget(row)
        body.add_widget(holder)
        sets = self._sets(self.code)
        layers = R.map_layers(sets, plan)
        lo, hi = layers["lo"], layers["hi"]
        card = _card(f"{place['name'].upper()} · RENDIMIENTO ESTIMADO")
        if not layers["sectors"]:
            card.add_widget(Factory.Muted(
                text="Aún no hay estimaciones con sector o ubicación en este predio. Elija el sector (o use el "
                     "GPS) al crear una estimación y aparecerá aquí."))
        self._sel = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6))
        # Parte en el plano solo (los colores se leen mejor); «Satélite» pone la imagen debajo.
        mp = sector_map_block(card, plan, {}, "", lambda sid: self._show_sector(sid, sets, plan, layers),
                              satellite=False)
        mp.fill = {sid: R.yield_color(v["t_ha"], lo, hi) for sid, v in layers["sectors"].items()}
        mp.marks = [{"x": p["x"], "y": p["y"], "kind": p["kind"]} for p in layers["points"]]
        self._map = mp
        card.add_widget(_legend(lo, hi))
        card.add_widget(self._sel)
        body.add_widget(card)
        # Resumen por sector, de más a menos
        if layers["sectors"]:
            card = _card("SECTORES, DE MÁS A MENOS")
            names = {x["id"]: x["nombre"] for x in plan["sectors"]}
            for sid, v in sorted(layers["sectors"].items(), key=lambda kv: -kv[1]["t_ha"]):
                rgb = R.yield_color(v["t_ha"], lo, hi)
                sub = f"{v['n']} estimación(es)" + (f", {v['real']} con conteo real" if v["real"] else "")
                r = YieldRow(title=names.get(sid, sid), subtitle=sub, value=f"{_num(v['t_ha'], 1)} t/ha")
                r.dot = [*rgb, 1]
                r.bind(on_release=lambda *_, sid=sid: (self._map.focus(sid), self._show_sector(sid, sets, plan, layers)))
                card.add_widget(r)
            body.add_widget(card)

    def _show_sector(self, sid, sets, plan, layers):
        box = self._sel
        box.clear_widgets()
        sec = next((x for x in plan["sectors"] if x["id"] == sid), None)
        if sec is None:
            return
        self._map.selected = sid
        v = layers["sectors"].get(sid)
        box.add_widget(Factory.SectionLabel(
            text=f"{sec['nombre'].upper()}" + (f" · {', '.join(sec.get('variedades') or [])}" if sec.get("variedades") else "")))
        if not v:
            box.add_widget(Factory.Muted(text="Sin estimaciones en este sector."))
            return
        box.add_widget(Factory.Body(text=f"Promedio: [b]{_num(v['t_ha'], 1)} t/ha[/b]", markup=True))
        ids = {p["set"] for p in layers["points"] if p["sector"] == sid}
        for s in sets:
            if s["id"] not in ids:
                continue
            t = R.best_t_ha(s)
            kind = "foto + conteo real" if s.get("kind") == "real" else "foto"
            r = YieldRow(title=f"{_date(s['taken_on'])} · {kind}",
                         subtitle=f"{s['photos']} foto(s) · {_num(s['per_plant'], 0)} frutos/planta",
                         value=f"{_num(t, 1)} t/ha" if t is not None else "—")
            r.bind(on_release=lambda *_, i=s["id"]: open_set(i))
            box.add_widget(r)


def _legend(lo, hi):
    """Barra de colores (menos → más) con los t/ha de los extremos y los símbolos."""
    from kivy.graphics import Color, Ellipse, Mesh, Rectangle
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(4), padding=(0, dp(6), 0, 0))
    bar = Widget(size_hint_y=None, height=dp(14))

    def draw(*_):
        bar.canvas.clear()
        n = 40
        with bar.canvas:
            for i in range(n):
                Color(*R.yield_color(i / (n - 1), 0, 1))
                Rectangle(pos=(bar.x + bar.width * i / n, bar.y), size=(bar.width / n + 1, bar.height))
    bar.bind(pos=draw, size=draw)
    box.add_widget(bar)
    row = MDBoxLayout(adaptive_height=True)
    row.add_widget(MDLabel(text=f"Menos{'' if lo is None else f' · {_num(lo, 1)} t/ha'}", font_style="Caption",
                           adaptive_height=True))
    row.add_widget(MDLabel(text=f"{'' if hi is None else f'{_num(hi, 1)} t/ha · '}Más", font_style="Caption",
                           halign="right", adaptive_height=True))
    box.add_widget(row)
    sym = Widget(size_hint_y=None, height=dp(22))

    def draw_sym(*_):
        sym.canvas.clear()
        x, y = sym.x + dp(8), sym.center_y
        with sym.canvas:
            Color(*c(theme.INK, .9))
            Ellipse(pos=(x - dp(6.3), y - dp(6.3)), size=(dp(12.6), dp(12.6)))
            Color(1, 1, 1, 1)
            Ellipse(pos=(x - dp(4.8), y - dp(4.8)), size=(dp(9.6), dp(9.6)))
            x2 = sym.center_x + dp(8)
            Color(*c(theme.INK, .9))
            Mesh(vertices=[x2, y + dp(8), 0, 0, x2 + dp(8), y, 0, 0, x2, y - dp(8), 0, 0, x2 - dp(8), y, 0, 0],
                 indices=[0, 1, 2, 3], mode="triangle_fan")
            Color(1, 1, 1, 1)
            Mesh(vertices=[x2, y + dp(6), 0, 0, x2 + dp(6), y, 0, 0, x2, y - dp(6), 0, 0, x2 - dp(6), y, 0, 0],
                 indices=[0, 1, 2, 3], mode="triangle_fan")
    sym.bind(pos=draw_sym, size=draw_sym)
    lab = MDBoxLayout(adaptive_height=True)
    lab.add_widget(MDLabel(text="       Foto", font_style="Caption", adaptive_height=True))
    lab.add_widget(MDLabel(text="       Foto + conteo real", font_style="Caption", adaptive_height=True))
    box.add_widget(sym)
    box.add_widget(lab)
    box.add_widget(Factory.Muted(text="Toque un sector para ver sus estimaciones. Color: promedio de t/ha del "
                                      "sector (el conteo real, si lo hay, pesa por sobre la foto)."))
    return box


class _Big(ButtonBehavior, Image):
    pass


# ============================================================================ navegación
def _screen(cls, name):
    a = app()
    if not a.sm.has_screen(name):
        a.sm.add_widget(cls(name=name))
    return a.sm.get_screen(name)


def open_map():
    _screen(YieldMap, "yield_map")
    app().go("yield_map")


def open_home():
    _screen(YieldHome, "yield")
    app().go("yield")


def new_set():
    d = db()
    last = d.get_setting("yield_last_place") or {}
    sid = d.new_set(last.get("place"), last.get("sector", ""))
    open_set(sid)


def open_set(set_id: int):
    s = _screen(YieldSet, "yield_set")
    s.set_id = set_id
    if app().sm.current == "yield_set":
        s.refresh()
    app().go("yield_set")


def open_photo(set_id: int, index: int):
    s = _screen(YieldPhoto, "yield_photo")
    s.set_id, s.index = set_id, index
    if app().sm.current == "yield_photo":
        s.refresh()
    app().go("yield_photo")


Builder.load_string(KV)
