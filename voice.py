"""
voice.py
========
Dictar datos a una planilla de mediciones:

1. Grabar audio (Android: MediaRecorder, AAC .m4a; con pausa y «modo bolsillo»).
2. Transcribir con Gemini (gratis, la clave de AeonScout): los números quedan con dígitos.
3. Ordenar: la persona toca un número y luego la celda, o la IA propone dónde va cada dato
   (queda en amarillo, por confirmar).

Los dictados se guardan en el teléfono (data/audio/dictados.json + los .m4a) y el audio se
respalda en Drive junto a las fotos de la semana. (= web/voice.js para la parte de la IA)
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
import uuid

from platform_utils import IS_ANDROID

MIME = {".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac", ".mp3": "audio/mpeg",
        ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
        ".webm": "audio/webm", ".flac": "audio/flac", ".3gp": "audio/3gpp", ".amr": "audio/amr"}
MAX_BYTES = 18 * 1024 * 1024          # Gemini acepta ~20 MB por consulta (≈ 1 h de dictado AAC)

NUM_RE = re.compile(r"(?<![A-Za-z\d])\d+(?:[.,]\d+)?(?![A-Za-z\d])")


def level_from_amp(amp: float) -> float:
    """Amplitud (0..32767, MediaRecorder.getMaxAmplitude) → 0..1 en decibeles: −50 dB = 0 y
    0 dB = 1. En escala lineal la voz normal quedaba casi en 0 (la onda se veía plana)."""
    import math
    if not amp or amp <= 0:
        return 0.0
    db = 20 * math.log10(min(amp, 32767) / 32767.0)
    return max(0.0, min(1.0, (db + 50) / 50))


def level_word(v: float) -> str:
    """Cómo suena: «bajo», «bien» o «alto» (saturando)."""
    return "bajo" if v < .38 else ("alto" if v > .93 else "bien")


class NotAvailable(RuntimeError):
    pass


# ------------------------------------------------------------------ grabación
def can_record() -> bool:
    return IS_ANDROID


class Recorder:
    """Grabadora (Android). start(path) · pause() · resume() · stop() · level() 0..1."""

    def __init__(self):
        self.rec = None
        self.path = ""
        self.paused = False

    def start(self, path: str) -> None:
        if not IS_ANDROID:
            raise NotAvailable("Grabar audio solo funciona en el teléfono (en la web: suba un archivo de audio).")
        from jnius import autoclass  # type: ignore
        MR = autoclass("android.media.MediaRecorder")
        AS = autoclass("android.media.MediaRecorder$AudioSource")
        OF = autoclass("android.media.MediaRecorder$OutputFormat")
        AE = autoclass("android.media.MediaRecorder$AudioEncoder")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        r = MR()
        r.setAudioSource(AS.MIC)
        r.setOutputFormat(OF.MPEG_4)
        r.setAudioEncoder(AE.AAC)
        r.setAudioChannels(1)
        r.setAudioSamplingRate(16000)       # voz: liviano y suficiente para transcribir
        r.setAudioEncodingBitRate(32000)
        r.setOutputFile(path)
        r.prepare()
        r.start()
        self.rec, self.path, self.paused = r, path, False

    def pause(self) -> None:
        if self.rec and not self.paused:
            self.rec.pause()
            self.paused = True

    def resume(self) -> None:
        if self.rec and self.paused:
            self.rec.resume()
            self.paused = False

    def level(self) -> float:
        """Volumen desde la última lectura, 0..1 en escala de decibeles (como un vúmetro)."""
        try:
            return level_from_amp(self.rec.getMaxAmplitude() if self.rec else 0)
        except Exception as exc:  # noqa: BLE001
            if not getattr(self, "_lvl_err", False):        # una vez al registro (para revisarlo)
                self._lvl_err = True
                print("nivel del micrófono:", exc)
            return 0.0

    def stop(self) -> str:
        r, self.rec = self.rec, None
        if r is not None:
            try:
                r.stop()
            finally:
                r.release()
        return self.path

    def cancel(self) -> None:
        path = self.path
        try:
            self.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            os.remove(path)
        except OSError:
            pass


class Player:
    """Reproductor del dictado (Android: MediaPlayer; en el computador, el de Kivy)."""

    def __init__(self, path: str):
        self.path, self.mp, self.snd = path, None, None

    def _ensure(self):
        if IS_ANDROID and self.mp is None:
            from jnius import autoclass  # type: ignore
            self.mp = autoclass("android.media.MediaPlayer")()
            self.mp.setDataSource(self.path)
            self.mp.prepare()
        elif not IS_ANDROID and self.snd is None:
            from kivy.core.audio import SoundLoader
            self.snd = SoundLoader.load(self.path)

    def toggle(self) -> bool:
        """Reproduce o pausa. Devuelve True si quedó sonando."""
        try:
            self._ensure()
        except Exception:  # noqa: BLE001
            return False
        if self.mp is not None:
            if self.mp.isPlaying():
                self.mp.pause()
                return False
            self.mp.start()
            return True
        if self.snd is not None:
            if self.snd.state == "play":
                self.snd.stop()
                return False
            self.snd.play()
            return True
        return False

    def position(self) -> tuple[float, float]:
        try:
            if self.mp is not None:
                return self.mp.getCurrentPosition() / 1000.0, self.mp.getDuration() / 1000.0
            if self.snd is not None:
                return self.snd.get_pos(), self.snd.length
        except Exception:  # noqa: BLE001
            pass
        return 0.0, 0.0

    def release(self):
        try:
            if self.mp is not None:
                self.mp.release()
            if self.snd is not None:
                self.snd.stop()
        except Exception:  # noqa: BLE001
            pass
        self.mp = self.snd = None


def set_brightness(level: float | None) -> None:
    """Modo bolsillo: brillo al mínimo (None = el del sistema). La app sigue en primer plano,
    así el micrófono sigue grabando (con la pantalla bloqueada Android lo silencia)."""
    if not IS_ANDROID:
        return
    try:
        from android.runnable import run_on_ui_thread  # type: ignore

        @run_on_ui_thread
        def _set():
            from jnius import autoclass  # type: ignore
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            win = act.getWindow()
            lp = win.getAttributes()
            lp.screenBrightness = -1.0 if level is None else float(level)
            win.setAttributes(lp)
            flag = autoclass("android.view.WindowManager$LayoutParams").FLAG_KEEP_SCREEN_ON
            if level is None:
                win.clearFlags(flag)
            else:
                win.addFlags(flag)
        _set()
    except Exception:  # noqa: BLE001
        pass


def ask_mic(callback) -> None:
    if not IS_ANDROID:
        callback(False)
        return
    from android.permissions import request_permissions  # type: ignore
    request_permissions(["android.permission.RECORD_AUDIO"], lambda _p, g: callback(all(g)))


# ------------------------------------------------------------------ dictados guardados
class Store:
    """data/audio/dictados.json: [{id, measure, week, path, created, seconds, text, used, status}]"""

    def __init__(self, data_dir: str):
        self.dir = os.path.join(data_dir, "audio")
        self.path = os.path.join(self.dir, "dictados.json")
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _save(self, items):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def new_path(self, stem: str) -> str:
        os.makedirs(self.dir, exist_ok=True)
        return os.path.join(self.dir, f"{stem}-{_dt.datetime.now():%Y%m%d-%H%M%S}.m4a")

    def add(self, measure: str, week: str, path: str, seconds: float = 0) -> dict:
        rec = {"id": uuid.uuid4().hex[:12], "measure": measure, "week": week, "path": path,
               "created": _dt.datetime.now().isoformat(timespec="seconds"), "seconds": round(seconds),
               "text": "", "used": [], "status": "pending"}
        with self._lock:
            items = self.all()
            items.append(rec)
            self._save(items)
        return rec

    def update(self, rec_id: str, **fields) -> dict | None:
        with self._lock:
            items = self.all()
            for it in items:
                if it["id"] == rec_id:
                    it.update(fields)
                    self._save(items)
                    return it
        return None

    def delete(self, rec_id: str) -> None:
        """Quita el dictado de la lista y borra su archivo de audio del teléfono."""
        with self._lock:
            all_ = self.all()
            gone = [i for i in all_ if i["id"] == rec_id]
            self._save([i for i in all_ if i["id"] != rec_id])
        for it in gone:
            try:
                os.remove(it.get("path") or "")
            except OSError:
                pass

    def for_measure(self, measure: str, week: str) -> list[dict]:
        return [i for i in self.all() if i["measure"] == measure and i["week"] == week]


# ------------------------------------------------------------------ IA (Gemini)
TRANSCRIBE_PROMPT = (
    "Transcribe en español este audio: es una persona dictando datos de un ensayo agrícola en terreno "
    "(tratamientos, repeticiones, plantas y mediciones). Escribe TODOS los números con dígitos (12, 45, "
    "3,5), con coma decimal. Escribe los códigos de parcela como T0R1, T3R2 (ej. «te cero erre uno» -> "
    "T0R1). No resumas ni inventes: transcribe lo que se dice, en orden.")
TRANSCRIBE_SCHEMA = {"type": "OBJECT", "required": ["text"], "properties": {"text": {"type": "STRING"}}}


def numbers(text: str) -> list[tuple[int, int, str]]:
    """Números de la transcripción: (inicio, fin, valor). Los códigos como T0R1 no cuentan."""
    return [(m.start(), m.end(), m.group(0)) for m in NUM_RE.finditer(text or "")]


def transcribe(key: str, path: str, db=None, progress=None) -> str:
    import scout_ai
    ext = os.path.splitext(path)[1].lower()
    mime = MIME.get(ext, "audio/mp4")
    if os.path.getsize(path) > MAX_BYTES:
        raise scout_ai.AIError("El audio es muy largo para transcribirlo de una vez (máx. ~18 MB): divídalo.")
    with open(path, "rb") as f:
        data = f.read()
    out = scout_ai.ask_gemini(key, [(data, mime)], TRANSCRIBE_PROMPT, progress=progress, db=db,
                              schema=TRANSCRIBE_SCHEMA)
    return str((out or {}).get("text") or "").strip()


def arrange_prompt(text: str, rows: list[str], cols: list[str]) -> str:
    return (
        "Transcripción de un dictado de datos de terreno:\n«" + text + "»\n\n"
        "Ubica cada dato dictado en la planilla. Filas posibles (exactas): " + " | ".join(rows) + ".\n"
        "Columnas posibles (exactas): " + " | ".join(cols) + ".\n"
        "Reglas: usa SOLO valores que se dijeron (con dígitos, coma decimal); si el dictado dice «planta 2» "
        "y hay columnas «Planta 2 · …», úsalas; si no se puede saber la fila o la columna de un número, no "
        "lo incluyas. Entrega una lista de {row, col, value}.")


def arrange_schema(rows: list[str], cols: list[str]) -> dict:
    return {"type": "ARRAY", "items": {"type": "OBJECT", "required": ["row", "col", "value"], "properties": {
        "row": {"type": "STRING", "enum": list(rows)}, "col": {"type": "STRING", "enum": list(cols)},
        "value": {"type": "STRING"}}}}


def arrange(key: str, text: str, rows: list[str], cols: list[str], db=None, progress=None) -> list[dict]:
    """La IA propone dónde va cada dato: [{"row", "col", "value"}] (filas/columnas exactas)."""
    import scout_ai
    if not rows or not cols:
        return []
    raw = scout_ai.ask_gemini(key, [], arrange_prompt(text, rows, cols), progress=progress, db=db,
                              schema=arrange_schema(rows, cols))
    return clean_arrange(raw, rows, cols)


def clean_arrange(raw, rows, cols) -> list[dict]:
    out, seen = [], set()
    for it in raw if isinstance(raw, list) else []:
        try:
            r, c_, v = str(it["row"]), str(it["col"]), str(it["value"]).strip()
        except (KeyError, TypeError):
            continue
        if r not in rows or c_ not in cols or not NUM_RE.fullmatch(v.replace(" ", "")) or (r, c_) in seen:
            continue
        seen.add((r, c_))
        out.append({"row": r, "col": c_, "value": v.replace(" ", "")})
    return out
