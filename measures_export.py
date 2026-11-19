"""
measures_export.py
==================
Exporta las mediciones personalizadas a Excel (.xlsx) sin librerías externas.

El .xlsx es un ZIP con XML (SpreadsheetML). Se escribe lo mínimo que Excel,
Google Sheets y LibreOffice abren sin quejas: textos en línea, números como
números (acepta coma decimal: «23,5» -> 23.5), fila de encabezado en negrita,
columnas con ancho cómodo y el encabezado fijo al desplazarse.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import zipfile
from xml.sax.saxutils import escape

import phenology as ph
from platform_utils import data_subdir, slugify

_NUM = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)$")
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def as_number(value):
    """«23,5» -> 23.5 · «12» -> 12 · cualquier otra cosa -> None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value or "").strip()
    if not _NUM.match(text):
        return None
    n = float(text.replace(",", "."))
    return int(n) if n.is_integer() and "." not in text and "," not in text else n


def _col(i: int) -> str:
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return name


def _cell(ref: str, value, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    n = as_number(value)
    if n is not None:
        return f'<c r="{ref}"{s}><v>{n}</v></c>'
    text = escape(_BAD_XML.sub("", str(value if value is not None else "")))
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(rows: list[list]) -> str:
    widths = {}
    for row in rows:
        for j, v in enumerate(row):
            widths[j] = min(60, max(widths.get(j, 8), len(str(v if v is not None else "")) + 2))
    cols = "".join(f'<col min="{j + 1}" max="{j + 1}" width="{w}" customWidth="1"/>'
                   for j, w in sorted(widths.items()))
    body = []
    for i, row in enumerate(rows):
        cells = "".join(_cell(f"{_col(j)}{i + 1}", v, 1 if i == 0 else 0) for j, v in enumerate(row))
        body.append(f'<row r="{i + 1}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'{"<cols>" + cols + "</cols>" if cols else ""}'
            f'<sheetData>{"".join(body)}</sheetData></worksheet>')


def write_xlsx(path: str, sheets: list[tuple[str, list[list]]]) -> str:
    """sheets: [(nombre_hoja, filas)] — la primera fila de cada hoja es el encabezado."""
    names, used = [], set()
    for name, _rows in sheets:
        base = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Hoja"
        n, cand = 1, base
        while cand.lower() in used:
            n += 1
            cand = f"{base[:28]} {n}"
        used.add(cand.lower())
        names.append(cand)
    ct = "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/'
                 f'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                 for i in range(len(sheets)))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                    f'{ct}</Types>')
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                    '</Relationships>')
        zf.writestr("xl/workbook.xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                    + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                              for i, n in enumerate(names))
                    + '</sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/'
                              f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                              for i in range(len(sheets)))
                    + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/'
                      'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        zf.writestr("xl/styles.xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
                    '<fill><patternFill patternType="gray125"/></fill></fills>'
                    '<borders count="1"><border/></borders>'
                    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                    '</styleSheet>')
        for i, (_name, rows) in enumerate(sheets):
            zf.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(rows))
    return path


def photo_marks() -> dict:
    """Marcas de cajas del cultivo abierto (training_labels: marcas.json local)."""
    try:
        from platform_utils import get_data_dir
        from training_labels import LabelStore
        return LabelStore(get_data_dir()).data["photos"]
    except Exception:  # noqa: BLE001 (sin marcas: el Excel sale sin conteos)
        return {}


