"""Módulo Plantas: hileras del campo, ensayo NV, eventos, mediciones y sincronización."""
import json

import plantas
import sync

NV = str(plantas.ASSETS / "plantas" / "NV.json")


def _db(tmp_path, name="a"):
    plantas._OPEN.clear()
    return plantas.PlantDB(str(tmp_path / name))


def test_field_rows_loaded_and_trial_marked(tmp_path):
    db = _db(tmp_path)
    rows = db.field_rows("AM")
    assert len(rows) == 3103
    assert sum(1 for r in rows if not r["rev"]) > 2700
    tid = db.import_trial(NV)
    rows = db.field_rows("AM")
    nv = [r for r in rows if r["trial"] == "NV"]
    assert sorted(r["n"] for r in nv) == [521, 522]
    r522 = next(r for r in nv if r["n"] == 522)
    assert (r522["s"], r522["e"], r522["pl"], r522["L"]) == (1, 2, 467, 386.3)   # lo contado
    assert db.trials()[0]["plants"] == 467 + 526
    assert db.import_trial(NV) == tid              # repetir no duplica
    assert db.trials()[0]["plants"] == 993


def test_row_corrections_subtitle_merge_and_duplicates(tmp_path):
    db = _db(tmp_path)
    rows = db.field_rows("AM")
    r = next(x for x in rows if x["n"] == 547 and x["s"] == 1 and x["e"] == 2 and x["rev"] and x["flag"] == 1)
    db.edit_row("AM", r["key"], ns="S")
    r2 = db.field_row("AM", r["key"])
    assert r2["label"] == "547 S" and r2["edited"]
    others = db.neighbors("AM", r["key"])
    north = next(o for o in others if o["y0"] > r["y0"] and o["s"] == 1)
    merged = db.merge_rows("AM", r["key"], north["key"])
    assert merged["L"] == round(r["L_plano"] + north["L_plano"], 1) and not merged["rev"]
    assert db.field_row("AM", north["key"])["hidden"]
    n = db.remove_duplicates("AM")
    assert n >= 50
    assert all(x["hidden"] for x in db.field_rows("AM") if x["flag"] == 2)
    db.undo_row("AM", r["key"])
    assert not db.field_row("AM", r["key"])["edited"]


def test_plants_numbering_steps_and_find(tmp_path):
    db = _db(tmp_path)
    tid = db.import_trial(NV)
    h1 = db.rows_of(tid)[0]
    ps = db.plants_of(h1["id"])
    assert len(ps) == 539 and sum(p["kind"] == "planta" for p in ps) == 467
    p = db.find_plant(tid, "H1", "Wakefield", 1, 21)
    assert p and p["hoyo"] == 128
    prev = db.step(p["id"], -1)
    assert prev["num"] == 20 and prev["hoyo"] == 126       # salta la falla del hoyo 127
    assert db.plant_title(db.plant(p["id"])) == "522 · W·B1 · P21"


def test_events_names_and_measures(tmp_path):
    db = _db(tmp_path)
    tid = db.import_trial(NV)
    p = db.find_plant(tid, "H1", "Wakefield", 1, 21)
    assert db.canonical("enfermedad", "botrytis") == ("Botrytis", None)
    assert db.canonical("enfermedad", "Botritis")[1] == "Botrytis"
    db.add_event(p["id"], "enfermedad", "Botrytis", 2, "en frutos")
    assert db.suggest("enfermedad", "bot")[0] == "Botrytis"
    db.add_event(p["id"], "muerta")
    assert db.plant(p["id"])["status"] == "muerta"
    db.add_event(p["id"], "replante", day="2026-12-01")
    assert db.plant(p["id"])["status"] == "replante"
    db.set_measure(p["id"], "2026-11-20", canas=8, primocanas=5)
    db.set_measure(p["id"], "2026-11-20", lat_arriba=12)
    m = db.measure(p["id"], "2026-11-20")
    assert (m["canas"], m["primocanas"], m["lat_arriba"]) == (8, 5, 12)
    db.set_measure(p["id"], "T2026-27", rend=1.25)
    assert db.last_values(tid, "canas") == {p["id"]: 8}
    h = db.history(p["id"])
    assert h[0]["_type"] == "measure" and h[0]["day"] == "T2026-27"
    out = db.export_csv(tid, str(tmp_path / "nv.csv"))
    assert "Botrytis" in open(out, encoding="utf-8-sig").read()
    assert plantas.season_of("2026-03-10") == "2025-26" and plantas.season_of("2026-11-10") == "2026-27"


def test_sync_between_two_phones(tmp_path):
    a = _db(tmp_path, "a")
    tid = a.import_trial(NV)
    p = a.find_plant(tid, "H2", None, None, 5)
    eid = a.add_event(p["id"], "plaga", "Arañita roja", 1)
    a.set_measure(p["id"], "2026-11-20", canas=6)
    a.edit_row("AM", a.field_rows("AM")[10]["key"], ns="N")
    bundle = json.loads(json.dumps(sync.export_changes(a, str(tmp_path))))
    plantas._OPEN.clear()
    b = plantas.PlantDB(str(tmp_path / "b"))
    with b.batch():
        sync.apply_changes(b, bundle, str(tmp_path))
    assert b.trials()[0]["plants"] == 993
    tb = b.trials()[0]["id"]
    pb = b.find_plant(tb, "H2", None, None, 5)
    assert [e["name"] for e in b.events(pb["id"])] == ["Arañita roja"]
    assert b.measure(pb["id"], "2026-11-20")["canas"] == 6
    assert b.field_rows("AM")[10]["ns"] == "N"
    assert eid


def test_row_edits_bake_into_asset(tmp_path):
    """Lo corregido en el teléfono se incorpora al plano: una instalación nueva viene corregida."""
    import sys
    sys.path.insert(0, str(plantas.ASSETS.parent / "tools"))
    import bake_row_edits
    db = _db(tmp_path)
    rows = db.field_rows("AM")
    rev = [r for r in rows if r["rev"] and r["flag"] == 1]
    a, b = rev[0], rev[1]
    dup = next(r for r in rows if r["flag"] == 2)
    db.edit_row("AM", a["key"], ns="S", largo=120.5, plantas=172, estado="ok")
    db.edit_row("AM", b["key"], estado="no")
    db.remove_duplicates("AM")
    data = json.loads(json.dumps(db.export_row_edits("AM")))
    asset = json.loads((plantas.ASSETS / "maps" / "AM_hileras.json").read_text(encoding="utf-8"))
    total = len(asset["rows"])
    baked, stats = bake_row_edits.bake(asset, data["edits"])
    assert stats["quitadas"] == 1 + sum(1 for r in rows if r["flag"] == 2)
    names = baked["fields"]
    got = {r[0]: dict(zip(names, r)) for r in baked["rows"]}
    assert got[a["key"]]["ns"] == "S" and got[a["key"]]["L"] == 120.5 and got[a["key"]]["flag"] == 0
    assert b["key"] not in got and dup["key"] not in got
    assert len(baked["rows"]) == total - stats["quitadas"]
    path = db.write_row_edits("AM")
    assert path and json.load(open(path, encoding="utf-8"))["edits"]
