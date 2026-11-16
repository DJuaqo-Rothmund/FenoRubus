"""Estimaciones de rendimiento sincronizadas entre equipos (y la web) por Drive."""
import os
import sqlite3

import pytest

import rendimiento as R
from tests.test_core import FakeDrive, _device, synthetic_photo


@pytest.fixture(autouse=True)
def _fresh_cache():
    R._OPEN.clear()
    yield
    R._OPEN.clear()


def test_yields_travel_between_devices(tmp_path):
    fake = FakeDrive()
    cel, _cws, _co, cdir = _device(tmp_path, "cel", fake)
    pc, _pws, _po, pdir = _device(tmp_path, "pc", fake)
    d = R.open_db(cdir, "frambuesa")
    sid = d.new_set({"kind": "predio", "name": "San José", "code": "SJ"}, "Meeker", "2026-11-09",
                    fruit_g=4.0, fruit_set=80, coverage=50, plants_ha=10000)
    path = os.path.join(d.photo_dir, f"{d.photo_basename(d.get_set(sid))}-0.jpg")
    synthetic_photo(61, "detail", path, 0)
    ph = d.add_photo(sid, path)
    d.set_counts(ph, {"boton": 10, "flor": 6, "fruto_verde": 4})
    from drive_backup import DriveBackup
    d.set_setting("drive_enabled", True)
    up = DriveBackup(d, authorizer=cel.drive.authorizer, transport=fake, metered=lambda: False)
    assert R.YieldDrive(d, up).run() == 1           # la foto sube a Drive
    assert cel.run()["sent"] > 0
    names = [f["name"] for f in fake.files.values()]
    assert any(n.endswith(".json") for n in names)
    pc.run(manual=True)
    p = R.open_db(pdir, "frambuesa")
    s = p.sets()
    assert len(s) == 1 and s[0]["place"] == "San José" and s[0]["sector"] == "Meeker"
    assert s[0]["fruits"] == 4 and s[0]["flowers"] == 16 and s[0]["photos"] == 1
    pp = p.photos(s[0]["id"])[0]
    assert os.path.exists(pp["path"]) and pp["queue_id"] is None      # la foto se bajó
    # Cambios de vuelta: parámetros y un conteo corregido en el PC.
    p.update_set(s[0]["id"], fruit_g=5.0)
    p.set_counts(pp["id"], {"boton": 12, "flor": 6, "fruto_verde": 4})
    pc.run()
    cel.run()
    assert d.get_set(sid)["fruit_g"] == 5.0 and d.counts(ph)["boton"] == 12
    assert d.query_one("SELECT queue_id FROM yield_photos WHERE id=?", (ph,))["queue_id"]   # la cola local queda
    # Borrar la estimación en un equipo la borra en el otro.
    d.delete_set(sid)
    cel.run()
    pc.run()
    assert p.sets() == []


def test_old_counts_table_is_migrated(tmp_path):
    d = R.YieldDB(str(tmp_path), "frambuesa")
    sid = d.new_set({"name": "X"}, "A", "2026-11-01")
    ph = d.add_photo(sid, str(tmp_path / "a.jpg"), enqueue=False)
    d.conn.close()
    con = sqlite3.connect(os.path.join(str(tmp_path), R.DIR, R.DB_FILE))
    con.executescript("DROP TABLE yield_counts; CREATE TABLE yield_counts (photo_id INTEGER NOT NULL, "
                      "stage TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'manual', "
                      "PRIMARY KEY (photo_id, stage));")
    con.execute("INSERT INTO yield_counts VALUES (?, 'flor', 7, 'manual')", (ph,))
    con.commit()
    con.close()
    d2 = R.YieldDB(str(tmp_path), "frambuesa")
    assert d2.counts(ph) == {"flor": 7}
    d2.set_counts(ph, {"flor": 8, "boton": 1})
    assert d2.counts(ph) == {"flor": 8, "boton": 1}
    dirty = {r["entity"] for r in d2.query("SELECT entity FROM sync_dirty")}
    assert {"yield_sets", "yield_photos", "yield_counts"} <= dirty


