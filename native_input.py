"""
native_input.py
===============
Escritura con el teclado REAL del teléfono (Android).

Kivy dibuja sus propios campos de texto: el teclado del sistema aparece, pero sin
autocorrector ni sugerencias útiles (Kivy no le informa el texto que ya está escrito) y
copiar/pegar sale en cuadros propios de Kivy. Por eso, al tocar un campo en Android se
abre un cuadro NATIVO de Android con el texto actual: autocorrector, sugerencias,
dictado por voz, emojis y copiar/pegar del sistema. Al aceptar, el texto vuelve al campo
de la app (y se dispara su guardado como si se hubiera escrito ahí).

* `install()`: una vez, antes de crear pantallas (en escritorio no hace nada).
* Un campo puede seguir con el teclado de Kivy con `native_edit = False`
  (p. ej. las celdas de las planillas, para ingresar números de corrido).
"""
from __future__ import annotations

from kivy.clock import Clock

from platform_utils import IS_ANDROID

_alive: list = []   # listeners Java vivos mientras el cuadro está abierto

# android.text.InputType
TEXT, NUMBER = 0x1, 0x2
CAP_SENTENCES, AUTO_CORRECT, MULTI_LINE = 0x4000, 0x8000, 0x20000
NUMBER_DECIMAL, NUMBER_SIGNED = 0x2000, 0x1000
TEXT_PASSWORD, NUMBER_PASSWORD = 0x80, 0x10


def input_type_for(ti) -> int:
    """Tipo de teclado según el campo (texto con autocorrector, número, clave)."""
    flt = getattr(ti, "input_filter", None)
    if flt in ("int", "float") or getattr(ti, "input_type", "text") == "number":
        t = NUMBER
        if flt == "float":
            t |= NUMBER_DECIMAL | NUMBER_SIGNED
        return t | (NUMBER_PASSWORD if ti.password else 0)
    if ti.password:
        return TEXT | TEXT_PASSWORD
    t = TEXT | CAP_SENTENCES | AUTO_CORRECT
    return t | (MULTI_LINE if ti.multiline else 0)


_broken = {"why": None}   # si el cuadro nativo falla una vez, se usa el teclado de la app


def wants_native(ti) -> bool:
    return (IS_ANDROID and _broken["why"] is None and getattr(ti, "native_edit", True)
            and not getattr(ti, "_native_skip", False) and not ti.readonly and not ti.disabled)


def _fallback(ti, why: str) -> None:
    """El cuadro nativo no abrió: se registra el motivo y el campo se abre con el teclado
    de la app (así siempre se puede escribir)."""
    if _broken["why"] is None:
        _broken["why"] = why
        try:
            import crashguard
            crashguard.record(RuntimeError(f"Teclado nativo: {why}"), "native_input")
        except Exception:  # noqa: BLE001
            pass
        try:
            from kivymd.app import MDApp
            MDApp.get_running_app().toast("Se usa el teclado de la app (detalle en Ajustes › Registro de errores)")
        except Exception:  # noqa: BLE001
            pass
    ti.use_bubble = ti.use_handles = True
    ti._native_skip = True
    ti.focus = True


def install() -> None:
    if not IS_ANDROID:
        return
    from kivy.uix.textinput import TextInput
    base = TextInput._on_focus

    def _on_focus(self, instance, value, *largs):
        if value and wants_native(self):
            self.use_bubble = self.use_handles = False   # sin cuadros «copy / paste» de Kivy
            Clock.schedule_once(lambda *_: setattr(self, "focus", False), 0)
            Clock.schedule_once(lambda *_: _safe_edit(self), 0)
            return None
        return base(self, instance, value, *largs)

    TextInput._on_focus = _on_focus


def _safe_edit(ti) -> None:
    state = {"shown": False}
    try:
        edit(ti, state)
    except Exception as exc:  # noqa: BLE001
        _fallback(ti, f"{type(exc).__name__}: {exc}")
        return
    # Si en 1,5 s el cuadro no apareció (error en el hilo de Android), teclado de la app.
    Clock.schedule_once(lambda *_: None if state["shown"] else _fallback(
        ti, state.get("error") or "el cuadro no apareció"), 1.5)


def _title(ti) -> str:
    return (getattr(ti, "hint_text", "") or "Escribir").strip()


def edit(ti, state: dict | None = None) -> None:
    """Abre el cuadro nativo (clase Java NativeInput) con el texto del campo; al aceptar,
    el texto vuelve al campo."""
    from jnius import PythonJavaClass, autoclass, java_method  # type: ignore

    state = state if state is not None else {}
    flt = getattr(ti, "input_filter", None)

    def deliver(text: str):
        if flt == "int":
            text = "".join(ch for ch in text if ch.isdigit() or ch == "-")
        elif flt == "float":
            text = "".join(ch for ch in text.replace(",", ".") if ch.isdigit() or ch in ".-")
        ti.text = text

    class Callback(PythonJavaClass):
        __javainterfaces__ = ["org/rubus/fenorubus/NativeInput$Callback"]
        __javacontext__ = "app"

        @java_method("()V")
        def onShown(self):  # noqa: N802
            state["shown"] = True

        @java_method("(Ljava/lang/String;)V")
        def onResult(self, text):  # noqa: N802
            Clock.schedule_once(lambda *_: deliver(str(text)), 0)

        @java_method("(Ljava/lang/String;)V")
        def onError(self, error):  # noqa: N802
            state["error"] = str(error)

    # El callback se crea en el hilo de Kivy (desde otros hilos pyjnius no encuentra las
    # clases de la app) y se mantiene vivo mientras el cuadro está abierto.
    cb = Callback()
    _alive[:] = [cb]
    NativeInput = autoclass("org.rubus.fenorubus.NativeInput")
    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    NativeInput.show(activity, _title(ti), ti.text or "", input_type_for(ti), bool(ti.multiline), cb)
