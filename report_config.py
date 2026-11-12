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
FORMAT_KEYS = ("photo_mode", "photo_size", "all_photos", "plain")


def default(db=None) -> dict:
    """Configuración de un ensayo que nunca la guardó: el informe de siempre, con lo que
    estaba en las casillas antiguas (PDF simple, todas las fotos, «Fotos: …»)."""
    get = (lambda k, d: db.get_setting(k, d)) if db is not None else (lambda _k, d: d)
    mode = get("report_photo_mode", "both")
    return {"template": "", "sections": list(CLASSIC),
            "photo_mode": mode if mode in PHOTO_MODES else "both", "photo_size": "normal",
            "all_photos": bool(get("report_all_photos", False)), "plain": bool(get("report_plain_pdf", False))}


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
    """La plantilla «key» (de las fijas o «u:<n>», una guardada) sobre cfg."""
    tpl = TEMPLATES.get(key)
    if tpl is None and key.startswith("u:") and saved:
        i = int(key[2:]) if key[2:].isdigit() else -1
        tpl = saved[i] if 0 <= i < len(saved) else None
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


def saved_templates(db) -> list[dict]:
    raw = _parse(db.get_setting(TEMPLATES_KEY, None))
    return [t for t in raw if isinstance(t, dict) and t.get("name")] if isinstance(raw, list) else []


def save_template(db, name: str, cfg: dict) -> list[dict]:
    items = [t for t in saved_templates(db) if t["name"] != name]
    items.append({"name": name, "sections": list(cfg["sections"]), **{k: cfg[k] for k in FORMAT_KEYS}})
    db.set_setting(TEMPLATES_KEY, items)
    return items


def delete_template(db, name: str) -> list[dict]:
    items = [t for t in saved_templates(db) if t["name"] != name]
    db.set_setting(TEMPLATES_KEY, items)
    return items


def summary(cfg: dict) -> str:
    """Una línea para el botón: «Completo · 22 secciones · PDF simple»."""
    name = TEMPLATES.get(cfg.get("template") or "", {}).get("name") or (
        cfg["template"] and "Plantilla guardada") or "Personalizado"
    n = len(cfg["sections"])
    bits = [name, f"{n} " + ("sección" if n == 1 else "secciones"), "fotos: " + PHOTO_MODES[cfg["photo_mode"]].lower()]
    if cfg["plain"]:
        bits.append("PDF simple")
    return " · ".join(bits)
