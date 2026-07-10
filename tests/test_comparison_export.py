import pandas as pd

from services.comparison_export import build_comparison_table


def test_build_comparison_table_orders_columns_by_selection_not_alphabet():
    base = pd.DataFrame([
        {"consecutivo": 2, "param_label": "WFK [pph]", "value": 200.0,
         "fecha_iso": "2024-01-02", "description": "TAKEOFF"},
        {"consecutivo": 2, "param_label": "EGTK [degC]", "value": 800.0,
         "fecha_iso": "2024-01-02", "description": "TAKEOFF"},
        {"consecutivo": 1, "param_label": "WFK [pph]", "value": 100.0,
         "fecha_iso": "2024-01-01", "description": "MAXI CONTINU"},
        {"consecutivo": 1, "param_label": "EGTK [degC]", "value": 780.0,
         "fecha_iso": "2024-01-01", "description": "MAXI CONTINU"},
    ])
    sel_multi = ["WFK [pph]", "EGTK [degC]"]

    tabla = build_comparison_table(base, sel_multi)

    assert list(tabla.columns) == ["Reporte", "Fecha", "Description", "WFK [pph]", "EGTK [degC]"]
    assert list(tabla["Reporte"]) == [1, 2]
    assert tabla.loc[tabla["Reporte"] == 1, "WFK [pph]"].iloc[0] == 100.0
    assert tabla.loc[tabla["Reporte"] == 2, "EGTK [degC]"].iloc[0] == 800.0


def test_build_comparison_table_dedups_repeated_point_param_rows():
    base = pd.DataFrame([
        {"consecutivo": 1, "param_label": "N1 [rpm]", "value": 50.0,
         "fecha_iso": "2024-01-01", "description": "TKO"},
        {"consecutivo": 1, "param_label": "N1 [rpm]", "value": 50.0,
         "fecha_iso": "2024-01-01", "description": "TKO"},
    ])
    tabla = build_comparison_table(base, ["N1 [rpm]"])
    assert len(tabla) == 1
