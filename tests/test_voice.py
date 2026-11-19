"""Dictar datos a una planilla: números de la transcripción, IA (simulada) y dictados guardados."""
import json
import os
import shutil
import subprocess

import pytest

import voice


def test_numbers_skip_codes():
    text = "T0R1, planta 1: 12 laterales, largo 45,5 cm; T3R2 entrenudo 3.5"
    assert [v for _a, _b, v in voice.numbers(text)] == ["1", "12", "45,5", "3.5"]


def test_clean_arrange():
    rows, cols = ["T0R1", "T1R1"], ["Planta 1 · Largo", "Planta 1 · N.º laterales"]
    raw = [{"row": "T0R1", "col": "Planta 1 · Largo", "value": "45"},
           {"row": "T0R1", "col": "Planta 1 · Largo", "value": "46"},          # repetida: se ignora
           {"row": "T9R9", "col": "Planta 1 · Largo", "value": "1"},           # fila inexistente
           {"row": "T1R1", "col": "Planta 1 · N.º laterales", "value": "doce"},  # no es número
           {"row": "T1R1", "col": "Planta 1 · N.º laterales", "value": "3, 5"}]
    assert voice.clean_arrange(raw, rows, cols) == [
        {"row": "T0R1", "col": "Planta 1 · Largo", "value": "45"},
        {"row": "T1R1", "col": "Planta 1 · N.º laterales", "value": "3,5"}]


def test_transcribe_and_arrange_with_gemini(monkeypatch, tmp_path):
    import scout_ai
    calls = []

    def fake(url, body, headers, timeout=90):
        b = json.loads(body)
        calls.append(b)
        parts = b["contents"][0]["parts"]
        if any("inline_data" in p for p in parts):
            out = {"text": "T0R1 planta 1: 12 laterales, largo 45."}
        else:
            out = [{"row": "T0R1", "col": "Planta 1 · Largo", "value": "45"}]
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]}).encode()

    monkeypatch.setattr(scout_ai, "_post", fake)
    p = tmp_path / "a.m4a"
    p.write_bytes(b"audio")
    text = voice.transcribe("k", str(p))
    assert "45" in text and calls[0]["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "audio/mp4"
    got = voice.arrange("k", text, ["T0R1"], ["Planta 1 · Largo"])
    assert got == [{"row": "T0R1", "col": "Planta 1 · Largo", "value": "45"}]
    enum = calls[1]["generationConfig"]["responseSchema"]["items"]["properties"]["row"]["enum"]
    assert enum == ["T0R1"]


def test_store(tmp_path):
    st = voice.Store(str(tmp_path))
    r = st.add("m1", "2026-11-16", str(tmp_path / "x.m4a"), 41.6)
    assert r["seconds"] == 42 and r["status"] == "pending"
    st.update(r["id"], status="done", text="hola 12", used=[0])
    assert st.for_measure("m1", "2026-11-16")[0]["used"] == [0] and st.for_measure("m1", "2026-11-23") == []
    st.delete(r["id"])
    assert st.all() == []


def test_web_voice_matches_python():
    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node.js")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = "T0R1, planta 1: 12 laterales, largo 45,5 cm; T3R2 entrenudo 3.5"
    code = ("import('./web/voice.js').then((V) => console.log(JSON.stringify({ n: V.numbers(process.argv[1]),"
            " p: V.TRANSCRIBE_PROMPT, a: V.arrangePrompt('x', ['A', 'B'], ['c']) })))")
    out = json.loads(subprocess.run([node, "--input-type=module", "-e", code, text], capture_output=True,
                                    text=True, cwd=root, check=True).stdout)
    assert [tuple(x) for x in out["n"]] == voice.numbers(text)
    assert out["p"] == voice.TRANSCRIBE_PROMPT and out["a"] == voice.arrange_prompt("x", ["A", "B"], ["c"])
