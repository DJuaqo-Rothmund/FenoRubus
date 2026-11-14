"""
season_compare.py
=================
Informe «Comparación entre temporadas»: ¿vamos adelantados o atrasados respecto de la
temporada anterior (o del promedio de varias), y por qué?

* Calor: °C·día acumulados a la misma altura de la temporada (mismo número de días desde el
  1 de septiembre), días de adelanto o atraso térmico y resumen por mes.
* Hitos BBCH de cada variedad: fecha y °C·día este año y en las temporadas de referencia.
  Si la fecha cambió pero el calor necesario fue casi el mismo, la diferencia la explica el
  CLIMA; si también cambió el calor, es algo propio de la VARIEDAD o del MANEJO.
* Estado a la misma fecha, curvas BBCH según °C·día superpuestas y fotos del mismo estado.

Las referencias son una lista de temporadas: hoy la anterior; con más años, su promedio.
Puro Python (sin Kivy).
"""
from __future__ import annotations

import datetime as _dt

import degree_days as gd
import phenology as ph

DAYS_T = 5          # días de diferencia a partir de los cuales una fecha «cambió»
GDD_T = 40          # °C·día de diferencia a partir de los cuales el calor necesario «cambió»
MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def season_label(season: int) -> str:
    return f"{season}-{str(season + 1)[-2:]}"


def available_seasons(db, season: int, limit: int = 5) -> list[int]:
    """Temporadas anteriores con estados BBCH en este ensayo (la más reciente primero)."""
    rows = db.query("SELECT DISTINCT w.season FROM observations o JOIN sampling_weeks w ON w.id = o.week_id "
                    "WHERE o.bbch_code IS NOT NULL AND w.season < ? ORDER BY w.season DESC", (season,))
    return [r["season"] for r in rows][:limit]


def _offset(day: _dt.date, season: int) -> int:
    return (day - gd.biofix(season)).days


def _at_offset(season: int, off: int) -> _dt.date:
    return gd.biofix(season) + _dt.timedelta(days=off)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def verdict(d_days: float | None, d_gdd: float | None) -> str:
    """«clima», «manejo» (variedad / manejo) o «igual»."""
    if d_gdd is not None and abs(d_gdd) >= GDD_T:
        return "manejo"
    if d_days is not None and abs(d_days) >= DAYS_T:
        return "clima"
    return "igual"


VERDICTS = {"clima": "clima", "manejo": "variedad / manejo", "igual": "igual", "pred": "≈ pronóstico",
            "na": ""}


# ====================================================================== calor
def thermal(cur: gd.Series, refs: dict[int, gd.Series]) -> dict:
    out = {"now": cur.total, "day": cur.last, "refs": {}}
    if not cur.days:
        return out
    off = _offset(cur.last, cur.season)
    for r, s in refs.items():
        if not s.days:
            continue
        same = _at_offset(r, off)
        at = s.acc_at(same)
        hit = next((x["day"] for x in s.days if x["acc"] >= cur.total), None)
        out["refs"][r] = {"at": at, "same": same, "delta": cur.total - at if at is not None else None,
                          "ahead": (hit - same).days if hit else None, "hit": hit}
    vals = [v for v in out["refs"].values() if v["at"] is not None]
    if vals:
        at = _mean([v["at"] for v in vals])
        out["mean"] = {"at": at, "delta": cur.total - at,
                       "ahead": _mean([v["ahead"] for v in vals if v["ahead"] is not None])}
    return out


