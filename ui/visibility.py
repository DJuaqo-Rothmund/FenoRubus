"""
ui/visibility.py
================
¿Se ve un widget? (sin importar Kivy, para poder probarlo sin pantalla)
"""
from __future__ import annotations


def hidden_by_opacity(widget, max_depth: int = 60) -> bool:
    """True si el widget o alguno de los que lo contienen tiene opacidad ~0.

    Sube hasta la ventana, cuyo «parent» es ella misma: sin ese corte el ciclo no
    terminaba y la app se congelaba al mostrar IA+ (v1.2.181)."""
    w, depth = widget, 0
    while w is not None and depth < max_depth:
        if getattr(w, "opacity", 1) <= 0.01:
            return True
        nxt = getattr(w, "parent", None)
        if nxt is w:
            break
        w, depth = nxt, depth + 1
    return False
