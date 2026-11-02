"""
PhenoRubus — Cuaderno de campo digital para el seguimiento fenológico y
biométrico de ensayos en frambueso (Rubus idaeus).

Punto de entrada y navegación KivyMD.

    python main.py                 # escritorio (PC)
    buildozer android debug        # APK (ver README.md)
"""
from __future__ import annotations

import gc
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import datetime as _dt
from functools import cached_property

os.environ.setdefault("KIVY_LOG_MODE", "PYTHON")
if os.name == "nt":
    # Windows: gráficos por ANGLE (DirectX), como Chrome. Funciona también en PCs de empresa,
    # escritorios remotos o máquinas virtuales que solo traen OpenGL 1.1.
    os.environ.setdefault("KIVY_GL_BACKEND", "angle_sdl2")

# Lo primero: la pantalla de carga animada de Android se queda hasta que la app termine de
# precargar (si no, el sistema la quitaría a los 5 s, en medio de la carga).
import splash_native  # noqa: E402

splash_native.hold()

from kivy.config import Config  # noqa: E402

# Rendimiento en gama media/baja: sin antialiasing multisample (MSAA duplica el
# costo de relleno en GPUs modestas; en pantallas de alta densidad no se nota).
Config.set("graphics", "multisamples", "0")
Config.set("kivy", "exit_on_escape", "0")
# Menos registro: cada línea de log de Kivy pasa por logcat y cuesta en teléfonos básicos.
Config.set("kivy", "log_level", "warning")

from kivy.clock import Clock, mainthread  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.lang import Builder  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.utils import platform  # noqa: E402
from kivymd.app import MDApp  # noqa: E402
from kivymd.uix.label import MDLabel  # noqa: E402
from kivymd.uix.screenmanager import MDScreenManager  # noqa: E402
from kivymd.uix.snackbar import MDSnackbar  # noqa: E402
from kivy.uix.floatlayout import FloatLayout  # noqa: E402
from kivy.uix.image import Image  # noqa: E402
from kivy.uix.screenmanager import FadeTransition, NoTransition  # noqa: E402

from kivy.base import EventLoopBase  # noqa: E402

from ui import theme  # noqa: E402

# Kivy quita la pantalla de carga en su primer cuadro; aquí la quita la app, cuando todo
# está precargado y el logo de Kivy va en el mismo cuadro que la animación nativa.
# Función con su nombre real (no lambda): el reloj de Kivy la busca por nombre en el
# objeto; con una lambda («<lambda>») fallaba en cada apertura.


def remove_android_splash(self, *args):
    """No hace nada: la pantalla de carga la quita splash_native.remove()."""


EventLoopBase.remove_android_splash = remove_android_splash

# Recolector de basura: menos revisiones de objetos nuevos (cada widget crea cientos) y
# lo ya cargado (pantallas, KivyMD) se congela para que las revisiones completas no lo
# recorran (ver _gc_freeze).
gc.set_threshold(5000, 15, 15)


def _gc_freeze():
    gc.collect(1)        # solo lo reciente (rápido); luego todo lo vivo queda fuera
    gc.freeze()

theme.install_palette()  # antes de cargar widgets KivyMD con color

from android_bridge import create_media, make_thumbnail, request_runtime_permissions  # noqa: E402
from notifications import ReminderManager  # noqa: E402
from platform_utils import data_subdir, get_data_dir, resource_path  # noqa: E402
from ui.screens import (AILabScreen, CropScreen, HomeScreen, LaunchScreen,  # noqa: E402
                        MeasureScreen, ObservationScreen,
                        PinForm, SectorsScreen, SettingsScreen, SplashScreen, StartScreen, TimelineScreen,
                        VarietyScreen,
                        WorkspacesScreen, form_dialog)
from workspaces import Workspaces  # noqa: E402
from crashguard import PAUSED, step as _step  # noqa: E402

