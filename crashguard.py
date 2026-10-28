"""
crashguard.py
=============
Red de seguridad: un error de Python en la interfaz o en un hilo de fondo ya no
cierra la app. Se registra en «logs/errores.log» (visible en Ajustes › Registro de
errores) y se avisa con un mensaje breve.

Lo que sí cierra la app (un fallo nativo o de Java, o Android que la mata) no alcanza a
pasar por aquí. Para eso queda el rastro del arranque («logs/arranque.log», un paso por
línea, escrito al instante): si la apertura anterior no llegó al final, la siguiente lo
sabe (`previous_failure`), abre en modo seguro y muestra dónde se quedó. Los fallos
nativos de Python quedan además en «logs/nativo.log» (faulthandler).
"""
from __future__ import annotations

import datetime as _dt
import faulthandler
import os
import sys
import threading
import traceback

from platform_utils import app_version, data_subdir

MAX_BYTES = 200_000
_notify = None   # función(texto) para avisar en pantalla
_trail = None    # archivo del rastro del arranque (abierto mientras arranca)
_native = None   # archivo de faulthandler
_previous: list[str] | None = None   # rastro de la apertura anterior si no terminó
DONE = "ARRANQUE COMPLETO"
PAUSED = "en segundo plano"


def log_path() -> str:
    return os.path.join(data_subdir("logs"), "errores.log")


def record(exc: BaseException, where: str = "") -> str:
    """Guarda el error con su traza y devuelve un resumen de una línea."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    summary = f"{type(exc).__name__}: {exc}"[:200]
    try:
        path = log_path()
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"=== {_dt.datetime.now():%Y-%m-%d %H:%M:%S} · v{app_version()} · {where}\n"
                    f"{tb}\n")
    except OSError:
        pass
    return summary


def entries(limit: int = 20) -> list[str]:
    """Últimos errores (más reciente primero), cada uno con su traza abreviada."""
    try:
        with open(log_path(), encoding="utf-8") as f:
            blocks = [b.strip() for b in f.read().split("=== ") if b.strip()]
    except OSError:
        return []
    out = []
    for b in reversed(blocks[-limit:]):
        head, _, body = b.partition("\n")
        lines = [ln for ln in body.splitlines() if ln.strip()]
        # cabecera + últimas líneas de la traza (archivo:línea y el error)
        out.append(head + "\n" + "\n".join(lines[-6:]))
    return out


def clear() -> None:
    for p in (log_path(), log_path() + ".1"):
        try:
            os.remove(p)
        except OSError:
            pass


def _trail_path() -> str:
    return os.path.join(data_subdir("logs"), "arranque.log")


def _native_path() -> str:
    return os.path.join(data_subdir("logs"), "nativo.log")


def begin() -> None:
    """Al abrir la app: lee el rastro anterior (¿terminó?) y empieza uno nuevo."""
    global _trail, _native, _previous
    try:
        with open(_trail_path(), encoding="utf-8") as f:
            prev = [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        prev = []
    _previous = prev if prev and not prev[-1].endswith((DONE, PAUSED)) else None
    native = ""
    try:
        with open(_native_path(), encoding="utf-8", errors="replace") as f:
            native = f.read().strip()
    except OSError:
        pass
    if native:
        # Fallo nativo de la vez anterior → al registro de errores (visible en Ajustes).
        _append(f"=== {_dt.datetime.now():%Y-%m-%d %H:%M:%S} · v{app_version()} · cierre nativo\n"
                f"{native[-4000:]}\n")
    try:
        _native = open(_native_path(), "w", encoding="utf-8")
        faulthandler.enable(_native, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        pass
    if _previous:
        _append(f"=== {_dt.datetime.now():%Y-%m-%d %H:%M:%S} · v{app_version()} · la app se cerró "
                f"al abrir\nÚltimos pasos:\n" + "\n".join(_previous[-8:]) + "\n")
    try:
        _trail = open(_trail_path(), "w", encoding="utf-8")
    except OSError:
        _trail = None
    step(f"abre v{app_version()}")


def step(name: str) -> None:
    """Anota un paso del arranque (se escribe al disco al tiro)."""
    if _trail is None:
        return
    try:
        _trail.write(f"{_dt.datetime.now():%H:%M:%S} {name}\n")
        _trail.flush()
        os.fsync(_trail.fileno())
    except (OSError, ValueError):
        pass


def finish() -> None:
    """La apertura terminó bien: la próxima no entra en modo seguro."""
    global _trail
    step(DONE)
    if _trail is not None:
        try:
            _trail.close()
        except OSError:
            pass
        _trail = None


def previous_failure() -> list[str] | None:
    """Pasos de la apertura anterior si se cerró antes de terminar (si no, None)."""
    return _previous


def _append(text: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def install(notify=None) -> None:
    """Instala los manejadores de Kivy (bucle de la interfaz) y de hilos."""
    global _notify
    _notify = notify
    from kivy.base import ExceptionHandler, ExceptionManager

    class _Guard(ExceptionHandler):
        def handle_exception(self, exc):
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                return ExceptionManager.RAISE
            summary = record(exc, "interfaz")
            if _notify:
                try:
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda *_: _notify(
                        f"Se evitó un cierre por un error: {summary[:90]}"), 0)
                except Exception:  # noqa: BLE001
                    pass
            return ExceptionManager.PASS

    ExceptionManager.add_handler(_Guard())

    def thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        record(args.exc_value, f"hilo {getattr(args.thread, 'name', '?')}")

    threading.excepthook = thread_hook
    prev_hook = sys.excepthook

    def main_hook(tp, value, tb):
        if value is not None and not issubclass(tp, (KeyboardInterrupt, SystemExit)):
            record(value, "arranque")
        prev_hook(tp, value, tb)

    sys.excepthook = main_hook
