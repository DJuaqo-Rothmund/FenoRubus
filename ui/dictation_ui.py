"""
ui/dictation_ui.py
==================
Dictar datos a una planilla (app):

* RecordPanel: barra de grabación abajo (tiempo, onda, pausa, terminar, descartar, bolsillo).
* PocketView: «modo bolsillo», pantalla negra y brillo al mínimo mientras sigue grabando.
* DictationCard: la transcripción con cada número como pastilla: se toca un número y luego la
  celda; o «Ordenar con IA» (las celdas quedan en lavanda hasta «Confirmar todo»).
"""
from __future__ import annotations

import time

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.stacklayout import StackLayout
from kivy.uix.widget import Widget

import voice
from ui import theme
from ui.common import GlassCard
from ui.theme import c

GOLD, GOLD_INK = "#C9A227", "#2A1F00"


def _glyph(name):
    from kivymd.icon_definitions import md_icons
    return md_icons.get(name, "")


def fmt_time(s: float) -> str:
    s = int(max(0, s))
    return f"{s // 60:02d}:{s % 60:02d}"


class RoundBtn(ButtonBehavior, Label):
    """Botón redondo con ícono Material."""

    def __init__(self, icon, bg, size=54, fg=(1, 1, 1, 1), **kw):
        super().__init__(text=_glyph(icon), font_name="Icons", font_size=sp(size * .42), color=fg,
                         size_hint=(None, None), size=(dp(size), dp(size)), **kw)
        self.bg = bg
        self.bind(pos=self._d, size=self._d, state=self._d)

    def set_icon(self, icon):
        self.text = _glyph(icon)

    def _d(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*c(self.bg)[:3], .8 if self.state == "down" else 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.width / 2])


class Wave(Widget):
    """Onda de la voz (barras con el nivel de los últimos instantes)."""

    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(44), **kw)
        self.levels = [0.0] * 46
        self.bind(pos=self.draw, size=self.draw)

    def push(self, v):
        self.levels = self.levels[1:] + [v]
        self.draw()

    # Color de cada barra según cómo suena: tenue (bajo), rosado (bien), ámbar (alto, satura).
    LOW, OK, HIGH = "#8A7F86", "#FF6A93", "#FFB300"

    def draw(self, *_):
        self.canvas.clear()
        n = len(self.levels)
        w = self.width / n
        with self.canvas:
            Color(1, 1, 1, .10)                       # línea de «bien» (mínimo recomendado)
            y_ok = self.height * (0.1 + 0.9 * .38) / 2
            RoundedRectangle(pos=(self.x, self.center_y + y_ok), size=(self.width, dp(1)))
            RoundedRectangle(pos=(self.x, self.center_y - y_ok), size=(self.width, dp(1)))
            for i, v in enumerate(self.levels):
                Color(*c(self.HIGH if v > .93 else (self.OK if v >= .38 else self.LOW)))
                h = max(dp(4), self.height * (0.08 + 0.92 * v))
                RoundedRectangle(pos=(self.x + i * w + w * .2, self.center_y - h / 2), size=(w * .6, h),
                                 radius=[w * .3])


class PocketView(ModalView):
    """Pantalla negra (brillo al mínimo) mientras se graba: doble toque para volver."""

    def __init__(self, panel, **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background_color=(0, 0, 0, 1),
                         overlay_color=(0, 0, 0, 1), **kw)
        self.panel = panel
        self.lb = Label(text="", font_size=sp(15), color=(1, 1, 1, .35), halign="center")
        self.add_widget(self.lb)
        self._ev = Clock.schedule_interval(self._tick, .5)
        voice.set_brightness(0.01)

    def _tick(self, *_):
        p = self.panel
        state = "En pausa" if p.rec.paused else "Grabando"
        self.lb.text = f"{state} · {fmt_time(p.elapsed())}\n\nToque dos veces para volver"

    def on_touch_down(self, touch):
        if touch.is_double_tap:
            self.close()
        return True

    def close(self):
        self._ev.cancel()
        voice.set_brightness(None)
        self.dismiss()


