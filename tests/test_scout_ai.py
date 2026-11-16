"""Guía de AeonScout e identificación con IA (servicios simulados, sin red)."""
import json
import os

import pytest
from PIL import Image

import scout
import scout_ai
import scout_guide


@pytest.fixture()
def db(tmp_path):
    d = scout.ScoutDB(str(tmp_path))
    yield d
    d.close() if hasattr(d, "close") else None


def _record(db, tmp_path, section="malezas", species=None, crop="cranberry"):
    sid = species or db.new_unidentified(section)
    rec = db.add_record(section, sid, crop=crop)
    for i, view in enumerate(("Planta completa", "Hoja (haz)")):
        path = os.path.join(db.photo_dir(section), f"20261115_MZ_{db.get_species(sid)['name']}_{i}.jpg")
        Image.new("RGB", (2000, 1500), (40, 120 + i, 60)).save(path)
        db.add_photo(rec, path, view=view)
    return rec


def test_guide_seed_and_find(db):
    names = {s["name"] for s in db.species("plagas", unidentified=False)}
    assert {"Gorgojo negro de la vid", "Burrito de bandas blancas", "Pololo (Sericoides)"} <= names
    assert scout_guide.find("plagas", scientific="Otiorhynchus sulcatus")["name"] == "Gorgojo negro de la vid"
    assert scout_guide.find("plagas", scientific="Sericoides germaini")["name"] == "Pololo (Sericoides)"
    assert scout_guide.find("malezas", scientific="Rumex acetosa")["name"] == "Romaza"
    cran = {s["name"] for s in scout_guide.species_for("malezas", "cranberry")}
    assert "Junquillo" in cran and "Maicillo" not in cran
    assert "[b]Cómo reconocerla:[/b]" in scout_guide.ficha_text(scout_guide.SPECIES[0])
    # no se duplica al reabrir
    n = len(db.species("plagas"))
    scout_guide.seed(db)
    assert len(db.species("plagas")) == n


def test_keys_stay_local(db):
    scout_ai.save_keys(db, gemini=" abc ", plantnet="")
    assert scout_ai.load_keys(db) == {"gemini": "abc"}
    assert scout_ai.chain(db, "malezas") == ["gemini"]
    assert scout_ai.chain(db, "plagas") == ["gemini"]


def _fake(responses, calls):
    def post(url, body, headers, timeout=90):
        calls.append((url, headers, body))
        for key, (code, payload) in responses.items():
            if key in url:
                return code, json.dumps(payload).encode()
        raise AssertionError(url)
    return post


def _gemini_ok(name="Junquillo", sci="Juncus effusus", conf=.8):
    txt = json.dumps({"is_target": True, "photo_advice": "Acerque la inflorescencia.", "notes": "",
                      "candidates": [{"common_name": name, "scientific_name": sci, "rank": "especie",
                                      "catalog_name": "", "stage": "vegetativo / roseta",
                                      "confidence": conf, "features": "Tallos cilíndricos sin nudos"}]})
    return 200, {"candidates": [{"content": {"parts": [{"text": txt}]}}]}


def test_plantnet_weak_then_gemini(db, tmp_path, monkeypatch):
    scout_ai.save_keys(db, plantnet="pn", gemini="gm")
    rec = _record(db, tmp_path)
    calls = []
    weak = {"results": [{"score": .05, "species": {"scientificNameWithoutAuthor": "Juncus bufonius",
                                                   "family": {"scientificNameWithoutAuthor": "Juncaceae"}}}],
            "remainingIdentificationRequests": 499}
    monkeypatch.setattr(scout_ai, "_post", _fake({"plantnet": (200, weak), "generativelanguage": _gemini_ok()},
                                                  calls))
    res = scout_ai.identify(db, rec)
    assert res["provider"] == "gemini"
    c = res["candidates"][0]
    assert c["name"] == "Junquillo" and c["stage"] == "Vegetativo / roseta"
    assert c["species_id"] == scout_ai.catalog_id(db, "malezas", "Junquillo", "")
    assert len(calls) == 2 and b"name=\"organs\"\r\n\r\nhabit" in calls[0][2]
    assert calls[1][1]["x-goog-api-key"] == "gm"
    assert scout_ai.usage(db)["remaining"]["plantnet"] == 499
    assert scout_ai.job(db, rec)["status"] == "done"


