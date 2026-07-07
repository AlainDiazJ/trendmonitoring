#!/usr/bin/env python3
"""
app.py a Dashboard de Trend Monitoring (piloto LEAP). Version 2.

Cambios sobre v1:
  - Variante en seleccion UNICA (maximo una activa: siempre se compara el mismo
    tipo de motor contra si mismo). Se muestra como "LEAP-1A" / "LEAP-1B".
  - Filtro de RANGO DE FECHAS (de-a). Default: todo el historico.
  - Eje X de la tendencia = CONSECUTIVO por variante (mas antiguo = 1).
  - Se usa 'Description' completo como etiqueta legible (hover y tabla).
  - Se quitaron los filtros de tipo de punto y de serial.

Sigue SIN bandas de control (decision: primero ver datos).

EJECUTAR:  py -m streamlit run app.py   ->  http://localhost:8501
REQUISITOS: py -m pip install streamlit plotly pandas sqlalchemy
"""

import sqlite3
import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import config_store as cfg
import correlacion_ref
from db_migrations import ensure_schema_and_backfill

DB_PATH = "data/motores.db"


def limpiar_description_display(description, variant):
    """Devuelve el Description legible para filtros/graficas.

    En CFM56 los buffers traen prefijos administrativos como "TEST 003 :".
    Para operar el dashboard interesa el rating/punto real, por ejemplo
    "MAXI CONTINU 5A1" o "TAKEOFF 7B24".
    """
    if description is None:
        return description
    txt = str(description).strip()
    if str(variant).upper().startswith("CFM56"):
        txt = re.sub(r"^\s*TEST\s*\d+\s*:\s*", "", txt, flags=re.IGNORECASE)
    return " ".join(txt.split())

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
        max-width: 100% !important;
    }

    section[data-testid="stSidebar"] div[data-baseweb="tag"] span {
        display: inline-block !important;
        max-width: 18rem !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        vertical-align: bottom !important;
    }

    ul[role="listbox"] li,
    div[role="option"] {
        white-space: normal !important;
        line-height: 1.25rem !important;
    }
</style>
"""

st.markdown(APP_CSS, unsafe_allow_html=True)

@st.cache_data
def load_data(db_path, db_mtime=None):
    # db_mtime solo participa en la clave de cache: invalida al cambiar motores.db.
    if not Path(db_path).exists():
        return None
    # Bases viejas: agrega columnas nuevas y rellena stable_point_key / fechas
    # ISO ANTES del SELECT, que ya asume ese schema. Idempotente: en una base
    # al dia no toca nada.
    ensure_schema_and_backfill(db_path)
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT
            tp.id            AS point_id,
            tp.stable_point_key AS stable_point_key,
            tp.variant       AS variant,
            tp.serial_number AS serial,
            tp.point_number  AS point_number,
            tp.test_date     AS test_date,
            tp.test_time     AS test_time,
            tp.test_date_raw AS test_date_raw,
            tp.test_date_iso AS test_date_iso,
            tp.test_datetime_iso AS test_datetime_iso,
            tp.date_parse_status AS date_parse_status,
            tp.date_parse_rule AS date_parse_rule,
            tp.description   AS description,
            tp.source_file   AS source_file,
            e.engine_type    AS engine_type,
            m.canonical      AS parametro,
            m.raw_name       AS raw_name,
            m.value          AS value,
            m.unit           AS unit
        FROM measurements m
        JOIN test_points tp ON m.point_id = tp.id
        JOIN engines e ON tp.engine_id = e.id
    """, con)
    con.close()

    # Fechas normalizadas por el ETL. Si una base vieja no tiene algun valor,
    # se conserva fallback DD/MM/YYYY para no dejar la app inutilizable.
    if "test_date_iso" not in df.columns:
        df["test_date_iso"] = None
    if "test_datetime_iso" not in df.columns:
        df["test_datetime_iso"] = None
    if "date_parse_status" not in df.columns:
        df["date_parse_status"] = None
    if "date_parse_rule" not in df.columns:
        df["date_parse_rule"] = None

    df["description_raw"] = df["description"]
    df["description"] = [
        limpiar_description_display(desc, var)
        for desc, var in zip(df["description_raw"], df["variant"])
    ]

    df["fecha"] = pd.to_datetime(df["test_date_iso"], errors="coerce")
    fecha_fallback = pd.to_datetime(df["test_date"], format="%d/%m/%Y", errors="coerce")
    df["fecha"] = df["fecha"].fillna(fecha_fallback)
    df["fecha_dt"] = pd.to_datetime(df["test_datetime_iso"], errors="coerce")
    df["fecha_dt"] = df["fecha_dt"].fillna(df["fecha"])

    # Version ISO (AAAA-MM-DD) de la fecha, para tablas ordenables.
    df["fecha_iso"] = df["test_date_iso"].fillna(df["fecha"].dt.strftime("%Y-%m-%d"))
    df["fecha_iso"] = df["fecha_iso"].fillna(df["test_date"])

    # Consecutivo por variante, ordenado por fecha normalizada (mas antiguo = 1).
    # Orden estable: fecha/hora ISO, numero de punto, id.
    df["pn_num"] = pd.to_numeric(df["point_number"], errors="coerce")
    puntos = (df[["point_id", "variant", "fecha", "fecha_dt", "test_time", "pn_num"]]
              .drop_duplicates("point_id")
              .sort_values(["variant", "fecha_dt", "fecha", "test_time", "pn_num", "point_id"],
                           na_position="last"))
    puntos["consecutivo"] = puntos.groupby("variant").cumcount() + 1
    df = df.merge(puntos[["point_id", "consecutivo"]], on="point_id", how="left")

    df["serie"] = df["raw_name"] + " [" + df["unit"].fillna("-") + "]"
    # cada version cruda + unidad es un parametro individual seleccionable
    df["param_label"] = df["raw_name"] + " [" + df["unit"].fillna("-") + "]"
    return df


