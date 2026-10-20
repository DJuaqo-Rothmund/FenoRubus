"""
tools/make_web_data.py
======================
Genera web/bbch.json (escala BBCH, estadios principales y colores) desde phenology.py,
para que la versión web use exactamente la misma escala que la app.

    python tools/make_web_data.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import phenology as ph  # noqa: E402


def main():
    data = {
        "version": ph.BBCH_SCALE_VERSION,
        "stages": [{"code": c, "label": label, "macro": ph.macro_of(c), "text": ph.code_str(c)}
                   for c, label, _desc, _kw in ph.BBCH_RUBUS],
        "macros": {str(k): v for k, v in ph.MACRO_STAGES.items()},
        "colors": {str(k): v for k, v in ph.MACRO_COLORS.items()},
    }
    out = os.path.join(ROOT, "web", "bbch.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(out, len(data["stages"]), "estados")


if __name__ == "__main__":
    main()
