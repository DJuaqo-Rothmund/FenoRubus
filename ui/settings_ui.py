"""
ui/settings_ui.py
=================
Ajustes del ensayo.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
import os
from kivy.clock import Clock
from kivymd.uix.button import MDRectangleFlatButton
from kivymd.uix.screen import MDScreen
import phenology as ph
from android_bridge import request_runtime_permissions
from notifications import FREQUENCIES, can_schedule_exact, request_exact_alarm_permission
from platform_utils import IS_ANDROID, app_version
from ui import theme
from ui.theme import c
from ui.common import (_crop, app, confirm, fast_clear, list_dialog, pick_dialog, show_error_log,
    text_dialog)


# ===========================================================================
# Ajustes
# ===========================================================================
class SettingsTab(MDScreen):
    _loading = False

    def _card(self, key: str, show: bool) -> None:
        """Tarjetas propias de cada cultivo: fuera cuando Ajustes se abre desde la pantalla
        principal de AeonCrop (ahí solo lo general; la app rehace Ajustes al cambiar de lugar)."""
        w = self.ids[key]
        if not show and w.parent is not None:
            w.parent.remove_widget(w)

    def refresh(self):
        a = app()
        home = getattr(a, "_settings_return", None) == "crops"
        for key in ("card_reminder", "card_season", "card_data"):
            self._card(key, not home)
        name, desc = theme.STYLES[theme.style]
        self.ids.style_text.text = f"[b]{name}[/b] · {desc}"
        self.ids.style_text.markup = True
        cfg = a.reminders.config()
        self._loading = True
        self.ids.enabled.active = cfg.enabled
        self._loading = False
        self.ids.day_btn.text = ph.DIAS[cfg.weekday].capitalize()
        self.ids.time_btn.text = f"{cfg.hour:02d}:{cfg.minute:02d}"
        self.ids.freq_btn.text = FREQUENCIES.get(cfg.every_weeks, f"Cada {cfg.every_weeks} semanas")
        nxt = a.reminders.next_time()
        self.ids.next_text.text = (f"Próximo aviso: {ph.DIAS[nxt.weekday()]} "
                                   f"{ph.format_date_es(nxt.date())}, {nxt:%H:%M}"
                                   if nxt else "Recordatorios desactivados.")
        box = self.ids.exact_box
        fast_clear(box)
        if IS_ANDROID and cfg.enabled and not can_schedule_exact():
            box.add_widget(MDRectangleFlatButton(
                text="Permitir alarmas exactas", theme_text_color="Custom",
                text_color=c(theme.WARN), line_color=c(theme.WARN),
                on_release=lambda *_: request_exact_alarm_permission()))
        self.ids.season_text.text = (f"{ph.season_title(a.season)} · semana en curso: "
                                     f"{ph.week_title(a.week)} ({a.week['label']})")
        self.ids.first_week_text.text = self._first_week_text(a)
        n = sum(a.db.reference_counts().values())
        # Sin instanciar el clasificador (evita cargar numpy solo por abrir Ajustes).
        ext = a.__dict__.get("classifier")
        engine = f"Extractor: {ext.extractor.name} · " if ext else ""
        self.ids.ai_text.text = (f"{engine}{n} fotos de referencia. "
                                 "Todo el análisis se ejecuta en el teléfono, sin conexión.")
        self.ids.data_text.text = f"{_crop().app} versión {app_version()} · datos locales: {a.db.path}"
        self.refresh_drive()
        self.refresh_sync()

    # ------------------------------------------------ respaldo en Google Drive
    def refresh_drive(self, st=None):
        a = app()
        drive = a.drive
        if not getattr(self, "_drive_hooked", False):
            self._drive_hooked = True
            drive.listeners.append(lambda status: Clock.schedule_once(
                lambda *_: self.refresh_drive(status)))
        st = st or drive.status()
        on = st["enabled"]
        total = st["pending"] + st["done"] + st["errors"]
        if not st["available"]:
            title, icon, col = ("Disponible en el teléfono" if IS_ANDROID else "Requiere la versión instalada"), "cloud-off-outline", theme.MUTED
        elif not on:
            title, icon, col = "Sin conectar", "cloud-off-outline", theme.MUTED
        elif st["running"]:
            title, icon, col = "Subiendo fotos…", "cloud-sync-outline", theme.LEAF
        elif st["errors"] and not st["pending"]:
            title, icon, col = "Con errores", "cloud-alert-outline", theme.WARN
        elif st["pending"]:
            title, icon, col = f"{st['pending']} foto(s) en espera", "cloud-clock-outline", theme.WARN
        else:
            title, icon, col = "Todo respaldado", "cloud-check-outline", theme.LEAF
        self.ids.drive_title.text = title
        self.ids.drive_icon.icon = icon
        self.ids.drive_icon.text_color = c(col)
        parts = []
        if on:
            parts.append(f"{st['done']} de {total} fotos en Drive" if total else "Aún no hay fotos en la cola")
            if st["errors"]:
                parts.append(f"{st['errors']} con error")
            if st["last_sync"]:
                parts.append("última sincronización " + st["last_sync"][5:16].replace("T", " "))
        if st["message"] and (on or not st["available"]):
            parts.append(st["message"])
        if on and st.get("account"):
            parts.insert(0, st["account"])
        self.ids.drive_text.text = " · ".join(parts)
        self.ids.drive_bar.value = 100 * st["done"] / total if on and total else 0
        self.ids.drive_bar_box.opacity = 1 if on and total else 0
        self.ids.drive_connect.text = ("Cambiar de cuenta" if on else "Conectar Google Drive")
        # Referencia FUERTE: al quitar el bloque del árbol, `ids` (referencia débil) lo
        # perdería y el recolector lo borraría → ReferenceError al volver a «General».
        if not hasattr(self, "_drive_slot"):
            opts = self.ids.drive_opts.__self__   # objeto real, no el proxy débil de `ids`
            self._drive_opts = opts
            self._drive_slot = (opts.parent, opts.parent.children.index(opts))
        opts = self._drive_opts
        parent, index = self._drive_slot
        if on and opts.parent is None:
            parent.add_widget(opts, index=index)
        elif not on and opts.parent is not None:
            parent.remove_widget(opts)
        self._loading = True
        self.ids.drive_wifi.active = st["wifi_only"]
        self._loading = False

    def drive_connect(self):
        a = app()
        if not a.drive.available:
            a.toast("Esta copia de la app no trae la credencial de Google (use la versión instalada).")
            return
        a.toast("Elija la cuenta de Google y acepte el permiso" if IS_ANDROID else
                "Se abrirá el navegador: elija su cuenta de Google y acepte el permiso")

        def done(ok, msg):
            Clock.schedule_once(lambda *_: (a.toast(msg), self.refresh_drive()))

        a.drive.connect(done)

    def drive_diagnostics(self):
        from platform_utils import app_version
        lines = app().drive.diagnostics()
        from android_bridge import package_name
        head = f"PhenoRubus {app_version()} · paquete {package_name()}"
        text_dialog("Diagnóstico de Google Drive",
                    [head] + (lines or ["Sin registros: toque «Conectar Google Drive» y vuelva aquí."]),
                    highlight="✗")

    def show_errors(self):
        show_error_log()

    def drive_disconnect(self):
        confirm("Desconectar Google Drive",
                "Las fotos dejarán de subirse y se quita el permiso de la app en esa cuenta. Lo que ya "
                "está en Drive y en el teléfono se conserva. Para usar otra cuenta, toque después "
                "«Conectar Google Drive» y elíjala de la lista.",
                [("Desconectar", lambda: (app().drive.disconnect(), self.refresh_drive()))])

    def drive_wifi(self, active: bool):
        if not self._loading:
            app().db.set_setting("drive_wifi_only", bool(active))
            if not active:
                app().drive.flush_async()

    def drive_sync(self):
        a = app()
        a.drive.retry_errors()
        a.toast("Sincronizando con Google Drive…")
        a.run_sync(manual=True)

    def refresh_sync(self):
        last = app().workspaces.shared.get_setting("sync_last")
        self.ids.sync_text.text = (f"Última sincronización (celular, PC y web): {last}" if last else
                                   "Los registros y fotos se comparten con el PC, la web y otros "
                                   "teléfonos con esta misma cuenta de Google (al abrir y cada 10 "
                                   "minutos; también desde el ícono de Drive del inicio).")

    def drive_existing(self):
        a = app()

        def work():
            n = a.drive.enqueue_existing()
            Clock.schedule_once(lambda *_: (a.toast(f"{n} foto(s) añadidas a la cola de respaldo"
                                                    if n else "No hay fotos anteriores pendientes"),
                                            a.backup_now(),       # insignia de avance del respaldo
                                            self.refresh_drive()))

        a.workers.submit(work)

    def _save(self, **changes):
        a = app()
        cfg = a.reminders.config()
        for k, v in changes.items():
            setattr(cfg, k, v)
        a.reminders.save(cfg)
        self.refresh()

    def on_toggle(self, active: bool):
        if not self._loading:
            self._save(enabled=active)

    def pick_day(self, caller):
        pick_dialog("Día del recordatorio", [(d.capitalize(), "", lambda i=i: self._save(weekday=i))
                                             for i, d in enumerate(ph.DIAS)])

    def pick_freq(self, caller):
        pick_dialog("Frecuencia", [(t, "", lambda k=k: self._save(every_weeks=k))
                                   for k, t in FREQUENCIES.items()])

    def pick_time(self):
        cfg = app().reminders.config()
        from kivymd.uix.pickers import MDTimePicker  # import diferido (pesado)
        picker = MDTimePicker(primary_color=c(theme.LEAF), accent_color=c(theme.GLASS),
                              text_button_color=c(theme.LEAF_DARK))
        picker.set_time(_dt.time(cfg.hour, cfg.minute))
        picker.bind(on_save=lambda inst, t: self._save(hour=t.hour, minute=t.minute))
        picker.open()

    @staticmethod
    def _first_week_text(a) -> str:
        fixed = a.db.first_week_date(a.season)
        if fixed:
            return f"Primera semana de muestreo: {ph.format_date_es(fixed)} (fijada)"
        n = a.db.first_week_with_data(a.season)
        if n is None:
            return "Primera semana de muestreo: automática (aún sin datos)"
        start = ph.week_start(a.db.season_start(a.season), n)
        return f"Primera semana de muestreo: automática ({ph.week_title(start.isoformat())})"

    def pick_start(self):
        """Fija desde qué semana parten matriz e informes (no cambia ningún registro)."""
        a = app()
        start = a.db.first_week_date(a.season) or _dt.date.fromisoformat(a.week["start_date"])
        from kivymd.uix.pickers import MDDatePicker  # import diferido (pesado)
        picker = MDDatePicker(year=start.year, month=start.month, day=start.day,
                              primary_color=c(theme.LEAF), selector_color=c(theme.LEAF),
                              text_button_color=c(theme.LEAF_DARK))
        picker.bind(on_save=lambda inst, value, _range: self._set_first_week(value))
        picker.open()

    def reset_start(self):
        a = app()
        a.db.set_first_week(a.season, None)
        self.refresh()
        a.toast("Primera semana de muestreo: automática (la primera con datos)")

    def _set_first_week(self, value: _dt.date):
        a = app()
        season = ph.season_of(value)
        if season != a.season:
            a.toast(f"Esa fecha es de la {ph.season_title(season)}; elija una de la "
                    f"{ph.season_title(a.season)}.")
            return
        week = a.db.week_for_date(value, season)
        a.db.set_first_week(season, _dt.date.fromisoformat(week["start_date"]))
        self.refresh()
        a.toast(f"Matriz e informes parten en la {ph.week_title(week)}")

    def show_audit(self):
        rows = [(f"{r['action']} · {r['entity']}" + (f" #{r['entity_id']}" if r["entity_id"] else ""),
                 f"{r['ts'].replace('T', ' ')} · {r['detail'][:80]}")
                for r in app().db.audit_trail(60)]
        list_dialog("Bitácora de cambios", rows)

    # ---------------------------------------------- copias de seguridad
    def _busy(self, text):
        self.ids.backup_text.text = text

    def optimize_photos(self):
        """Aligera las fotos antiguas (mismo archivo y ruta) en segundo plano."""
        if getattr(self, "_optimizing", False):
            app().toast("Ya se están optimizando las fotos…")
            return
        a = app()
        import photo_optimizer as po
        dbs = a.all_dbs() + ([a.db.shared] if getattr(a.db, "shared", None) is not None else [])
        self.ids.photo_text.text = "Revisando fotos…"

        def show(text):
            Clock.schedule_once(lambda *_: setattr(self.ids.photo_text, "text", text))

        def run(found):
            self._optimizing = True

            def progress(i, n, saved):
                if i == n or i % 5 == 0:
                    show(f"Optimizando fotos: {i} de {n} · {saved / 1e6:.1f} MB liberados")

            def work():
                try:
                    res = po.optimize(found["paths"], progress)
                    msg = (f"Listo: {res['optimized']} fotos optimizadas, "
                           f"{res['saved'] / 1e6:.1f} MB liberados.")
                except Exception as exc:  # noqa: BLE001
                    msg = f"No se pudieron optimizar las fotos: {exc}"
                self._optimizing = False
                show(msg)
                Clock.schedule_once(lambda *_: a.toast(msg))
            a.workers.submit(work)

        def ask(found):
            n, mb = len(found["paths"]), found["bytes"] / 1e6
            if not n:
                self.ids.photo_text.text = (f"Las {found['total']} fotos del teléfono ya están "
                                            "livianas: no hay nada que optimizar.")
                return
            self.ids.photo_text.text = f"{n} fotos pesadas ({mb:.0f} MB)."
            confirm("Optimizar fotos guardadas",
                    f"Hay {n} fotos pesadas ({mb:.0f} MB). Se reducirán a 1600 px y JPEG liviano "
                    f"(quedan en ≈{n * .3:.0f} MB), en el mismo archivo: registros, informes e IA "
                    "siguen igual. Las copias en Drive no se modifican. ¿Continuar?",
                    [("Optimizar", lambda: run(found))])

        def scan():
            found = po.scan(dbs)
            Clock.schedule_once(lambda *_: ask(found))
        a.workers.submit(scan)

    def full_backup(self):
        a = app()
        self._busy("Creando copia de seguridad…")

        def work():
            try:
                from data_transfer import full_backup
                path = full_backup(a.db, workspaces=a.workspaces, open_db=a.open_db)
                a.media.save_public(path, "application/zip")   # una sola copia en Descargas
                if a.db.get_setting("drive_enabled", False):
                    a.drive.enqueue(None, path, remote=f"Respaldos/{os.path.basename(path)}")
                size = os.path.getsize(path) / 1e6
                msg = (f"Copia guardada en Descargas › PhenoRubus: {os.path.basename(path)} "
                       f"({size:.1f} MB)" + (" · también se sube a Drive" if a.db.get_setting(
                           "drive_enabled", False) else ""))
                Clock.schedule_once(lambda *_: (self._busy(msg), a.toast("Copia de seguridad lista"),
                                                self._offer_share(path)))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: (self._busy(f"No se pudo crear la copia: {error}"),))

        a.workers.submit(work)

    def _offer_share(self, path):
        confirm("Copia de seguridad lista",
                "Quedó en Descargas › PhenoRubus. ¿Quiere además enviarla (Drive, correo, WhatsApp…)?",
                [("Compartir", lambda: app().share_file(path, "application/zip"))])

    def restore_backup(self):
        a = app()

        def picked(path, name):
            if not path:
                return
            if not path.lower().endswith((".zip", ".sqlite3", ".db")):
                a.toast("Elija la copia .zip o el archivo .sqlite3")
                return
            from ai_share import is_knowledge_package
            if is_knowledge_package(path):
                a.toast("Ese es un paquete de la IA: impórtelo en el módulo de IA › Modelo")
                return
            confirm("Restaurar copia de seguridad",
                    f"Se reemplazarán los datos actuales por los de «{name or os.path.basename(path)}». "
                    "Antes se guarda automáticamente una copia de lo actual.",
                    [("Restaurar", lambda: self._do_restore(path))])

        a.media.pick_document(picked, exts=(".zip", ".sqlite3", ".db"))

    def _do_restore(self, path):
        a = app()
        self._busy("Restaurando… no cierre la app.")

        def progress(i, n):
            if i % 10 == 0:
                Clock.schedule_once(lambda *_: self._busy(f"Recuperando fotos… {i}/{n}"))

        def work():
            try:
                from data_transfer import restore
                res = restore(a.db, path, progress=progress, workspaces=a.workspaces,
                              open_db=a.open_db)
                Clock.schedule_once(lambda *_: self._restored(res, None))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: self._restored(None, error))

        request_runtime_permissions(lambda _ok: a.workers.submit(work))

    def _restored(self, res, error):
        a = app()
        if error:
            self._busy(f"No se pudo restaurar: {error}")
            return
        a.reload_data()
        self.refresh()
        self._busy("Restaurado: " + res.summary())
        text = res.summary()
        if res.missing:
            text += ("\n\nFotos sin archivo (puede recuperarlas con «Importar informes semanales» "
                     "o volver a adjuntarlas desde la galería):\n• " + "\n• ".join(res.missing[:12]))
            if len(res.missing) > 12:
                text += f"\n… y {len(res.missing) - 12} más"
        confirm("Datos restaurados", text, [])

    def import_reports(self):
        a = app()

        def picked(path, name):
            if not path:
                return
            if not path.lower().endswith((".pdf", ".html", ".htm", ".zip")):
                a.toast("Elija un informe semanal (PDF, o .html/.zip de versiones anteriores)")
                return
            self._busy(f"Leyendo {name or os.path.basename(path)}…")

            def work():
                try:
                    from data_transfer import import_reports
                    res = import_reports(a.db, [path])
                    Clock.schedule_once(lambda *_: self._reports_done(res, None))
                except Exception as exc:  # noqa: BLE001
                    error = exc
                    Clock.schedule_once(lambda *_: self._reports_done(None, error))

            a.workers.submit(work)

        a.media.pick_document(picked, exts=(".pdf", ".html", ".htm", ".zip"))

    def _reports_done(self, res, error):
        a = app()
        if error:
            self._busy(f"No se pudo importar: {error}")
            return
        a.reload_data()
        self.refresh()
        self._busy("Importado: " + res.summary() + (" · " + "; ".join(res.skipped[:3]) if res.skipped else ""))
        a.toast("Informe importado" if res.reports else "El archivo no es un informe semanal")
