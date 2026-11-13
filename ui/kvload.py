"""
ui/kvload.py
============
Carga del diseño (ui/kv/*.kv, más de 4000 líneas en total) en segundo plano.

Kivy compila cada expresión del .kv antes de mostrar el primer cuadro: en el teléfono eran
~4 s con la pantalla de carga quieta. Aquí la compilación (lo lento: texto → código) corre
en un hilo mientras se ve la animación de apertura, y el registro de las reglas (rápido)
se hace en el hilo de Kivy, igual que Builder.load_string.

    kvload.start(paths)       # al abrir (build): lista de archivos .kv, en orden
    kvload.ready()            # ¿ya está compilado?
    kvload.apply()            # en el hilo de Kivy, antes de crear pantallas del diseño
"""
from __future__ import annotations

import glob
import os
import threading
import time
from functools import partial

_state: dict = {"parsed": [], "error": None, "applied": False, "thread": None, "paths": [], "ms": 0.0}


def design_files(folder: str) -> list[str]:
    """Los .kv del diseño: base.kv primero (piezas que usan los demás), luego por nombre."""
    files = sorted(glob.glob(os.path.join(folder, "*.kv")))
    return sorted(files, key=lambda p: os.path.basename(p) != "base.kv")


def start(paths) -> None:
    """Empieza a compilar los .kv en un hilo (las directivas #:import también corren ahí)."""
    if _state["thread"] is not None:
        return
    paths = [paths] if isinstance(paths, str) else list(paths)
    _state["paths"] = paths

    def work():
        t0 = time.perf_counter()
        try:
            from kivy.lang.parser import Parser
            for path in paths:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                _state["parsed"].append((path, Parser(content=content, filename=path)))
        except BaseException as exc:  # noqa: BLE001 - se informa al aplicar
            _state["error"] = exc
        _state["ms"] = (time.perf_counter() - t0) * 1000

    th = threading.Thread(target=work, name="kv-parse", daemon=True)
    _state["thread"] = th
    th.start()


def ready() -> bool:
    th = _state["thread"]
    return _state["applied"] or (th is not None and not th.is_alive())


def _register(path: str, parser) -> None:
    """= Builder.load_string, sin volver a compilar."""
    from kivy.factory import Factory
    from kivy.lang import Builder
    Builder.rules.extend(parser.rules)
    Builder._clear_matchcache()
    for name, cls, template in parser.templates:
        Builder.templates[name] = (cls, template, path)
        Factory.register(name, cls=partial(Builder.template, name), is_template=True, warn=True)
    for name, baseclasses in parser.dynamic_classes.items():
        Factory.register(name, baseclasses=baseclasses, filename=path, warn=True)
    if parser.templates or parser.dynamic_classes or parser.rules:
        Builder.files.append(path)


def apply() -> None:
    """Registra las reglas ya compiladas (si aún no termina, espera). Si algo falló en el hilo,
    los archivos que faltan se cargan como siempre."""
    if _state["applied"]:
        return
    from kivy.lang import Builder
    th = _state["thread"]
    if th is not None:
        th.join()
    done = set()
    for path, parser in _state["parsed"]:
        _register(path, parser)
        done.add(path)
    if _state["error"] is not None:
        print("kv en segundo plano falló; se carga como siempre:", _state["error"])
    for path in _state["paths"]:
        if path not in done:
            Builder.load_file(path)
    _state["applied"] = True
    try:
        import perf
        perf.record("apertura.diseño (en segundo plano)", _state["ms"])
    except Exception:  # noqa: BLE001
        pass
