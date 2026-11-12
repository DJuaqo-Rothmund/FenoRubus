"""Versión web (web/core.js): misma lógica que la app y paquetes compatibles en ambos sentidos."""
import datetime as dt
import json
import os
import shutil
import subprocess

import pytest

import phenology as ph
import sync
from database import Database

NODE = shutil.which("node")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(NODE is None, reason="sin Node.js")


def _node(mode, data, tmp_path):
    src, out = tmp_path / f"{mode}_in.json", tmp_path / f"{mode}_out.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    subprocess.run([NODE, os.path.join(ROOT, "tests", "web_roundtrip.mjs"), mode, str(src), str(out)],
                   check=True, cwd=ROOT)
    return json.loads(out.read_text(encoding="utf-8"))


def test_web_helpers_match_python(tmp_path):
    dates = ["2026-03-29", "2026-03-30", "2026-04-01", "2026-10-16", "2026-12-28", "2027-01-04",
             "2027-03-31", "2020-01-01", "2050-12-31", "2026-06-07"]
    vs = [{"name": "Meeker", "code": "MEE"}, {"name": "Código 11", "code": ""},
          {"name": "Equipo de riego 1, sector 2", "cultivar": "Tulameen", "sector": 2, "irrigation": 1,
           "plant_year": 2019, "code": ""}]
    res = _node("helpers", {"dates": dates, "varieties": vs}, tmp_path)
    for d, r in zip(dates, res["dates"]):
        day = dt.date.fromisoformat(d)
        monday = day - dt.timedelta(days=day.weekday())
        assert r["season"] == ph.season_of(day), d
        assert tuple(r["iso"]) == ph.iso_week(day), d
        assert r["monday"] == monday.isoformat()
        assert r["label"] == ph.week_label(day)
        from drive_backup import DriveBackup
        assert r["folder"] == DriveBackup.week_folder(d)
    assert res["names"] == [ph.photo_basename(v, "2026-10-12", "detail", 2, trial="AM") for v in vs]
    assert res["units"] == [[ph.unit_main(v), ph.unit_place(v)] for v in vs]
    assert res["codes"] == [ph.code_str(c) for c in (7, 65, 891)]
    from reporter import seq_color
    assert res["seq"] == [list(seq_color(c)) for c in (None, 7, 31, 65, 891, 99)]
    import ast
    src = open(os.path.join(ROOT, "ui", "sector_map.py"), encoding="utf-8").read()   # sin Kivy
    mod = ast.parse(src)
    ns = {}
    keep = [n for n in mod.body if isinstance(n, (ast.Assign, ast.FunctionDef))
            and getattr(n, "name", None) in (None, "_hex", "sector_color")
            and (not isinstance(n, ast.Assign) or n.targets[0].id in ("EQUIPO_RAMP", "EMPTY", "N_SECTORS"))]
    exec(compile(ast.Module(body=keep, type_ignores=[]), "sector_map", "exec"), ns)
    for (e, sct, f), (col, light) in zip([(1, 1, False), (2, 5, False), (3, 10, True), (4, 3, False)], res["sect"]):
        rgba, py_light = ns["sector_color"](e, sct, f)
        assert col == "#" + "".join(f"{round(x * 255):02x}" for x in rgba[:3]) and light == py_light


