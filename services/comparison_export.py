#!/usr/bin/env python3
"""services/comparison_export.py — tabla ancha para el export de Excel del
modo comparacion de Tendencia (varios parametros, un eje Y cada uno).

Separado de views/tendencia.py para poder testearlo sin Streamlit.
"""


def build_comparison_table(base, sel_multi):
    """Convierte 'base' (formato largo: consecutivo/param_label/value, mas
    fecha_iso/description) en una tabla ancha para exportar:

        Reporte | Fecha | Description | <param_label 1> | <param_label 2> | ...

    con las columnas de parametro en el mismo orden que sel_multi (no
    alfabetico, que es el orden por defecto de pivot_table).
    """
    tabla = (
        base.drop_duplicates(["consecutivo", "param_label"])
            .pivot_table(index="consecutivo", columns="param_label",
                         values="value", aggfunc="first")
            .reset_index()
    )
    cols = ["consecutivo"] + [p for p in sel_multi if p in tabla.columns]
    tabla = tabla[cols].sort_values("consecutivo")

    ctx = base.drop_duplicates("consecutivo")[["consecutivo", "fecha_iso", "description"]]
    tabla = ctx.merge(tabla, on="consecutivo", how="right").rename(
        columns={"consecutivo": "Reporte", "fecha_iso": "Fecha",
                 "description": "Description"}
    )
    return tabla
