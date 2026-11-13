"""
ui/observation.py
=================
Registro de una observación: fotos general/detalle, BBCH, notas.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
import os
import perf
import threading
from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivymd.uix.button import MDRectangleFlatButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import phenology as ph
from android_bridge import store_photo
from platform_utils import data_subdir
from ui import theme
from ui.theme import c
from ui.common import (GlassButton, GlassCard, _crop, app, bbch_dialog, confirm, fast_clear,
    form_dialog, thumb_widget)


# ===========================================================================
# Registro fenológico (variedad × semana)
# ===========================================================================
class StripThumb(GlassButton):
    primary = BooleanProperty(False)
    photo_id = NumericProperty(0)


class PhotoSlot(GlassCard):
    kind = StringProperty()
    caption = StringProperty()
    meta = StringProperty("Sin foto")
    has_photo = BooleanProperty(False)
    count = NumericProperty(0)
    screen = ObjectProperty()

    def show_busy(self, text: str = "Procesando foto…"):
        from kivymd.uix.spinner import MDSpinner
        box = self.ids.image_box
        fast_clear(box)
        box.add_widget(MDSpinner(size_hint=(None, None), size=(dp(32), dp(32)),
                                 pos_hint={"center_x": .5, "center_y": .5},
                                 color=c(theme.BERRY)))
        self.meta = text

    def show(self, photos: list[dict]):
        """photos: todas las fotos de este tipo, la principal primero."""
        box, strip = self.ids.image_box, self.ids.strip
        fast_clear(box)
        fast_clear(strip)
        self.count = len(photos)
        self.has_photo = bool(photos)
        if not photos:
            box.add_widget(thumb_widget(None, icon="camera-plus-outline"))
            self.meta = "Sin foto · la cámara suma una foto por toma"
            return
        main = photos[0]
        box.add_widget(thumb_widget(main["path"], 640))
        origin = {"camera": "cámara", "gallery": "galería"}.get(main["source"], main["source"])
        self.meta = (f"Principal: {origin} · {main['captured_at'][11:16]}"
                     + (" · toque una miniatura para cambiarla" if len(photos) > 1 else ""))
        if len(photos) > 1:
            for ph_ in photos:
                t = StripThumb(primary=bool(ph_["is_primary"]), photo_id=ph_["id"])
                t.add_widget(thumb_widget(ph_["path"], 160))
                t.bind(on_release=lambda w: self.screen.make_primary(self.kind, w.photo_id))
                strip.add_widget(t)


class ObservationScreen(MDScreen):
    variety_id = NumericProperty(0)
    week_id = NumericProperty(0)
    suggestion = ObjectProperty(None, allownone=True)

    @perf.timed("registro.cargar")
    def load(self, variety_id: int, week_id: int):
        a = app()
        self.variety_id, self.week_id = variety_id, week_id
        self.variety = a.db.get_variety(variety_id)
        self.week = a.db.get_week(week_id)
        self.obs = a.db.get_or_create_observation(variety_id, week_id)
        self.ids.bar.title = (a.db.display_name(self.variety) if a.db.is_trial
                              else ph.unit_main(self.variety))
        where = ph.unit_place(self.variety)       # predio: equipo y sector, en la línea de abajo
        self.ids.week_caption.text = (f"{where} · " if where else "") + \
            f"{ph.week_title(self.week)} · {self.week['label']}"
        self._refresh_slot("canopy")
        self._refresh_slot("detail")
        self.load_attachments()
        self.ids.bbch.text = self.obs["bbch_label"] or (
            ph.bbch_label(self.obs["bbch_code"], a.db.bbch_names())
            if self.obs["bbch_code"] is not None else "")
        self.ids.notes.text = self.obs["notes"] or ""
        self.ids.stamp.text = (f"Última modificación: {self.obs['updated_at'].replace('T', ' ')}"
                               if self.obs["bbch_code"] is not None else "Registro nuevo")
        self.suggestion = None
        self._show_ai_from_obs()
        self.refresh_location()

    # ------------------------------------------------ ubicación (opcional)
    GPS_SOURCES = {"gps": "GPS del teléfono", "foto": "desde la foto", "mapa": "marcada en el mapa"}

    def refresh_location(self):
        o = self.obs
        has = o["latitude"] is not None and o["longitude"] is not None
        self.ids.gps_icon.icon = "map-marker-check" if has else "map-marker-off-outline"
        self.ids.gps_icon.text_color = c(theme.BERRY if has else theme.MUTED)
        if has:
            import geo
            self.ids.gps_text.text = geo.fmt(o["latitude"], o["longitude"])
            parts = [self.GPS_SOURCES.get(o["gps_source"] or "", o["gps_source"] or "")]
            if o["gps_accuracy"]:
                parts.append(f"precisión ±{o['gps_accuracy']:.0f} m")
            self.ids.gps_detail.text = " · ".join(p for p in parts if p)
        else:
            self.ids.gps_text.text = "Sin ubicación"
            self.ids.gps_detail.text = ("Opcional: tome la posición actual, márquela en el mapa o "
                                        "se completa sola si la foto trae GPS.")
        self.ids.gps_clear.opacity = 1 if has else 0
        self.ids.gps_clear.disabled = not has

    def set_location(self, lat, lon, accuracy=None, source="gps"):
        a = app()
        a.db.update_observation(self.obs["id"], latitude=lat, longitude=lon,
                                gps_accuracy=accuracy, gps_source=source)
        a.db.set_setting("last_location", [lat, lon])
        self.obs = a.db.get_observation(self.variety_id, self.week_id)
        self.refresh_location()

    def clear_location(self):
        self.set_location(None, None, None, None)

    def locate_gps(self):
        a = app()
        import geo
        gps = getattr(self, "_gps", None)
        if gps is not None and not gps._done:
            gps.finish()   # «Usar ahora»: se queda con la mejor lectura obtenida
            return

        def granted(ok):
            if not ok:
                a.toast("Sin permiso de ubicación: puede marcar el punto en el mapa.")
                return
            Clock.schedule_once(lambda *_: start(), 0)

        def reset_button():
            self.ids.gps_btn.text = "Mi ubicación"
            self.ids.gps_btn.icon = "crosshairs-gps"

        def start():
            obs_id = self.obs["id"]
            self.ids.gps_text.text = "Buscando señal GPS…"
            self.ids.gps_detail.text = (f"Objetivo ±{geo.LocationRequest.TARGET_M:.0f} m · mejor al aire "
                                        "libre, con el teléfono quieto")
            self.ids.gps_btn.text = "Usar ahora"
            self.ids.gps_btn.icon = "check"

            def progress(lat, lon, acc):
                if self.obs["id"] != obs_id:
                    return
                self.ids.gps_text.text = f"{geo.fmt(lat, lon)}"
                self.ids.gps_detail.text = (f"Precisión actual ±{acc:.0f} m · buscando ±"
                                            f"{geo.LocationRequest.TARGET_M:.0f} m…")
                self.ids.gps_btn.text = f"Usar ahora (±{acc:.0f} m)"

            def done(lat, lon, acc):
                self._gps = None
                reset_button()
                if self.obs["id"] != obs_id:
                    return
                self.set_location(lat, lon, acc, "gps")
                if acc <= geo.LocationRequest.TARGET_M:
                    a.toast(f"Ubicación guardada (±{acc:.0f} m)")
                else:
                    a.toast(f"Ubicación guardada con ±{acc:.0f} m (no se logró ±10 m: "
                            "pruebe al aire libre y reintente)")

            def fail(msg):
                self._gps = None
                reset_button()
                self.refresh_location()
                a.toast(msg)

            try:
                self._gps = geo.LocationRequest(done, fail, progress)
                self._gps.start()
            except Exception as exc:  # noqa: BLE001
                fail(f"No se pudo leer el GPS: {exc}")

        geo.request_location_permission(granted)

    def on_leave(self, *_):
        gps = getattr(self, "_gps", None)
        if gps is not None:
            gps.cancel()   # no dejar el GPS encendido al salir del registro
            self._gps = None
            self.ids.gps_btn.text = "Mi ubicación"
            self.ids.gps_btn.icon = "crosshairs-gps"

    def pick_on_map(self):
        a = app()
        o = self.obs
        if o["latitude"] is not None:
            start, zoom = (o["latitude"], o["longitude"]), 18
        elif a.db.get_setting("last_location"):
            start, zoom = tuple(a.db.get_setting("last_location")), 17
        else:
            import geo
            start, zoom = geo.DEFAULT_CENTER, 6
        map_dialog(start, zoom, lambda lat, lon: self.set_location(lat, lon, None, "mapa"))

    def _show_ai_from_obs(self):
        o = self.obs
        fast_clear(self.ids.alternatives)
        if o["ai_code"] is None:
            self.ids.ai_label.text = "Suba la foto de detalle para obtener una sugerencia."
            self.ids.ai_conf.value = 0
            self.ids.ai_conf_text.text = ""
            self.ids.ai_explain.text = ""
            self.ids.accept_btn.disabled = True
            return
        self.ids.ai_label.text = ph.bbch_label(o["ai_code"], app().db.bbch_names())
        conf = o["ai_confidence"] or 0
        self.ids.ai_conf.value = conf
        self.ids.ai_conf_text.text = f"{conf:.0%} confianza"
        try:
            import json
            detail = json.loads(o["ai_detail"] or "{}")
        except ValueError:
            detail = {}
        self.ids.ai_explain.text = detail.get("explanation", "")
        self._alternatives(detail.get("top", []))
        self.ids.accept_btn.disabled = False

    def _alternatives(self, top):
        box = self.ids.alternatives
        fast_clear(box)
        for code, p in top[1:3]:
            box.add_widget(MDRectangleFlatButton(
                text=f"BBCH {ph.code_str(code)} · {p:.0%}", theme_text_color="Custom",
                text_color=c(theme.LEAF_DARK), line_color=c(theme.LINE),
                on_release=lambda b, code=code: self._set_bbch(code)))

    def _set_bbch(self, code: int):
        self.ids.bbch.text = ph.bbch_label(code, app().db.bbch_names())

    # ------------------------------------------------------ fotos adjuntas
    def load_attachments(self):
        a = app()
        box = self.ids.attachments
        fast_clear(box)
        items = a.db.list_attachments(self.variety["id"], week_id=self.week["id"])
        for f in items:
            row = AttachmentRow(caption=f["caption"] or "", item=f, screen=self,
                                date=ph.format_date_es(_dt.date.fromisoformat(f["captured_at"][:10])))
            row.ids.thumb_box.add_widget(thumb_widget(f["path"], 160))
            box.add_widget(row)
        if not items:
            box.add_widget(MDLabel(text="Sin fotos adjuntas.", font_style="Caption",
                                   adaptive_height=True, theme_text_color="Custom",
                                   text_color=c(theme.MUTED)))

    def attach(self, source: str):
        """Fotos adjuntas a ESTE registro semanal (tomar o elegir de la galería) con descripción."""
        a = app()
        variety, week = self.variety, self.week
        base = ph.photo_basename(variety, week["start_date"], "attachment", trial=a.db.code)

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            a.toast("Guardando foto…" if len(paths) == 1 else f"Guardando {len(paths)} fotos…")

            def work():
                ids, error = [], None
                try:
                    dest_dir = data_subdir("photos", f"T{week['season']}", ph.week_dir(week))
                    for tmp in paths:
                        path = store_photo(tmp, dest_dir, base, exact=True)
                        ids.append(a.db.add_attachment(
                            variety["id"], week["season"], path, week_id=week["id"],
                            source="camera" if origin == "camera" else "gallery"))
                        a.thumb(path, 160)
                        a.backup_extra(path, week["start_date"], "Adjuntas")
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: stored(ids, error))

            def stored(ids, error):
                if self.week["id"] != week["id"] or self.variety["id"] != variety["id"]:
                    return
                self.load_attachments()
                if error:
                    a.toast(f"No se pudo guardar la foto: {error}")
                elif len(ids) == 1:
                    from ui import camera_burst
                    row = a.db.query_one("SELECT * FROM variety_attachments WHERE id=?", (ids[0],))
                    camera_burst.defer(lambda: self.caption_dialog(row))

            a.workers.submit(work)

        if source == "camera":
            from ui import camera_burst          # varias seguidas, hasta «Listo»
            camera_burst.burst(done, base, exact=True,
                               title=f"Foto adjunta\n{a.db.display_name(variety)}")
        else:
            a.media.pick_images(done)

    def caption_dialog(self, item: dict | None):
        if not item:
            return
        a = app()
        form = CaptionForm()
        form.ids.caption.text = item["caption"] or ""

        def ok(f):
            a.db.set_attachment_caption(item["id"], f.ids.caption.text)
            self.load_attachments()

        form_dialog("Descripción de la foto", form, ok)

    def delete_attachment(self, item: dict):
        def go():
            app().db.delete_attachment(item["id"])
            self.load_attachments()

        confirm("Quitar foto adjunta", "La foto deja de aparecer en el registro y en los informes "
                "(el archivo se conserva en el teléfono).", [("Quitar", go)])

    # -------------------------------------------------------------- fotos
    def _refresh_slot(self, kind: str):
        self.ids[kind].show(app().db.list_photos(self.obs["id"], kind))

    def capture(self, kind: str, source: str):
        """Cada toma (o cada foto elegida de la galería) SE SUMA al registro."""
        a = app()

        def done(result, origin):
            paths = [p for p in (result if isinstance(result, list) else [result]) if p]
            if not paths:
                if origin == "error":
                    a.toast("No se pudo obtener la foto.")
                return
            season, n = self.week["season"], self.week["week_number"]
            obs_id = self.obs["id"]
            self.ids[kind].show_busy("Procesando foto…" if len(paths) == 1
                                     else f"Procesando {len(paths)} fotos…")

            def work():  # normalizar y guardar fuera del hilo de la interfaz
                error = None
                try:
                    dest_dir = data_subdir("photos", f"T{season}", ph.week_dir(self.week))
                    base = ph.photo_basename(self.variety, self.week["start_date"], kind, trial=a.db.code)
                    for tmp in paths:
                        if self.obs["latitude"] is None:
                            import geo
                            gps = geo.exif_gps(tmp)
                            if gps:
                                Clock.schedule_once(lambda *_, g=gps: (
                                    self.set_location(g[0], g[1], None, "foto"),
                                    a.toast("Ubicación tomada de la foto")))
                        path = store_photo(tmp, dest_dir, base, exact=True)
                        pid = a.db.add_photo(obs_id, kind, path, source=origin)
                        a.thumb(path, 640)
                        a.thumb(path, 160)
                        a.backup_photo(pid, path)
                except Exception as exc:  # noqa: BLE001
                    error = exc
                Clock.schedule_once(lambda *_: stored(error))

            def stored(error):
                if self.obs["id"] != obs_id:  # el usuario ya cambió de registro
                    return
                self._refresh_slot(kind)
                if error:
                    a.toast(f"No se pudo guardar la foto: {error}")
                    return
                if kind == "detail":
                    self.analyze()

            a.workers.submit(work)

        if source == "camera":
            # Mismo nombre que en la app y en Drive: 20260928-C11G, 20260928-C11G-2…
            # Varias seguidas (hasta «Listo»): cada una con el número que le toca.
            from ui import camera_burst
            obs_id, variety, start = self.obs["id"], self.variety, self.week["start_date"]

            def hint():
                seq = len(a.db.list_photos(obs_id, kind)) + 1
                return ph.photo_basename(variety, start, kind, seq, trial=a.db.code)
            what = {"canopy": "Foto general", "detail": "Foto de detalle"}.get(kind, "Foto")
            camera_burst.burst(done, hint, exact=True,
                               title=f"{what}\n{a.db.display_name(variety)}")
        else:
            a.media.pick_images(done)

    def make_primary(self, kind: str, photo_id: int):
        app().db.set_primary(photo_id)
        self._refresh_slot(kind)
        app().toast("Foto principal actualizada (es la que aparece en los informes)")

    def remove_photo(self, kind: str):
        a = app()
        photo = a.db.get_photos(self.obs["id"]).get(kind)
        if not photo:
            return

        def do():
            a.db.delete_photo(photo["id"])
            self._refresh_slot(kind)

        confirm("Quitar la foto principal",
                "La foto se desvincula del registro (el archivo se conserva en el teléfono). "
                "Si hay otras fotos, la más reciente pasa a ser la principal.", [("Quitar", do)])

    # ----------------------------------------------------------------- IA
    def analyze(self):
        a = app()
        details = [p["path"] for p in a.db.list_photos(self.obs["id"], "detail")]
        if not details:
            a.toast("Primero agregue la foto de detalle (Foto 2).")
            return
        self.ids.spinner.active = True
        self.ids.ai_label.text = ("Analizando foto de detalle…" if len(details) == 1
                                  else f"Analizando {len(details)} fotos de detalle…")
        prev = a.db.previous_observation(self.variety_id, self.week["season"],
                                         self.week["week_number"])
        previous = (prev["bbch_code"], prev["week_number"]) if prev else None
        notes = self.ids.notes.text
        obs_id = self.obs["id"]

        def work():
            try:
                s = a.classifier.suggest(details, self.week["week_number"], previous, notes)
                a.db.update_observation(obs_id, ai_code=s.code, ai_confidence=s.confidence,
                                        ai_detail=s.as_detail_json())
                self._analysis_done(s, None)
            except Exception as exc:  # noqa: BLE001
                self._analysis_done(None, exc)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _analysis_done(self, s, error):
        self.ids.spinner.active = False
        if error:
            self.ids.ai_label.text = "No se pudo analizar la imagen."
            self.ids.ai_explain.text = str(error)
            return
        self.suggestion = s
        self.obs = app().db.get_observation(self.variety_id, self.week_id)
        self._show_ai_from_obs()
        if not self.ids.bbch.text.strip():  # sugerencia pre-cargada en el campo editable
            self.ids.bbch.text = s.label

    def accept_ai(self):
        if self.obs["ai_code"] is not None:
            self._set_bbch(self.obs["ai_code"])

    def open_scale(self, caller):
        bbch_dialog(f"Escala BBCH · {_crop().fruit}", app().db, self._set_bbch,
                    current=ph.parse_bbch_code(self.ids.bbch.text or ""))

    # -------------------------------------------------------------- guardar
    @perf.timed("registro.guardar")
    def save(self):
        a = app()
        text = self.ids.bbch.text.strip()
        code = ph.parse_bbch_code(text)
        if text and code is None:
            a.toast("Indique un código BBCH (ej. «BBCH 65: Plena floración»).")
            return
        ai_code = self.obs["ai_code"]
        a.db.update_observation(
            self.obs["id"], bbch_code=code, bbch_label=text, notes=self.ids.notes.text,
            observed_at=_dt.date.today().isoformat(),
            ai_accepted=None if ai_code is None or code is None else int(code == ai_code))
        if code is not None and a.db.get_setting("ai_auto_learn", True):
            # Aprendizaje continuo: cada foto de detalle del registro (con su estado
            # confirmado) se suma a la memoria de la IA, en segundo plano.
            photos = [p for p in a.db.list_photos(self.obs["id"], "detail") if os.path.exists(p["path"])]

            def learn():
                for p in photos:
                    a.classifier.add_reference(p["path"], code, photo_id=p["id"])

            if photos:
                a.workers.submit(learn)
        a.toast("Registro guardado")
        a.back()


# Referencias a otras pantallas (al final: así no hay importaciones circulares).
from ui.varieties_ui import AttachmentRow, CaptionForm, map_dialog  # noqa: E402