class RecordPanel(ModalView):
    """Barra de grabación (abajo). on_done(path, segundos) al terminar."""

    def __init__(self, path: str, title: str, on_done, **kw):
        super().__init__(size_hint=(1, None), height=dp(268), pos_hint={"y": 0}, auto_dismiss=False,
                         background_color=(0, 0, 0, 0), overlay_color=(0, 0, 0, .25), **kw)
        self.on_done, self.rec, self.path = on_done, voice.Recorder(), path
        self.t0, self.paused_for, self.pause_at = 0.0, 0.0, None
        box = BoxLayout(orientation="vertical", padding=(dp(18), dp(14), dp(18), dp(12)), spacing=dp(6))
        box.bind(pos=self._bg, size=self._bg)
        self.box = box
        top = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(10))
        self.dot = Widget(size_hint=(None, None), size=(dp(14), dp(14)), pos_hint={"center_y": .5})
        self.dot.bind(pos=self._dot, size=self._dot)
        self.state_lb = Label(text="Grabando · 00:00", bold=True, font_size=sp(15), halign="left",
                              valign="middle", color=(1, 1, 1, 1))
        self.state_lb.bind(size=lambda w, s: setattr(w, "text_size", s))
        top.add_widget(self.dot)
        top.add_widget(self.state_lb)
        top.add_widget(Label(text=title, font_size=sp(11), color=(1, 1, 1, .6), halign="right", valign="middle",
                             shorten=True, text_size=(dp(150), None), size_hint_x=None, width=dp(150)))
        box.add_widget(top)
        self.wave = Wave()
        box.add_widget(self.wave)
        self.vol_lb = Label(text="Volumen: —", font_size=sp(12.5), bold=True, color=(1, 1, 1, .7),
                            size_hint_y=None, height=dp(18))
        box.add_widget(self.vol_lb)
        self._vol = 0.0
        row = BoxLayout(size_hint_y=None, height=dp(66), spacing=dp(18))
        row.add_widget(Widget())
        self.pause_b = RoundBtn("pause", "#333338")
        self.pause_b.bind(on_release=lambda *_: self.toggle_pause())
        stop_b = RoundBtn("stop", "#FF3B5C", size=64)
        stop_b.bind(on_release=lambda *_: self.finish())
        cancel_b = RoundBtn("close", "#333338")
        cancel_b.bind(on_release=lambda *_: self.discard())
        pocket_b = RoundBtn("cellphone-off", "#333338")
        pocket_b.bind(on_release=lambda *_: PocketView(self).open())
        for b in (self.pause_b, stop_b, cancel_b, pocket_b):
            row.add_widget(b)
        row.add_widget(Widget())
        box.add_widget(row)
        tip = Label(text="Diga, por ejemplo: «T cero R uno, planta uno, doce laterales, largo cuarenta y cinco…»"
                         "  ·  Bolsillo: pantalla negra sin dejar de grabar (no bloquee el teléfono).",
                    font_size=sp(10.5), color=(1, 1, 1, .55), halign="center", valign="top", size_hint_y=None)
        tip.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                 texture_size=lambda w, t: setattr(w, "height", t[1]))
        box.add_widget(tip)
        self.add_widget(box)

    def _bg(self, *_):
        b = self.box
        b.canvas.before.clear()
        with b.canvas.before:
            Color(*c("#1B1B1F"))
            RoundedRectangle(pos=(b.x + dp(10), b.y + dp(8)), size=(b.width - dp(20), b.height - dp(8)),
                             radius=[dp(26)])

    def _dot(self, *_):
        d = self.dot
        d.canvas.clear()
        with d.canvas:
            Color(*c("#FFB300" if self.rec.paused else "#FF3B5C"))
            RoundedRectangle(pos=d.pos, size=d.size, radius=[d.width / 2])

    def start(self):
        self.rec.start(self.path)
        self.t0 = time.time()
        self.open()
        self._ev = Clock.schedule_interval(self._tick, .1)

    def elapsed(self) -> float:
        now = self.pause_at or time.time()
        return now - self.t0 - self.paused_for

    def _tick(self, *_):
        self.state_lb.text = f"{'En pausa' if self.rec.paused else 'Grabando'} · {fmt_time(self.elapsed())}"
        v = 0 if self.rec.paused else self.rec.level()
        self.wave.push(v)
        self._vol = self._vol * .8 + v * .2               # suavizado: el texto no parpadea
        if self.rec.paused:
            self.vol_lb.text, self.vol_lb.color = "En pausa", (1, 1, 1, .5)
        else:
            word = voice.level_word(max(self._vol, v if v > .93 else 0))
            self.vol_lb.text = {"bajo": "Volumen: bajo · hable más fuerte o acérquese",
                                "bien": "Volumen: bien", "alto": "Volumen: alto · aléjese un poco"}[word]
            self.vol_lb.color = c({"bajo": "#B9AEB4", "bien": "#7CE3A6", "alto": "#FFB300"}[word])

    def toggle_pause(self):
        if self.rec.paused:
            self.rec.resume()
            self.paused_for += time.time() - (self.pause_at or time.time())
            self.pause_at = None
            self.pause_b.set_icon("pause")
        else:
            self.rec.pause()
            self.pause_at = time.time()
            self.pause_b.set_icon("play")
        self._dot()

    def finish(self):
        self._ev.cancel()
        secs = self.elapsed()
        try:
            path = self.rec.stop()
        except Exception as exc:  # noqa: BLE001
            from ui.common import app
            app().toast(f"No se pudo guardar el audio: {exc}")
            self.dismiss()
            return
        self.dismiss()
        self.on_done(path, secs)

    def discard(self):
        from ui.common import confirm

        def go():
            self._ev.cancel()
            self.rec.cancel()
            self.dismiss()
        confirm("Descartar grabación", "Se borra lo grabado.", [("Descartar", go)])


