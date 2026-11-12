"""
report_config.py
================
«Configuración de informes» de un ensayo o predio: plantilla, formato (PDF simple, fotos) y
qué secciones lleva el informe semanal. Se guarda como un ajuste del ensayo
(«reportcfg», JSON; las «report_…» son comunes y no se sincronizan), así viaja con la sincronización entre la app y la web.

Puro Python (sin Kivy): lo usan la app, reporter.py y la web (Pyodide).
"""
from __future__ import annotations

import json

KEY = "reportcfg"
TEMPLATES_KEY = "reportcfg_templates"   # plantillas guardadas por el usuario (del ensayo)

# (clave, nombre, grupo) en el orden en que salen en el informe.
SECTIONS = [
    ("summary", "Resumen ejecutivo", "Resumen"),
    ("bbch_table", "Tabla de estados BBCH", "Resumen"),
    ("change", "Cambio vs semana anterior", "Resumen"),
    ("missing", "Variedades sin registro", "Resumen"),
    ("photos", "Registro fotográfico", "Fotos y notas"),
    ("notes", "Notas del muestreo", "Fotos y notas"),
    ("ai", "Sugerencia de la IA", "Fotos y notas"),
    ("attachments", "Fotos adjuntas", "Fotos y notas"),
    ("gps", "Ubicación GPS", "Fotos y notas"),
    ("measures", "Mediciones de la semana", "Mediciones y ensayo"),
    ("progress", "Avance de mediciones", "Mediciones y ensayo"),
    ("matrix", "Matriz fenológica", "Evolución"),
    ("chart", "Gráfico BBCH por semana", "Evolución"),
    ("precocity", "Precocidad relativa", "Evolución"),
    ("milestones", "Hitos fenológicos", "Evolución"),
    ("gallery", "Galería paralela", "Evolución"),
    ("treatments", "Tratamientos y ANOVA", "Mediciones y ensayo"),
    ("parcels", "Detalle por parcela", "Mediciones y ensayo"),
    ("scout", "Plagas y enfermedades", "Del predio"),
    ("yield", "Rendimiento estimado + mapa", "Del predio"),
    ("notebook", "Cuaderno de campo de la semana", "Del predio"),
    ("map", "Mapa de los muestreos", "Del predio"),
]
SECTION_KEYS = [k for k, _n, _g in SECTIONS]
SECTION_NAMES = {k: n for k, n, _g in SECTIONS}
GROUPS = ["Resumen", "Fotos y notas", "Evolución", "Mediciones y ensayo", "Del predio"]
NEW = {"summary", "change", "missing", "scout", "yield", "notebook", "map"}   # «nuevo» en la pantalla

PHOTO_MODES = {"both": "General y detalle", "canopy": "Solo general", "detail": "Solo detalle",
               "none": "Sin fotos"}
PHOTO_SIZES = {"compact": "Compacto", "normal": "Normal", "large": "Grande"}

# Lo que llevaba el informe semanal antes de la configuración (ensayos sin configurar).
CLASSIC = ["bbch_table", "photos", "notes", "ai", "attachments", "gps", "measures"]

TEMPLATES = {
    "completo": {"name": "Completo", "sections": list(SECTION_KEYS), "photo_mode": "both",
                 "photo_size": "normal", "all_photos": True, "plain": False},
    "resumido": {"name": "Resumido", "sections": ["summary", "bbch_table", "change", "missing", "chart",
                                                  "measures"],
                 "photo_mode": "none", "photo_size": "compact", "all_photos": False, "plain": False},
    "fotos": {"name": "Solo fotos", "sections": ["photos", "notes", "attachments"], "photo_mode": "both",
              "photo_size": "large", "all_photos": True, "plain": False},
    "cliente": {"name": "Para el cliente", "sections": ["summary", "bbch_table", "photos", "notes", "chart",
                                                        "milestones", "yield", "map"],
                "photo_mode": "both", "photo_size": "normal", "all_photos": False, "plain": True},
}
FORMAT_KEYS = ("photo_mode", "photo_size", "all_photos", "plain", "no_date")