def measure_rows(db, measure: dict, season: int | None = None, labels: dict | None = None) -> list[list]:
    """Filas (con encabezado) de una medición para toda la temporada. labels: marcas de cajas
    por nombre de foto (por defecto, las del teléfono)."""
    cfg = db.sheet_first()
    head = ["Semana del año", "Año", "Inicio de semana", cfg["title"]]
    names = db.treatment_names()
    vmap = {v["id"]: v for v in db.list_varieties(include_archived=True)}
    if measure["kind"] == "table":
        head += measure["columns"]
        # Columnas que ya no están en la definición, pero tienen datos: no se pierden.
        extra = []
        entries = [e for e in db.list_entries(measure["id"], season=season)
                   if any(str(v).strip() for v in e["data"].values())]   # sin filas vacías
        for e in entries:
            for k in e["data"]:
                if k not in measure["columns"] and k not in extra:
                    extra.append(k)
        head += extra
    else:
        entries = db.list_entries(measure["id"], season=season)
        head += ["Descripción", "Archivo"]
        # Conteo con cajas (IA+ / «Contar» en la foto): una columna por estructura y el total.
        import training_labels as tl
        marks = photo_marks() if labels is None else labels
        counted = {os.path.basename(e["path"] or ""): tl.counts(marks.get(os.path.basename(e["path"] or "")))
                   for e in entries}
        seen = {k for got in counted.values() if got for k in got}
        stages = [k for k, _n, _c in tl.CLASSES if k in seen] + sorted(seen - set(tl.NAMES))
        if any(v is not None for v in counted.values()):
            head += [tl.NAMES.get(k, k) for k in stages] + ["Total estructuras"]
    head.append("Registrado")
    rows = [head]
    for e in entries:
        week, year = ph.iso_week(e["start_date"])
        start = _dt.date.fromisoformat(e["start_date"][:10])
        row = [week, year, f"{start:%d-%m-%Y}", db.sheet_label(vmap.get(e["variety_id"]), names, cfg)]
        if measure["kind"] == "table":
            row += [e["data"].get(c, "") for c in head[4:-1]]
        else:
            name = os.path.basename(e["path"] or "")
            row += [e["caption"] or "", name]
            if "Total estructuras" in head:
                got = counted.get(name)
                row += ([got.get(k, 0) for k in stages] + [sum(got.values())] if got is not None
                        else [""] * (len(stages) + 1))
        row.append(e["created_at"].replace("T", " ")[:16])
        rows.append(row)
    return rows


def long_rows(rows: list[list]) -> list[list] | None:
    """Planilla por plantas en formato largo (una fila por planta): Semana, Año, Inicio,
    Tratamiento, [Rep.], Muestra y una columna por evaluación. Para análisis (tablas
    dinámicas, InfoStat, R). None si la planilla no tiene columnas subdivididas."""
    import sheet_layout as SL
    head = rows[0]
    data_cols = head[4:-1]
    if not SL.is_grouped(data_cols):
        return None
    evals, samples = [], []
    for col in data_cols:
        g, sub = SL.split(col)
        if g is None:
            continue
        if sub not in evals:
            evals.append(sub)
        if g not in samples:
            samples.append(g)
    loose = [c for c in data_cols if SL.split(c)[0] is None]
    out = [head[:4] + loose + ["Muestra"] + evals]
    for r in rows[1:]:
        vals = dict(zip(head, r))
        base = r[:4] + [vals.get(c, "") for c in loose]
        for g in samples:
            got = [vals.get(SL.join(g, ev), "") for ev in evals]
            if any(str(v).strip() for v in got):
                out.append(base + [g] + got)
    return out


def export_measures(db, measure_ids: list[int], season: int | None = None,
                    dest_dir: str | None = None, labels: dict | None = None) -> str:
    """Un .xlsx con una hoja por medición. Devuelve la ruta."""
    measures = [m for m in (db.get_measure(i) for i in measure_ids) if m]
    if not measures:
        raise ValueError("No hay mediciones para exportar.")
    dest_dir = dest_dir or data_subdir("reports")
    stem = slugify(measures[0]["name"]) if len(measures) == 1 else "mediciones"
    code = f"{db.code}_" if getattr(db, "code", "") else ""
    path = os.path.join(dest_dir, f"{stem}_{code}{season or 'todas'}_{_dt.datetime.now():%Y%m%d_%H%M}.xlsx")
    labels = photo_marks() if labels is None else labels
    sheets, failed = [], []
    for m in measures:
        # Una medición con un dato raro no impide bajar las demás: su hoja dice qué pasó.
        try:
            rows = measure_rows(db, m, season, labels)
            longer = long_rows(rows) if m["kind"] == "table" else None
        except Exception as exc:  # noqa: BLE001
            failed.append(m["name"])
            sheets.append((m["name"], [["No se pudo exportar esta medición"], [f"{type(exc).__name__}: {exc}"]]))
            continue
        sheets.append((m["name"], rows))
        if longer:
            sheets.append((f"{m['name'][:20]} por muestra", longer))
    if failed and len(failed) == len(measures):
        raise ValueError("No se pudo exportar: " + sheets[0][1][1][0])
    write_xlsx(path, sheets)
    db.log("export", "measures", None, os.path.basename(path))
    return path