def test_web_reads_app_bundle_and_app_applies_web_changes(tmp_path):
    data = str(tmp_path / "cel")
    db = Database(os.path.join(data, "AM.sqlite3"), code="AM")
    db.set_season_start(2026, dt.date(2026, 9, 7))
    vid = db.add_variety("Variedad Web", code="VW")
    w = db.week_for_date(dt.date(2026, 10, 12))
    db.update_observation(db.get_or_create_observation(vid, w["id"])["id"], bbch_code=61, bbch_label="x")
    bundle = sync.export_changes(db, data)
    sync.mark_exported(db, bundle)
    res = _node("roundtrip", bundle, tmp_path)
    assert res["had"] == 61 and res["varieties"] == len(db.list_varieties())
    stats = sync.apply_changes(db, res["bundle"], data, week_for_date=db.week_for_date)
    # 4 cambios de la web + la semana del 12/10, que la web también manda porque las
    # semanas creadas solas en la app no viajan.
    assert stats["applied"] == 5
    obs = db.get_observation(vid, w["id"])
    assert obs["bbch_code"] == 65 and obs["notes"] == "desde la web" and obs["bbch_label"] == "Final de la floración"
    nov = db.query_one("SELECT * FROM sampling_weeks WHERE start_date='2026-11-02'")
    assert nov is not None and nov["season"] == 2026            # semana nueva creada por la web
    o2 = db.get_observation(vid, nov["id"])
    assert o2["bbch_code"] == 891
    p = db.query_one("SELECT * FROM photos WHERE observation_id=?", (o2["id"],))
    assert p["path"].endswith(os.path.join("photos", "T2026", "web", "20261102-AM-GlwD.jpg")) and p["is_primary"] == 1
    assert stats["missing_files"] == [p["path"]]                  # el celular la baja de Drive
    db.close()


def test_web_stats_match_trial_stats(tmp_path):
    import random
    import trial_stats as st
    rnd = random.Random(7)
    cases = []
    for k in range(25):
        nt, nr = rnd.randint(2, 6), rnd.randint(2, 4)
        shift = rnd.choice([0, 0.5, 3, 8])
        vals = [(t, r, round(50 + t * shift + rnd.gauss(0, 2), 2)) for t in range(1, nt + 1) for r in range(1, nr + 1)
                if not (k % 4 == 0 and rnd.random() < .2)]               # a veces faltan parcelas
        cases.append(vals)
    cases.append([(1, 1, 5), (1, 2, 5), (2, 1, 5), (2, 2, 5)])          # sin varianza
    cases.append([(1, 1, 5)])                                          # un solo tratamiento
    vals = [[1, 2, 3.5], [7], [], [2, None, 4]]
    res = _node("stats", {"cases": cases, "vals": vals}, tmp_path)
    for case, js in zip(cases, res["res"]):
        py = st.anova({(t, r): v for t, r, v in case})
        if py is None:
            assert js is None
            continue
        assert js["design"] == py["design"] and tuple(js["df"]) == py["df"]
        assert (js["f"] == "inf") == (py["f"] == float("inf"))
        if js["f"] != "inf":
            assert js["f"] == pytest.approx(py["f"], rel=1e-9, abs=1e-12)
        assert js["p"] == pytest.approx(py["p"], rel=1e-7, abs=1e-12)
        assert (js["lsd"] is None) == (py["lsd"] is None)
        if py["lsd"] is not None:
            assert js["lsd"] == pytest.approx(py["lsd"], rel=1e-6)
        assert {int(k): v for k, v in js["letters"].items()} == py["letters"]
    for v, (m, se) in zip(vals, res["ms"]):
        pm, pse = st.mean_se(v)
        assert (m is None) == (pm is None) and (pm is None or m == pytest.approx(pm))
        assert (se is None) == (pse is None) and (pse is None or se == pytest.approx(pse))
    assert res["tcrit"] == pytest.approx([st.t_crit(d) for d in (2, 6, 20)], rel=1e-9)


def test_web_settings_changes_apply_in_app(tmp_path):
    """Ajustes hechos en la web (unidad de predio, variedad, ensayo de tratamientos, nombre de
    tratamiento y primera semana) quedan en la app igual que si se hubieran hecho ahí."""
    db = Database(str(tmp_path / "app" / "AM.sqlite3"), code="AM")
    db.add_variety("Variedad Web", code="VW")
    bundle = sync.export_changes(db, str(tmp_path / "app"))
    res = _node("settings", bundle, tmp_path)
    assert res["unit"] == "Equipo de riego 1, sector 2"
    assert res["errors"][0].startswith("Ya existe «Equipo de riego 1, sector 2» con la variedad")
    assert res["errors"][1] == "Ya existe «Variedad Web»."
    assert res["counts"] == [6, 0, 2]
    sync.apply_changes(db, res["bundle"], str(tmp_path / "app"), week_for_date=db.week_for_date)
    u = db.query_one("SELECT * FROM varieties WHERE name='Equipo de riego 1, sector 2'")
    assert (u["cultivar"], u["sector"], u["irrigation"], u["plant_year"], u["code"]) == ("Tulameen", 2, 1, 2019, "TU")
    v = db.query_one("SELECT * FROM varieties WHERE name='Variedad Web'")
    assert (v["code"], v["notes"]) == ("VWX", "editada en la web")
    assert db.trial_size() == (2, 2)
    trts = db.list_treatments()
    assert [t["label"] for t in trts] == ["T1 · Testigo", "T2"]
    assert [p["name"] for p in trts[0]["parcels"]] == ["T1R1", "T1R2"] and trts[0]["variety"] == "Heritage"
    assert db.query_one("SELECT active FROM varieties WHERE name='T3R2'")["active"] == 0
    assert db.first_week_date(2026) == dt.date(2026, 9, 7)


