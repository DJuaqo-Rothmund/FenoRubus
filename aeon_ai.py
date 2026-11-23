"""
aeon_ai.py
==========
«Aeon IA»: la IA interna (detector de estructuras entrenado con las marcas de IA+,
tools/train_ia_v1.ipynb) en el teléfono. Mismo modelo y mismo resultado que la web
(web/aeon_ai.js): el .onnx más reciente de «AeonCrop/<módulo>/Entrenamiento IA/modelos/<versión>/».

* update_from_drive(sync): baja el modelo nuevo (si cambió) a la carpeta de datos.
* detect(path, keys): cajas sugeridas [{"c", "x", "y", "w", "h", "s": "aeon", "p"}] (0 a 1).
  En Android corre con ONNX Runtime (android/src/.../AeonDetector.java); en el PC, con
  onnxruntime de Python si está instalado.
"""
from __future__ import annotations

import json
import os

from platform_utils import data_subdir, is_android

CONF = 0.25          # puntaje mínimo para sugerir una caja
IOU = 0.5            # cajas de la misma clase que se tapan más que esto: queda una
MAX_BOXES = 150
TRAIN_DIR = "Entrenamiento IA"
MODELS_DIR = "modelos"


def _dir() -> str:
    return data_subdir("aeon_ia")


def current() -> dict | None:
    """Modelo bajado: {"meta", "path"} o None."""
    try:
        with open(os.path.join(_dir(), "model.json"), encoding="utf-8") as f:
            meta = json.load(f)
        path = os.path.join(_dir(), meta.get("_file") or "")
        return {"meta": meta, "path": path} if meta.get("_file") and os.path.exists(path) else None
    except (OSError, ValueError):
        return None


