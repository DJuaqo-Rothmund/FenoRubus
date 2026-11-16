"""
box_ai.py
=========
Cajas automáticas (sugeridas) sobre una foto de detalle: botones, flores y frutos por
estadio, con Gemini (gratis, la misma clave de AeonScout: scout_ai). Mientras no esté
entrenada la IA propia, sirven para contar más rápido: la persona revisa, corrige el tipo
de cada caja y agrega o borra las que falten (editor de IA+: ui/boxes.py y web/train.js).

Gemini entrega cada caja como box_2d = [ymin, xmin, ymax, xmax] de 0 a 1000; aquí se pasa al
formato de las marcas (training_labels): {"c", "x", "y", "w", "h"} de 0 a 1.
"""
from __future__ import annotations

import scout_ai

MAX_BOXES = 150

DESCRIPTIONS = {        # ayuda para distinguir los estadios (frambuesa, arándano, cranberry)
    "yema": "yema cerrada en la caña o tallo",
    "brote": "brote vegetativo nuevo (hojas pequeñas)",
    "lateral": "lateral: rama florífera que sale de la caña",
    "upright": "brote vertical (upright) de cranberry",
    "estolon": "estolón (guía rastrera) de cranberry",
    "boton": "botón floral cerrado, verde",
    "boton_blanco": "botón floral blanco a punto de abrir",
    "racimo": "racimo floral de arándano (varias flores cerradas juntas)",
    "gancho": "gancho: botón floral curvado de cranberry",
    "flor": "flor abierta",
    "flor_pasada": "flor pasada: pétalos caídos o secos, aún sin fruto formado",
    "fruto_verde": "fruto verde (cuajado, sin color)",
    "fruto_pinton": "fruto que empieza a tomar color (pintón / rosado / blush)",
    "fruto_maduro": "fruto maduro de color pleno",
}


def schema(keys: list[str]) -> dict:
    return {"type": "ARRAY", "items": {"type": "OBJECT", "required": ["box_2d", "label"], "properties": {
        "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "label": {"type": "STRING", "enum": list(keys)}}}}


def prompt(classes: list[tuple[str, str, str]], crop_name: str = "") -> str:
    lines = "\n".join(f"- {k}: {n} — {DESCRIPTIONS.get(k, n)}" for k, n, _c in classes)
    return (
        f"Foto de detalle de una planta de {crop_name or 'berries'}. Marca con una caja ajustada CADA "
        "estructura de estas clases que se vea (también las parcialmente tapadas o pequeñas):\n"
        f"{lines}\n\n"
        "No marques hojas ni tallos sueltos, ni lo que esté fuera de foco al fondo. Una caja por "
        "estructura (no agrupes varias). Para cada una entrega box_2d = [ymin, xmin, ymax, xmax] "
        f"normalizado de 0 a 1000 y label con la clave exacta. Máximo {MAX_BOXES} cajas."
    )


def to_boxes(raw, keys) -> list[dict]:
    """Respuesta de Gemini -> cajas de las marcas (0-1), descartando las inválidas."""
    out = []
    for it in raw if isinstance(raw, list) else []:
        try:
            y0, x0, y1, x1 = [float(v) / 1000 for v in it["box_2d"]][:4]
        except (KeyError, TypeError, ValueError):
            continue
        c = it.get("label")
        if c not in keys:
            continue
        x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
        y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
        if x1 - x0 < .004 or y1 - y0 < .004:
            continue
        out.append({"c": c, "x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4),
                    "h": round(y1 - y0, 4), "s": "ia"})
    return out[:MAX_BOXES]


def iou(a: dict, b: dict) -> float:
    ix = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    inter = ix * iy
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def merge(existing: list[dict], new: list[dict], thr: float = .5) -> list[dict]:
    """Agrega las sugeridas que no tapan una caja que ya estaba (las de la persona mandan)."""
    keep = [n for n in new if all(iou(n, e) < thr for e in existing)]
    return list(existing) + keep


def suggest(key: str, image_path: str, classes, crop_name: str = "", db=None, progress=None) -> list[dict]:
    """Cajas sugeridas para la foto (lanza scout_ai.AIError/Quota/BadKey/Offline)."""
    keys = [k for k, _n, _c in classes]
    img = scout_ai.prepare([image_path], max_side=1600)
    raw = scout_ai.ask_gemini(key, img, prompt(classes, crop_name), progress=progress, db=db,
                              schema=schema(keys))
    return to_boxes(raw, keys)
