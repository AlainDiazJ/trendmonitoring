#!/usr/bin/env python3
"""views/sidebar.py — filtros de la barra lateral (vistas favoritas,
variante, description, rango de fechas).

Extraida de app.py sin cambios de logica. Devuelve un objeto Filtros que
las vistas reciben en render(filtros).
"""

from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

import config_store as cfg


@dataclass
class Filtros:
    """Estado de los filtros del sidebar + datos ya filtrados.

    fdf: datos con TODOS los filtros aplicados (variante, description, fechas).
    dfv_hist: historico completo de la variante activa (sin fechas ni
    description), para bandas/baseline sobre toda la historia.
    """
    fdf: pd.DataFrame
    dfv_hist: pd.DataFrame
    sel_var: str
    sel_lbl: str
    sel_desc: list
    variantes: list
    etiqueta: dict = field(default_factory=dict)


def render_sidebar(df):
    st.sidebar.header("Filtros")

    variantes = sorted(df["variant"].dropna().unique())


    def etiqueta_variante(v):
        return f"LEAP-{v}" if v in ("1A", "1B") else str(v)


    etiqueta = {v: etiqueta_variante(v) for v in variantes}
    inv_etiqueta = {lbl: v for v, lbl in etiqueta.items()}

    # --- Vistas favoritas (aplicar / guardar / borrar) ---
    with st.sidebar.expander("Vistas favoritas", expanded=False):
        vistas = cfg.list_views()
        nombres_vistas = [v["name"] for v in vistas]
        if nombres_vistas:
            vsel = st.selectbox("Vista guardada", ["(ninguna)"] + nombres_vistas,
                                key="vw_sel")
            cva, cvb = st.columns(2)
            with cva:
                if st.button("Aplicar", key="vw_apply") and vsel != "(ninguna)":
                    payload = cfg.get_view(vsel)
                    if payload:
                        # escribir en session_state las keys de los filtros
                        var_p = payload.get("variant")
                        if var_p in variantes:
                            st.session_state["f_variant"] = etiqueta[var_p]
                        if payload.get("param"):
                            st.session_state["f_param"] = payload["param"]
                        if payload.get("desc"):
                            st.session_state["f_desc"] = payload["desc"]
                        if payload.get("d0") and payload.get("d1"):
                            import datetime as _d
                            try:
                                st.session_state["f_fechas"] = (
                                    _d.date.fromisoformat(payload["d0"]),
                                    _d.date.fromisoformat(payload["d1"]))
                            except Exception:
                                pass
                        st.rerun()
            with cvb:
                if st.button("Borrar", key="vw_del") and vsel != "(ninguna)":
                    cfg.delete_view(vsel)
                    st.success("Vista borrada.")
                    st.rerun()
        else:
            st.caption("Aun no hay vistas guardadas. Guarda una abajo.")

        nueva_vista = st.text_input("Nombre para guardar vista actual", key="vw_new_name",
                                    placeholder="Ej: EGT TKO 1B")
        guardar_vista = st.button("Guardar vista actual", key="vw_save")

    # Seleccion UNICA de variante (radio): nunca dos activas a la vez
    labels_var = [etiqueta[v] for v in variantes]
    sel_lbl = st.sidebar.radio("Variante de motor", labels_var, key="f_variant")
    sel_var = inv_etiqueta[sel_lbl]

    dfv = df[df["variant"] == sel_var].copy()
    # historico completo de la variante (sin filtros de fecha/description),
    # para calcular bandas de control sobre toda la historia
    dfv_hist = dfv.copy()

    # Filtro de Rating / Punto (texto completo, seleccion multiple, default todos)
    descripciones = sorted(dfv["description"].dropna().unique())
    sel_desc = list(descripciones)
    if descripciones:
        # Contar puntos/reportes unicos por rating. Si ya hay un parametro
        # seleccionado (por ejemplo EGTK), el conteo corresponde a ese parametro;
        # si no, usa todos los puntos cargados del rating.
        param_actual = st.session_state.get("f_param")
        base_conteo = dfv
        if param_actual and "param_label" in dfv.columns and param_actual in set(dfv["param_label"].dropna()):
            base_conteo = dfv[dfv["param_label"] == param_actual]
        conteo_desc = (
            base_conteo[["description", "point_id"]]
            .dropna(subset=["description"])
            .drop_duplicates()
            .groupby("description")["point_id"]
            .nunique()
            .to_dict()
        )

        def etiqueta_desc(desc):
            return f"{desc} ({int(conteo_desc.get(desc, 0))})"

        # default: vista guardada si sus desc existen, si no todos
        default_desc = descripciones
        if "f_desc" in st.session_state:
            guardados = [d for d in st.session_state["f_desc"] if d in descripciones]
            if guardados:
                default_desc = guardados
        sel_desc = st.sidebar.multiselect(
            "Rating / Punto", descripciones, default=default_desc,
            format_func=etiqueta_desc,
            help="Filtra por Rating / Punto. El numero entre parentesis es la cantidad de puntos cargados para el parametro actual cuando aplica.",
            key="f_desc",
        )
        dfv = dfv[dfv["description"].isin(sel_desc)]

    # Filtro de rango de fechas (default: todo el historico de esa variante)
    fechas_validas = dfv["fecha"].dropna()
    if not fechas_validas.empty:
        fmin = fechas_validas.min().date()
        fmax = fechas_validas.max().date()
        with st.sidebar.expander("Rango de fechas", expanded=False):
            rango = st.date_input(
                "Fechas", value=(fmin, fmax),
                min_value=fmin, key="f_fechas",
            )
        if isinstance(rango, tuple) and len(rango) == 2:
            d0, d1 = rango
            dfv = dfv[(dfv["fecha"].dt.date >= d0) & (dfv["fecha"].dt.date <= d1)]

    fdf = dfv

    return Filtros(
        fdf=fdf,
        dfv_hist=dfv_hist,
        sel_var=sel_var,
        sel_lbl=sel_lbl,
        sel_desc=sel_desc,
        variantes=variantes,
        etiqueta=etiqueta,
    )
