"""
ui/home.py
==========
Pantallas de apertura e inicio: carga, cultivos, inicio del ensayo (StartBase).
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
import math
import perf
import time
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.image import Image as KivyImage
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.properties import BooleanProperty, ColorProperty, NumericProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.screen import MDScreen
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import DriveDial, app, form_dialog, when_text


# ===========================================================================
# Home
# ===========================================================================
class SplashScreen(MDScreen):
    """Pantalla de carga de cada módulo: logo animado, nombre y firma. PhenoRubus usa su
    animación de siempre; PhenoBlue y PhenoCran, la de su logo simple. La animación la
    maneja la app (main.choose_crop)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        if theme.crop_id != "frambuesa":
            # PhenoBlue y PhenoCran: la misma animación que PhenoRubus, con sus capas.
            from platform_utils import resource_path
            from ui.splash_anim import LogoAnim
            old = self.ids.logo
            new = LogoAnim(resource_path("assets", "crops", theme.crop_id, "splash"), size_hint=old.size_hint)
            parent = old.parent
            parent.remove_widget(old)
            parent.add_widget(new)
            self.ids["logo"] = new


class HomeScreen(MDScreen):
    TITLES = {"sampling": "Muestreo semanal", "reports": "Informes", "preview": "Vista previa"}

    def on_tab(self, name: str):
        self.ids.tabs.current = name
        self.ids.bar.title = self.TITLES[name]
        getattr(self.ids, name).refresh()

    def refresh(self):
        for tab in self.TITLES:
            getattr(self.ids, tab).refresh()

    def refresh_current(self):
        self.update_banner()
        getattr(self.ids, self.ids.tabs.current or "sampling").refresh()
        Clock.schedule_once(lambda *_: self.update_drive_icon(), 0)

    # ------------------------------------------------- acceso rápido a Drive
    def _action(self, sources) -> object | None:
        for btn in self.ids.bar.ids.right_actions.children:
            if getattr(btn, "icon", None) in sources:
                return btn
        return None

    def update_drive_icon(self, *_):
        """Drive con flecha (hay algo por subir), con check (al día) o tachado (sin cuenta)."""
        if getattr(self, "_spin_ev", None):
            return   # subiendo: lo actualiza la animación
        btn = self._action([theme.DRIVE_UP, theme.DRIVE_OK, theme.DRIVE_OFF])
        if btn is None:
            return
        try:
            st = app().drive.status()
        except Exception:  # noqa: BLE001
            return
        btn.icon = (theme.DRIVE_OFF if not st["enabled"] else
                    theme.DRIVE_UP if st["pending"] or st["errors"] else theme.DRIVE_OK)

    def drive_quick(self):
        a = app()
        drive = a.drive
        if not drive.available:
            a.toast("El respaldo en Google Drive funciona en el teléfono (Android).")
            return
        if not drive.enabled:
            a.toast("Elija su cuenta de Google para respaldar en Drive")
            drive.connect(lambda ok, msg: Clock.schedule_once(lambda *_: (a.toast(msg), self.update_drive_icon())))
            return
        st = drive.status()
        todo = st["pending"] + st["errors"]
        backup = "Todo respaldado" if not todo else (f"{todo} foto por respaldar" if todo == 1
                                                     else f"{todo} fotos por respaldar")
        raw = a.workspaces.shared.get_setting("sync_last") or ""
        stamp, _, msg = raw.partition(" · ")
        failed = msg.startswith("No se pudo")
        sync = ("Sin sincronizar aún" if not raw else
                f"Falló {when_text(stamp)}" if failed else f"Sincronizado {when_text(stamp)}")
        btn = self._action([theme.DRIVE_UP, theme.DRIVE_OK, theme.DRIVE_OFF] + theme.DRIVE_SPIN)
        if btn is not None:
            anchor = btn.to_window(btn.center_x, btn.y)
        else:
            from kivy.core.window import Window
            anchor = (Window.width - dp(70), Window.height - dp(60))
        DriveDial(anchor, [
            ("cloud-upload-outline" if todo else "cloud-check-outline", theme.BERRY,
             str(todo) if todo else "", backup, bool(st["errors"]), self.drive_backup_now),
            ("sync", theme.LEAF, "", sync, failed, self.drive_sync_now),
        ]).open()

    def drive_backup_now(self):
        a = app()
        if getattr(self, "_spin_ev", None):
            a.toast("Trabajando con Google Drive…")
            return
        a.backup_now()           # reintenta errores y sube lo pendiente (insignia de avance)
        self._start_spin()

    def drive_sync_now(self):
        """Recibe lo hecho en el PC, la web u otro teléfono y envía lo de aquí (y baja todas
        las fotos pendientes)."""
        a = app()
        if getattr(a, "_syncing", False):
            a.toast("Ya se está sincronizando…")
            return
        a.toast("Sincronizando con sus otros dispositivos…")
        a.run_sync(manual=True)
        self._start_spin(report=False)

    def _start_spin(self, report: bool = True):
        import time as _t
        btn = self._action([theme.DRIVE_UP, theme.DRIVE_OK, theme.DRIVE_OFF] + theme.DRIVE_SPIN)
        if btn is None:
            return
        state = {"k": 0, "t0": _t.monotonic()}

        def tick(_dt):
            state["k"] = (state["k"] + 1) % len(theme.DRIVE_SPIN)
            btn.icon = theme.DRIVE_SPIN[state["k"]]
            drive = app().drive
            if _t.monotonic() - state["t0"] > 1.2 and not drive.running \
                    and not getattr(app(), "_syncing", False):
                self._spin_ev.cancel()
                self._spin_ev = None
                st = drive.status()
                btn.icon = theme.DRIVE_UP if st["pending"] or st["errors"] else theme.DRIVE_OK
                if report:     # la sincronización avisa su propio resumen
                    app().toast("Todo respaldado en Google Drive ✓" if btn.icon == theme.DRIVE_OK else
                                st.get("message") or "Quedan archivos por subir")

        self._spin_ev = Clock.schedule_interval(tick, .1)

    def update_banner(self):
        """Franja bajo la barra: en qué ensayo o predio se está trabajando."""
        ws = getattr(app(), "workspace", None)
        if ws:
            from workspaces import Workspaces
            self.ids.ws_banner.text = f"{Workspaces.title(ws)}  ·  {ws['code']}"
            self.ids.ws_banner.icon = "flask-outline" if ws["profile"] == "id" else "barn"