MIME = {".html": "text/html", ".zip": "application/zip", ".sqlite3": "application/x-sqlite3",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf"}


class FenoRubusApp(MDApp):
    title = "AeonCrop"

    # ------------------------------------------------------------ build
    def build(self):
        import crashguard
        crashguard.begin()     # rastro del arranque: si la vez anterior se cerró, modo seguro
        crashguard.install(notify=lambda text: self.toast(text))
        self.safe_mode = crashguard.previous_failure() is not None
        import native_input
        native_input.install()   # Android: campos de texto con el teclado real del teléfono
        # Cultivo (PhenoRubus, PhenoBlue o PhenoCran) y estilo: los últimos elegidos. Al abrir
        # se muestra igual la pantalla de cultivos; el último queda precargado detrás.
        import crops
        from platform_utils import global_get
        crops.activate(global_get("crop", crops.DEFAULT))
        theme.configure(crops.current().id, global_get("style", theme.DEFAULT_STYLE))
        self._loaded = (crops.current().id, theme.style)
        theme.apply(self.theme_cls)
        theme.speed_up_theme_bindings()   # crear pantallas no se vuelve más lento con el uso
        Clock.schedule_interval(lambda *_: theme.purge_theme_observers(self.theme_cls), 20)
        if platform not in ("android", "ios"):
            Window.size = (412, 860)
        # Ensayos y predios: cada uno con su base; la común guarda IA, escala y ajustes.
        self.workspaces = Workspaces(get_data_dir())
        self._dbs: dict = {}
        self.workspace = self.workspaces.last()
        crashguard.step(f"base {self.workspace.get('code')}")
        self.db = self.open_db(self.workspace)
        self.reminders = ReminderManager(self.db)
        self.media = create_media(data_subdir("tmp"), self._desktop_file_chooser)
        self.week = self.db.current_week()
        self.season = self.week["season"]
        self._history: list[str] = []
        self.workers = ThreadPoolExecutor(max_workers=2)  # miniaturas y fotos
        self._file_manager = None

        crashguard.step("interfaz")
        Builder.load_file(resource_path("ui", "layout.kv"))
        # Fundido corto: con pantallas translúcidas un deslizamiento superpondría contenidos.
        # Cambio de pantalla instantáneo: un fundido dibuja las DOS pantallas en texturas
        # intermedias en cada cuadro, lo más costoso para GPUs modestas.
        self.sm = MDScreenManager(transition=NoTransition())
        # Primero solo la pantalla de apertura (los tres frutos, igual a la de Android): el
        # primer cuadro aparece de inmediato; la de cultivos se arma en on_start.
        self.sm.add_widget(LaunchScreen(name="launch"))
        self.home = None
        Window.bind(on_keyboard=self._on_keyboard)
        Window.clearcolor = theme.c(theme.SPLASH_BG)  # sin destello entre presplash e inicio
        # Fondo difuminado (color de la fruta o del estilo) detrás de las pantallas translúcidas.
        root = FloatLayout()
        self._bg = Image(source=theme.BACKGROUND, fit_mode="fill")
        root.add_widget(self._bg)
        root.add_widget(self.sm)
        return root

    # ------------------------------------------------------- cultivos y estilos
    def _load_module(self, crop_id: str) -> None:
        """Abre los datos del cultivo y rehace la interfaz con sus colores (las pantallas
        se vuelven a construir: precarga en _preload_steps)."""
        import crops
        # Las bases del cultivo anterior no se cierran a la fuerza: una subida a Drive en
        # curso podría estar usándolas (se liberan solas).
        self._dbs = {}
        import sys
        if "ui.boxes" in sys.modules:       # IA+: las marcas son de cada cultivo
            sys.modules["ui.boxes"]._store = None
        for name in ("classifier", "reports", "drive", "pin", "sync"):
            self.__dict__.pop(name, None)
        for name in list(self.sm.screen_names):
            if name not in ("crops", "launch", "splash"):
                self.sm.remove_widget(self.sm.get_screen(name))
        self.home = None
        self._history = []
        crops.activate(crop_id)
        theme.configure(crop_id, None)
        theme.apply(self.theme_cls)
        self._bg.source = theme.BACKGROUND
        Window.clearcolor = theme.c(theme.SPLASH_BG)
        self.workspaces = Workspaces(get_data_dir())
        self.workspace = self.workspaces.last()
        self.db = self.open_db(self.workspace)
        self.reminders = ReminderManager(self.db)
        self.week = self.db.current_week()
        self.season = self.week["season"]
        self._loaded = (crop_id, theme.style)
        self._preloaded = False
        self._preload = self._preload_steps()

    def open_crops(self):
        """Pantalla de cultivos (desde el inicio de un módulo o con «atrás»)."""
        self._history = []
        if not self.sm.has_screen("crops"):
            self.sm.add_widget(CropScreen(name="crops"))
        self.sm.current = "crops"

    def choose_crop(self, crop_id: str) -> None:
        """Entra al módulo del cultivo: su pantalla de carga (con su logo animado) y luego
        su inicio. Si es otro cultivo, sus datos e interfaz se preparan detrás."""
        import crops
        from platform_utils import global_set
        global_set("crop", crop_id)
        if self._loaded != (crop_id, theme.style):
            self._load_module(crop_id)
        if self.sm.has_screen("splash"):
            self.sm.remove_widget(self.sm.get_screen("splash"))
        splash = SplashScreen(name="splash")
        self.sm.add_widget(splash)
        self.sm.current = "splash"
        splash.ids.logo.start(0.0)
        self._t_enter = time.monotonic()
        self.title = crops.current().app
        Clock.schedule_once(self._enter_next, 0)

    def _enter_next(self, *_):
        """Un paso de precarga por cuadro mientras se ve el logo; luego, el inicio."""
        if self._preload and time.monotonic() - self._t_enter < self.SPLASH_MAX_S:
            self._run_preload_step()
            Clock.schedule_once(self._enter_next, 0)
            return
        if self.home is None:          # se agotó el tiempo: lo mínimo para entrar
            self.home = HomeScreen(name="home")
            self.sm.add_widget(self.home)
            self.home.refresh_current()
        wait = self.SPLASH_MIN_S - (time.monotonic() - self._t_enter)
        Clock.schedule_once(self._enter_module, max(0, wait))

    def _enter_module(self, *_):
        self.sm.get_screen("splash").ids.logo.stop()
        self.sm.transition = FadeTransition(duration=0.25)
        self.open_start()
        Clock.schedule_once(lambda *_: setattr(self.sm, "transition", NoTransition()), 0.3)
        Clock.schedule_once(lambda *_: self.sm.has_screen("splash")
                            and self.sm.remove_widget(self.sm.get_screen("splash")), 0.6)
        Clock.schedule_once(lambda *_: _gc_freeze(), 1)
        self._after_enter()

    def pick_style(self):
        """Ajustes › Estilo de la app (también en la pantalla de cultivos)."""
        from ui.screens import pick_dialog
        opts = []
        for key, (name, desc) in theme.STYLES.items():
            mark = "✓ " if key == theme.style else ""
            opts.append((mark + name, desc, lambda key=key: self.set_style(key)))
        pick_dialog("Estilo de la app", opts)

    def set_style(self, style: str) -> None:
        from platform_utils import global_set
        if style == theme.style:
            return
        global_set("style", style)
        inside = self.sm.current not in ("crops", "launch")
        theme.configure(None, style)
        theme.apply(self.theme_cls)
        self._bg.source = theme.BACKGROUND
        Window.clearcolor = theme.c(theme.SPLASH_BG)
        if self.sm.has_screen("crops"):
            self.sm.remove_widget(self.sm.get_screen("crops"))
        self.sm.add_widget(CropScreen(name="crops"))
        if inside:
            import crops
            self.choose_crop(crops.current().id)     # se rehace el módulo con el estilo nuevo
        else:
            self._load_module(theme.crop_id)
            self.sm.current = "crops"
            Clock.schedule_once(self._preload_idle, 0.5)

    # --------------------------------------- carga diferida (arranque rápido)
    @cached_property
    def classifier(self):
        from ai_classifier import PhenologyClassifier  # numpy: solo al usar la IA
        return PhenologyClassifier(self.db)

    @cached_property
    def pin(self):
        from ai_classifier import PinGuard
        return PinGuard(self.db)

    @cached_property
    def reports(self):
        from reporter import ReportGenerator  # Jinja2: solo al generar informes
        return ReportGenerator(self.db, data_subdir("reports"))

    def configured_reports(self):
        """Generador de informes con las preferencias del teléfono (fotos a incluir)."""
        r = self.reports
        r.include_all_photos = bool(self.db.get_setting("report_all_photos", False))
        r.photo_mode = self.db.get_setting("report_photo_mode", "both")
        return r

    @cached_property
    def drive(self):
        from drive_backup import DriveBackup  # respaldo de fotos en Google Drive
        return DriveBackup(self.db)

    @cached_property
    def sync(self):
        from sync_drive import DriveSync   # celular <-> PC por Google Drive
        return DriveSync(self.drive, self.workspaces, self.open_db, get_data_dir())

    def run_sync(self, manual: bool = False) -> None:
        """Recibe los cambios del otro equipo y envía los de aquí (en segundo plano)."""
        if not (self.db.get_setting("drive_enabled", False) and self.drive.available):
            if manual:
                self.toast("Conecte Google Drive (Ajustes) para sincronizar con su PC.")
            return
        if getattr(self, "_syncing", False):
            return
        self._syncing = True

        def work():
            from drive_backup import Offline, explain
            from sync_drive import summary
            res = None
            try:
                # Sin red por un momento (al abrir o volver a la app el Wi-Fi/datos aún no
                # está listo: «No address associated with hostname»): se reintenta enseguida.
                for wait in (4, 12, 30, None):
                    try:
                        _step("sincroniza")
                        res = self.sync.run(manual=manual)
                        msg = summary(res)
                        _step("cuaderno → PDF")
                        self._export_notebooks()
                        _step("sincronizado")
                        break
                    except Offline as exc:
                        if wait is None:
                            msg = f"No se pudo sincronizar: {explain(str(exc))} · se reintenta en 10 min"
                            break
                        time.sleep(wait)
            except Exception as exc:  # noqa: BLE001 (sin permiso…: se reintenta luego)
                msg = f"No se pudo sincronizar: {explain(str(exc))}"
            finally:
                self._syncing = False
            stamp = _dt.datetime.now().strftime("%d/%m %H:%M")
            self.workspaces.shared.set_setting("sync_last", f"{stamp} · {msg}")
            Clock.schedule_once(lambda *_: self._after_sync(res, msg, manual))
        self.workers.submit(work)

    def _export_notebooks(self) -> None:
        """Páginas del cuaderno que cambiaron (aquí o en otro equipo) → PDF en Drive, carpeta
        «Cuaderno de campo» (notebook_export.py). Un error aquí no frena la sincronización."""
        try:
            from notebook_export import export_pending
            for db in self.all_dbs():
                export_pending(db, self.drive, data_subdir("cuaderno_pdf"))
        except Exception as exc:  # noqa: BLE001
            print("cuaderno → Drive:", exc)

    def backup_notebook(self, path: str) -> None:
        """Foto del cuaderno → Drive, carpeta exclusiva «Cuaderno de campo»."""
        if not self.db.get_setting("drive_enabled", False):
            return
        from notebook_export import photo_remote
        self.drive.enqueue(None, path, remote=photo_remote(path))

    def _after_sync(self, res, msg, manual):
        if manual:
            self.toast(msg)
        if res and res.get("downloaded") and res.get("pending_photos"):
            Clock.schedule_once(lambda *_: self.run_sync(), 20)   # quedan fotos: sigue pronto
        if res and (res["applied"] or res["created"] or res["downloaded"]) and self.home is not None:
            self.refresh_home()       # lo que llegó del otro equipo se ve ya
        if self.sm.has_screen("settings"):
            for w in self.sm.get_screen("settings").walk():
                if type(w).__name__ == "SettingsTab":
                    w.refresh_sync()
                    break

    def _screen(self, cls, name):
        if not self.sm.has_screen(name):
            self.sm.add_widget(cls(name=name))
        return self.sm.get_screen(name)

    @property
    def observation(self):
        return self._screen(ObservationScreen, "observation")

    @property
    def variety(self):
        return self._screen(VarietyScreen, "variety")

    @property
    def measure(self):
        return self._screen(MeasureScreen, "measure")

    def open_measure(self, measure_id: int, week_id: int):
        self.measure.load(measure_id, week_id)
        self.go("measure")

    @property
    def workspaces_screen(self):
        return self._screen(WorkspacesScreen, "workspaces")

    def open_db(self, ws: dict):
        """Base del ensayo/predio (se reutiliza la conexión si ya estaba abierta)."""
        db = self._dbs.get(ws["id"])
        if db is None:
            db = self._dbs[ws["id"]] = self.workspaces.open(ws)
        db.workspace = dict(ws)
        return db

    def all_dbs(self) -> list:
        """Bases de todos los ensayos y predios activos (el entrenador IA es uno solo)."""
        dbs = [self.open_db(ws) for ws in self.workspaces.list()]
        if self.db is not None and all(d is not self.db for d in dbs):
            dbs.append(self.db)
        return dbs

    def open_workspaces(self, profile: str | None = None):
        """profile: «id» o «predio» desde la pantalla de inicio (menú solo de ese perfil)."""
        scr = self.workspaces_screen
        scr.menu_mode = profile is not None
        if profile:
            scr.profile = profile
        self.go("workspaces")

    @property
    def heatmap(self):
        from ui.heatmap import HeatmapScreen
        return self._screen(HeatmapScreen, "heatmap")

    def open_heatmap(self):
        """Mapa de calor de dónde se tomaron las fotos (desde «Vista previa»)."""
        self.heatmap
        self.go("heatmap")

    @property
    def notebook(self):
        from ui.notebook import NotebookScreen
        return self._screen(NotebookScreen, "notebook")

    @property
    def note_page(self):
        from ui.notebook import NoteScreen
        return self._screen(NoteScreen, "note_page")

    def open_notebook(self):
        """Cuaderno de campo (bitácora diaria del ensayo o predio)."""
        self.go("notebook")

    @property
    def sectors(self):
        return self._screen(SectorsScreen, "sectors")

    @property
    def start(self):
        return self._screen(StartScreen, "start")

    def open_start(self):
        """Pantalla de inicio (I+D, Predio, Entrenador IA, cuenta de Google)."""
        self.start
        self._history = []
        self.sm.current = "start"

    def enter_home(self):
        self._history = []
        self.sm.current = "home"
        self.refresh_home()

    def workspace_renamed(self, ws_id: int):
        ws = self.workspaces.get(ws_id)
        if ws_id in self._dbs:
            self._dbs[ws_id].workspace = dict(ws)
        if self.workspace and self.workspace["id"] == ws_id:
            self.workspace = ws
            if self.home is not None:
                self.home.update_banner()

    def move_to_predio(self, src: dict, dst: dict):
        """Traspasa un ensayo de I+D a un predio vacío (ver Workspaces.move_to_predio)."""
        if "drive" in self.__dict__ and self.drive.running:
            self.toast("Espere a que termine la subida a Google Drive y vuelva a intentarlo.")
            return
        for ws_id in (src["id"], dst["id"]):   # se cierran: sus archivos cambian de dueño
            db = self._dbs.pop(ws_id, None)
            if db is not None:
                if db is self.db:
                    self.db = None
                try:
                    db.close()
                except Exception:  # noqa: BLE001
                    pass
        try:
            res = self.workspaces.move_to_predio(src, dst)
        except Exception as exc:  # noqa: BLE001
            self.toast(str(exc))
            self.open_workspace((self.workspace or src)["id"])
            return
        self.open_workspace(dst["id"], target="sectors")
        # Galería del teléfono («Imágenes de Fenología»): …-NV-… -> …-AM-… (hilo principal).
        from photo_rename import recode_name
        try:
            self.media.rename_public_legacy(lambda n: recode_name(n, res["old"], res["new"]))
        except Exception as exc:  # noqa: BLE001 - nunca impedir el traspaso
            print("gallery recode:", exc)
        self.toast(f"Listo: {res['units']} sectores y {res['photos']} fotos ahora en "
                   f"{dst['name']} ({res['new']}).")

    def open_workspace(self, ws_id: int, target: str | None = "home"):
        """Cambia de ensayo o predio: todas las pantallas se rehacen con sus datos.
        target=None: solo cambia de ensayo, sin moverse de la pantalla actual (cuaderno)."""
        ws = self.workspaces.get(ws_id)
        if ws is None:
            return
        self.workspace = ws
        self.workspaces.remember(ws)
        self.db = self.open_db(ws)
        self.reminders = ReminderManager(self.db)
        for name in ("classifier", "reports", "drive", "pin"):
            self.__dict__.pop(name, None)
        self.week = self.db.current_week()
        self.season = self.week["season"]
        # Las pantallas ya construidas se REUTILIZAN (rehacerlas tomaba más de 1 s en
        # teléfonos básicos): cada una vuelve a leer la base al mostrarse; solo se olvidan
        # las selecciones que eran del ensayo anterior.
        if target is not None:
            self._history = []
        if self.home is None:
            self.home = HomeScreen(name="home")
            self.sm.add_widget(self.home)
        ids = self.home.ids
        ids.reports.sel_week = ids.reports.sel_variety = ids.reports.sel_month = None
        ids.preview._season = None
        self.home.refresh_current()
        if target is None:
            pass
        elif target == "sectors":   # predio: lista de sectores; «atrás» vuelve a la lista de predios
            self.sectors
            self._history = ["start", "workspaces"]
            self.sm.current = "sectors"
        else:
            self.sm.current = "home"
        # Sin aviso emergente con el nombre: ya se ve en el banner del muestreo.
        self.workers.submit(self._rename_photos)
        if self.db.get_setting("drive_enabled", False):
            Clock.schedule_once(lambda *_: self.workers.submit(self._drive_daily), 3)

    @property
    def ailab(self):
        return self._screen(AILabScreen, "ailab")

    @property
    def settings(self):
        return self._screen(SettingsScreen, "settings")

    # --------------------------------------------- apertura y precarga
    SPLASH_MIN_S = 1.8    # el logo completa su entrada aunque la carga sea instantánea
    SPLASH_MAX_S = 12.0   # pase lo que pase, a los 12 s se entra a la app

    def on_start(self):
        """La pantalla de carga de Android (los tres frutos) se quita apenas está lista la
        pantalla de cultivos. El módulo elegido la última vez se precarga detrás, de a un
        paso por cuadro, para entrar al instante si se vuelve a elegir."""
        self._t_start = time.monotonic()
        # Seguro: pase lo que pase, la pantalla de carga nativa no tapa la app para siempre.
        Clock.schedule_once(lambda *_: splash_native.remove(), self.SPLASH_MAX_S + 3)
        self.workers.submit(self._preload_modules)
        self._preloaded = False
        self._preload = self._preload_steps()
        self.sm.add_widget(CropScreen(name="crops"))
        # La pantalla de carga de Android es el primer cuadro de la animación de AeonCrop:
        # se quita y sigue la animación (la huella se dibuja, la planta crece).
        Clock.schedule_once(lambda *_: splash_native.remove(), 0)
        self._frame = 0
        self._anim_ev = Clock.schedule_interval(self._launch_frame, 1 / 20)

    def _launch_frame(self, *_):
        if not self.sm.has_screen("launch"):
            self._anim_ev.cancel()
            return
        self._frame += 1
        if self._frame < len(theme.AEON_FRAMES):
            self.sm.get_screen("launch").ids.anim.source = theme.AEON_FRAMES[self._frame]
            return
        if self._frame >= len(theme.AEON_FRAMES) + 6:   # el logo completo un momento
            self._anim_ev.cancel()
            self._show_crops()

    def _show_crops(self, *_):
        _step("cultivos")
        splash_native.remove()
        self.sm.transition = FadeTransition(duration=0.25)
        self.sm.current = "crops"
        Clock.schedule_once(lambda *_: setattr(self.sm, "transition", NoTransition()), 0.3)
        Clock.schedule_once(lambda *_: self.sm.has_screen("launch")
                            and self.sm.remove_widget(self.sm.get_screen("launch")), 0.6)
        Clock.schedule_once(lambda *_: self._after_launch(), 0.4)
        Clock.schedule_once(self._preload_idle, 0.8)

    def _run_preload_step(self):
        step = self._preload.pop(0)
        _step(f"precarga {len(self._preload)}")
        try:
            step()
        except Exception as exc:  # noqa: BLE001 (la precarga nunca debe cerrar la app)
            print("preload:", exc)
        if not self._preload:
            self._preloaded = True

    def _preload_idle(self, *_):
        """Precarga del módulo mientras se ve la pantalla de cultivos (un paso cada tanto)."""
        if self._preload and self.sm.current == "crops":
            self._run_preload_step()
            Clock.schedule_once(self._preload_idle, 0.05)

    def _preload_steps(self):
        """Pasos de la precarga, del más necesario al menos (uno por cuadro)."""
        def home():
            self.home = HomeScreen(name="home")
            self.sm.add_widget(self.home)

        return [home, lambda: self.home.refresh_current(), lambda: self.start,
                lambda: self.workspaces_screen, lambda: self.observation,
                lambda: self.settings, lambda: self.settings.ids.varieties.refresh(),
                lambda: self.variety, lambda: self.measure, lambda: self.timeline,
                lambda: self.sectors, lambda: self.ailab,
                lambda: self.home.ids.reports.refresh(),
                lambda: self.home.ids.preview.refresh(),
                self._preload_images]

    def _preload_modules(self):
        for mod in ("numpy", "ai_classifier", "jinja2", "reporter", "pdf_report"):
            try:
                __import__(mod)
            except Exception as exc:  # noqa: BLE001
                print("preload", mod, exc)

    def _preload_images(self):
        """Imágenes de la interfaz y frambuesas a la caché de Kivy (se abren al instante)."""
        from kivy.core.image import Image as CoreImage
        for parts in (("assets", "ui"), ("assets", "ui", "berries")):
            path = resource_path(*parts)
            for name in sorted(os.listdir(path)) if os.path.isdir(path) else []:
                if name.endswith(".png"):
                    try:
                        CoreImage(os.path.join(path, name))
                    except Exception:  # noqa: BLE001
                        pass

    def _after_launch(self):
        """Una vez, al ver la pantalla de cultivos."""
        _step("permisos")
        request_runtime_permissions()
        if self.safe_mode:
            # La apertura anterior se cerró a medias: esta vez nada automático en segundo
            # plano (Drive, sincronización, renombres) y se muestra dónde se quedó.
            Clock.schedule_once(lambda *_: self._show_safe_mode(), 1.5)
            Clock.schedule_once(lambda *_: self._finish_start(), 20)
            return
        # La apertura termina cuando acabó la primera sincronización (o a los 45 s).
        Clock.schedule_once(lambda *_: self._finish_start(), 45)

    def _after_enter(self):
        """Cada vez que se entra a un módulo (cultivo)."""
        _step("inicio")
        _step("recordatorios")
        self.reminders.apply()
        if not getattr(self, "_timers", False):
            self._timers = True
            Clock.schedule_interval(lambda *_: self._check_reminder(), 60)
            if not self.safe_mode:
                # Sincronización con el PC: cada 10 minutos (la del módulo abierto).
                Clock.schedule_interval(lambda *_: self.run_sync(), 600)
        if self.safe_mode:
            return
        # Nombres de foto «ddmmaaaa-…» (hasta la 1.1.30) -> «aaaammdd-…»: archivos de la app,
        # galería del teléfono y (al respaldar) Google Drive.
        Clock.schedule_once(lambda *_: self.workers.submit(self._rename_photos), 4)
        # Sube lo que haya quedado en cola (sin red la última vez).
        # y respalda la base en Drive una vez al día (las fotos ya se suben solas).
        if self.db.get_setting("drive_enabled", False):
            Clock.schedule_once(lambda *_: self.workers.submit(self._drive_daily), 6)
            # IA+ (Lab): las marcas de Drive se precargan apenas se conoce la cuenta.
            Clock.schedule_once(lambda *_: self._preload_iaplus(), 3)
        Clock.schedule_once(lambda *_: self.run_sync(), 10)

    def _finish_start(self):
        import crashguard
        if not getattr(self, "_syncing", False):
            crashguard.finish()
        else:
            Clock.schedule_once(lambda *_: self._finish_start(), 15)

    def _show_safe_mode(self):
        import crashguard
        from ui.screens import text_dialog
        steps = crashguard.previous_failure() or []
        text_dialog("La app se cerró al abrirla la vez anterior",
                    ["Esta vez abrió en modo seguro: sin sincronizar ni subir a Drive hasta la "
                     "próxima apertura. Envíe una captura de esta pantalla para encontrar la causa.",
                     "Últimos pasos:"] + steps[-8:]
                    + ["Detalle: Ajustes › Registro de errores."], small=True)

    def _rename_photos(self):
        _step("renombra fotos")
        try:
            from photo_rename import migrate_local
            res = migrate_local(self.db)
        except Exception as exc:  # noqa: BLE001 (nunca debe impedir usar la app)
            print("rename photos:", exc)
            return
        Clock.schedule_once(lambda *_: self._rename_public(res["renamed"]), 0)

    def _rename_public(self, local: int):
        """Galería («Imágenes de Fenología»): en el hilo principal (Java), una sola vez."""
        public = 0
        if not self.db.get_setting("public_names_v34", False):
            # Fotos de versiones anteriores (todas de «Nuevas variedades»): fecha aaaammdd
            # y código NV. Las que ya tienen el código de algún ensayo no se tocan.
            from photo_rename import new_name
            known = self.workspaces.codes()
            try:
                public, _failed = self.media.rename_public_legacy(lambda n: new_name(n, "NV", known))
                self.db.set_setting("public_names_v34", True)
            except Exception as exc:  # noqa: BLE001
                print("rename public:", exc)
        if local or public:
            self.toast(f"Fotos renombradas (fecha año-mes-día y código del ensayo): {max(local, public)}")
        if self.db.get_setting("drive_enabled", False):
            self.drive.flush_async()   # renombra también las ya subidas a Drive

    def on_pause(self):
        _step(PAUSED)    # en segundo plano: no cuenta como cierre al abrir
        return True

    def on_resume(self):
        _step("vuelve")
        self.week = self.db.current_week() if self.week is None else self.week
        if "drive" in self.__dict__:
            self.drive.flush_async()
            self.run_sync()
        if self.home is not None:
            self.refresh_home()

    def on_stop(self):
        self.workers.shutdown(wait=False)
        self.db.close()

    # ------------------------------------------------------- navegación
    def go(self, name: str, direction: str = "left"):
        if not self.sm.has_screen(name):
            getattr(self, name)  # carga diferida de la pantalla
            Clock.schedule_once(lambda *_: _gc_freeze(), .5)
        if self.sm.current != name:
            self._history.append(self.sm.current)
        self.sm.current = name

    def back(self):
        if self.sm.current == "settings" and getattr(self, "_settings_return", None):
            # Ajustes vuelve siempre a donde se abrió (inicio o el ensayo).
            target = self._settings_return
            self._settings_return = None
            while self._history and self._history[-1] != target:
                self._history.pop()
            if self._history:
                self._history.pop()
            if target == "start":
                self.open_start()
                return
            if target == "crops":
                self.open_crops()
                return
            self.sm.current = target
            if target == "home":
                self.refresh_home()
            return
        target = self._history.pop() if self._history else "home"
        if target == "crops":
            self.open_crops()
            return
        self.sm.current = target
        if target == "home":
            self.refresh_home()

    def _on_keyboard(self, _window, key, *_args):
        if key == 27:  # botón «atrás» de Android / Esc
            if self.media.close_preview():  # cierra la vista previa del informe
                return True
            if self._file_manager and self._file_manager._window_manager_open:
                self._file_manager.close()
                return True
            if self.sm.current == "home":   # desde el inicio de un ensayo -> pantalla de inicio
                self.open_start()
                return True
            if self.sm.current == "start":  # del inicio del módulo -> pantalla de cultivos
                self.open_crops()
                return True
            if self.sm.current in ("splash", "launch"):
                return True
            if self.sm.current != "crops":
                self.back()
                return True
            if platform == "android":
                # En el inicio: la app pasa a segundo plano, como cualquier app de Android.
                # Cerrarla del todo dejaba el proceso a medio terminar y la siguiente
                # apertura podía cerrarse sola.
                from android_bridge import to_background
                if to_background():
                    return True
        return False

    def refresh_home(self):
        # Solo la pestaña visible; las demás se refrescan al seleccionarlas.
        self.home.refresh_current()

    def open_observation(self, variety_id: int, week_id: int):
        self.observation.load(variety_id, week_id)
        self.go("observation")

    @property
    def timeline(self):
        return self._screen(TimelineScreen, "timeline")

    def open_timeline(self, variety_id: int, week_id: int | None = None):
        self.timeline.load(variety_id, week_id)
        self.go("timeline")

    def open_variety(self, variety_id: int):
        self.variety.load(variety_id)
        self.go("variety")

    def open_settings(self, general_only: bool = False):
        """general_only: desde el inicio, solo los ajustes generales (sin la pestaña de
        registros del ensayo)."""
        home = self.sm.current == "crops"
        if getattr(self, "_settings_home", None) != home and self.sm.has_screen("settings"):
            self.sm.remove_widget(self.sm.get_screen("settings"))   # otras tarjetas
        self._settings_home = home
        self.settings.general_only = general_only
        self._settings_return = self.sm.current
        self.go("settings")

    def open_ai_entry(self, kind: str):
        """IA o IA+ desde la pantalla principal: PIN, luego el cultivo a entrenar (cada IA
        aprende por separado). Al volver, se regresa a la pantalla principal."""
        def go_crop(crop_id):
            import crops
            if self._loaded != (crop_id, theme.style):
                self._load_module(crop_id)
            from platform_utils import global_set
            global_set("crop", crop_id)
            self.title = "AeonCrop"
            self._history = ["crops"]
            if kind == "iaplus":
                from ui import boxes
                boxes.open_screen()
            else:
                self.go("ailab")
            self._history = ["crops"]
            self.toast(f"{'IA+' if kind == 'iaplus' else 'Entrenador IA'} · {crops.get(crop_id).app}")

        self._ask_pin(lambda: self.pick_crop("¿Qué IA quiere entrenar?" if kind == "ia"
                                             else "IA+ · ¿de qué cultivo?", go_crop))

    def pick_crop(self, title: str, on_pick) -> None:
        """Los tres cultivos con su logo, para elegir uno."""
        import crops
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.modalview import ModalView
        from ui.screens import FloatCrop, GlassCard
        view = ModalView(size_hint=(.94, None), height=dp(196), background="",
                         background_color=(0, 0, 0, .45))
        card = GlassCard(orientation="vertical", padding=(dp(12), dp(14), dp(12), dp(10)),
                         spacing=dp(6), md_bg_color=theme.c(theme.GLASS_STRONG), radius=[dp(26)])
        card.add_widget(MDLabel(text=title, halign="center", font_style="Subtitle1", bold=True,
                                theme_text_color="Custom", text_color=theme.c(theme.LEAF_DARK),
                                size_hint_y=None, height=dp(30)))
        row = BoxLayout(spacing=dp(4), size_hint_y=None, height=dp(118))
        for crop in crops.CROPS.values():
            w = FloatCrop(crop_id=crop.id, app_name=crop.app, logo=theme.crop_logo(crop.id),
                          accent=theme.crop_accent(crop.id), side=dp(96))
            w.size_hint = (1, None)

            def pick(btn):
                view.dismiss()
                Clock.schedule_once(lambda *_: on_pick(btn.crop_id), 0.05)
            w.bind(on_release=pick)
            row.add_widget(w)
        card.add_widget(row)
        view.add_widget(card)
        view.open()

    def _ask_pin(self, on_ok) -> None:
        form = PinForm()

        def ok(f):
            if self.pin.verify(f.ids.pin.text):
                Clock.schedule_once(lambda *_: on_ok(), 0.1)
                return True
            wait = self.pin.locked_seconds
            f.ids.msg.text = (f"Demasiados intentos. Espere {wait} s." if wait
                              else "PIN incorrecto.")
            f.ids.pin.text = ""
            return False

        dialog = form_dialog("Acceso restringido · IA", form, ok, "INGRESAR")
        form.ids.pin.bind(on_text_validate=lambda *_: ok(form) and dialog.dismiss())

    def sync_all_crops(self) -> None:
        """Botón sincronizar de la pantalla principal: los tres cultivos, uno tras otro (en
        segundo plano). Sin cuenta de Google, avisa: todo sigue guardado en el teléfono."""
        from platform_utils import global_get
        if not global_get("drive_enabled", False):
            self.toast("Conecte su cuenta de Google: mientras, todo queda guardado en el teléfono.")
            return
        if getattr(self, "_syncing", False):
            return
        self._syncing = True
        self.toast("Sincronizando los tres cultivos con Google Drive…")
        loaded = self._loaded[0]

        def work():
            import crops
            from drive_backup import DriveBackup, explain
            from platform_utils import get_data_dir
            from sync_drive import DriveSync, summary
            msgs = []
            try:
                for crop in crops.CROPS.values():
                    try:
                        if crop.id == loaded:
                            res = self.sync.run(manual=True)
                        else:
                            crops.activate(crop.id)
                            wss = Workspaces(get_data_dir())
                            db = wss.open(wss.last())
                            res = DriveSync(DriveBackup(db), wss, wss.open, get_data_dir()).run(manual=True)
                        msgs.append(f"{crop.app}: {summary(res)}")
                    except Exception as exc:  # noqa: BLE001
                        msgs.append(f"{crop.app}: {explain(str(exc))}")
                    finally:
                        crops.activate(loaded)
            finally:
                self._syncing = False
            Clock.schedule_once(lambda *_: self.toast(" · ".join(msgs)))
        self.workers.submit(work)

    def open_ai_lab(self):
        """Módulo de calibración: requiere PIN (por defecto 1234)."""
        form = PinForm()

        def ok(f):
            if self.pin.verify(f.ids.pin.text):
                self.go("ailab")
                return True
            wait = self.pin.locked_seconds
            f.ids.msg.text = (f"Demasiados intentos. Espere {wait} s." if wait
                              else "PIN incorrecto.")
            f.ids.pin.text = ""
            return False

        dialog = form_dialog("Acceso restringido · Calibración IA", form, ok, "INGRESAR")
        # «Listo» en el teclado también entra.
        form.ids.pin.bind(on_text_validate=lambda *_: ok(form) and dialog.dismiss())

    # ---------------------------------------------------------- utilidades
    def toast(self, text: str):
        MDSnackbar(MDLabel(text=text, theme_text_color="Custom", text_color=(1, 1, 1, 1)),
                   md_bg_color=theme.c(theme.FILL_DARK, .94), radius=[dp(18)] * 4,
                   y=dp(108), pos_hint={"center_x": .5}, size_hint_x=.9, duration=2.5).open()

    def _thumb_dest(self, path: str, size: int) -> str | None:
        try:
            key = hashlib.md5(f"{path}|{os.path.getmtime(path)}|{size}".encode()).hexdigest()
        except OSError:
            return None
        return os.path.join(data_subdir("thumbs"), key + ".jpg")

    def set_season(self, season: int) -> None:
        """Temporada que muestran muestreo, vista previa e informes (sin mezclar registros):
        en la temporada en curso, la semana actual; en otra, su última semana con datos."""
        if season == self.db.current_season():
            self.week = self.db.current_week()
        else:
            self.week = self.db.last_week(season) or self.db.ensure_week(season, 1)
        self.season = self.week["season"]

    def thumb(self, path: str, size: int = 320) -> str:
        """Miniatura cacheada (síncrona; usar thumb_async desde la interfaz)."""
        dest = self._thumb_dest(path, size)
        if dest is None:
            return path
        if not os.path.exists(dest):
            try:
                make_thumbnail(path, dest, size)
            except Exception:
                return path
        return dest

    def thumb_async(self, path: str, size: int, callback) -> None:
        """Entrega la miniatura a `callback` sin bloquear la interfaz."""
        dest = self._thumb_dest(path, size)
        if dest and os.path.exists(dest):
            callback(dest)
            return

        def work():
            result = self.thumb(path, size)
            Clock.schedule_once(lambda *_: callback(result))

        self.workers.submit(work)

    def run_report(self, job, on_done=None):
        self.toast("Generando informe…")

        def work():
            try:
                res = job()
                self._report_done(res, None, on_done)
            except Exception as exc:  # noqa: BLE001
                self._report_done(None, exc, on_done)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _report_done(self, res, error, on_done):
        if error:
            self.toast(f"Error al generar: {error}")
            return
        if on_done:
            on_done(res)
        self.report_actions(res.path, title="Informe listo",
                            info=f"{os.path.basename(res.path)} · {res.size_kb} KB")

    # ------------------------------------------- enviar / guardar informes
    def report_actions(self, path: str, title: str = "Informe", info: str = "", viewable: bool = True):
        """Menú: WhatsApp, correo, guardar en el teléfono, ver u otras apps."""
        from ui.screens import pick_dialog
        size_mb = os.path.getsize(path) / 1e6
        heavy = size_mb > 20
        mail_note = (f"{size_mb:.0f} MB: puede superar el límite de adjuntos del correo" if heavy
                     else "Gmail, Outlook u otra app de correo")
        options = [
            ("WhatsApp", "Enviar como documento", lambda: self.share_file(path, target="whatsapp")),
            ("Correo electrónico", mail_note, lambda: self.send_email(path)),
            ("Guardar en el teléfono", "Descargas › PhenoRubus", lambda: self.save_file(path)),
            ("Guardar en Google Drive", "Carpeta de la semana en «AeonCrop»"
             if self.db.get_setting("drive_enabled", False) else "Primero conecte Drive en Ajustes",
             lambda: self.save_to_drive(path)),
            ("Ver informe", "Abrir en el lector de PDF" if path.endswith(".pdf") else "Abrir en el navegador",
             lambda: self.open_file(path)),
            ("Otras apps…", "Drive, Telegram, Bluetooth…", lambda: self.share_file(path)),
        ]
        if not viewable:
            options = [o for o in options if o[0] != "Ver informe"]
        pick_dialog(f"{title}" + (f"\n{info}" if info else ""), options)

    def _mime(self, path: str) -> str:
        return MIME.get(os.path.splitext(path)[1], "*/*")

    def open_file(self, path: str):
        try:
            self.media.open(path, self._mime(path))
        except Exception as exc:  # noqa: BLE001
            self.toast(f"No se pudo abrir: {exc}")

    def save_file(self, path: str):
        try:
            where = self.media.save_public(path, self._mime(path))
            self.toast(f"Guardado en {where}")
        except Exception as exc:  # noqa: BLE001
            self.toast(f"No se pudo guardar: {exc}")

    def send_email(self, path: str):
        """Una app de correo → directo; varias → el usuario elige; ninguna → menú general."""
        try:
            apps = self.media.email_apps()
        except Exception:  # noqa: BLE001
            apps = []
        if len(apps) == 1:
            self.share_file(path, target=f"email:{apps[0][1]}")
        elif apps:
            from ui.screens import pick_dialog
            pick_dialog("Enviar por correo con…", [
                (label, "", lambda pkg=pkg: self.share_file(path, target=f"email:{pkg}"))
                for label, pkg in apps])
        else:
            self.share_file(path, target="email")

    def save_to_drive(self, path: str):
        if not self.db.get_setting("drive_enabled", False):
            self.toast("Conecte Google Drive en Ajustes › Respaldo en Google Drive")
            return
        remote = self.drive.enqueue_report(path)
        self.toast(f"Se sube a Drive: {remote.rsplit('/', 1)[0]}")

    def share_file(self, path: str, mime: str | None = None, target: str | None = None):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            self.media.share(path, mime or self._mime(path), target=target,
                             subject=f"PhenoRubus · {name}",
                             text="Informe fenológico generado con PhenoRubus. Ábralo con el "
                                  "navegador del teléfono o del computador.")
        except Exception as exc:  # noqa: BLE001
            self.toast(f"No se pudo compartir: {exc}")

    def _preload_iaplus(self):
        from ui import boxes
        boxes.preload()

    def _drive_daily(self):
        _step("respaldo diario")
        try:
            if self.drive.backup_database() is None:
                self.drive.flush_async()
        except Exception as exc:  # noqa: BLE001
            print("drive daily backup:", exc)

    def reload_data(self):
        """Tras restaurar un respaldo: descarta cachés y vuelve a leer todo (el registro de
        ensayos también pudo cambiar)."""
        ws = self.workspaces.get(self.workspace["id"]) if self.workspace else None
        if ws is None or ws["archived"]:
            ws = self.workspaces.last()
        self.open_workspace(ws["id"])
        self.reminders.apply()

    def backup_photo(self, photo_id: int, path: str) -> None:
        """Encola la foto para respaldo en Google Drive (si está activado)."""
        if not self.db.get_setting("drive_enabled", False):
            return
        self.drive.enqueue(photo_id, path)

    def backup_extra(self, path: str, start_date: str, folder: str) -> None:
        """Fotos adjuntas o de mediciones → carpeta de la semana en Drive («…/Adjuntas», «…/<medición>»)."""
        if not self.db.get_setting("drive_enabled", False):
            return
        safe = folder.replace("/", "-").strip() or "Otras"
        self.drive.enqueue(None, path, remote=f"{self.drive.week_path(start_date)}/{safe}/"
                                              f"{os.path.basename(path)}")

    def _check_reminder(self):
        if self.reminders.check_due():
            self.toast("Recordatorio: hoy corresponde el muestreo semanal.")

    def _desktop_file_chooser(self, callback, exts):
        from kivymd.uix.filemanager import MDFileManager

        def select(path):
            self._file_manager.close()
            callback(path if os.path.isfile(path) else None)

        def exit_manager(*_):
            self._file_manager.close()
            callback(None)

        self._file_manager = MDFileManager(select_path=select, exit_manager=exit_manager,
                                           ext=list(exts), preview=False)
        self._file_manager.show(os.path.expanduser("~"))


if __name__ == "__main__":
    FenoRubusApp().run()
