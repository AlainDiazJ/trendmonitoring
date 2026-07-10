#!/usr/bin/env python3
"""
app.py — Dashboard de Trend Monitoring (piloto LEAP). Version 3: router.

app.py ya solo orquesta. Carga los datos (services/data_loader, que migra y
backfillea bases viejas antes del SELECT), construye los filtros del sidebar
(views/sidebar) y despacha la pestana activa a su modulo:

    views/tendencia.py       grafica principal, bandas, baseline, drift, export
    views/correlacion.py     scatter parametro vs parametro
    views/correlacion_ref.py correlacion vs celda de pruebas (+-N sigma)
    views/anomalias.py       outliers / umbrales / CUSUM / rachas consolidados
    views/modificadores.py   vigilancia de factores de celda por rating
    views/eventos.py         gestion de marcas temporales
    views/datos.py           tabla filtrada + retiro con cuarentena de Exceles

    services/data_loader.py       carga y normalizacion de motores.db
    services/deletion_service.py  retiro de puntos y cuarentena de Exceles
    config_store.py               configuracion del usuario (config.db)
    db_migrations.py              migracion de schema + backfill

EJECUTAR:  py -m streamlit run app.py   ->  http://localhost:8501
REQUISITOS: py -m pip install streamlit plotly pandas sqlalchemy matplotlib
"""

from pathlib import Path

import streamlit as st

import config_store as cfg
from services.data_loader import DB_PATH, load_data
from services.unit_corrections import apply_unit_corrections
from views import (
    anomalias,
    correlacion,
    correlacion_ref,
    datos,
    eventos,
    modificadores,
    tendencia,
)
from views.sidebar import render_sidebar


st.set_page_config(page_title="Trend Monitoring - Celda de Pruebas",
                   layout="wide", initial_sidebar_state="expanded")

APP_CSS = """
<style>
    /* Shell de Streamlit */
    header[data-testid="stHeader"] {display: none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Sidebar fijo: se oculta el control de colapso para no perder el menu. */
    button[kind="header"],
    button[data-testid="baseButton-header"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }

    /* Layout principal */
    section[data-testid="stMain"] .block-container {
        max-width: none;
        padding: 0.4rem 2rem 2rem 2rem;
    }

    .app-title {
        font-size: 1.45rem;
        line-height: 1.15;
        font-weight: 700;
        margin: 0 0 0.75rem 0;
    }

    /* Sidebar: dejar el scroll nativo de Streamlit para evitar barras dobles. */
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
    div[data-testid="stSidebarUserContent"] {
        overflow-x: hidden !important;
        padding-top: 0.75rem !important;
        padding-bottom: 5rem !important;
        margin-top: 0 !important;
    }

    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        margin-bottom: 0.35rem !important;
    }

    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }


    /* Multiselect legible sin fijar el ancho del sidebar. */
    section[data-testid="stSidebar"] div[data-baseweb="select"] {
        max-width: 100% !important;
    }

    section[data-testid="stSidebar"] div[data-baseweb="tag"] {
        flex: 1 0 100% !important;
        width: 100% !important;
        max-width: 100% !important;
        min-height: 1.9rem !important;
        height: auto !important;
        align-items: flex-start !important;
        white-space: normal !important;
    }

    section[data-testid="stSidebar"] div[data-baseweb="tag"],
    section[data-testid="stSidebar"] div[data-baseweb="tag"] *,
    section[data-testid="stSidebar"] div[data-baseweb="tag"] span,
    section[data-testid="stSidebar"] div[data-baseweb="tag"] div {
        max-width: none !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
        word-break: break-word !important;
    }

    section[data-testid="stSidebar"] div[data-baseweb="tag"] span {
        display: inline !important;
        line-height: 1.2rem !important;
        vertical-align: bottom !important;
    }



    section[data-testid="stSidebar"] div[data-baseweb="tag"] [title],
    section[data-testid="stSidebar"] div[data-baseweb="tag"] [class*="Label"],
    section[data-testid="stSidebar"] div[data-baseweb="tag"] [class*="label"],
    section[data-testid="stSidebar"] div[data-baseweb="tag"] [class*="Text"],
    section[data-testid="stSidebar"] div[data-baseweb="tag"] [class*="text"] {
        display: inline !important;
        width: auto !important;
        max-width: none !important;
        min-width: 0 !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
        word-break: break-word !important;
    }

    ul[role="listbox"] li,
    div[role="option"] {
        white-space: normal !important;
        line-height: 1.25rem !important;
    }
</style>
"""

st.markdown(APP_CSS, unsafe_allow_html=True)

