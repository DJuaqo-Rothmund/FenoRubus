"""
crops.py
========
Cultivos de la app (un «módulo» por cultivo, todos con el mismo entorno):

* Frambuesa  → PhenoRubus (el de siempre: sus datos siguen en la carpeta de datos raíz).
* Arándano   → PhenoBlue  (datos en «cultivos/arandano»).
* Cranberry  → PhenoCran  (datos en «cultivos/cranberry»).

Cada cultivo tiene su escala fenológica (phenology.py), sus variedades iniciales, su
carpeta en Google Drive («App Fenología/<módulo>») y su color de fruta (ui/theme.py).
Elegir un cultivo (`activate`) deja todo listo para abrir su entorno.

Puro Python (sin Kivy): lo usa también el servicio de recordatorios.
"""
from __future__ import annotations

from dataclasses import dataclass

DRIVE_TOP = "App Fenología"      # carpeta grande en «Mi unidad» con un módulo por cultivo


@dataclass(frozen=True)
class Crop:
    id: str                  # clave interna (carpeta de datos, ajustes)
    name: str                # «Arándano»
    app: str                 # «PhenoBlue»
    species: str             # nombre científico
    fruit: str               # «arándano» (en textos)
    subdir: str | None       # carpeta de datos dentro de la raíz (None = la raíz misma)
    varieties: tuple         # variedades iniciales (nombre, código)

    @property
    def drive_folder(self) -> str:
        return self.app


CROPS: dict[str, Crop] = {
    "arandano": Crop(
        "arandano", "Arándano", "PhenoBlue", "Vaccinium corymbosum", "arándano",
        "cultivos/arandano",
        (("Duke", "DUK"), ("Legacy", "LEG"), ("Brigitta", "BRI"), ("Emerald", "EME"),
         ("Ventura", "VEN"))),
    "cranberry": Crop(
        "cranberry", "Cranberry", "PhenoCran", "Vaccinium macrocarpon", "cranberry",
        "cultivos/cranberry",
        (("Stevens", "STE"), ("Ben Lear", "BL"), ("Pilgrim", "PIL"), ("HyRed", "HYR"),
         ("Mullica Queen", "MQ"))),
    "frambuesa": Crop(
        "frambuesa", "Frambuesa", "PhenoRubus", "Rubus idaeus", "frambuesa", None,
        (("Código 11", "C11"), ("Código 31", "C31"), ("Código 24", "C24"),
         ("Código 55", "C55"), ("Código 81", "C81"), ("Cascade Harvest", "CH"),
         ("Lagorai", "LAG"), ("Meeker", "MEE"), ("Regina", "REG"), ("Wakefield", "WAK"))),
}
DEFAULT = "frambuesa"

_current = DEFAULT


def get(crop_id: str | None = None) -> Crop:
    return CROPS.get(crop_id or _current) or CROPS[DEFAULT]


def current() -> Crop:
    return CROPS[_current]


def activate(crop_id: str) -> Crop:
    """Deja el cultivo listo: carpeta de datos, escala BBCH y calendario esperado. La
    interfaz (colores, logos) la cambia ui/theme.configure."""
    global _current
    if crop_id not in CROPS:
        crop_id = DEFAULT
    _current = crop_id
    import platform_utils
    platform_utils.set_crop_dir(CROPS[crop_id].subdir)
    import phenology
    phenology.set_crop(crop_id)
    try:
        import training_labels          # IA+ (solo en la app Lab): clases de las cajas
        training_labels.set_crop(crop_id)
    except ImportError:
        pass
    return CROPS[crop_id]
