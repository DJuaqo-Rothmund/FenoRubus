"""
ui/camera_burst.py
==================
Varias fotos seguidas sin volver a tocar «Sacar foto» (cámara en cadena).

La cámara del teléfono entrega una foto por vez y se cierra. Aquí, después de cada foto la
app la guarda y vuelve a abrir la cámara sola en un instante. Mientras tanto, abajo se ve
una barra con las fotos sacadas y el botón «Listo» para terminar (también termina al
volver atrás desde la cámara sin sacar foto).

    burst(done, hint)       # done(ruta, origen) se llama por cada foto, como take_photo
    defer(fn)               # un diálogo «de una foto» (pie de foto, ficha…): se muestra
                            # al terminar, y solo si se sacó una sola
"""
from __future__ import annotations

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar

from ui import theme
from ui.theme import c

REOPEN_S = 1.4        # tiempo para tocar «Listo» antes de que la cámara se abra de nuevo

_state: dict | None = None      # ráfaga en curso


def active() -> bool:
    return _state is not None


def defer(fn) -> None:
    """Fuera de una ráfaga, fn() al tiro; dentro, al terminar si fue una sola foto."""
    if _state is None:
        fn()
    else:
        _state["deferred"] = fn


def burst(done, hint=None, exact: bool = False, title: str = "") -> None:
    """Abre la cámara y la vuelve a abrir después de cada foto hasta tocar «Listo».

    hint: nombre de la foto (texto) o función que lo da (para numerarlas: -2, -3…)."""
    global _state
    if _state is not None:
        return
    _state = {"done": done, "hint": hint, "exact": exact, "n": 0, "deferred": None,
              "bar": None, "ev": None, "title": title}
    _shoot()


def _shoot(*_):
    st = _state
    if st is None:
        return
    _hide_bar()
    hint = st["hint"]() if callable(st["hint"]) else st["hint"]
    try:
        MDApp.get_running_app().media.take_photo(_got, hint, exact=st["exact"])
    except Exception as exc:  # noqa: BLE001
        MDApp.get_running_app().toast(f"No se pudo abrir la cámara: {exc}")
        finish()


def _got(path, origin):
    st = _state
    if st is None:
        return
    if not path:                       # atrás en la cámara (o error): se termina
        if origin == "error":
            MDApp.get_running_app().toast("No se pudo obtener la foto.")
        finish()
        return
    st["n"] += 1
    try:
        st["done"](path, origin)
    except Exception as exc:  # noqa: BLE001
        MDApp.get_running_app().toast(f"No se pudo guardar la foto: {exc}")
    _show_bar()
    st["ev"] = Clock.schedule_once(_shoot, REOPEN_S)


def finish(*_):
    """Termina la ráfaga (botón «Listo», atrás en la cámara o error)."""
    global _state
    st = _state
    if st is None:
        return
    if st["ev"] is not None:
        st["ev"].cancel()
    _hide_bar()
    _state = None
    n = st["n"]
    if n == 1 and st["deferred"]:
        Clock.schedule_once(lambda *_: st["deferred"](), .3)
    elif n > 1:
        MDApp.get_running_app().toast(f"{n} fotos guardadas")


def _again(*_):
    st = _state
    if st is not None and st["ev"] is not None:
        st["ev"].cancel()
        _shoot()


# ------------------------------------------------------------------ barra
def _show_bar():
    st = _state
    bar = st["bar"]
    if bar is None:
        bar = MDCard(orientation="vertical", size_hint=(None, None), radius=[dp(18)] * 4,
                     md_bg_color=c(theme.FILL_DARK, .96), padding=(dp(16), dp(10), dp(10), dp(8)),
                     spacing=dp(6), elevation=3)
        row = MDBoxLayout(adaptive_height=True, spacing=dp(6))
        lbl = MDLabel(theme_text_color="Custom", text_color=(1, 1, 1, 1), font_style="Body2",
                      adaptive_height=True, pos_hint={"center_y": .5})
        row.add_widget(lbl)
        row.add_widget(MDFlatButton(text="OTRA YA", theme_text_color="Custom", text_color=(1, 1, 1, .85),
                                    on_release=_again, pos_hint={"center_y": .5}))
        row.add_widget(MDRaisedButton(text="LISTO", md_bg_color=c(theme.LEAF), on_release=finish,
                                      pos_hint={"center_y": .5}))
        bar.add_widget(row)
        prog = MDProgressBar(value=0, max=1, size_hint_y=None, height=dp(3), color=c(theme.LEAF))
        bar.add_widget(prog)
        bar._lbl, bar._prog = lbl, prog
        st["bar"] = bar
    bar.width = min(Window.width - dp(24), dp(460))
    bar.height = dp(74)
    bar.pos = ((Window.width - bar.width) / 2, dp(24))
    n = st["n"]
    bar._lbl.text = f"{n} foto{'s' if n != 1 else ''} · la cámara se abre de nuevo…"
    if bar.parent is None:
        Window.add_widget(bar)
    Animation.cancel_all(bar._prog)
    bar._prog.value = 0
    Animation(value=1, d=REOPEN_S).start(bar._prog)


def _hide_bar():
    st = _state
    bar = st and st["bar"]
    if bar is not None and bar.parent is not None:
        bar.parent.remove_widget(bar)
