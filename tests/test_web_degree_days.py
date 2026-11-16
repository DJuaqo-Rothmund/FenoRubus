"""Web (Pyodide): informes de días grado con las temperaturas del predio cargadas en la web."""
import datetime as dt
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "web"))

import degree_days as gd  # noqa: E402
import sync  # noqa: E402
from database import Database  # noqa: E402


def _weather_bundle(days, mode="propios"):
    """Paquete como el que arma la web al subir datos de la estación (app.js · sendTo)."""
    ts = "2026-11-16T10:00:00.000"
    ch = [{"entity": "weather_days", "uid": d["day"], "ts": ts, "deleted": 0,
           "data": {"day": d["day"], "tmean": d.get("tmean"), "tmin": None, "tmax": None, "rain": d.get("rain"),
                    "source": "estación (web)", "updated_at": ts}} for d in days]
    return {"format": 1, "device": "web-x", "workspace": "PR", "created": ts, "upto": ts, "changes": ch,
            "settings": {gd.MODE_KEY: mode}}


def test_web_degree_days_and_compare(tmp_path, monkeypatch):
    monkeypatch.setenv("FENORUBUS_DATA", str(tmp_path / "web"))
    wr = importlib.reload(importlib.import_module("webreport"))
    # ensayo de la app con estados BBCH en dos temporadas
    app = Database(str(tmp_path / "app.sqlite3"), code="EN", workspace={"code": "EN", "name": "Ensayo", "profile": "id"})
    v = app.add_variety("Zeta W")
    for season, shift in ((2025, 0), (2026, 7)):
        for i, code in enumerate((51, 61, 65, 71)):
            day = gd.biofix(season) + dt.timedelta(days=30 + 14 * i + shift)
            o = app.get_or_create_observation(v, app.week_for_date(day)["id"])
            app.update_observation(o["id"], bbch_code=code, observed_at=day.isoformat())
    app.set_setting(gd.SETTING_PREDIO, "PR")
    bundle = sync.export_all(app, str(tmp_path))
    wr.use_crop("PhenoRubus")
    assert wr.load("EN", json.dumps({"code": "EN", "name": "Ensayo", "profile": "id"}),
                   json.dumps([["b1.json", bundle]])) == 1
    days = [{"day": (gd.biofix(s) + dt.timedelta(days=i)).isoformat(), "tmean": 9 + i * .05}
            for s in (2025, 2026) for i in range(90 if s == 2026 else 365)]
    wr.load("PR", json.dumps({"code": "PR", "name": "El Amanecer", "profile": "predio"}),
            json.dumps([["w1.json", _weather_bundle(days)]]))
    info = json.loads(wr.weather_info("EN", 2026))
    assert info["predio"]["name"] == "El Amanecer" and info["mode"] == "propios" and info["own"] == len(days)
    path = wr.report("EN", "degree_days", "", 2026)
    assert path.endswith(".pdf") and os.path.getsize(path) > 3000
    path = wr.report("EN", "season_compare", "PR|prev", 2026)
    assert path.endswith(".pdf") and os.path.getsize(path) > 3000
    # Archivo de la estación (CSV con coma decimal) -> días
    csv = tmp_path / "est.csv"
    csv.write_text("Fecha;T media;Lluvia\n01-09-2026;11,5;0\n02-09-2026;9,8;3,2\n", encoding="utf-8")
    out = json.loads(wr.parse_weather(str(csv)))
    assert [d["tmean"] for d in out["days"]] == [11.5, 9.8]
    out = json.loads(wr.parse_weather("", "2026-09-03\t12\n2026-09-04\t13"))
    assert len(out["days"]) == 2
