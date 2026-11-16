"""Contar estructuras con cajas en las fotos de mediciones (app, Excel y web)."""
import datetime as dt
import json
import os
import shutil
import subprocess
import zipfile

import pytest

import box_ai
import training_labels as tl
from database import Database
from measures_export import export_measures

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _box(c, x=.1, y=.1, w=.1, h=.1):
    return {"c": c, "x": x, "y": y, "w": w, "h": h}


def test_counts_and_text():
    tl.set_crop("frambuesa")
    rec = {"boxes": [_box("flor"), _box("boton"), _box("flor"), _box("fruto_maduro")]}
    assert tl.counts(rec) == {"boton": 1, "flor": 2, "fruto_maduro": 1}
    assert list(tl.counts(rec)) == ["boton", "flor", "fruto_maduro"]       # orden de las clases
    assert tl.count_text(rec) == "Botón 1 · Flor 2 · Fruto maduro 1  (4)"
    assert tl.counts({"empty": True, "boxes": []}) == {} and tl.count_text({"empty": True}) == "Sin estructuras"
    assert tl.counts(None) is None and tl.count_text({"boxes": []}) == ""


def test_excel_has_counts(tmp_path):
    tl.set_crop("frambuesa")
    db = Database(str(tmp_path / "t.sqlite3"))
    m = db.add_measure("Racimos", kind="images")
    w = db.week_for_date(dt.date(2026, 11, 16))
    a = db.add_entry(m, w["id"], path=str(tmp_path / "a.jpg"), caption="Caña 1")
    db.add_entry(m, w["id"], path=str(tmp_path / "b.jpg"), caption="Caña 2")       # sin contar
    labels = {"a.jpg": {"boxes": [_box("flor"), _box("flor"), _box("fruto_verde")]}}
    path = export_measures(db, [m], w["season"], str(tmp_path), labels=labels)
    xml = zipfile.ZipFile(path).read("xl/worksheets/sheet1.xml").decode()
    for t in ("Flor", "Fruto verde", "Total estructuras", "a.jpg"):
        assert t in xml
    assert "<v>2</v>" in xml and "<v>3</v>" in xml
    assert a


def test_gemini_boxes_to_marks():
    keys = ["flor", "fruto_verde"]
    raw = [{"box_2d": [100, 200, 300, 260], "label": "flor"},
           {"box_2d": [500, 900, 400, 1200], "label": "fruto_verde"},     # al revés y fuera: se arregla
           {"box_2d": [1, 1, 2, 2], "label": "flor"},                      # muy chica
           {"box_2d": [1, 1, 200, 200], "label": "hoja"}]                  # clase desconocida
    got = box_ai.to_boxes(raw, keys)
    assert got[0] == {"c": "flor", "x": .2, "y": .1, "w": .06, "h": .2, "s": "ia"}
    assert got[1]["x"] == .9 and got[1]["w"] == pytest.approx(.1) and len(got) == 2
    mine = [{"c": "flor", "x": .21, "y": .1, "w": .06, "h": .2}]
    assert box_ai.merge(mine, got) == mine + [got[1]]        # la de la persona manda


def test_web_box_ai_matches_app(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node.js")
    tl.set_crop("arandano")
    classes = [list(c) for c in tl.CLASSES]
    raw = [{"box_2d": [100, 200, 300, 260], "label": "flor"}, {"box_2d": [500, 900, 400, 1200], "label": "racimo"}]
    script = tmp_path / "t.mjs"
    script.write_text(
        f"import * as B from {json.dumps(os.path.join(ROOT, 'web', 'box_ai.js'))};\n"
        f"const c = {json.dumps(classes)};\n"
        f"console.log(JSON.stringify({{p: B.prompt(c, 'arándano'), b: B.toBoxes({json.dumps(raw)}, c.map((x) => x[0]))}}));\n")
    out = json.loads(subprocess.run([node, str(script)], check=True, capture_output=True, text=True).stdout)
    assert out["p"] == box_ai.prompt(tl.CLASSES, "arándano")
    assert out["b"] == box_ai.to_boxes(raw, [k for k, _n, _c in tl.CLASSES])
    tl.set_crop("frambuesa")


def test_measure_photos_listed_in_iaplus(tmp_path):
    db = Database(str(tmp_path / "t.sqlite3"))
    db.workspace = {"code": "NV", "name": "Nuevas variedades"}
    m = db.add_measure("Racimos", kind="images")
    w = db.week_for_date(dt.date(2026, 11, 16))
    db.add_entry(m, w["id"], path=str(tmp_path / "20261116-NV-racimos.jpg"), caption="Caña 1")
    db.add_entry(m, w["id"], data={"x": 1})                              # fila sin foto: no
    got = tl.measure_photos([db])
    assert [(p["name"], p["code"], p["variety"], p["week"][:10]) for p in got] == [
        ("20261116-NV-racimos.jpg", "NV", "Medición Racimos · Caña 1", "2026-11-16")]


def test_measure_photo_named_with_treatment_and_caption(tmp_path):
    db = Database(str(tmp_path / "t.sqlite3"))
    db.code = "AUF"
    m = db.add_measure("Laterales flores", kind="images")
    w = db.week_for_date(dt.date(2026, 11, 9))
    vid = db.add_variety("T2R1")
    db.execute("UPDATE varieties SET treatment=2 WHERE id=?", (vid,))
    db.execute("INSERT OR REPLACE INTO treatments(num, name) VALUES (2, '23 kg/ha')")
    old = tmp_path / "20261109-AUF-laterales-flores-30.jpg"
    old.write_bytes(b"x")
    e = db.add_entry(m, w["id"], path=str(old))
    db.execute("INSERT INTO drive_queue(photo_id, path, name, status, drive_id, created_at) VALUES "
               "(NULL, ?, ?, 'done', 'f1', 'x')", (str(old), "Año 2026/Semana 45/Laterales flores/" + old.name))
    assert db.rename_measure_photo(e) is None                        # sin tratamiento ni descripción
    db.update_entry(e, caption="Medio 3", variety_id=vid)
    assert db.rename_measure_photo(e) == ("20261109-AUF-laterales-flores-30.jpg",
                                          "20261109-AUF-laterales-flores-23-kg-ha-medio-3.jpg")
    new = db.query_one("SELECT path FROM measure_entries WHERE id=?", (e,))["path"]
    assert os.path.exists(new) and not old.exists()
    q = db.query_one("SELECT * FROM drive_queue")
    assert q["path"] == new and q["name"].endswith("23-kg-ha-medio-3.jpg")
    assert db.get_setting("week_moves_drive")[-1]["old"] == old.name          # se renombra en Drive
    assert db.rename_measure_photo(e) is None                                # ya está
    # Las cajas de IA+ pasan al nombre nuevo y el anterior deja de contar.
    store = tl.LabelStore(str(tmp_path))
    store.put(old.name, {"w": 1, "h": 1, "boxes": [_box("flor")]})
    assert store.rename(old.name, os.path.basename(new))
    assert tl.counts(store.get(os.path.basename(new))) == {"flor": 1} and not tl.is_marked(store.get(old.name))