def test_web_exif_gps_matches_python(tmp_path):
    """La web lee el GPS de la cámara (EXIF) igual que geo.exif_gps."""
    from PIL import Image
    import geo
    files = []
    for k, (lat, lon) in enumerate([(-33.4495, -70.6625), (40.5, 3.25), (None, None)]):
        img = Image.new("RGB", (16, 16), "green")
        exif = Image.Exif()
        if lat is not None:
            def dms(x):
                x = abs(x)
                d, m = int(x), int((x - int(x)) * 60)
                return (d, m, round(((x - d) * 60 - m) * 60, 4))
            exif[0x8825] = {1: "S" if lat < 0 else "N", 2: dms(lat), 3: "W" if lon < 0 else "E", 4: dms(lon)}
        path = tmp_path / f"g{k}.jpg"
        img.save(path, exif=exif)
        files.append(str(path))
    res = _node("exif", {"files": files}, tmp_path)
    for f, r in zip(files, res):
        py = geo.exif_gps(f)
        assert (r is None) == (py is None)
        if py:
            assert abs(r[0] - py[0]) < 1e-6 and abs(r[1] - py[1]) < 1e-6
    assert res[0][0] < 0 and res[0][1] < 0 and res[2] is None


def test_aeoncrop_web_t0_units_and_week_move_apply_in_app(tmp_path):
    """AeonCrop Web: ensayo con T0 (T0…T2), fenología unificada con dos puntos por tratamiento
    y mover una semana a otra (renombra fotos y junta con lo que ya había): la app lo recibe
    igual que si se hubiera hecho ahí."""
    ws = {"profile": "id", "kind": "tratamientos", "name": "Urea", "code": "AUF"}
    data = tmp_path / "app"
    db = Database(str(data / "AUF.sqlite3"), code="AUF", workspace=ws, seed=False)
    v = db.add_variety("Meeker", code="MEE")
    w1 = db.week_for_date(dt.date(2026, 10, 12))
    w2 = db.week_for_date(dt.date(2026, 10, 19))
    o1 = db.get_or_create_observation(v, w1["id"])
    db.update_observation(o1["id"], bbch_code=61, notes="semana equivocada")
    photo = data / "photos" / "20261012-AUF-MEEG.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"jpg")
    db.add_photo(o1["id"], "canopy", str(photo))
    o2 = db.get_or_create_observation(v, w2["id"])
    db.update_observation(o2["id"], bbch_code=65)                 # el destino ya tiene datos
    bundle = sync.export_changes(db, str(data))
    res = _node("lab", bundle, tmp_path)
    assert res["trts"] == [0, 1, 2]
    assert res["parcels"][:2] == ["T0R1", "T0R2"] and "T2R2" in res["parcels"] and "T3R1" not in res["parcels"]
    assert res["units"] == ["T0 · Caña gruesa", "T0 · Caña delgada", "T1 · Caña gruesa", "T1 · Caña delgada",
                            "T2 · Caña gruesa", "T2 · Caña delgada"]
    assert res["renames"] == [["20261012-AUF-MEEG.jpg", "20261019-AUF-MEEG.jpg", "photo"]]
    assert res["moved"] == {"records": 0, "merged": 1, "photos": 1, "entries": 0}
    sync.apply_changes(db, res["bundle"], str(data), week_for_date=db.week_for_date)
    assert db.trial_has_t0 and db.trial_size() == (3, 2) and db.trial_nums() == [0, 1, 2]
    assert db.unified_pheno and db.pheno_config() == {"scope": "treatment", "names": ["Caña gruesa", "Caña delgada"],
                                                    "counts": {}}
    names = [u["name"] for u in db.pheno_units()]
    assert names == res["units"]
    assert [u["name"] for u in db.sync_pheno_units()] == names          # la app no cambia nada
    assert not db.query("SELECT 1 FROM observations WHERE week_id=?", (w1["id"],))
    o = db.query_one("SELECT * FROM observations WHERE week_id=? AND variety_id=?", (w2["id"], v))
    assert o["bbch_code"] == 65 and "semana equivocada" in o["notes"] and "BBCH 61" in o["notes"]
    p = db.query_one("SELECT * FROM photos")
    assert p["observation_id"] == o["id"] and os.path.basename(p["path"]) == "20261019-AUF-MEEG.jpg"