def monthly(cur: gd.Series, refs: dict[int, gd.Series]) -> list[dict]:
    """Por mes (desde septiembre hasta el mes actual): T media y °C·día de cada temporada, en
    el mismo tramo (el mes en curso, hasta el mismo día)."""
    if not cur.days:
        return []
    last_off = _offset(cur.last, cur.season)
    rows = []
    months = []
    for x in cur.days:
        if x["day"].month not in months:
            months.append(x["day"].month)

    def stats(s: gd.Series, month: int):
        days = [x for x in s.days if x["day"].month == month and _offset(x["day"], s.season) <= last_off]
        if not days:
            return None
        return {"t": sum(x["tmean"] for x in days) / len(days), "g": sum(x["gdd"] for x in days), "n": len(days)}
    for m in months:
        c = stats(cur, m)
        part = cur.last.month == m and cur.last.day < 28
        rows.append({"month": m, "name": MESES[m] + (f" (al {cur.last.day})" if part else ""), "cur": c,
                     "refs": {r: stats(s, m) for r, s in refs.items()}})
    return rows


# ====================================================================== hitos por variedad
def compare(db, season: int, weather: dict[int, list[dict]], refs: list[int], groups: dict[int, str] | None = None,
            tbase: float = gd.TBASE, milestones=gd.MILESTONES) -> dict:
    """weather: {temporada: filas de temperatura}; refs: temporadas de referencia."""
    if groups is None:
        groups = gd.groups_for(db)[0]
    series = {s: gd.Series(weather.get(s) or [], s, tbase) for s in [season] + list(refs)}
    pts = {s: gd.unit_points(gd.observations(db, s), series[s], groups) for s in series}
    names = [n for n in dict.fromkeys(groups.values()) if any(n in pts[s] for s in pts)]
    cur = series[season]
    rate = cur.rate()
    units = []
    for name in names:
        rows = []
        for code, label in milestones:
            c = gd.reached(pts[season].get(name, []), code)
            r_hits = {r: gd.reached(pts[r].get(name, []), code) for r in refs}
            r_valid = {r: h for r, h in r_hits.items() if h}
            if not r_valid and not c:
                continue
            base_off = _mean([_offset(h["day"], r) for r, h in r_valid.items()])
            base_gdd = _mean([h["gdd"] for h in r_valid.values()])
            row = {"code": code, "label": label, "cur": c, "refs": r_hits, "base_off": base_off,
                   "base_gdd": base_gdd, "base_day": (_at_offset(season, round(base_off))
                                                       if base_off is not None else None)}
            if c and r_valid:
                row["d_days"] = _offset(c["day"], season) - base_off
                row["d_gdd"] = (c["gdd"] - base_gdd) if c["gdd"] is not None and base_gdd is not None else None
                row["verdict"] = verdict(row["d_days"], row["d_gdd"])
            elif not c and base_gdd is not None and cur.days and pts[season].get(name):
                left = base_gdd - cur.total
                if left <= 0:
                    row["pred"] = {"need": base_gdd, "left": 0, "day": None, "overdue": True}
                else:
                    n = round(left / rate) if rate > .05 else None
                    row["pred"] = {"need": base_gdd, "left": left, "overdue": False,
                                   "day": cur.last + _dt.timedelta(days=n) if n is not None else None}
                row["verdict"] = "pred"
            else:
                row["verdict"] = "na"
            rows.append(row)
        same = None
        cp = pts[season].get(name) or []
        if cp:
            last = cp[-1]
            off = _offset(last["day"], season)
            back = {}
            for r in refs:
                before = [p for p in pts[r].get(name, []) if _offset(p["day"], r) <= off]
                back[r] = before[-1] if before else None
            same = {"cur": last, "refs": back}
        units.append({"name": name, "rows": rows, "same": same,
                      "points": {s: pts[s].get(name, []) for s in series}})
    return {"season": season, "refs": list(refs), "series": series, "thermal": thermal(cur, {r: series[r] for r in refs}),
            "monthly": monthly(cur, {r: series[r] for r in refs}), "units": units, "milestones": milestones,
            "tbase": tbase, "rate": rate,
            "ref_days": sum(1 for s in series for r in (weather.get(s) or [])
                            if r.get("source") == gd.OPEN_METEO_SOURCE)}