class StartIcon(ButtonBehavior, BoxLayout):
    """Botón de forma libre (ícono a línea sobre su burbuja) con su nombre debajo."""
    source = StringProperty()
    bubble = StringProperty("")
    glow = StringProperty("")
    glow_level = NumericProperty(.82)   # brillo neón (Entrenador IA)
    label = StringProperty()
    color = ColorProperty([0, 0, 0, 1])
    diameter = NumericProperty(dp(130))
    lift = NumericProperty(0)           # animación de entrada (desplazamiento hacia abajo)
    reveal = NumericProperty(1)         # animación de entrada (opacidad)
    bob = NumericProperty(0)            # flotación suave mientras se ve el inicio
    pulse = NumericProperty(1)          # la sombra (burbuja) «respira» al flotar


class StatusPill(Widget):
    text = StringProperty()
    color = ColorProperty([0, 0, 0, 1])


class GoogleButton(ButtonBehavior, FloatLayout):
    """Botón «Inicia sesión con Google» (blanco, con la G de colores)."""
    text = StringProperty("Inicia sesión con Google")


class LaunchScreen(MDScreen):
    """Lo que se ve al abrir la app (igual a la pantalla de carga de Android: los tres
    animación de AeonCrop) mientras se prepara la pantalla principal."""


class FloatCrop(ButtonBehavior, FloatLayout):
    """Logo de un cultivo en la pantalla principal de AeonCrop: suelto, flotando."""
    crop_id = StringProperty()
    app_name = StringProperty()
    logo = StringProperty()
    accent = StringProperty("#A8184A")
    side = NumericProperty(dp(120))
    bob = NumericProperty(0)


class AiLauncher(ButtonBehavior, FloatLayout):
    """IA (con brillo neón cian que sube y baja) o IA+ (con ki rojo) en la pantalla
    principal. Tocarlo pide el PIN y luego el cultivo a entrenar."""
    label = StringProperty()
    plus = BooleanProperty(False)
    side = NumericProperty(dp(86))
    glow_level = NumericProperty(.7)

    def __init__(self, **kw):
        super().__init__(**kw)
        Clock.schedule_once(self._build, 0)

    def _build(self, *_):
        from kivy.uix.image import Image
        s = self.side
        top = {"center_x": .5, "top": 1}       # arriba; el nombre va abajo (regla KV)
        if self.plus:
            from ui.arcade import KiButton
            icon = KiButton(source=theme.AEON_IAPLUS, size_hint=(None, None), size=(s, s), pos_hint=top)
            icon.bind(on_release=lambda *_: self.dispatch("on_release"))
        else:
            self.glow = Image(source=theme.AEON_IA_GLOW, size_hint=(None, None), size=(s, s),
                              fit_mode="contain", opacity=self.glow_level, pos_hint=top)
            self.bind(glow_level=lambda *_: setattr(self.glow, "opacity", self.glow_level))
            self.add_widget(self.glow)
            icon = Image(source=theme.AEON_IA, size_hint=(None, None), size=(s, s),
                         fit_mode="contain", mipmap=True, pos_hint=top)
        self.add_widget(icon)

    def on_release(self):
        app().open_ai_entry("iaplus" if self.plus else "ia")


