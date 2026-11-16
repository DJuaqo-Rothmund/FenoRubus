"""
app_flavor.py
=============
Qué app se compila con este código: «aeoncrop» (todo: cultivos, IA, AeonScout…) o «scout»
(AeonScout sola, para quien ya usa PhenoRubus y quiere el banco de plagas, malezas y
enfermedades aparte). La compilación de AeonScout reemplaza este archivo (ver
.github/workflows/android.yml y release_scout.env); en el código, por defecto, AeonCrop.
"""
FLAVOR = "aeoncrop"


def is_scout() -> bool:
    return FLAVOR == "scout"
