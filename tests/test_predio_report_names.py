"""Informes de predio: cada unidad sale con variedad, equipo y sector (antes solo «Equipo de
riego 1, sector 2», sin la variedad)."""
import datetime as dt

import phenology as ph
from database import Database
from reporter import LabeledDB, ReportGenerator


def _predio(tmp_path):
    db = Database(str(tmp_path / "AM.sqlite3"), code="AM")
    for v in db.list_varieties():
        db.archive_variety(v["id"]) if hasattr(db, "archive_variety") else None
    uid = db.save_unit("Meeker", sector=2, irrigation=1, plant_year=2019)
    week = db.week_for_date(dt.date(2026, 11, 16))
    obs = db.get_or_create_observation(uid, week["id"])
    db.update_observation(obs["id"], bbch_code=61)
    return db, uid, week


def test_unit_report_name():
    v = {"cultivar": "Meeker", "plant_year": 2019, "sector": 2, "irrigation": 1, "treatment": None, "name": "x"}
    assert ph.unit_report_name(v) == "Meeker 2019 · Equipo 1 · Sector 2"
    assert ph.unit_report_name({**v, "irrigation": None}) == "Meeker 2019 · Sector 2"
    assert ph.unit_report_name({"name": "Tulameen"}) == "Tulameen"


def test_predio_reports_show_variety_equipo_sector(tmp_path):
    db, uid, week = _predio(tmp_path)
    ldb = LabeledDB(db)
    assert ldb.get_variety(uid)["name"] == "Meeker 2019 · Equipo 1 · Sector 2"
    assert any(v["name"] == "Meeker 2019 · Equipo 1 · Sector 2" for v in ldb.pheno_units())
    gen = ReportGenerator(db, str(tmp_path / "out"))
    res = gen.weekly(week["id"]) if hasattr(gen, "weekly") else None
    if res is not None:
        html = open(res.path, encoding="utf-8").read() if res.path.endswith(".html") else ""
        if html:
            assert "Meeker 2019 · Equipo 1 · Sector 2" in html


def test_predio_pdf_has_variety_equipo_sector(tmp_path, monkeypatch):
    import json
    import os
    import re
    import sys
    import zlib
    import sync
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "web"))
    phone = Database(str(tmp_path / "phone" / "AM.sqlite3"), code="AM")
    uid = phone.save_unit("Meeker", sector=2, irrigation=1, plant_year=2019)
    week = phone.week_for_date(dt.date(2026, 11, 16))
    o = phone.get_or_create_observation(uid, week["id"])
    phone.update_observation(o["id"], bbch_code=61)
    bundle = sync.export_changes(phone, str(tmp_path / "phone"))
    monkeypatch.setenv("FENORUBUS_DATA", str(tmp_path / "web"))
    import webreport
    monkeypatch.setattr(webreport, "DATA", str(tmp_path / "web"))
    webreport.load("AM", json.dumps({"code": "AM", "name": "El Amanecer", "profile": "predio"}),
                   json.dumps([["b1", bundle]]))
    for kind, arg in (("weekly", week["start_date"]), ("matrix", "")):
        raw = open(webreport.report("AM", kind, arg, 2026), "rb").read()
        text = b"".join(zlib.decompress(m) for m in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S)
                        if m[:1] == b"x")
        assert b"Meeker 2019" in text and b"Equipo 1" in text and b"Sector 2" in text, kind
