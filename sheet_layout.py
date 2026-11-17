"""
sheet_layout.py
===============
Planillas con columnas SUBDIVIDIDAS: «Planta 1» con dentro «N.º laterales», «Largo
laterales»…, luego «Planta 2» con las mismas, y así hasta n.

No cambia cómo se guardan los datos: cada subcolumna es una columna normal llamada
«Planta 1 · N.º laterales» (así funcionan la sincronización, la web, el Excel y las
planillas antiguas). La grilla agrupa las columnas por lo que va antes de « · ».
(= web/sheet.js)
"""
from __future__ import annotations

SEP = " · "
MAX_SAMPLES, MAX_VARS = 50, 20
REP_COL = "Rep."


def split(col: str) -> tuple[str | None, str]:
    """«Planta 1 · Largo» → ("Planta 1", "Largo"); «Notas» → (None, "Notas")."""
    if SEP in col:
        group, sub = col.split(SEP, 1)
        if group.strip() and sub.strip():
            return group, sub
    return None, col


def join(group: str | None, sub: str) -> str:
    return f"{group}{SEP}{sub}" if group else sub


def groups(cols: list[str]) -> list[tuple[str | None, list[str]]]:
    """Columnas seguidas con el mismo grupo: [("Planta 1", [...3]), (None, ["Notas"]), …]."""
    out: list[tuple[str | None, list[str]]] = []
    for col in cols:
        g, _s = split(col)
        if g is not None and out and out[-1][0] == g:
            out[-1][1].append(col)
        else:
            out.append((g, [col]))
    return out


def is_grouped(cols: list[str]) -> bool:
    return any(split(c)[0] is not None for c in cols)


def parse_vars(text: str) -> list[str]:
    """Evaluaciones escritas una por línea (o separadas por coma / punto y coma)."""
    raw = (text or "").replace(";", "\n").replace(",", "\n").split("\n")
    out = []
    for v in raw:
        v = " ".join(v.replace(SEP.strip(), " ").split())
        if v and v not in out:
            out.append(v)
    return out[:MAX_VARS]


def build(variables: list[str], samples: int = 1, sample_name: str = "Planta",
          reps_col: bool = False) -> list[str]:
    """Columnas de la planilla: con 2 o más muestras, una subcolumna por evaluación dentro de
    cada muestra («Planta 1 · …», «Planta 2 · …»); con 1, solo las evaluaciones."""
    variables = [v for v in variables if v]
    if not variables:
        raise ValueError("Escriba al menos una evaluación (ej.: N.º laterales).")
    samples = max(1, min(MAX_SAMPLES, int(samples or 1)))
    sample_name = " ".join((sample_name or "Planta").replace(SEP.strip(), " ").split()) or "Planta"
    cols = [REP_COL] if reps_col else []
    if samples == 1:
        return cols + list(variables)
    return cols + [join(f"{sample_name} {i}", v) for i in range(1, samples + 1) for v in variables]


def describe(cols: list[str]) -> str:
    """Resumen corto: «Planta 1…5 × 3 evaluaciones (15 columnas)»."""
    gs = [g for g, _c in groups(cols) if g]
    if not gs:
        return f"{len(cols)} columna(s): " + ", ".join(cols[:6]) + ("…" if len(cols) > 6 else "")
    subs = groups(cols)
    first = next(c for g, c in subs if g)
    return (f"{gs[0]} … {gs[-1]} ({len(gs)}) × {len(first)} evaluación(es): "
            + ", ".join(split(c)[1] for c in first) + f" · {len(cols)} columnas")


def rename_group(cols: list[str], old: str, new: str) -> list[str]:
    """Cambia el nombre de un grupo (todas sus subcolumnas)."""
    return [join(new, split(c)[1]) if split(c)[0] == old else c for c in cols]


def rename_sub(cols: list[str], sub: str, new: str) -> list[tuple[str, str]]:
    """Cambiar una evaluación en TODOS los grupos: pares (vieja, nueva)."""
    out = []
    for c in cols:
        g, s = split(c)
        if g is not None and s == sub:
            out.append((c, join(g, new)))
    return out


def next_group(cols: list[str]) -> tuple[str, list[str]] | None:
    """Otra muestra al final: («Planta 6», sus columnas) copiando las evaluaciones de la última."""
    gs = [(g, c) for g, c in groups(cols) if g]
    if not gs:
        return None
    last, sub = gs[-1]
    head, _sp, num = last.rpartition(" ")
    names = {g for g, _c in gs}
    if num.isdigit():
        n = int(num) + 1
        while f"{head} {n}" in names:
            n += 1
        name = f"{head} {n}"
    else:
        n = 2
        while f"{last} {n}" in names:
            n += 1
        name = f"{last} {n}"
    return name, [join(name, split(c)[1]) for c in sub]


def add_sub(cols: list[str], name: str) -> list[str]:
    """Otra evaluación dentro de CADA grupo (al final de cada uno)."""
    out = []
    for g, cs in groups(cols):
        out += cs
        if g is not None:
            out.append(join(g, name))
    return out


def unit_word(cols: list[str]) -> str:
    """«plantas», «cañas»…: la palabra de los grupos en plural (para los menús)."""
    g = next((g for g, _c in groups(cols) if g), "")
    head = g.rpartition(" ")[0] if g.rpartition(" ")[2].isdigit() else g
    head = (head or "muestra").lower()
    return head if head.endswith("s") else head + ("es" if head[-1:] in "lrnd" else "s")
