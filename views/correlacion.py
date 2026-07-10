#!/usr/bin/env python3
"""views/correlacion.py — pestana Correlacion (scatter parametro vs parametro).

Extraida de app.py sin cambios de logica.
"""

import plotly.express as px
import streamlit as st

from services.unit_corrections import (
    apply_unit_corrections,
    checkbox_correccion,
    parametro_tiene_correccion,
)

def render(filtros):
    fdf = filtros.fdf
    sel_var = filtros.sel_var
    sel_lbl = filtros.sel_lbl

    st.subheader(f"Correlacion - {sel_lbl}")
    st.caption("Cada punto es un punto de prueba. Ej.: empuje vs. flujo de combustible.")

    todos_params = sorted(fdf["param_label"].unique())

    # Guardar la seleccion fuera del key del widget. Los keys que empiezan
    # con "_" son solo del selectbox; corr_*_saved sobreviven aunque el widget
    # no se renderice temporalmente al apagar todos los ratings.
    def _save_corr_x():
        st.session_state["corr_x_saved"] = st.session_state.get("_corr_x")

    def _save_corr_y():
        st.session_state["corr_y_saved"] = st.session_state.get("_corr_y")

    default_x = st.session_state.get("corr_x_saved")
    if default_x not in todos_params:
        default_x = todos_params[0]
        st.session_state["corr_x_saved"] = default_x

    default_y = st.session_state.get("corr_y_saved")
    if default_y not in todos_params:
        default_y = todos_params[min(1, len(todos_params) - 1)]
        st.session_state["corr_y_saved"] = default_y

    st.session_state["_corr_x"] = default_x
    st.session_state["_corr_y"] = default_y

    c1, c2 = st.columns(2)
    with c1:
        px_par = st.selectbox(
            "Eje X", todos_params, key="_corr_x", on_change=_save_corr_x,
        )
    with c2:
        py_par = st.selectbox(
            "Eje Y", todos_params, key="_corr_y", on_change=_save_corr_y,
        )

    datos = fdf
    if parametro_tiene_correccion(sel_var, px_par) or parametro_tiene_correccion(sel_var, py_par):
        if checkbox_correccion(
            key="unit_corr_correlacion",
            ayuda="Corrige el eje (X y/o Y) que tenga la regla activa.",
        ):
            datos = fdf.copy()
            apply_unit_corrections(datos)

    def serie_por_punto(data, param_label):
        s = data[data["param_label"] == param_label]
        if s.empty:
            return None
        return s.groupby(["point_id", "consecutivo", "description", "test_date", "source_file"],
                         as_index=False, dropna=False)["value"].mean().rename(columns={"value": param_label})

    gx = serie_por_punto(datos, px_par)
    gy = serie_por_punto(datos, py_par)
    if gx is None or gy is None:
        st.warning("Uno de los parametros no tiene datos con los filtros actuales.")
    elif px_par == py_par:
        st.info("Elige dos parametros distintos para el eje X y el eje Y.")
    else:
        merged = gx.merge(gy[["point_id", py_par]], on="point_id", how="inner")
        if merged.empty:
            st.warning("No hay puntos que tengan ambos parametros a la vez.")
        else:
            fig2 = px.scatter(
                merged, x=px_par, y=py_par,
                hover_data={"description": True, "test_date": True, "source_file": True, "consecutivo": True},
                title=f"{py_par} vs {px_par} - {sel_lbl}",
            )
            fig2.update_layout(height=520)
            fig2.update_traces(marker=dict(size=12))
            st.plotly_chart(fig2, use_container_width=True)