def test_gemini_free_models_and_quota(db, tmp_path, monkeypatch):
    scout_ai.save_keys(db, plantnet="pn", gemini="gm")
    calls = []

    def post(url, body, headers, timeout=90):
        calls.append(url)
        if "lite" not in url:      # los modelos no-lite sin cuota: pasa al lite
            return 429, json.dumps({"error": {"message": "Quota exceeded per minute"}}).encode()
        if "lite" in url:
            code, payload = _gemini_ok("Gorgojo negro de la vid", "Otiorhynchus sulcatus")
            return code, json.dumps(payload).encode()
        raise AssertionError(url)
    monkeypatch.setattr(scout_ai, "_post", post)
    rec = _record(db, tmp_path, "plagas")
    res = scout_ai.identify(db, rec)
    assert res["candidates"][0]["name"] == "Gorgojo negro de la vid"
    assert [u.split("/models/")[1].split(":")[0] for u in calls] == ["gemini-2.5-flash", "gemini-flash-latest",
                                                                       "gemini-2.5-flash-lite"]
    assert db.get_setting(scout_ai.GEMINI_OK_KEY) == "gemini-2.5-flash-lite"      # la próxima, primero
    # todos sin cuota diaria: queda pendiente y Gemini se marca agotado hoy
    monkeypatch.setattr(scout_ai, "_post", _fake({"generativelanguage": (429, {"error": {
        "message": "Quota exceeded for GenerateRequestsPerDayPerProjectPerModel"}})}, []))
    rec2 = _record(db, tmp_path, "plagas")
    with pytest.raises(scout_ai.Quota):
        scout_ai.identify(db, rec2)
    assert "gemini" in scout_ai.usage(db)["out"] and scout_ai.pending(db) == [rec2]
    assert "claude" not in scout_ai.PROVIDERS and scout_ai.ORDER["malezas"] == ("plantnet", "gemini")


def test_offline_stays_pending(db, tmp_path, monkeypatch):
    scout_ai.save_keys(db, gemini="gm")
    rec = _record(db, tmp_path, "enfermedades")

    def off(*_a, **_k):
        raise scout_ai.Offline("sin red")
    monkeypatch.setattr(scout_ai, "_post", off)
    with pytest.raises(scout_ai.Offline):
        scout_ai.identify(db, rec)
    assert scout_ai.pending(db) == [rec]


def test_accept_moves_record(db, tmp_path):
    rec = _record(db, tmp_path)
    ni = db.get_record(rec)["species_id"]
    scout_ai.queue(db, rec)
    sid = scout_ai.accept(db, rec, {"name": "Hierba nueva", "scientific": "Herba nova", "stage": "Floración",
                                    "confidence": .7, "species_id": None})
    r = db.get_record(rec)
    assert r["species_id"] == sid and r["stage"] == "Floración"
    assert not db.get_species(ni)["active"]                      # la NI vacía se oculta
    assert all("Hierba-nueva" in os.path.basename(p["path"]) for p in db.photos(rec))
    names = {q["name"] for q in db.query("SELECT name FROM drive_queue")}
    assert all(n.startswith("Malezas/Hierba nueva/Floración/") for n in names)
    assert scout_ai.job(db, rec)["accepted"] == "Hierba nueva"


def test_normalize_keeps_unlisted_species(db):
    raw = {"is_target": True, "candidates": [
        {"common_name": "Acedera", "scientific_name": "Rumex acetosa", "rank": "especie", "catalog_name": "",
         "stage": "", "confidence": .4, "features": ""},
        {"common_name": "", "scientific_name": "Juncus effusus", "rank": "especie", "catalog_name": "",
         "stage": "", "confidence": .3, "features": ""}]}
    res = scout_ai.normalize(db, "malezas", raw, "gemini")
    assert res["candidates"][0]["name"] == "Acedera" and res["candidates"][0]["species_id"] is None
    assert res["candidates"][1]["name"] == "Junquillo" and res["candidates"][1]["species_id"]


