"""Planillas con columnas subdivididas (Planta 1 · N.º laterales …) y su Excel por muestra."""
import json
import os
import shutil
import subprocess
import zipfile

import pytest

import sheet_layout as SL
import datetime as dt

from database import Database


def make_db(tmp_path):
    return Database(str(tmp_path / "t.sqlite3"))

EVALS = ["N.º laterales", "Largo laterales (cm)", "Largo entrenudos (cm)"]


def test_build_and_groups():
    cols = SL.build(SL.parse_vars("N.º laterales\nLargo laterales (cm), Largo entrenudos (cm)"), 3, "Planta")
    assert len(cols) == 9 and cols[0] == "Planta 1 · N.º laterales" and cols[-1] == "Planta 3 · Largo entrenudos (cm)"
    gs = SL.groups(cols + ["Notas"])
    assert [g for g, _c in gs] == ["Planta 1", "Planta 2", "Planta 3", None]
    assert SL.split("Notas") == (None, "Notas") and SL.is_grouped(cols) and not SL.is_grouped(EVALS)
    assert SL.build(EVALS, 1) == EVALS
    assert SL.build(EVALS, 2, reps_col=True)[0] == SL.REP_COL
    assert SL.next_group(cols)[0] == "Planta 4" and len(SL.next_group(cols)[1]) == 3
    assert SL.add_sub(cols, "Diámetro")[3] == "Planta 1 · Diámetro"
    assert SL.unit_word(cols) == "plantas" and SL.unit_word(SL.build(EVALS, 2, "Caña")) == "cañas"
    with pytest.raises(ValueError):
        SL.build([], 3)


def test_trial_sheet_rows_and_excel(tmp_path):
    from measures_export import export_measures
    db = make_db(tmp_path)
    db.setup_trial(3, 2)
    week = db.week_for_date(dt.date(2026, 11, 16))
    mid = db.add_measure("Laterales", "table", SL.build(EVALS, 4))
    assert db.fill_sheet_rows(mid, week["id"]) == 6           # una fila por parcela
    assert db.fill_sheet_rows(mid, week["id"]) == 0           # no repite
    rows = db.list_entries(mid, week_id=week["id"])
    db.update_entry(rows[0]["id"], data={"Planta 1 · N.º laterales": "12", "Planta 1 · Largo laterales (cm)": "45,5",
                                         "Planta 2 · N.º laterales": "10"})
    path = export_measures(db, [mid], week["season"], str(tmp_path))
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if n.startswith("xl/worksheets/")]
    assert len(names) == 2                                   # planilla + «por muestra»
    long = z.read("xl/worksheets/sheet2.xml").decode()
    assert "Muestra" in long and "Planta 1" in long and "Planta 2" in long and "Planta 3" not in long
    assert "45.5" in long                                    # número, no texto


def test_variety_reps_and_structure(tmp_path):
    db = make_db(tmp_path)
    nv = len(db.sheet_units())
    assert nv > 0
    week = db.week_for_date(dt.date(2026, 11, 16))
    mid = db.add_measure("Plantas", "table")
    db.update_entry(db.add_entry(mid, week["id"], None, data={}), data={"Columna 2": "x"})
    cols = db.structure_measure(mid, SL.build(EVALS, 2, reps_col=True))
    assert cols[0] == SL.REP_COL and cols[-1] == "Columna 2"   # la columna con datos se conserva
    assert "Columna 1" not in cols
    assert db.fill_sheet_rows(mid, week["id"], 3) == nv * 3   # variedades × 3 repeticiones
    w2 = db.week_for_date(dt.date(2026, 11, 23))
    assert db.fill_sheet_rows(mid, w2["id"]) == nv * 3        # otra semana: mismas repeticiones
    reps = sorted(e["data"][SL.REP_COL] for e in db.list_entries(mid, week_id=w2["id"]))
    assert reps == sorted(["1", "2", "3"] * nv)


def test_web_sheet_matches_python():
    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node.js")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import('./web/sheet.js').then((S) => { const c = S.build(S.parseVars(process.argv[1]), 3, 'Caña', true);"
            "console.log(JSON.stringify({ c, g: S.groups(c).map((x) => x[0]), n: S.nextGroup(c), d: S.describe(c.slice(1)),"
            "w: S.unitWord(c), a: S.addSub(c, 'Diámetro'), t: S.table('1\\t2\\n3\\t4\\n') })); })")
    out = subprocess.run([node, "-e", code, "N.º laterales\nLargo; Largo"], capture_output=True, text=True,
                         cwd=root, check=True).stdout
    js = json.loads(out)
    py = SL.build(SL.parse_vars("N.º laterales\nLargo; Largo"), 3, "Caña", True)
    assert js["c"] == py
    assert js["g"] == [g for g, _c in SL.groups(py)]
    assert tuple(js["n"][0:1]) == (SL.next_group(py)[0],) and js["n"][1] == SL.next_group(py)[1]
    assert js["d"] == SL.describe(py[1:]) and js["w"] == SL.unit_word(py) and js["a"] == SL.add_sub(py, "Diámetro")
    assert js["t"] == [["1", "2"], ["3", "4"]]


def test_measure_schedule_and_sync(tmp_path):
    """Mediciones de una sola vez o de semanas elegidas; la web las fija con un ajuste sincronizado."""
    import sync
    db = make_db(tmp_path)
    w1 = db.week_for_date(dt.date(2026, 11, 16))
    w2 = db.week_for_date(dt.date(2026, 11, 23))
    m = db.get_measure(db.add_measure("Altura final", "table"))
    assert db.measure_schedule(m)["mode"] == "weekly" and db.measure_due(m, w2)
    db.set_measure_schedule(m, "once", [w1["start_date"], w2["start_date"]])
    assert db.measure_schedule(m) == {"mode": "once", "weeks": ["2026-11-16"]}
    assert db.measure_due(m, w1) and not db.measure_due(m, w2)
    assert db.schedule_text(m).startswith("Una sola vez · semana 47")
    with pytest.raises(ValueError):
        db.set_measure_schedule(m, "weeks", [])
    # Lo que manda la web (texto JSON en el paquete) llega igual a la app.
    bundle = {"format": 1, "device": "web1", "workspace": "", "changes": [],
              "settings": {f"measure_schedule:{m['uid']}": json.dumps({"mode": "weeks", "weeks": ["2026-11-23"]})}}
    sync.apply_changes(db, bundle, str(tmp_path))
    assert db.measure_schedule(m)["weeks"] == ["2026-11-23"] and db.measure_due(m, w2) and not db.measure_due(m, w1)
    assert any(k.startswith("measure_schedule:") for k in sync.export_changes(db, str(tmp_path))["settings"])