_db_mtime = Path(DB_PATH).stat().st_mtime if Path(DB_PATH).exists() else None
# Se carga crudo. La correccion kg/h -> lb/h se aplica despues del sidebar,
# solo cuando el parametro seleccionado tiene una regla activa.
df = load_data(DB_PATH, _db_mtime, aplicar_correcciones_unidad=False)

st.markdown(
    '<div class="app-title">Trend Monitoring - Celda de Pruebas de Motores</div>',
    unsafe_allow_html=True,
)

if df is None:
    st.error(
        f"No se encontro la base en '{DB_PATH}'. Corre primero el ETL "
        "para generar data/motores.db, o ajusta DB_PATH al inicio de app.py."
    )
    st.stop()
if df.empty:
    st.warning("La base existe pero no tiene datos. Corre el ETL sobre tus archivos.")
    st.stop()

# Puntos ocultados con alcance GLOBAL (desde Correlacion Ref.): se excluyen de
# TODAS las pestanas. Prefiere stable_point_key; point_id solo como fallback
# de registros viejos sin llave. Nada se borra de motores.db.
_ocultos_global = cfg.list_hidden_points_detail(scope=cfg.GLOBAL_HIDDEN_SCOPE)
if _ocultos_global:
    _g_keys = {d["stable_point_key"] for d in _ocultos_global if d["stable_point_key"]}
    _g_ids = {d["point_id"] for d in _ocultos_global if not d["stable_point_key"]}
    _mask_g = df["stable_point_key"].isin(_g_keys) | df["point_id"].isin(_g_ids)
    if _mask_g.any():
        df = df[~_mask_g]
        st.caption(
            f"{len(_ocultos_global)} punto(s) ocultos globalmente "
            "(se administran en Correlacion Ref. > puntos ocultos)."
        )
    if df.empty:
        st.warning("Todos los puntos estan ocultos globalmente.")
        if st.button("Restaurar todos los puntos ocultos globales"):
            cfg.unhide_all_points(scope=cfg.GLOBAL_HIDDEN_SCOPE)
            st.rerun()
        st.stop()

_parse_counts = df[["point_id", "date_parse_status"]].drop_duplicates()["date_parse_status"].value_counts(dropna=False)
_n_amb = int(_parse_counts.get("ambiguous", 0))
_n_err = int(_parse_counts.get("error", 0) + _parse_counts.get("missing", 0))
if _n_err:
    st.warning(f"Hay {_n_err} punto(s) con fecha sin parsear o faltante. Revisa la pestana Datos antes de confiar en tendencias.")
elif _n_amb:
    st.info(f"Hay {_n_amb} punto(s) con fecha ambigua; se interpretaron como DD/MM/YYYY desde el ETL.")


# FILTROS (sidebar) -> objeto Filtros con fdf, dfv_hist, seleccion actual
filtros = render_sidebar(df)
if st.session_state.get("apply_unit_corrections", False):
    apply_unit_corrections(filtros.fdf)
    apply_unit_corrections(filtros.dfv_hist)
fdf = filtros.fdf

tabs = ["Tendencia", "Correlacion", "Correlacion Ref.", "Anomalias", "Modificadores", "Eventos", "Datos"]
active_tab = st.radio(
    "Vista",
    tabs,
    horizontal=True,
    label_visibility="collapsed",
    key="active_tab",
)

if fdf.empty:
    st.warning("Ningun dato con los filtros actuales. Ajusta la seleccion.")
    st.stop()


# ===== DESPACHO DE PESTANAS =====
if active_tab == "Tendencia":
    tendencia.render(filtros)
elif active_tab == "Correlacion":
    correlacion.render(filtros)
elif active_tab == "Correlacion Ref.":
    correlacion_ref.render(filtros.fdf, filtros.sel_var, filtros.sel_lbl)
elif active_tab == "Anomalias":
    anomalias.render(filtros)
elif active_tab == "Modificadores":
    modificadores.render(filtros)
elif active_tab == "Eventos":
    eventos.render(filtros)
elif active_tab == "Datos":
    datos.render(filtros)


# ===== Guardar vista favorita (se procesa al final, ya con todos los filtros) =====
if "vw_save" in st.session_state and st.session_state.get("vw_save"):
    _nombre = st.session_state.get("vw_new_name", "").strip()
    if _nombre:
        # parametro actual (si existe en session_state)
        _param = st.session_state.get("f_param")
        _payload = {
            "variant": filtros.sel_var,
            "param": _param,
            "desc": filtros.sel_desc,
        }
        # fechas actuales
        _fechas = st.session_state.get("f_fechas")
        if isinstance(_fechas, tuple) and len(_fechas) == 2:
            _payload["d0"] = _fechas[0].isoformat()
            _payload["d1"] = _fechas[1].isoformat()
        cfg.save_view(_nombre, _payload)
        st.sidebar.success(f"Vista '{_nombre}' guardada.")