class AeonLogo(ButtonBehavior, KivyImage):
    """Logo de AeonCrop en la pantalla principal: tocarlo muestra IA e IA+."""
    pulse = NumericProperty(1)


class CropScreen(MDScreen):
    """Pantalla principal de AeonCrop: los cultivos (PhenoRubus, PhenoBlue, PhenoCran)
    flotando, IA e IA+ aparte, ajustes, sincronizar y la cuenta de Google (una para todos).
    Sin cuenta, todo queda guardado en el teléfono hasta conectarla."""
    sync_angle = NumericProperty(0)
    ai_shown = NumericProperty(0)      # IA e IA+ visibles (0-1): aparecen al tocar el logo
    PHASE = {"frambuesa": 0.0, "arandano": 1.7, "cranberry": 3.4}

    def toggle_ai(self, show: bool | None = None):
        from kivy.animation import Animation
        show = self.ai_shown < .5 if show is None else show
        Animation.cancel_all(self, "ai_shown")
        Animation(ai_shown=1 if show else 0, d=.28, t="out_cubic").start(self)

    def on_kv_post(self, *_):
        import crops
        for crop in crops.CROPS.values():
            w = self.ids[f"c_{crop.id}"]
            w.app_name, w.logo, w.accent = crop.app, theme.crop_logo(crop.id), theme.crop_accent(crop.id)

    def on_pre_enter(self, *_):
        self.refresh_account()

    def on_enter(self, *_):
        self._t0 = time.monotonic()
        # Solo mueve y escala en el canvas; a 30 cuadros/s y se detiene sin toques (batería).
        from ui.idle_anim import IdleLoop
        self._loop = getattr(self, "_loop", None) or IdleLoop(self._float)
        self._loop.start()

    def on_leave(self, *_):
        if getattr(self, "_loop", None):
            self._loop.stop()
        self.ai_shown = 0                  # al volver, IA e IA+ quedan ocultas

    def _float(self, *_):
        t = time.monotonic() - self._t0
        for crop_id, ph_ in self.PHASE.items():
            self.ids[f"c_{crop_id}"].bob = dp(6) * math.sin(t * 1.3 + ph_)
        self.ids.scout.bob = dp(4) * math.sin(t * 1.3 + 5.1)
        if self.ai_shown:
            self.ids.ai.glow_level = .7 + .25 * math.sin(t * 1.6)
        # Mientras IA e IA+ están ocultas, el logo «respira» (se puede tocar).
        self.ids.logo.pulse = 1 + .025 * math.sin(t * 2.2) * (1 - self.ai_shown)

    def refresh(self):
        self.refresh_account()

    def refresh_account(self):
        from platform_utils import global_get
        acc = global_get("drive_account")
        on = bool(global_get("drive_enabled", False))
        btn = self.ids.google_btn
        if on:
            self.ids.account.text = f"Google Drive conectado · {acc or 'cuenta de Google'}"
            btn.text = "Cambiar cuenta de Google"
        else:
            self.ids.account.text = "Sin cuenta: se guarda en el teléfono hasta conectarla"
            btn.text = "Inicia sesión con Google"

    def connect_google(self):
        a = app()
        if not a.drive.available:
            a.toast("La cuenta de Google se conecta en el teléfono (Android).")
            return
        a.toast("Elija la cuenta de Google y acepte el permiso")

        def done(ok, msg):
            Clock.schedule_once(lambda *_: (a.toast(msg), self.refresh_account()))

        a.drive.connect(done)

    # ------------------------------------------------------------ sincronizar todo
    def sync_all(self):
        a = app()
        a.sync_all_crops()
        if getattr(self, "_spin_ev", None) is None:
            self._spin_ev = Clock.schedule_interval(self._spin, 1 / 30)

    def _spin(self, *_):
        if getattr(app(), "_syncing", False):
            self.sync_angle = (self.sync_angle - 9) % 360
            return
        self.sync_angle = 0
        self._spin_ev.cancel()
        self._spin_ev = None
        self.refresh_account()


