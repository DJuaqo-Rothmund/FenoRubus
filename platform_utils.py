"""
platform_utils.py
=================
Detección de plataforma y rutas de datos compartidas entre la app (Activity)
y el servicio de recordatorios (proceso Python independiente en Android).
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

APP_NAME = "PhenoRubus"
# Carpeta de datos en escritorio: se conserva el nombre original para no «perder» datos.
DATA_DIR_NAME = "FenoRubus"
APP_SLUG = "fenorubus"


def is_android() -> bool:
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ \
        or hasattr(sys, "getandroidapilevel")


IS_ANDROID = is_android()


def android_context():
    """Context Android válido tanto desde la Activity como desde un Service p4a."""
    from jnius import autoclass, cast  # type: ignore
    try:
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        if activity is not None:
            return cast("android.content.Context", activity)
    except Exception:
        pass
    service = autoclass("org.kivy.android.PythonService").mService
    return cast("android.content.Context", service)


def android_api_level() -> int:
    if not IS_ANDROID:
        return 0
    from jnius import autoclass  # type: ignore
    return int(autoclass("android.os.Build$VERSION").SDK_INT)


_crop_dir: str | None = None
_crop_set = False


def set_crop_dir(subdir: str | None) -> None:
    """Carpeta de datos del cultivo activo (crops.activate). None = la raíz (frambuesa,
    donde siempre estuvieron sus datos)."""
    global _crop_dir, _crop_set
    _crop_dir, _crop_set = subdir, True


def get_data_dir() -> str:
    """
    Directorio de datos del cultivo activo: la raíz (frambuesa) o «cultivos/<cultivo>».
    En el servicio de recordatorios (otro proceso) vale el último cultivo abierto.
    """
    if not _crop_set:
        import crops
        crops.activate(global_get("crop", crops.DEFAULT))
    path = get_base_dir()
    if _crop_dir:
        path = os.path.join(path, _crop_dir)
        os.makedirs(path, exist_ok=True)
    return path


def crop_data_dir(subdir: str | None) -> str:
    """Carpeta de datos de un cultivo cualquiera, SIN cambiar el cultivo activo de la app
    (sincronizar los otros cultivos en segundo plano no debe tocar el abierto)."""
    path = get_base_dir()
    if subdir:
        path = os.path.join(path, subdir)
        os.makedirs(path, exist_ok=True)
    return path


def get_base_dir() -> str:
    """
    Directorio persistente y privado de la app (raíz común a todos los cultivos).

    * Android: Context.getFilesDir() (mismo valor para Activity y Service).
    * Escritorio: $FENORUBUS_DATA o ~/.local/share/fenorubus (o %APPDATA%).
    """
    override = os.environ.get("FENORUBUS_DATA")
    if override:
        path = override
    elif IS_ANDROID:
        path = android_context().getFilesDir().getAbsolutePath()
    elif sys.platform.startswith("win"):
        path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), DATA_DIR_NAME)
    elif sys.platform == "darwin":
        path = os.path.expanduser(f"~/Library/Application Support/{DATA_DIR_NAME}")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        path = os.path.join(base, APP_SLUG)
    os.makedirs(path, exist_ok=True)
    return path


def data_subdir(*parts: str) -> str:
    path = os.path.join(get_data_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def resource_path(*parts: str) -> str:
    """Ruta a recursos empaquetados junto al código (templates, modelos)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "informe"


def app_version() -> str:
    """Versión instalada (la escribe CI en version.txt; «dev» al ejecutar desde el código)."""
    try:
        with open(resource_path("version.txt"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


# ------------------------------------------------------------------ ajustes globales
# Valen para toda la app, sobre todos los cultivos: cultivo elegido, estilo y la cuenta de
# Google Drive (se conecta una vez, en la pantalla de cultivos). Archivo JSON en la raíz.
GLOBAL_FILE = "app_global.json"
_global: dict | None = None
_global_at: str | None = None     # archivo leído (cambia en pruebas con otra carpeta)


def _global_path() -> str:
    return os.path.join(get_base_dir(), GLOBAL_FILE)


def _load_global() -> dict:
    global _global, _global_at
    path = _global_path()
    if _global is None or _global_at != path:
        import json
        try:
            with open(path, encoding="utf-8") as f:
                _global = json.load(f)
        except (OSError, ValueError):
            _global = _legacy_global()
        _global_at = path
    return _global


def _legacy_global() -> dict:
    """Primera vez: la cuenta de Drive que ya tenía la app (base común de frambuesa)."""
    import json
    import sqlite3
    out: dict = {}
    path = os.path.join(get_base_dir(), "comun.sqlite3")
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(path)
        try:
            for key, value in con.execute(
                    "SELECT key, value FROM settings WHERE key IN (%s)" % ",".join("?" * len(GLOBAL_KEYS)),
                    GLOBAL_KEYS):
                try:
                    out[key] = json.loads(value)
                except (TypeError, ValueError):
                    out[key] = value
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return out


GLOBAL_KEYS = ("drive_enabled", "drive_account", "drive_wifi_only")


def global_get(key: str, default=None):
    return _load_global().get(key, default)


def global_set(key: str, value) -> None:
    import json
    data = _load_global()
    data[key] = value
    tmp = _global_path() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _global_path())


def reset_global_cache() -> None:
    """Pruebas: vuelve a leer el archivo (otra carpeta de datos)."""
    global _global, _crop_set, _crop_dir
    _global, _crop_set, _crop_dir = None, False, None
