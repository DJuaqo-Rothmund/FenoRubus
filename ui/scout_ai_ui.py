"""
ui/scout_ai_ui.py
=================
AeonScout · identificación con IA y guía (ver scout_ai y scout_guide):

* `keys_dialog`      — claves de Pl@ntNet, Gemini y Claude (quedan solo en el teléfono).
* `run`              — identifica una captura en segundo plano (pide permiso antes de Claude).
* `run_pending`      — reintenta las que quedaron sin señal o sin cuota.
* `result_dialog`    — candidatas con su confianza y rasgos: tocar una la acepta.
* `photo_guide`      — cómo sacar las fotos para que la IA reconozca.
* `ficha_card`       — ficha de la guía para la pantalla de la especie.
* `ai_block`         — estado de la IA en cada captura.
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout

import scout
import scout_ai
import scout_guide

AUTO_KEY = "scout_ai_auto"
_running: set[int] = set()


def app():
    return MDApp.get_running_app()


def db():
    return app().scout


def has_keys(section: str | None = None) -> bool:
    keys = scout_ai.load_keys(db())
    if section:
        return bool(scout_ai.chain(db(), section))
    return any(keys.values())


def auto_on() -> bool:
    return bool(db().get_setting(AUTO_KEY, True))


# ----------------------------------------------------------------- claves
def keys_dialog(on_done=None):
    from ui.screens import form_dialog
    keys = scout_ai.load_keys(db())
    form = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(6), padding=(0, dp(10), 0, 0))
    form.add_widget(Factory.Muted(
        text="Se guardan solo en este teléfono (no van a Drive). Malezas: Pl@ntNet › Gemini › Claude "
             "(este último pide permiso cada vez). Plagas y enfermedades: solo Gemini."))
    fields = {}
    for key, hint, help_text in (
            ("plantnet", "Clave de Pl@ntNet", "Gratis (500 consultas al día): my.plantnet.org › tu cuenta › "
                                               "API key."),
            ("gemini", "Clave de Gemini", "Google AI Studio (aistudio.google.com) › Get API key. Tiene un "
                                           "nivel gratuito; la suscripción de Gemini no incluye la API."),
            ("claude", "Clave de Claude (opcional)", "console.anthropic.com › API keys. Se paga aparte de la "
                                                      "suscripción de Claude; solo se usa si usted autoriza.")):
        f = Factory.Field(hint_text=hint, text=keys.get(key, ""), password=True)
        fields[key] = f
        form.add_widget(f)
        form.add_widget(Factory.Muted(text=help_text))
    from ui.varieties_ui import check_row
    row, auto = check_row("Identificar sola cada captura nueva (si hay clave)", auto_on())
    form.add_widget(row)

    def ok(_f):
        scout_ai.save_keys(db(), **{k: f.text for k, f in fields.items()})
        db().set_setting(AUTO_KEY, bool(auto.active))
        app().toast("Claves guardadas en el teléfono")
        if on_done:
            on_done()
    form_dialog("Claves de IA", form, ok)


# ----------------------------------------------------------------- identificar
def run(record_id: int, on_done=None, allow_claude: bool = False, quiet: bool = False):
    """Identifica la captura en segundo plano; al terminar muestra las candidatas (o
    un aviso). on_done() se llama siempre al final (para refrescar la pantalla)."""
    if record_id in _running:
        return
    a = app()
    _running.add(record_id)
    if not quiet:
        a.toast("Consultando a la IA…")

    def work():
        res, err = None, None
        try:
            res = scout_ai.identify(db(), record_id, allow_claude=allow_claude)
        except Exception as exc:  # noqa: BLE001 (se muestra al usuario)
            err = exc
        Clock.schedule_once(lambda *_: finished(res, err))

    def finished(res, err):
        _running.discard(record_id)
        if isinstance(err, scout_ai.NeedsClaude):
            _ask_claude(record_id, on_done)
        elif isinstance(err, scout_ai.Offline):
            if not quiet:
                a.toast("Sin señal: se identifica sola cuando haya conexión.")
        elif err is not None:
            if not quiet:
                a.toast(str(err)[:160])
        elif res is not None and not quiet:
            result_dialog(record_id, on_done)
        elif res is not None:
            top = res["candidates"][0] if res["candidates"] else None
            if top:
                a.toast(f"IA: posible {top['name']} ({top['confidence']:.0%})")
        if on_done:
            on_done()

    a.workers.submit(work)


def _ask_claude(record_id: int, on_done):
    from ui.screens import confirm
    confirm("¿Usar Claude?",
            "Hoy no quedan consultas en Pl@ntNet ni en Gemini. Claude puede identificarla, pero gasta "
            "créditos de su cuenta de la API de Claude (unos pocos centavos de dólar por consulta). "
            "Si no, queda pendiente y se identifica mañana.",
            [("Usar Claude", lambda: run(record_id, on_done, allow_claude=True))])


def run_pending(on_done=None):
    """Reintenta en silencio las capturas pendientes (sin señal o sin cuota)."""
    ids = scout_ai.pending(db())
    for rid in ids[:5]:
        run(rid, on_done, quiet=True)


# ----------------------------------------------------------------- resultado
def _cand_title(cnd: dict) -> str:
    return f"{cnd['name']}  ·  {cnd['confidence']:.0%}"


def _cand_sub(cnd: dict) -> str:
    parts = [cnd["scientific"], cnd["rank"], f"estadio: {cnd['stage']}" if cnd["stage"] else "",
             "en el catálogo" if cnd["species_id"] else "nueva en el catálogo"]
    return " · ".join(p for p in parts if p)


def result_dialog(record_id: int, on_done=None):
    from ui.screens import pick_dialog
    job = scout_ai.job(db(), record_id)
    data = (job or {}).get("data") or {}
    cands = data.get("candidates") or []
    prov = scout_ai.PROVIDERS.get(data.get("provider"), data.get("provider") or "IA")
    sub = [f"Según {prov}. Toque la que corresponde para asignarla."]
    if not data.get("is_target", True):
        sub.append("La IA no ve claramente una plaga, maleza o enfermedad en las fotos.")
    if data.get("advice"):
        sub.append("Para confirmar: " + data["advice"])
    items = [(_cand_title(cnd), _cand_sub(cnd), lambda cnd=cnd: _accept(record_id, cnd, on_done))
             for cnd in cands]
    footer = [("text-box-search-outline", "Ver rasgos", lambda: _features(record_id)),
              ("refresh", "Consultar de nuevo", lambda: (scout_ai.queue(db(), record_id),
                                                         run(record_id, on_done)))]
    pick_dialog("Sugerencia de la IA", items, subtitle="\n".join(sub), footer=footer,
                empty="La IA no encontró candidatas: saque más fotos (ver la guía) y consulte de nuevo.")


def _features(record_id: int):
    from ui.screens import text_dialog
    data = (scout_ai.job(db(), record_id) or {}).get("data") or {}
    lines = []
    for cnd in data.get("candidates") or []:
        lines.append(f"[b]{cnd['name']}[/b] ({cnd['confidence']:.0%}) [i]{cnd['scientific']}[/i]\n"
                     f"{cnd['features'] or '—'}")
        g = scout_guide.find(db().get_record(record_id)["section"], cnd["name"], cnd["scientific"])
        if g:
            lines.append("Ficha: " + g["look"])
    if data.get("notes"):
        lines.append("Notas: " + data["notes"])
    if data.get("advice"):
        lines.append("Foto que falta: " + data["advice"])
    text_dialog("Rasgos que vio la IA", lines or ["Sin detalle."], markup=True)


def _accept(record_id: int, cnd: dict, on_done):
    from ui.screens import confirm
    rec = db().get_record(record_id)
    cur = db().get_species(rec["species_id"])

    def go():
        try:
            sid = scout_ai.accept(db(), record_id, cnd)
        except ValueError as exc:
            app().toast(str(exc))
            return
        app().toast(f"Captura asignada a {db().get_species(sid)['name']}")
        app().scout_backup()
        if on_done:
            on_done(sid) if _wants_sid(on_done) else on_done()

    if cur and not cur["unidentified"] and cur["name"] == cnd["name"]:
        app().toast("Ya está identificada así.")
        return
    was = "sin identificar" if cur["unidentified"] else f"«{cur['name']}»"
    confirm("Asignar especie",
            f"La captura ({was}) pasa a «{cnd['name']}» con sus fotos (también en Drive)."
            + ("" if cnd["species_id"] else " Se agrega al catálogo."), [("Asignar", go)])


def _wants_sid(fn) -> bool:
    import inspect
    try:
        return len(inspect.signature(fn).parameters) >= 1
    except (TypeError, ValueError):
        return False


# ----------------------------------------------------------------- guía
def photo_guide(section: str):
    """Guía ilustrada de cómo sacar las fotos (pantalla con láminas)."""
    from ui import scout_ui
    scout_ui.open_guide(section)


def ficha_card(sp: dict):
    """Tarjeta con la ficha de la guía (o None si la especie no está en la guía)."""
    g = scout_guide.find(sp["section"], sp["name"], sp["scientific"])
    if not g:
        return None
    card = Factory.PaperCard()
    card.add_widget(Factory.SectionLabel(text="FICHA DE LA GUÍA" + ("" if g["name"] == sp["name"] else
                                                                   f" · {g['name']}")))
    card.add_widget(Factory.Body(text=scout_guide.ficha_text(g), markup=True))
    card.add_widget(Factory.Muted(text="Ayuda de campo: confirme con un especialista o laboratorio "
                                       "cuando haya dudas (sobre todo en enfermedades)."))
    return card


def crops_label(sp: dict) -> str:
    g = scout_guide.find(sp["section"], sp["name"], sp["scientific"])
    return ("Fr " if "F" in g["crops"] else "") + ("Ar " if "A" in g["crops"] else "") + \
        ("Cr" if "C" in g["crops"] else "") if g else ""


def ai_block(record_id: int, refresh):
    """Fila con el estado de la IA para una captura (en la pantalla de la especie)."""
    job = scout_ai.job(db(), record_id)
    sec = db().get_record(record_id)["section"]
    box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(2))
    if job and job["status"] == "done":
        data = job["data"]
        top = (data.get("candidates") or [None])[0]
        prov = scout_ai.PROVIDERS.get(job["provider"], job["provider"])
        txt = (f"IA ({prov}): {top['name']} {top['confidence']:.0%}" if top else f"IA ({prov}): sin candidatas")
        if job["accepted"]:
            txt += f" · asignada: {job['accepted']}"
        b = Factory.GhostButton(icon="robot-outline", text=txt)
        b.bind(on_release=lambda *_: result_dialog(record_id, refresh))
        box.add_widget(b)
    elif job and job["status"] in ("pending", "claude", "error") or record_id in _running:
        msg = ("Consultando…" if record_id in _running else
               {"pending": "IA: pendiente (sin señal o sin cuota)", "claude": "IA: falta autorizar Claude",
                "error": f"IA: {job['error'] or 'error'}"}[job["status"]])
        b = Factory.GhostButton(icon="robot-confused-outline", text=msg + " · tocar para reintentar")
        b.bind(on_release=lambda *_: (scout_ai.queue(db(), record_id), run(record_id, refresh)))
        box.add_widget(b)
    else:
        if not has_keys(sec):
            b = Factory.GhostButton(icon="key-outline", text="Identificar con IA (poner las claves)")
            b.bind(on_release=lambda *_: keys_dialog(refresh))
        else:
            b = Factory.GhostButton(icon="robot-outline", text="Identificar con IA")
            b.bind(on_release=lambda *_: run(record_id, refresh))
        box.add_widget(b)
    return box
