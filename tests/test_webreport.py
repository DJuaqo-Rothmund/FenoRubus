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
    m = phone.add_measure("Calibre", "table", ["mm"])
    phone.add_entry(m, week["id"], vid, data={"mm": "18"})
    assert webreport.load("AM", json.dumps(ws), json.dumps([["b2", sync.export_changes(phone, str(tmp_path / "phone"))]])) == 1
    assert webreport.report("AM", "excel", "", 2026).endswith(".xlsx")
    for kind, arg in (("weekly", week["start_date"]), ("matrix", ""), ("period", f"{week['start_date']}|{week['start_date']}")):
        path = webreport.report("AM", kind, arg, 2026)
        with open(path, "rb") as f:
            assert f.read(5) == b"%PDF-"
    # Configuración de informes de la web: todas las secciones (con el plano del predio AM).
    import report_config as rc
    full = json.dumps(rc.apply_template(rc.default(), "completo"))
    assert isinstance(json.loads(webreport.photos("AM", "weekly", week["start_date"], 2026, full)), list)
    path = webreport.report("AM", "weekly", week["start_date"], 2026, False, full)
    with open(path, "rb") as f:
        assert f.read(5) == b"%PDF-"
    # «Sin fecha de generación» también en los PDF de la web (pie: solo el número de página).
    import re
    import zlib
    nod = json.dumps(dict(rc.apply_template(rc.default(), "completo"), no_date=True, plain=True))
    raw = open(webreport.report("AM", "weekly", week["start_date"], 2026, True, nod), "rb").read()
    text = b"".join(zlib.decompress(m) for m in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S)
                    if m[:1] == b"x")
    assert b"enerado" not in text and b"gina 1 de" in text
