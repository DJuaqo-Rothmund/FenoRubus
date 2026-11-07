"""
tools/make_web_data.py
======================
Datos de la versión web, generados desde la app para que nunca difieran:

* web/bbch.json   escala BBCH, estadios principales y colores (phenology.py)
* web/report.css  estilo de los informes (templates/base.html)
* web/maps/*.json planos de sector de los predios (assets/maps)
* web/py.zip      código de informes de la app (PDF idénticos, con Pyodide en el navegador)

    python tools/make_web_data.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import phenology as ph  # noqa: E402


def scale(crop_id: str) -> dict:
    """Escala BBCH, estadios principales y colores de un cultivo (phenology.set_crop)."""
    ph.set_crop(crop_id)
    try:
        return {
            "stages": [{"code": c, "label": label, "macro": ph.macro_of(c), "text": ph.code_str(c)}
                       for c, label, _desc, _kw in ph.BBCH_SCALE],
            "macros": {str(k): v for k, v in ph.MACRO_STAGES.items()},
            "colors": {str(k): v for k, v in ph.MACRO_COLORS.items()},
        }
    finally:
        ph.set_crop("frambuesa")


def main():
    import crops
    # Arriba la de frambuesa (PhenoRubus, como siempre); en «crops», la de cada cultivo.
    data = {"version": ph.BBCH_SCALE_VERSION, **scale("frambuesa"),
            "crops": {c.app: scale(c.id) for c in crops.CROPS.values()}}
    out = os.path.join(ROOT, "web", "bbch.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(out, len(data["stages"]), "estados", {k: len(v["stages"]) for k, v in data["crops"].items()})
    images()

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
    py_zip()


def images():
    """Logos de AeonCrop, de cada cultivo y de AeonScout para la web (achicados)."""
    from PIL import Image
    web = os.path.join(ROOT, "web")

    def put(src, dst, side):
        im = Image.open(os.path.join(ROOT, *src.split("/"))).convert("RGBA")
        im.thumbnail((side, side), Image.LANCZOS)
        os.makedirs(os.path.dirname(os.path.join(web, dst)), exist_ok=True)
        im.save(os.path.join(web, dst), optimize=True)
    put("assets/ui/aeoncrop.png", "aeon_logo.png", 480)
    put("assets/icon_aeoncrop.png", "aeon_icon.png", 192)
    put("assets/ui/logo.png", "crops/phenorubus.png", 256)
    put("assets/crops/arandano/logo.png", "crops/phenoblue.png", 256)
    put("assets/crops/cranberry/logo.png", "crops/phenocran.png", 256)
    for name in ("scout_logo", "scout_plagas", "scout_malezas", "scout_enfermedades"):
        put(f"assets/ui/{name}.png", f"scout/{name}.png", 192)


PY_MODULES = ["phenology", "crops", "database", "sync", "reporter", "pdf_report", "pdfdoc", "platform_utils",
              "trial_stats", "measures_export", "workspaces", "geo"]


def py_zip():
    import zipfile
    out = os.path.join(ROOT, "web", "py.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for m in PY_MODULES:
            z.write(os.path.join(ROOT, f"{m}.py"), f"{m}.py")
        z.write(os.path.join(ROOT, "tools", "web", "webreport.py"), "webreport.py")
        for name in sorted(os.listdir(os.path.join(ROOT, "templates"))):
            z.write(os.path.join(ROOT, "templates", name), f"templates/{name}")
        z.write(os.path.join(ROOT, "assets", "ui", "logo_line_report.png"), "assets/ui/logo_line_report.png")
    print(out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
