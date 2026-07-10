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
import etl
from services.data_loader import DB_PATH, load_data
from views import (
    anomalias,
    correlacion,
    correlacion_ref,
    datos,
    eventos,
    modificadores,
    tendencia,
)
from views import params_dialog
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
# Se carga crudo. La correccion kg/h -> lb/h la activa cada vista (Tendencia,
# Correlacion, Correlacion Ref.) con su propio checkbox, solo cuando el
# parametro que esa vista tiene seleccionado cae en una regla activa.
df = load_data(DB_PATH, _db_mtime, aplicar_correcciones_unidad=False)

# Unloaded/ y Loaded/ viven siempre como hermanas de la carpeta de la app
# (App/), sin depender del directorio desde el que se lanza streamlit.
APP_DIR = Path(__file__).resolve().parent
UNLOADED_DIR = APP_DIR.parent / "Unloaded"
LOADED_DIR = APP_DIR.parent / "Loaded"

col_title, col_params, col_sync = st.columns([0.64, 0.18, 0.18])
with col_title:
    st.markdown(
        '<div class="app-title">Trend Monitoring - Celda de Pruebas de Motores</div>',
        unsafe_allow_html=True,
    )
with col_params:
    if st.button("Parametros", key="btn_params", use_container_width=True):
        if df is None or df.empty:
            st.info("Carga datos primero (Sync) para administrar parametros.")
        else:
            params_dialog.iniciar_estado()
            params_dialog.abrir_dialogo(df, LOADED_DIR)
with col_sync:
    if st.button("Sync", key="btn_sync", use_container_width=True):
        if not UNLOADED_DIR.exists():
            st.session_state["_sync_flash"] = {
                "tipo": "info",
                "msg": (
                    f"No existe la carpeta '{UNLOADED_DIR}'. Crea 'Unloaded' junto "
                    "a la carpeta de la app y coloca ahi los Exceles nuevos."
                ),
            }
        else:
            with st.spinner("Cargando y ordenando Exceles..."):
                resultado = etl.run_sync(UNLOADED_DIR, LOADED_DIR, DB_PATH, "mapping.yaml")
            if resultado["total"] == 0:
                st.session_state["_sync_flash"] = {
                    "tipo": "info", "msg": "No hay Exceles nuevos en 'Unloaded'.",
                }
            else:
                st.session_state["_sync_flash"] = {
                    "tipo": "success",
                    "msg": (
                        f"{resultado['ok']} cargados ({resultado['moved']} movidos a "
                        f"Loaded), {resultado['skipped']} duplicados, "
                        f"{resultado['error']} con error."
                    ),
                }
                if resultado["skipped"] or resultado["error"] or resultado["move_errors"]:
                    st.session_state["_sync_detalle"] = resultado["mensajes"]
                load_data.clear()
        st.rerun()

# Mensajes diferidos de Sync y del dialogo de Parametros (se guardan en
# session_state porque un st.toast/success/info justo antes del st.rerun()
# que dispara la actualizacion no llega a pintarse de forma confiable; se
# muestran aqui, en el primer render normal siguiente, y se limpian para no
# repetirse). st.toast se autodesvanece solo, sin necesitar logica de timer.
_sync_flash = st.session_state.pop("_sync_flash", None)
if _sync_flash:
    _icon = "✅" if _sync_flash["tipo"] == "success" else "ℹ️"
    st.toast(_sync_flash["msg"], icon=_icon)
_sync_detalle = st.session_state.pop("_sync_detalle", None)
if _sync_detalle:
    with st.expander("Detalle del sync"):
        for _m in _sync_detalle:
            st.caption(_m)

_params_flash = st.session_state.pop("_params_flash", None)
if _params_flash:
    for _kind, _msg in _params_flash:
        getattr(st, _kind)(_msg)

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
_n_err = int(_parse_counts.get("error", 0) + _parse_counts.get("missing", 0))
if _n_err:
    st.warning(f"Hay {_n_err} punto(s) con fecha sin parsear o faltante. Revisa la pestana Datos antes de confiar en tendencias.")


# FILTROS (sidebar) -> objeto Filtros con fdf, dfv_hist, seleccion actual
filtros = render_sidebar(df)
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
        # fechas actuales: guarda el modo siempre para no arrastrar un rango
        # viejo de session_state si el usuario esta en "Historico completo"
        _fecha_modo = st.session_state.get("f_fecha_modo", "Historico completo")
        _payload["fecha_modo"] = _fecha_modo
        if _fecha_modo == "Rango personalizado":
            _fechas = st.session_state.get("f_fechas")
            if isinstance(_fechas, tuple) and len(_fechas) == 2:
                _payload["d0"] = _fechas[0].isoformat()
                _payload["d1"] = _fechas[1].isoformat()
        cfg.save_view(_nombre, _payload)
        st.sidebar.success(f"Vista '{_nombre}' guardada.")
