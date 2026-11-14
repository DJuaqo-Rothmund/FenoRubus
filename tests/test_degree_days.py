import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import degree_days as gd  # noqa: E402
from database import Database  # noqa: E402


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.sqlite3"))
    yield d
    d.close()


def _temps(season, n, base=10.0, step=0.1):
    start = gd.biofix(season)
    return [{"day": (start + dt.timedelta(days=i)).isoformat(), "tmean": base + step * i} for i in range(n)]


def test_series_accumulates_and_fills_gaps():
    rows = [{"day": "2026-09-01", "tmean": 10}, {"day": "2026-09-02", "tmean": 4},
            {"day": "2026-09-04", "tmean": 14}, {"day": "2026-08-31", "tmean": 30}]
    s = gd.Series(rows, 2026)
    assert [round(r["gdd"], 1) for r in s.days] == [5.0, 0.0, 4.0, 9.0]   # el 3: (4+14)/2 = 9
    assert s.missing == 1 and s.zero_days() == 1
    assert s.total == pytest.approx(18.0)
    assert s.acc_at(dt.date(2026, 8, 1)) == 0 and s.acc_at(dt.date(2026, 9, 10)) is None
    # Sin T media: promedio de mínima y máxima.
    assert gd.Series([{"day": "2026-09-01", "tmin": 2, "tmax": 18}], 2026).total == pytest.approx(5.0)


def test_parse_pasted_text_and_hourly():
    text = "Fecha\tT media (°C)\tLluvia (mm)\n01-09-2026\t11,5\t0\n02/09/2026\t9,8\t3,2\nxx\t1\t2\n"
    days, warn = gd.parse_rows(gd.split_text(text))
    assert days == [{"day": "2026-09-01", "tmean": 11.5, "tmin": None, "tmax": None, "rain": 0.0},
                    {"day": "2026-09-02", "tmean": 9.8, "tmin": None, "tmax": None, "rain": 3.2}]
    assert any("sin fecha" in w for w in warn)
    # Sin encabezado, coma como separador y punto decimal.
    days, _ = gd.parse_rows(gd.split_text("2026-09-01,12.5\n2026-09-02,13\n"))
    assert [d["tmean"] for d in days] == [12.5, 13.0]
    # Datos horarios: se resumen por día.
    hourly = "fecha;temperatura;pp\n2026-09-01 00:00;8;0,2\n2026-09-01 12:00;16;0,3\n"
    days, warn = gd.parse_rows(gd.split_text(hourly))
    assert days[0]["tmean"] == 12 and days[0]["tmin"] == 8 and days[0]["tmax"] == 16
    assert days[0]["rain"] == pytest.approx(0.5)
    assert gd.parse_date("46266") == dt.date(2026, 9, 1)


def test_read_xlsx(tmp_path):
    from measures_export import write_xlsx
    p = write_xlsx(str(tmp_path / "t.xlsx"), [("Clima", [["Fecha", "Tmin", "Tmax", "Lluvia"],
                                                           ["01-09-2026", 4, 20, 1.5]])])
    days, _ = gd.parse_rows(gd.read_file(p))
    assert days == [{"day": "2026-09-01", "tmean": None, "tmin": 4.0, "tmax": 20.0, "rain": 1.5}]


def test_save_and_sync_weather(db, tmp_path):
    import sync
    assert gd.save_days(db, [{"day": "2026-09-01", "tmean": 11}, {"day": "2026-09-02", "tmean": 12}]) == 2
    assert gd.save_days(db, [{"day": "2026-09-01", "tmean": 11}]) == 0          # sin cambios
    assert gd.save_days(db, [{"day": "2026-09-01", "rain": 4}]) == 1            # solo pisa la lluvia
    assert db.query_one("SELECT tmean, rain FROM weather_days WHERE day='2026-09-01'") == {"tmean": 11, "rain": 4}
    bundle = sync.export_changes(db, str(tmp_path))
    other = Database(str(tmp_path / "o.sqlite3"))
    sync.apply_changes(other, bundle, str(tmp_path))
    assert [r["day"] for r in gd.list_days(other)] == ["2026-09-01", "2026-09-02"]
    gd.delete_day(db, "2026-09-02")
    sync.apply_changes(other, sync.export_changes(db, str(tmp_path)), str(tmp_path))
    assert [r["day"] for r in gd.list_days(other)] == ["2026-09-01"]
    other.close()


