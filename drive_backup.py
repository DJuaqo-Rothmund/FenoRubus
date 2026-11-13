"""
drive_backup.py
===============
Respaldo de fotos en Google Drive (además de la copia en el teléfono).

* Cada foto nueva se encola en `drive_queue` (SQLite): el respaldo funciona sin
  conexión y se sube en cuanto hay red (reintentos con límite).
* Carpeta en «Mi unidad»:  PhenoRubus · Imágenes de Fenología / Año 2026 / Semana 37 · 07-09-2026 / …
* Permiso mínimo `drive.file`: la app solo ve los archivos que ella misma creó.
* Android: autorización con Google Identity Services (AuthorizationClient de
  play-services-auth); la subida usa la API REST v3 con urllib (sin librerías extra).
* El transporte HTTP y el proveedor de token son inyectables (pruebas / escritorio).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import os
import threading
import time

import perf
import urllib.error
import urllib.parse
import urllib.request
import uuid

import phenology as ph
from platform_utils import IS_ANDROID

SCOPE = "https://www.googleapis.com/auth/drive.file"
ROOT_FOLDER = "PhenoRubus · Imágenes de Fenología"   # raíz antigua (hasta la 1.1.151)
_FOLDER_LOCK = threading.RLock()     # buscar-o-crear carpetas: de a una (ver _folder)
# Permiso de Google (token): un solo pedido a la vez en toda la app y el token compartido
# entre todos los respaldos (ensayos, AeonScout, rendimiento, sincronización). Antes cada
# uno pedía el suyo y, si coincidían varios hilos, los «oyentes» Java de un pedido se
# borraban antes de que Google respondiera y la app se cerraba sin dejar error.
_TOKEN_LOCK = threading.RLock()
_SHARED_TOKEN: dict = {}
# Mientras corre algo que pidió el usuario (botón «Sincronizar»): si Google pide aceptar de
# nuevo el permiso, se puede abrir su ventana (en lo automático, nunca).
_INTERACTIVE_OK: dict = {"on": False}


class interactive_auth:
    """with interactive_auth(manual): permite abrir la ventana de Google si hace falta."""

    def __init__(self, on: bool = True):
        self.on, self.prev = on, False

    def __enter__(self):
        self.prev = _INTERACTIVE_OK["on"]
        _INTERACTIVE_OK["on"] = self.on or self.prev
        return self

    def __exit__(self, *exc):
        _INTERACTIVE_OK["on"] = self.prev
        return False             # cuenta -> (token, vence)
_AUTHORIZER = None                   # un solo AndroidAuthorizer para toda la app
FOLDER_MIME = "application/vnd.google-apps.folder"
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id"
MAX_ATTEMPTS = 6
UPLOAD_THREADS = 3                   # fotos que se suben a la vez
RC_DRIVE_AUTH = 7301
RC_PICK_ACCOUNT = 7302


class DriveError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class NeedsConsent(DriveError):
    """El usuario debe (re)conectar su cuenta desde Ajustes."""


class Offline(DriveError):
    """Sin red: se reintenta más tarde sin gastar intentos."""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _ssl_context():
    import ssl
    try:
        import certifi  # en Android no hay almacén de CA accesible para OpenSSL
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        raise Offline(f"Sin conexión: {getattr(e, 'reason', e)}") from e


# --------------------------------------------------------------- autorización
# Códigos de ApiException (CommonStatusCodes) más frecuentes al conectar.
API_HINTS = {
    "10": "DEVELOPER_ERROR: Google no reconoce la app. Revise en Google Cloud el ID de cliente "
          "Android: paquete org.rubus.fenorubus y huella SHA-1 exacta.",
    "12500": "Error al iniciar sesión: actualice Servicios de Google Play y revise la pantalla "
             "de consentimiento (usuario de prueba agregado).",
    "12501": "Conexión cancelada.",
    "16": "Conexión cancelada.",
    "7": "Sin conexión a internet.",
    "8": "Error interno de Google: intente de nuevo.",
    "17": "Servicios de Google Play no disponibles en este teléfono.",
}


def explain(error: str) -> str:
    """Convierte «ApiException: 10: …» en una explicación útil."""
    import re as _re
    m = _re.search(r"ApiException:\s*(\d+)", error or "")
    if m and m[1] in API_HINTS:
        return f"{API_HINTS[m[1]]} (código {m[1]})"
    if "ClassNotFound" in (error or "") or "NoClassDefFound" in (error or "") \
            or "Class not found" in (error or ""):
        # El comienzo dice QUÉ clase faltó (el final es solo la pila de llamadas).
        head = " ".join((error or "").split())[:220]
        return f"La app no pudo cargar una clase de Android/Google. Detalle: {head}"
    return error


def _detach():
    try:
        from jnius import detach  # type: ignore
        detach()  # obligatorio al terminar un hilo de Python que usó Java
    except Exception:  # noqa: BLE001
        pass


class AndroidAuthorizer:
    """Token OAuth de Drive vía `Identity.getAuthorizationClient(activity)`.

    Importante: en Android, pyjnius busca clases con JNI FindClass, que desde un hilo
    creado por Python solo ve las clases del sistema (no las de la app, como Google
    Play Services). Por eso toda llamada a clases de Google se hace en el hilo
    principal de Kivy (`_on_main`); el hilo de fondo solo espera.
    """

    AUTHORIZE_TIMEOUT = 45
    CONSENT_TIMEOUT = 300
    GOOGLE_CLASSES = ("com.google.android.gms.auth.api.identity.Identity",
                      "com.google.android.gms.auth.api.identity.AuthorizationRequest",
                      "com.google.android.gms.auth.api.identity.AuthorizationResult",
                      "com.google.android.gms.common.api.Scope")

    def __init__(self, log=None):
        from android import activity  # type: ignore
        self.log = log or (lambda msg: None)
        self._pending = {}            # código -> (event, holder) de una pantalla de Google
        self.account = None           # correo de la cuenta elegida (None: la que recuerde Google)
        self._listeners = []          # referencias vivas para pyjnius
        activity.bind(on_activity_result=self._on_activity_result)

    # ---------------------------------------------------------- hilo principal
    @staticmethod
    def _on_main(fn, timeout: float = 20):
        """Ejecuta fn en el hilo principal de Kivy y devuelve su resultado."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        from kivy.clock import Clock
        ev, box = threading.Event(), {}

        def run(*_):
            try:
                box["value"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
            ev.set()

        Clock.schedule_once(run, 0)
        if not ev.wait(timeout):
            raise DriveError("La app no respondió (hilo principal ocupado)")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def preload(self) -> None:
        """Carga las clases de Google (llamar en el hilo principal)."""
        from jnius import autoclass  # type: ignore
        for name in self.GOOGLE_CLASSES:
            autoclass(name)

    def _request(self):
        from jnius import autoclass  # type: ignore
        scopes = autoclass("java.util.ArrayList")()
        scopes.add(autoclass("com.google.android.gms.common.api.Scope")(SCOPE))
        builder = autoclass("com.google.android.gms.auth.api.identity.AuthorizationRequest") \
            .builder().setRequestedScopes(scopes)
        if self.account:   # cuenta elegida por el usuario (si no, Google usa la última autorizada)
            builder = builder.setAccount(autoclass("android.accounts.Account")(self.account, "com.google"))
        req = builder.build()
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        client = autoclass("com.google.android.gms.auth.api.identity.Identity").getAuthorizationClient(act)
        return client, req

    # ----------------------------------------------------------- autorización
    def get_token(self, interactive: bool, timeout: float | None = None) -> str:
        done = threading.Event()
        box: dict = {}

        def start():
            from jnius import PythonJavaClass, java_method  # type: ignore

            class Success(PythonJavaClass):
                __javainterfaces__ = ["com/google/android/gms/tasks/OnSuccessListener"]
                __javacontext__ = "app"

                @java_method("(Ljava/lang/Object;)V")
                def onSuccess(self, result):  # noqa: N802
                    box["result"] = result
                    done.set()

            class Failure(PythonJavaClass):
                __javainterfaces__ = ["com/google/android/gms/tasks/OnFailureListener"]
                __javacontext__ = "app"

                @java_method("(Ljava/lang/Exception;)V")
                def onFailure(self, exc):  # noqa: N802
                    try:
                        box["error"] = exc.toString()
                    except Exception as e:  # noqa: BLE001
                        box["error"] = repr(e)
                    done.set()

            self.preload()
            client, req = self._request()
            ok, ko = Success(), Failure()
            # Vivos hasta que Google responda (si se soltaban antes, Java llamaba a un objeto
            # ya borrado y la app se cerraba).
            self._listeners.append((ok, ko))
            del self._listeners[:-8]
            task = client.authorize(req)
            task.addOnSuccessListener(ok)
            task.addOnFailureListener(ko)

        self.log("Pidiendo autorización a Google…")
        try:
            self._on_main(start)
        except DriveError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DriveError(explain(f"No se pudo preparar la autorización: {exc}")) from exc
        if not done.wait(timeout or self.AUTHORIZE_TIMEOUT):
            raise DriveError("Google no respondió (¿Servicios de Google Play desactualizados o sin red?)")
        if "error" in box:
            raise DriveError(explain(box["error"]))

        def read_result():
            from jnius import cast  # type: ignore
            res = cast("com.google.android.gms.auth.api.identity.AuthorizationResult", box["result"])
            if res.hasResolution():
                return None, res.getPendingIntent()
            return res.getAccessToken(), None

        token, pending_intent = self._on_main(read_result)
        if pending_intent is not None:
            if not interactive:
                raise NeedsConsent("Conecte su cuenta de Google en Ajustes")
            self.log("Abriendo el selector de cuenta de Google…")
            return self._resolve(pending_intent)
        if not token:
            raise DriveError("Google no entregó un token de acceso")
        return token

    def choose_account(self) -> str:
        """Selector de cuentas de Google del teléfono. Devuelve el correo elegido."""
        ev, holder = threading.Event(), {}
        self._pending[RC_PICK_ACCOUNT] = (ev, holder)

        def launch():
            from jnius import autoclass  # type: ignore
            AccountManager = autoclass("android.accounts.AccountManager")
            current = autoclass("android.accounts.Account")(self.account, "com.google") \
                if self.account else None
            intent = AccountManager.newChooseAccountIntent(
                current, None, ["com.google"], "Cuenta de Google para el respaldo en Drive",
                None, None, None)
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            act.startActivityForResult(intent, RC_PICK_ACCOUNT)

        self.log("Abriendo la lista de cuentas de Google…")
        try:
            self._on_main(launch)
        except Exception as exc:  # noqa: BLE001
            self._pending.pop(RC_PICK_ACCOUNT, None)
            raise DriveError(explain(f"No se pudo abrir la lista de cuentas: {exc}")) from exc
        if not ev.wait(self.CONSENT_TIMEOUT):
            self._pending.pop(RC_PICK_ACCOUNT, None)
            raise DriveError("No se eligió ninguna cuenta (tiempo agotado)")
        if "error" in holder:
            raise DriveError("No se eligió ninguna cuenta")
        name = self._on_main(lambda data=holder["data"]: data.getStringExtra("authAccount"))
        if not name:
            raise DriveError("No se eligió ninguna cuenta")
        return str(name)

    def _resolve(self, pending_intent) -> str:
        ev, holder = threading.Event(), {}
        self._pending[RC_DRIVE_AUTH] = (ev, holder)

        def launch():
            from jnius import autoclass  # type: ignore
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            # Versión de 6 argumentos (sin Bundle): evita ambigüedad de sobrecargas.
            act.startIntentSenderForResult(pending_intent.getIntentSender(), RC_DRIVE_AUTH,
                                           None, 0, 0, 0)

        try:
            self._on_main(launch)
        except Exception as exc:  # noqa: BLE001
            self._pending.pop(RC_DRIVE_AUTH, None)
            raise DriveError(f"No se pudo abrir el selector de cuenta: {exc}") from exc
        if not ev.wait(self.CONSENT_TIMEOUT):  # el usuario elige cuenta y acepta
            self._pending.pop(RC_DRIVE_AUTH, None)
            raise DriveError("No se completó la conexión con Google (tiempo agotado)")
        if "error" in holder:
            raise DriveError(explain(holder["error"]))

        def read(data=holder.get("data")):
            client, _req = self._request()
            return client.getAuthorizationResultFromIntent(data).getAccessToken()

        try:
            token = self._on_main(read)
        except Exception as exc:  # noqa: BLE001 (ApiException de Java incluida)
            raise DriveError(explain(str(exc)) or "Conexión cancelada") from exc
        if not token:
            raise DriveError("Google no entregó un token de acceso")
        return token

    def _on_activity_result(self, request_code, result_code, data):
        if request_code not in self._pending:
            return
        ev, holder = self._pending.pop(request_code)
        if data is None or (request_code == RC_PICK_ACCOUNT and result_code != -1):   # -1 = RESULT_OK
            holder["error"] = f"Conexión cancelada (resultado {result_code})"
        else:
            holder["data"] = data   # se interpreta en el hilo principal de Kivy
        ev.set()


def is_metered() -> bool:
    """True si la red activa es de datos móviles (o medida)."""
    if not IS_ANDROID:
        return False
    try:
        from jnius import autoclass  # type: ignore
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        Context = autoclass("android.content.Context")
        cm = act.getSystemService(Context.CONNECTIVITY_SERVICE)
        # «Solo con Wi-Fi» = conectado por Wi-Fi o cable (aunque Android marque esa red Wi-Fi
        # como «de uso medido», p. ej. un punto de acceso).
        caps = cm.getNetworkCapabilities(cm.getActiveNetwork())
        if caps is not None:
            NC = autoclass("android.net.NetworkCapabilities")
            if caps.hasTransport(NC.TRANSPORT_WIFI) or caps.hasTransport(NC.TRANSPORT_ETHERNET):
                return False
            return bool(caps.hasTransport(NC.TRANSPORT_CELLULAR)) or bool(cm.isActiveNetworkMetered())
        return bool(cm.isActiveNetworkMetered())
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------- respaldo
class DriveBackup:
    TOKEN_TTL = 45 * 60

    def __init__(self, db, authorizer=None, transport=None, metered=is_metered, crop=None):
        import crops
        self.db = db
        # El cultivo queda fijo: aunque luego se active otro (sincronizar todo), lo de esta
        # base va siempre a la carpeta de SU módulo.
        self.crop = crop or crops.current()
        self._authorizer = authorizer
        self.transport = transport or urllib_transport
        self.metered = metered
        self._token: tuple[str, float] | None = None
        self._flush_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._again = False
        self.running = False
        self.listeners: list = []   # callbacks(status) al cambiar el estado

    # ----------------------------------------------------------- ajustes
    @property
    def enabled(self) -> bool:
        return bool(self.db.get_setting("drive_enabled", False))

    @property
    def wifi_only(self) -> bool:
        return bool(self.db.get_setting("drive_wifi_only", True))

    @property
    def authorizer(self):
        if self._authorizer is None and IS_ANDROID:
            # Se crea en el hilo principal: al registrarse para recibir el resultado de la
            # cuenta de Google, pyjnius crea un «listener» Java que solo encuentra las
            # clases de la app desde ese hilo (desde un hilo de fondo fallaba con
            # ClassNotFoundException · «No se encontró un componente…»). Uno solo para toda
            # la app (antes uno por respaldo, cada uno pidiendo su permiso).
            # Sin candado: el hilo principal también pasa por aquí y no debe esperar a un
            # hilo de fondo que a su vez espera al principal.
            global _AUTHORIZER
            if _AUTHORIZER is None:
                made = AndroidAuthorizer._on_main(lambda: AndroidAuthorizer(log=self.log))
                if _AUTHORIZER is None:
                    _AUTHORIZER = made
            self._authorizer = _AUTHORIZER
            self._authorizer.account = self.account
        elif self._authorizer is None:
            # PC (Windows): inicio de sesión en el navegador, si esta copia trae la credencial.
            from desktop_auth import DesktopAuthorizer, client_config
            from platform_utils import get_data_dir
            client = client_config(get_data_dir())
            if client:
                self._authorizer = DesktopAuthorizer(self.db, self.transport, client, log=self.log)
        return self._authorizer

    @property
    def account(self) -> str | None:
        """Correo de la cuenta de Google elegida (None en conexiones de versiones anteriores)."""
        return self.db.get_setting("drive_account") or None

    def log(self, message: str, error: bool = False) -> None:
        """Paso visible en la tarjeta de Ajustes + historial para «Ver diagnóstico»."""
        hist = self.db.get_setting("drive_log") or []
        hist.append(f"{_dt.datetime.now():%d/%m %H:%M:%S} {'✗ ' if error else ''}{message}")
        self.db.set_setting("drive_log", hist[-40:])
        self._set_message(message)

    def diagnostics(self) -> list[str]:
        """Archivos que no se pudieron subir (con su motivo) + historial reciente."""
        return self.failed_items() + list(reversed(self.db.get_setting("drive_log") or []))

    @property
    def available(self) -> bool:
        return self.authorizer is not None

    def status(self) -> dict:
        counts = {r["status"]: r["n"] for r in self.db.query(   # «skipped» no cuenta
            "SELECT status, COUNT(*) AS n FROM drive_queue GROUP BY status")}
        st = self.db.get_setting("drive_status") or {}
        return {"enabled": self.enabled, "available": self.available, "wifi_only": self.wifi_only,
                "pending": counts.get("pending", 0), "done": counts.get("done", 0),
                "errors": counts.get("error", 0), "running": self.running,
                "last_sync": st.get("last_sync"), "message": st.get("message", ""),
                "account": self.account}

    def _set_message(self, message: str, synced: bool = False) -> None:
        st = self.db.get_setting("drive_status") or {}
        st["message"] = message
        if synced:
            st["last_sync"] = _now()
        self.db.set_setting("drive_status", st)
        for cb in list(self.listeners):
            try:
                cb(self.status())
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------- cola
    @staticmethod
    def week_folder(start_date: str) -> str:
        """«Año 2026/Semana 40 · 28-09-2026»: semana del año ISO (el número ordena las carpetas)."""
        d = _dt.date.fromisoformat(str(start_date)[:10])
        week, year = ph.iso_week(d)
        return f"Año {year}/Semana {week:02d} · {d:%d-%m-%Y}"

    @property
    def prefix(self) -> str:
        """Carpeta del ensayo o predio: «I+D/Nuevas variedades/», «Predio/El Amanecer/»."""
        ws = getattr(self.db, "workspace", None) or {}
        if not ws:
            return ""
        from workspaces import Workspaces
        return Workspaces.drive_prefix(ws) + "/"

    def week_path(self, start_date: str) -> str:
        return f"{self.prefix}{self.week_folder(start_date)}"

    def _remote_name(self, photo_id: int | None, path: str) -> str:
        """Carpeta de la SEMANA de muestreo de la foto (y, en I+D, la de su variedad o
        parcela) + nombre del archivo."""
        return self._target_for(path, photo_id) or f"{self.prefix}{os.path.basename(path)}"

    def _unit_folder(self, variety_id) -> str:
        """En los ensayos de I+D, la subcarpeta de la variedad, parcela (T1R1…) o punto de
        fenología dentro de la carpeta de la semana; en los predios, ninguna."""
        ws = getattr(self.db, "workspace", None) or {}
        if ws.get("profile") != "id" or not variety_id:
            return ""
        v = self.db.query_one("SELECT name FROM varieties WHERE id=?", (variety_id,))
        return (v["name"] or "").replace("/", "-").strip() if v else ""

    def _target_for(self, path: str | None, photo_id: int | None = None) -> str | None:
        """Ruta en Drive que le corresponde a una foto del registro, una adjunta o una foto de
        medición, según su semana y su variedad/parcela:
        «<ensayo>/Año 2026/Semana 44 · 26-10-2026/T1R1/[Adjuntas|<medición>/]foto.jpg».
        None si el archivo no es de ninguno de esos registros."""
        if not path:
            return None
        row, sub = None, ""
        q = ("SELECT w.start_date, o.variety_id FROM photos p JOIN observations o ON o.id = p.observation_id "
             "JOIN sampling_weeks w ON w.id = o.week_id WHERE ")
        if photo_id is not None:
            row = self.db.query_one(q + "p.id = ?", (photo_id,))
        if row is None:
            row = self.db.query_one(q + "p.path = ?", (path,))
        if row is None:
            row = self.db.query_one("SELECT w.start_date, a.variety_id FROM variety_attachments a "
                                    "JOIN sampling_weeks w ON w.id = a.week_id WHERE a.path = ?", (path,))
            sub = "Adjuntas" if row else ""
        if row is None:
            row = self.db.query_one("SELECT w.start_date, e.variety_id, m.name AS mname FROM measure_entries e "
                                    "JOIN measures m ON m.id = e.measure_id JOIN sampling_weeks w "
                                    "ON w.id = e.week_id WHERE e.path = ?", (path,))
            sub = (row["mname"] or "Otras").replace("/", "-").strip() if row else ""
        if row is None:
            return None
        parts = [self.week_path(row["start_date"]), self._unit_folder(row["variety_id"]), sub,
                 os.path.basename(path)]
        return "/".join(p for p in parts if p)

    def enqueue_report(self, path: str, flush: bool = True) -> str:
        """Sube un informe: los semanales van a la carpeta de su semana; el resto a
        «Año …/Informes». Devuelve la ruta en Drive."""
        import re
        base = os.path.basename(path)
        remote = None
        m = re.match(r"semanal_(?:[A-Z0-9]{2,4}_)?(\d{4})_S(\d+)", base)   # semanal_NV_2026_S37
        old = re.match(r"semanal_T(\d{4})_S(\d+)", base)       # formato anterior (n.º de muestreo)
        if m:
            try:
                start = _dt.date.fromisocalendar(int(m[1]), int(m[2]), 1)
            except ValueError:
                start = None
            if start:
                w = self.db.query_one(
                    "SELECT start_date FROM sampling_weeks WHERE start_date BETWEEN ? AND ? "
                    "ORDER BY start_date LIMIT 1",
                    (start.isoformat(), (start + _dt.timedelta(days=6)).isoformat()))
                remote = f"{self.week_path(w['start_date'] if w else start.isoformat())}/{base}"
        elif old:
            w = self.db.query_one("SELECT start_date FROM sampling_weeks WHERE season=? AND week_number=?",
                                  (int(old[1]), int(old[2])))
            if w:
                remote = f"{self.week_path(w['start_date'])}/{base}"
        if remote is None:
            t = re.search(r"_T?(\d{4})(?=[_.-]|$)", base)
            year = int(t[1]) if t else _dt.date.today().year
            remote = f"{self.prefix}Año {year}/Informes/{base}"
        self.enqueue(None, path, remote=remote, flush=flush)
        return remote

    def enqueue(self, photo_id: int | None, path: str, flush: bool = True,
                remote: str | None = None) -> int | None:
        if photo_id is not None and self.db.query_one(
                "SELECT id FROM drive_queue WHERE photo_id=? AND path=?", (photo_id, path)):
            return None
        cur = self.db.execute(
            "INSERT INTO drive_queue(photo_id, path, name, created_at) VALUES (?,?,?,?)",
            (photo_id, path, remote or self._remote_name(photo_id, path), _now()))
        if flush:
            self.flush_async()
        return cur.lastrowid

    def enqueue_existing(self) -> int:
        """Encola todas las fotos guardadas que aún no están en la cola."""
        rows = self.db.query(
            "SELECT p.id, p.path FROM photos p WHERE NOT EXISTS "
            "(SELECT 1 FROM drive_queue q WHERE q.photo_id = p.id AND q.path = p.path)")
        n = 0
        for r in rows:
            if os.path.exists(r["path"]):
                self.enqueue(r["id"], r["path"], flush=False)
                n += 1
        if n:
            self.flush_async()
        return n

    DB_BACKUP_EVERY_H = 24
    DB_BACKUPS_KEPT = 5

    def backup_database(self, force: bool = False) -> str | None:
        """Copia diaria de la base (sin fotos, que ya están en Drive) a «Respaldos»."""
        last = self.db.get_setting("db_backup_last")      # por ensayo (no es ajuste global)
        if not force and last and (_dt.datetime.now() - _dt.datetime.fromisoformat(last)
                                   ).total_seconds() < self.DB_BACKUP_EVERY_H * 3600:
            return None
        from data_transfer import _checkpoint_copy
        from platform_utils import data_subdir
        folder = data_subdir("backups", "diarios")
        dest = _checkpoint_copy(self.db, os.path.join(
            folder, f"PhenoRubus_base_{self.db.code + '_' if self.db.code else ''}"
                    f"{_dt.datetime.now():%Y-%m-%d_%H%M}.sqlite3"))
        old = sorted(f for f in os.listdir(folder) if f.endswith(".sqlite3"))
        for f in old[:-self.DB_BACKUPS_KEPT]:
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass
        self.db.set_setting("db_backup_last", _now())
        self.enqueue(None, dest, remote=f"{self.prefix}Respaldos/{os.path.basename(dest)}")
        return dest

    def retry_errors(self) -> None:
        self._skip_missing()
        self.db.execute("UPDATE drive_queue SET status='pending', attempts=0 WHERE status='error'")
        self.flush_async()

    def _skip_missing(self) -> int:
        """Entradas con error cuyo archivo ya no existe (foto borrada o reemplazada): se
        omiten para que no queden «pegadas» en 181 de 182."""
        n = 0
        for r in self.db.query("SELECT id, path FROM drive_queue WHERE status='error'"):
            if not os.path.exists(r["path"] or ""):
                self.db.execute("UPDATE drive_queue SET status='skipped', error=? WHERE id=?",
                                ("El archivo ya no existe en el teléfono", r["id"]))
                n += 1
        return n

    def failed_items(self) -> list[str]:
        return [f"✗ {os.path.basename(r['path'] or r['name'])}: {r['error'] or 'sin detalle'}"
                for r in self.db.query("SELECT path, name, error FROM drive_queue "
                                       "WHERE status='error' ORDER BY id LIMIT 20")]

    # ------------------------------------------------------------ conexión
    def connect(self, callback=None, choose: bool = True) -> None:
        """Autorización interactiva (desde Ajustes). callback(ok, mensaje).
        choose=True: primero la lista de cuentas de Google del teléfono (cambiar de cuenta)."""
        def work():
            try:
                self.log("Conectando con Google…")
                if not self.available:
                    raise DriveError("Esta copia de la app no trae la credencial de Google")
                auth = self.authorizer
                if choose and hasattr(auth, "choose_account"):
                    name = auth.choose_account()
                    self.log(f"Cuenta elegida: {name}")
                    self.use_account(name)
                with _TOKEN_LOCK:
                    token = auth.get_token(interactive=True)
                    self._token = _SHARED_TOKEN[self.account or ""] = (token, time.monotonic() + self.TOKEN_TTL)
                self.db.set_setting("drive_enabled", True)
                who = self.account
                self.log(f"Cuenta conectada{': ' + who if who else ''}")
                ok, msg = True, f"Google Drive conectado{' (' + who + ')' if who else ''}"
            except Exception as exc:  # noqa: BLE001
                ok, msg = False, explain(str(exc)) or exc.__class__.__name__
                self.log(msg, error=True)
            if callback:
                callback(ok, msg)
            try:
                if ok:
                    self.flush()
            finally:
                _detach()

        threading.Thread(target=work, daemon=True).start()

    def use_account(self, name: str | None) -> None:
        """Cambia la cuenta de Google. Las carpetas en caché son de la cuenta anterior."""
        if (name or None) != self.account:
            self.db.set_setting("drive_account", name or None)
            self.db.set_setting("drive_folders", {})
            self._token = None
            _SHARED_TOKEN.clear()
        if self._authorizer is not None:
            self._authorizer.account = name or None

    def _sync_account_queue(self) -> None:
        """Si se cambió de cuenta, lo ya subido a la cuenta anterior se vuelve a subir a la
        nueva (cada ensayo o predio lo hace al sincronizar)."""
        acc = self.account
        if not acc:
            return
        mine = self.db.get_setting("queue_account")    # ajuste de ESTE ensayo (no global)
        if mine and mine != acc:
            n = self.db.execute("UPDATE drive_queue SET status='pending', attempts=0, drive_id=NULL, "
                                "error='' WHERE status != 'pending'").rowcount
            self.log(f"Nueva cuenta {acc}: {n} archivos se suben de nuevo")
        if mine != acc:
            self.db.set_setting("queue_account", acc)

    def disconnect(self) -> None:
        """Deja de subir y retira el permiso de la app en la cuenta (para poder elegir otra)."""
        token = self._token[0] if self._token else None
        self.db.set_setting("drive_enabled", False)
        self._token = None
        _SHARED_TOKEN.clear()
        if hasattr(self._authorizer, "forget"):
            self._authorizer.forget()          # PC: la próxima vez vuelve a pedir la cuenta
        if token:   # revocar en Google: la próxima conexión vuelve a pedir cuenta y permiso
            def revoke():
                try:
                    self.transport("POST", "https://oauth2.googleapis.com/revoke?" +
                                   urllib.parse.urlencode({"token": token}),
                                   {"Content-Type": "application/x-www-form-urlencoded"}, b"")
                except Exception:  # noqa: BLE001 - sin red: igual queda desconectada en la app
                    pass
            threading.Thread(target=revoke, daemon=True).start()
        self._set_message("Respaldo desactivado")

    def _get_token(self) -> str:
        if self._token and self._token[1] > time.monotonic():
            return self._token[0]
        with _TOKEN_LOCK:                    # un pedido a la vez; los demás reusan el token
            key = self.account or ""
            shared = _SHARED_TOKEN.get(key)
            if shared and shared[1] > time.monotonic():
                self._token = shared
                return shared[0]
            if not self.available:
                raise NeedsConsent("Sin cuenta de Google conectada")
            auth = self.authorizer
            auth.account = self.account        # el autorizador es uno solo para toda la app
            try:
                token = auth.get_token(interactive=False)
            except NeedsConsent:
                # Google pide volver a aceptar el permiso. Si fue el usuario quien tocó
                # «Sincronizar», se abre la ventana de Google (antes solo fallaba con
                # «Conecte su cuenta de Google en Ajustes»).
                if not (_INTERACTIVE_OK.get("on") and self.db.get_setting("drive_enabled", False)):
                    raise
                self.log("Google pide aceptar de nuevo el permiso: abriendo su ventana…")
                token = auth.get_token(interactive=True)
            self._token = _SHARED_TOKEN[key] = (token, time.monotonic() + self.TOKEN_TTL)
            return token

    def _drop_token(self) -> None:
        """Token rechazado (vencido): se olvida aquí y en el compartido."""
        with _TOKEN_LOCK:
            old = self._token
            self._token = None
            key = self.account or ""
            if old and _SHARED_TOKEN.get(key) == old:
                _SHARED_TOKEN.pop(key, None)

    # ------------------------------------------------------------ API REST
    def _call(self, method: str, url: str, body: bytes | None = None,
              content_type: str | None = None) -> dict:
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._get_token()}"}
            if content_type:
                headers["Content-Type"] = content_type
            t0 = time.perf_counter()
            status, data = self.transport(method, url, headers, body)
            perf.add("drive.pedidos")
            perf.add("drive.pedidos ms", (time.perf_counter() - t0) * 1000)
            if status == 401 and attempt == 0:
                self._drop_token()  # token vencido: pedir otro una vez
                continue
            if status >= 400:
                try:
                    msg = json.loads(data)["error"]["message"]
                except Exception:  # noqa: BLE001
                    msg = data[:200].decode("utf-8", "replace")
                if status == 401:
                    raise NeedsConsent("Google rechazó el acceso: reconecte su cuenta", status)
                raise DriveError(f"Drive {status}: {msg}", status)
            return json.loads(data or b"{}")
        raise NeedsConsent("Google rechazó el acceso")

    def _download(self, file_id: str) -> bytes:
        """Contenido de un archivo creado por la app (paquetes de sincronización, fotos)."""
        url = f"{API}/{file_id}?alt=media"
        perf.add("drive.bajadas")
        for attempt in range(2):
            status, data = self.transport("GET", url, {"Authorization": f"Bearer {self._get_token()}"}, None)
            if status == 401 and attempt == 0:
                self._drop_token()
                continue
            if status >= 400:
                raise DriveError(f"Drive {status}: {data[:200].decode('utf-8', 'replace')}", status)
            return data
        raise NeedsConsent("Google rechazó el acceso")

    def _folder(self, name: str, parent: str | None) -> str:
        cache = self.db.get_setting("drive_folders") or {}
        key = f"{parent or 'root'}/{name}"
        if key in cache:
            return cache[key]
        # Una sola búsqueda-o-creación a la vez en toda la app: subidas, sincronización y
        # «sincronizar todo» corren en hilos distintos y, sin esto, cada uno creaba su copia.
        with _FOLDER_LOCK:
            cache = self.db.get_setting("drive_folders") or {}
            if key in cache:
                return cache[key]
            fid = self._find_folder(name, parent)
            if fid is None:
                meta = {"name": name, "mimeType": FOLDER_MIME}
                if parent:
                    meta["parents"] = [parent]
                fid = self._call("POST", f"{API}?fields=id", json.dumps(meta).encode(),
                                 "application/json; charset=UTF-8")["id"]
            cache = self.db.get_setting("drive_folders") or {}
            cache[key] = fid
            self.db.set_setting("drive_folders", cache)
            return fid

    def root_id(self) -> str:
        """Carpeta del módulo en Drive: «AeonCrop/<PhenoRubus|PhenoBlue|PhenoCran>».
        Frambuesa: la primera vez, la carpeta antigua «PhenoRubus · Imágenes de Fenología»
        (con todo lo respaldado) se mueve ahí y pasa a llamarse «PhenoRubus»."""
        import crops
        crop = self.crop
        cache = self.db.get_setting("drive_folders") or {}
        key = f"module/{crop.drive_folder}"
        # Una vez por módulo: se busca de nuevo para juntar carpetas del módulo repetidas
        # (p. ej. dos «PhenoBlue» creadas a la vez antes del arreglo de duplicados).
        once = f"module_dupes_checked_v1/{crop.drive_folder}"
        if key in cache and not self.db.get_setting(once):
            cache.pop(key, None)
            self.db.set_setting("drive_folders", cache)
            self.db.set_setting(once, True)
        if key in cache:
            return cache[key]
        with _FOLDER_LOCK:
            return self._root_locked(crop, key)

    def _root_locked(self, crop, key: str) -> str:
        import crops
        cache = self.db.get_setting("drive_folders") or {}
        if key in cache:
            return cache[key]
        top = self._find_folder(crops.DRIVE_TOP, None)
        if top is None:
            # «App Fenología» (versiones anteriores) pasa a llamarse «AeonCrop», con todo.
            old_top = self._find_folder(crops.DRIVE_TOP_OLD, None)
            if old_top is not None:
                self._call("PATCH", f"{API}/{old_top}?fields=id",
                           json.dumps({"name": crops.DRIVE_TOP}).encode(), "application/json; charset=UTF-8")
                self.log(f"Drive: «{crops.DRIVE_TOP_OLD}» pasa a llamarse «{crops.DRIVE_TOP}»")
                top = old_top
            else:
                top = self._folder(crops.DRIVE_TOP, None)
        fid = self._find_folder(crop.drive_folder, top)
        if fid is None and crop.id == "frambuesa":
            old = self._find_folder(ROOT_FOLDER, None)
            if old is not None:
                parents = self._call("GET", f"{API}/{old}?fields=parents").get("parents", [])
                self._call("PATCH", f"{API}/{old}?" + urllib.parse.urlencode(
                    {"addParents": top, "removeParents": ",".join(parents), "fields": "id"}),
                    json.dumps({"name": crop.drive_folder}).encode(), "application/json; charset=UTF-8")
                fid = old
                self.log(f"Drive: «{ROOT_FOLDER}» pasa a «{crops.DRIVE_TOP}/{crop.drive_folder}»")
        if fid is None:
            fid = self._folder(crop.drive_folder, top)
        cache = self.db.get_setting("drive_folders") or {}
        cache[key] = fid
        self.db.set_setting("drive_folders", cache)
        return fid

    def _find_folder(self, name: str, parent: str | None) -> str | None:
        """La carpeta con ese nombre (la más antigua). Si hay copias repetidas (de versiones
        que las creaban a la vez desde dos hilos), su contenido pasa a la más antigua y las
        copias vacías van a la papelera."""
        esc = name.replace("\\", "\\\\").replace("'", "\\'")
        q = f"name='{esc}' and mimeType='{FOLDER_MIME}' and trashed=false"
        if parent:
            q += f" and '{parent}' in parents"
        found = self._call("GET", f"{API}?" + urllib.parse.urlencode(
            {"q": q, "fields": "files(id, name, createdTime)", "spaces": "drive",
             "orderBy": "createdTime"})).get("files", [])
        if not found:
            return None
        found.sort(key=lambda f: f.get("createdTime") or "")
        keep = found[0]["id"]
        for dup in [f for f in found[1:] if f.get("name") == name and f["id"] != keep]:
            try:
                self._merge_folder(dup["id"], keep)
            except DriveError as exc:      # se reintenta la próxima vez; nunca frena la subida
                self.log(f"Drive: no se pudo juntar la carpeta repetida «{name}»: {exc}", error=True)
        return keep

    def _merge_folder(self, src: str, dst: str) -> None:
        """Mueve todo lo de `src` a `dst` (juntando también subcarpetas repetidas) y manda
        `src`, ya vacía, a la papelera."""
        token = None
        children = []
        while True:
            params = {"q": f"'{src}' in parents and trashed=false",
                      "fields": "nextPageToken, files(id, name, mimeType)", "pageSize": "1000"}
            if token:
                params["pageToken"] = token
            res = self._call("GET", f"{API}?" + urllib.parse.urlencode(params))
            children += res.get("files", [])
            token = res.get("nextPageToken")
            if not token:
                break
        for ch in children:
            if ch.get("mimeType") == FOLDER_MIME:
                esc = ch["name"].replace("\\", "\\\\").replace("'", "\\'")
                same = self._call("GET", f"{API}?" + urllib.parse.urlencode(
                    {"q": f"name='{esc}' and mimeType='{FOLDER_MIME}' and '{dst}' in parents and trashed=false",
                     "fields": "files(id)"})).get("files", [])
                if same:
                    self._merge_folder(ch["id"], same[0]["id"])
                    continue
            self._call("PATCH", f"{API}/{ch['id']}?" + urllib.parse.urlencode(
                {"addParents": dst, "removeParents": src, "fields": "id"}), b"{}",
                "application/json; charset=UTF-8")
        self._call("PATCH", f"{API}/{src}?fields=id", json.dumps({"trashed": True}).encode(),
                   "application/json; charset=UTF-8")
        self.db.set_setting("drive_folders", {})      # las rutas en caché pudieron cambiar
        self.log("Drive: se juntó una carpeta repetida")

    def _upload(self, path: str, remote: str) -> str:
        with perf.timed("drive.carpeta del archivo"):
            parent, fname = self._parent_of(remote)
        try:
            with perf.timed("drive.subir archivo", lambda: f"{os.path.getsize(path) // 1024} KB"):
                perf.add("drive.subidas")
                return self._post_file(path, fname, parent)
        except DriveError as exc:
            if exc.status == 404:  # la carpeta se borró en Drive: recrearla la próxima vez
                self.db.set_setting("drive_folders", {})
            raise

    def _parent_of(self, remote: str) -> tuple[str, str]:
        """(id de la carpeta, nombre del archivo) de «<carpetas>/<archivo>» (crea las carpetas)."""
        *dirs, fname = remote.split("/")
        parent = self.root_id()
        for d in dirs:
            parent = self._folder(d, parent)
        return parent, fname

    def _post_file(self, path: str, fname: str, parent: str) -> str:
        """Sube el archivo a la carpeta `parent` (solo red: se puede llamar desde varios hilos)."""
        with open(path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".zip": "application/zip", ".sqlite3": "application/x-sqlite3",
                ".html": "text/html", ".pdf": "application/pdf",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(ext, "image/jpeg")
        boundary = uuid.uuid4().hex
        meta = json.dumps({"name": fname, "parents": [parent]}).encode()
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                + meta + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
                + data + f"\r\n--{boundary}--\r\n".encode())
        return self._call("POST", UPLOAD, body, f"multipart/related; boundary={boundary}")["id"]

    def move_file(self, drive_id: str, remote: str) -> None:
        """Mueve y renombra un archivo ya subido a «<módulo>/<remote>» (sin subirlo de nuevo).
        Lo usa AeonScout al identificar una especie."""
        *dirs, fname = remote.split("/")
        parent = self.root_id()
        for d in dirs:
            parent = self._folder(d, parent)
        old = self._call("GET", f"{API}/{drive_id}?fields=parents").get("parents", [])
        params = {"fields": "id"}
        if parent not in old:
            params["addParents"] = parent
            if old:
                params["removeParents"] = ",".join(old)
        self._call("PATCH", f"{API}/{drive_id}?" + urllib.parse.urlencode(params),
                   json.dumps({"name": fname}).encode(), "application/json; charset=UTF-8")

    def put_file(self, path: str, remote: str) -> str:
        """Sube `path` a «PhenoRubus · …/<remote>» REEMPLAZANDO el archivo del mismo nombre si
        ya existe (p. ej. la página del cuaderno al editarla de nuevo). Devuelve su id."""
        *dirs, fname = remote.split("/")
        parent = self.root_id()
        for d in dirs:
            parent = self._folder(d, parent)
        esc = fname.replace("\\", "\\\\").replace("'", "\\'")
        found = self._call("GET", f"{API}?" + urllib.parse.urlencode(
            {"q": f"name='{esc}' and '{parent}' in parents and trashed=false",
             "fields": "files(id)", "spaces": "drive"})).get("files", [])
        with open(path, "rb") as f:
            data = f.read()
        mime = "application/pdf" if fname.lower().endswith(".pdf") else "image/jpeg"
        boundary = uuid.uuid4().hex
        meta = json.dumps({"name": fname} if found else {"name": fname, "parents": [parent]}).encode()
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                + meta + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
                + data + f"\r\n--{boundary}--\r\n".encode())
        ctype = f"multipart/related; boundary={boundary}"
        if found:
            return self._call("PATCH", UPLOAD.replace("/files?", f"/files/{found[0]['id']}?"), body, ctype)["id"]
        return self._call("POST", UPLOAD, body, ctype)["id"]

    LEGACY_TOP = ("Año ", "Temporada ", "Respaldos")

    def relocate_legacy(self) -> int:
        """Hasta la 1.1.33 todo se subía directo a la carpeta raíz. Una sola vez, lo
        existente (que es del ensayo «Nuevas variedades») pasa a su carpeta de ensayo."""
        # Su dueño es «Nuevas variedades», salvo que se haya traspasado a un predio.
        if (self.db.code != self.db.get_setting("drive_legacy_code", "NV")
                or self.db.get_setting("drive_layout_v2", False)):
            return 0
        root = self.root_id()
        q = f"'{root}' in parents and mimeType='{FOLDER_MIME}' and trashed=false"
        found = self._call("GET", f"{API}?" + urllib.parse.urlencode(
            {"q": q, "fields": "files(id,name)", "spaces": "drive", "pageSize": "200"})).get("files", [])
        moving = [f for f in found if f["name"].startswith(self.LEGACY_TOP)]
        moved = 0
        if moving:
            dest = root
            for part in self.prefix.strip("/").split("/"):
                dest = self._folder(part, dest)
            for f in moving:
                self._call("PATCH", f"{API}/{f['id']}?" + urllib.parse.urlencode(
                    {"addParents": dest, "removeParents": root, "fields": "id"}),
                    b"{}", "application/json; charset=UTF-8")
                moved += 1
            self.db.set_setting("drive_folders", {})   # las rutas en caché cambiaron
            self.db.log("move", "drive", None, f"{moved} carpetas a {self.prefix.strip('/')}")
        self.db.set_setting("drive_layout_v2", True)
        return moved

    def _find_path(self, path: str) -> str | None:
        """Id de la carpeta «PhenoRubus/<path>» en Drive, o None si no existe (no la crea)."""
        parent = self.root_id()
        for part in path.strip("/").split("/"):
            esc = part.replace("\\", "\\\\").replace("'", "\\'")
            q = (f"name='{esc}' and mimeType='{FOLDER_MIME}' and trashed=false "
                 f"and '{parent}' in parents")
            found = self._call("GET", f"{API}?" + urllib.parse.urlencode(
                {"q": q, "fields": "files(id)", "spaces": "drive"})).get("files", [])
            if not found:
                return None
            parent = found[0]["id"]
        return parent

    WEEK_DIR_RE = re.compile(r"Año \d{4}/Semana \d{2} · \d{2}-\d{2}-\d{4}")

    def _expected_name(self, r: dict) -> str | None:
        """Ruta que le corresponde HOY en Drive a un archivo de la cola que está en la carpeta
        de una semana («…/Año 2026/Semana 42 · 12-10-2026/…»): la de la semana de su registro
        y, en I+D, la subcarpeta de su variedad o parcela. None si no corresponde (lo que no
        está en una carpeta semanal no se toca)."""
        if not self.WEEK_DIR_RE.search(r["name"] or ""):
            return None
        return self._target_for(r["path"], r["photo_id"])

    def _drive_ids_by_name(self, *names: str) -> list[str]:
        """Ids de los archivos de la app en Drive con ese nombre (los haya subido este equipo
        u otro; si hay copias repetidas, todas)."""
        for n in names:
            if not n:
                continue
            esc = n.replace("\\", "\\\\").replace("'", "\\'")
            found = self._call("GET", f"{API}?" + urllib.parse.urlencode(
                {"q": f"name='{esc}' and trashed=false and mimeType!='{FOLDER_MIME}'",
                 "fields": "files(id,name)", "spaces": "drive"})).get("files", [])
            if found:
                return [f["id"] for f in found]
        return []

    def relocate_weeks(self) -> int:
        """Datos movidos a otra semana (Mover datos de semana): las fotos, adjuntas y fotos de
        mediciones YA SUBIDAS se mueven en Drive a la carpeta de su nueva semana (que se crea
        si no existe), sin subirlas de nuevo; las pendientes suben directo allá. La carpeta
        de la semana anterior, si queda vacía, va a la papelera. Corre tras mover una semana
        y una vez para lo movido antes de esta versión."""
        if hasattr(self.db, "fix_week_names"):
            self.db.fix_week_names()      # una vez: lo movido antes, con la fecha de su semana
        todo = self.db.get_setting("week_moves_drive")
        if not (todo or not self.db.get_setting("weeks_drive_checked_v2")):
            return 0
        moved, emptied = 0, set()
        # 1) Lo movido con «Mover datos de semana»: cada archivo, a la carpeta de su nueva
        #    semana y con su nombre nuevo (se busca por nombre si lo subió otro equipo).
        left = []
        for it in todo if isinstance(todo, list) else []:
            new_base = os.path.basename(it.get("path") or "")
            sub = (it.get("sub") or "").replace("/", "-").strip()
            want = self._target_for(it.get("path")) or (
                f"{self.week_path(it['dst'])}/" + (f"{sub}/" if sub else "") + new_base)
            q = self.db.query_one("SELECT * FROM drive_queue WHERE path=? ORDER BY id DESC", (it.get("path"),))
            if q and q["status"] == "pending":
                if not q["photo_id"]:
                    self.db.execute("UPDATE drive_queue SET name=? WHERE id=?", (want, q["id"]))
                continue                                # sube directo a la carpeta nueva
            fids = self._drive_ids_by_name(it.get("old"), new_base)
            if q and q["drive_id"] and q["drive_id"] not in fids:
                fids.insert(0, q["drive_id"])
            if not fids:
                continue                                # nunca se subió: nada que mover
            fid = fids[0]
            if moved == 0:
                self._set_message("Moviendo en Drive los archivos de la semana cambiada…")
            failed = False
            for one in fids:                            # también las copias repetidas
                try:
                    self.move_file(one, want)
                except DriveError as exc:
                    if exc.status not in (403, 404):
                        failed = True
            if failed:
                left.append(it)
                continue
            if q:
                self.db.execute("UPDATE drive_queue SET name=?, drive_id=? WHERE id=?", (want, fid, q["id"]))
            emptied.add(self.week_path(it["src"]))
            for sub_dir in ("Adjuntas", sub):
                if sub_dir:
                    emptied.add(f"{self.week_path(it['src'])}/{sub_dir}")
            moved += 1
        # 2) Lo que quedó en la cola con la carpeta de otra semana (también lo movido antes).
        for r in self.db.query("SELECT * FROM drive_queue WHERE status IN ('done', 'pending')"):
            want = self._expected_name(r)
            if not want or want == r["name"]:
                continue
            if r["status"] == "pending" or not r["drive_id"]:
                self.db.execute("UPDATE drive_queue SET name=? WHERE id=?", (want, r["id"]))
                continue
            if moved == 0:
                self._set_message("Moviendo en Drive los archivos de la semana cambiada…")
            try:
                self.move_file(r["drive_id"], want)
            except DriveError as exc:
                if exc.status in (403, 404):   # ya no está en Drive: se sube de nuevo allá
                    self.db.execute("UPDATE drive_queue SET status='pending', drive_id=NULL, attempts=0, "
                                    "name=? WHERE id=?", (want, r["id"]))
                    continue
                raise
            old_dir = (r["name"] or "").rpartition("/")[0]
            m = self.WEEK_DIR_RE.search(old_dir)
            if m:
                emptied.add(old_dir[:m.end()])
                emptied.add(old_dir)                    # p. ej. «…/Semana 44/Adjuntas» vacía
            if moved % 10 == 0:
                self._set_message(f"Ordenando Drive: {moved} archivo(s) movidos…")
            self.db.execute("UPDATE drive_queue SET name=? WHERE id=?", (want, r["id"]))
            moved += 1
        for folder in sorted(emptied, key=len, reverse=True):
            self._trash_if_empty(folder)
        self.db.set_setting("week_moves_drive", left or None)
        self.db.set_setting("weeks_drive_checked_v2", True)   # v2: subcarpetas por variedad/parcela (I+D)
        if moved:
            self.log(f"Drive: {moved} archivo(s) ordenados en su carpeta de semana y variedad/parcela")
        return moved

    def _lookup_names(self, names: list[str], batch: int = 40, threads: int = 4) -> list[dict]:
        """Archivos (no carpetas) de la app en Drive con esos nombres: id, name, parents. Se
        consultan de a `batch` nombres y `threads` consultas a la vez (es lo que más demora
        al ordenar un ensayo con muchas fotos)."""
        def query(part):
            esc = [n.replace("\\", "\\\\").replace("'", "\\'") for n in part]
            q = "(" + " or ".join(f"name='{n}'" for n in esc) + f") and trashed=false and mimeType!='{FOLDER_MIME}'"
            found, token = [], None
            while True:
                params = {"q": q, "fields": "nextPageToken, files(id,name,parents)", "pageSize": "1000",
                          "spaces": "drive"}
                if token:
                    params["pageToken"] = token
                res = self._call("GET", f"{API}?" + urllib.parse.urlencode(params))
                found += res.get("files", [])
                token = res.get("nextPageToken")
                if not token:
                    return found
        parts = [names[i:i + batch] for i in range(0, len(names), batch)]
        if len(parts) <= 1:
            return [f for p in parts for f in query(p)]
        self._get_token()                      # el token se pide una vez, antes de los hilos
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(threads) as ex:
            return [f for res in ex.map(query, parts) for f in res]

    def reorganize(self, force: bool = False) -> int:
        """Ordena en Drive TODAS las fotos del ensayo o predio (del registro, adjuntas y de
        mediciones), las haya subido este teléfono, otro equipo u otra app (p. ej. PhenoRubus):
        se buscan por nombre y la que no esté en su carpeta (semana y, en I+D, variedad o
        parcela) se mueve allá (nada se sube de nuevo). Las carpetas que quedan vacías van a la
        papelera. Corre al sincronizar (como mucho cada 6 h, salvo `force`)."""
        last = self.db.get_setting("layout_checked_at")
        now = time.time()
        if not force and last and now - float(last) < 6 * 3600:
            return 0
        targets: dict[str, str] = {}
        rows = [r["path"] for r in self.db.query("SELECT path FROM photos")]
        rows += [r["path"] for r in self.db.query("SELECT path FROM variety_attachments WHERE path IS NOT NULL")]
        rows += [r["path"] for r in self.db.query(
            "SELECT path FROM measure_entries WHERE path IS NOT NULL AND path != ''")]
        for path in rows:
            t = self._target_for(path)
            if t:
                targets[os.path.basename(path)] = t
        names = sorted(targets)
        dir_ids: dict[str, str] = {}

        def dir_id(path: str) -> str:
            if path not in dir_ids:
                parent = self.root_id()
                for part in path.split("/"):
                    parent = self._folder(part, parent)
                dir_ids[path] = parent
            return dir_ids[path]

        moved, vacated = 0, set()
        for f in self._lookup_names(names):
            want = targets.get(f["name"])
            if not want:
                continue
            folder = dir_id(want.rpartition("/")[0])
            parents = f.get("parents") or []
            if folder in parents:
                continue
            if moved == 0:
                self._set_message("Ordenando Drive…")
            params = {"fields": "id", "addParents": folder}
            if parents:
                params["removeParents"] = ",".join(parents)
            try:
                self._call("PATCH", f"{API}/{f['id']}?" + urllib.parse.urlencode(params), b"{}",
                           "application/json; charset=UTF-8")
            except DriveError as exc:      # uno que falle no frena el resto
                if exc.status not in (403, 404):
                    self.log(f"Drive: no se pudo mover {f['name']}: {exc}", error=True)
                continue
            vacated.update(parents)
            moved += 1
            if moved % 20 == 0:
                self._set_message(f"Ordenando Drive: {moved} archivo(s) movidos…")
        for fid in vacated:
            self._trash_folder_if_empty(fid)
        self.db.set_setting("layout_checked_at", now)
        if moved:
            self.log(f"Drive: {moved} archivo(s) ordenados en su carpeta (semana y variedad/parcela)")
        return moved

    def clean_empty_folders(self) -> int:
        """Orden completo (ver tidy); devuelve cuántas carpetas vacías fueron a la papelera."""
        return self.tidy()["folders"]

    def _kids(self, fid: str) -> list[dict]:
        out, token = [], None
        while True:
            params = {"q": f"'{fid}' in parents and trashed=false", "pageSize": "1000",
                      "fields": "nextPageToken, files(id,name,mimeType,createdTime,size)"}
            if token:
                params["pageToken"] = token
            res = self._call("GET", f"{API}?" + urllib.parse.urlencode(params))
            out += res.get("files", [])
            token = res.get("nextPageToken")
            if not token:
                return out

    def tidy(self) -> dict:
        """Orden completo de la carpeta del ensayo o predio en Drive (al sincronizar):

        1. Carpetas repetidas con el mismo nombre (dos «Respaldos», dos «Semana 37…»): se
           juntan en la más antigua.
        2. Fotos cuyo registro se movió de semana y que en Drive conservan la fecha vieja en
           el nombre (20261102-NV-C31G.jpg, y en el teléfono ya es 20261026-NV-C31G.jpg): se
           reconocen por el resto del nombre y se renombran y mueven a su semana y variedad.
        3. Copias exactas (mismo nombre y tamaño en la misma carpeta): queda una; las demás
           a la papelera (recuperables 30 días).
        4. Carpetas vacías: a la papelera (la del ensayo no se toca).
        """
        stats = {"merged": 0, "renamed": 0, "moved": 0, "dupes": 0, "folders": 0}
        prefix = self.prefix.strip("/")
        top = self._find_path(prefix) if prefix else None
        if not top:
            return stats
        local: dict[str, str] = {}
        rows = [r["path"] for r in self.db.query("SELECT path FROM photos")]
        rows += [r["path"] for r in self.db.query("SELECT path FROM variety_attachments WHERE path IS NOT NULL")]
        rows += [r["path"] for r in self.db.query(
            "SELECT path FROM measure_entries WHERE path IS NOT NULL AND path != ''")]
        pending = {r["path"] for r in self.db.query("SELECT path FROM drive_queue WHERE status='pending'")}
        by_suffix: dict[str, list] = {}
        for path in rows:
            t = self._target_for(path)
            if not t:
                continue
            name = os.path.basename(path)
            local[name] = t
            m = re.match(r"(\d{8})(\D.*)$", name)
            if m and path not in pending:
                by_suffix.setdefault(m[2], []).append((m[1], name))
        files: list[dict] = []

        def walk(fid: str) -> None:
            kids = self._kids(fid)
            groups: dict[str, list] = {}
            for k in kids:
                if k.get("mimeType") == FOLDER_MIME:
                    groups.setdefault(k["name"], []).append(k)
            merged = False
            for same in groups.values():
                if len(same) > 1:
                    same.sort(key=lambda k: k.get("createdTime") or "")
                    for dup in same[1:]:
                        try:
                            self._merge_folder(dup["id"], same[0]["id"])
                        except DriveError as exc:
                            self.log(f"Drive: no se pudo juntar «{dup['name']}»: {exc}", error=True)
                            continue
                        stats["merged"] += 1
                        merged = True
            if merged:
                kids = self._kids(fid)
            for k in kids:
                if k.get("mimeType") == FOLDER_MIME:
                    walk(k["id"])
                else:
                    files.append(dict(k, parent=fid))

        walk(top)
        present = {f["name"] for f in files}
        sizes: dict[str, set] = {}
        for f in files:
            sizes.setdefault(f["name"], set()).add(f.get("size"))
        dir_ids: dict[str, str] = {}

        def dir_id(path: str) -> str:
            if path not in dir_ids:
                parent = self.root_id()
                for part in path.split("/"):
                    parent = self._folder(part, parent)
                dir_ids[path] = parent
            return dir_ids[path]

        renamed_from: dict[tuple, bool] = {}
        stale: list[dict] = []
        for f in files:
            name, want = f["name"], local.get(f["name"])
            if not want:
                m = re.match(r"(\d{8})(\D.*)$", name)
                near = []
                for d, n in (by_suffix.get(m[2], []) if m else []):
                    try:
                        gap = abs((_dt.datetime.strptime(d, "%Y%m%d").date()
                                   - _dt.datetime.strptime(m[1], "%Y%m%d").date()).days)
                    except ValueError:
                        continue
                    if gap <= 14:
                        near.append((gap, d, n))
                # Ya está en Drive con su nombre nuevo y el mismo tamaño: esta es la copia vieja
                # (p. ej. la subió la otra app antes de mover la semana).
                if f.get("size") and any(f.get("size") in sizes.get(n, ()) for _, _, n in near):
                    stale.append(f)
                    continue
                cands = [(d, n) for _, d, n in near if n not in present]
                if cands:
                    try:
                        day = _dt.datetime.strptime(m[1], "%Y%m%d").date()
                        best = min(cands, key=lambda c: abs((_dt.datetime.strptime(c[0], "%Y%m%d").date()
                                                             - day).days))
                        if abs((_dt.datetime.strptime(best[0], "%Y%m%d").date() - day).days) <= 14:
                            name, want = best[1], local[best[1]]
                    except ValueError:
                        pass
            if not want:
                continue
            folder = dir_id(want.rpartition("/")[0])
            params, body = {"fields": "id"}, {}
            if folder != f["parent"]:
                params.update(addParents=folder, removeParents=f["parent"])
            if name != f["name"]:
                body["name"] = name
            if len(params) == 1 and not body:
                continue
            try:
                self._call("PATCH", f"{API}/{f['id']}?" + urllib.parse.urlencode(params),
                           json.dumps(body).encode(), "application/json; charset=UTF-8")
            except DriveError as exc:      # uno que falle no frena el resto del orden
                self.log(f"Drive: no se pudo ordenar {f['name']}: {exc}", error=True)
                continue
            if name != f["name"]:
                stats["renamed"] += 1
                present.add(name)
                renamed_from[(f["name"], f.get("size"))] = True
            stats["moved"] += folder != f["parent"]
            f["name"], f["parent"] = name, folder
        def trash(fid: str) -> bool:
            try:
                self._call("PATCH", f"{API}/{fid}?fields=id", json.dumps({"trashed": True}).encode(),
                           "application/json; charset=UTF-8")
                return True
            except DriveError as exc:
                self.log(f"Drive: no se pudo mandar a la papelera: {exc}", error=True)
                return False

        seen: dict[tuple, str] = {}
        for f in stale:
            stats["dupes"] += trash(f["id"])
        stale_ids = {f["id"] for f in stale}
        for f in sorted(files, key=lambda f: f.get("createdTime") or ""):
            if f["id"] in stale_ids:
                continue
            key = (f["parent"], f["name"], f.get("size"))
            # Copia exacta en la misma carpeta, o copia (mismo nombre viejo y tamaño) de una
            # foto que ya se renombró y movió a su semana.
            if f.get("size") and (key in seen or (f["name"], f.get("size")) in renamed_from):
                stats["dupes"] += trash(f["id"])
            else:
                seen[key] = f["id"]

        def empty(fid: str) -> bool:
            left = 0
            for k in self._kids(fid):
                if k.get("mimeType") == FOLDER_MIME and empty(k["id"]):
                    continue
                left += 1
            if left or fid == top:
                return False
            if trash(fid):
                stats["folders"] += 1
                return True
            return False

        empty(top)
        self.db.set_setting("layout_tidied_at", time.time())
        if any(stats.values()):
            self.db.set_setting("drive_folders", {})      # rutas en caché
            self.log("Drive ordenado: " + ", ".join(f"{k} {v}" for k, v in stats.items() if v))
        return stats

    def _trash_folder_if_empty(self, fid: str, depth: int = 0) -> None:
        """La carpeta (por id) a la papelera si quedó vacía, y luego su carpeta de arriba si
        también quedó vacía (hasta la de la semana: «Año …» y el ensayo no se tocan)."""
        try:
            meta = self._call("GET", f"{API}/{fid}?fields=id,name,parents,mimeType")
            if meta.get("mimeType") not in (None, FOLDER_MIME):
                return
            name = meta.get("name") or ""
            if name.startswith("Año ") or depth > 3:
                return
            kids = self._call("GET", f"{API}?" + urllib.parse.urlencode(
                {"q": f"'{fid}' in parents and trashed=false", "fields": "files(id)", "pageSize": "5"})
                ).get("files", [])
            if kids:
                return
            self._call("PATCH", f"{API}/{fid}?fields=id", json.dumps({"trashed": True}).encode(),
                       "application/json; charset=UTF-8")
            self.db.set_setting("drive_folders", {})
            if not self.WEEK_DIR_RE.search(f"Año 2000/{name}"):     # no era la semana: ver la de arriba
                for p in meta.get("parents") or []:
                    self._trash_folder_if_empty(p, depth + 1)
        except (DriveError, KeyError, ValueError):
            pass

    def _trash_if_empty(self, path: str) -> None:
        """La carpeta «<módulo>/<path>» a la papelera si quedó vacía (también sus subcarpetas
        vacías, como «Adjuntas»)."""
        try:
            fid = self._find_path(path)
            if not fid:
                return

            def empty(folder_id) -> bool:
                kids = self._call("GET", f"{API}?" + urllib.parse.urlencode(
                    {"q": f"'{folder_id}' in parents and trashed=false",
                     "fields": "files(id,mimeType)", "pageSize": "50"})).get("files", [])
                return all(k.get("mimeType") == FOLDER_MIME and empty(k["id"]) for k in kids)

            if empty(fid):
                self._call("PATCH", f"{API}/{fid}?fields=id", json.dumps({"trashed": True}).encode(),
                           "application/json; charset=UTF-8")
                self.db.set_setting("drive_folders", {})   # rutas en caché
        except (DriveError, KeyError, ValueError):
            pass

    def relocate_moved(self) -> int:
        """Ensayo traspasado a un predio (Workspaces.move_to_predio): en Drive, el contenido
        de «I+D/Nuevas variedades» pasa a «Predio/El Amanecer» y las fotos ya subidas toman
        el código nuevo (…-NV-… -> …-AM-…). Nada se vuelve a subir."""
        mv = self.db.get_setting("ws_move_pending")
        if not mv:
            return 0
        from photo_rename import recode_name
        self._set_message("Ordenando Drive tras el traspaso…")
        src = self._find_path(mv["from"])
        moved = 0
        if src:
            dest = self.root_id()
            for part in mv["to"].strip("/").split("/"):
                dest = self._folder(part, dest)
            q = f"'{src}' in parents and trashed=false"
            children = self._call("GET", f"{API}?" + urllib.parse.urlencode(
                {"q": q, "fields": "files(id,name)", "spaces": "drive", "pageSize": "500"})).get("files", [])
            for f in children:
                self._call("PATCH", f"{API}/{f['id']}?" + urllib.parse.urlencode(
                    {"addParents": dest, "removeParents": src, "fields": "id"}),
                    b"{}", "application/json; charset=UTF-8")
                moved += 1
            self.db.set_setting("drive_folders", {})   # las rutas en caché cambiaron
        rows = self.db.query("SELECT id, name, drive_id FROM drive_queue "
                             "WHERE status='done' AND drive_id IS NOT NULL")
        done = 0
        for i, r in enumerate(rows, 1):
            name = r["name"] or ""
            if name.startswith(mv["from"] + "/"):
                name = mv["to"] + name[len(mv["from"]):]
            head, _, base = name.rpartition("/")
            nn = recode_name(base, mv["old"], mv["new"])
            if nn:
                if i % 10 == 0:
                    self._set_message(f"Renombrando en Drive {i} de {len(rows)}…")
                try:
                    self._call("PATCH", f"{API}/{r['drive_id']}?fields=id",
                               json.dumps({"name": nn}).encode(), "application/json; charset=UTF-8")
                    done += 1
                except DriveError as exc:
                    if exc.status not in (403, 404):   # 404: ya no está; 403: no es de la app
                        raise
                name = f"{head}/{nn}" if head else nn
            if name != r["name"]:
                self.db.execute("UPDATE drive_queue SET name=? WHERE id=?", (name, r["id"]))
        self.db.set_setting("ws_move_pending", None)
        self.db.log("move", "drive", None,
                    f"{mv['from']} -> {mv['to']}: {moved} carpetas, {done} fotos renombradas")
        return moved + done

    def rename_legacy(self) -> int:
        """Fotos ya subidas con el nombre antiguo «ddmmaaaa-…»: se renombran en Drive a
        «aaaammdd-…» (la app solo puede tocar los archivos que ella misma subió)."""
        from photo_rename import known_codes, new_name
        known = known_codes(self.db)
        done = 0
        todo = []
        for r in self.db.query("SELECT id, name, drive_id FROM drive_queue "
                               "WHERE status='done' AND drive_id IS NOT NULL"):
            head, _, base = (r["name"] or "").rpartition("/")
            nn = new_name(base, self.db.code, known)
            if nn:
                todo.append((r, head, nn))
        if todo:
            self.log(f"Renombrando {len(todo)} fotos ya subidas (aaaammdd-{self.db.code or ''}…)")
        for i, (r, head, nn) in enumerate(todo, 1):
            if i % 10 == 0:
                self._set_message(f"Renombrando en Drive {i} de {len(todo)}…")
            try:
                self._call("PATCH", f"{API}/{r['drive_id']}?fields=id",
                           json.dumps({"name": nn}).encode(), "application/json; charset=UTF-8")
                done += 1
            except DriveError as exc:
                if exc.status not in (403, 404):   # 404: ya no está en Drive; 403: no es de la app
                    raise
            self.db.execute("UPDATE drive_queue SET name=? WHERE id=?",
                            (f"{head}/{nn}" if head else nn, r["id"]))
        if done:
            self.db.log("rename", "drive", None, f"{done} fotos renombradas en Drive (aaaammdd)")
        return done

    # --------------------------------------------------------------- envío
    def flush_async(self) -> None:
        if self.enabled:
            threading.Thread(target=self._flush_thread, daemon=True).start()

    def _flush_thread(self) -> None:
        try:
            self.flush()
        finally:
            _detach()

    def _upload_many(self, jobs: list) -> list:
        """[(fila, id en Drive o la excepción)] de los trabajos (fila, carpeta, nombre); los
        envíos van en paralelo (UPLOAD_THREADS a la vez)."""
        def one(job):
            r, parent, fname = job
            if isinstance(parent, Exception):
                return r, parent
            try:
                return r, self._post_file(r["path"], fname, parent)
            except (DriveError, Offline, NeedsConsent, OSError) as exc:
                return r, exc
        if len(jobs) <= 1:
            return [one(j) for j in jobs]
        self._get_token()                      # el token se pide una vez, antes de los hilos
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(UPLOAD_THREADS) as ex:
            return list(ex.map(one, jobs))

    def flush(self) -> int:
        """Sube lo pendiente. Devuelve cuántas fotos se subieron."""
        if not self.enabled:
            return 0
        if not self._flush_lock.acquire(blocking=False):
            self._again = True  # hay otro envío en curso: que repase la cola al terminar
            return 0
        uploaded = failed = 0
        self.running = True
        try:
            # Datos movidos a otra semana: sus archivos se mueven y renombran en Drive. Va
            # antes del «solo Wi-Fi»: no se sube nada, solo cambian carpeta y nombre.
            self.relocate_weeks()
            if self.wifi_only and self.metered():
                raise Offline("Esperando Wi-Fi (datos móviles desactivados para el respaldo)")
            self._sync_account_queue()
            self._skip_missing()
            # Primero mover lo de versiones anteriores (rápido: unas pocas carpetas)…
            self.relocate_legacy()  # lo subido antes de los ensayos -> «I+D/Nuevas variedades»
            self.relocate_moved()   # ensayo traspasado a un predio: carpeta y nombres en Drive
            while True:
                self._again = False
                if self.wifi_only and self.metered():
                    raise Offline("Esperando Wi-Fi (datos móviles desactivados para el respaldo)")
                rows = self.db.query("SELECT * FROM drive_queue WHERE status='pending' ORDER BY id")
                if not rows:
                    break
                # De a UPLOAD_THREADS fotos a la vez: carpetas y nombres se calculan antes (base
                # de datos, en este hilo) y solo el envío corre en paralelo.
                step = UPLOAD_THREADS * 2
                for start in range(0, len(rows), step):
                    chunk, jobs = rows[start:start + step], []
                    i = start + 1
                    self._set_message(f"Subiendo {i} de {len(rows)}…")
                    cb = getattr(self, "progress_cb", None)
                    if cb:
                        cb(start / len(rows), f"Subiendo {i} de {len(rows)}")
                    for r in chunk:
                        if not os.path.exists(r["path"]):
                            # Foto borrada o reemplazada en la app: no hay nada que subir.
                            self.db.execute("UPDATE drive_queue SET status='skipped', error=? WHERE id=?",
                                            ("El archivo ya no existe en el teléfono", r["id"]))
                            self.log(f"Omitida (ya no está en el teléfono): {os.path.basename(r['path'])}")
                            continue
                        try:
                            # Fotos: la carpeta se calcula al subir (semana actual del registro,
                            # también para lo que quedó en cola con el esquema anterior).
                            name = (self._remote_name(r["photo_id"], r["path"]) if r["photo_id"]
                                    else r["name"])
                            jobs.append((r, *self._parent_of(name)))
                        except (Offline, NeedsConsent):
                            raise
                        except DriveError as exc:
                            jobs.append((r, exc, None))
                    for r, res in self._upload_many(jobs):
                        if isinstance(res, (Offline, NeedsConsent)):
                            raise res
                        if isinstance(res, Exception):
                            failed += 1
                            if failed <= 3:   # en el diagnóstico, sin llenarlo
                                self.log(f"{os.path.basename(r['path'])}: {explain(str(res))[:140]}", error=True)
                            if isinstance(res, DriveError) and res.status == 404:
                                self.db.set_setting("drive_folders", {})   # carpeta borrada en Drive
                            attempts = r["attempts"] + 1
                            self.db.execute(
                                "UPDATE drive_queue SET attempts=?, error=?, status=? WHERE id=?",
                                (attempts, str(res), "error" if attempts >= MAX_ATTEMPTS else "pending",
                                 r["id"]))
                            continue
                        self.db.execute("UPDATE drive_queue SET status='done', drive_id=?, error='', "
                                        "uploaded_at=? WHERE id=?", (res, _now(), r["id"]))
                        uploaded += 1
                if not self._again:
                    left = self.db.query_one(
                        "SELECT COUNT(*) AS n FROM drive_queue WHERE status='pending' AND attempts=0")
                    if not left["n"]:
                        break
            if uploaded:
                self.log(f"{uploaded} archivo(s) subidos")
            # …y al final renombrar lo ya subido con el nombre antiguo (puede ser lento: no debe
            # retrasar las fotos nuevas).
            self.rename_legacy()   # nombres antiguos ya subidos -> aaaammdd-NV-… (una sola vez)
            pending = self.status()["pending"]
            message, synced = ("Todo respaldado" if not pending else f"{pending} en espera"), True
        except Offline as exc:
            message, synced = ("Esperando Wi-Fi" if "Wi-Fi" in str(exc)
                               else "Sin conexión: se subirá al volver la red"), False
        except NeedsConsent as exc:
            message, synced = explain(str(exc)), False
        except Exception as exc:  # noqa: BLE001
            message, synced = f"Error: {explain(str(exc))[:160]}", False
        finally:
            self.running = False
            self._flush_lock.release()
        if synced:
            self._set_message(message, synced=True)
        else:
            self.log(message, error=not message.startswith(("Esperando", "Sin conexión")))
        return uploaded