def delete_test_point(db_path, point_id):
    """Borra un punto completo y todas sus mediciones asociadas."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        n_meas = cur.execute(
            "SELECT COUNT(*) FROM measurements WHERE point_id=?",
            (int(point_id),),
        ).fetchone()[0]
        cur.execute("DELETE FROM measurements WHERE point_id=?", (int(point_id),))
        cur.execute("DELETE FROM test_points WHERE id=?", (int(point_id),))
        n_points = cur.rowcount
        con.commit()
        return n_points, n_meas
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


QUARANTINE_DIR = "quarantine"


def quarantine_source_excels(source_files, source_folder, quarantine_root=QUARANTINE_DIR):
    """Mueve los Excel de origen a una carpeta de cuarentena (NO los borra).

    Los Excel son la evidencia primaria de cada punto; retirarlos del
    dashboard no debe destruirlos. Quedan en quarantine/AAAA-MM-DD/ junto a
    la app, y el registro de la accion se guarda en config.db
    (excel_quarantine_log).

    Devuelve (moved, missing, errors); moved es lista de (origen, destino).
    """
    import shutil
    from datetime import datetime

    folder = Path(source_folder).expanduser()
    dest_dir = Path(quarantine_root).expanduser() / datetime.now().strftime("%Y-%m-%d")
    moved = []
    missing = []
    errors = []

    for source_file in sorted(set(source_files)):
        if not source_file:
            continue
        src = Path(str(source_file))
        path = src if src.is_absolute() else folder / src.name
        try:
            if path.exists() and path.is_file():
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                seq = 1
                while dest.exists():
                    dest = dest_dir / f"{path.stem}_{seq}{path.suffix}"
                    seq += 1
                shutil.move(str(path), str(dest))
                moved.append((str(path), str(dest)))
            else:
                missing.append(str(path))
        except Exception as e:
            errors.append(f"{path}: {e}")

    return moved, missing, errors


_db_mtime = Path(DB_PATH).stat().st_mtime if Path(DB_PATH).exists() else None
df = load_data(DB_PATH, _db_mtime)

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


# FILTROS
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

# Filtro de Description (texto completo, seleccion multiple, default todos)
descripciones = sorted(dfv["description"].dropna().unique())
sel_desc = list(descripciones)
if descripciones:
    # default: vista guardada si sus desc existen, si no todos
    default_desc = descripciones
    if "f_desc" in st.session_state:
        guardados = [d for d in st.session_state["f_desc"] if d in descripciones]
        if guardados:
            default_desc = guardados
    sel_desc = st.sidebar.multiselect(
        "Description (rating / punto)", descripciones, default=default_desc,
        help="Filtra por el texto completo de Description. Por defecto, todos.",
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


def pos_evento_en_consecutivo(fecha_evento, pts_df):
    """Traduce la fecha de un evento a una posicion en el eje X numerico.

    El eje de tendencia usa el consecutivo real del reporte. Por eso la
    posicion del evento se interpola entre los consecutivos visibles que
    rodean su fecha, en vez de usar indices 0..n-1. Asi la linea queda en la
    misma fecha aunque se filtre el rango visible.

    Devuelve None si no hay fechas validas.
    """
    p = (pts_df.dropna(subset=["fecha", "consecutivo"])
                .drop_duplicates("consecutivo")
                .sort_values("consecutivo")
                .reset_index(drop=True))
    if p.empty:
        return None

    fe = pd.to_datetime(fecha_evento)
    if fe <= p["fecha"].iloc[0]:
        return float(p["consecutivo"].iloc[0]) - 0.5
    if fe >= p["fecha"].iloc[-1]:
        return float(p["consecutivo"].iloc[-1]) + 0.5

    for i in range(len(p) - 1):
        f0, f1 = p["fecha"].iloc[i], p["fecha"].iloc[i + 1]
        if f0 <= fe <= f1:
            c0 = float(p["consecutivo"].iloc[i])
            c1 = float(p["consecutivo"].iloc[i + 1])
            frac = (fe - f0) / (f1 - f0) if f1 != f0 else 0
            return c0 + frac * (c1 - c0)
    return None

# ===== TENDENCIA =====
if active_tab == "Tendencia":
    st.subheader(f"Tendencia - {sel_lbl}")

    # Cada version cruda (EGTK, EGTK3, FN, FNK...) es un parametro individual.
    todos_params = sorted(fdf["param_label"].unique())

    modo_comp = st.checkbox(
        "Modo comparacion: varios parametros con su propio eje Y", value=False,
        help="Compara hasta 4 parametros de magnitudes distintas. "
             "Comparten el eje X (consecutivo).",
    )

    if not modo_comp:
        # --- Un solo parametro ---
        # Si hay un parametro guardado por una vista y existe en la lista, usarlo.
        if "f_param" in st.session_state and st.session_state["f_param"] in todos_params:
            default_idx = todos_params.index(st.session_state["f_param"])
        else:
            default_idx = next((i for i, p in enumerate(todos_params)
                                if p.startswith("EGTK ") or p.startswith("EGTR2 ")), 0)
        p_sel = st.selectbox("Parametro", todos_params, index=default_idx, key="f_param")

        sub = fdf[fdf["param_label"] == p_sel].copy().sort_values("consecutivo")
        # eje X solo con consecutivos activos
        orden = sorted(sub["consecutivo"].unique())

        # ---- Controles de vista en la BARRA LATERAL (plegables) ----
        with st.sidebar.expander("Bandas / baseline", expanded=False):
            mostrar_bandas = st.checkbox("Mostrar bandas (+/-Nsigma)", value=False)
            n_sigma = st.slider("N (sigma)", min_value=1, max_value=6, value=3, step=1)
            baseline_modo = st.selectbox(
                "Baseline estadistico",
                ["Historico completo", "Visible", "Rango manual"],
                index=0,
                help="Define de donde salen media y sigma. La ventana visible solo controla lo que ves.",
                key="baseline_modo_tend",
            )
            baseline_fechas = None
            if baseline_modo == "Rango manual":
                _bf = dfv_hist["fecha"].dropna()
                if not _bf.empty:
                    baseline_fechas = st.date_input(
                        "Fechas baseline",
                        value=(_bf.min().date(), _bf.max().date()),
                        min_value=_bf.min().date(),
                        max_value=_bf.max().date(),
                        key="baseline_fechas_tend",
                    )

        with st.sidebar.expander("Tendencia / regresion", expanded=False):
            mostrar_reg = st.checkbox("Linea de tendencia (regresion)", value=False)
            proy = st.slider("Proyectar N reportes adelante", 0, 10, 3, step=1,
                             help="Extiende la recta de regresion para anticipar deriva.")

        with st.sidebar.expander("Deteccion de drift", expanded=False):
            mostrar_drift = st.checkbox("Activar deteccion de drift", value=False)
            ventana_mm = st.slider("Ventana media movil", 2, 12, 5, step=1)
            cusum_k = st.slider("CUSUM: holgura k (en sigma)", 0.0, 2.0, 0.5, step=0.1,
                                help="Margen que se ignora antes de acumular. Tipico 0.5 sigma.")
            cusum_h = st.slider("CUSUM: limite H (en sigma)", 2.0, 8.0, 4.0, step=0.5,
                                help="Umbral de alarma de la suma acumulada. Tipico 4-5 sigma.")

        # un solo Description activo es requisito para bandas/umbrales con sentido
        un_solo_desc = len(sel_desc) == 1

        def obtener_base_calc(param_label, desc, visible_df):
            if baseline_modo == "Visible":
                return visible_df, "visible"
            base = dfv_hist[
                (dfv_hist["param_label"] == param_label)
                & (dfv_hist["description"] == desc)
            ].copy()
            if baseline_modo == "Rango manual" and isinstance(baseline_fechas, tuple) and len(baseline_fechas) == 2:
                d0b, d1b = baseline_fechas
                base = base[(base["fecha"].dt.date >= d0b) & (base["fecha"].dt.date <= d1b)]
                return base, f"rango manual {d0b.isoformat()} a {d1b.isoformat()}"
            return base, "historico completo"

        # ---- Umbrales fijos (limites manuales) por variante+parametro+description ----
        with st.sidebar.expander("Umbrales fijos (limites)", expanded=False):
            if not un_solo_desc:
                st.caption("Filtra a UN solo Description para definir o ver umbrales.")
                low_fijo = high_fijo = None
                mostrar_umbral = False
            else:
                desc_actual = sel_desc[0]
                low_guardado, high_guardado = cfg.get_threshold(sel_var, p_sel, desc_actual)
                st.caption(f"Para {p_sel} - {desc_actual}")
                mostrar_umbral = st.checkbox("Aplicar umbrales fijos", value=False)
                c_lo, c_hi = st.columns(2)
                with c_lo:
                    low_in = st.number_input(
                        "Limite inferior", value=float(low_guardado) if low_guardado is not None else 0.0,
                        format="%.3f", key="low_fijo")
                    usar_low = st.checkbox("usar inf.", value=low_guardado is not None, key="ulow")
                with c_hi:
                    high_in = st.number_input(
                        "Limite superior", value=float(high_guardado) if high_guardado is not None else 0.0,
                        format="%.3f", key="high_fijo")
                    usar_high = st.checkbox("usar sup.", value=high_guardado is not None, key="uhigh")
                low_fijo = low_in if usar_low else None
                high_fijo = high_in if usar_high else None
                cbtn1, cbtn2 = st.columns(2)
                with cbtn1:
                    if st.button("Guardar umbral"):
                        cfg.set_threshold(sel_var, p_sel, desc_actual, low_fijo, high_fijo)
                        st.success("Guardado.")
                with cbtn2:
                    if st.button("Borrar umbral"):
                        cfg.delete_threshold(sel_var, p_sel, desc_actual)
                        st.success("Borrado.")

        fig = px.line(
            sub, x="consecutivo", y="value", markers=True,
            labels={"value": p_sel, "consecutivo": "No de reporte (consecutivo)"},
            hover_data={"description": True, "test_date": True, "source_file": True},
            title=f"{p_sel} - {sel_lbl}",
        )
        regresion_export = None
        media_movil_export = None
        eventos_export = []

        if mostrar_bandas:
            if not un_solo_desc:
                st.info("Para mostrar bandas, filtra a UN solo Description en la barra "
                        "lateral (mezclar ratings distintos da una media sin sentido).")
            else:
                # datos para calcular media/sigma desde baseline elegido
                base_calc, baseline_label = obtener_base_calc(p_sel, sel_desc[0], sub)
                vals = base_calc["value"].astype(float).dropna()
                if len(vals) >= 2:
                    media = vals.mean()
                    sigma = vals.std(ddof=1)  # sigma muestral
                    ucl = media + n_sigma * sigma
                    lcl = media - n_sigma * sigma

                    # lineas horizontales: media y limites
                    fig.add_hline(y=media, line_dash="solid", line_color="green",
                                  annotation_text="media", annotation_position="right")
                    fig.add_hline(y=ucl, line_dash="dash", line_color="red",
                                  annotation_text=f"+{n_sigma}sigma", annotation_position="right")
                    fig.add_hline(y=lcl, line_dash="dash", line_color="red",
                                  annotation_text=f"-{n_sigma}sigma", annotation_position="right")

                    # resaltar puntos fuera de banda
                    fuera = sub[(sub["value"] > ucl) | (sub["value"] < lcl)]
                    if not fuera.empty:
                        import plotly.graph_objects as go
                        fig.add_trace(go.Scatter(
                            x=fuera["consecutivo"], y=fuera["value"], mode="markers",
                            marker=dict(color="red", size=14, symbol="x"),
                            name="Fuera de banda",
                            customdata=fuera[["description", "test_date", "source_file"]],
                            hovertemplate="FUERA DE BANDA<br>consec %{x}<br>valor %{y}<br>"
                                          "%{customdata[0]}<br>fecha %{customdata[1]}<br>"
                                          "archivo %{customdata[2]}<extra></extra>",
                        ))

                    st.caption(
                        f"Media = {media:.3f} - sigma = {sigma:.3f} - "
                        f"+/-{n_sigma}sigma -> [{lcl:.3f}, {ucl:.3f}] - "
                        f"base: {baseline_label} "
                        f"({len(vals)} puntos) - "
                        f"{len(fuera) if un_solo_desc else 0} fuera de banda"
                    )
                else:
                    st.info("No hay suficientes puntos (a2) para calcular las bandas.")

        # ---- Linea de tendencia / regresion ----
        if mostrar_reg:
            import numpy as np
            import plotly.graph_objects as go
            sreg = sub.dropna(subset=["value"]).sort_values("consecutivo")
            if len(sreg) >= 2:
                x = sreg["consecutivo"].astype(float).values
                y = sreg["value"].astype(float).values
                pendiente, interseccion = np.polyfit(x, y, 1)
                x_fin = x.max() + proy
                x_line = np.array([x.min(), x_fin])
                y_line = pendiente * x_line + interseccion
                fig.add_trace(go.Scatter(
                    x=x_line, y=y_line, mode="lines",
                    line=dict(color="orange", dash="dot", width=2),
                    name=f"Tendencia (pend={pendiente:+.3f}/reporte)",
                ))
                regresion_export = {
                    "x": x_line.tolist(),
                    "y": y_line.tolist(),
                    "pendiente": float(pendiente),
                    "interseccion": float(interseccion),
                    "proy": int(proy),
                    "x_min": float(x.min()),
                    "x_max": float(x_fin),
                }

                # marcar zona de proyeccion con un area
                if proy > 0:
                    st.caption(
                        f"Pendiente = {pendiente:+.4f} por reporte - "
                        f"interseccion = {interseccion:.3f} - "
                        f"proyeccion a +{proy}: {pendiente * x_fin + interseccion:.3f}"
                    )
                else:
                    st.caption(f"Pendiente = {pendiente:+.4f} por reporte - "
                               f"interseccion = {interseccion:.3f}")
            else:
                st.info("No hay suficientes puntos (a2) para la regresion.")

        # ---- Umbrales fijos: lineas en la grafica ----
        cruces_umbral = pd.DataFrame()
        if un_solo_desc and mostrar_umbral and (low_fijo is not None or high_fijo is not None):
            if high_fijo is not None:
                fig.add_hline(y=high_fijo, line_dash="dashdot", line_color="purple",
                              annotation_text=f"limite sup {high_fijo:.1f}",
                              annotation_position="left")
            if low_fijo is not None:
                fig.add_hline(y=low_fijo, line_dash="dashdot", line_color="purple",
                              annotation_text=f"limite inf {low_fijo:.1f}",
                              annotation_position="left")
            # puntos que cruzan el umbral fijo
            cond = pd.Series(False, index=sub.index)
            if high_fijo is not None:
                cond = cond | (sub["value"] > high_fijo)
            if low_fijo is not None:
                cond = cond | (sub["value"] < low_fijo)
            cruces_umbral = sub[cond].copy()
            if not cruces_umbral.empty:
                import plotly.graph_objects as go
                fig.add_trace(go.Scatter(
                    x=cruces_umbral["consecutivo"], y=cruces_umbral["value"],
                    mode="markers", marker=dict(color="purple", size=14, symbol="diamond"),
                    name="Cruza umbral fijo",
                    customdata=cruces_umbral[["description", "test_date", "source_file"]],
                    hovertemplate="CRUZA UMBRAL<br>consec %{x}<br>valor %{y}<br>"
                                  "%{customdata[0]}<br>fecha %{customdata[1]}<br>"
                                  "archivo %{customdata[2]}<extra></extra>",
                ))

        # ---- Drift: media movil sobre la grafica ----
        if mostrar_drift:
            import plotly.graph_objects as go
            sdr = sub.sort_values("consecutivo")
            mm = sdr["value"].rolling(window=ventana_mm, min_periods=1).mean()
            fig.add_trace(go.Scatter(
                x=sdr["consecutivo"], y=mm, mode="lines",
                line=dict(color="darkorange", width=2.5),
                name=f"Media movil ({ventana_mm})",
                customdata=sdr[["description", "test_date", "source_file"]],
                hovertemplate="reporte %{x}<br>media movil %{y:.3f}<br>"
                              "%{customdata[0]}<br>fecha %{customdata[1]}<br>"
                              "archivo %{customdata[2]}<extra></extra>",
            ))
            media_movil_export = {
                "x": sdr["consecutivo"].astype(float).tolist(),
                "y": mm.astype(float).tolist(),
                "ventana": int(ventana_mm),
            }

        # ---- Eventos: lineas verticales con etiqueta ----
        mostrar_eventos = st.checkbox(
            "Mostrar eventos en la grafica", value=False,
            help="Marca actualizaciones, recalibraciones, etc. en su posicion temporal.",
        )
        if mostrar_eventos:
            eventos = cfg.list_events(scope=sel_var)
            # posiciones de los reportes visibles (para interpolar)
            pts_vis = sub[["consecutivo", "fecha"]].drop_duplicates()
            n_dibujados = 0
            for ev in eventos:
                xcoord = pos_evento_en_consecutivo(ev["event_date"], pts_vis)
                if xcoord is None:
                    continue
                # solo dibujar si cae dentro del rango visible (con margen 0.5)
                if xcoord < min(orden) - 0.5 or xcoord > max(orden) + 0.5:
                    continue
                fig.add_vline(x=xcoord, line_width=2, line_dash="dot", line_color="teal")
                fig.add_annotation(x=xcoord, yref="paper", y=1.0, showarrow=False,
                                   text=ev["name"], textangle=-90,
                                   font=dict(color="teal", size=11),
                                   xanchor="left", yanchor="top")
                eventos_export.append((float(xcoord), ev["name"], ev["event_date"]))
                n_dibujados += 1
            if n_dibujados == 0:
                st.caption("No hay eventos dentro del rango visible para esta variante.")

        fig.update_layout(height=520)
        st.plotly_chart(fig, use_container_width=True)

        # ---- Drift: CUSUM + alerta de racha (debajo de la grafica) ----
        if mostrar_drift:
            import numpy as np
            import plotly.graph_objects as go
            sdr = sub.sort_values("consecutivo")
            serie = sdr["value"].astype(float).reset_index(drop=True)
            consec = sdr["consecutivo"].astype(int).reset_index(drop=True)

            if len(serie) >= 3:
                # base de media/sigma: baseline elegido si hay un solo Description
                if un_solo_desc:
                    base_calc_d, _baseline_label_d = obtener_base_calc(p_sel, sel_desc[0], sub)
                    base_d = base_calc_d["value"].astype(float)
                else:
                    base_d = serie
                mu = base_d.mean()
                sd = base_d.std(ddof=1) if base_d.std(ddof=1) > 0 else 1.0

                # CUSUM tabular (acumula desviaciones normalizadas)
                k = cusum_k  # holgura en sigmas
                h = cusum_h  # limite en sigmas
                z = (serie - mu) / sd
                sh = np.zeros(len(z))  # suma alta (detecta subidas)
                sl = np.zeros(len(z))  # suma baja (detecta bajadas)
                for i in range(len(z)):
                    prev_h = sh[i-1] if i > 0 else 0.0
                    prev_l = sl[i-1] if i > 0 else 0.0
                    sh[i] = max(0.0, prev_h + z[i] - k)
                    sl[i] = min(0.0, prev_l + z[i] + k)

                figd = go.Figure()
                xcat = consec.astype(str)
                cusum_hover = sdr[["test_date", "source_file"]].astype(str).to_numpy()
                figd.add_trace(go.Scatter(
                    x=xcat, y=sh, mode="lines+markers",
                    name="CUSUM+ (subidas)", line=dict(color="crimson"),
                    customdata=cusum_hover,
                    hovertemplate="reporte %{x}<br>CUSUM+ %{y:.3f}<br>"
                                  "fecha %{customdata[0]}<br>archivo %{customdata[1]}"
                                  "<extra></extra>",
                ))
                figd.add_trace(go.Scatter(
                    x=xcat, y=sl, mode="lines+markers",
                    name="CUSUM- (bajadas)", line=dict(color="royalblue"),
                    customdata=cusum_hover,
                    hovertemplate="reporte %{x}<br>CUSUM- %{y:.3f}<br>"
                                  "fecha %{customdata[0]}<br>archivo %{customdata[1]}"
                                  "<extra></extra>",
                ))
                figd.add_hline(y=h, line_dash="dash", line_color="crimson")
                figd.add_hline(y=-h, line_dash="dash", line_color="royalblue")
                figd.update_layout(height=300, title="CUSUM (suma acumulada de desviaciones, en sigma)",
                                   xaxis_title="No de reporte", yaxis_title="CUSUM (sigma)",
                                   margin=dict(t=40))
                st.plotly_chart(figd, use_container_width=True)

                # alarmas CUSUM
                alarma_sube = consec[sh > h].tolist()
                alarma_baja = consec[sl < -h].tolist()
                if alarma_sube:
                    st.warning(f"as  CUSUM detecta DERIVA AL ALZA. Primer reporte que dispara: "
                               f"{alarma_sube[0]} (limite H={h}sigma).")
                if alarma_baja:
                    st.warning(f"as  CUSUM detecta DERIVA A LA BAJA. Primer reporte que dispara: "
                               f"{alarma_baja[0]} (limite H={h}sigma).")
                if not alarma_sube and not alarma_baja:
                    st.success("CUSUM no detecta deriva sostenida con los parametros actuales.")

                # ---- Alerta de racha (N reportes consecutivos subiendo/bajando) ----
                diffs = serie.diff().dropna()
                def racha_final(signo):
                    cnt = 0
                    for d in reversed(diffs.tolist()):
                        if (signo > 0 and d > 0) or (signo < 0 and d < 0):
                            cnt += 1
                        else:
                            break
                    return cnt
                r_sube = racha_final(1)
                r_baja = racha_final(-1)
                UMBRAL_RACHA = 4
                if r_sube >= UMBRAL_RACHA:
                    st.warning(f"as  Racha: el parametro lleva {r_sube} reportes consecutivos SUBIENDO.")
                elif r_baja >= UMBRAL_RACHA:
                    st.warning(f"as  Racha: el parametro lleva {r_baja} reportes consecutivos BAJANDO.")
                else:
                    st.caption(f"Racha actual: {r_sube} subiendo / {r_baja} bajando "
                               f"(alerta a partir de {UMBRAL_RACHA}).")
            else:
                st.info("Se necesitan al menos 3 puntos para la deteccion de drift.")

        # ---- Alerta visual + tabla de cruces de umbral fijo ----
        if un_solo_desc and mostrar_umbral and (low_fijo is not None or high_fijo is not None):
            if not cruces_umbral.empty:
                st.error(f"as  {len(cruces_umbral)} punto(s) cruzan el umbral fijo definido.")
                tcr = cruces_umbral[["consecutivo", "description", "test_date", "value"]].copy()
                tcr = tcr.rename(columns={"consecutivo": "Reporte", "description": "Description",
                                          "test_date": "Fecha", "value": "Valor"})
                st.dataframe(tcr.sort_values("Reporte"), use_container_width=True, hide_index=True)
            else:
                st.success("Ningun punto cruza el umbral fijo con los filtros actuales.")

        # ---- Deteccion automatica de outliers (lista) ----
        if mostrar_bandas and un_solo_desc:
            # recalcular base igual que arriba para listar
            base_calc, baseline_label = obtener_base_calc(p_sel, sel_desc[0], sub)
            vals = base_calc["value"].astype(float).dropna()
            if len(vals) >= 2:
                media = vals.mean()
                sigma = vals.std(ddof=1)
                ucl = media + n_sigma * sigma
                lcl = media - n_sigma * sigma
                fuera = sub[(sub["value"] > ucl) | (sub["value"] < lcl)].copy()
                st.markdown(f"**Outliers detectados (fuera de +/-{n_sigma}sigma): {len(fuera)}**")
                if not fuera.empty:
                    fuera["desviacion_sigma"] = (fuera["value"] - media) / sigma
                    tabla = fuera[["consecutivo", "description", "test_date",
                                   "value", "desviacion_sigma"]].copy()
                    tabla = tabla.rename(columns={
                        "consecutivo": "Reporte", "description": "Description",
                        "test_date": "Fecha", "value": "Valor",
                        "desviacion_sigma": "Desv (sigma)"})
                    tabla["Desv (sigma)"] = tabla["Desv (sigma)"].round(2)
                    st.dataframe(tabla.sort_values("Reporte"),
                                 use_container_width=True, hide_index=True)
                else:
                    st.caption("Ningun punto fuera de banda con los filtros actuales.")

        # ---- Exportar reporte (Excel / PDF) ----
        st.markdown("---")
        st.markdown("**Exportar reporte**")
        # reunir estadisticas actuales (si hay bandas calculadas)
        stats_export = {}
        stats_grafica = None
        if un_solo_desc:
            base_calc, baseline_label_export = obtener_base_calc(p_sel, sel_desc[0], sub)
            vals_e = base_calc["value"].astype(float).dropna()
            if len(vals_e) >= 2:
                media_e = vals_e.mean()
                sigma_e = vals_e.std(ddof=1)
                ucl_e = media_e + n_sigma * sigma_e
                lcl_e = media_e - n_sigma * sigma_e
                fuera_e = sub[(sub["value"] > ucl_e) | (sub["value"] < lcl_e)]
                stats_export = {
                    "Media": round(media_e, 4), "Sigma": round(sigma_e, 4),
                    f"+{n_sigma}sigma (UCL)": round(ucl_e, 4),
                    f"-{n_sigma}sigma (LCL)": round(lcl_e, 4),
                    "N puntos (base)": len(vals_e),
                    "Outliers (visibles)": len(fuera_e),
                    "Base de calculo": baseline_label_export,
                }
                stats_grafica = {"media": media_e, "ucl": ucl_e, "lcl": lcl_e,
                                 "n_sigma": n_sigma}

        if regresion_export:
            stats_export.update({
                "Regresion pendiente por reporte": round(regresion_export["pendiente"], 6),
                "Regresion interseccion": round(regresion_export["interseccion"], 6),
                "Regresion proyeccion reportes": regresion_export["proy"],
            })

        _fechas_export = st.session_state.get("f_fechas")
        if isinstance(_fechas_export, tuple) and len(_fechas_export) == 2:
            rango_fechas_txt = f"{_fechas_export[0].isoformat()} a {_fechas_export[1].isoformat()}"
        elif isinstance(_fechas_export, list) and len(_fechas_export) == 2:
            rango_fechas_txt = f"{_fechas_export[0].isoformat()} a {_fechas_export[1].isoformat()}"
        else:
            rango_fechas_txt = "Historico visible completo"

        desc_txt = "; ".join(sel_desc) if sel_desc else "(ninguna)"
        baseline_export_txt = baseline_modo
        if baseline_modo == "Rango manual" and isinstance(baseline_fechas, tuple) and len(baseline_fechas) == 2:
            baseline_export_txt = (
                f"Rango manual {baseline_fechas[0].isoformat()} a {baseline_fechas[1].isoformat()}"
            )
        eventos_txt = (
            "; ".join(f"{ev[2]} - {ev[1]}" for ev in eventos_export)
            if eventos_export else "Ninguno dibujado"
        )
        umbrales_export = None
        if un_solo_desc and mostrar_umbral and (low_fijo is not None or high_fijo is not None):
            umbrales_export = {"low": low_fijo, "high": high_fijo}

        config_export = {
            "Variante de motor": sel_lbl,
            "Parametro": p_sel,
            "Descriptions seleccionadas": desc_txt,
            "Rango de fechas": rango_fechas_txt,
            "Puntos visibles en grafica": sub["consecutivo"].nunique(),
            "Rango de reportes visible": f"{min(orden)} a {max(orden)}" if orden else "Sin datos",
            "Modo comparacion": "No",
            "Bandas de control visibles": "Si" if mostrar_bandas else "No",
            "N sigma": n_sigma,
            "Base de calculo de bandas": baseline_export_txt,
            "Umbrales fijos visibles": "Si" if (un_solo_desc and mostrar_umbral) else "No",
            "Limite inferior fijo": low_fijo if (un_solo_desc and low_fijo is not None) else "No usado",
            "Limite superior fijo": high_fijo if (un_solo_desc and high_fijo is not None) else "No usado",
            "Regresion visible": "Si" if mostrar_reg else "No",
            "Regresion proyectar N reportes": proy,
            "Deteccion de drift visible": "Si" if mostrar_drift else "No",
            "Ventana media movil": ventana_mm,
            "CUSUM k (sigma)": cusum_k,
            "CUSUM H (sigma)": cusum_h,
            "Eventos visibles": "Si" if mostrar_eventos else "No",
            "Eventos dibujados": eventos_txt,
        }

        meta_export = {
            "Variante": sel_lbl,
            "Parametro": p_sel,
            "Description": sel_desc[0] if un_solo_desc else f"varios ({len(sel_desc)})",
            "Rango de fechas": rango_fechas_txt,
            "Generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "Puntos en reporte": sub["consecutivo"].nunique(),
        }
        datos_export = sub[["consecutivo", "description", "test_date",
                            "value", "unit"]].sort_values("consecutivo").rename(
            columns={"consecutivo": "Reporte", "description": "Description",
                     "test_date": "Fecha", "value": "Valor", "unit": "Unidad"})

        import report_export as rx
        try:
            png_bytes = rx.grafica_tendencia_png(
                sub, p_sel, sel_lbl,
                stats_grafica if mostrar_bandas else None,
                eventos_pos=eventos_export if mostrar_eventos else None,
                regresion=regresion_export if mostrar_reg else None,
                umbrales=umbrales_export,
                media_movil=media_movil_export if mostrar_drift else None,
            )
        except Exception as e:
            png_bytes = None
            st.caption(f"No se pudo generar la grafica para exportar: {e}")

        cexp1, cexp2 = st.columns(2)
        with cexp1:
            try:
                xlsx_bytes = rx.exportar_excel(
                    datos_export, stats_export, meta_export, config_export, png_bytes
                )
                st.download_button(
                    "Descargar Excel", data=xlsx_bytes,
                    file_name=f"reporte_{sel_var}_{p_sel.split(' ')[0]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as e:
                st.caption(f"No se pudo generar Excel: {e}")
        with cexp2:
            try:
                pdf_bytes = rx.exportar_pdf(datos_export, stats_export, meta_export,
                                            png_bytes, config_export)
                st.download_button(
                    "Descargar PDF", data=pdf_bytes,
                    file_name=f"reporte_{sel_var}_{p_sel.split(' ')[0]}.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.caption(f"No se pudo generar PDF: {e}")

    else:
        # --- Varios parametros, cada uno con su eje Y ---
        sel_multi = st.multiselect(
            "Parametros a comparar (max 4)", todos_params,
            default=todos_params[:2], max_selections=4, key="tend_multi",
        )
        vista = st.radio(
            "Escala", ["Ejes Y separados (valores reales)", "Normalizado 0-100%"],
            horizontal=True,
        )

        if not sel_multi:
            st.info("Selecciona al menos un parametro.")
        else:
            import plotly.graph_objects as go
            # consecutivos activos (union de los parametros elegidos)
            base = fdf[fdf["param_label"].isin(sel_multi)]
            orden = sorted(base["consecutivo"].unique())
            xcat = [str(c) for c in orden]

            fig = go.Figure()
            colores = px.colors.qualitative.Plotly

            if vista.startswith("Normalizado"):
                # todos en un solo eje, escalados a 0-100%
                for i, p in enumerate(sel_multi):
                    s = base[base["param_label"] == p].sort_values("consecutivo")
                    v = s["value"].astype(float)
                    rng = v.max() - v.min()
                    vn = (v - v.min()) / rng * 100 if rng != 0 else v * 0 + 50
                    fig.add_trace(go.Scatter(
                        x=s["consecutivo"].astype(str), y=vn, mode="lines+markers",
                        name=p, line=dict(color=colores[i % len(colores)]),
                        customdata=s[["description", "value", "test_date", "source_file"]],
                        hovertemplate=("%{x}<br>" + p + "<br>real=%{customdata[1]}"
                                       "<br>%{customdata[0]}<br>fecha %{customdata[2]}"
                                       "<br>archivo %{customdata[3]}<extra></extra>"),
                    ))
                fig.update_yaxes(title_text="Valor normalizado (0-100%)")
                fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=xcat))
            else:
                # cada parametro su propio eje Y
                for i, p in enumerate(sel_multi):
                    s = base[base["param_label"] == p].sort_values("consecutivo")
                    axis_id = "y" if i == 0 else f"y{i+1}"
                    fig.add_trace(go.Scatter(
                        x=s["consecutivo"].astype(str), y=s["value"], mode="lines+markers",
                        name=p, yaxis=axis_id, line=dict(color=colores[i % len(colores)]),
                        customdata=s[["description", "test_date", "source_file"]],
                        hovertemplate=("%{x}<br>" + p + "=%{y}<br>%{customdata[0]}"
                                       "<br>fecha %{customdata[1]}"
                                       "<br>archivo %{customdata[2]}<extra></extra>"),
                    ))
                # configurar ejes Y multiples
                layout_axes = {"xaxis": dict(title="No de reporte (consecutivo)",
                                             categoryorder="array", categoryarray=xcat)}
                posiciones_der = [1.0, 0.94, 0.88]
                for i, p in enumerate(sel_multi):
                    col = colores[i % len(colores)]
                    if i == 0:
                        layout_axes["yaxis"] = dict(
                            title=dict(text=p, font=dict(color=col)),
                            tickfont=dict(color=col))
                    else:
                        side = "right"
                        pos = posiciones_der[(i-1) % len(posiciones_der)]
                        layout_axes[f"yaxis{i+1}"] = dict(
                            title=dict(text=p, font=dict(color=col)),
                            overlaying="y", side=side, position=pos,
                            tickfont=dict(color=col),
                            anchor="free" if i > 1 else "x",
                        )
                fig.update_layout(**layout_axes)

            fig.update_layout(height=560, legend=dict(orientation="h", y=1.12),
                              margin=dict(r=120))
            st.plotly_chart(fig, use_container_width=True)
            if vista.startswith("Ejes") and len(sel_multi) > 2:
                st.caption("Con mas de 2 parametros los ejes Y se apilan a la derecha; "
                           "si se satura, prueba la vista Normalizado.")

# ===== CORRELACION =====
if active_tab == "Correlacion":
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

    def serie_por_punto(data, param_label):
        s = data[data["param_label"] == param_label]
        if s.empty:
            return None
        return s.groupby(["point_id", "consecutivo", "description", "test_date", "source_file"],
                         as_index=False, dropna=False)["value"].mean().rename(columns={"value": param_label})

    gx = serie_por_punto(fdf, px_par)
    gy = serie_por_punto(fdf, py_par)
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

# ===== CORRELACION REF. (vs celda de pruebas, con bandas +-N sigma) =====
if active_tab == "Correlacion Ref.":
    correlacion_ref.render(fdf, sel_var, sel_lbl)

# ===== DATOS =====
if active_tab == "Datos":
    st.subheader("Datos filtrados")
    st.caption(
        "Selecciona una fila de la tabla y usa el boton para retirar el punto "
        "completo al que pertenece esa medicion. El Excel de origen NO se "
        f"borra: se mueve a la carpeta '{QUARANTINE_DIR}/' junto a la app."
    )
    source_folder = st.text_input(
        "Carpeta donde estan los Excel de origen",
        value=st.session_state.get("source_excel_folder", ""),
        key="source_excel_folder",
        placeholder=r"C:\ruta\a\carpeta_de_pruebas",
        help="De ahi se toma el archivo indicado en source_file para moverlo a cuarentena.",
    )

    cols = ["point_id", "consecutivo", "description", "fecha_iso", "date_parse_status",
            "date_parse_rule", "point_number", "source_file", "param_label", "value", "unit"]
    datos_tabla = fdf[cols].rename(columns={"fecha_iso": "fecha"}) \
        .sort_values(["consecutivo", "param_label"]).reset_index(drop=True)
    tabla_event = st.dataframe(
        datos_tabla,
        use_container_width=True, height=480,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
    )

    selected_rows = tabla_event.selection.rows
    if selected_rows:
        filas_sel = datos_tabla.iloc[selected_rows]
        punto_ids = sorted({int(pid) for pid in filas_sel["point_id"].dropna().unique()})
        source_files = sorted(str(s) for s in filas_sel["source_file"].dropna().unique())
        n_med_visibles = int(fdf[fdf["point_id"].isin(punto_ids)].shape[0])
        st.info(
            f"Puntos seleccionados: {len(punto_ids)} | "
            f"mediciones visibles asociadas: {n_med_visibles} | "
            f"Exceles asociados: {len(source_files)}."
        )
        st.caption(
            "Se retiraran de la base los puntos completos asociados a las filas "
            "seleccionadas (con sus mediciones) y sus Excel de origen se moveran "
            "a cuarentena. Nada se destruye: el Excel se puede restaurar a mano."
        )
        motivo_retiro = st.text_input(
            "Motivo del retiro (queda en el registro de cuarentena)",
            key="quarantine_reason",
            placeholder="Ej: punto capturado con celda descalibrada",
        )
        puede_borrar = bool(source_folder.strip())
        if not puede_borrar:
            st.caption("Indica la carpeta de Exceles para habilitar el retiro.")
        if st.button("Retirar puntos y mover Exceles a cuarentena", type="primary",
                     disabled=not puede_borrar):
            try:
                # 1) primero se pone a salvo la evidencia (mover Excel);
                # 2) luego se retiran los puntos de la base;
                # 3) al final se registra todo en config.db.
                moved_files, missing_files, file_errors = quarantine_source_excels(
                    source_files, source_folder,
                )
                if file_errors:
                    st.error("No se pudieron mover algunos Excel: " + " | ".join(file_errors))
                    st.stop()

                # puntos/llaves asociados a cada Excel, para el registro
                sel_puntos = (
                    fdf[fdf["point_id"].isin(punto_ids)]
                    [["point_id", "stable_point_key", "source_file"]]
                    .drop_duplicates("point_id")
                )

                total_points = 0
                total_meas = 0
                for punto_id in punto_ids:
                    n_points, n_meas = delete_test_point(DB_PATH, punto_id)
                    total_points += n_points
                    total_meas += n_meas
                load_data.clear()

                destino_por_origen = dict(moved_files)
                for source_file in source_files:
                    src = Path(str(source_file))
                    path = src if src.is_absolute() else Path(source_folder).expanduser() / src.name
                    afectados = sel_puntos[sel_puntos["source_file"].astype(str) == str(source_file)]
                    cfg.log_excel_quarantine(
                        source_file=str(source_file),
                        original_path=str(path),
                        quarantine_path=destino_por_origen.get(str(path)),
                        point_ids=afectados["point_id"].tolist(),
                        stable_point_keys=afectados["stable_point_key"].tolist(),
                        reason=motivo_retiro.strip(),
                    )

                if total_points:
                    st.success(
                        f"Se retiraron {total_points} punto(s), {total_meas} mediciones. "
                        f"{len(moved_files)} Excel(es) movidos a cuarentena."
                    )
                    if missing_files:
                        st.warning(
                            "No se encontraron estos Excel (los puntos si se retiraron): "
                            + " | ".join(missing_files)
                        )
                    st.rerun()
                else:
                    st.warning("No se encontraron esos puntos en la base.")
            except Exception as e:
                st.error(f"No se pudieron retirar los puntos: {e}")
    else:
        st.caption("No hay ninguna fila seleccionada.")
    st.caption(f"{len(fdf)} mediciones - {sel_lbl}")

    # ---- Historial de cuarentena ----
    historial_q = cfg.list_excel_quarantine()
    if historial_q:
        with st.expander(f"Historial de cuarentena ({len(historial_q)} registro(s))",
                         expanded=False):
            st.caption(
                "Exceles retirados del dashboard. El archivo sigue en la ruta "
                "de cuarentena indicada; para reincorporarlo, muevelo de vuelta "
                "a la carpeta de origen y vuelve a correr el ETL."
            )
            st.dataframe(
                pd.DataFrame(historial_q)[
                    ["created_at", "source_file", "quarantine_path", "point_ids", "reason"]
                ].rename(columns={
                    "created_at": "Fecha", "source_file": "Archivo",
                    "quarantine_path": "Ruta cuarentena", "point_ids": "point_id(s)",
                    "reason": "Motivo",
                }),
                use_container_width=True, hide_index=True,
            )


# ===== ANOMALIAS (vista consolidada de todo lo que merece revision) =====
if active_tab == "Anomalias":
    st.subheader(f"Anomalias - {sel_lbl}")
    st.caption("Vista consolidada de outliers, cruces de umbral, deriva CUSUM "
               "y rachas largas. Recorre todos los parametros del nucleo y "
               "respeta tus filtros de fecha y Description.")

    import anomaly_engine as ae

    # Controles
    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        n_sigma_a = st.slider("N sigma (outliers)", 1, 6, 3, key="anom_nsig")
    with cc2:
        cusum_k_a = st.slider("CUSUM k (sigma)", 0.0, 2.0, 0.5, step=0.1, key="anom_k")
    with cc3:
        cusum_h_a = st.slider("CUSUM H (sigma)", 2.0, 8.0, 4.0, step=0.5, key="anom_h")


    with st.expander("Baseline de deteccion", expanded=False):
        baseline_modo_a = st.selectbox(
            "Baseline estadistico para anomalias",
            ["Historico completo", "Visible", "Rango manual"],
            index=0,
            key="baseline_modo_anom",
            help="Media/sigma para outliers y CUSUM. La lista de anomalias sigue respetando los filtros visibles.",
        )
        baseline_fechas_a = None
        if baseline_modo_a == "Rango manual":
            _bfa = dfv_hist["fecha"].dropna()
            if not _bfa.empty:
                baseline_fechas_a = st.date_input(
                    "Fechas baseline anomalias",
                    value=(_bfa.min().date(), _bfa.max().date()),
                    min_value=_bfa.min().date(),
                    max_value=_bfa.max().date(),
                    key="baseline_fechas_anom",
                )

    def construir_baseline_stats_anom():
        if baseline_modo_a == "Visible":
            base = fdf.copy()
            label = "visible"
        else:
            base = dfv_hist[dfv_hist["description"].isin(sel_desc)].copy()
            label = "historico completo"
            if baseline_modo_a == "Rango manual" and isinstance(baseline_fechas_a, tuple) and len(baseline_fechas_a) == 2:
                d0a, d1a = baseline_fechas_a
                base = base[(base["fecha"].dt.date >= d0a) & (base["fecha"].dt.date <= d1a)]
                label = f"rango manual {d0a.isoformat()} a {d1a.isoformat()}"
        out = {}
        if base.empty:
            return out, label, 0
        for (param, desc), g in base.groupby(["param_label", "description"]):
            vals = g["value"].astype(float).dropna()
            if len(vals) >= 2:
                sd = vals.std(ddof=1)
                if sd and sd > 0:
                    out[(param, desc)] = {
                        "mu": vals.mean(),
                        "sd": sd,
                        "n": len(vals),
                        "label": label,
                    }
        return out, label, len(base[["point_id", "param_label"]].drop_duplicates())

    baseline_stats_a, baseline_label_a, baseline_n_a = construir_baseline_stats_anom()
    st.caption(f"Baseline activo para anomalias: {baseline_label_a} - {baseline_n_a} mediciones base.")

    # Recoger umbrales fijos guardados (todos los de esta variante)
    thr_dict = {}
    for r in cfg.list_thresholds():
        v, pl, dscr, low, high = r
        if v == sel_var:
            thr_dict[(pl, dscr)] = (low, high)

    # Ejecutar deteccion sobre fdf (ya filtrado por variante, fechas, description)
    anom_df = ae.detectar_anomalias(
        fdf, sel_var, thresholds_por_clave=thr_dict,
        n_sigma=n_sigma_a, cusum_k=cusum_k_a, cusum_h=cusum_h_a, racha_umbral=4,
        baseline_stats=baseline_stats_a,
    )

    if anom_df.empty:
        st.success("a Sin anomalias detectadas con los filtros y parametros actuales.")
    else:
        # Cargar estados guardados y enriquecer con fecha + stable key del punto.
        estados = cfg.list_anom_statuses()
        meta_anom = (
            fdf[["param_label", "description", "consecutivo", "fecha_iso", "stable_point_key"]]
            .drop_duplicates(["param_label", "description", "consecutivo"])
            .rename(columns={
                "param_label": "parametro",
                "consecutivo": "reporte",
                "fecha_iso": "fecha",
            })
        )
        anom_df = anom_df.merge(
            meta_anom,
            on=["parametro", "description", "reporte"],
            how="left",
        )

        firmas = []
        firmas_legacy = []
        estados_resueltos = []
        notas_resueltas = []
        migradas = 0
        for _, r in anom_df.iterrows():
            stable_key = r.get("stable_point_key")
            if pd.isna(stable_key):
                stable_key = None
            firma = cfg.anom_signature(
                sel_var, r["parametro"], r["reporte"], r["tipo"], r["description"],
                stable_point_key=stable_key,
            )
            firma_legacy = cfg.anom_signature(
                sel_var, r["parametro"], r["reporte"], r["tipo"], r["description"],
            )
            estado_new = estados.get(firma)
            estado_old = estados.get(firma_legacy)
            if estado_new is None and estado_old is not None and stable_key:
                cfg.set_anom_status(firma, estado_old.get("status", "Pendiente"), estado_old.get("note", ""))
                estado_new = estado_old
                estados[firma] = estado_old
                migradas += 1
            estado_final = estado_new or estado_old or {"status": "Pendiente", "note": ""}
            firmas.append(firma)
            firmas_legacy.append(firma_legacy)
            estados_resueltos.append(estado_final.get("status", "Pendiente"))
            notas_resueltas.append(estado_final.get("note", ""))

        anom_df["firma"] = firmas
        anom_df["firma_legacy"] = firmas_legacy
        anom_df["estado"] = estados_resueltos
        anom_df["nota"] = notas_resueltas
        if migradas:
            st.caption(f"Migrados {migradas} estado(s) de anomalia a stable_point_key.")

        # Metricas resumen
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total", len(anom_df))
        m2.metric("Alta", (anom_df["severidad"] == "Alta").sum())
        m3.metric("Pendientes",
                  (anom_df["estado"] == "Pendiente").sum())
        m4.metric("Revisadas",
                  (anom_df["estado"] == "Revisada").sum())

        # Filtros locales de la pestana
        st.markdown("**Filtros de la lista**")
        fa1, fa2, fa3 = st.columns(3)
        with fa1:
            f_sev = st.multiselect("Severidad", ["Alta", "Media", "Baja"],
                                   default=["Alta", "Media", "Baja"], key="anom_fsev")
        with fa2:
            f_est = st.multiselect("Estado", ["Pendiente", "Revisada", "Descartada"],
                                   default=["Pendiente"], key="anom_fest")
        with fa3:
            tipos_disp = sorted(anom_df["tipo"].unique())
            f_tipo = st.multiselect("Tipo", tipos_disp, default=tipos_disp, key="anom_ftipo")

        vista = anom_df[anom_df["severidad"].isin(f_sev)
                        & anom_df["estado"].isin(f_est)
                        & anom_df["tipo"].isin(f_tipo)].copy()

        # Orden: severidad (Alta > Media > Baja), luego por reporte desc
        sev_ord = {"Alta": 0, "Media": 1, "Baja": 2}
        vista["_so"] = vista["severidad"].map(sev_ord)
        vista = vista.sort_values(["_so", "reporte"], ascending=[True, False]).drop(columns=["_so"])

        st.markdown(f"**{len(vista)} anomalias** (de {len(anom_df)} totales)")

        # Tabla editable: el usuario puede cambiar estado y nota
        col_show = ["severidad", "tipo", "fecha", "parametro", "reporte", "description",
                    "valor", "esperado", "desviacion", "baseline", "detalle", "estado", "nota"]
        edit_df = st.data_editor(
            vista[col_show + ["firma"]].set_index("firma"),
            column_config={
                "estado": st.column_config.SelectboxColumn(
                    "Estado", options=["Pendiente", "Revisada", "Descartada"],
                    required=True,
                ),
                "nota": st.column_config.TextColumn("Nota", help="Comentario libre"),
                "fecha": st.column_config.TextColumn(
                    "Fecha", help="Formato AAAA-MM-DD para ordenar cronologicamente"),
                "valor": st.column_config.NumberColumn("Valor", format="%.2f"),
                "esperado": st.column_config.NumberColumn("Esperado", format="%.2f"),
            },
            disabled=["severidad", "tipo", "fecha", "parametro", "reporte", "description",
                      "valor", "esperado", "desviacion", "baseline", "detalle"],
            use_container_width=True, height=420, key="anom_editor",
        )

        if st.button("Guardar cambios de estado", key="anom_save"):
            cambios = 0
            for firma_idx, fila in edit_df.iterrows():
                prev = estados.get(firma_idx, {"status": "Pendiente", "note": ""})
                if (fila["estado"] != prev["status"]) or (fila["nota"] != prev["note"]):
                    cfg.set_anom_status(firma_idx, fila["estado"], fila["nota"])
                    cambios += 1
            if cambios:
                st.success(f"Guardados {cambios} cambio(s) de estado.")
                st.rerun()
            else:
                st.info("Sin cambios para guardar.")


# ===== MODIFICADORES (vigilancia de cambios en factores de celda) =====
if active_tab == "Modificadores":
    st.subheader(f"Modificadores de celda - {sel_lbl}")
    st.caption("Los modificadores deben mantenerse en un nivel constante a lo "
               "largo del historico, POR RATING. Si dentro de un mismo rating "
               "aparecen varios niveles, alguien recalibro la celda entre esos "
               "reportes. Esta pagina ignora los filtros de fecha y Description "
               "del sidebar: muestra el historico completo por rating.")

    MODS_POR_VARIANTE = {
        "1A": ["FMFN", "FMEGT", "FMN2", "FMW2", "FMWF"],
        "1B": ["CFFN", "CFN2", "CFEGT", "CFw2A", "CFWFM"],
    }
    mods_var = MODS_POR_VARIANTE.get(sel_var, [])

    if not mods_var:
        st.info(f"No hay modificadores definidos para la variante {sel_lbl}.")
    else:
        mod_data = dfv_hist[dfv_hist["param_label"].apply(
            lambda x: any(str(x).split(" ")[0].split("[")[0].strip() == m
                          for m in mods_var)
        )].copy()

        if mod_data.empty:
            st.warning(
                f"No se encontraron modificadores en la base de datos para {sel_lbl}. "
                f"Esperados: {', '.join(mods_var)}. "
                "Verifica que el ETL los este cargando (mapping.yaml)."
            )
        else:
            import numpy as np
            import plotly.graph_objects as go

            tol_pct = st.slider(
                "Tolerancia para considerar 'mismo nivel' (% del valor)",
                0.1, 5.0, 1.0, step=0.1,
                help="Cambios menores a esta tolerancia se consideran ruido "
                     "normal. Solo cambios mayores cuentan como recalibracion.",
                key="mod_tol",
            )

            def detectar_niveles(valores, tolerancia_pct):
                """Agrupa valores casi iguales. Devuelve lista de
                (idx_inicio, idx_fin, valor_representativo)."""
                if len(valores) == 0:
                    return []
                niveles = []
                ini = 0
                grupo = [valores[0]]
                for i in range(1, len(valores)):
                    media = float(np.mean(grupo))
                    if media == 0:
                        mismo = abs(valores[i]) < 1e-9
                    else:
                        mismo = (abs(valores[i] - media) / abs(media) * 100
                                 < tolerancia_pct)
                    if mismo:
                        grupo.append(valores[i])
                    else:
                        niveles.append((ini, i - 1, float(np.mean(grupo))))
                        ini = i
                        grupo = [valores[i]]
                niveles.append((ini, len(valores) - 1, float(np.mean(grupo))))
                return niveles

            # ---- Recorre por (rating, modificador) y acumula resultados ----
            ratings = sorted(mod_data["description"].dropna().unique())
            mods_presentes_global = sorted(mod_data["param_label"].unique())

            # estructura: resultados_por_rating[rating] = {
            #   "mods": {param_label: {niveles, consec, fechas, vals}},
            #   "n_estables": int, "n_con_cambios": int,
            # }
            resultados_por_rating = {}
            transiciones_totales = []  # tabla unica al final
            total_mods_vigilados = 0
            total_estables = 0
            total_con_cambios = 0

            for rating in ratings:
                sub_rating = mod_data[mod_data["description"] == rating]
                mods_presentes = sorted(sub_rating["param_label"].unique())
                info_mods = {}
                n_estables = 0
                n_con_cambios = 0

                for m in mods_presentes:
                    s = (sub_rating[sub_rating["param_label"] == m]
                         .sort_values("consecutivo")
                         .drop_duplicates("consecutivo")
                         .reset_index(drop=True))
                    if s.empty:
                        continue
                    vals = s["value"].astype(float).tolist()
                    consec = s["consecutivo"].astype(int).tolist()
                    fechas = s["test_date"].astype(str).tolist()
                    source_files = s["source_file"].fillna("").astype(str).tolist()
                    niveles = detectar_niveles(vals, tol_pct)
                    info_mods[m] = {
                        "niveles": niveles, "consec": consec,
                        "fechas": fechas, "source_files": source_files, "vals": vals,
                    }
                    if len(niveles) > 1:
                        n_con_cambios += 1
                        for k in range(1, len(niveles)):
                            idx_t = niveles[k][0]
                            transiciones_totales.append({
                                "Rating": rating,
                                "Modificador": m,
                                "Reporte": consec[idx_t],
                                "Fecha": fechas[idx_t],
                                "Nivel anterior": niveles[k - 1][2],
                                "Nivel nuevo": niveles[k][2],
                                "Delta %": ((niveles[k][2] - niveles[k - 1][2])
                                            / niveles[k - 1][2] * 100
                                            if niveles[k - 1][2] != 0
                                            else float("inf")),
                            })
                    else:
                        n_estables += 1

                resultados_por_rating[rating] = {
                    "mods": info_mods,
                    "n_estables": n_estables,
                    "n_con_cambios": n_con_cambios,
                }
                total_mods_vigilados += len(info_mods)
                total_estables += n_estables
                total_con_cambios += n_con_cambios

            # ---- Resumen global arriba ----
            gm1, gm2, gm3, gm4 = st.columns(4)
            gm1.metric("Ratings analizados", len(ratings))
            gm2.metric("Modificadores vigilados (total)", total_mods_vigilados)
            gm3.metric("Estables (1 nivel)", total_estables)
            gm4.metric("Con cambios", total_con_cambios)

            if total_con_cambios > 0:
                st.error(f"as  {total_con_cambios} caso(s) de modificador-en-rating "
                         "muestran mas de un nivel. Hubo recalibracion(es) en "
                         "el historico. Detalle por rating abajo, transiciones "
                         "consolidadas al final.")
            else:
                st.success("a Todos los modificadores estan en un solo nivel "
                           "dentro de cada rating: no hubo recalibracion en el "
                           "historico.")

            # ---- Bloque por rating ----
            for rating in ratings:
                info = resultados_por_rating[rating]
                mods_aqui = list(info["mods"].keys())
                if not mods_aqui:
                    continue

                st.markdown("---")
                st.markdown(f"### {rating}")
                rm1, rm2, rm3 = st.columns(3)
                rm1.metric("Modificadores en este rating", len(mods_aqui))
                rm2.metric("Estables", info["n_estables"])
                rm3.metric("Con cambios", info["n_con_cambios"])

                n_cols = 2
                for i in range(0, len(mods_aqui), n_cols):
                    fila = st.columns(n_cols)
                    bloque = mods_aqui[i:i + n_cols]
                    for j in range(n_cols):
                        if j >= len(bloque):
                            continue
                        m = bloque[j]
                        with fila[j]:
                            try:
                                d = info["mods"][m]
                                niveles = d["niveles"]
                                consec = d["consec"]
                                fechas = d["fechas"]
                                source_files = d["source_files"]
                                vals = d["vals"]
                                n_niv = len(niveles)
                                color = "#2ca02c" if n_niv == 1 else "crimson"
                                figm = go.Figure()
                                figm.add_trace(go.Scatter(
                                    x=[str(c) for c in consec], y=vals,
                                    mode="lines",
                                    line=dict(color=color, width=1.5),
                                    customdata=list(zip(fechas, source_files)),
                                    hovertemplate=("reporte %{x}<br>"
                                                   "valor %{y:.6f}"
                                                   "<br>fecha %{customdata[0]}"
                                                   "<br>archivo %{customdata[1]}"
                                                   "<extra></extra>"),
                                    showlegend=False,
                                ))
                                for k in range(1, n_niv):
                                    idx_t = niveles[k][0]
                                    figm.add_vline(
                                        x=idx_t, line_color="red",
                                        line_dash="dot", line_width=2,
                                    )
                                etiqueta = ("a 1 nivel" if n_niv == 1
                                            else f"as  {n_niv} niveles")
                                figm.update_layout(
                                    title=f"{m} a {etiqueta}",
                                    height=260,
                                    margin=dict(t=40, b=30, l=50, r=10),
                                    xaxis_title="reporte",
                                    xaxis=dict(showticklabels=False),
                                )
                                # key incluye rating para evitar colisiones
                                safe_rating = "".join(
                                    c if c.isalnum() else "_" for c in rating
                                )[:40]
                                st.plotly_chart(
                                    figm, use_container_width=True,
                                    key=f"mod_chart_{sel_var}_{safe_rating}_{m}",
                                )
                            except Exception as _ex:
                                st.error(f"Error dibujando {m} en {rating}: "
                                         f"{type(_ex).__name__}: {_ex}")

            # ---- Tabla unica de transiciones al final ----
            if transiciones_totales:
                st.markdown("---")
                st.markdown(f"**Transiciones detectadas a consolidado "
                            f"({len(transiciones_totales)})**")
                st.caption("Si una misma Fecha aparece en varios ratings, es "
                           "una recalibracion real de celda (afecta a todos los "
                           "ratings simultaneamente). Si solo aparece en uno, "
                           "vale la pena revisar ese dato.")
                tabla = pd.DataFrame(transiciones_totales)
                tabla = tabla.sort_values(["Fecha", "Rating", "Modificador"]) \
                             .reset_index(drop=True)
                st.dataframe(
                    tabla.style.format({
                        "Nivel anterior": "{:.6f}",
                        "Nivel nuevo": "{:.6f}",
                        "Delta %": "{:+.3f}%",
                    }),
                    use_container_width=True,
                    height=min(420, 80 + 35 * len(tabla)),
                )


# ===== EVENTOS (gestion: crear / editar / borrar) =====
if active_tab == "Eventos":
    st.subheader("Eventos")
    st.caption("Marcas temporales (actualizaciones de software, recalibraciones, "
               "cambios de sensor...) que se dibujan en la grafica de tendencia "
               "segun su fecha. Se guardan en config.db.")

    import datetime as _dt

    # --- Crear nuevo evento ---
    with st.expander("Crear nuevo evento", expanded=True):
        ce1, ce2 = st.columns(2)
        with ce1:
            ev_fecha = st.date_input("Fecha del evento", value=_dt.date.today(),
                                     key="ev_new_fecha")
            scope_options = ["ALL"] + variantes
            scope_lbl = {"ALL": "Todas las variantes"}
            scope_lbl.update({v: f"Solo {etiqueta[v]}" for v in variantes})
            ev_scope = st.selectbox(
                "Alcance", scope_options,
                format_func=lambda s: scope_lbl.get(s, s),
                key="ev_new_scope",
            )
        with ce2:
            ev_nombre = st.text_input("Nombre", key="ev_new_nombre",
                                      placeholder="Ej: Actualizacion de software")
            ev_desc = st.text_area("Descripcion", key="ev_new_desc", height=80,
                                   placeholder="Detalle del evento")
        if st.button("Agregar evento"):
            if ev_nombre.strip():
                cfg.add_event(ev_fecha.isoformat(), ev_nombre.strip(),
                              ev_desc.strip(), ev_scope)
                st.success(f"Evento '{ev_nombre}' agregado.")
                st.rerun()
            else:
                st.warning("El nombre es obligatorio.")

    # --- Lista de eventos existentes con editar/borrar ---
    st.markdown("**Eventos registrados**")
    eventos = cfg.list_events()  # todos
    if not eventos:
        st.caption("Aun no hay eventos. Crea uno arriba.")
    else:
        scope_lbl = {"ALL": "Todas"}
        scope_lbl.update({v: etiqueta[v] for v in variantes})
        scope_options = ["ALL"] + variantes
        for ev in eventos:
            if ev["scope"] not in scope_options:
                scope_options_ev = scope_options + [ev["scope"]]
                scope_lbl[ev["scope"]] = ev["scope"]
            else:
                scope_options_ev = scope_options
            with st.expander(f"{ev['event_date']} - {ev['name']} "
                             f"[{scope_lbl.get(ev['scope'], ev['scope'])}]"):
                ed1, ed2 = st.columns(2)
                with ed1:
                    nf = st.date_input("Fecha", value=_dt.date.fromisoformat(ev["event_date"]),
                                       key=f"ed_fecha_{ev['id']}")
                    ns = st.selectbox("Alcance", scope_options_ev,
                                      index=scope_options_ev.index(ev["scope"]),
                                      format_func=lambda s: scope_lbl.get(s, s),
                                      key=f"ed_scope_{ev['id']}")
                with ed2:
                    nn = st.text_input("Nombre", value=ev["name"], key=f"ed_nombre_{ev['id']}")
                    nd = st.text_area("Descripcion", value=ev["description"] or "",
                                      key=f"ed_desc_{ev['id']}", height=80)
                bg1, bg2 = st.columns(2)
                with bg1:
                    if st.button("Guardar cambios", key=f"save_{ev['id']}"):
                        cfg.update_event(ev["id"], nf.isoformat(), nn.strip(),
                                         nd.strip(), ns)
                        st.success("Actualizado.")
                        st.rerun()
                with bg2:
                    if st.button("Borrar", key=f"del_{ev['id']}"):
                        cfg.delete_event(ev["id"])
                        st.success("Borrado.")
                        st.rerun()


# ===== Guardar vista favorita (se procesa al final, ya con todos los filtros) =====
if "vw_save" in st.session_state and st.session_state.get("vw_save"):
    _nombre = st.session_state.get("vw_new_name", "").strip()
    if _nombre:
        # parametro actual (si existe en session_state)
        _param = st.session_state.get("f_param")
        _payload = {
            "variant": sel_var,
            "param": _param,
            "desc": sel_desc,
        }
        # fechas actuales
        _fechas = st.session_state.get("f_fechas")
        if isinstance(_fechas, tuple) and len(_fechas) == 2:
            _payload["d0"] = _fechas[0].isoformat()
            _payload["d1"] = _fechas[1].isoformat()
        cfg.save_view(_nombre, _payload)
        st.sidebar.success(f"Vista '{_nombre}' guardada.")


