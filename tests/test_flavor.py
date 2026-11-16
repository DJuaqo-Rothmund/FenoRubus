"""App AeonScout sola: el código se publica como AeonCrop; CI cambia la variante."""
import os
import re

import app_flavor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_default_flavor_and_scout_release():
    assert app_flavor.FLAVOR == "aeoncrop" and not app_flavor.is_scout()
    env = dict(re.findall(r'^([A-Z_]+)=(.*?)\s*(?:#.*)?$', open(os.path.join(ROOT, "release_scout.env")).read(), re.M))
    assert env["PACKAGE"] == "aeonscout" and env["FLAVOR"] == "scout"
    for k in ("ICON", "ICON_FG", "ICON_BG", "PRESPLASH"):
        assert os.path.exists(os.path.join(ROOT, env[k])), k
    wf = open(os.path.join(ROOT, ".github", "workflows", "android.yml")).read()
    assert "release_scout.env" in wf and re.search(r'^FLAVOR = "aeoncrop"$', open(app_flavor.__file__).read(), re.M)
