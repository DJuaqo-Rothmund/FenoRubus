"""Aeon IA (aeon_ai.py): lectura del resultado del detector del teléfono."""
import pytest

import aeon_ai


def test_parse_boxes_times_and_retired_classes():
    classes = ["yema", "brote", "lateral", "boton"]
    got = aeon_ai._parse("T:900,120,1500|1,0.88,0.1,0.2,0.3,0.4;2,0.9,0,0,1,1;3,0.5,0.5,0.5,0.6,0.6",
                         classes, ["yema", "brote", "boton"])
    assert [b["c"] for b in got] == ["brote", "boton"]              # «lateral» se ignora
    assert got[0] == {"c": "brote", "x": 0.1, "y": 0.2, "w": 0.2, "h": 0.2, "s": "aeon", "p": 0.88}
    assert aeon_ai._parse("T:1,2,3|", classes, ["brote"]) == []


def test_parse_error():
    with pytest.raises(RuntimeError, match="sin memoria"):
        aeon_ai._parse("ERROR: sin memoria", ["a"], ["a"])