class NumChip(ButtonBehavior, Label):
    """Número de la transcripción: tocar = elegirlo (luego tocar la celda)."""

    def __init__(self, value: str, idx: int, used=False, **kw):
        super().__init__(text=value, bold=True, font_size=sp(13.5), size_hint=(None, None), height=dp(28), **kw)
        self.value, self.idx, self.used, self.sel = value, idx, used, False
        self.texture_update()
        self.width = self.texture_size[0] + dp(20)
        self.bind(pos=self._d, size=self._d)
        self._d()

    def set(self, used=None, sel=None):
        if used is not None:
            self.used = used
        if sel is not None:
            self.sel = sel
        self._d()

    def _d(self, *_):
        bg, fg = ("#A8184A", "#FFFFFF") if self.sel else (("#DDEFE3", "#4E7A60") if self.used else ("#E3EAFF", "#2A4FB8"))
        self.color = c(fg)
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*c(bg))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.height / 2])
        self.canvas.after.clear()
        if self.used and not self.sel:              # tachado: ya se usó
            from kivy.graphics import Line
            with self.canvas.after:
                Color(*c("#4E7A60", .8))
                Line(points=[self.x + dp(8), self.center_y, self.right - dp(8), self.center_y], width=dp(1.2))


class SpeedPill(ButtonBehavior, Label):
    """«1×» / «2×» en el reproductor del dictado."""


def _word(text):
    lb = Label(text=text, font_size=sp(13.5), color=c(theme.INK), size_hint=(None, None), height=dp(28))
    lb.texture_update()
    lb.width = lb.texture_size[0] + dp(1)
    return lb


