"""
scout_ai.py
===========
Identificación con IA online de las capturas de AeonScout (capa 3; la capa 1 es la guía
scout_guide). Puro Python (sin Kivy): urllib + Pillow.

Orden de servicios (lo eligió el usuario):

* MALEZAS: Pl@ntNet (gratis, hasta agotar su cuota diaria) → Gemini → Claude (solo con
  autorización explícita cada vez: gasta créditos de la API de Claude).
* PLAGAS y ENFERMEDADES: solo Gemini.

Las claves (API keys) quedan en el teléfono, en «aeonscout/ia_claves.json»: nunca van a Drive
ni a la sincronización. Las suscripciones a Gemini o Claude NO incluyen la API: la clave de
Gemini se saca gratis en Google AI Studio y la de Claude en la consola de Anthropic (pagada).

Cada consulta queda en la tabla `scout_ai` (una fila por captura): pendiente (sin señal o sin
cuota: se reintenta sola), lista (con hasta 3 candidatas) o con error. Al aceptar una
candidata, la captura pasa a esa especie (y se suma al catálogo si no estaba): esas
confirmaciones son las etiquetas con que después se entrena la IA propia.

Nota: la llamada a Claude es HTTP directo (no el SDK oficial) porque el SDK de Python depende
de paquetes compilados que python-for-android no construye; el resto de la app usa urllib.
"""
from __future__ import annotations

import base64
import datetime as _dt
import io
import json
import os
import urllib.error
import urllib.request
import uuid

import scout
import scout_guide

KEYS_FILE = "ia_claves.json"
PROVIDERS = {
    "plantnet": "Pl@ntNet",
    "gemini": "Gemini",
    "claude": "Claude",
}
ORDER = {
    "malezas": ("plantnet", "gemini", "claude"),
    "plagas": ("gemini",),
    "enfermedades": ("gemini",),
}
PLANTNET_URL = "https://my-api.plantnet.org/v2/identify/all"
PLANTNET_DAILY = 500
PLANTNET_MIN_SCORE = .15        # por debajo, se pide una segunda opinión (Gemini)
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_FALLBACK_MODEL = "gemini-flash-latest"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-opus-5-5"
MAX_PHOTOS = 5
MAX_SIDE = 1280

SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_ai (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   INTEGER NOT NULL UNIQUE REFERENCES scout_records(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | done | error | claude (pide permiso)
    provider    TEXT NOT NULL DEFAULT '',
    result      TEXT NOT NULL DEFAULT '',          -- JSON (ver normalize)
    error       TEXT NOT NULL DEFAULT '',
    accepted    TEXT NOT NULL DEFAULT '',          -- nombre de la candidata aceptada
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class AIError(Exception):
    """Error que se muestra al usuario."""


class Offline(AIError):
    """Sin señal: queda pendiente y se reintenta."""


class Quota(AIError):
    """Sin cuota (diaria o por minuto) en ese servicio."""

    def __init__(self, msg: str, daily: bool = True):
        super().__init__(msg)
        self.daily = daily


class BadKey(AIError):
    """La clave no sirve (401/403)."""


class NeedsClaude(AIError):
    """Solo queda Claude: hay que pedir autorización."""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return _dt.date.today().isoformat()


def ensure(db) -> None:
    with db._lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()


# ----------------------------------------------------------------- claves y cuotas
def keys_path(db) -> str:
    return os.path.join(db.base_dir, KEYS_FILE)


def load_keys(db) -> dict:
    try:
        with open(keys_path(db), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_keys(db, **values) -> dict:
    data = load_keys(db)
    for k, v in values.items():
        v = (v or "").strip()
        if v:
            data[k] = v
        else:
            data.pop(k, None)
    with open(keys_path(db), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def usage(db) -> dict:
    u = db.get_setting("scout_ai_usage") or {}
    if u.get("day") != _today():
        u = {"day": _today(), "count": {}, "out": []}
    return u


def _count(db, provider: str, remaining: int | None = None, out: bool = False) -> None:
    u = usage(db)
    u["count"][provider] = u["count"].get(provider, 0) + (0 if out else 1)
    if remaining is not None:
        u.setdefault("remaining", {})[provider] = remaining
    if out and provider not in u["out"]:
        u["out"].append(provider)
    db.set_setting("scout_ai_usage", u)


def available(db, provider: str) -> bool:
    """Tiene clave y no se le agotó la cuota hoy."""
    if not load_keys(db).get(provider):
        return False
    return provider not in usage(db)["out"]


def chain(db, section: str) -> list[str]:
    """Servicios a probar, en orden, para la sección (los sin clave no cuentan)."""
    return [p for p in ORDER.get(section, ()) if load_keys(db).get(p)]


def status_text(db) -> str:
    keys, u = load_keys(db), usage(db)
    out = []
    for p, name in PROVIDERS.items():
        if not keys.get(p):
            out.append(f"{name}: sin clave")
            continue
        n = u["count"].get(p, 0)
        extra = ""
        if p == "plantnet":
            rem = u.get("remaining", {}).get(p)
            extra = f" · quedan {rem}" if rem is not None else f" · cuota {PLANTNET_DAILY}/día"
        out.append(f"{name}: {n} hoy{extra}" + (" · SIN CUOTA HOY" if p in u["out"] else ""))
    return "\n".join(out)


# ----------------------------------------------------------------- HTTP
def _ssl():
    from drive_backup import _ssl_context
    return _ssl_context()


def _post(url: str, body: bytes, headers: dict, timeout: int = 90) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        raise Offline(f"Sin conexión: {getattr(e, 'reason', e)}") from e


def _json(data: bytes) -> dict:
    try:
        out = json.loads(data.decode("utf-8", "replace"))
        return out if isinstance(out, dict) else {}
    except ValueError:
        return {}


def _err_text(data: bytes) -> str:
    j = _json(data)
    e = j.get("error")
    if isinstance(e, dict):
        return str(e.get("message") or e)[:300]
    return str(e or j.get("message") or data[:200])[:300]


# ----------------------------------------------------------------- fotos
def prepare(paths: list[str], max_side: int = MAX_SIDE) -> list[bytes]:
    """JPEG livianos (lado mayor ≤ 1280 px) para enviar."""
    from PIL import Image, ImageOps
    out = []
    for p in paths[:MAX_PHOTOS]:
        try:
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        except Exception:  # noqa: BLE001 (foto borrada o dañada: se salta)
            continue
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        out.append(buf.getvalue())
    return out


PLANTNET_ORGANS = {"Planta completa": "habit", "Hoja (haz)": "leaf", "Hoja (envés)": "leaf",
                   "Flor / semilla": "flower"}


# ----------------------------------------------------------------- consulta (texto)
def _context(section: str, record: dict) -> dict:
    crop = record.get("crop") or ""
    crop_name = scout_guide.CROP_NAMES.get(crop, crop or "sin indicar")
    cands = scout_guide.species_for(section, crop if crop in scout_guide.CROP_NAMES else None)
    return {"crop": crop_name, "candidates": cands, "stages": scout.STAGES[section]}


def prompt(section: str, record: dict, views: list[str]) -> str:
    ctx = _context(section, record)
    what = {"plagas": "insecto, ácaro, molusco u otro artrópodo (plaga o benéfico)",
            "malezas": "maleza (planta espontánea)",
            "enfermedades": "enfermedad o daño (hongo, bacteria, virus o abiótico)"}[section]
    lines = "\n".join(f"- {c['name']} — {c['scientific']} ({c['rank']})" for c in ctx["candidates"])
    v = ", ".join(x for x in views if x) or "sin indicar"
    return (
        f"Eres un experto en sanidad vegetal de berries en la {scout_guide.REGION}. Las fotos son "
        f"del mismo individuo o muestra: un(a) {what}, en un cultivo de {ctx['crop']}. "
        f"Vistas: {v}. Órgano: {record.get('organ') or 'sin indicar'}. Notas del usuario: "
        f"{record.get('notes') or '—'}.\n\n"
        "Identifica la especie; si no se puede llegar a especie con seguridad, llega al género o "
        "a la familia (rank). Describe en «features» los rasgos que ves y que sustentan la "
        "identificación (forma, color, tamaño, estructuras). Indica el estadio, eligiendo uno de: "
        + "; ".join(ctx["stages"]) + ". Da hasta 3 candidatas ordenadas de más a menos "
        "probable, con confianza entre 0 y 1 (sé honesto: baja si la foto no alcanza).\n\n"
        "Especies frecuentes en la zona (si es una de estas, copia su nombre exacto en "
        "catalog_name; si no, deja catalog_name vacío y da igual el nombre común y científico):\n"
        f"{lines}\n\n"
        "En photo_advice di qué foto adicional ayudaría a confirmar (ángulo, detalle, escala). "
        "Si las fotos no muestran un(a) " + what + ", pon is_target en false. Responde en español."
    )


_CAND_PROPS = {
    "common_name": "string", "scientific_name": "string", "rank": "string", "catalog_name": "string",
    "stage": "string", "confidence": "number", "features": "string",
}


def claude_schema() -> dict:
    cand = {"type": "object", "additionalProperties": False, "required": list(_CAND_PROPS),
            "properties": {k: {"type": t} for k, t in _CAND_PROPS.items()}}
    return {"type": "object", "additionalProperties": False,
            "required": ["is_target", "candidates", "photo_advice", "notes"],
            "properties": {"is_target": {"type": "boolean"},
                           "candidates": {"type": "array", "items": cand},
                           "photo_advice": {"type": "string"}, "notes": {"type": "string"}}}


def gemini_schema() -> dict:
    up = {"string": "STRING", "number": "NUMBER"}
    cand = {"type": "OBJECT", "required": list(_CAND_PROPS),
            "properties": {k: {"type": up[t]} for k, t in _CAND_PROPS.items()}}
    return {"type": "OBJECT", "required": ["is_target", "candidates", "photo_advice", "notes"],
            "properties": {"is_target": {"type": "BOOLEAN"},
                           "candidates": {"type": "ARRAY", "items": cand},
                           "photo_advice": {"type": "STRING"}, "notes": {"type": "STRING"}}}


# ----------------------------------------------------------------- servicios
def ask_plantnet(key: str, images: list[bytes], organs: list[str]) -> tuple[dict, int | None]:
    boundary = uuid.uuid4().hex
    parts = []
    for i, img in enumerate(images):
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"images\"; "
                      f"filename=\"foto{i}.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() + img + b"\r\n")
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"organs\"\r\n\r\n"
                      f"{organs[i] if i < len(organs) else 'auto'}\r\n").encode())
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    url = f"{PLANTNET_URL}?api-key={urllib.request.quote(key)}&lang=es&nb-results=5"
    code, data = _post(url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    j = _json(data)
    remaining = j.get("remainingIdentificationRequests")
    if code == 404:          # «Species not found»: no reconoció nada
        return {"is_target": False, "candidates": [], "photo_advice": "", "notes":
                "Pl@ntNet no reconoció la planta."}, remaining
    if code == 429:
        raise Quota("Pl@ntNet: se acabó la cuota de hoy.")
    if code in (401, 403):
        raise BadKey("Pl@ntNet: la clave no es válida.")
    if code != 200:
        raise AIError(f"Pl@ntNet ({code}): {_err_text(data)}")
    cands = []
    for r in (j.get("results") or [])[:3]:
        sp = r.get("species") or {}
        common = (sp.get("commonNames") or [""])[0]
        cands.append({
            "common_name": common, "scientific_name": sp.get("scientificNameWithoutAuthor", ""),
            "rank": "especie", "catalog_name": "", "stage": "",
            "confidence": float(r.get("score") or 0),
            "features": f"Familia {(sp.get('family') or {}).get('scientificNameWithoutAuthor', '?')}",
        })
    return {"is_target": True, "candidates": cands, "photo_advice": "", "notes": ""}, remaining


def ask_gemini(key: str, images: list[bytes], text: str, model: str = GEMINI_MODEL) -> dict:
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(i).decode()}}
             for i in images]
    parts.append({"text": text})
    body = json.dumps({"contents": [{"role": "user", "parts": parts}],
                       "generationConfig": {"responseMimeType": "application/json",
                                            "responseSchema": gemini_schema()}}).encode()
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    code, data = _post(GEMINI_URL.format(model=model), body, headers)
    if code == 404 and model != GEMINI_FALLBACK_MODEL:      # modelo retirado: el alias vigente
        return ask_gemini(key, images, text, GEMINI_FALLBACK_MODEL)
    if code == 429:
        msg = _err_text(data)
        raise Quota("Gemini: sin cuota (" + msg[:120] + ")", daily="day" in msg.lower())
    if code in (401, 403) or (code == 400 and "API key" in _err_text(data)):
        raise BadKey("Gemini: la clave no es válida.")
    if code != 200:
        raise AIError(f"Gemini ({code}): {_err_text(data)}")
    j = _json(data)
    try:
        txt = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        return json.loads(txt)
    except (KeyError, IndexError, ValueError) as exc:
        reason = ((j.get("promptFeedback") or {}).get("blockReason")
                  or ((j.get("candidates") or [{}])[0].get("finishReason")))
        raise AIError(f"Gemini no dio una respuesta válida ({reason or exc}).") from exc


