"""
perf.py
=======
Registro de tiempos de la app, para saber DÓNDE se va el tiempo antes de optimizar.

    with perf.timed("muestreo.refrescar"):      # o @perf.timed("…") sobre una función
        ...
    perf.add("drive.pedidos")                    # contador (p. ej. pedidos a Drive)
    perf.note("sync", "PhenoRubus: 12 ensayos")  # una línea suelta

Guarda lo último en «logs/tiempos.log» (se ve y se envía desde Ajustes › Registro de
errores › «Tiempos»). Cuesta microsegundos por medición; nunca lanza errores.

Puro Python (sin Kivy): lo usan la app y las pruebas.
"""
from __future__ import annotations

import datetime as _dt
import functools
import os
import threading
import time

MAX_LINES = 600          # últimas mediciones en memoria (y en el archivo)
MIN_MS = 1.0             # lo que demora menos no se anota línea a línea (sí en el resumen)

_lock = threading.Lock()
_lines: list[str] = []
_stats: dict[str, list] = {}       # nombre -> [veces, total ms, máx ms, último ms]
_counts: dict[str, float] = {}
_loaded = False
_dirty = 0


def _path() -> str:
    from platform_utils import data_subdir
    return os.path.join(data_subdir("logs"), "tiempos.log")


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_path(), encoding="utf-8", errors="replace") as f:
            _lines[:0] = [ln.rstrip("\n") for ln in f.readlines()[-MAX_LINES:]]
    except OSError:
        pass
    _lines.append(f"--- apertura {_dt.datetime.now():%Y-%m-%d %H:%M:%S}")


def _write(force: bool = False) -> None:
    """A disco cada tanto (no en cada medición: escribir también cuesta)."""
    global _dirty
    _dirty += 1
    if not force and _dirty < 25:
        return
    _dirty = 0
    try:
        tmp = _path() + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(_lines[-MAX_LINES:]) + "\n")
        os.replace(tmp, _path())
    except OSError:
        pass


def record(name: str, ms: float, extra: str = "") -> None:
    try:
        with _lock:
            _load()
            st = _stats.setdefault(name, [0, 0.0, 0.0, 0.0])
            st[0] += 1
            st[1] += ms
            st[2] = max(st[2], ms)
            st[3] = ms
            if ms >= MIN_MS:
                _lines.append(f"{_dt.datetime.now():%H:%M:%S} {ms:9.1f} ms  {name}" + (f"  · {extra}" if extra else ""))
                del _lines[:-MAX_LINES]
                _write(force=ms >= 2000)        # lo muy lento queda en disco de inmediato
    except Exception:  # noqa: BLE001 - medir nunca rompe la app
        pass


def note(name: str, text: str) -> None:
    try:
        with _lock:
            _load()
            _lines.append(f"{_dt.datetime.now():%H:%M:%S}               {name}  · {text}")
            del _lines[:-MAX_LINES]
            _write()
    except Exception:  # noqa: BLE001
        pass


def add(name: str, n: float = 1) -> None:
    with _lock:
        _counts[name] = _counts.get(name, 0) + n


def counts() -> dict:
    with _lock:
        return dict(_counts)


def since(before: dict) -> dict:
    """Contadores que cambiaron desde `before` (= counts() de antes)."""
    now = counts()
    return {k: v - before.get(k, 0) for k, v in now.items() if v != before.get(k, 0)}


class timed:
    """Mide un bloque (with) o una función (decorador). extra: texto fijo o función que lo da."""

    def __init__(self, name: str, extra=""):
        self.name, self.extra = name, extra

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc):
        extra = self.extra() if callable(self.extra) else self.extra
        record(self.name, (time.perf_counter() - self.t0) * 1000, extra or "")
        return False

    def __call__(self, fn):
        name = self.name

        @functools.wraps(fn)
        def wrapper(*a, **k):
            t0 = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                record(name, (time.perf_counter() - t0) * 1000)
        return wrapper


def flush() -> None:
    with _lock:
        _write(force=True)


def summary() -> list[str]:
    """Resumen por medición, de la que más tiempo suma a la que menos."""
    with _lock:
        rows = sorted(_stats.items(), key=lambda kv: -kv[1][1])
        out = [f"{'total':>9} {'veces':>6} {'prom.':>8} {'máx.':>8}  medición"]
        for name, (n, total, mx, _last) in rows:
            out.append(f"{_fmt(total):>9} {n:>6} {_fmt(total / n):>8} {_fmt(mx):>8}  {name}")
        if _counts:
            out.append("")
            out += [f"{int(v) if float(v).is_integer() else round(v, 1):>9}  {k}" for k, v in sorted(_counts.items())]
        return out


def _fmt(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def full_text() -> str:
    """Resumen de esta apertura + las últimas mediciones (también de aperturas anteriores)."""
    with _lock:
        _load()
        tail = list(_lines[-MAX_LINES:])
    return ("=== Tiempos · resumen de esta apertura\n" + "\n".join(summary())
            + "\n\n=== Tiempos · últimas mediciones\n" + "\n".join(tail))


def reset() -> None:
    """Para las pruebas."""
    global _loaded, _dirty
    with _lock:
        _lines.clear()
        _stats.clear()
        _counts.clear()
        _loaded, _dirty = False, 0