def test_gemini_model_without_free_tier_is_skipped(db, tmp_path, monkeypatch):
    scout_ai.save_keys(db, gemini="gm")

    def post(url, body, headers, timeout=90):
        if "2.5-flash:" in url:
            return 429, json.dumps({"error": {"message": "Quota exceeded for metric: "
                                              "generate_content_free_tier_requests, limit: 0, model: x PerDay"}}).encode()
        code, payload = _gemini_ok("Trips", "Frankliniella occidentalis")
        return code, json.dumps(payload).encode()
    monkeypatch.setattr(scout_ai, "_post", post)
    rec = _record(db, tmp_path, "plagas")
    assert scout_ai.identify(db, rec)["candidates"][0]["name"] == "Trips"
    assert "gemini" not in scout_ai.usage(db)["out"]       # no se marca «sin cuota» todo el día


def test_import_web_results(db, tmp_path):
    rec = _record(db, tmp_path)
    photo = os.path.basename(db.photos(rec)[0]["path"])
    entry = {"photo": photo, "at": "2026-11-16T10:00:00", "provider": "gemini",
             "result": {"is_target": True, "advice": "Saque la flor.", "notes": "",
                        "candidates": [{"name": "Junquillo", "scientific": "Juncus effusus", "rank": "especie",
                                        "stage": "Floración", "confidence": .7, "features": "tallos"}]}}
    assert scout_ai.import_web(db, [entry, {"photo": "otra.jpg"}]) == 1
    j = scout_ai.job(db, rec)
    assert j["status"] == "done" and j["provider"] == "web · Gemini"
    c = j["data"]["candidates"][0]
    assert c["species_id"] == scout_ai.catalog_id(db, "malezas", "Junquillo", "") and c["stage"] == "Floración"
    assert scout_ai.import_web(db, [entry]) == 0                  # el mismo: no se repite
    scout_ai.accept(db, rec, c)
    assert scout_ai.import_web(db, [dict(entry, at="2026-11-17T00:00:00")]) == 0   # ya aceptada


def test_web_scout_ai_matches_app(db, tmp_path):
    """web/scout_ai.js: misma ficha, misma consulta y mismo resultado normalizado que la app."""
    import importlib.util
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node.js")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("mwd", os.path.join(root, "tools", "make_web_data.py"))
    mwd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mwd)
    mwd.scout_data()
    finds = [["plagas", "", "Otiorhynchus sulcatus"], ["malezas", "", "Rumex acetosa"], ["malezas", "Junquillo", ""],
             ["malezas", "", "Juncus bufonius"], ["plagas", "Nada", "Xus yus"]]
    recs = [["malezas", {"crop": "cranberry", "organ": "Hoja", "notes": "en el dique"}, ["Planta completa", "Hoja (haz)"]],
            ["plagas", {"crop": "", "organ": "", "notes": ""}, []],
            ["enfermedades", {"crop": "frambuesa", "organ": "Fruto", "notes": ""}, ["", "Detalle de la lesión"]]]
    raw = {"is_target": True, "photo_advice": " Acerque ", "notes": "", "candidates": [
        {"common_name": "Acedera", "scientific_name": "Rumex acetosa", "rank": "especie", "catalog_name": "",
         "stage": "floración", "confidence": .4, "features": "x"},
        {"common_name": "", "scientific_name": "Juncus effusus", "rank": "especie", "catalog_name": "",
         "stage": "", "confidence": 1.3, "features": ""}]}
    pn = {"results": [{"score": .61, "species": {"scientificNameWithoutAuthor": "Juncus effusus", "commonNames": ["junco"],
                                                 "family": {"scientificNameWithoutAuthor": "Juncaceae"}}}]}
    src, out = tmp_path / "in.json", tmp_path / "out.json"
    src.write_text(json.dumps({"finds": finds, "prompts": recs, "norm": [["malezas", raw, "gemini"]], "plantnet": pn}))
    subprocess.run([node, os.path.join(root, "tests", "web_scout.mjs"), str(src), str(out)], check=True, cwd=root)
    res = json.loads(out.read_text())
    assert res["finds"] == [(scout_guide.find(*f) or {}).get("name") for f in finds]
    assert res["prompts"] == [scout_ai.prompt(sec, r, v) for sec, r, v in recs]
    py = scout_ai.normalize(db, "malezas", raw, "gemini")
    for c in py["candidates"]:
        c.pop("species_id")
    assert res["norm"][0]["candidates"] == py["candidates"] and res["norm"][0]["advice"] == "Acerque"
    assert res["plantnet"]["candidates"][0]["scientific_name"] == "Juncus effusus"
    assert res["merged"] == [{"photo": "a"}, {"photo": "b", "at": 2}]