# ====================================================================== textos
def _sign(v, digits=0, unit=""):
    if v is None:
        return "—"
    return ("+" if v > 0 else "−" if v < 0 else "") + gd.fmt(abs(v), digits) + unit


def _days(v):
    if v is None:
        return "—"
    n = round(v)
    return "mismo día" if n == 0 else f"{'+' if n > 0 else '−'}{abs(n)} día{'s' if abs(n) != 1 else ''}"


def display(res: dict) -> dict:
    refs = res["refs"]
    multi = len(refs) > 1
    base_name = (f"promedio {season_label(refs[-1])} a {season_label(refs[0])}" if multi else
                 season_label(refs[0]) if refs else "—")
    th = res["thermal"]
    ref0 = th.get("mean") if multi else (th["refs"].get(refs[0]) if refs else None)
    kpis = []
    if th["day"] and ref0:
        kpis.append((f"{gd.fmt(th['now'], 0)} vs {gd.fmt(ref0['at'], 0)}", "°C·día",
                     f"al {gd.short_date(th['day'])} ({season_label(res['season'])} vs {base_name})"))
        pct = ref0["delta"] / ref0["at"] * 100 if ref0["at"] else None
        kpis.append((_sign(ref0["delta"]) + (f" ({_sign(pct)} %)" if pct is not None else ""), "°C·día",
                     "más calor que " + base_name if ref0["delta"] >= 0 else "menos calor que " + base_name))
        a = ref0.get("ahead")
        if a is not None:
            kpis.append((f"{abs(round(a))} días", "", ("de adelanto térmico" if a > 0 else
                                                      "de atraso térmico" if a < 0 else "sin adelanto ni atraso")))
    early = late = 0
    for u in res["units"]:
        s = u["same"]
        if s and refs:
            r = s["refs"].get(refs[0])
            if r:
                if s["cur"]["value"] > r["value"]:
                    early += 1
                elif s["cur"]["value"] < r["value"]:
                    late += 1
    n_same = sum(1 for u in res["units"] if u["same"] and refs and u["same"]["refs"].get(refs[0]))
    if n_same:
        kpis.append((f"{early} de {n_same}", "", "adelantadas en estado a la misma fecha"
                     + (f" ({late} atrasadas)" if late else "")))
    ahead_txt = ""
    if ref0 and ref0.get("ahead") is not None and ref0.get("ahead") != 0:
        h = th["refs"].get(refs[0], {}).get("hit") if not multi else None
        ahead_txt = (f"Los {gd.fmt(th['now'], 0)} °C·día de hoy " +
                     (f"se alcanzaron el {gd.short_date(h)} en {season_label(refs[0])}" if h else
                      f"se alcanzaron en promedio {abs(round(ref0['ahead']))} días "
                      f"{'después' if ref0['ahead'] > 0 else 'antes'}") +
                     f": vamos {abs(round(ref0['ahead']))} días {'adelantados' if ref0['ahead'] > 0 else 'atrasados'}.")
    months = []
    for m in res["monthly"]:
        refs_v = [m["refs"].get(r) for r in refs]
        base_g = _mean([x["g"] for x in refs_v if x])
        base_t = _mean([x["t"] for x in refs_v if x])
        c = m["cur"]
        months.append({"name": m["name"], "t": gd.fmt(c["t"]) if c else "—", "t_ref": gd.fmt(base_t),
                       "g": gd.fmt(c["g"], 0) if c else "—", "g_ref": gd.fmt(base_g, 0),
                       "d": _sign(c["g"] - base_g) if c and base_g is not None else "—",
                       "up": bool(c and base_g is not None and c["g"] >= base_g)})
    units = []
    for i, u in enumerate(res["units"]):
        rows = []
        for r in u["rows"]:
            c = r["cur"]
            pred = r.get("pred")
            if c:
                cur_day, cur_g = gd.short_date(c["day"]), gd.fmt(c["gdd"], 0)
            elif pred and pred["overdue"]:
                cur_day, cur_g = "ya debería", "≈" + gd.fmt(pred["need"], 0)
            elif pred:
                cur_day = "≈" + gd.short_date(pred["day"]) if pred["day"] else "pendiente"
                cur_g = "≈" + gd.fmt(pred["need"], 0)
            else:
                cur_day, cur_g = "pendiente", "—"
            rows.append({"code": ph.code_str(r["code"]), "label": r["label"],
                         "ref_day": gd.short_date(r["base_day"]) if r["base_day"] else "—",
                         "ref_g": gd.fmt(r["base_gdd"], 0), "cur_day": cur_day, "cur_g": cur_g,
                         "d_days": _days(r.get("d_days")) if "d_days" in r else "—",
                         "d_gdd": _sign(r.get("d_gdd")) if "d_gdd" in r else "—",
                         "verdict": r["verdict"], "verdict_txt": VERDICTS[r["verdict"]],
                         "per_ref": [(season_label(rr), gd.short_date(h["day"]) if h else "—",
                                      gd.fmt(h["gdd"], 0) if h else "—") for rr, h in r["refs"].items()]})
        same = None
        if u["same"]:
            s = u["same"]
            r0 = s["refs"].get(refs[0]) if refs else None
            diff = (s["cur"]["value"] - r0["value"]) if r0 else None
            same = {"day": gd.short_date(s["cur"]["day"]), "cur": "BBCH " + ph.code_str(s["cur"]["code"]),
                    "ref": ("BBCH " + ph.code_str(r0["code"]) + f" ({gd.short_date(r0['day'])})") if r0 else "sin dato",
                    "diff": ("adelantada" if diff > 0 else "atrasada" if diff < 0 else "igual") +
                            (f" {_sign(diff)}" if diff else "") if diff is not None else "—",
                    "cls": "up" if diff and diff > 0 else "dn" if diff and diff < 0 else ""}
        units.append({"name": u["name"], "color": gd.PALETTE[i % len(gd.PALETTE)], "rows": rows, "same": same})
    counts = {}
    for u in units:
        for r in u["rows"]:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"kpis": kpis, "ahead_txt": ahead_txt, "months": months, "units": units, "base_name": base_name,
            "cur_name": season_label(res["season"]), "ref_names": [season_label(r) for r in refs],
            "multi": multi, "counts": counts}


