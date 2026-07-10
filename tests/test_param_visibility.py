import pandas as pd

import config_store as cfg
from services.param_visibility import parametros_visibles


def _df():
    return pd.DataFrame([
        {"raw_name": "EGTK", "param_label": "EGTK [degC]"},
        {"raw_name": "EGTK", "param_label": "EGTK [degF]"},
        {"raw_name": "N1K", "param_label": "N1K [%]"},
        {"raw_name": "WFK", "param_label": "WFK [pph]"},
    ])


def test_parametros_visibles_sin_ocultos_devuelve_todos(tmp_path):
    db_path = str(tmp_path / "config_test.db")
    assert parametros_visibles(_df(), db_path=db_path) == [
        "EGTK [degC]", "EGTK [degF]", "N1K [%]", "WFK [pph]",
    ]


def test_parametros_visibles_oculta_por_raw_name_todas_sus_unidades(tmp_path):
    db_path = str(tmp_path / "config_test.db")
    cfg.set_hidden_params(["EGTK"], db_path=db_path)

    visibles = parametros_visibles(_df(), db_path=db_path)
    assert visibles == ["N1K [%]", "WFK [pph]"]
    assert not any(v.startswith("EGTK") for v in visibles)


def test_parametros_visibles_reactivar_lo_devuelve(tmp_path):
    db_path = str(tmp_path / "config_test.db")
    cfg.set_hidden_params(["EGTK"], db_path=db_path)
    cfg.set_hidden_params([], db_path=db_path)

    assert parametros_visibles(_df(), db_path=db_path) == [
        "EGTK [degC]", "EGTK [degF]", "N1K [%]", "WFK [pph]",
    ]
