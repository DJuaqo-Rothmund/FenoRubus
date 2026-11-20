"""py.zip (el código de informes que corre en la web con Pyodide) debe traer TODOS los módulos
que importa: se prueba descomprimido solo, sin el resto del repositorio, como en el navegador.
(Un «import perf» nuevo en database.py dejó la web sin PDF: ModuleNotFoundError.)"""
import json
import os
import subprocess
import sys
import zipfile

import sync
from database import Database

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

SCRIPT = r"""
import json, os, sys
app, data, bundle = sys.argv[1:4]
sys.path.insert(0, app)
os.environ["FENORUBUS_DATA"] = data
import webreport
webreport.use_crop("PhenoRubus")
ws = {"code": "AUF", "name": "Ensayo", "profile": "id", "kind": "tratamientos"}
webreport.load("AUF", json.dumps(ws), json.dumps([["b1", json.load(open(bundle))]]))
week = sys.argv[4]
out = []
for kind, arg in (("weekly", week), ("matrix", ""), ("treatments", ""), ("excel", ""),
                  ("period", week + "|" + week)):
    webreport.photos("AUF", kind, arg, 2026)
    out.append(os.path.basename(webreport.report("AUF", kind, arg, 2026)))
print(json.dumps(out))
"""


def test_py_zip_is_self_contained(tmp_path):
    import make_web_data
    zpath = tmp_path / "py.zip"
    make_web_data.py_zip(str(zpath))
    app = tmp_path / "app"
    zipfile.ZipFile(zpath).extractall(app)

    phone = Database(str(tmp_path / "phone" / "AUF.sqlite3"), code="AUF")
    phone.setup_trial(2, 2)
    import datetime as dt
    week = phone.week_for_date(dt.date(2026, 11, 16))
    for v in phone.list_varieties():
        if phone.is_parcel(v):
            obs = phone.get_or_create_observation(v["id"], week["id"])
            phone.update_observation(obs["id"], bbch_code=61)
    import sheet_layout as SL
    m = phone.add_measure("Primocañas", "table", SL.build(["Corona", "Fuera"], 2))
    phone.fill_sheet_rows(m, week["id"])
    first = phone.list_entries(m, week_id=week["id"])[0]
    phone.update_entry(first["id"], data={"Planta 1 · Corona": "6", "Planta 1 · Fuera": "1"})
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(sync.export_changes(phone, str(tmp_path / "phone"))))

    script = tmp_path / "run.py"
    script.write_text(SCRIPT)
    # -I: sin el directorio actual ni PYTHONPATH (solo lo que trae py.zip + paquetes instalados).
    res = subprocess.run([sys.executable, "-I", str(script), str(app), str(tmp_path / "web"), str(bundle),
                          week["start_date"]], capture_output=True, text=True, cwd=str(tmp_path), timeout=300)
    assert res.returncode == 0, res.stderr[-2000:]
    names = json.loads(res.stdout.strip().splitlines()[-1])
    assert names[0].endswith(".pdf") and names[3].endswith(".xlsx")
