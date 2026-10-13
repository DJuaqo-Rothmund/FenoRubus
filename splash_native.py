"""
splash_native.py
================
La pantalla de carga animada de Android (Lottie, assets/splash_lottie.json) bajo control
de la app:

* `hold()`: lo antes posible al arrancar. python-for-android la quitaría 5 s después de
  iniciar Python, esté lista la app o no; así se queda hasta que la app termina de
  precargar (y Kivy tampoco la quita en su primer cuadro: ver main.py).
* `lottie_time()`: segundos de la animación nativa (None si ya no está a la vista), para
  que el logo de Kivy, dibujado detrás, vaya en el mismo cuadro.
* `remove()`: la quita; debajo queda el logo de Kivy en el mismo instante de la animación.

En el computador no hay pantalla nativa: todo devuelve None/False y no hace nada.
"""
from __future__ import annotations

from platform_utils import IS_ANDROID

FPS = 60   # = ui/splash_timeline.LOTTIE_FPS (no se importa: este módulo va antes que Kivy)
_cls = {}


def _java(name):
    if name not in _cls:
        from jnius import autoclass  # type: ignore
        _cls[name] = autoclass(name)
    return _cls[name]


def _activity():
    return _java("org.kivy.android.PythonActivity").mActivity


def hold() -> bool:
    if not IS_ANDROID:
        return False
    try:
        return bool(_java("org.rubus.fenorubus.SplashHold").hold(_activity()))
    except Exception as exc:  # noqa: BLE001 (sin esto la app arranca igual)
        print("splash hold:", exc)
        return False


def lottie_time() -> float | None:
    if not IS_ANDROID:
        return None
    try:
        frame = _java("org.rubus.fenorubus.SplashHold").lottieFrame()
    except Exception:  # noqa: BLE001
        return None
    return frame / FPS if frame >= 0 else None


def remove() -> None:
    if not IS_ANDROID:
        return
    try:
        _activity().removeLoadingScreen()
    except Exception as exc:  # noqa: BLE001
        print("splash remove:", exc)