def test_web_notebook_sheets_and_pasted_photos_roundtrip(tmp_path):
    """Cuaderno en la web: lee las hojas y el lugar de las fotos de la app; lo que cambia
    (otra hoja, hoja nueva, foto movida a otra hoja, foto nueva pegada) llega a la app."""
    data = tmp_path / "app"
    db = Database(str(data / "AM.sqlite3"), code="AM", workspace={"profile": "predio", "name": "El Amanecer",
                                                                 "code": "AM"}, seed=False)
    e = db.note_for_day("2026-11-20", create=True)
    db.save_note_page(e["id"], 0, "hoja uno", "")
    db.add_note_page(e["id"])
    db.save_note_page(e["id"], 1, "hoja dos", "")
    photo = data / "photos" / "cuaderno" / "20261120-AM-cuaderno.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"jpg")
    pid = db.add_note_photo(e["id"], str(photo), page=1, place={"x": 7, "y": 8, "w": 9, "r": 12})
    res = _node("notebook", sync.export_changes(db, str(data)), tmp_path)
    assert res["pages"] == ["hoja uno", "hoja dos"]
    assert res["place"] == {"x": 7, "y": 8, "w": 9, "r": 12}
    sync.apply_changes(db, res["bundle"], str(data), week_for_date=db.week_for_date)
    e = db.note_for_day("2026-11-20")
    assert [p["text"] for p in db.note_pages(e)] == ["hoja uno", "hoja dos desde la web", "hoja tres nueva"]
    ph = {p["id"]: p for p in e["photos"]}
    assert ph[pid]["page"] == 2 and json.loads(ph[pid]["place"]) == {"x": 3, "y": 4, "w": 5, "r": 350}
    new = [p for p in e["photos"] if p["id"] != pid]
    assert len(new) == 1 and new[0]["page"] == 0 and json.loads(new[0]["place"])["w"] == 6


def test_web_zip_of_weekly_reports_opens_in_python(tmp_path):
    """«Todos los semanales»: el ZIP armado en la web (sin compresión) se abre normal."""
    import zipfile
    files = [["20261012-NV-semanal.pdf", "%PDF-1.4 uno"], ["20261019-NV-semanal.pdf", "%PDF-1.4 dos ñ"]]
    src, out = tmp_path / "zip_in.json", tmp_path / "out.zip"
    src.write_text(json.dumps({"files": files}), encoding="utf-8")
    subprocess.run([NODE, os.path.join(ROOT, "tests", "web_roundtrip.mjs"), "zip", str(src), str(out)],
                   check=True, cwd=ROOT)
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert z.namelist() == [f[0] for f in files]
        assert [z.read(n).decode() for n in z.namelist()] == [f[1] for f in files]


