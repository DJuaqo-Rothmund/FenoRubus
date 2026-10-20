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
