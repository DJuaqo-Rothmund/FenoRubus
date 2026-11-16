"""
scout_ai.py
===========
Identificación con IA online de las capturas de AeonScout (capa 3; la capa 1 es la guía
scout_guide). Puro Python (sin Kivy): urllib + Pillow.

Orden de servicios (lo eligió el usuario):

* MALEZAS: Pl@ntNet (gratis, hasta agotar su cuota diaria) → Gemini.
* PLAGAS y ENFERMEDADES: solo Gemini.

Todo gratis: Gemini se usa con su nivel gratuito y, si se agota la cuota de un modelo, se
pasa al siguiente (flash → flash-lite, cada uno con su propia cuota diaria).

Las claves (API keys) quedan en el teléfono, en «aeonscout/ia_claves.json»: nunca van a Drive
ni a la sincronización. La clave de Gemini se saca gratis en Google AI Studio.

Cada consulta queda en la tabla `scout_ai` (una fila por captura): pendiente (sin señal o sin
cuota: se reintenta sola), lista (con hasta 3 candidatas) o con error. Al aceptar una
candidata, la captura pasa a esa especie (y se suma al catálogo si no estaba): esas
confirmaciones son las etiquetas con que después se entrena la IA propia.

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
}
ORDER = {
    "malezas": ("plantnet", "gemini"),
    "plagas": ("gemini",),
    "enfermedades": ("gemini",),
}
PLANTNET_URL = "https://my-api.plantnet.org/v2/identify/all"
PLANTNET_DAILY = 500
PLANTNET_MIN_SCORE = .15        # por debajo, se pide una segunda opinión (Gemini)
# Modelos gratuitos de Gemini en orden (alias «latest»: siempre el vigente). Cada uno tiene su
# propia cuota diaria gratuita: si se agota uno, se usa el siguiente.
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite",
                 "gemini-flash-lite-latest", "gemini-2.0-flash")
GEMINI_OK_KEY = "scout_gemini_ok"        # último modelo que respondió: se prueba primero
GEMINI_LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_PHOTOS = 5
MAX_SIDE = 1280

SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_ai (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   INTEGER NOT NULL UNIQUE REFERENCES scout_records(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | done | error
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


def _get(url: str, headers: dict, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method="GET", headers=headers)
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


def gemini_order(db=None) -> list[str]:
    first = db.get_setting(GEMINI_OK_KEY) if db is not None else None
    return ([first] if first else []) + [m for m in GEMINI_MODELS if m != first]


def ask_gemini(key: str, images: list[bytes], text: str, models=GEMINI_MODELS, progress=None,
               db=None, schema: dict | None = None):
    """Prueba los modelos gratuitos en orden (el último que funcionó primero): si uno no
    existe, no acepta la consulta o no tiene cuota gratuita, pasa al siguiente."""
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(i).decode()}}
             for i in images]
    parts.append({"text": text})
    body = json.dumps({"contents": [{"role": "user", "parts": parts}],
                       "generationConfig": {"responseMimeType": "application/json",
                                            "responseSchema": schema or gemini_schema()}}).encode()
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    if db is not None and models is GEMINI_MODELS:
        models = gemini_order(db)
    quota_msg, errors = "", []
    for model in models:
        short = model.replace("gemini-", "")
        if progress:
            progress(f"Gemini ({short})")
        code, data = _post(GEMINI_URL.format(model=model), body, headers, timeout=60)
        msg = _err_text(data) if code != 200 else ""
        if code in (401, 403) or (code == 400 and "api key" in msg.lower()):
            raise BadKey(f"Gemini: la clave no es válida ({msg[:120]}).")
        if code == 429 and "limit: 0" in msg.replace("limit:0", "limit: 0"):
            errors.append(f"{short}: sin nivel gratuito")      # ese modelo no es gratis: no es «cuota agotada»
            continue
        if code == 429:
            quota_msg = msg
            errors.append(f"{short}: sin cuota")
            continue
        if code != 200:                 # modelo retirado (404) o que no acepta la consulta (400)
            errors.append(f"{short}: {code} {msg[:80]}")
            continue
        j = _json(data)
        try:
            txt = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
            out = json.loads(txt)
        except (KeyError, IndexError, ValueError) as exc:
            reason = ((j.get("promptFeedback") or {}).get("blockReason")
                      or ((j.get("candidates") or [{}])[0].get("finishReason")))
            raise AIError(f"Gemini no dio una respuesta válida ({reason or exc}).") from exc
        if db is not None:
            db.set_setting(GEMINI_OK_KEY, model)
        return out
    if quota_msg and len(errors) == sum(e.endswith("sin cuota") for e in errors):
        raise Quota("Gemini: sin cuota gratuita por ahora (" + quota_msg[:140] + ")",
                    daily="day" in quota_msg.lower())
    raise AIError("Gemini: ningún modelo respondió · " + " · ".join(errors)[:300])


def test_keys(db) -> list[str]:
    """Prueba rápida de las claves (Ajustes de IA › Probar claves): qué responde cada servicio."""
    keys, out = load_keys(db), []
    k = keys.get("gemini")
    if not k:
        out.append("Gemini: sin clave.")
    else:
        try:
            code, data = _get(f"{GEMINI_LIST_URL}?pageSize=200", {"x-goog-api-key": k})
            if code != 200:
                out.append(f"Gemini: la clave no sirve ({code}: {_err_text(data)[:160]})")
            else:
                names = [m.get("name", "").split("/")[-1] for m in _json(data).get("models", [])]
                flash = [n for n in names if "flash" in n]
                out.append("Gemini: clave válida. Modelos flash disponibles: " + (", ".join(flash[:8]) or "ninguno"))
                body = json.dumps({"contents": [{"parts": [{"text": "Responde solo: ok"}]}]}).encode()
                tried = [m for m in gemini_order(db) if m in names] + [n for n in flash if n not in GEMINI_MODELS][:3]
                for m in tried:
                    code, data = _post(GEMINI_URL.format(model=m), body,
                                       {"Content-Type": "application/json", "x-goog-api-key": k}, timeout=40)
                    if code == 200:
                        db.set_setting(GEMINI_OK_KEY, m)
                        u = usage(db)
                        if "gemini" in u["out"]:
                            u["out"].remove("gemini")
                            db.set_setting("scout_ai_usage", u)
                        out.append(f"Gemini: responde con {m}. Listo para identificar.")
                        break
                    out.append(f"Gemini {m}: {code} {_err_text(data)[:160]}")
                else:
                    out.append("Gemini: ningún modelo respondió (ver arriba).")
        except Offline as exc:
            out.append(f"Gemini: {exc}")
    k = keys.get("plantnet")
    if not k:
        out.append("Pl@ntNet: sin clave.")
    else:
        try:
            code, data = _get(f"https://my-api.plantnet.org/v2/projects?api-key={urllib.request.quote(k)}", {})
            out.append("Pl@ntNet: clave válida." if code == 200 else
                       f"Pl@ntNet: {code} {_err_text(data)[:160]}")
        except Offline as exc:
            out.append(f"Pl@ntNet: {exc}")
    u = usage(db)
    if u["out"]:
        out.append("Marcados sin cuota hoy: " + ", ".join(PROVIDERS.get(p, p) for p in u["out"]) +
                   " (se reintenta mañana; «Probar claves» los desbloquea si ya responden).")
    return out


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


def identify(db, record_id: int, progress=None, force: bool = False) -> dict:
    """Consulta los servicios en orden y guarda el resultado. Lanza Offline (queda
    pendiente), Quota/BadKey/AIError (queda con error)."""
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
        if prov in usage(db)["out"] and not force:     # a mano (force) se intenta igual
            continue
        try:
            if progress:
                progress(PROVIDERS[prov])
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
            raw = ask_gemini(keys[prov], images, text, progress=progress, db=db)
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


# ----------------------------------------------------------------- desde la web
WEB_FILE = "identificaciones-web.json"     # en «AeonCrop/AeonScout» (lo escribe AeonCrop Web)


def import_web(db, entries: list) -> int:
    """Resultados de IA hechos en la web (sobre fotos ya respaldadas): quedan en la captura
    como si se hubieran hecho aquí, para aceptarlos en la app. No pisa uno aceptado ni uno
    más nuevo. entries: [{"photo", "at", "provider", "result": {is_target, advice, notes,
    candidates: [{name, scientific, rank, stage, confidence, features}]}}]. Devuelve cuántos."""
    n = 0
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("photo"):
            continue
        name = os.path.basename(str(e["photo"]))
        row = next((r for r in db.query(
            "SELECT p.record_id, p.path, r.section FROM scout_photos p JOIN scout_records r ON r.id = p.record_id "
            "WHERE p.path LIKE ?", ("%" + name,)) if os.path.basename(r["path"]) == name), None)
        if not row:
            continue
        cur = job(db, row["record_id"])
        at = str(e.get("at") or "")
        if cur and (cur["accepted"] or (cur["status"] == "done" and str(cur["data"].get("at") or "") >= at)):
            continue
        raw = e.get("result") or {}
        cands = [{"catalog_name": c.get("name", ""), "common_name": c.get("name", ""),
                  "scientific_name": c.get("scientific", ""), "rank": c.get("rank", ""),
                  "stage": c.get("stage", ""), "confidence": c.get("confidence", 0),
                  "features": c.get("features", "")} for c in raw.get("candidates") or [] if isinstance(c, dict)]
        res = normalize(db, row["section"], {"is_target": raw.get("is_target", True), "candidates": cands,
                                             "photo_advice": raw.get("advice", ""), "notes": raw.get("notes", "")},
                        f"web · {PROVIDERS.get(e.get('provider'), e.get('provider') or 'IA')}")
        res["at"] = at or res["at"]
        if cur is None:
            queue(db, row["record_id"])
        _done(db, row["record_id"], res)
        n += 1
    return n


def accept(db, record_id: int, cand: dict) -> int:
    """La captura es `cand`: pasa a esa especie (la crea en el catálogo si no estaba) y toma su
    estadio si no tenía. Devuelve el id de la especie."""
    rec = db.get_record(record_id)
    section = rec["section"]
    # Por nombre: el id guardado en el resultado puede ser de otro teléfono (AeonScout compartido).
    sid = catalog_id(db, section, cand["name"], cand["scientific"])
    if not sid and cand.get("species_id"):
        sp = db.get_species(cand["species_id"])
        sid = sp["id"] if sp and sp["section"] == section and sp["name"] == cand["name"] else None
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