def test_report_config_js_matches_python():
    """web/reportcfg.js y report_config.py: mismas secciones, plantillas y claves."""
    import re
    import report_config as rc
    js = open(os.path.join(ROOT, "web", "reportcfg.js"), encoding="utf-8").read()
    keys = re.findall(r'^\s*\["(\w+)", "([^"]+)", "([^"]+)"\],', js, re.M)
    assert keys == [tuple(s) for s in rc.SECTIONS]
    assert f'KEY = "{rc.KEY}"' in js and f'TEMPLATES_KEY = "{rc.TEMPLATES_KEY}"' in js
    for k, t in rc.TEMPLATES.items():
        m = re.search(rf'{k}: {{ name: "{t["name"]}", sections: (\[[^\]]*\]|\[\.\.\.SECTION_KEYS\])', js)
        assert m, k
        if "SECTION_KEYS" not in m.group(1):
            assert re.findall(r'"(\w+)"', m.group(1)) == t["sections"], k


def test_report_config_travels_with_sync(tmp_path):
    import report_config as rc
    import sync
    from database import Database
    a = Database(str(tmp_path / "a.sqlite3"))
    rc.save(a, rc.apply_template(rc.default(a), "cliente"))
    bundle = sync.export_changes(a, str(tmp_path))
    assert rc.KEY in bundle["settings"]
    b = Database(str(tmp_path / "b.sqlite3"))
    sync.apply_changes(b, bundle, str(tmp_path))
    assert rc.load(b)["template"] == "cliente" and rc.load(b)["plain"]


def test_report_config_app_to_web_and_back(tmp_path):
    import report_config as rc
    import sync
    from database import Database
    a = Database(str(tmp_path / "a.sqlite3"))
    rc.save(a, rc.apply_template(rc.default(a), "resumido"))
    res = _node("reportcfg", sync.export_changes(a, str(tmp_path)), tmp_path)
    assert res["read"] == rc.load(a)                       # la web lee lo mismo que la app
    back = {"format": 1, "device": "web", "workspace": "", "changes": [], "settings": res["settings"]}
    sync.apply_changes(a, back, str(tmp_path))
    got = rc.load(a)
    assert "gps" not in got["sections"] and "summary" in got["sections"] and got["template"] == ""
    assert res["summary"] == rc.summary(got)


def test_report_templates_merge_same_in_web_and_app(tmp_path):
    import re
    import report_config as rc
    a = [{"name": "Gerencia", "sections": ["summary"], "plain": True, "ts": "2026-11-12T10:00:00.000000Z"},
         {"name": "Vieja", "sections": [], "ts": "2026-11-12T09:00:00.000000Z"}]
    b = [{"name": "Vieja", "deleted": True, "ts": "2026-11-12T11:00:00.000000Z"},
         {"name": "Gerencia", "sections": ["map"], "ts": "2026-11-12T08:00:00.000000Z"},
         {"name": "cliente B", "sections": ["map"], "ts": "2026-11-12T08:00:00.000000Z"}]
    res = _node("tplmerge", {"a": a, "b": b}, tmp_path)
    assert res["merged"] == rc.merge(a, b)
    assert res["visible"] == [t["name"] for t in rc.visible(rc.merge(a, b))] == ["cliente B", "Gerencia"]
    assert res["summary"].startswith("Gerencia")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", res["ts"])      # mismo formato que la app
    assert len(res["ts"]) == len(rc._now())


def test_unit_counts_per_treatment_web_matches_app(tmp_path):
    import sync
    from workspaces import Workspaces
    wss = Workspaces(str(tmp_path / "data"))
    db = wss.open(wss.create("id", "tratamientos", "Número de cañas", "NC"))
    db.setup_trial(3, 4)
    res = _node("unitcounts", {"bundle": sync.export_changes(db, str(tmp_path)), "names": ["Planta 1", "Planta 2", "Planta 3"],
                               "counts": {"1": 3, "2": 0, "3": 3}}, tmp_path)
    assert res["counts"] == {"1": 3, "2": 0, "3": 3}
    assert res["units"] == ["T1 · Planta 1", "T1 · Planta 2", "T1 · Planta 3", "T3 · Planta 1", "T3 · Planta 2", "T3 · Planta 3"]
    sync.apply_changes(db, res["bundle"], str(tmp_path))           # lo hecho en la web llega a la app
    assert db.unit_counts() == {1: 3, 2: 0, 3: 3}
    assert [u["name"] for u in db.pheno_units()] == res["units"]
    db.sync_pheno_units()                                            # la app no cambia nada
    assert [u["name"] for u in db.pheno_units()] == res["units"]
