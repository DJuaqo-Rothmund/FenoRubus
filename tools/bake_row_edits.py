"""
tools/bake_row_edits.py
=======================
Incorpora al plano de la app las correcciones de hileras hechas en el teléfono, para que
una instalación nueva ya venga corregida:

    python tools/bake_row_edits.py "Hileras corregidas AM.json"
    -> assets/maps/AM_hileras.json (actualizado)

El archivo lo deja la app en Drive («AeonCrop/<módulo>/Plantas/Hileras corregidas AM.json»;
se actualiza al sincronizar o con el botón de la nube en «Hileras del campo»).

* Hilera corregida: sus datos pasan a ser los del plano (número, subtítulo N/S, sector,
  equipo, largo, plantas, variedad, año) y deja de estar «por revisar».
* Repetida, «no es hilera» o unida a otra: sale del plano.
* Las claves no cambian: lo ya corregido en otros teléfonos sigue calzando (y, si se
  vuelve a importar, no hace nada nuevo).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {"n": "n", "ns": "ns", "sector": "s", "equipo": "e", "largo": "L", "plantas": "pl",
          "variedad": "var", "anio": "anio"}


def bake(asset: dict, edits: list[dict]) -> tuple[dict, dict]:
    names = asset["fields"]
    idx = {name: i for i, name in enumerate(names)}
    by_key = {r[0]: r for r in asset["rows"]}
    stats = {"corregidas": 0, "quitadas": 0, "sin_hilera": 0}
    drop = set()
    for e in edits:
        row = by_key.get(e["key"])
        if row is None:
            stats["sin_hilera"] += 1
            continue
        if e.get("estado") in ("dup", "no", "unida"):
            drop.add(e["key"])
            stats["quitadas"] += 1
            continue
        for src, dst in FIELDS.items():
            if src in e and e[src] not in (None, ""):
                row[idx[dst]] = e[src]
        if e.get("estado") == "ok" or any(src in e for src in FIELDS):
            row[idx["flag"]] = 0
        stats["corregidas"] += 1
    asset["rows"] = [r for r in asset["rows"] if r[0] not in drop]
    return asset, stats


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 1
    data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    path = ROOT / "assets" / "maps" / f"{data['predio']}_hileras.json"
    asset = json.loads(path.read_text(encoding="utf-8"))
    asset, stats = bake(asset, data["edits"])
    asset["baked"] = data.get("exported_at", "")
    path.write_text(json.dumps(asset, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    flags = [r[asset["fields"].index("flag")] for r in asset["rows"]]
    print(f"{path.name}: {stats['corregidas']} corregidas, {stats['quitadas']} quitadas"
          f"{', ' + str(stats['sin_hilera']) + ' sin hilera' if stats['sin_hilera'] else ''} · "
          f"quedan {len(asset['rows'])} hileras, {sum(1 for f in flags if f)} por revisar")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
