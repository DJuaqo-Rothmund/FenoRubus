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
    assert stats["applied"] == 4
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