def ask_claude(key: str, images: list[bytes], text: str) -> dict:
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(i).decode()}} for i in images]
    content.append({"type": "text", "text": text})
    body = json.dumps({
        "model": CLAUDE_MODEL, "max_tokens": 16000,
        "fallbacks": "default",
        "output_config": {"effort": "medium",
                          "format": {"type": "json_schema", "schema": claude_schema()}},
        "messages": [{"role": "user", "content": content}],
    }).encode()
    headers = {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2026-10-21",
               "anthropic-beta": "server-side-fallback-2026-07-01"}
    code, data = _post(CLAUDE_URL, body, headers, timeout=180)
    if code == 429:
        raise Quota("Claude: límite de uso alcanzado; intente más tarde.", daily=False)
    if code in (401, 403):
        raise BadKey("Claude: la clave no es válida o no tiene permisos.")
    if code != 200:
        raise AIError(f"Claude ({code}): {_err_text(data)}")
    j = _json(data)
    if j.get("stop_reason") == "refusal":
        raise AIError("Claude no quiso responder esta consulta.")
    if j.get("stop_reason") == "max_tokens":
        raise AIError("Claude: respuesta incompleta.")
    txt = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    try:
        return json.loads(txt)
    except ValueError as exc:
        raise AIError("Claude no dio una respuesta válida.") from exc


