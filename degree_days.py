"""
degree_days.py
==============
Días grado (°C·día) y fenología: el informe «Fenología y días grado».

* Cada día suma  max(0, T media − T base)  (T base 5 °C), desde el 1 de septiembre de la
  temporada (inicio del conteo). Si falta la media pero hay mínima y máxima, se usa su
  promedio. Los días sin dato se rellenan con la recta entre los días vecinos (y se avisa).
* Las temperaturas (y la lluvia, que por ahora solo se guarda) son del PREDIO: viven en la
  base del predio (tabla weather_days, se sincroniza como lo demás) y los ensayos de ese
  predio las usan (ajuste «trial_predio» del ensayo).
* Cada estado BBCH observado queda asociado a los °C·día acumulados en la fecha del
  muestreo. Los hitos se interpolan entre dos muestreos (la planta pasó el estado en algún
  punto entre ambos).
* Pronóstico de los hitos que faltan: °C·día que necesitó esa variedad la temporada
  anterior (o, si no hay, el promedio de las otras variedades este año) y el ritmo de los
  últimos 7 días.

Puro Python (sin Kivy): se prueba en el PC.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

import phenology as ph

TBASE = 5.0
BIOFIX = (9, 1)                      # 1 de septiembre
SETTING_PREDIO = "trial_predio"      # código del predio del ensayo (viaja con la sync)
# Hitos del informe: (código BBCH, nombre). 891 = 89-1 «10 % de los frutos cosechados».
MILESTONES = [(51, "Botón floral visible"), (61, "Inicio de floración"), (65, "Plena flor"),
              (71, "Cuaja"), (81, "Inicio de coloración"), (891, "Fruta madura (10 %)")]
RATE_DAYS = 7


# ====================================================================== fechas y números
def biofix(season: int) -> _dt.date:
    return _dt.date(season, *BIOFIX)


def season_end(season: int) -> _dt.date:
    return ph.season_bounds(season)[1]


def _norm(text) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    return re.sub(r"[^a-z0-9]+", "_", "".join(c for c in t if not unicodedata.combining(c)).lower()).strip("_")


def parse_date(text) -> _dt.date | None:
    """2026-09-01, 01-09-2026, 1/9/2026, 01/09/26, 01.09.2026, «2026-09-01 00:00:00» o
    número de serie de Excel (46266)."""
    if text is None:
        return None
    if isinstance(text, _dt.datetime):
        return text.date()
    if isinstance(text, _dt.date):
        return text
    s = str(text).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{5}(\.\d+)?", s):                   # serie de Excel
        n = float(s)
        if 30000 < n < 80000:
            return _dt.date(1899, 12, 30) + _dt.timedelta(days=int(n))
        return None
    s = s.split("T")[0].split(" ")[0]
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
        if not m:
            return None
        d, mo, y = map(int, m.groups())
        if y < 100:
            y += 2000
    try:
        return _dt.date(y, mo, d)
    except ValueError:
        return None


def parse_num(text, decimal_comma: bool = True) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace("−", "-").replace("°", "").replace("ºC", "").replace("°C", "")
    s = s.replace("C", "").replace("mm", "").strip()
    if not s or s in ("-", "—", "s/d", "sd", "NA", "na"):
        return None
    if decimal_comma and "," in s:
        s = s.replace(".", "").replace(",", ".") if s.count(",") == 1 and "." in s and s.index(".") < s.index(",") \
            else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def fmt(v, digits: int = 1) -> str:
    if v is None:
        return "—"
    s = f"{v:.{digits}f}".replace(".", ",")
    return s[:-2] if digits == 1 and s.endswith(",0") else s


def short_date(d: _dt.date | None) -> str:
    return f"{d.day}/{d.month}" if d else "—"


# ====================================================================== lectura de archivos
COLUMNS = {
    "day": ("fecha", "dia", "date", "day", "fecha_hora", "fecha_y_hora", "tiempo", "time"),
    "tmean": ("tmedia", "t_media", "temp_media", "temperatura_media", "tmed", "t_med", "tprom",
              "t_prom", "temp_prom", "temperatura_promedio", "promedio", "media", "tmean", "t_mean",
              "mean", "temperatura", "temp", "t", "temperatura_c", "t_c", "temperature_2m_mean",
              "temperature_2m"),
    "tmin": ("tmin", "t_min", "temp_min", "temperatura_minima", "minima", "min", "t_minima",
             "temperature_2m_min"),
    "tmax": ("tmax", "t_max", "temp_max", "temperatura_maxima", "maxima", "max", "t_maxima",
             "temperature_2m_max"),
    "rain": ("lluvia", "pp", "precipitacion", "precipitaciones", "pluviometria", "pluviometro",
             "agua_caida", "rain", "mm", "lluvia_mm", "pp_mm", "precipitacion_mm", "precipitation_sum",
             "precipitation", "rain_sum"),
}


def _column_of(header: str) -> str | None:
    h = _norm(header)
    for key, names in COLUMNS.items():
        if h in names:
            return key
    best = None                                   # «Temperatura media (°C)», «Lluvia (mm)»…
    for key, names in COLUMNS.items():            # (el nombre más largo que calce)
        for n in names:
            if len(n) > 2 and h.startswith(n + "_") and (best is None or len(n) > best[1]):
                best = (key, len(n))
    return best[0] if best else None


def split_text(text: str) -> list[list[str]]:
    """Texto pegado (de Excel, una planilla o un CSV) -> filas de celdas."""
    lines = [ln for ln in (text or "").replace("\r", "").split("\n") if ln.strip()]
    if not lines:
        return []
    sample = "\n".join(lines[:20])
    if "\t" in sample:
        return [ln.split("\t") for ln in lines]
    if ";" in sample:
        return [ln.split(";") for ln in lines]
    if "," in sample:
        return list(csv.reader(lines))
    return [ln.split() for ln in lines]


def read_xlsx(path_or_bytes) -> list[list[str]]:
    """Primera hoja de un .xlsx como filas de texto (sin librerías externas)."""
    zf = zipfile.ZipFile(path_or_bytes if isinstance(path_or_bytes, str) else io.BytesIO(path_or_bytes))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    sheets = sorted(n for n in zf.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not sheets:
        return []
    name = "xl/worksheets/sheet1.xml" if "xl/worksheets/sheet1.xml" in sheets else sheets[0]
    root = ET.fromstring(zf.read(name))
    rows = []
    for r in root.iter(f"{{{ns['m']}}}row"):
        cells: dict[int, str] = {}
        for cel in r.findall("m:c", ns):
            ref = cel.get("r", "")
            letters = re.match(r"[A-Z]+", ref)
            col = 0
            for ch in (letters.group(0) if letters else ""):
                col = col * 26 + ord(ch) - 64
            col = max(col - 1, len(cells) if not letters else 0)
            t = cel.get("t")
            v = cel.find("m:v", ns)
            if t == "s" and v is not None:
                val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in cel.iter(f"{{{ns['m']}}}t"))
            else:
                val = v.text if v is not None and v.text is not None else ""
            cells[col] = val
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def read_file(path: str) -> list[list[str]]:
    if path.lower().endswith((".xlsx", ".xlsm")):
        return read_xlsx(path)
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return split_text(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return []


def parse_rows(rows: list[list[str]], decimal_comma: bool | None = None) -> tuple[list[dict], list[str]]:
    """Filas -> días {day, tmean, tmin, tmax, rain}. Reconoce los encabezados (fecha, T media,
    T mín, T máx, lluvia…); sin encabezado: fecha, T media y (opcional) lluvia. Si hay
    varias filas del mismo día (datos horarios de una estación) se resumen: media de las
    temperaturas, mínima, máxima y suma de la lluvia. Devuelve (días, avisos)."""
    rows = [[str(c).strip() for c in r] for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return [], ["No hay datos."]
    cols: dict[str, int] = {}
    start = 0
    for i, r in enumerate(rows[:5]):                       # encabezado en las primeras filas
        if parse_date(r[0] if r else "") is not None:
            break
        found = {}
        for j, h in enumerate(r):
            k = _column_of(h)
            if k and k not in found:
                found[k] = j
        if "day" in found and len(found) >= 2:
            cols, start = found, i + 1
            break
    if not cols:
        cols = {"day": 0, "tmean": 1}
        width = max(len(r) for r in rows)
        if width >= 3:
            cols["rain"] = 2
    if decimal_comma is None:
        decimal_comma = not any("." in c and "," not in c for r in rows[start:start + 30]
                                for j, c in enumerate(r) if j != cols.get("day") and re.search(r"\d\.\d", c))
    warnings, per_day = [], {}
    bad = 0
    for r in rows[start:]:
        day = parse_date(r[cols["day"]] if cols["day"] < len(r) else "")
        if day is None:
            bad += 1
            continue
        vals = {k: parse_num(r[j], decimal_comma) if j < len(r) else None
                for k, j in cols.items() if k != "day"}
        if all(v is None for v in vals.values()):
            continue
        per_day.setdefault(day, []).append(vals)
    if bad:
        warnings.append(f"{bad} fila(s) sin fecha reconocible (se omiten).")
    out = []
    multi = 0
    for day in sorted(per_day):
        recs = per_day[day]
        if len(recs) > 1:
            multi += 1

        def pick(k, how):
            vs = [x[k] for x in recs if x.get(k) is not None]
            return how(vs) if vs else None
        d = {"day": day.isoformat(),
             "tmean": pick("tmean", lambda v: round(sum(v) / len(v), 2)),
             "tmin": pick("tmin", min), "tmax": pick("tmax", max),
             "rain": pick("rain", lambda v: round(sum(v), 2))}
        if len(recs) > 1 and "tmin" not in cols and d["tmean"] is not None:
            d["tmin"] = pick("tmean", min)
            d["tmax"] = pick("tmean", max)
        out.append(d)
    if multi:
        warnings.append(f"{multi} día(s) con varias lecturas: se resumieron por día.")
    for d in out:
        for k in ("tmean", "tmin", "tmax"):
            if d[k] is not None and not -30 <= d[k] <= 50:
                warnings.append(f"{d['day']}: {k} = {d[k]} parece fuera de rango.")
    return out, warnings


# ====================================================================== Open-Meteo (referencia)
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_SOURCE = "Open-Meteo (reanálisis)"
_DAILY = "temperature_2m_mean,temperature_2m_min,temperature_2m_max,precipitation_sum"


def map_center(plan: dict | None) -> tuple[float, float] | None:
    """(lat, lon) del centro del plano de un predio (assets/maps/<código>.json)."""
    g = (plan or {}).get("geo")
    if not g or not plan.get("w"):
        return None
    return (plan["h"] / 2 + g["y0"]) / g["ky"], (plan["w"] / 2 + g["x0"]) / g["kx"]


def _om_days(payload: dict) -> list[dict]:
    d = payload.get("daily") or {}
    out = []
    for i, day in enumerate(d.get("time") or []):
        def v(k):
            vals = d.get(k) or []
            x = vals[i] if i < len(vals) else None
            return round(float(x), 2) if x is not None else None
        rec = {"day": str(day)[:10], "tmean": v("temperature_2m_mean"), "tmin": v("temperature_2m_min"),
               "tmax": v("temperature_2m_max"), "rain": v("precipitation_sum"), "source": OPEN_METEO_SOURCE}
        if rec["tmean"] is None and rec["tmin"] is not None and rec["tmax"] is not None:
            rec["tmean"] = round((rec["tmin"] + rec["tmax"]) / 2, 2)
        if rec["tmean"] is not None:
            out.append(rec)
    return out


def fetch_open_meteo(lat: float, lon: float, start: _dt.date, end: _dt.date, get=None) -> list[dict]:
    """Temperatura diaria (media, mín, máx) y lluvia de Open-Meteo en esas coordenadas: el
    reanálisis histórico (ERA5, ~5 días de atraso) y, para los últimos días, el modelo del
    pronóstico. Es una REFERENCIA de la zona (celda de ~10-25 km), no la estación del campo.
    get(url) -> bytes (para pruebas)."""
    import json
    from urllib.parse import urlencode
    if get is None:
        def get(url):
            import urllib.request
            from drive_backup import _ssl_context
            with urllib.request.urlopen(url, timeout=60, context=_ssl_context()) as r:
                return r.read()
    base = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "daily": _DAILY,
            "timezone": "America/Santiago"}
    days = {d["day"]: d for d in _om_days(json.loads(get(
        OPEN_METEO_ARCHIVE + "?" + urlencode(dict(base, start_date=start.isoformat(),
                                                    end_date=end.isoformat())))))}
    missing = [start + _dt.timedelta(days=i) for i in range((end - start).days + 1)]
    missing = [d for d in missing if d.isoformat() not in days]
    if missing and (_dt.date.today() - missing[0]).days <= 90:   # lo reciente: del pronóstico
        past = min(92, (_dt.date.today() - missing[0]).days + 1)
        try:
            recent = _om_days(json.loads(get(OPEN_METEO_FORECAST + "?" + urlencode(
                dict(base, past_days=past, forecast_days=1)))))
        except Exception:  # noqa: BLE001 - sin los últimos días no es grave
            recent = []
        for d in recent:
            if d["day"] not in days and start.isoformat() <= d["day"] <= end.isoformat():
                days[d["day"]] = dict(d, fc=1)          # del pronóstico: se reemplaza después
    return [days[k] for k in sorted(days)]


# ====================================================================== fuente de temperaturas
# Cada predio elige de dónde salen sus temperaturas (ajuste del predio, viaja con la sync):
#   «openmeteo»: estimación de la zona, se descarga y actualiza sola (caché en el teléfono,
#                no se sincroniza: cada equipo la baja);
#   «propios»:   los datos de la estación del campo que se cargan a mano (tabla weather_days).
MODE_KEY = "trial_weather_mode"
MODE_OM, MODE_OWN = "openmeteo", "propios"
MODES = {MODE_OM: ("Open-Meteo", "estimación de la zona (modelo y satélite); se actualiza sola"),
         MODE_OWN: ("Datos propios", "estación del campo; los carga usted (más precisos)")}
OM_MAX_AGE_H = 6


def own_days(db, start: _dt.date | None = None, end: _dt.date | None = None) -> list[dict]:
    """Datos propios del predio (sin los de Open-Meteo que guardaba la versión anterior)."""
    return [r for r in list_days(db, start, end) if r.get("source") != OPEN_METEO_SOURCE]


def get_mode(db) -> str:
    """Fuente elegida; sin elegir: datos propios si ya hay, si no Open-Meteo."""
    v = db.get_setting(MODE_KEY, "")
    if v in MODES:
        return v
    return MODE_OWN if own_days(db) else MODE_OM


def set_mode(db, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(mode)
    db.set_setting(MODE_KEY, mode)


class OmCache:
    """Días de Open-Meteo de un predio guardados en el teléfono (JSON)."""

    def __init__(self, path: str):
        self.path = path
        try:
            import json
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        self.lat, self.lon = data.get("lat"), data.get("lon")
        self.fetched = data.get("fetched") or ""
        self.days = {d["day"]: d for d in data.get("days") or []}

    def save(self) -> None:
        import json
        import os
        tmp = self.path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"lat": self.lat, "lon": self.lon, "fetched": self.fetched,
                       "days": [self.days[k] for k in sorted(self.days)]}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def rows(self, start: _dt.date | None = None, end: _dt.date | None = None) -> list[dict]:
        lo, hi = (start.isoformat() if start else ""), (end.isoformat() if end else "9999")
        return [self.days[k] for k in sorted(self.days) if lo <= k <= hi]

    def _same_place(self, lat, lon) -> bool:
        return self.lat is not None and abs(self.lat - lat) < .01 and abs(self.lon - lon) < .01

    def stale(self, lat: float, lon: float, now: _dt.datetime | None = None,
              first: _dt.date | None = None) -> bool:
        """¿Hay que pedir datos? (otro lugar, o faltan días hasta ayer o hay días del
        pronóstico por reemplazar, y la última consulta fue hace más de OM_MAX_AGE_H horas)."""
        now = now or _dt.datetime.now()
        if not self._same_place(lat, lon) or not self.days:
            return True
        if first is not None and first.isoformat() < min(self.days):
            return True
        yesterday = (now.date() - _dt.timedelta(days=1)).isoformat()
        behind = max(self.days) < yesterday or any(d.get("fc") for d in self.days.values())
        try:
            age = (now - _dt.datetime.fromisoformat(self.fetched)).total_seconds() / 3600
        except ValueError:
            age = 1e9
        return behind and age >= OM_MAX_AGE_H

    def update(self, lat: float, lon: float, first: _dt.date, fetch=None,
               today: _dt.date | None = None) -> int:
        """Baja lo que falta (desde «first» si es otro lugar o está vacía; si no, desde el
        primer día del pronóstico o el día siguiente al último). Devuelve los días nuevos o
        cambiados."""
        fetch = fetch or fetch_open_meteo
        today = today or _dt.date.today()
        end = today - _dt.timedelta(days=1)
        if not self._same_place(lat, lon):
            self.days, self.lat, self.lon = {}, lat, lon
        if self.days:
            fc = [k for k, d in self.days.items() if d.get("fc")]
            nxt = (_dt.date.fromisoformat(max(self.days)) + _dt.timedelta(days=1)).isoformat()
            start = _dt.date.fromisoformat(min(fc + [nxt]))
            start = max(start, first)
        else:
            start = first
        n = 0
        if self.days and first.isoformat() < min(self.days):      # piden años más atrás
            early_end = _dt.date.fromisoformat(min(self.days)) - _dt.timedelta(days=1)
            for d in fetch(lat, lon, first, early_end):
                self.days[d["day"]] = d
                n += 1
        if start <= end:
            for d in fetch(lat, lon, start, end):
                old = self.days.get(d["day"])
                if old != d:
                    self.days[d["day"]] = d
                    n += 1
        self.fetched = _dt.datetime.now().isoformat(timespec="seconds")
        self.save()
        return n


# ====================================================================== base de datos
def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def list_days(db, start: _dt.date | None = None, end: _dt.date | None = None) -> list[dict]:
    sql, args = "SELECT * FROM weather_days WHERE 1=1", []
    if start:
        sql += " AND day >= ?"
        args.append(start.isoformat())
    if end:
        sql += " AND day <= ?"
        args.append(end.isoformat())
    return db.query(sql + " ORDER BY day", tuple(args))


def save_days(db, days: list[dict], source: str = "manual", overwrite: bool = True) -> int:
    """Guarda (o actualiza) días. Solo pisa los valores que vienen; overwrite=False deja los
    días que ya existían. Devuelve cuántos días cambiaron."""
    n = 0
    for d in days:
        row = db.query_one("SELECT * FROM weather_days WHERE day=?", (d["day"],))
        vals = {k: d.get(k) for k in ("tmean", "tmin", "tmax", "rain") if d.get(k) is not None}
        if row is None:
            db.execute("INSERT INTO weather_days(day, tmean, tmin, tmax, rain, source, updated_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (d["day"], vals.get("tmean"), vals.get("tmin"), vals.get("tmax"),
                        vals.get("rain"), source, _now()))
            n += 1
        elif row.get("source") == OPEN_METEO_SOURCE and source != OPEN_METEO_SOURCE:
            # Día que la versión anterior guardó de Open-Meteo: el dato propio lo reemplaza entero.
            db.execute("UPDATE weather_days SET tmean=?, tmin=?, tmax=?, rain=?, source=?, updated_at=? "
                       "WHERE id=?", (vals.get("tmean"), vals.get("tmin"), vals.get("tmax"),
                                      vals.get("rain"), source, _now(), row["id"]))
            n += 1
        elif overwrite and any(row.get(k) != v for k, v in vals.items()):
            sets = ", ".join(f"{k}=?" for k in vals)
            db.execute(f"UPDATE weather_days SET {sets}, source=?, updated_at=? WHERE id=?",
                       (*vals.values(), source, _now(), row["id"]))
            n += 1
    return n


def set_day(db, day: str, tmean=None, tmin=None, tmax=None, rain=None) -> None:
    """Edición a mano: deja exactamente estos valores (None = vacío)."""
    row = db.query_one("SELECT id FROM weather_days WHERE day=?", (day,))
    if row is None:
        db.execute("INSERT INTO weather_days(day, tmean, tmin, tmax, rain, source, updated_at) "
                   "VALUES (?, ?, ?, ?, ?, 'manual', ?)", (day, tmean, tmin, tmax, rain, _now()))
    else:
        db.execute("UPDATE weather_days SET tmean=?, tmin=?, tmax=?, rain=?, source='manual', "
                   "updated_at=? WHERE id=?", (tmean, tmin, tmax, rain, _now(), row["id"]))


def delete_day(db, day: str) -> None:
    db.execute("DELETE FROM weather_days WHERE day=?", (day,))


def tmean_of(row: dict) -> float | None:
    if row.get("tmean") is not None:
        return float(row["tmean"])
    if row.get("tmin") is not None and row.get("tmax") is not None:
        return (float(row["tmin"]) + float(row["tmax"])) / 2
    return None


# ====================================================================== serie de días grado
class Series:
    """Días grado de una temporada: día a día desde el 1 de septiembre hasta el último día
    con temperatura."""

    def __init__(self, rows: list[dict], season: int, tbase: float = TBASE):
        self.season, self.tbase = season, tbase
        self.start = biofix(season)
        end = season_end(season)
        known = {}
        for r in rows:
            d = _dt.date.fromisoformat(str(r["day"])[:10])
            t = tmean_of(r)
            if self.start <= d <= end and t is not None:
                known[d] = t
        self.days: list[dict] = []
        if not known:
            self.last = None
            return
        self.last = max(known)
        acc, n = 0.0, (self.last - self.start).days + 1
        dates = sorted(known)
        for i in range(n):
            d = self.start + _dt.timedelta(days=i)
            t, filled = known.get(d), False
            if t is None:                                   # sin dato: recta entre vecinos
                prev = max((x for x in dates if x < d), default=None)
                nxt = min((x for x in dates if x > d), default=None)
                if prev and nxt:
                    f = (d - prev).days / (nxt - prev).days
                    t = known[prev] + f * (known[nxt] - known[prev])
                else:
                    t = known[nxt] if nxt else known[prev]
                filled = True
            g = max(0.0, t - tbase)
            acc += g
            self.days.append({"day": d, "tmean": t, "gdd": g, "acc": acc, "filled": filled})
        self._idx = {r["day"]: r for r in self.days}

    @property
    def total(self) -> float:
        return self.days[-1]["acc"] if self.days else 0.0

    @property
    def missing(self) -> int:
        return sum(1 for r in self.days if r["filled"])

    def acc_at(self, day: _dt.date) -> float | None:
        """°C·día acumulados al final de ese día (None si es después del último dato)."""
        if day < self.start:
            return 0.0
        r = self._idx.get(day) if self.days else None
        return r["acc"] if r else None

    def rate(self, n: int = RATE_DAYS) -> float:
        tail = self.days[-n:]
        return sum(r["gdd"] for r in tail) / len(tail) if tail else 0.0

    def mean_temp(self) -> float | None:
        return sum(r["tmean"] for r in self.days) / len(self.days) if self.days else None

    def zero_days(self) -> int:
        return sum(1 for r in self.days if r["gdd"] <= 0)


# ====================================================================== fenología × días grado
def _obs_date(o: dict) -> _dt.date:
    for k in ("observed_at", "start_date"):
        if o.get(k):
            try:
                return _dt.date.fromisoformat(str(o[k])[:10])
            except ValueError:
                continue
    return _dt.date.fromisoformat(str(o["start_date"])[:10])


def observations(db, season: int) -> list[dict]:
    """Estados BBCH de la temporada con su fecha (fecha del registro o inicio de la semana)."""
    return db.query(
        "SELECT o.id AS obs_id, o.variety_id, o.bbch_code, o.observed_at, w.start_date FROM observations o "
        "JOIN sampling_weeks w ON w.id = o.week_id "
        "WHERE w.season = ? AND o.bbch_code IS NOT NULL AND COALESCE(w.skipped, 0) = 0 "
        "ORDER BY w.start_date", (season,))


def unit_points(obs: list[dict], series: Series, groups: dict[int, str]) -> dict[str, list[dict]]:
    """{unidad: [{day, value, code, gdd}]} con la fecha y los °C·día de cada estado. groups:
    variety_id -> nombre de la unidad (en ensayos T×R, el tratamiento: promedio de las
    repeticiones de cada fecha)."""
    per: dict[str, dict[_dt.date, list[tuple]]] = {}
    for o in obs:
        name = groups.get(o["variety_id"])
        if name is None:
            continue
        d = _obs_date(o)
        if d < series.start:                    # antes del inicio del conteo (otoño-invierno)
            continue
        per.setdefault(name, {}).setdefault(d, []).append(
            (ph.bbch_value(o["bbch_code"]), o["bbch_code"], o.get("obs_id")))
    out = {}
    for name, by_day in per.items():
        pts, best = [], -1.0
        for d in sorted(by_day):
            vals = by_day[d]
            v = sum(x[0] for x in vals) / len(vals)
            code = max(vals)[1]
            best = max(best, v)                      # un estado no retrocede
            pts.append({"day": d, "value": best, "code": code, "gdd": series.acc_at(d),
                        "obs": [x[2] for x in vals if x[2] is not None]})
        out[name] = pts
    return out


def reached(points: list[dict], code: int) -> dict | None:
    """Cuándo la unidad llegó al estado: interpolado entre el último muestreo por debajo y el
    primero en o sobre él. {"gdd", "day", "first"} (first: ya estaba en el primer muestreo)."""
    m = ph.bbch_value(code)
    for i, p in enumerate(points):
        if p["value"] >= m:
            if p["gdd"] is None:
                return {"gdd": None, "day": p["day"], "first": i == 0}
            if i == 0 or points[i - 1]["gdd"] is None:
                return {"gdd": p["gdd"], "day": p["day"], "first": i == 0}
            a = points[i - 1]
            f = (m - a["value"]) / (p["value"] - a["value"]) if p["value"] > a["value"] else 1.0
            day = a["day"] + _dt.timedelta(days=round(f * (p["day"] - a["day"]).days))
            return {"gdd": a["gdd"] + f * (p["gdd"] - a["gdd"]), "day": day, "first": False}
    return None


def groups_for(db) -> tuple[dict, str, str]:
    """variety_id -> unidad del informe, título y palabra. Ensayos T×R (sin fenología
    unificada): el tratamiento (promedio de sus repeticiones); si no, cada
    variedad/sector/punto de fenología."""
    units = db.pheno_units()
    if getattr(db, "is_trial", False) and not getattr(db, "unified_pheno", False) and any(u.get("treatment") for u in units):
        names = {t["num"]: t for t in db.list_treatments()}

        def tname(n):
            t = names.get(n) or {}
            return f"T{n}" + (f" · {t['name']}" if t.get("name") else "")
        return ({u["id"]: tname(u["treatment"]) for u in units if u.get("treatment") is not None},
                "Tratamiento", "tratamiento")
    word = "sector" if getattr(db, "is_predio", False) else "variedad"
    return {u["id"]: ph.unit_report_name(u) for u in units}, word.capitalize(), word


def analyze(db, season: int, weather_rows: list[dict], prev_weather_rows: list[dict] | None = None,
            groups: dict[int, str] | None = None, tbase: float = TBASE,
            milestones=MILESTONES) -> dict:
    """Todo el informe en datos (para HTML, PDF y la vista previa del teléfono)."""
    series = Series(weather_rows, season, tbase)
    if groups is None:
        groups = groups_for(db)[0]
    pts = unit_points(observations(db, season), series, groups)
    prev_series = Series(prev_weather_rows or [], season - 1, tbase)
    prev_pts = unit_points(observations(db, season - 1), prev_series, groups) if prev_series.days else {}
    # Solo las unidades con estados (esta temporada o la anterior), en el orden del ensayo.
    names = [n for n in dict.fromkeys(groups.values()) if n in pts or n in prev_pts]
    rate = series.rate()
    units = []
    for name in names:
        p = pts.get(name, [])
        cells = []
        for code, label in milestones:
            hit = reached(p, code)
            prev_hit = reached(prev_pts.get(name, []), code)
            cell = {"code": code, "hit": hit, "prev": prev_hit["gdd"] if prev_hit else None}
            cells.append(cell)
        units.append({"name": name, "points": p, "cells": cells,
                      "last": p[-1] if p else None})
    # Referencias para pronosticar: la misma unidad la temporada anterior; si no, el promedio
    # de las otras unidades este año; si no, el promedio de la temporada anterior.
    for j, (code, _label) in enumerate(milestones):
        now_vals = [u["cells"][j]["hit"]["gdd"] for u in units
                    if u["cells"][j]["hit"] and u["cells"][j]["hit"]["gdd"] is not None]
        prev_vals = [u["cells"][j]["prev"] for u in units if u["cells"][j]["prev"] is not None]
        for u in units:
            cell = u["cells"][j]
            if cell["hit"] or not series.days or not u["points"]:
                continue
            if cell["prev"] is not None:
                need, why = cell["prev"], "temporada anterior"
            elif now_vals:
                need, why = sum(now_vals) / len(now_vals), "otras variedades"
            elif prev_vals:
                need, why = sum(prev_vals) / len(prev_vals), "promedio temporada anterior"
            else:
                continue
            left = need - series.total
            if left <= 0:
                cell["pred"] = {"need": need, "left": 0, "day": None, "why": why, "overdue": True}
            else:
                days = round(left / rate) if rate > 0.05 else None
                cell["pred"] = {"need": need, "left": left, "why": why, "overdue": False,
                                "day": series.last + _dt.timedelta(days=days) if days is not None else None}
    # Comparación con la temporada anterior a la misma fecha.
    vs_prev = None
    if series.days and prev_series.days:
        same = series.last.replace(year=series.last.year - 1) if not (
            series.last.month == 2 and series.last.day == 29) else series.last - _dt.timedelta(days=366)
        prev_at = prev_series.acc_at(same)
        if prev_at is not None:
            vs_prev = {"prev": prev_at, "delta": series.total - prev_at, "day": same}
    ref = sum(1 for r in weather_rows if r.get("source") == OPEN_METEO_SOURCE
              and series.start.isoformat() <= str(r["day"])[:10])
    return {"ref_days": ref, "season": season, "tbase": tbase, "start": series.start, "series": series,
            "prev_series": prev_series, "units": units, "milestones": milestones,
            "rate": rate, "vs_prev": vs_prev, "has_prev": bool(prev_pts),
            "n_obs": sum(len(u["points"]) for u in units),
            "no_gdd": sum(1 for u in units for p in u["points"] if p["gdd"] is None)}


def next_milestone(unit: dict, milestones=MILESTONES) -> tuple[int, str, dict] | None:
    """El primer hito aún no alcanzado de la unidad, con su pronóstico (si hay)."""
    for (code, label), cell in zip(milestones, unit["cells"]):
        if not cell["hit"]:
            return code, label, cell.get("pred") or {}
    return None


# ====================================================================== gráficos (SVG, para el HTML)
PALETTE = ["#B0124B", "#2F6B4F", "#C8963E", "#3E6A8A", "#7A4E9E", "#8A6A4A", "#4F8F8A",
           "#C2593A", "#5B6B3A", "#A0567A"]


def svg_temperature(series: Series, prev: Series | None = None, w: int = 860, h: int = 260) -> str:
    if not series.days:
        return ""
    P, PR = 46, 52
    n = len(series.days)
    tmax = max(25, max(r["tmean"] for r in series.days) + 2)
    tmin = min(0, min(r["tmean"] for r in series.days) - 1)
    span = max(n - 1, 1)
    shown = prev.days[:n] if prev and prev.days else []      # la anterior, en el mismo tramo
    ptot = shown[-1]["acc"] if shown else 0
    gmax = max(100, (int(max(series.total, ptot) / 100) + 1) * 100)

    def x(i):
        return P + (w - P - PR) * i / span

    def yt(t):
        return h - P - (h - 2 * P) * (t - tmin) / (tmax - tmin)

    def yg(g):
        return h - P - (h - 2 * P) * g / gmax
    bw = max(1.0, (w - P - PR) / max(n, 1) * .7)
    out = [f'<svg viewBox="0 0 {w} {h}" class="gddchart" role="img" aria-label="Temperatura media y días grado">']
    for t in range(int(tmin // 5 * 5), int(tmax) + 1, 5):
        out.append(f'<line x1="{P}" x2="{w - PR}" y1="{yt(t):.1f}" y2="{yt(t):.1f}" class="grid"/>'
                   f'<text x="{P - 6}" y="{yt(t) + 4:.1f}" class="ax t" text-anchor="end">{t}°</text>')
    for i, r in enumerate(series.days):
        cls = "bar fill" if r["filled"] else ("bar" if r["gdd"] > 0 else "bar cold")
        top, base = yt(max(r["tmean"], tmin)), yt(max(0, tmin))
        out.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{min(top, base):.1f}" width="{bw:.1f}" '
                   f'height="{abs(base - top):.1f}" class="{cls}"/>')
    out.append(f'<line x1="{P}" x2="{w - PR}" y1="{yt(series.tbase):.1f}" y2="{yt(series.tbase):.1f}" class="tbase"/>'
               f'<text x="{w - PR - 4}" y="{yt(series.tbase) - 5:.1f}" class="lbl" text-anchor="end">'
               f'T base {fmt(series.tbase)} °C</text>')
    if prev and prev.days:
        pp = " ".join(f"{x(i):.1f},{yg(r['acc']):.1f}" for i, r in enumerate(shown))
        out.append(f'<polyline points="{pp}" class="prev"/>')
    line = " ".join(f"{x(i):.1f},{yg(r['acc']):.1f}" for i, r in enumerate(series.days))
    out.append(f'<polyline points="{line}" class="acc"/>')
    for g in range(0, gmax + 1, max(50, gmax // 5 // 50 * 50)):
        out.append(f'<text x="{w - PR + 6}" y="{yg(g) + 4:.1f}" class="ax g">{g}</text>')
    for i, r in enumerate(series.days):
        if r["day"].day in (1, 15):
            out.append(f'<text x="{x(i):.1f}" y="{h - P + 16}" class="ax" text-anchor="middle">{short_date(r["day"])}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_stages(units: list[dict], gmax: float, w: int = 860, h: int = 300) -> str:
    P = 46
    gmax = max(100, (int(gmax / 100) + 1) * 100)

    def x(g):
        return P + (w - 2 * P) * g / gmax

    def y(v):
        return h - P - (h - 2 * P) * min(v, 90) / 90
    out = [f'<svg viewBox="0 0 {w} {h}" class="gddchart" role="img" aria-label="Estado BBCH según días grado">']
    for b in range(0, 91, 10):
        out.append(f'<line x1="{P}" x2="{w - P}" y1="{y(b):.1f}" y2="{y(b):.1f}" class="grid"/>'
                   f'<text x="{P - 6}" y="{y(b) + 4:.1f}" class="ax" text-anchor="end">{b}</text>')
    step = 100 if gmax <= 1000 else 200
    for g in range(0, gmax + 1, step):
        out.append(f'<text x="{x(g):.1f}" y="{h - P + 16}" class="ax" text-anchor="middle">{g}</text>')
    for i, u in enumerate(units):
        col = PALETTE[i % len(PALETTE)]
        pts = [p for p in u["points"] if p["gdd"] is not None]
        if not pts:
            continue
        line = " ".join(f"{x(p['gdd']):.1f},{y(p['value']):.1f}" for p in pts)
        out.append(f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2.4"/>')
        out.extend(f'<circle cx="{x(p["gdd"]):.1f}" cy="{y(p["value"]):.1f}" r="3.2" fill="{col}">'
                   f'<title>{u["name"]} · BBCH {ph.code_str(p["code"])} · {fmt(p["gdd"], 0)} °C·día · '
                   f'{short_date(p["day"])}</title></circle>' for p in pts)
    out.append(f'<text x="{w / 2}" y="{h - 6}" class="lbl" text-anchor="middle">Días grado acumulados '
               f'desde el 1 de septiembre (°C·día)</text>')
    out.append("</svg>")
    return "".join(out)


# ====================================================================== textos para informe y vista previa
def display(res: dict) -> dict:
    """Lo que muestran el HTML, el PDF y la vista previa del teléfono (ya en texto)."""
    s: Series = res["series"]
    ms = res["milestones"]
    kpis = []
    if s.days:
        kpis = [(fmt(s.total, 0), "°C·día", f"acumulados al {short_date(s.last)}"),
                (fmt(res["rate"]), "°C·día/día", f"ritmo de los últimos {RATE_DAYS} días"),
                (fmt(s.mean_temp()), "°C", "temperatura media desde el 1/9"),
                (str(s.zero_days()), "días", f"sin acumular (T media ≤ {fmt(res['tbase'])} °C)")]
        if res["vs_prev"]:
            d = res["vs_prev"]["delta"]
            kpis.append((("+" if d >= 0 else "−") + fmt(abs(d), 0), "°C·día",
                         f"vs temporada anterior al {short_date(res['vs_prev']['day'])}"))
    rows = []
    for i, u in enumerate(res["units"]):
        cells = []
        for (code, _label), cl in zip(ms, u["cells"]):
            hit, pred = cl["hit"], cl.get("pred")
            if hit and hit["gdd"] is not None:
                cells.append({"main": ("≤" if hit["first"] else "") + fmt(hit["gdd"], 0),
                              "sub": short_date(hit["day"]), "cls": "hit"})
            elif hit:
                cells.append({"main": short_date(hit["day"]), "sub": "sin temperatura", "cls": "hit"})
            elif pred and pred["overdue"]:
                cells.append({"main": "≈" + fmt(pred["need"], 0), "sub": "ya debería estar · revisar",
                              "cls": "pred late"})
            elif pred:
                cells.append({"main": "≈" + fmt(pred["need"], 0),
                              "sub": f"faltan {fmt(pred['left'], 0)}" + (f" · ~{short_date(pred['day'])}"
                                                                         if pred["day"] else ""),
                              "cls": "pred"})
            else:
                cells.append({"main": "—", "sub": "", "cls": "na"})
        last = u["last"]
        nxt = next_milestone(u, ms)
        rows.append({"name": u["name"], "color": PALETTE[i % len(PALETTE)], "cells": cells,
                     "now": (f"BBCH {ph.code_str(last['code'])} · {short_date(last['day'])}"
                             + (f" · {fmt(last['gdd'], 0)} °C·día" if last and last["gdd"] is not None else "")
                             ) if last else "sin registros",
                     "next": _next_text(nxt)})
    prev_rows = []
    if res["has_prev"]:
        for i, u in enumerate(res["units"]):
            cells = []
            for cl in u["cells"]:
                now = cl["hit"]["gdd"] if cl["hit"] else None
                prev = cl["prev"]
                diff = (now - prev) if now is not None and prev is not None else None
                cells.append({"now": fmt(now, 0), "prev": fmt(prev, 0),
                              "diff": ("+" if diff >= 0 else "−") + fmt(abs(diff), 0) if diff is not None else ""})
            if any(c["prev"] != "—" for c in cells):
                prev_rows.append({"name": u["name"], "color": PALETTE[i % len(PALETTE)], "cells": cells})
    notes = []
    if res.get("ref_days"):
        notes.append(f"Temperaturas de Open-Meteo ({res['ref_days']} días): estimación de la zona "
                     "(modelo y satélite), no la estación del campo. Con datos propios el cálculo es más preciso.")
    if s.missing:
        notes.append(f"{s.missing} día(s) sin temperatura: se completaron con la recta entre los días vecinos.")
    if res["no_gdd"]:
        notes.append(f"{res['no_gdd']} registro(s) BBCH posteriores al último día con temperatura "
                     f"({short_date(s.last)}): cargue las temperaturas para ubicarlos.")
    return {"kpis": kpis, "rows": rows, "prev_rows": prev_rows, "notes": notes,
            "heads": [(ph.code_str(c), label) for c, label in ms]}


def _next_text(nxt) -> str:
    if nxt is None:
        return "todos los hitos alcanzados"
    code, label, pred = nxt
    if not pred:
        return f"próximo: {label} (BBCH {ph.code_str(code)}) · sin referencia aún"
    if pred["overdue"]:
        return f"próximo: {label} · ya debería estar (≈{fmt(pred['need'], 0)} °C·día) · revisar en terreno"
    when = f" · ~{short_date(pred['day'])}" if pred["day"] else ""
    return f"próximo: {label} · faltan {fmt(pred['left'], 0)} °C·día{when}"