def test_web_yield_matches_app(tmp_path):
    """web/yield.js: mismos resultados que rendimiento.py y sus cambios se aplican en la app."""
    import json
    import shutil
    import subprocess

    import geo
    import sync
    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node.js")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = R.YieldDB(str(tmp_path), "frambuesa")
    sid = d.new_set({"kind": "predio", "name": "San José", "code": "SJ"}, "Meeker", "2026-11-09",
                    fruit_g=4.0, fruit_set=75, coverage=40, plants_ha=12000)
    d.update_set(sid, kind="real", real_per_plant=90)
    ph = [d.add_photo(sid, str(tmp_path / R.DIR / "fotos" / f"f{i}.jpg"), enqueue=False) for i in range(2)]
    d.set_counts(ph[0], {"boton": 10, "flor": 6, "fruto_verde": 4})
    d.set_counts(ph[1], {"flor": 3, "fruto_maduro": 2}, source="ia")
    bundle = sync.export_changes(d, str(tmp_path))
    maps = os.path.join(root, "assets", "maps")
    plan = None
    for name in sorted(os.listdir(maps)) if os.path.isdir(maps) else []:
        cand = json.load(open(os.path.join(maps, name), encoding="utf-8"))
        if cand.get("geo") and any(s["id"] == "E2-S7" for s in cand.get("sectors", [])):
            plan = cand
            break
    lat = lon = None
    if plan:
        g = plan["geo"]
        ring = plan["sectors"][0]["parts"][0]
        x, y = sum(ring[0::2]) / (len(ring) / 2), sum(ring[1::2]) / (len(ring) / 2)
        lon, lat = (x + g["x0"]) / g["kx"], (y + g["y0"]) / g["ky"]
    src, out = tmp_path / "in.json", tmp_path / "out.json"
    src.write_text(json.dumps({"bundles": [bundle], "mod": "PhenoRubus", "plan": plan, "lat": lat, "lon": lon,
                               "fields": {"fruit_g": 5.0, "sector": "Meeker", "notes": "desde la web"},
                               "counts": {"boton": 12, "flor": 6, "fruto_verde": 4, "fruto_maduro": 1}}))
    subprocess.run([node, os.path.join(root, "tests", "web_yield.mjs"), str(src), str(out)], check=True, cwd=root)
    res = json.loads(out.read_text())
    py = d.sets()[0]
    js = res["sets"][0]
    for k in ("per_plant", "kg_ha", "t_ha", "real_t_ha", "photo_error"):
        assert js[k] == pytest.approx(py[k]), k
    assert js["counted"] == 2 and js["photos"] == 2 and js["totals"] == py["totals"]
    # La planilla de la web es la misma de la app.
    app_csv = open(d.export_csv(), encoding="utf-8-sig").read().replace("\r\n", "\n")
    assert res["csv"].lstrip("﻿").replace("\r\n", "\n") == app_csv
    if plan:
        assert res["sector"] == geo.sector_at(plan, lat, lon)["id"] and res["byName"] == "E2-S7"
    # Lo editado en la web llega a la app: parámetro, conteos corregidos y uno nuevo.
    assert {c["entity"] for c in res["changes"]} == {"yield_sets", "yield_counts"}
    stats = sync.apply_changes(d, res["bundle"], str(tmp_path))
    assert stats["applied"] == len(res["changes"])
    s = d.get_set(sid)
    assert s["fruit_g"] == 5.0 and s["notes"] == "desde la web" and s["real_per_plant"] == 90
    assert d.counts(ph[0]) == {"boton": 12, "flor": 6, "fruto_verde": 4, "fruto_maduro": 1}
    assert d.photos(sid)[0]["path"].endswith("f0.jpg")
