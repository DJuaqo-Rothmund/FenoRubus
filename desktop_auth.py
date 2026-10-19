"""
desktop_auth.py
===============
Inicio de sesión con Google en el PC (Windows), para el respaldo y la sincronización.

* Flujo para apps de escritorio: se abre el navegador, el usuario elige su cuenta y
  acepta; Google vuelve a la app por http://127.0.0.1:<puerto> (PKCE).
* Se guarda el «refresh token» en los ajustes comunes: las veces siguientes se pide el
  acceso sin abrir el navegador. (Con la app de Google Cloud en estado «Prueba», Google lo
  invalida a los 7 días: entonces la app pide conectar de nuevo.)
* La credencial (ID y secreto del cliente «App de escritorio») NO está en el código
  público: la escribe la compilación de Windows en google_client.py desde los secretos de
  GitHub. También se puede dar por variables de entorno o google_client.json en la carpeta
  de datos (pruebas).
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import urllib.parse
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/drive.file openid email"
LOGIN_TIMEOUT = 300


def client_config(data_dir: str | None = None) -> tuple[str, str] | None:
    """(id, secreto) del cliente de escritorio, o None si esta copia no lo trae."""
    try:
        import google_client  # type: ignore  # generado por la compilación de Windows
        if google_client.CLIENT_ID:
            return google_client.CLIENT_ID, google_client.CLIENT_SECRET
    except ImportError:
        pass
    cid, sec = os.environ.get("GOOGLE_DESKTOP_CLIENT_ID"), os.environ.get("GOOGLE_DESKTOP_CLIENT_SECRET")
    if cid and sec:
        return cid, sec
    if data_dir:
        path = os.path.join(data_dir, "google_client.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            raw = raw.get("installed", raw)
            return raw["client_id"], raw["client_secret"]
    return None


def _email_from_id_token(token: str | None) -> str | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except Exception:  # noqa: BLE001
        return None


class DesktopAuthorizer:
    def __init__(self, settings, transport, client: tuple[str, str], log=None,
                 open_browser=webbrowser.open):
        self.settings = settings          # base común (ajustes «drive_…» del equipo)
        self.transport = transport
        self.client_id, self.client_secret = client
        self.log = log or (lambda *a, **k: None)
        self.open_browser = open_browser
        self.account = settings.get_setting("drive_account") or None

    # ------------------------------------------------------------ token
    def get_token(self, interactive: bool, timeout: float | None = None) -> str:
        from drive_backup import NeedsConsent
        refresh = self.settings.get_setting("drive_refresh_token")
        if refresh:
            status, data = self._post({"grant_type": "refresh_token", "refresh_token": refresh})
            if status == 200:
                return json.loads(data)["access_token"]
            if status in (400, 401):      # vencido o revocado: hay que iniciar sesión de nuevo
                self.settings.set_setting("drive_refresh_token", None)
            else:
                raise NeedsConsent(f"Google respondió {status} al renovar el acceso")
        if not interactive:
            raise NeedsConsent("Inicie sesión con Google (Ajustes › Conectar Google Drive)")
        return self._browser_login(timeout or LOGIN_TIMEOUT)

    def forget(self) -> None:
        self.settings.set_setting("drive_refresh_token", None)

    def _post(self, fields: dict) -> tuple[int, bytes]:
        body = urllib.parse.urlencode({"client_id": self.client_id,
                                       "client_secret": self.client_secret, **fields}).encode()
        return self.transport("POST", TOKEN_URL,
                              {"Content-Type": "application/x-www-form-urlencoded"}, body)

    # ------------------------------------------------------------ navegador
    def _browser_login(self, timeout: float) -> str:
        from drive_backup import DriveError
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        result: dict = {}
        done = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                if "code" not in q and "error" not in q:
                    self.send_response(404)
                    self.end_headers()
                    return
                result.update({k: v[0] for k, v in q.items()})
                ok = "code" in q and q.get("state", [""])[0] == state
                page = ("<h2>PhenoRubus quedó conectado a Google Drive.</h2><p>Ya puede cerrar esta "
                        "pestaña y volver a la app.</p>" if ok else
                        "<h2>No se completó la conexión.</h2><p>Vuelva a la app e inténtelo de nuevo.</p>")
                body = f"<html><meta charset='utf-8'><body style='font-family:sans-serif'>{page}</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
                done.set()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        redirect = f"http://127.0.0.1:{server.server_port}"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = AUTH_URL + "?" + urllib.parse.urlencode({
                "client_id": self.client_id, "redirect_uri": redirect, "response_type": "code",
                "scope": SCOPES, "code_challenge": challenge, "code_challenge_method": "S256",
                "state": state, "access_type": "offline", "prompt": "consent select_account"})
            self.log("Se abrió el navegador: elija su cuenta de Google y acepte")
            self.open_browser(url)
            if not done.wait(timeout):
                raise DriveError("No se completó el inicio de sesión en el navegador (tiempo agotado)")
        finally:
            server.shutdown()
            server.server_close()
        if result.get("state") != state or "code" not in result:
            raise DriveError(f"Google no autorizó la conexión ({result.get('error', 'sin respuesta')})")
        status, data = self._post({"grant_type": "authorization_code", "code": result["code"],
                                   "redirect_uri": redirect, "code_verifier": verifier})
        if status != 200:
            raise DriveError(f"Google rechazó el código ({status}): {data[:200].decode('utf-8', 'replace')}")
        tok = json.loads(data)
        if tok.get("refresh_token"):
            self.settings.set_setting("drive_refresh_token", tok["refresh_token"])
        email = _email_from_id_token(tok.get("id_token"))
        if email:
            self.account = email
            self.settings.set_setting("drive_account", email)
        return tok["access_token"]