# ----------------------------------------------------------------- resultado
def normalize(db, section: str, raw: dict, provider: str) -> dict:
    """Respuesta de cualquier servicio -> {"provider", "at", "is_target", "advice", "notes",
    "candidates": [{"name", "scientific", "rank", "stage", "confidence", "features",
    "species_id"}]} (species_id: la especie del catálogo, si la hay)."""
    stages = scout.STAGES[section]
    out = []
    for cnd in (raw.get("candidates") or [])[:3]:
        if not isinstance(cnd, dict):
            continue
        name = (cnd.get("catalog_name") or cnd.get("common_name") or "").strip()
        sci = (cnd.get("scientific_name") or "").strip()
        g = scout_guide.find(section, name, sci)
        rank = (cnd.get("rank") or "").lower()
        exact = g and (scout_guide._norm(g["scientific"]) == scout_guide._norm(sci)
                       or scout_guide._norm(g["name"]) == scout_guide._norm(name))
        # La ficha del género entero solo vale si la IA llegó al género (o no dio nombre común).
        if g and (exact or rank in ("género", "genero", "familia") or not cnd.get("common_name")):
            name = g["name"]
            sci = sci or g["scientific"]
        sid = catalog_id(db, section, name, sci)
        stage = (cnd.get("stage") or "").strip()
        stage = next((s for s in stages if s.lower() == stage.lower()), "")
        try:
            conf = max(0.0, min(1.0, float(cnd.get("confidence") or 0)))
        except (TypeError, ValueError):
            conf = 0.0
        out.append({"name": name or sci or "?", "scientific": sci, "rank": cnd.get("rank") or "",
                    "stage": stage, "confidence": conf, "features": (cnd.get("features") or "").strip(),
                    "species_id": sid})
    out.sort(key=lambda c: -c["confidence"])
    return {"provider": provider, "at": _now(), "is_target": bool(raw.get("is_target", True)),
            "advice": (raw.get("photo_advice") or "").strip(), "notes": (raw.get("notes") or "").strip(),
            "candidates": out}


def catalog_id(db, section: str, name: str, sci: str) -> int | None:
    row = None
    if name:
        row = db.query_one("SELECT id FROM scout_species WHERE section=? AND unidentified=0 AND name=?",
                           (section, name))
    if not row and sci:
        row = db.query_one("SELECT id FROM scout_species WHERE section=? AND unidentified=0 AND "
                           "scientific=? COLLATE NOCASE", (section, sci))
    return row["id"] if row else None


# ----------------------------------------------------------------- trabajos
def job(db, record_id: int) -> dict | None:
    row = db.query_one("SELECT * FROM scout_ai WHERE record_id=?", (record_id,))
    if row:
        row["data"] = _json(row["result"].encode()) if row["result"] else {}
    return row


def queue(db, record_id: int) -> None:
    """Deja la captura para identificar (se procesa cuando haya señal)."""
    db.execute("INSERT INTO scout_ai(record_id, status, created_at, updated_at) VALUES (?, 'pending', ?, ?) "
               "ON CONFLICT(record_id) DO UPDATE SET status='pending', error='', updated_at=excluded.updated_at",
               (record_id, _now(), _now()))


