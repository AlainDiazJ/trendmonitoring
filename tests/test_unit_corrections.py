import pandas as pd
import pytest

from services.unit_corrections import (
    KG_H_A_LB_H,
    apply_unit_corrections,
    parametro_tiene_correccion,
)


@pytest.mark.parametrize("variant,param_label,esperado", [
    ("1A", "WF36 [pph]", True),
    ("1A", "WFK [pph]", True),
    ("1B", "WFMR2 [pph]", True),
    ("1B", "WF36pph [pph]", True),
    ("CFM56-7B", "WFK [pph]", True),
    ("1A", "EGTK [C]", False),
    ("1B", "WFK [pph]", False),  # regla de WFK es solo para CFM56-7B, no 1B
    (None, "WFK [pph]", False),
    ("1A", None, False),
])
def test_parametro_tiene_correccion(variant, param_label, esperado):
    assert parametro_tiene_correccion(variant, param_label) is esperado


def _fila(variant, raw_name, fecha, value=100.0, unit="pph"):
    return {
        "variant": variant, "raw_name": raw_name, "unit": unit,
        "fecha": pd.Timestamp(fecha), "value": value,
    }


def test_apply_unit_corrections_multiplica_solo_las_filas_que_matchean():
    df = pd.DataFrame([
        _fila("1A", "WF36", "2026-01-01", value=100.0),   # antes del corte -> se corrige
        _fila("1A", "WF36", "2026-03-05", value=100.0),   # despues del corte -> NO se corrige
        _fila("1A", "EGTK", "2026-01-01", value=500.0),   # otro raw_name -> NO se corrige
        _fila("1B", "WF36", "2026-01-01", value=100.0),   # otra variante -> NO se corrige
    ])
    out = apply_unit_corrections(df)

    assert out.loc[0, "value"] == pytest.approx(100.0 * KG_H_A_LB_H)
    assert out.loc[1, "value"] == 100.0
    assert out.loc[2, "value"] == 500.0
    assert out.loc[3, "value"] == 100.0


def test_apply_unit_corrections_el_dia_de_corte_no_se_corrige():
    df = pd.DataFrame([_fila("1A", "WF36", "2026-03-01", value=100.0)])
    out = apply_unit_corrections(df)
    assert out.loc[0, "value"] == 100.0


def test_apply_unit_corrections_operador_mayor_que():
    df = pd.DataFrame([
        _fila("CFM56-7B", "WFK", "2026-03-02", value=100.0),  # despues del corte -> se corrige
        _fila("CFM56-7B", "WFK", "2026-02-01", value=100.0),  # antes del corte -> NO se corrige
    ])
    out = apply_unit_corrections(df)
    assert out.loc[0, "value"] == pytest.approx(100.0 * KG_H_A_LB_H)
    assert out.loc[1, "value"] == 100.0


def test_apply_unit_corrections_fecha_nat_nunca_se_corrige():
    df = pd.DataFrame([_fila("1A", "WF36", pd.NaT, value=100.0)])
    out = apply_unit_corrections(df)
    assert out.loc[0, "value"] == 100.0


def test_apply_unit_corrections_no_toca_unit():
    df = pd.DataFrame([_fila("1A", "WF36", "2026-01-01", value=100.0, unit="pph")])
    out = apply_unit_corrections(df)
    assert out.loc[0, "unit"] == "pph"


def test_apply_unit_corrections_mutacion_es_in_place():
    df = pd.DataFrame([_fila("1A", "WF36", "2026-01-01", value=100.0)])
    out = apply_unit_corrections(df)
    assert out is df
