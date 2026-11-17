"""
clip.py
=======
Portapapeles y menú «copiar / pegar» en español.

* Kivy en Android lee el portapapeles mal (al pegar convierte un objeto Java con
  `.encode()` y falla, o queda esperando): aquí se usa ClipboardManager de Android
  directamente y se corrige el Clipboard de Kivy para que todos los campos peguen bien.
* Los cuadritos de Kivy «Cut / Copy / Paste / Select All» salen en español.
"""
from __future__ import annotations

import threading

from platform_utils import IS_ANDROID

LABELS = {"cut": "Cortar", "copy": "Copiar", "paste": "Pegar", "selectall": "Seleccionar todo"}

_mgr = {"cm": None}
_local = {"text": ""}       # respaldo si el sistema no responde (y en escritorio sin portapapeles)


def _manager():
    """ClipboardManager creado en el hilo de Android (fuera de él falla en algunos equipos)."""
    if _mgr["cm"] is not None:
        return _mgr["cm"]
    from android.runnable import run_on_ui_thread  # type: ignore
    from jnius import autoclass, cast  # type: ignore
    done = threading.Event()

    @run_on_ui_thread
    def make():
        try:
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            Context = autoclass("android.content.Context")
            _mgr["cm"] = cast("android.content.ClipboardManager",
                              cast("android.app.Activity", act).getSystemService(Context.CLIPBOARD_SERVICE))
        finally:
            done.set()

    make()
    done.wait(2)
    return _mgr["cm"]


def copy(text: str) -> None:
    text = "" if text is None else str(text)
    _local["text"] = text
    if IS_ANDROID:
        from jnius import autoclass  # type: ignore
        cm = _manager()
        if cm is not None:
            ClipData = autoclass("android.content.ClipData")
            String = autoclass("java.lang.String")
            cm.setPrimaryClip(ClipData.newPlainText(String("AeonCrop"), String(text)))
        return
    try:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(text)
    except Exception:  # noqa: BLE001
        pass


def paste() -> str:
    if IS_ANDROID:
        from jnius import autoclass  # type: ignore
        cm = _manager()
        clip = cm.getPrimaryClip() if cm is not None else None
        if clip is not None and clip.getItemCount() > 0:
            ctx = autoclass("org.kivy.android.PythonActivity").mActivity.getApplicationContext()
            got = clip.getItemAt(0).coerceToText(ctx)
            return "" if got is None else str(got.toString())
        return _local["text"]
    try:
        from kivy.core.clipboard import Clipboard
        return Clipboard.paste() or _local["text"]
    except Exception:  # noqa: BLE001
        return _local["text"]


def table(text: str) -> list[list[str]]:
    """Texto copiado de Excel / Sheets: filas por línea, columnas por tabulación."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not text:
        return []
    return [line.split("\t") for line in text.split("\n")]


def install() -> None:
    """Cuadritos de copiar/pegar de Kivy en español y, en Android, con el portapapeles real."""
    from kivy.uix.textinput import TextInputCutCopyPaste
    base = TextInputCutCopyPaste.on_parent

    def on_parent(self, instance, value):
        for key, label in LABELS.items():
            b = getattr(self, "but_" + key, None)
            if b is not None:
                b.text = label
        return base(self, instance, value)

    TextInputCutCopyPaste.on_parent = on_parent
    if not IS_ANDROID:
        return
    from kivy.core import clipboard as kc
    cb = kc.Clipboard

    def _copy(data=""):
        try:
            copy(data)
        except Exception:  # noqa: BLE001
            _local["text"] = str(data)

    def _paste():
        try:
            return paste()
        except Exception:  # noqa: BLE001
            return _local["text"]

    try:
        cb.copy = _copy
        cb.paste = _paste
    except Exception:  # noqa: BLE001
        pass