def update_from_drive(drive_sync, progress=None) -> dict | None:
    """Busca en Drive la versión más reciente (por «trained_at») y la baja si es nueva.
    drive_sync: sync_drive.DriveSync. Devuelve el modelo listo (current()) o None si no hay."""
    drive = drive_sync.drive
    train = drive._find_folder(TRAIN_DIR, drive.root_id())
    models = train and drive._find_folder(MODELS_DIR, train)
    if not models:
        return current()
    best = None
    for f in drive_sync._list(models):                   # una carpeta por versión
        try:
            files = drive_sync._list(f["id"])
        except Exception:  # noqa: BLE001 - no era una carpeta
            continue
        mj = next((x for x in files if x["name"] == "model.json"), None)
        ox = next((x for x in files if x["name"].endswith(".onnx")), None)
        if not mj or not ox:
            continue
        try:
            meta = json.loads(drive_sync._get(mj["id"]).decode("utf-8"))
        except ValueError:
            continue
        if best is None or (meta.get("trained_at") or "") > (best[0].get("trained_at") or ""):
            best = (meta, ox)
    if best is None:
        return current()
    meta, ox = best
    stamp = f"{ox['id']}/{ox.get('modifiedTime', '')}"
    have = current()
    if have and have["meta"].get("_stamp") == stamp:
        return have
    if progress:
        progress(f"Bajando Aeon IA {meta.get('version', '')}…")
    data = drive_sync._get(ox["id"])
    name = f"detector_{meta.get('version', 'v')}.onnx"
    tmp = os.path.join(_dir(), name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, os.path.join(_dir(), name))
    old = have and have["path"]
    meta = dict(meta, _file=name, _stamp=stamp)
    with open(os.path.join(_dir(), "model.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    if old and os.path.basename(old) != name:
        try:
            os.remove(old)
        except OSError:
            pass
    return current()


def _parse(text: str, classes: list[str], keys: list[str]) -> list[dict]:
    if text.startswith("ERROR:"):
        raise RuntimeError(text[6:].strip() or "error de Aeon IA")
    if text.startswith("T:"):              # tiempos del teléfono: modelo, foto, análisis (ms)
        head, _, text = text.partition("|")
        try:
            import perf
            for name, ms in zip(("aeon.cargar modelo", "aeon.preparar foto", "aeon.analizar"), head[2:].split(",")):
                perf.record(name, float(ms))
        except Exception:  # noqa: BLE001
            pass
    out = []
    for item in filter(None, text.split(";")):
        ci, p, x0, y0, x1, y1 = item.split(",")
        k = classes[int(float(ci))] if int(float(ci)) < len(classes) else None
        if k not in keys:
            continue
        x0, y0, x1, y1 = (float(v) for v in (x0, y0, x1, y1))
        r4 = lambda v: round(v, 4)  # noqa: E731
        out.append({"c": k, "x": r4(x0), "y": r4(y0), "w": r4(x1 - x0), "h": r4(y1 - y0), "s": "aeon",
                    "p": round(float(p), 2)})
    return out[:MAX_BOXES]


def _detect_numpy(model_path: str, image_path: str, imgsz: int) -> str:
    """Lo mismo que AeonDetector.java, con onnxruntime de Python (PC y pruebas)."""
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    W, H = im.size
    k = min(imgsz / W, imgsz / H)
    w, h = round(W * k), round(H * k)
    px, py = (imgsz - w) // 2, (imgsz - h) // 2
    canvas = Image.new("RGB", (imgsz, imgsz), (114, 114, 114))
    canvas.paste(im.resize((w, h), Image.BILINEAR), (px, py))
    x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    d = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]          # [4 + nc, N]
    if d.shape[0] > d.shape[1]:                                         # traspuesto: [N, 4 + nc]
        d = d.T
    scores = d[4:]
    ci = scores.argmax(0)
    best = scores.max(0)
    idx = np.where(best >= CONF)[0]
    cand = []
    for j in idx:
        cx, cy, bw, bh = d[:4, j]
        x0, y0 = max(0.0, (cx - bw / 2 - px) / k), max(0.0, (cy - bh / 2 - py) / k)
        x1, y1 = min(W, (cx + bw / 2 - px) / k), min(H, (cy + bh / 2 - py) / k)
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            cand.append((int(ci[j]), float(best[j]), x0, y0, x1, y1))
    cand.sort(key=lambda b: -b[1])

    def iou(a, b):
        ix = max(0.0, min(a[4], b[4]) - max(a[2], b[2]))
        iy = max(0.0, min(a[5], b[5]) - max(a[3], b[3]))
        inter = ix * iy
        u = (a[4] - a[2]) * (a[5] - a[3]) + (b[4] - b[2]) * (b[5] - b[3]) - inter
        return inter / u if u > 0 else 0.0
    keep = []
    for b in cand:
        if any(kb[0] == b[0] and iou(kb, b) > IOU for kb in keep):
            continue
        keep.append(b)
        if len(keep) >= MAX_BOXES:
            break
    return ";".join(f"{c},{p},{x0 / W},{y0 / H},{x1 / W},{y1 / H}" for c, p, x0, y0, x1, y1 in keep)


# ---- En Android, sin bloquear la interfaz (ver AeonDetector.start/poll) ----
_det = None


def _java():
    """La clase Java, cargada desde la interfaz (en otros hilos la app no siempre la encuentra)."""
    global _det
    if _det is None:
        from jnius import autoclass
        _det = autoclass("org.rubus.fenorubus.AeonDetector")
    return _det


def start_android(image_path: str, model: dict) -> bool:
    imgsz = int(model["meta"].get("imgsz") or 640)
    return bool(_java().start(model["path"], image_path, imgsz, float(CONF), float(IOU), MAX_BOXES))


def poll_android(model: dict, keys: list[str]):
    """None mientras analiza; después, las cajas (o error con RuntimeError)."""
    text = _java().poll()
    if text is None:
        return None
    return _parse(str(text), list(model["meta"].get("classes") or []), list(keys))


def stage_android() -> str:
    try:
        return str(_java().stage() or "")
    except Exception:  # noqa: BLE001
        return ""


def detect(image_path: str, keys: list[str], model: dict | None = None) -> list[dict]:
    """Cajas sugeridas para la foto. keys: clases que se usan hoy (las demás se ignoran)."""
    model = model or current()
    if not model:
        raise RuntimeError("aún no hay un modelo de Aeon IA en el teléfono (conecte Drive)")
    meta = model["meta"]
    imgsz = int(meta.get("imgsz") or 640)
    if is_android():
        from jnius import autoclass
        det = autoclass("org.rubus.fenorubus.AeonDetector")
        text = det.detect(model["path"], image_path, imgsz, float(CONF), float(IOU), MAX_BOXES)
    else:
        try:
            text = _detect_numpy(model["path"], image_path, imgsz)
        except ImportError as exc:
            raise RuntimeError("Aeon IA en el PC necesita «onnxruntime» (pip install onnxruntime)") from exc
    return _parse(str(text or ""), list(meta.get("classes") or []), list(keys))
