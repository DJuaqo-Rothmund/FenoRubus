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
    """Abre el cuadro nativo con el texto del campo; al aceptar, lo devuelve."""
    state = state if state is not None else {}
    from android.runnable import run_on_ui_thread  # type: ignore
    from jnius import PythonJavaClass, autoclass, cast, java_method  # type: ignore

    Activity = autoclass("org.kivy.android.PythonActivity").mActivity
    Builder = autoclass("android.app.AlertDialog$Builder")
    EditText = autoclass("android.widget.EditText")
    String = autoclass("java.lang.String")
    FrameLayout = autoclass("android.widget.FrameLayout")
    WindowParams = autoclass("android.view.WindowManager$LayoutParams")
    flt = getattr(ti, "input_filter", None)

    def cs(text):
        return cast("java.lang.CharSequence", String(text))

    def deliver(text: str):
        if flt == "int":
            text = "".join(ch for ch in text if ch.isdigit() or ch == "-")
        elif flt == "float":
            text = "".join(ch for ch in text.replace(",", ".") if ch.isdigit() or ch in ".-")
        ti.text = text

    class Click(PythonJavaClass):
        __javainterfaces__ = ["android/content/DialogInterface$OnClickListener"]
        __javacontext__ = "app"

        def __init__(self, fn):
            super().__init__()
            self.fn = fn

        @java_method("(Landroid/content/DialogInterface;I)V")
        def onClick(self, dialog, which):  # noqa: N802
            try:
                self.fn()
            finally:
                _alive.clear()

    # Los listeners Java se crean en el hilo de Kivy (desde otros hilos pyjnius no
    # encuentra las clases de la app); Android los llama después en su hilo de interfaz.
    box: dict = {}

    def ok():
        text = box["field"].getText().toString()
        Clock.schedule_once(lambda *_: deliver(text), 0)

    ok_l, cancel_l = Click(ok), Click(lambda: None)
    _alive[:] = [ok_l, cancel_l]

    @run_on_ui_thread
    def show():
        try:
            _show()
            state["shown"] = True
        except Exception as exc:  # noqa: BLE001 - se informa y se usa el teclado de la app
            state["error"] = f"{type(exc).__name__}: {exc}"

    def _show():
        field = box["field"] = EditText(Activity)
        field.setInputType(input_type_for(ti))
        field.setText(cs(ti.text or ""))
        field.setSelection(field.getText().length())
        if ti.multiline:
            field.setMinLines(3)
            field.setMaxLines(8)
        else:
            field.setSingleLine(True)
        pad = int(20 * Activity.getResources().getDisplayMetrics().density)
        frame = FrameLayout(Activity)
        frame.setPadding(pad, pad // 2, pad, 0)
        frame.addView(field)
        builder = Builder(Activity)
        builder.setTitle(cs(_title(ti)))
        builder.setView(frame)
        builder.setPositiveButton(cs("Aceptar"), ok_l)
        builder.setNegativeButton(cs("Cancelar"), cancel_l)
        dialog = builder.create()
        dialog.getWindow().setSoftInputMode(WindowParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE)
        dialog.show()
        field.requestFocus()

    show()
