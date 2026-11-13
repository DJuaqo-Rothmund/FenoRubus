"""
ui/ailab.py
===========
Laboratorio de IA (IA / IA+).
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
import os
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.fitimage import FitImage
from kivymd.uix.label import MDLabel
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.screen import MDScreen
from kivymd.uix.toolbar import MDTopAppBar
import phenology as ph
from android_bridge import store_photo
from platform_utils import data_subdir
from ui import theme
from ui.theme import c
from ui.common import (GlassButton, PillButton, _crop, app, confirm, fast_clear, form_dialog,
    list_dialog, thumb_widget)


# ===========================================================================
# Calibración IA (protegida por PIN)
# ===========================================================================
class PinForm(MDBoxLayout):
    """Campo de PIN que se escribe ahí mismo (sin el cuadro de texto nativo encima: así
    es un solo diálogo) con el teclado numérico, que se abre solo."""

    def on_kv_post(self, *_):
        pin = self.ids.pin
        pin.native_edit = False
        pin.input_type = "number"
        Clock.schedule_once(lambda *_: setattr(pin, "focus", self.autofocus), .35)

    autofocus = True


class MindSeg(PillButton):
    pass


class MindTopBar(MDTopAppBar):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(lambda *_: setattr(self, "specific_text_color", c(theme.MIND_TEXT)))


class MindRow(GlassButton):
    title = StringProperty()
    subtitle = StringProperty()
    value = StringProperty()


class MindOption(GlassButton):
    title = StringProperty()
    subtitle = StringProperty()
    code = NumericProperty(0)
    result = StringProperty("")   # "", "ok", "bad"
    locked = BooleanProperty(False)  # ya respondida (sin atenuar el texto como «disabled»)


def _mind(cls_name: str, **kw):
    from kivy.factory import Factory
    return getattr(Factory, cls_name)(**kw)


class AILabScreen(MDScreen):
    """«Mente del sistema»: desafío diario, etiquetado, modelo y datos históricos."""

    def on_pre_enter(self, *_):
        self.refresh()

    def on_enter(self, *_):
        self.ids.sky.start()       # fondo vivo: destellos y píxeles

    def on_leave(self, *_):
        self.ids.sky.stop()

    def show(self, name: str):
        self.ids.seg.current = name
        self.refresh()

    def open_iaplus(self):
        """IA+: cajas para el detector, en su propia pantalla (ui/boxes.py)."""
        from ui import boxes
        boxes.open_screen()

    def refresh(self):
        getattr(self, f"refresh_{self.ids.seg.current}")()

    # ======================================================= desafío diario
    @property
    def game(self):
        a = app()
        if getattr(self, "_game", None) is None or self._game.db is not a.db:   # cambió de ensayo
            from ai_game import DailyChallenge
            self._game = DailyChallenge(a.db, lambda: a.classifier, a.all_dbs)
        return self._game

    _mode = None          # modo en juego («identify» / «capture»); None = sala de juego
    _pick = "identify"    # modo elegido en la sala

    def refresh_challenge(self):
        if self._mode is None:
            self._render_lobby()
            return
        box = self.ids.task_box
        fast_clear(box)
        box.add_widget(self._mind_note("Cargando el siguiente desafío…"))
        mode, endless = self._mode, self._endless

        def work():
            try:
                # Sin fin: siempre hay otro; si no, solo los desafíos del día de ese modo.
                ch = self.game.next_challenge(mode, create=endless)
                Clock.schedule_once(lambda *_: self._render_challenge(ch))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: (app().toast(f"No se pudo preparar: {error}"),
                                                self._exit_game()))

        app().workers.submit(work)

    # ---- sala de juego: «¿Aceptas el desafío?»
    MODE_TEXT = {"identify": "Ponle nombre (estado BBCH) a fotos que ya están en la app. Si la foto "
                             "ya tenía estado es un quiz; si no, tu respuesta la etiqueta.",
                 "capture": "La IA te pide un estado y tú le muestras una foto (cámara o galería). "
                            "Dice qué vio y aprende con tu ejemplo.",
                 }
    _run = 0              # desafíos respondidos en esta partida
    _endless = False      # casilla «Modo sin fin» (vale para nombrar o para subir fotos)

    def _render_lobby(self):
        from ui import arcade
        self._update_header()
        box = self.ids.task_box
        fast_clear(box)
        card = _mind("MindCard")
        arena = arcade.PixelArena(size_hint_y=None, height=dp(330))
        arena.add_widget(arcade.PixelText(text="¿ACEPTAS\nEL DESAFÍO?", px=dp(4),
                                          pos_hint={"center_x": .5, "top": .95}))
        orb = arcade.PixelOrb(size_hint=(None, None), size=(dp(156), dp(156)),
                              pos_hint={"center_x": .5, "center_y": .36})
        orb.bind(on_release=lambda *_: self._start_game())
        arena.add_widget(orb)
        arena.add_widget(arcade.PixelText(text="GO", px=dp(7), color=c(theme.MIND_ACCENT),
                                          pos_hint={"center_x": .5, "center_y": .36}))
        arena.orb = orb
        card.add_widget(arena)
        card.add_widget(_mind("MindSection", text="ELIGE TU DESAFÍO"))
        row = MDBoxLayout(adaptive_height=True, spacing=dp(8))
        self._mode_btns = {}
        for kind, label in (("identify", "Nombrar fotos"), ("capture", "Subir fotos")):
            b = _mind("MindSeg", text=label, selected=kind == self._pick)
            b.bind(on_release=lambda w, k=kind: self._choose_mode(k))
            self._mode_btns[kind] = b
            row.add_widget(b)
        card.add_widget(row)
        from ui.arcade import AuraCheck
        endless = MDBoxLayout(adaptive_height=True, spacing=dp(10), padding=(dp(4), dp(2)))
        chk = AuraCheck(active=self._endless, pos_hint={"center_y": .5})
        chk.bind(active=lambda w, v: (setattr(self, "_endless", v), self._choose_mode(self._pick)))
        endless.add_widget(chk)
        lbl = MDBoxLayout(orientation="vertical", adaptive_height=True, pos_hint={"center_y": .5})
        lbl.add_widget(_mind("MindText", text="Modo sin fin", bold=True))
        lbl.add_widget(_mind("MindMuted", text="Un desafío tras otro, sin parar · cada 5 seguidos, ronda completada"))
        endless.add_widget(lbl)
        card.add_widget(endless)
        self._mode_desc = _mind("MindMuted", text="")
        card.add_widget(self._mode_desc)
        start = _mind("MindButton", text="COMENZAR")
        start.bind(on_release=lambda *_: self._start_game())
        card.add_widget(start)
        box.add_widget(card)
        self._choose_mode(self._pick)
        arena.start()

    def _choose_mode(self, kind):
        self._pick = kind
        for k, b in getattr(self, "_mode_btns", {}).items():
            b.selected = k == kind
        extra = ""
        if kind == "identify":
            n = self.game.available("identify")
            extra = f"  ·  {n} foto(s) por nombrar" if n else "  ·  no quedan fotos por nombrar"
        if not self._endless:
            extra += "  ·  solo los desafíos de hoy"
        self._mode_desc.text = self.MODE_TEXT[kind] + extra

    def _start_game(self):
        if self._pick == "identify" and not self.game.available("identify"):
            app().toast("No quedan fotos por nombrar: registra fotos en el muestreo o elige «Subir fotos».")
            return
        from ui import arcade

        def go():
            self._mode, self._run = self._pick, 0
            self.refresh_challenge()

        arcade.countdown(go)

    def _exit_game(self):
        self._mode = None
        self.refresh_challenge()

    def _exit_button(self):
        b = MDFlatButton(text="SALIR AL MENÚ DEL DESAFÍO", theme_text_color="Custom",
                         text_color=c(theme.MIND_MUTED), pos_hint={"center_x": .5})
        b.bind(on_release=lambda *_: self._exit_game())
        return b

    def _update_header(self):
        st = self.game.stats()
        done, total = self.game.progress()
        self.ids.ch_ring.value = done / total if total else 0
        self.ids.ch_ring_text.text = f"{done}/{total or 5}"
        today = _dt.date.today().isoformat()
        self.ids.ch_title.text = ("¡Desafío completado!" if st.get("last_day") == today
                                  else "Desafíos cerrados" if total and done == total
                                  else "Entrena a la IA")
        self.ids.streak_text.text = f"{st['streak']} día" + ("s" if st["streak"] != 1 else "")
        acc = f" · {st['accuracy']:.0%} aciertos" if st["accuracy"] is not None else ""
        self.ids.xp_text.text = f"Nivel {st['level']} · {st['xp']} XP{acc}"
        self.ids.level_bar.value = st["level_progress"]

    def _mind_note(self, text):
        card = _mind("MindCard")
        card.add_widget(_mind("MindText", text=text))
        return card

    def _render_challenge(self, ch=None):
        self._update_header()
        box = self.ids.task_box
        fast_clear(box)
        if ch is None:   # sin desafíos de hoy en este modo (o sin fotos para nombrar)
            card = _mind("MindCard")
            card.add_widget(_mind("MindSection", text="¡NIVEL DESPEJADO!"))
            no_photos = self._mode == "identify" and not self.game.available("identify")
            card.add_widget(MDLabel(text="Ya nombraste todas las fotos disponibles." if no_photos
                                    else "Completaste los desafíos de hoy de este modo.",
                                    font_style="H6", bold=True, adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(theme.MIND_TEXT)))
            card.add_widget(_mind("MindMuted", text=(
                "Registra fotos nuevas en el muestreo o cambia a «Subir fotos» para seguir."
                if no_photos else "Activa «Modo sin fin» para seguir jugando, o vuelve mañana.")))
            card.add_widget(self._exit_button())
            box.add_widget(card)
            return
        card = self._identify_card(ch) if ch["kind"] == "identify" else self._capture_card(ch)
        if self._endless:
            card.add_widget(_mind("MindSection", text=f"MODO SIN FIN · {self._run} SEGUIDOS"), index=len(card.children))
        card.add_widget(self._exit_button())
        box.add_widget(card)

    # ---- «¿Qué estado es?»
    def _identify_card(self, ch):
        p = ch["payload"]
        names = app().db.bbch_names()
        card = _mind("MindCard")
        card.add_widget(_mind("MindSection", text="¿QUÉ ESTADO ES?"))
        card.add_widget(_mind("MindMuted", text=f"{p['variety']} · {p['week']}"
                                                + ("" if p.get("truth") is not None
                                                   else " · foto sin estado: tu respuesta la etiqueta")))
        img = MDBoxLayout(size_hint_y=None, height=dp(230))
        img.add_widget(thumb_widget(p["path"], 640))
        card.add_widget(img)
        grid = MDGridLayout(cols=2, spacing=dp(8), adaptive_height=True)
        opts = []
        for code in p["options"]:
            o = MindOption(title=f"BBCH {ph.code_str(code)}", subtitle=names.get(code, ""), code=code)
            o.bind(on_release=lambda w, ch=ch: self._answer(ch, w, opts))
            opts.append(o)
            grid.add_widget(o)
        card.add_widget(grid)
        self._skip = self._skip_button(ch)
        card.add_widget(self._skip)
        return card

    def _answer(self, ch, option, opts):
        if option.locked:
            return
        for o in opts:
            o.locked = True
        if getattr(self, "_skip", None) is not None and self._skip.parent:
            self._skip.parent.remove_widget(self._skip)
        res = self.game.answer_identify(ch["id"], option.code)
        truth = res["truth"]
        for o in opts:
            if truth is not None and o.code == truth:
                o.result = "ok"
            elif o is option:
                o.result = "ok" if res["correct"] in (True, None) else "bad"
            if not o.result:
                o.opacity = .45
        if res["correct"] is not False:   # acierto o etiqueta nueva: explosión de píxeles
            from ui import arcade
            arcade.burst(*option.to_window(*option.center))
        if res["correct"] is None:
            msg = f"Etiquetada como BBCH {ph.code_str(option.code)}. +{res['xp']} XP"
        elif res["correct"]:
            msg = f"¡Correcto! +{res['xp']} XP"
        else:
            msg = f"Era BBCH {ph.code_str(truth)}. La IA lo aprende igual. +{res['xp']} XP"
        if res.get("ai") is not None:
            msg += f" · la IA había pensado BBCH {ph.code_str(res['ai'])}"
        self._feedback(msg, res)

    # ---- «Muéstrame este estado»
    def _capture_card(self, ch):
        a = app()
        code = ch["payload"]["target"]
        row = next((r for r in a.db.list_bbch() if r["code"] == code), None)
        card = _mind("MindCard")
        card.add_widget(_mind("MindSection", text="MUÉSTRAME ESTE ESTADO"))
        card.add_widget(MDLabel(text=f"BBCH {ph.code_str(code)}", font_style="H4", bold=True, adaptive_height=True,
                                theme_text_color="Custom", text_color=c(theme.MIND_ACCENT)))
        card.add_widget(MDLabel(text=row["label"] if row else "", font_style="H6", adaptive_height=True,
                                theme_text_color="Custom", text_color=c(theme.MIND_TEXT)))
        if row and row["description"]:
            card.add_widget(_mind("MindMuted", text=row["description"]))
        card.add_widget(_mind("MindMuted", text=ph.MACRO_STAGES.get(ph.macro_of(code), "")))
        cam = _mind("MindButton", text="Tomar foto")
        cam.bind(on_release=lambda *_: self._capture(ch, "camera"))
        gal = _mind("MindGhost", icon="image-outline", text="Elegir de la galería")
        gal.bind(on_release=lambda *_: self._capture(ch, "gallery"))
        card.add_widget(cam)
        card.add_widget(gal)
        card.add_widget(self._skip_button(ch))
        return card

    def _capture(self, ch, source):
        a = app()

        def done(result, _origin):
            path = result[0] if isinstance(result, list) else result
            if not path:
                return
            fast_clear(self.ids.task_box)
            self.ids.task_box.add_widget(self._mind_note("La IA está mirando la foto…"))

            def work():
                try:
                    stored = store_photo(path, data_subdir("training"), f"desafio_bbch{ph.code_str(ch['payload']['target'])}")
                    res = self.game.complete_capture(ch["id"], stored)
                    res["path"] = stored
                    Clock.schedule_once(lambda *_: self._capture_done(res))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: (a.toast(f"No se pudo procesar: {error}"),
                                                    self.refresh_challenge()))

            a.workers.submit(work)

        if source == "camera":
            a.media.take_photo(done, f"entrenamiento_BBCH{ph.code_str(ch['payload']['target'])}")
        else:
            a.media.pick_image(done)

    def _capture_done(self, res):
        fast_clear(self.ids.task_box)
        card = _mind("MindCard")
        img = MDBoxLayout(size_hint_y=None, height=dp(200))
        img.add_widget(thumb_widget(res["path"], 640))
        card.add_widget(img)
        from kivy.core.window import Window
        from ui import arcade
        arcade.burst(Window.width / 2, Window.height / 2)
        seen = f"La IA vio BBCH {ph.code_str(res['ai'])}"
        verdict = " — ¡coincide con el estadio!" if res["agree"] else " — ahora aprende tu ejemplo"
        self.ids.task_box.add_widget(card)
        self._feedback(f"{seen}{verdict}. +{res['xp']} XP", res, container=card)

    # ---- comunes
    def _skip_button(self, ch):
        b = MDFlatButton(text="SALTAR", theme_text_color="Custom", text_color=c(theme.MIND_MUTED),
                         pos_hint={"center_x": .5})
        b.bind(on_release=lambda *_: (self.game.skip(ch["id"]), self.refresh_challenge()))
        return b

    def _celebrate(self, res):
        """Serpentinas de píxeles: desafío del día completado o ronda del modo sin fin."""
        from ui import arcade
        self._run += 1
        if res.get("day_done"):
            arcade.party("DESAFIO\nCOMPLETADO",
                         f"Racha: {res['stats']['streak']} día(s) · {res['stats']['xp']} XP")
        elif self._endless and self._run % 5 == 0:
            arcade.party(f"RONDA {self._run // 5}\nCOMPLETADA", f"{self._run} desafíos seguidos · ¡sigue!")

    def _feedback(self, msg, res, container=None):
        self._celebrate(res)
        self._update_header()
        card = container or _mind("MindCard")
        card.add_widget(MDLabel(text=msg, font_style="Subtitle1", bold=True, adaptive_height=True,
                                theme_text_color="Custom",
                                text_color=c(theme.MIND_BAD if res.get("correct") is False else theme.MIND_OK)))
        if res.get("day_done"):
            card.add_widget(_mind("MindMuted", text=f"¡Desafío del día completado! Racha: "
                                                    f"{res['stats']['streak']} día(s)."))
        nxt = _mind("MindButton", text="Siguiente")
        nxt.bind(on_release=lambda *_: self.refresh_challenge())
        card.add_widget(nxt)
        if container is None:
            self.ids.task_box.add_widget(card)

    # ============================================================ etiquetado
    def set_auto_learn(self, active: bool):
        app().db.set_setting("ai_auto_learn", bool(active))

    def add_all_labeled(self):
        a = app()
        from ai_game import detail_photos
        todo = [p for p in detail_photos(a.all_dbs()) if p["bbch_code"] is not None
                and not p["in_reference"] and os.path.exists(p["path"])]
        if not todo:
            a.toast("No hay fotos etiquetadas pendientes.")
            return

        def work():
            for p in todo:
                a.classifier.add_reference(p["path"], p["bbch_code"], photo_id=p["id"], db=p["db"])
            Clock.schedule_once(lambda *_: (a.toast(f"{len(todo)} referencias agregadas"),
                                            self.refresh_model()))

        a.workers.submit(work)
        a.toast(f"Procesando {len(todo)} fotos…")

    # ================================================================ modelo
    def refresh_model(self):
        a = app()
        ext = a.classifier.extractor
        counts = a.db.reference_counts()
        self.ids.model_text.text = (f"{ext.name} · {ext.dim} dimensiones · k-NN coseno "
                                    f"(k={a.classifier.K}) + priors · {sum(counts.values())} referencias")
        box = self.ids.counts
        fast_clear(box)
        names = a.db.bbch_names()
        for code in sorted(counts):
            box.add_widget(MindRow(title=f"BBCH {ph.code_str(code)}", subtitle=names.get(code, ""),
                                   value=str(counts[code])))
        if not counts:
            box.add_widget(_mind("MindMuted", text="Sin referencias: la IA usa solo los priors agronómicos."))
        self.ids.auto_learn.active = bool(a.db.get_setting("ai_auto_learn", True))
        self.refresh_data()      # «Modelo y datos»: documentos y temporadas anteriores

    def refresh_extra(self):
        """Fotos extra para IA+ (carpeta «IA+ Conocimiento ampliado»): ui/extra.py."""
        from ui import extra
        extra.build(self)

    def evaluate(self):
        ev = app().classifier.evaluate()
        if ev["exact"] is None:
            self.ids.eval_text.text = "Se necesitan al menos 3 referencias para evaluar."
        else:
            app().db.set_setting("ai_last_eval", ev)
            self.ids.eval_text.text = (f"Validación leave-one-out (n={ev['n']}): código exacto "
                                       f"{ev['exact']:.0%} · estadio principal {ev['macro']:.0%}")

    def retrain(self):
        a = app()

        def progress(i, n):
            Clock.schedule_once(lambda *_: setattr(self.ids.train_progress, "value", i / max(1, n)))

        def work():
            n = a.classifier.rebuild(progress)
            Clock.schedule_once(lambda *_: (a.toast(f"{n} embeddings recalculados"),
                                            self.refresh_model()))

        a.workers.submit(work)

    def try_photo(self):
        a = app()

        def picked(path, _origin):
            if not path:
                return
            self.ids.spinner.active = True
            self.ids.try_label.text = "Analizando…"
            week = a.week["week_number"]

            def work():
                try:
                    preview = a.thumb(path, 640)
                    s = a.classifier.suggest(path, week_number=week)
                    Clock.schedule_once(lambda *_: self._show(preview, s, None))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: self._show(None, None, error))

            a.workers.submit(work)

        a.media.pick_image(picked)

    def _show(self, preview, s, error):
        self.ids.spinner.active = False
        if error:
            self.ids.try_label.text = "No se pudo analizar la imagen."
            self.ids.try_explain.text = str(error)
            return
        box = self.ids.try_box
        fast_clear(box)
        box.add_widget(FitImage(source=preview, radius=[dp(16)]))
        box.height, box.opacity = dp(190), 1
        self.ids.try_label.text = s.label
        self.ids.try_conf.value = s.confidence
        alts = " · ".join(f"BBCH {ph.code_str(code)} {p:.0%}" for code, p in s.top[1:])
        self.ids.try_explain.text = f"Confianza {s.confidence:.0%} · alternativas: {alts}\n{s.explanation}"

    # ------------------------------------------- compartir entre teléfonos
    def export_knowledge(self):
        a = app()
        if not a.db.reference_counts():
            a.toast("Todavía no hay fotos etiquetadas en la memoria de la IA.")
            return
        a.toast("Preparando paquete…")

        def work():
            try:
                from ai_share import export_knowledge
                path, n = export_knowledge(a.db)
                Clock.schedule_once(lambda *_: a.report_actions(
                    path, "Conocimiento de la IA", f"{n} referencias · ábralo en el otro teléfono "
                    "con «Importar conocimiento»", viewable=False))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: a.toast(f"No se pudo exportar: {error}"))

        a.workers.submit(work)

    def import_knowledge(self):
        a = app()

        def picked(path, name):
            if not path:
                return
            a.toast("Sumando conocimiento…")

            def work():
                try:
                    from ai_share import import_knowledge
                    res = import_knowledge(a.db, path, a.classifier)
                    Clock.schedule_once(lambda *_: (self.refresh_model(),
                                                    confirm("Conocimiento importado", res.summary(), [])))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: a.toast(f"No se pudo importar: {error}"))

            a.workers.submit(work)

        a.media.pick_document(picked, exts=(".zip",))

    def change_pin(self):
        a = app()
        form = PinForm()
        form.ids.pin.hint_text = "PIN actual"
        new = PinForm()
        new.ids.pin.hint_text = "Nuevo PIN (4-8 dígitos)"
        new.autofocus = False
        box = MDBoxLayout(orientation="vertical", adaptive_height=True)
        box.add_widget(form)
        box.add_widget(new)

        def ok(_):
            try:
                if not a.pin.change(form.ids.pin.text, new.ids.pin.text):
                    form.ids.msg.text = "PIN actual incorrecto."
                    return False
            except ValueError as exc:
                new.ids.msg.text = str(exc)
                return False
            a.toast("PIN actualizado")

        form_dialog("Cambiar PIN", box, ok)

    # ================================================================= datos
    def refresh_data(self):
        box = self.ids.docs
        fast_clear(box)
        for d in app().db.list_documents():
            row = MindRow(title=d["title"], subtitle=f"{d['created_at'][:10]} · {d['chars']} caracteres",
                          value=f"{d['stages_found']}")
            row.bind(on_release=lambda w, d=d: self._doc_menu(d))
            box.add_widget(row)
        last = app().db.get_setting("last_import")
        if last and not self.ids.import_text.text:
            self.ids.import_text.text = f"Última importación: {last}"

    def _doc_menu(self, doc):
        def delete():
            app().db.delete_document(doc["id"])
            self.refresh_data()
        confirm(doc["title"], "¿Quitar este documento de la base de conocimiento? "
                              "(la escala BBCH enriquecida se mantiene)", [("Eliminar", delete)])

    def import_document(self):
        a = app()

        def done(path, name):
            if not path:
                return
            try:
                _id, n = a.classifier.import_document(path, title=name or os.path.basename(path))
            except Exception as exc:  # noqa: BLE001
                a.toast(f"No se pudo leer el documento: {exc}")
                return
            a.toast(f"Documento cargado: {n} claves BBCH detectadas")
            self.refresh_data()

        a.media.pick_document(done)

    def show_scale(self):
        rows = [(f"BBCH {ph.code_str(r['code'])}: {r['label']}", f"[{r['source']}] {r['description']}")
                for r in app().db.list_bbch()]
        list_dialog(f"Escala BBCH · {_crop().fruit}", rows)

    def save_template(self):
        from importer import write_template
        a = app()
        path = write_template(os.path.join(data_subdir("tmp"), "plantilla_historico_phenorubus.csv"))
        try:
            a.media.save_public(path, "text/csv")
            a.toast("Plantilla guardada en Descargas/PhenoRubus")
        except Exception as exc:  # noqa: BLE001
            a.toast(f"No se pudo guardar: {exc}")

    def import_history(self):
        a = app()

        def done(path, name):
            if not path:
                return
            if not path.lower().endswith((".csv", ".zip")):
                a.toast("Elija un archivo .csv o .zip")
                return
            train = self.ids.train_import.active
            self.ids.import_btn.disabled = True
            self.ids.import_text.text = f"Importando {name or os.path.basename(path)}…"

            def progress(i, n):
                Clock.schedule_once(lambda *_: setattr(self.ids.import_progress, "value", i / max(1, n)))

            def work():
                from importer import import_file
                try:
                    res = import_file(a.db, path, classifier=a.classifier if train else None,
                                      train_ai=train, progress=progress)
                    Clock.schedule_once(lambda *_: self._import_done(res, None))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: self._import_done(None, error))

            a.workers.submit(work)

        a.media.pick_document(done)

    def _import_done(self, res, error):
        self.ids.import_btn.disabled = False
        if error:
            self.ids.import_text.text = f"No se pudo importar: {error}"
            return
        summary = res.summary()
        app().db.set_setting("last_import", summary)
        errs = (f"\n{len(res.errors)} advertencia(s): " + "; ".join(res.errors[:3])) if res.errors else ""
        self.ids.import_text.text = f"Importado: {summary}{errs}"
        app().toast("Importación terminada")
