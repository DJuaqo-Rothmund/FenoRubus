"""
tools/make_trial_plants.py
==========================
Plantas de un ensayo (módulo Plantas) desde la hoja «Mapeo» de su planilla: cada hilera
del ensayo con sus hoyos, de sur (0 m) a norte, y en cada hoyo la planta (variedad,
bloque, número dentro de su tramo), una falla, una separación o una planta eliminada. Los
drenajes no tienen hoyos: quedan como huecos entre posiciones.

    python tools/make_trial_plants.py "00.Datos - nuevas variedades.xlsx" NV "Nuevas variedades" \
        H1=522 H2=521
    -> assets/plantas/NV.json

H1=522: la hilera «H1» del Mapeo es la 522 del campo (su sector y equipo se toman de
assets/maps/AM_hileras.json, la tira más larga con ese número dentro del ensayo, opción
--sector S-E). Necesita openpyxl (solo aquí).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VARIETIES = {"CH": "Cascade Harvest", "W": "Wakefield", "M": "Meeker", "L": "Lagorai"}
KINDS = {"Planta": "planta", "Hoyo vacío": "falla", "Vacío": "separacion", "Eliminada": "eliminada"}


def build(xlsx: str, code: str, name: str, mapping: dict, sector: tuple, predio: str = "AM") -> dict:
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, data_only=True)["Mapeo"]
    rows_in = [r for r in ws.iter_rows(values_only=True)
               if r[0] in mapping and isinstance(r[3], (int, float))]
    field = json.loads((ROOT / "assets" / "maps" / f"{predio}_hileras.json").read_text(encoding="utf-8"))
    spacing = .7
    out = []
    for label, field_n in mapping.items():
        cand = [r for r in field["rows"] if r[1] == field_n and (r[2], r[3]) == sector]
        if not cand:
            raise SystemExit(f"No está la hilera {field_n} del sector {sector} en el plano")
        frow = max(cand, key=lambda r: r[5])
        holes, segs = [], []
        for h, tramo, cant, d0, d1, pn, hd, hh, largo, bloque, var, tipo, nota in (r[:13] for r in rows_in
                                                                                      if r[0] == label):
            if isinstance(var, (int, float)) or str(var).strip().isdigit():
                var = f"#{int(float(var))}"                 # códigos numéricos: «#24»
            var = VARIETIES.get(str(var), str(var) if var else "")
            segs.append({"d0": d0, "d1": d1, "kind": "drenaje" if str(tipo).startswith("Drenaje") else
                         KINDS.get(tipo, "separacion"), "var": var, "bloque": bloque or 0, "note": nota or ""})
            if hd is None:
                continue
            nums = []
            if pn:
                a, b = (int(x) for x in re.split(r"[–-]", str(pn)))
                nums = list(range(a, b + 1))
            kind = KINDS.get(tipo, "separacion")
            for k, hoyo in enumerate(range(int(hd), int(hh) + 1)):
                holes.append([hoyo, round(d0 + (k + .5) * spacing, 2), kind,
                              var if kind in ("planta", "falla", "eliminada") else "",
                              bloque or 0, nums[k] if k < len(nums) else 0])
        out.append({"label": label, "field_key": frow[0], "field_n": field_n, "sector": sector[0],
                    "equipo": sector[1], "largo": max(s["d1"] for s in segs),
                    "plantas": sum(1 for x in holes if x[2] == "planta"), "holes": holes, "segments": segs})
    return {"version": 1, "code": code, "name": name, "predio": predio, "spacing": spacing,
            "source": Path(xlsx).name, "rows": out}


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in argv[1:] if a.startswith("--"))
    if len(args) < 4:
        print(__doc__)
        return 1
    xlsx, code, name = args[:3]
    mapping = {k: int(v) for k, v in (a.split("=") for a in args[3:])}
    s, e = (int(x) for x in opts.get("sector", "1-2").split("-"))
    data = build(xlsx, code.upper(), name, mapping, (s, e))
    path = ROOT / "assets" / "plantas" / f"{code.upper()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for r in data["rows"]:
        print(f"{r['label']} = hilera {r['field_n']} (S{r['sector']}·E{r['equipo']}): "
              f"{len(r['holes'])} hoyos, {r['plantas']} plantas, {r['largo']} m")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
