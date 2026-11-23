import os
import sys

import pytest

# Los módulos de la app están en la raíz del repositorio (con «pytest» a secas no está en la ruta).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Las pruebas nunca escriben en la carpeta de datos real del usuario."""
    monkeypatch.setenv("FENORUBUS_DATA", str(tmp_path / "appdata"))
    import crops
    crops.activate("frambuesa")     # cada prueba parte en frambuesa (PhenoRubus)
