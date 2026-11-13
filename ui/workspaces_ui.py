"""
ui/workspaces_ui.py
===================
Ensayos y predios: lista, creación y cambio de ensayo.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import GlassButton, SegButton, app, confirm, fast_clear, form_dialog, pick_dialog


class WorkspaceBanner(GlassButton):
    text = StringProperty()
    icon = StringProperty("flask-outline")

    def open_measures(self):
        open_measures_menu()


class WorkspaceRow(GlassButton):
    title = StringProperty()
    subtitle = StringProperty()
    code = StringProperty()
    profile = StringProperty("id")
    current = BooleanProperty(False)
    ws = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


class WorkspaceTile(GlassButton):
    """Vista en cuadrícula: el mismo ensayo/predio como baldosa (código en un círculo)."""
    title = StringProperty()
    subtitle = StringProperty()
    code = StringProperty()
    profile = StringProperty("id")
    current = BooleanProperty(False)
    ws = ObjectProperty(None, allownone=True)
    screen = ObjectProperty()


class WorkspacesScreen(MDScreen):
    """Menú inicial: perfil I+D (ensayos) o Predio, y la lista para elegir dónde trabajar."""
    profile = StringProperty("id")
    show_archived = BooleanProperty(False)
    view_mode = StringProperty("list")   # «list» o «grid» (se recuerda)

    def on_kv_post(self, *_):
        try:
            self.view_mode = app().db.get_setting("workspaces_view", "list") or "list"
        except Exception:  # noqa: BLE001
            pass

    def toggle_view(self):
        self.view_mode = "grid" if self.view_mode == "list" else "list"
        app().db.set_setting("workspaces_view", self.view_mode)
        self.refresh()

    menu_mode = BooleanProperty(False)   # abierto desde el inicio: solo I+D o solo Predio

    def on_pre_enter(self, *_):
        ws = getattr(app(), "workspace", None)
        if not self.menu_mode and ws:
            self.profile = ws["profile"]
        self.show_archived = False
        self.refresh()

    def set_profile(self, profile: str):
        self.profile = profile
        self.show_archived = False
        self.refresh()

    def toggle_archived(self):
        self.show_archived = not self.show_archived
        self.refresh()

    def _stats(self, ws) -> str:
        from workspaces import KINDS
        a = app()
        parts = [KINDS.get(ws["kind"], ws["kind"])]
        try:
            db = a.open_db(ws)
            n = db.query_one("SELECT COUNT(*) AS n FROM varieties WHERE active=1 AND pheno_unit=0")["n"]
            one, many = {"tratamientos": ("parcela", "parcelas"), "predio": ("sector", "sectores")
                         }.get(ws["kind"], ("variedad", "variedades"))
            parts.append(f"{n} {one if n == 1 else many}")
            last = db.query_one("SELECT w.start_date FROM observations o JOIN sampling_weeks w "
                                "ON w.id = o.week_id WHERE o.bbch_code IS NOT NULL "
                                "ORDER BY w.start_date DESC LIMIT 1")
            if last:
                parts.append(f"último registro: {ph.week_title(last['start_date'])}")
        except Exception:  # noqa: BLE001 - nunca bloquear el menú por una base dañada
            pass
        return " · ".join(parts)

    def refresh(self):
        a = app()
        box = self.ids.ws_list
        fast_clear(box)
        items = a.workspaces.list(self.profile, archived=self.show_archived)
        cur = getattr(a, "workspace", None) or {}
        from workspaces import KINDS
        rows = []
        for ws in items:
            cls = WorkspaceTile if self.view_mode == "grid" else WorkspaceRow
            row = cls(title=ws["name"], code=ws["code"], profile=ws["profile"],
                               subtitle=KINDS.get(ws["kind"], ws["kind"]),
                               current=ws["id"] == cur.get("id"), ws=ws, screen=self)
            row.bind(on_release=lambda w: self.choose(w.ws))
            box.add_widget(row)
            rows.append(row)
        # Las estadísticas abren la base de cada ensayo: una por cuadro, ya con la lista a la vista.
        def fill(i=0):
            if i < len(rows) and rows[i].parent is box:
                rows[i].subtitle = self._stats(rows[i].ws)
                Clock.schedule_once(lambda *_: fill(i + 1), 0)
        Clock.schedule_once(lambda *_: fill(), 0.05)
        if not items:
            box.add_widget(MDLabel(text="No hay archivados." if self.show_archived else
                                   "Aún no hay nada aquí: toque + para crear el primero.",
                                   font_style="Caption", adaptive_height=True, halign="center",
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
        is_id = self.profile == "id"
        self.ids.hint.text = ("Ensayos de investigación y desarrollo: cada uno con sus variedades, "
                              "semanas, fotos, mediciones e informes por separado." if is_id else
                              "Predios comerciales: fenología por variedad, sector y equipo de riego.")
        if self.show_archived:
            self.ids.hint.text = "Archivados: no aparecen en la lista, pero sus datos se conservan."
        self.ids.add_btn.opacity, self.ids.add_btn.disabled = (0, True) if self.show_archived else (1, False)
        self.ids.archived_btn.text = "Volver a la lista" if self.show_archived else "Ver archivados"

    def choose(self, ws):
        if ws["archived"]:
            app().toast("Está archivado: desarchívelo con ⋮ para trabajar en él.")
            return
        # Predio: primero la lista de sectores a muestrear; ensayo: el muestreo semanal.
        app().open_workspace(ws["id"], target="sectors" if ws["profile"] == "predio" else "home")

    def item_menu(self, ws):
        a = app()

        def rename():
            from kivy.factory import Factory
            form = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=(0, dp(8), 0, 0))
            form.add_widget(Factory.Field(hint_text="Nombre", text=ws["name"]))

            def ok(f):
                try:
                    a.workspaces.rename(ws["id"], f.children[0].text)
                except ValueError as exc:
                    a.toast(str(exc))
                    return False
                a.workspace_renamed(ws["id"])
                self.refresh()

            form_dialog("Cambiar nombre", form, ok)

        def archive(flag):
            if flag and ws["id"] == (a.workspace or {}).get("id"):
                a.toast("Primero cambie a otro ensayo o predio.")
                return
            a.workspaces.set_archived(ws["id"], flag)
            self.refresh()

        def move():
            predios = a.workspaces.list("predio")
            if not predios:
                a.toast("No hay predios: cree uno primero en el menú Predio.")
                return

            def pick(dst):
                if a.workspaces.records(dst):
                    a.toast(f"«{dst['name']}» ya tiene registros: solo se traspasa a un predio vacío.")
                    return
                text = (f"Todo lo de «{ws['name']}» ({ws['code']}) pasa al predio «{dst['name']}» "
                        f"({dst['code']}): sectores, registros, fotos y mediciones, sin copiar ni "
                        f"volver a subir nada.\n\nLas fotos cambian su código a {dst['code']} en el "
                        f"teléfono, en la galería y en Google Drive (en el próximo respaldo). "
                        f"«{ws['name']}» queda vacío en I+D.")
                Clock.schedule_once(lambda *_: confirm(
                    f"Mover a {dst['name']}", text,
                    [("Mover", lambda: a.move_to_predio(ws, dst))]), .3)

            # El menú anterior se está cerrando: el siguiente diálogo, un instante después.
            Clock.schedule_once(lambda *_: pick_dialog("¿A qué predio?", [
                (p["name"], f"Código {p['code']}", lambda p=p: pick(p)) for p in predios]), .3)

        items = [("Cambiar nombre", f"Código {ws['code']} (no cambia)", rename)]
        if ws["profile"] == "id" and not ws["archived"]:
            items.append(("Mover a Predio…", "Si estos datos son de un predio (p. ej. tras actualizar)",
                          move))
        if ws["archived"]:
            items.append(("Desarchivar", "Vuelve a la lista", lambda: archive(False)))
        else:
            items.append(("Archivar", "Ocultar de la lista; los datos se conservan", lambda: archive(True)))
        pick_dialog(f"{ws['name']} · {ws['code']}", items)

    def new_item(self):
        a = app()
        from kivy.factory import Factory
        from workspaces import suggest_code
        is_id = self.profile == "id"
        form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8),
                           padding=(0, dp(12), 0, 0))
        name = Factory.Field(hint_text="Nombre del ensayo" if is_id else "Nombre del predio")
        code = Factory.Field(hint_text="Código (2 a 4 letras, va en el nombre de las fotos)")
        state = {"auto": True}

        def on_name(_w, text):
            if state["auto"]:
                code.text = suggest_code(text, a.workspaces.codes())

        def on_code(_w, text):
            up = text.upper()[:4]
            if up != text:
                code.text = up
            if code.focus:
                state["auto"] = False

        name.bind(text=on_name)
        code.bind(text=on_code)
        form.add_widget(name)
        form.add_widget(code)
        state["kind"] = "variedades" if is_id else "predio"
        if is_id:
            seg = MDBoxLayout(adaptive_height=True, spacing=dp(8))
            # Altos y en dos líneas: «Tratamientos × repeticiones» se leía cortado («…»).
            b_var = SegButton(text="Variedades", selected=True, height=dp(54), shorten=False,
                              font_size="14sp")
            b_trt = SegButton(text="Tratamientos\n× repeticiones", height=dp(54), shorten=False,
                              font_size="14sp", line_height=1.05)
            seg.add_widget(b_var)
            seg.add_widget(b_trt)
            trt = MDBoxLayout(adaptive_height=True, spacing=dp(8))
            n_t = Factory.Field(hint_text="N.º tratamientos", input_filter="int", text="4")
            n_r = Factory.Field(hint_text="N.º repeticiones", input_filter="int", text="4")
            trt.add_widget(n_t)
            trt.add_widget(n_r)
            t0_row, t0_cb = check_row("El ensayo tiene T0 (tratamiento 0): T0 … Tn-1",
                                      on_change=lambda *_: (update_info(), build_meanings()))
            # Alto fijo: el diálogo no cambia de tamaño al elegir el tipo (KivyMD no lo reajusta).
            info = MDLabel(font_style="Caption", size_hint_y=None, height=dp(48), valign="top",
                           theme_text_color="Custom", text_color=c(theme.MUTED))
            info.bind(width=lambda w, v: setattr(w, "text_size", (v, dp(48))))
            form.add_widget(MDLabel(text="Tipo de ensayo", font_style="Caption", adaptive_height=True,
                                    theme_text_color="Custom", text_color=c(theme.MUTED)))
            form.add_widget(seg)
            form.add_widget(trt)
            form.add_widget(t0_row)
            form.add_widget(info)
            # Qué es cada tratamiento (T1 = Testigo…): opcional, también en Ajustes › Registros.
            from kivy.uix.scrollview import ScrollView
            meanings = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6))
            m_title = MDLabel(text="Qué es cada tratamiento (opcional)", font_style="Caption",
                              bold=True, adaptive_height=True, theme_text_color="Custom",
                              text_color=c(theme.LEAF_DARK))
            m_scroll = ScrollView(size_hint_y=None, height=0, do_scroll_x=False, bar_width=dp(3))
            m_scroll.add_widget(meanings)
            form.add_widget(m_title)
            form.add_widget(m_scroll)
            state["meanings"] = []

            def build_meanings(*_):
                show = state["kind"] == "tratamientos"
                try:
                    t = min(int(n_t.text or 0), 20) if show else 0
                except ValueError:
                    t = 0
                old = [f.text for f in state["meanings"]]
                fast_clear(meanings)
                state["meanings"] = []
                first = 0 if t0_cb.active else 1
                for j in range(t):
                    i = first + j
                    f = Factory.Field(hint_text=f"T{i} = (ej.: {'Testigo' if j == 0 else 'producto, dosis…'})",
                                      text=old[j] if j < len(old) else "")
                    meanings.add_widget(f)
                    state["meanings"].append(f)
                m_title.opacity = 1 if t else 0
                m_title.height = m_title.texture_size[1] if t else 0
                Clock.schedule_once(lambda *_: setattr(
                    m_scroll, "height", min(dp(190), meanings.height) if t else 0), 0)

            def set_kind(kind):
                state["kind"] = kind
                b_var.selected, b_trt.selected = kind == "variedades", kind == "tratamientos"
                trt.disabled = t0_row.disabled = kind != "tratamientos"
                trt.opacity = t0_row.opacity = 1 if kind == "tratamientos" else .35
                update_info()
                build_meanings()

            def update_info(*_):
                if state["kind"] == "variedades":
                    info.text = ("Ensayo de variedades: cada variedad se registra por separado y los "
                                 "informes comparan variedades.")
                    return
                try:
                    t, r = int(n_t.text or 0), int(n_r.text or 0)
                except ValueError:
                    t = r = 0
                f0 = 0 if t0_cb.active else 1
                info.text = (f"Se crearán {t * r} parcelas: T{f0}R1 … T{f0 + t - 1}R{r}. Los informes promedian las "
                             "repeticiones y comparan los tratamientos (ANOVA)." if t and r else
                             "Indique cuántos tratamientos y repeticiones tiene el ensayo.")

            b_var.bind(on_release=lambda *_: set_kind("variedades"))
            b_trt.bind(on_release=lambda *_: set_kind("tratamientos"))
            n_t.bind(text=update_info)
            n_t.bind(text=build_meanings)
            n_r.bind(text=update_info)
            set_kind("variedades")

        def ok(_f):
            kind = state["kind"]
            size = None
            if kind == "tratamientos":
                try:
                    size = int(n_t.text or 0), int(n_r.text or 0)
                except ValueError:
                    size = (0, 0)
                from database import Database
                if not (1 <= size[0] <= Database.MAX_TREATMENTS and 1 <= size[1] <= Database.MAX_REPS):
                    a.toast(f"Tratamientos: 1 a {Database.MAX_TREATMENTS} · repeticiones: 1 a {Database.MAX_REPS}.")
                    return False
            try:
                ws = a.workspaces.create(self.profile, kind, name.text, code.text)
            except ValueError as exc:
                a.toast(str(exc))
                return False
            named = 0
            if size:
                db = a.open_db(ws)
                db.setup_trial(*size, t0=t0_cb.active)
                for i, f in enumerate(state.get("meanings", [])[:size[0]], 0 if t0_cb.active else 1):
                    if f.text.strip():
                        db.update_treatment(i, f.text)
                        named += 1
            a.open_workspace(ws["id"], target="sectors" if ws["profile"] == "predio" else "home")
            if size:
                a.toast(f"«{ws['name']}» creado con {size[0] * size[1]} parcelas"
                        + ("" if named == size[0] else
                           ". Defina qué es cada tratamiento en Ajustes › Registros"))
            else:
                a.toast(f"«{ws['name']}» creado: agregue sus "
                        + ("variedades en Ajustes › Registros" if is_id
                           else "sectores con «+ Nuevo sector»"))

        form_dialog("Nuevo ensayo" if is_id else "Nuevo predio", form, ok, "CREAR")


# Referencias a otras pantallas (al final: así no hay importaciones circulares).
from ui.varieties_ui import check_row  # noqa: E402
from ui.measures_ui import open_measures_menu  # noqa: E402