class StartBase(MDScreen):
    """Lo primero que se ve al abrir un cultivo: I+D, Predio, Cuaderno, Rendimiento, pendientes
    de hoy y el estado de Drive. La lógica es una sola; el dibujo depende del estilo:
    StartScreen (íconos flotantes) o ui/start_tech.StartTech (tarjetas con datos)."""
    _animated = False
    sync_angle = NumericProperty(0)    # giro del botón sincronizar mientras trabaja

    def sync_now(self):
        """Botón junto al engranaje: trae ya lo de la cuenta de Google (otros equipos)."""
        a = app()
        if not (a.db.get_setting("drive_enabled", False) and a.drive.available):
            a.run_sync(manual=True)        # avisa que falta conectar Google Drive
            return
        if not getattr(a, "_syncing", False):
            a.toast("Sincronizando con Google Drive…")
        a.run_sync(manual=True)
        if getattr(self, "_spin_ev", None) is None:
            self._spin_ev = Clock.schedule_interval(self._spin, 1 / 30)

    def _spin(self, *_):
        if getattr(app(), "_syncing", False):
            self.sync_angle = (self.sync_angle - 9) % 360
            return
        self.sync_angle = 0
        self._spin_ev.cancel()
        self._spin_ev = None
        self.refresh()

    def on_pre_enter(self, *_):
        if not StartBase._animated:        # animación de entrada: solo la primera vez
            StartBase._animated = True
            self._prepare_intro()
        # La pantalla aparece al instante; los textos (consultas a la base) justo después.
        Clock.schedule_once(lambda *_: self.refresh(), 0)

    def on_enter(self, *_):
        if getattr(self, "_intro_ready", False):
            self._intro_ready = False
            self._play_intro()
        self._t0 = time.monotonic()
        from ui.idle_anim import IdleLoop     # 30 cuadros/s y se detiene sin toques (batería)
        self._loop = getattr(self, "_loop", None) or IdleLoop(self._float)
        self._loop.start()

    FLOAT = ((0.0, "ic_id"), (1.6, "ic_predio"), (4.8, "ic_nb"), (3.2, "ic_yield"))   # desfase de cada ícono

    def _float(self, *_):
        """Flotación suave y continua de los íconos: cada cuadro, solo mueve y escala en el
        canvas (no cambia tamaños ni reacomoda la pantalla)."""
        t = time.monotonic() - self._t0
        for phase, key in self.FLOAT:
            w = self.ids[key]
            k = math.sin(t * 1.5 + phase)
            w.bob = dp(4) * k
            w.pulse = 1 + .035 * math.sin(t * 1.5 + phase - .9)

    @staticmethod
    def neon(t: float) -> float:
        """Brillo neón del Entrenador IA: sube y baja suave y continuo (sin parpadeos)."""
        return .7 + .25 * math.sin(t * 1.6)

    def on_leave(self, *_):
        if getattr(self, "_loop", None):
            self._loop.stop()

    # ------------------------------------------------------------ animación
    def _prepare_intro(self):
        for w in (self.ids.ic_id, self.ids.ic_predio, self.ids.ic_nb, self.ids.ic_yield):
            w.reveal, w.lift = 0, dp(46)
        self.ids.logo.opacity = 0
        self._intro_ready = True

    def _play_intro(self):
        from kivy.animation import Animation
        logo = self.ids.logo
        h = logo.height
        logo.height = h * .7
        (Animation(opacity=1, height=h * 1.06, d=.32, t="out_cubic")
         + Animation(height=h, d=.16, t="in_out_sine")).start(logo)
        for i, w in enumerate((self.ids.ic_id, self.ids.ic_predio, self.ids.ic_nb, self.ids.ic_yield)):
            anim = Animation(d=.12 + .11 * i) + Animation(reveal=1, lift=0, d=.38, t="out_back")
            anim.start(w)

    # --------------------------------------------------------------- textos
    @staticmethod
    def _greeting() -> str:
        h = _dt.datetime.now().hour
        return "Buenos días" if 5 <= h < 12 else "Buenas tardes" if 12 <= h < 20 else "Buenas noches"

    @perf.timed("inicio.refrescar")
    def refresh(self):
        a = app()
        from workspaces import Workspaces
        name = (a.db.get_setting("user_name") or "").strip()
        self.ids.greeting.text = f"{self._greeting()}, {name}" if name else f"{self._greeting()} · toque para poner su nombre"
        ws = getattr(a, "workspace", None)
        try:
            units = a.db.pheno_units()
            ids = {v["id"] for v in units}
            done = sum(1 for r in a.db.query(
                "SELECT variety_id FROM observations WHERE week_id=? AND bbch_code IS NOT NULL",
                (a.week["id"],)) if r["variety_id"] in ids)
            what = {"predio": "sectores", "tratamientos": "parcelas"}.get(
                (ws or {}).get("kind") if (ws or {}).get("kind") == "tratamientos" else (ws or {}).get("profile"),
                "registros")
            self._show_week({"week": ph.week_of_year(a.week), "done": done, "total": len(units), "what": what,
                             "title": Workspaces.title(ws) if ws else "", "code": (ws or {}).get("code", ""),
                             "ws": ws})
        except Exception:  # noqa: BLE001 - nunca bloquear el inicio
            self._show_week(None)
        self._pills()
        self._postit()

    def _show_week(self, info: dict | None) -> None:
        """Avance del muestreo de la semana en el ensayo o predio en uso."""
        if not info:
            self.ids.week_lbl.text = ""
            return
        ws = info["ws"]
        self.ids.week_lbl.text = (f"Semana {info['week']} · {info['done']} de {info['total']} "
                                  f"{info['what']} · {info['title']}" if ws and info["total"] else
                                  (f"Último usado: {info['title']} ({info['code']})" if ws else ""))
        self.ids.week_bar.progress = info["done"] / info["total"] if info["total"] else 0

    def _pills(self):
        a = app()
        box = self.ids.pills
        box.clear_widgets()
        pills = []
        try:
            st = a.drive.status()
            if not st["enabled"]:
                pills.append(("Drive sin conectar", theme.MUTED))
            elif st["errors"]:
                pills.append((f"Drive: {st['errors']} con error", theme.WARN))
            elif st["pending"]:
                pills.append((f"Drive: {st['pending']} por subir", theme.WARN))
            else:
                pills.append(("Drive al día", theme.LEAF))
            last = a.db.query_one("SELECT MAX(observed_at) AS t FROM observations WHERE bbch_code IS NOT NULL")
            if last and last["t"]:
                days = (_dt.date.today() - _dt.date.fromisoformat(last["t"][:10])).days
                when = "hoy" if days <= 0 else "ayer" if days == 1 else f"hace {days} días"
                pills.append((f"Último registro: {when}", theme.BERRY))
            n_ai = sum(a.db.reference_counts().values())
            pills.append((f"IA: {n_ai} fotos", "#3A6BFF"))
        except Exception as exc:  # noqa: BLE001
            import crashguard
            crashguard.quiet(exc, "inicio: datos del ensayo")
        for text, col in pills:
            pill = StatusPill(text=text, color=c(col))
            pill.ids.lbl.texture_update()
            pill.width = dp(26) + pill.ids.lbl.texture_size[0]
            box.add_widget(pill)
        box.width = sum(p.width for p in box.children) + dp(6) * max(0, len(box.children) - 1)

    def ask_name(self):
        from kivy.factory import Factory
        a = app()
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
        field = Factory.Field(hint_text="Su nombre (para el saludo)", text=a.db.get_setting("user_name") or "")
        form.add_widget(field)

        def ok(_f):
            a.db.set_setting("user_name", field.text.strip())
            self.refresh()

        form_dialog("¿Cómo se llama?", form, ok)

    def open_profile(self, profile: str):
        app().open_workspaces(profile)

    # ------------------------------------------------------------ pendientes de hoy
    def _postit(self):
        from ui.pending import today_tasks
        try:
            self._tasks = today_tasks()
        except Exception:  # noqa: BLE001 - nunca bloquear el inicio
            self._tasks = []
        post = self.ids.postit
        lines = [t["short"] for t in self._tasks if not t["done"]]
        was = bool(post.lines)
        post.lines = lines
        if lines and not was:
            post.wobble()

    def open_tasks(self):
        from ui.pending import TasksSheet, today_tasks
        TasksSheet(today_tasks(), on_close=self._postit).open()

    def open_ai(self):
        app().open_ai_lab()


class StartScreen(StartBase):
    """Inicio de los estilos de siempre: íconos ilustrados que flotan y el post-it."""