# ====================================================================== gráficos (SVG)
REF_STYLES = ["6 4", "2 3", "9 3 2 3", "1 2", "4 2"]


def svg_thermal(res: dict, w: int = 860, h: int = 250) -> str:
    cur = res["series"][res["season"]]
    if not cur.days:
        return ""
    refs = [res["series"][r] for r in res["refs"] if res["series"][r].days]
    n = max(122, len(cur.days) + 30)
    shown = {s.season: s.days[:n] for s in refs}
    top = max([cur.total] + [d[-1]["acc"] for d in shown.values() if d])
    gmax = max(100, (int(top / 200) + 1) * 200)
    P = 46

    def x(i):
        return P + (w - 2 * P) * i / (n - 1)

    def y(g):
        return h - P - (h - 2 * P) * g / gmax
    out = [f'<svg viewBox="0 0 {w} {h}" class="gddchart">']
    for g in range(0, gmax + 1, 200 if gmax > 600 else 100):
        out.append(f'<line x1="{P}" x2="{w - P}" y1="{y(g):.1f}" y2="{y(g):.1f}" class="grid"/>'
                   f'<text x="{P - 6}" y="{y(g) + 4:.1f}" class="ax" text-anchor="end">{g}</text>')
    for i in range(n):
        d = cur.start + _dt.timedelta(days=i)
        if d.day == 1:
            out.append(f'<text x="{x(i):.1f}" y="{h - P + 16}" class="ax" text-anchor="middle">1/{d.month}</text>')
    for k, s in enumerate(refs):
        pts = " ".join(f"{x(i):.1f},{y(r['acc']):.1f}" for i, r in enumerate(shown[s.season]))
        out.append(f'<polyline points="{pts}" class="prev" stroke-dasharray="{REF_STYLES[k % len(REF_STYLES)]}"/>')
    out.append('<polyline points="' + " ".join(f"{x(i):.1f},{y(r['acc']):.1f}" for i, r in enumerate(cur.days))
               + '" class="acc"/>')
    i_now = len(cur.days) - 1
    out.append(f'<circle cx="{x(i_now):.1f}" cy="{y(cur.total):.1f}" r="4" fill="#B0124B"/>')
    th = res["thermal"]
    if res["refs"] and th["refs"].get(res["refs"][0], {}).get("hit"):
        hit = th["refs"][res["refs"][0]]["hit"]
        i_hit = _offset(hit, res["refs"][0])
        if 0 <= i_hit < n:
            out.append(f'<line x1="{x(i_now):.1f}" x2="{x(i_hit):.1f}" y1="{y(cur.total):.1f}" '
                       f'y2="{y(cur.total):.1f}" stroke="#B0124B" stroke-width="1.4"/>'
                       f'<circle cx="{x(i_hit):.1f}" cy="{y(cur.total):.1f}" r="3" fill="none" stroke="#B0124B"/>')
    out.append("</svg>")
    return "".join(out)