class DictationCard(GlassCard):
    """El dictado de la semana sobre la grilla: reproductor, transcripción y acciones."""

    def __init__(self, screen, rec: dict, n_total: int = 1, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, padding=(dp(14), dp(12)), spacing=dp(8), **kw)
        self.radius = [dp(20)]
        self.screen, self.rec, self.player, self.chips = screen, rec, None, []
        self.bind(minimum_height=self.setter("height"))
        # Reproductor
        pl = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10), padding=(dp(6), 0))
        pl.bind(pos=self._pl_bg, size=self._pl_bg)
        self.pl = pl
        self.play_b = RoundBtn("play", "#2F6B4F", size=34)
        self.play_b.bind(on_release=lambda *_: self.toggle_play())
        self.time_lb = Label(text=fmt_time(rec.get("seconds", 0)), font_size=sp(12), color=(1, 1, 1, 1),
                             halign="left", valign="middle")
        self.time_lb.bind(size=lambda w, s: setattr(w, "text_size", s))
        pl.add_widget(self.play_b)
        pl.add_widget(self.time_lb)
        # 1× / 2×: escuchar el dictado más rápido (se recuerda para la próxima vez).
        self.speed_b = SpeedPill(text="", bold=True, font_size=sp(12.5), color=(1, 1, 1, 1),
                              size_hint=(None, None), size=(dp(44), dp(28)), pos_hint={"center_y": .5})
        self.speed_b.bind(pos=self._speed_bg, size=self._speed_bg, on_release=lambda *_: self.toggle_speed())
        pl.add_widget(self.speed_b)
        self._show_speed()
        Clock.schedule_once(lambda *_: self._show_speed(), 0)     # ya con su lugar en la fila
        more = Label(text=(f"Dictados de la semana: {n_total}" if n_total > 1 else "Dictado"), font_size=sp(11),
                     color=(1, 1, 1, .75), halign="right", valign="middle", size_hint_x=None, width=dp(150))
        more.bind(size=lambda w, s: setattr(w, "text_size", s))
        pl.add_widget(more)
        self.add_widget(pl)
        self.status = Label(text="", font_size=sp(11.5), color=c(theme.MUTED), halign="left", size_hint_y=None)
        self.status.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                         texture_size=lambda w, t: setattr(w, "height", t[1]))
        self.add_widget(self.status)
        self.words = StackLayout(size_hint_y=None, height=0, spacing=(dp(3), dp(4)))
        self.words.bind(minimum_height=self.words.setter("height"))
        self.add_widget(self.words)
        self.actions = StackLayout(size_hint_y=None, height=0, spacing=dp(8))
        self.actions.bind(minimum_height=self.actions.setter("height"))
        self.add_widget(self.actions)
        self.render()

    def _pl_bg(self, *_):
        self.pl.canvas.before.clear()
        with self.pl.canvas.before:
            Color(*c("#1E4A3A"))
            RoundedRectangle(pos=self.pl.pos, size=self.pl.size, radius=[dp(14)])

    def _speed(self) -> float:
        from platform_utils import global_get
        return float(global_get("dictation_speed", 1.0) or 1.0)

    def _show_speed(self):
        self.speed_b.text = "2×" if self._speed() >= 2 else "1×"
        self._speed_bg()

    def _speed_bg(self, *_):
        b = self.speed_b
        fast = self._speed() >= 2
        b.canvas.before.clear()
        with b.canvas.before:
            Color(*c("#FFFFFF", .95) if fast else c("#FFFFFF", .16))
            RoundedRectangle(pos=b.pos, size=b.size, radius=[b.height / 2])
        b.color = c("#1E4A3A") if fast else (1, 1, 1, 1)

    def toggle_speed(self):
        from platform_utils import global_set
        new = 1.0 if self._speed() >= 2 else 2.0
        global_set("dictation_speed", new)
        if self.player is not None:
            self.player.set_speed(new)
        self._show_speed()

    def toggle_play(self):
        if self.player is None:
            self.player = voice.Player(self.rec["path"])
            self.player.speed = self._speed()
        on = self.player.toggle()
        self.play_b.set_icon("pause" if on else "play")
        ev = getattr(self, "_pev", None)
        if ev:
            ev.cancel()
        if on:
            def tick(*_):
                if self.player is None:          # se cerró la tarjeta o se detuvo el audio
                    return False
                pos, dur = self.player.position()
                self.time_lb.text = f"{fmt_time(pos)} / {fmt_time(dur or self.rec.get('seconds', 0))}"
                if dur and pos >= dur - .2:
                    self.play_b.set_icon("play")
                    return False
            self._pev = Clock.schedule_interval(tick, .3)

    def stop_audio(self):
        ev = getattr(self, "_pev", None)
        if ev:
            ev.cancel()
        if self.player is not None:
            self.player.release()
            self.player = None

    def _btn(self, text, cb, gold=False, primary=False, danger=False):
        from kivymd.uix.button import MDRoundFlatButton
        dark = theme.is_dark()
        if gold:
            fg, bg = c(GOLD_INK), c(GOLD)
        elif primary:
            fg, bg = c("#FFFFFF"), c(theme.BERRY)
        elif danger:
            fg, bg = c("#FF7A9A" if dark else theme.BERRY), c("#FFFFFF", .06 if dark else .55)
        else:
            fg, bg = c("#E6EDF3" if dark else theme.LEAF_DARK), c("#FFFFFF", .06 if dark else .55)
        b = MDRoundFlatButton(text=text, font_size=sp(13), on_release=lambda *_: cb(),
                              theme_text_color="Custom", text_color=fg, md_bg_color=bg,
                              line_color=c(theme.BERRY if danger else ("#FFFFFF" if dark else theme.LEAF_DARK), .25))
        self.actions.add_widget(b)

    def _ai_btn(self, text, cb, icon, main=False):
        """Acciones de la IA con su identidad violeta (el dictado en sí sigue dorado)."""
        from kivy.core.text import Label as CoreLabel
        from ui.ai_style import AIButton, AIGhost
        cl = CoreLabel(text=text, font_size=sp(14), bold=True)
        cl.refresh()
        w = cl.texture.size[0] + dp(64)
        b = (AIButton if main else AIGhost)(text, icon, on_press_cb=cb, size_hint=(None, None),
                                           size=(w, dp(44)))
        self.actions.add_widget(b)

    def render(self):
        rec = self.rec
        self.words.clear_widgets()
        self.actions.clear_widgets()
        self.chips = []
        st = rec.get("status")
        if st in ("pending", "working"):
            self.status.text = "Transcribiendo con IA…" if st == "working" else "Audio guardado: falta transcribirlo."
        elif st == "error":
            self.status.text = f"No se pudo transcribir: {rec.get('error', '')[:140]}"
        else:
            ia = self.screen.ia_pending()
            self.status.text = (f"[b]La IA ordenó {ia} dato(s):[/b] revise los violetas y confirme." if ia else
                                "Toque un número y luego la celda donde va · o «Ordenar con IA».")
            self.status.markup = True
        text = rec.get("text") or ""
        if text:
            pos, k = 0, 0
            used = set(rec.get("used") or [])
            for a, b, val in voice.numbers(text):
                for w in text[pos:a].split():
                    self.words.add_widget(_word(w))
                chip = NumChip(val, k, used=k in used)
                chip.bind(on_release=lambda ch: self.screen.pick_number(self, ch))
                self.words.add_widget(chip)
                self.chips.append(chip)
                pos, k = b, k + 1
            for w in text[pos:].split():
                self.words.add_widget(_word(w))
        if st in ("pending", "error"):
            self._btn("Transcribir", lambda: self.screen.transcribe(rec), gold=True)
        elif st == "done":
            if self.screen.ia_pending():
                self._ai_btn("Confirmar todo", self.screen.ia_confirm, "check-all", main=True)
                self._ai_btn("Deshacer", self.screen.ia_undo, "undo")
            else:
                self._ai_btn("Ordenar con IA", lambda: self.screen.arrange(rec), "auto-fix", main=True)
        self._btn("Dictar más", self.screen.dictate)
        self._btn("Otros dictados", self.screen.pick_dictation)
        self._btn("Borrar audio", lambda: self.screen.delete_dictation(self.rec), danger=True)
        self._btn("Cerrar", self.screen.close_dictation)

    def mark_used(self, idx: int):
        used = sorted(set(self.rec.get("used") or []) | {idx})
        self.rec["used"] = used
        self.screen.dictations.update(self.rec["id"], used=used)
