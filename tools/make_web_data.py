"""
tools/make_web_data.py
======================
Datos de la versión web, generados desde la app para que nunca difieran:

* web/bbch.json   escala BBCH, estadios principales y colores (phenology.py)
* web/report.css  estilo de los informes (templates/base.html)
* web/maps/*.json planos de sector de los predios (assets/maps)

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

    import re
    import shutil
    from reporter import seq_color
    html = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    css = re.sub(r"\{\{\s*(\d+)\|seq\|first\s*\}\}", lambda m: seq_color(int(m.group(1)))[0], css)
    assert "{{" not in css and "{%" not in css
    with open(os.path.join(ROOT, "web", "report.css"), "w", encoding="utf-8") as f:
        f.write(css.strip() + "\n")
    maps = os.path.join(ROOT, "web", "maps")
    os.makedirs(maps, exist_ok=True)
    for name in os.listdir(os.path.join(ROOT, "assets", "maps")):
        if name.endswith(".json"):
            shutil.copy(os.path.join(ROOT, "assets", "maps", name), os.path.join(maps, name))
    print("report.css y", len(os.listdir(maps)), "plano(s)")


if __name__ == "__main__":
    main()