def test_analyze_milestones_and_prediction(db):
    a = db.add_variety("Zeta A")
    b = db.add_variety("Zeta B")
    aid = a["id"] if isinstance(a, dict) else a
    bid = b["id"] if isinstance(b, dict) else b

    def obs(vid, day, code):
        w = db.week_for_date(day)
        o = db.get_or_create_observation(vid, w["id"])
        db.update_observation(o["id"], bbch_code=code, observed_at=day.isoformat())
    weather = _temps(2026, 60, base=10, step=0)       # 5 °C·día por día
    d0 = gd.biofix(2026)
    obs(aid, d0 + dt.timedelta(days=7), 15)            # 40
    obs(aid, d0 + dt.timedelta(days=21), 55)           # 110 → BBCH 51 interpolado: 40 + 36/40·70 = 103
    obs(bid, d0 + dt.timedelta(days=21), 15)
    res = gd.analyze(db, 2026, weather)
    m = {u["name"]: u for u in res["units"]}
    hit = m["Zeta A"]["cells"][0]["hit"]
    assert hit["gdd"] == pytest.approx(103.0) and not hit["first"]
    pred = m["Zeta B"]["cells"][0]["pred"]                  # según la otra variedad
    assert pred["why"] == "otras variedades"
    assert pred["overdue"] is True                              # ya van 300 °C·día
    assert res["series"].total == pytest.approx(300)
    nm = gd.next_milestone(m["Zeta A"])
    assert nm[0] == 61
    html = gd.svg_temperature(res["series"]) + gd.svg_stages(res["units"], res["series"].total)
    assert html.count("<svg") == 2


def test_open_meteo_csv_and_fetch():
    csv_text = ("latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n"
                "-39.55,-72.47,120.0,-10800,America/Santiago,GMT-3\n\n"
                "time,temperature_2m_mean (°C),temperature_2m_min (°C),temperature_2m_max (°C),precipitation_sum (mm)\n"
                "2026-09-01,8.4,3.1,13.2,0.0\n2026-09-02,9.1,4.0,14.5,12.6\n")
    days, _ = gd.parse_rows(gd.split_text(csv_text))
    assert days[1] == {"day": "2026-09-02", "tmean": 9.1, "tmin": 4.0, "tmax": 14.5, "rain": 12.6}
    import json
    calls = []

    def get(url):
        calls.append(url)
        if "archive" in url:
            return json.dumps({"daily": {"time": ["2026-09-01", "2026-09-02", "2026-09-03"],
                                         "temperature_2m_mean": [8.4, None, None],
                                         "temperature_2m_min": [3.1, 2.0, None],
                                         "temperature_2m_max": [13.2, 12.0, None],
                                         "precipitation_sum": [0, 1.5, None]}}).encode()
        return json.dumps({"daily": {"time": ["2026-09-03", "2026-09-04"],
                                     "temperature_2m_mean": [10.0, 11.0], "temperature_2m_min": [5, 6],
                                     "temperature_2m_max": [15, 16], "precipitation_sum": [0, 0]}}).encode()
    today = dt.date.today()
    start = today - dt.timedelta(days=3)
    # Fechas relativas a hoy para que la parte «reciente» se pida al pronóstico.
    def shift(raw):
        return raw.replace(b"2026-09-01", str(start).encode()).replace(
            b"2026-09-02", str(start + dt.timedelta(1)).encode()).replace(
            b"2026-09-03", str(start + dt.timedelta(2)).encode()).replace(
            b"2026-09-04", str(start + dt.timedelta(3)).encode())
    out = gd.fetch_open_meteo(-39.55, -72.47, start, start + dt.timedelta(2), get=lambda u: shift(get(u)))
    assert [d["tmean"] for d in out] == [8.4, 7.0, 10.0]          # 7.0 = (2+12)/2 · el 3º del pronóstico
    assert len(calls) == 2 and "past_days" in calls[1]
    lat, lon = gd.map_center({"w": 100, "h": 50, "geo": {"x0": -100, "y0": -40, "kx": 1, "ky": 1}})
    assert (lat, lon) == (-15, -50)
