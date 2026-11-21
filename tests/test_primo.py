"""Primocañas: seguimiento opcional (desde BBCH 30) en tablas propias que se sincronizan."""
import datetime as dt

import sync
from database import Database


def _db(path, code="AM"):
    return Database(str(path), code=code)


def test_primo_basic_and_optional(tmp_path):
    db = _db(tmp_path / "a" / "AM.sqlite3")
    v = db.list_varieties()[0]
    week = db.week_for_date(dt.date(2026, 11, 16))
    assert db.get_primo(v["id"], week["id"]) is None            # opcional: no existe hasta agregarla
    p = db.get_or_create_primo(v["id"], week["id"])
    assert db.primo_is_empty(p["id"])
    db.update_primo(p["id"], bbch_code=35, bbch_label="BBCH 35")
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    a = db.add_primo_photo(p["id"], "canopy", str(f))
    b = db.add_primo_photo(p["id"], "canopy", str(f))
    assert [x["id"] for x in db.list_primo_photos(p["id"], "canopy")][0] == a    # la primera es principal
    db.set_primo_primary(b)
    assert db.list_primo_photos(p["id"], "canopy")[0]["id"] == b
    db.delete_primo_photo(b)
    assert db.list_primo_photos(p["id"], "canopy")[0]["is_primary"] == 1
    assert db.primo_week_codes(week["id"]) == {v["id"]: 35}
    assert db.primo_series(week["season"])[v["id"]] == [(week["week_number"], 35)]
    # La floricaña (fenología de siempre) no se toca: sin observación ni fotos.
    assert not db.query("SELECT 1 FROM observations WHERE variety_id=? AND week_id=?", (v["id"], week["id"]))
    db.delete_primo(p["id"])
    assert db.get_primo(v["id"], week["id"]) is None


def test_primo_syncs_to_other_device(tmp_path):
    a = _db(tmp_path / "a" / "AM.sqlite3")
    v = a.list_varieties()[0]
    week = a.week_for_date(dt.date(2026, 11, 16))
    p = a.get_or_create_primo(v["id"], week["id"])
    a.update_primo(p["id"], bbch_code=37)
    f = tmp_path / "a" / "photos" / "p.jpg"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
    a.add_primo_photo(p["id"], "detail", str(f))
    bundle = sync.export_changes(a, str(tmp_path / "a"))
    assert {c["entity"] for c in bundle["changes"]} >= {"primo_obs", "primo_photos"}
    b = _db(tmp_path / "b" / "AM.sqlite3")
    sync.apply_changes(b, bundle, str(tmp_path / "b"), week_for_date=b.week_for_date)
    vb = next(x for x in b.list_varieties() if x["name"] == v["name"])
    wb = b.week_for_date(dt.date(2026, 11, 16))
    got = b.get_primo(vb["id"], wb["id"])
    assert got and got["bbch_code"] == 37
    assert len(b.list_primo_photos(got["id"], "detail")) == 1


def test_axis_floricana_skips_brotes_and_primo_from_30():
    import crops
    import reporter
    old = crops._current
    try:
        crops._current = "frambuesa"
        ax = reporter.flori_axis()
        assert ax.frac(29) < ax.frac(40) and abs(ax.frac(40) - ax.frac(29)) < .02   # sin el tramo 30–39
        assert all(not (30 <= lo <= 39) for lo, _hi, _n in ax.bands())
        assert ax.frac(99) == 1 and ax.frac(0) == 0
        crops._current = "arandano"
        assert reporter.flori_axis() is reporter.FULL_AXIS                         # otros cultivos: igual que antes
    finally:
        crops._current = old
    p = reporter.PRIMO_AXIS
    assert p.frac(30) == 0 and p.frac(99) == 1 and p.bands()[0][0] == 30


def test_reports_include_primo_only_when_present(tmp_path):
    from reporter import ReportGenerator
    db = _db(tmp_path / "AM.sqlite3")
    v = db.list_varieties()[0]
    w = db.week_for_date(dt.date(2026, 11, 16))
    o = db.get_or_create_observation(v["id"], w["id"])
    db.update_observation(o["id"], bbch_code=61)
    gen = ReportGenerator(db, str(tmp_path / "out"))
    html = open(gen.weekly(w["id"]).path, encoding="utf-8").read()
    assert "Primocaña · brotes del año" not in html
    p = db.get_or_create_primo(v["id"], w["id"])
    db.update_primo(p["id"], bbch_code=35, lengths=db.parse_lengths("120 135 98,5 141"))
    html = open(gen.weekly(w["id"]).path, encoding="utf-8").read()
    assert "Primocaña · brotes del año" in html and "141 cm" in html
    assert gen.weekly(w["id"], "pdf").path.endswith(".pdf")
    assert "Primocaña" in open(gen.variety(v["id"], w["season"]).path, encoding="utf-8").read()


def test_parse_lengths():
    assert Database.parse_lengths("120 135 98,5; 141") == [120, 135, 98.5, 141]
    assert Database.parse_lengths("120, 130") == [120, 130]
    import pytest
    with pytest.raises(ValueError):
        Database.parse_lengths("5000")
