"""PDF de la web (tools/web/webreport.py, con Pyodide): los paquetes de sincronización
arman una base y salen los mismos informes que en la app."""
import json
import os
import sys

import sync
from database import Database

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "web"))


def test_webreport_builds_pdfs_from_bundles(tmp_path, monkeypatch):
    phone = Database(str(tmp_path / "phone" / "AM.sqlite3"), code="AM")
    week = phone.ensure_week(2026, 3)
    vid = phone.add_variety("Variedad Web", code="VW")
    obs = phone.get_or_create_observation(vid, week["id"])
    phone.update_observation(obs["id"], bbch_code=61)
    bundle = sync.export_changes(phone, str(tmp_path / "phone"))

    monkeypatch.setenv("FENORUBUS_DATA", str(tmp_path / "web"))
    import webreport
    monkeypatch.setattr(webreport, "DATA", str(tmp_path / "web"))
    ws = {"code": "AM", "name": "El Amanecer", "profile": "predio"}
    assert webreport.load("AM", json.dumps(ws), json.dumps([["b1", bundle]])) == 1
    assert webreport.load("AM", json.dumps(ws), json.dumps([["b1", bundle]])) == 0     # ya leído
    names = [r["name"] for r in webreport._dbs["AM"][0].list_varieties()]
    assert names == [v["name"] for v in phone.list_varieties()]           # sin variedades de ejemplo
    for kind, arg in (("weekly", week["start_date"]), ("matrix", "")):
        path = webreport.report("AM", kind, arg, 2026)
        with open(path, "rb") as f:
            assert f.read(5) == b"%PDF-"