def default(db=None) -> dict:
    """Configuración de un ensayo que nunca la guardó: el informe de siempre, con lo que
    estaba en las casillas antiguas (PDF simple, todas las fotos, «Fotos: …»)."""
    get = (lambda k, d: db.get_setting(k, d)) if db is not None else (lambda _k, d: d)
    mode = get("report_photo_mode", "both")
    return {"template": "", "sections": list(CLASSIC),
            "photo_mode": mode if mode in PHOTO_MODES else "both", "photo_size": "normal",
            "all_photos": bool(get("report_all_photos", False)), "plain": bool(get("report_plain_pdf", False)),
            "no_date": False}


def normalize(cfg: dict | None, base: dict | None = None) -> dict:
    out = dict(base or default())
    if isinstance(cfg, dict):
        for k in FORMAT_KEYS + ("template",):
            if k in cfg:
                out[k] = cfg[k]
        if isinstance(cfg.get("sections"), list):
            out["sections"] = [k for k in SECTION_KEYS if k in cfg["sections"]]   # orden del informe
    if out["photo_mode"] not in PHOTO_MODES:
        out["photo_mode"] = "both"
    if out["photo_size"] not in PHOTO_SIZES:
        out["photo_size"] = "normal"
    out["all_photos"], out["plain"] = bool(out["all_photos"]), bool(out["plain"])
    out["no_date"] = bool(out.get("no_date"))     # sin «Generado dd-mm-aaaa hh:mm»
    return out