def _set(db, record_id: int, **cols) -> None:
    cols["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in cols)
    db.execute(f"UPDATE scout_ai SET {sets} WHERE record_id=?", (*cols.values(), record_id))


def pending(db) -> list[int]:
    return [r["record_id"] for r in db.query("SELECT record_id FROM scout_ai WHERE status='pending' ORDER BY id")]


def identify(db, record_id: int, allow_claude: bool = False) -> dict:
    """Consulta los servicios en orden y guarda el resultado. Lanza Offline (queda
    pendiente), NeedsClaude (pedir permiso), Quota/BadKey/AIError (queda con error)."""
    rec = db.get_record(record_id)
    if not rec:
        raise AIError("La captura ya no existe.")
    section = rec["section"]
    if job(db, record_id) is None:
        queue(db, record_id)
    photos = [p for p in db.photos(record_id) if os.path.exists(p["path"])]
    if not photos:
        raise AIError("La captura no tiene fotos en el teléfono.")
    providers = chain(db, section)
    if not providers:
        need = "Pl@ntNet o Gemini" if section == "malezas" else "Gemini"
        _set(db, record_id, status="error", error=f"Falta la clave de {need} (Ajustes de IA).")
        raise AIError(f"Falta la clave de {need}: póngala en «Claves de IA».")
    images = prepare([p["path"] for p in photos])
    views = [p["view"] for p in photos[:MAX_PHOTOS]]
    keys = load_keys(db)
    text = None
    last_err: Exception | None = None
    weak: dict | None = None
    for prov in providers:
        if prov in usage(db)["out"]:
            continue
        if prov == "claude" and not allow_claude:
            if weak:
                break
            _set(db, record_id, status="claude",
                 error="Pl@ntNet y Gemini sin cuota hoy: falta autorizar Claude.")
            raise NeedsClaude("Pl@ntNet y Gemini no están disponibles hoy. ¿Usar Claude?")
        try:
            if prov == "plantnet":
                organs = [PLANTNET_ORGANS.get(v, "auto") for v in views]
                raw, remaining = ask_plantnet(keys[prov], images, organs)
                _count(db, prov, remaining)
                if remaining is not None and remaining <= 0:
                    _count(db, prov, 0, out=True)
                res = normalize(db, section, raw, prov)
                top = res["candidates"][0]["confidence"] if res["candidates"] else 0
                if top >= PLANTNET_MIN_SCORE:
                    return _done(db, record_id, res)
                weak = res if res["candidates"] else weak      # segunda opinión con Gemini
                continue
            text = text or prompt(section, rec, views)
            raw = ask_gemini(keys[prov], images, text) if prov == "gemini" else ask_claude(keys[prov], images, text)
            _count(db, prov)
            return _done(db, record_id, normalize(db, section, raw, prov))
        except Quota as exc:
            if exc.daily:
                _count(db, prov, out=True)
            last_err = exc
            if not exc.daily and prov != "plantnet":
                break
        except BadKey as exc:
            last_err = exc
        except Offline:
            _set(db, record_id, status="pending", error="Sin señal: se identifica cuando haya.")
            raise
    if weak:
        return _done(db, record_id, weak)
    msg = str(last_err) if last_err else "Ningún servicio disponible."
    status = "pending" if isinstance(last_err, Quota) else "error"
    _set(db, record_id, status=status, error=msg)
    raise last_err if last_err else AIError(msg)


def _done(db, record_id: int, res: dict) -> dict:
    _set(db, record_id, status="done", provider=res["provider"], result=json.dumps(res, ensure_ascii=False),
         error="")
    return res


def accept(db, record_id: int, cand: dict) -> int:
    """La captura es `cand`: pasa a esa especie (la crea en el catálogo si no estaba) y toma su
    estadio si no tenía. Devuelve el id de la especie."""
    rec = db.get_record(record_id)
    section = rec["section"]
    sid = cand.get("species_id") or catalog_id(db, section, cand["name"], cand["scientific"])
    if not sid:
        g = scout_guide.find(section, cand["name"], cand["scientific"])
        kind = (g or {}).get("kind") or ("plaga" if section == "plagas" else "")
        sid = db.add_species(section, cand["name"], cand["scientific"], kind=kind)
    if cand.get("stage") and not rec["stage"]:      # antes de mover: el estadio va en la carpeta
        db.execute("UPDATE scout_records SET stage=? WHERE id=?", (cand["stage"], record_id))
    db.move_record(record_id, sid)
    _set(db, record_id, accepted=cand["name"])
    db.log("update", "scout_ai_accept", record_id, f"{cand['name']} ({cand.get('confidence', 0):.0%})")
    return sid
