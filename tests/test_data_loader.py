import pytest

from services.data_loader import limpiar_description_display, normalizar_raw_name


@pytest.mark.parametrize("raw_name,variant,esperado", [
    ("PCELLR_abs", "CFM56-7B", "PCELLR"),
    ("PCELLF", "CFM56-7B", "PCELLF"),
    ("PCELLR", "1A", "PCELLR"),
    ("PCELLR_abs", "1B", "PCELLR_abs"),  # solo aplica a CFM56-7B
    ("EGTK", "CFM56-7B", "EGTK"),
])
def test_normalizar_raw_name(raw_name, variant, esperado):
    assert normalizar_raw_name(raw_name, variant) == esperado


def test_limpiar_description_display_quita_prefijo_test_en_cfm56():
    assert limpiar_description_display("TEST 003 : MAXI CONTINU", "CFM56-5A") == "MAXI CONTINU"


def test_limpiar_description_display_no_toca_leap():
    assert limpiar_description_display("TEST 003 : MAXI CONTINU", "1A") == "TEST 003 : MAXI CONTINU"