def _parse(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw


def load(db) -> dict:
    return normalize(_parse(db.get_setting(KEY, None)), default(db))


def save(db, cfg: dict) -> dict:
    cfg = normalize(cfg, default(db))
    db.set_setting(KEY, cfg)
    # Las casillas antiguas siguen al día (versiones anteriores de la app y la web).
    db.set_setting("report_plain_pdf", cfg["plain"])
    db.set_setting("report_all_photos", cfg["all_photos"])
    db.set_setting("report_photo_mode", cfg["photo_mode"] if cfg["photo_mode"] != "none" else "both")
    return cfg


def apply_template(cfg: dict, key: str, saved: list[dict] | None = None) -> dict:
    """La plantilla «key» (de las fijas o «u:<nombre>», una guardada) sobre cfg."""
    tpl = TEMPLATES.get(key)
    if tpl is None and key.startswith("u:") and saved:
        ref = key[2:]
        tpl = next((t for t in saved if t["name"] == ref), None)
        if tpl is None and ref.isdigit() and int(ref) < len(saved):   # versiones anteriores: «u:<n>»
            tpl = saved[int(ref)]
            key = f"u:{tpl['name']}"
    if tpl is None:
        return dict(cfg)
    out = dict(cfg, **{k: tpl[k] for k in FORMAT_KEYS if k in tpl})
    out["sections"] = [k for k in SECTION_KEYS if k in tpl.get("sections", [])]
    out["template"] = key
    return normalize(out)


def toggle(cfg: dict, section: str) -> dict:
    sel = set(cfg["sections"])
    sel.symmetric_difference_update({section})
    if section == "photos" and section not in sel:      # sin registro, sin sus partes
        sel -= {"notes", "ai", "attachments", "gps"}
    if section in ("notes", "ai", "attachments", "gps") and section in sel:
        sel.add("photos")
    return normalize(dict(cfg, sections=list(sel), template=""))


# --------------------------------------------------- plantillas de la cuenta
# Las plantillas guardadas son de la CUENTA de Google (todos los cultivos, ensayos y equipos):
# en el teléfono, en el archivo global de la app (una lista por cuenta) y, en Drive,
# «AeonCrop/plantillas-informes.json», que la app y la web leen y suman al sincronizar.
# Cada una lleva «ts» (cuándo se guardó); al borrarla queda {"name", "deleted": true, "ts"}
# para que el borrado también llegue a los demás equipos.
DRIVE_FILE = "plantillas-informes.json"


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _account(db=None) -> str:
    from platform_utils import global_get
    return (global_get("drive_account", "") or "").strip().lower()


def _store_key(account: str | None = None) -> str:
    return "report_templates@" + (_account() if account is None else account)


def account_items(db=None, account: str | None = None) -> list[dict]:
    """Todas las plantillas de la cuenta, con las borradas (para sincronizar)."""
    from platform_utils import global_get
    raw = global_get(_store_key(account), None)
    items = [t for t in raw if isinstance(t, dict) and t.get("name")] if isinstance(raw, list) else []
    acc = _account() if account is None else account
    if acc:                   # guardadas antes de conectar la cuenta de Google: pasan a la cuenta
        loose = global_get(_store_key(""), None)
        if isinstance(loose, list) and loose:
            items = merge(items, [t for t in loose if isinstance(t, dict) and t.get("name")])
            _put_items(items, account)
            _put_items([], "")
    if db is not None:      # plantillas guardadas en un ensayo (versión anterior): pasan a la cuenta
        old = _parse(db.get_setting(TEMPLATES_KEY, None))
        if isinstance(old, list) and old:
            have = {t["name"] for t in items}
            for t in old:
                if isinstance(t, dict) and t.get("name") and t["name"] not in have:
                    items.append(dict(t, ts=_now()))
            _put_items(items, account)
            db.set_setting(TEMPLATES_KEY, [])
    return items


def _put_items(items: list[dict], account: str | None = None) -> None:
    from platform_utils import global_set
    global_set(_store_key(account), items)


def merge(a: list[dict], b: list[dict]) -> list[dict]:
    """Une dos listas de plantillas: por nombre, gana la guardada (o borrada) más reciente."""
    out: dict = {}
    for t in list(a or []) + list(b or []):
        if not isinstance(t, dict) or not t.get("name"):
            continue
        cur = out.get(t["name"])
        if cur is None or (t.get("ts") or "") > (cur.get("ts") or ""):
            out[t["name"]] = t
    return sorted(out.values(), key=lambda t: t["name"].lower())


def visible(items: list[dict]) -> list[dict]:
    return [t for t in items if not t.get("deleted")]


def saved_templates(db=None) -> list[dict]:
    return visible(account_items(db))


def save_template(db, name: str, cfg: dict) -> list[dict]:
    item = {"name": name, "sections": list(cfg["sections"]), **{k: cfg[k] for k in FORMAT_KEYS}, "ts": _now()}
    items = merge(account_items(db), [item])
    _put_items(items)
    return visible(items)


def delete_template(db, name: str) -> list[dict]:
    items = merge(account_items(db), [{"name": name, "deleted": True, "ts": _now()}])
    _put_items(items)
    return visible(items)


def receive_account(remote: list[dict]) -> tuple[list[dict], bool]:
    """Suma lo que llegó de Drive. Devuelve (todo, hay que subir lo de aquí)."""
    local = account_items()
    merged = merge(local, remote or [])
    if merged != merge(local, []):
        _put_items(merged)
    return merged, merged != merge(remote or [], [])


def summary(cfg: dict) -> str:
    """Una línea para el botón: «Completo · 22 secciones · PDF simple»."""
    tpl = cfg.get("template") or ""
    name = TEMPLATES.get(tpl, {}).get("name") or (tpl[2:] if tpl.startswith("u:") else "") or "Personalizado"
    n = len(cfg["sections"])
    bits = [name, f"{n} " + ("sección" if n == 1 else "secciones"), "fotos: " + PHOTO_MODES[cfg["photo_mode"]].lower()]
    if cfg["plain"]:
        bits.append("PDF simple")
    if cfg.get("no_date"):
        bits.append("sin fecha")
    return " · ".join(bits)
