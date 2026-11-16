"""AeonScout compartido entre dos cuentas: misma carpeta en Drive, base sincronizada."""
import os

import pytest
from PIL import Image

import scout
import scout_ai
import sharing
from tests.test_core import MovableDrive


class Auth:
    def get_token(self, interactive):
        return "t"


def _phone(tmp_path, name, fake):
    d = scout.ScoutDB(str(tmp_path / name))
    d.set_setting("drive_enabled", True)
    return d, scout.ScoutDrive(d, scout.make_backup(d, authorizer=Auth(), transport=fake, metered=lambda: False))


def _capture(d, section="malezas", species=None, color=(40, 120, 60)):
    sid = species or d.new_unidentified(section)
    rec = d.add_record(section, sid, crop="frambuesa", place="Campo norte", place_kind="otro")
    sp = d.get_species(sid)
    path = os.path.join(d.photo_dir(section), f"20261116_MZ_{scout.slug(sp['name'])}_{rec}.jpg")
    Image.new("RGB", (400, 300), color).save(path)
    d.add_photo(rec, path, view="Planta completa")
    return rec


def test_two_accounts_share_scout(tmp_path, monkeypatch):
    fake = MovableDrive()
    a, da = _phone(tmp_path, "juaco", fake)
    b, db = _phone(tmp_path, "coni", fake)
    me = {id(da.backup): "juaco@x.cl", id(db.backup): "coni@x.cl"}
    monkeypatch.setattr(sharing, "my_email", lambda drive: me.get(id(drive), "x@x.cl"))
    # Juaco ya tenía capturas; Coni también (antes de compartir).
    ra = _capture(a)
    rb = _capture(b, color=(150, 60, 40))
    assert da.run() == 1
    # Juaco comparte (lo de la API de permisos se simula: solo queda la carpeta común).
    folder = da.backup.root_id()
    a.set_setting("share_folder", folder)
    scout._set_tag(a, "juaco@x.cl")
    assert scout.join(db.backup, {"folder": folder, "owner": "Juaco", "owner_email": "juaco@x.cl"}) > 0
    assert b.get_setting("scout_ni_tag") == "C" and a.get_setting("scout_ni_tag") == "J"
    assert db.run() == 1                          # la foto de Coni sube a la carpeta COMÚN
    da.run()
    # Juaco ve la captura de Coni con su foto; las dos «NI-001» siguen siendo dos ejemplares.
    nis = [s["name"] for s in a.species("malezas", unidentified=True)]
    assert sorted(nis) == ["NI-001", "NI-001-b"]
    photos = a.query("SELECT path FROM scout_photos")
    assert len(photos) == 2 and all(os.path.exists(p["path"]) for p in photos)
    # Una NI nueva lleva la letra de la cuenta.
    assert a.get_species(a.new_unidentified("plagas"))["name"] == "NI-001-J"
    # Juaco identifica la de Coni (resultado de IA aceptado): a Coni le llega especie y nombre.
    rec_b_in_a = next(r["id"] for r in a.query("SELECT id FROM scout_records") if r["id"] != ra)
    scout_ai.queue(a, rec_b_in_a)
    scout_ai.accept(a, rec_b_in_a, {"name": "Junquillo", "scientific": "Juncus effusus", "stage": "Floración",
                                    "confidence": .8, "species_id": 999})
    da.run()
    db.run()
    r = b.get_record(rb)
    assert b.get_species(r["species_id"])["name"] == "Junquillo" and r["stage"] == "Floración"
    p = b.photos(rb)[0]
    assert "Junquillo" in os.path.basename(p["path"]) and os.path.exists(p["path"])   # renombrada aquí
    assert scout_ai.job(b, rb)["accepted"] == "Junquillo"
    # En Drive: carpeta común con las fotos de los dos en su especie, y los paquetes.
    common = [f for f in fake.files.values() if not f["folder"] and f["name"].endswith(".jpg")
              and not f.get("trashed")]
    assert any("Junquillo" in f["name"] for f in common)
    sync_dir = next(k for k, f in fake.files.items() if f["folder"] and f["name"] == "Sincronización"
                    and folder in f["parents"])
    assert sum(sync_dir in f["parents"] for f in fake.files.values()) >= 3
