"""Same synthetic vectors used by the browser helper and real browser journey."""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from app.recipe_service import NUTRIENTS, _values_payload

VECTORS = json.loads((Path(__file__).parent / "browser/recipe-calculator-vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("vector", VECTORS, ids=lambda vector: vector["name"])
def test_shared_recipe_display_vectors(vector):
    values = {key: Fraction(0) for key in NUTRIENTS}
    for _, weight, *coefficients in vector["rows"]:
        for key, coefficient in zip(NUTRIENTS, coefficients):
            values[key] += Fraction(int(coefficient) * int(weight))
    for kind, factor in [("all", Fraction(1)), ("per100", Fraction(100, int(vector["yield"]))),
                         ("perPortion", Fraction(int(vector["portion"]), int(vector["yield"])) )]:
        assert list(_values_payload(values, factor).values()) == vector["expected"][kind]
