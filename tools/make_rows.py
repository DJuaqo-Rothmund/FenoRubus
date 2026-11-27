"""
tools/make_rows.py
==================
Hileras del campo para el módulo Plantas: cruza el plano de construcción (DXF, capa
HILERAS, en UTM) con la «Planilla de código de hileras» y deja el resultado en el mismo
sistema de metros que el plano de sectores del predio (assets/maps/<código>.json).

    python tools/make_rows.py plano.dxf planilla.xlsx AM
    -> assets/maps/AM_hileras.json

(Un .dwg se pasa antes a DXF, p. ej. con dwg2dxf de LibreDWG.)

Regla de numeración: el número de hilera es la COLUMNA del campo, de oeste a este, cada
~3 m; por eso el mismo número se repite en varios sectores (uno al norte del otro). Las
columnas del plano se alinean con los números de la planilla comparando la secuencia de
largos (programación dinámica): así se absorben los huecos anchos del plano.

Cada línea del plano queda con su fila de la planilla (sector, equipo, N/S, largo,
plantas, variedad, año) o marcada «por revisar» (tramos cortados distinto, duplicados).
Necesita ezdxf, openpyxl y pyproj (solo aquí; la app no los usa).
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UTM_EPSG = 32718            # UTM 18 sur (Los Ríos)
TOL_SEQ = 0.6               # m: largos «iguales» al alinear columnas
TOL_ROW = 1.5               # m: largo de una línea vs. su fila de la planilla


def read_lines(dxf_path: str) -> list[dict]:
    from ezdxf import recover
    doc, _ = recover.readfile(dxf_path)
    out = []
    for e in doc.modelspace().query("LWPOLYLINE[layer=='HILERAS']"):
        pts = [p[:2] for p in e.get_points()]
        if len(pts) < 2:
            continue
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        if y0 > y1:
            x0, y0, x1, y1 = x1, y1, x0, y0          # siempre de sur a norte
        L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** .5
        if L < 1:                                    # líneas sin largo (restos del dibujo)
            continue
        out.append(dict(ux0=x0, uy0=y0, ux1=x1, uy1=y1, x=(x0 + x1) / 2, L=L))
    return out


def read_planilla(xlsx: str) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["Datos actualizados"]
    out = []
    for r in ws.iter_rows(min_row=3, values_only=True):
        if isinstance(r[1], int) and isinstance(r[2], int):
            ns = (r[4] or "").strip().upper() if isinstance(r[4], str) else ""
            out.append(dict(n=r[1], s=r[2], e=r[3], ns=ns,
                            L=float(r[5]) if isinstance(r[5], (int, float)) else None,
                            pl=int(r[7]) if isinstance(r[7], (int, float)) else None,
                            var=str(r[8] or ""), anio=str(r[9] or "")))
    return out


def columns(lines: list[dict]) -> list[list[dict]]:
    cols: list[list[dict]] = []
    for r in sorted(lines, key=lambda r: r["x"]):
        if cols and r["x"] - cols[-1][-1]["x"] < .5:
            cols[-1].append(r)
        else:
            cols.append([r])
    return cols


def align(cols, byn) -> dict[int, int]:
    """Columna -> número de hilera (máximo de largos coincidentes, en orden)."""
    N, C = max(byn), len(cols)

    def score(i, n):
        ps = [p["L"] for p in byn.get(n, []) if p["L"]]
        return sum(1 for r in cols[i] if any(abs(L - r["L"]) < TOL_SEQ for L in ps))

    neg = -1e9
    dp = [[neg] * (N + 1) for _ in range(C + 1)]
    bk = [[0] * (N + 1) for _ in range(C + 1)]
    for n in range(N + 1):
        dp[0][n] = 0
    for i in range(1, C + 1):
        row, prev = dp[i], dp[i - 1]
        for n in range(1, N + 1):
            a = prev[n - 1] + score(i - 1, n)
            b = row[n - 1] - .01            # número sin columna (hileras que no están en el plano)
            c = prev[n] - .5                # columna sin número
            if a >= b and a >= c:
                row[n], bk[i][n] = a, 1
            elif b >= c:
                row[n], bk[i][n] = b, 2
            else:
                row[n], bk[i][n] = c, 3
    i, n, num = C, N, {}
    while i > 0 and n > 0:
        k = bk[i][n]
        if k == 1:
            num[i - 1] = n
            i, n = i - 1, n - 1
        elif k == 2:
            n -= 1
        else:
            i -= 1
    return num


def build(dxf_path: str, xlsx: str, code: str) -> dict:
    from pyproj import Transformer
    plan = json.loads((ROOT / "assets" / "maps" / f"{code}.json").read_text(encoding="utf-8"))
    g = plan["geo"]
    to_ll = Transformer.from_crs(UTM_EPSG, 4326, always_xy=True)

    def to_plan(x, y):
        lon, lat = to_ll.transform(x, y)
        return round(lon * g["kx"] - g["x0"], 2), round(lat * g["ky"] - g["y0"], 2)

    lines, P = read_lines(dxf_path), read_planilla(xlsx)
    byn = collections.defaultdict(list)
    for p in P:
        byn[p["n"]].append(p)
    cols = columns(lines)
    num = align(cols, byn)
    seen = collections.Counter()
    rows = []
    for i, col in enumerate(cols):
        n = num.get(i)
        cand = list(byn.get(n, [])) if n else []
        for r in sorted(col, key=lambda r: -r["L"]):
            m = [p for p in cand if p["L"] and abs(p["L"] - r["L"]) < TOL_ROW]
            p = min(m, key=lambda p: abs(p["L"] - r["L"])) if m else None
            if p:
                cand.remove(p)
            sig = (round(r["x"], 1), round(r["uy0"]), round(r["uy1"]))
            seen[sig] += 1
            dup = seen[sig] > 1
            r.update(n=n, p=p, dup=dup)
            rows.append(r)
    # Sin fila en la planilla: sector y equipo del polígono de Predio donde cae (o de las
    # vecinas), «por revisar».
    ok = [r for r in rows if r["p"]]

    def in_ring(ring, x, y):
        inside, n = False, len(ring) // 2
        j = n - 1
        for i in range(n):
            xi, yi, xj, yj = ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def sector_at(ux, uy):
        x, y = to_plan(ux, uy)
        for sec in plan["sectors"]:
            if any(in_ring(ring, x, y) for ring in sec["parts"]):
                return sec["sector"], sec["equipo"]
        return None
    out = []
    for r in sorted(rows, key=lambda r: (r["x"], r["uy0"])):
        p = r["p"]
        s = e = None
        if p:
            s, e = p["s"], p["e"]
        elif sector_at(r["x"], (r["uy0"] + r["uy1"]) / 2):
            s, e = sector_at(r["x"], (r["uy0"] + r["uy1"]) / 2)
        else:
            near = collections.Counter((k["p"]["s"], k["p"]["e"]) for k in ok
                                       if abs(k["x"] - r["x"]) < 12 and k["uy0"] < r["uy1"] + 5
                                       and k["uy1"] > r["uy0"] - 5)
            if near:
                s, e = near.most_common(1)[0][0]
        x0, y0 = to_plan(r["ux0"], r["uy0"])
        x1, y1 = to_plan(r["ux1"], r["uy1"])
        flag = 2 if r["dup"] else (0 if p else 1)
        out.append([r["n"] or 0, s or 0, e or 0, (p or {}).get("ns", ""), (p or {}).get("L") or round(r["L"], 1),
                    (p or {}).get("pl") or 0, (p or {}).get("var", ""), (p or {}).get("anio", ""),
                    x0, y0, x1, y1, flag, round(r["L"], 1)])
    # Clave estable: número + posición (m, sur) en el plano; las copias, con sufijo.
    keys = collections.Counter()
    for o in out:
        k = f"{o[0]}@{round(o[8])},{round(o[9])}"
        keys[k] += 1
        o.insert(0, k if keys[k] == 1 else f"{k}#{keys[k]}")
    return {"version": 1, "name": plan["name"], "spacing": .7, "source": Path(dxf_path).name,
            "fields": ["key", "n", "s", "e", "ns", "L", "pl", "var", "anio", "x0", "y0", "x1", "y1",
                       "flag", "L_plano"],
            "rows": out}


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 1
    data = build(argv[1], argv[2], argv[3].upper())
    path = ROOT / "assets" / "maps" / f"{argv[3].upper()}_hileras.json"
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    flags = collections.Counter(r[13] for r in data["rows"])
    print(f"{path.name}: {len(data['rows'])} hileras · calzan {flags[0]} · por revisar {flags[1]} · "
          f"repetidas {flags[2]} · {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