def svg_unit(res: dict, unit: dict, color: str, w: int = 280, h: int = 180) -> str:
    P = 28
    allg = [p["gdd"] for ps in unit["points"].values() for p in ps if p["gdd"] is not None]
    if not allg:
        return ""
    curg = [p["gdd"] for p in unit["points"].get(res["season"], []) if p["gdd"] is not None]
    top = max(curg) * 1.35 + 60 if curg else max(allg)         # el tramo de esta temporada (y algo más)
    gmax = max(200, (int(min(top, max(allg)) / 200) + 1) * 200)

    def X(g):
        return P + (w - P - 8) * g / gmax

    def Y(v):
        return h - P - (h - P - 18) * min(v, 90) / 90
    out = [f'<svg viewBox="0 0 {w} {h}" class="gddchart"><text x="{P}" y="13" class="lbl" '
           f'style="font-weight:700;fill:{color}">{unit["name"]}</text>']
    for b in (0, 30, 60, 90):
        out.append(f'<line x1="{P}" x2="{w - 8}" y1="{Y(b):.1f}" y2="{Y(b):.1f}" class="grid"/>'
                   f'<text x="{P - 4}" y="{Y(b) + 3:.1f}" class="ax" style="font-size:9px" text-anchor="end">{b}</text>')
    step = 200 if gmax <= 1000 else 400
    for g in range(0, gmax + 1, step):
        out.append(f'<text x="{X(g):.1f}" y="{h - P + 12}" class="ax" style="font-size:9px" text-anchor="middle">{g}</text>')
    for k, r in enumerate(res["refs"]):
        ps = [p for p in unit["points"].get(r, []) if p["gdd"] is not None and p["gdd"] <= gmax]
        if len(ps) > 1:
            out.append('<polyline fill="none" stroke="#8a8f80" stroke-width="1.6" stroke-dasharray="'
                       + REF_STYLES[k % len(REF_STYLES)] + '" points="'
                       + " ".join(f"{X(p['gdd']):.1f},{Y(p['value']):.1f}" for p in ps) + '"/>')
    ps = [p for p in unit["points"].get(res["season"], []) if p["gdd"] is not None]
    if ps:
        out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="'
                   + " ".join(f"{X(p['gdd']):.1f},{Y(p['value']):.1f}" for p in ps) + '"/>')
        out.extend(f'<circle cx="{X(p["gdd"]):.1f}" cy="{Y(p["value"]):.1f}" r="2.4" fill="{color}"/>' for p in ps)
    out.append("</svg>")
    return "".join(out)
