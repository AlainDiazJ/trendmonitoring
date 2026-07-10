#!/usr/bin/env python3
"""
correlacion_ref.py - Correlacion (celda de pruebas) vs Historico del motor.

Compara los puntos historicos reales de la variante activa contra la curva
de correlacion de referencia de la celda de pruebas, con bandas de control
+-N sigma calculadas a partir de la dispersion de los propios puntos de
correlacion respecto a una curva ajustada.

Se integra a app.py como una pestana mas: se llama a render(fdf, sel_var,
sel_lbl) desde el bloque 'if active_tab == "Correlacion Ref.":'.

EXCEL DE CORRELACION
---------------------
Un solo archivo, ej. 'Datos Correlacion.xlsx', con UNA HOJA POR VARIANTE:
  - hoja "LEAP-1A"
  - hoja "LEAP-1B"

Dentro de cada hoja, la misma estructura de 6 bloques de columnas:
  Fila 1: "Eje X" / "Eje Y" (se ignora, es solo etiqueta)
  Fila 2: nombre corto de la variable (N1R, N2R, FNR, WFR, W2R, EGTR)
  Filas 3 a 49: datos numericos

  Bloques (0-indexed): A,B | D,E | G,H | J,K | M,N | P,Q
    A,B -> N1R vs N2R      D,E -> N1R vs FNR      G,H -> N1R vs WFR
    J,K -> N1R vs W2R      M,N -> N1R vs EGTR     P,Q -> W2R vs FNR
  (C, F, I, L, O son columnas separadoras en blanco)

Por defecto el archivo se busca en CORR_XLSX_PATH (junto a app.py). Si no
esta ahi, se ofrece un file_uploader para cargarlo manualmente en la sesion.

PUNTOS OCULTOS
--------------
Un punto puede estar mal calculado (error de captura, celda descalibrada,
etc.) sin que se quiera borrar el Excel completo de motores.db. Para eso,
config_store.hidden_points guarda que punto se debe excluir, con tres
alcances posibles elegibles desde la UI:
  - solo un par (scope='correlacion_ref::<par>'): el punto puede ser valido
    en cinco correlaciones y problematico solo en una;
  - toda esta vista (scope='correlacion_ref');
  - global (scope=config_store.GLOBAL_HIDDEN_SCOPE): lo filtra app.py al
    cargar, asi que desaparece de todas las pestanas.
El ocultamiento es reversible y sobrevive a volver a correr etl.py /
resync_measurements.py, porque se guarda con stable_point_key (que no
cambia al regenerar la base).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config_store import (
    GLOBAL_HIDDEN_SCOPE,
    hide_point,
    unhide_point,
    unhide_all_points,
    list_hidden_points_detail,
)
from services.unit_corrections import (
    apply_unit_corrections,
    checkbox_correccion,
    parametro_tiene_correccion,
)

# ---------------------------------------------------------------------------
# Configuracion fija
# ---------------------------------------------------------------------------

CORR_XLSX_PATH = "Datos Correlacion.xlsx"

HOJA_POR_VARIANTE = {
    "1A": "LEAP-1A",
    "1B": "LEAP-1B",
}

BLOQUES_COLUMNAS = {
    # nombre_par: (col_x, col_y, var_x, var_y)
    # var_x/var_y quedan FIJOS por posicion de bloque (no se leen de la celda
    # de la fila 2, porque si esa celda viene vacia o con un formato distinto
    # el nombre se corrompe silenciosamente). La fila 2 solo se usa para
    # advertir si no coincide con lo esperado.
    "N1R vs N2R":  (0, 1, "N1R", "N2R"),
    "N1R vs FNR":  (3, 4, "N1R", "FNR"),
    "N1R vs WFR":  (6, 7, "N1R", "WFR"),
    "N1R vs W2R":  (9, 10, "N1R", "W2R"),
    "N1R vs EGTR": (12, 13, "N1R", "EGTR"),
    "W2R vs FNR":  (15, 16, "W2R", "FNR"),
}

FILA_DATOS_INICIO = 2   # fila 3 en Excel (0-indexed)
FILA_DATOS_FIN = 48     # fila 49 en Excel (0-indexed, inclusive)

# Variable "generica" de la correlacion -> raw_name real en measurements,
# por variante. Debe coincidir con lo que mapping.yaml extrae del Buffer.
MAPEO_VARIABLES = {
    "1A": {
        "N1R": "N1R",
        "N2R": "N2K",
        "WFR": "WFK",
        "W2R": "W2AR",
        "EGTR": "EGTK",
        "FNR": "FNK",
    },
    "1B": {
        "N1R": "N1RKH",
        "N2R": "N2R2",
        "WFR": "WFMR2",
        "W2R": "W2AR2",
        "EGTR": "EGTR2",
        "FNR": "FNR2",
    },
}

GRADOS_DISPONIBLES = [1, 2, 3]

# El Excel de correlacion trae el EGTR de LEAP-1B en Kelvin (confirmado por
# el usuario), mientras que el EGTR2 real del motor (via mapping.yaml) viene
# en grados Celsius. Sin esta conversion, la curva de referencia queda
# desfasada ~273 unidades respecto a los puntos del motor en "N1R vs EGTR".
# Solo aplica a 1B: 1A no reporta este problema.
KELVIN_A_CELSIUS = 273.15
PARES_CON_CONVERSION_K_A_C = {
    # (hoja_excel, nombre_par, eje): se le resta KELVIN_A_CELSIUS a ese eje.
    ("LEAP-1B", "N1R vs EGTR", "y"),
}

# Scope fijo con el que esta vista guarda/consulta sus puntos ocultos en
# config_store.hidden_points. No lo cambies sin migrar los datos existentes.
HIDDEN_SCOPE = "correlacion_ref"

# Etiquetas de alcance que se ofrecen al ocultar un punto.
ALCANCE_PAR = "Solo este par"
ALCANCE_VISTA = "Toda Correlacion Ref."
ALCANCE_GLOBAL = "Global (toda la app)"


def _scope_par(nombre_par: str) -> str:
    """Scope de ocultamiento especifico de un par de correlacion."""
    return f"{HIDDEN_SCOPE}::{nombre_par}"


def _filtrar_ocultos(df: pd.DataFrame, scope: str) -> pd.DataFrame:
    """Quita de df los puntos ocultos en ese scope. Prefiere stable_point_key;
    point_id solo se usa para registros viejos que no guardaron llave."""
    detalle = list_hidden_points_detail(scope=scope)
    if not detalle:
        return df
    keys = {d["stable_point_key"] for d in detalle if d["stable_point_key"]}
    ids = {d["point_id"] for d in detalle if not d["stable_point_key"]}
    mask = pd.Series(False, index=df.index)
    if keys and "stable_point_key" in df.columns:
        mask |= df["stable_point_key"].isin(keys)
    if ids:
        mask |= df["point_id"].isin(ids)
    return df[~mask]


# ---------------------------------------------------------------------------
# Carga de la correlacion
# ---------------------------------------------------------------------------

@dataclass
class ParCorrelacion:
    nombre: str
    var_x: str
    var_y: str
    datos: pd.DataFrame  # columnas: x, y


@st.cache_data(show_spinner=False)
def _leer_pares_de_hoja(xlsx_bytes_or_path, hoja: str, cache_bust=None):
    """Devuelve (pares, avisos). avisos: lista de strings si la fila 2 del
    Excel no coincide con lo esperado (solo informativo, no bloquea).

    cache_bust: valor auxiliar (ej. mtime del archivo) que NO se usa dentro
    de la funcion, solo forma parte de la clave de cache de Streamlit para
    que un archivo modificado en disco se vuelva a leer automaticamente."""
    raw = pd.read_excel(xlsx_bytes_or_path, sheet_name=hoja, header=None)

    pares: dict[str, ParCorrelacion] = {}
    avisos: list[str] = []
    for nombre_par, (col_x, col_y, var_x, var_y) in BLOQUES_COLUMNAS.items():
        # Solo para validar; si viene vacia/None no se usa para nada critico.
        celda_x = raw.iat[1, col_x] if raw.shape[0] > 1 else None
        celda_y = raw.iat[1, col_y] if raw.shape[0] > 1 else None
        leido_x = None if pd.isna(celda_x) else str(celda_x).strip()
        leido_y = None if pd.isna(celda_y) else str(celda_y).strip()
        if leido_x and leido_x != var_x:
            avisos.append(f"'{nombre_par}': columna X dice '{leido_x}' en el Excel, se uso '{var_x}'.")
        if leido_y and leido_y != var_y:
            avisos.append(f"'{nombre_par}': columna Y dice '{leido_y}' en el Excel, se uso '{var_y}'.")

        bloque = raw.iloc[FILA_DATOS_INICIO:FILA_DATOS_FIN + 1, [col_x, col_y]]
        bloque.columns = ["x", "y"]
        bloque = bloque.apply(pd.to_numeric, errors="coerce").dropna()

        for eje in ("x", "y"):
            if (hoja, nombre_par, eje) in PARES_CON_CONVERSION_K_A_C:
                bloque[eje] = bloque[eje] - KELVIN_A_CELSIUS

        bloque = bloque.sort_values("x").reset_index(drop=True)

        pares[nombre_par] = ParCorrelacion(
            nombre=nombre_par, var_x=var_x, var_y=var_y, datos=bloque
        )
    return pares, avisos


def cargar_correlacion(sel_var: str):
    """Devuelve (pares, origen_str, avisos) o (None, mensaje_error, [])."""
    hoja = HOJA_POR_VARIANTE.get(sel_var)
    if hoja is None:
        return None, f"Variante '{sel_var}' sin hoja de correlacion definida.", []

    ruta_local = Path(CORR_XLSX_PATH)
    if ruta_local.exists():
        try:
            mtime = ruta_local.stat().st_mtime  # cambia si el archivo se guarda de nuevo
            pares, avisos = _leer_pares_de_hoja(str(ruta_local), hoja, cache_bust=mtime)
            return pares, f"'{ruta_local.name}' (hoja {hoja})", avisos
        except Exception as e:
            return None, f"No se pudo leer la hoja '{hoja}' de {ruta_local.name}: {e}", []

    st.info(
        f"No se encontro '{CORR_XLSX_PATH}' junto a la app. "
        f"Subelo abajo para esta sesion (debe tener una hoja llamada '{hoja}')."
    )
    up = st.file_uploader(
        "Excel de correlacion", type=["xlsx", "xls"], key="corr_ref_upload"
    )
    if up is None:
        return None, None, []
    try:
        pares, avisos = _leer_pares_de_hoja(up.getvalue(), hoja)
        return pares, f"'{up.name}' (hoja {hoja}, sesion actual)", avisos
    except Exception as e:
        return None, f"No se pudo leer la hoja '{hoja}' del archivo subido: {e}", []


# ---------------------------------------------------------------------------
# Ajuste de curva, sigma y bandas
# ---------------------------------------------------------------------------

def ajustar_curva_y_sigma(x: np.ndarray, y: np.ndarray, grado: int):
    grado_efectivo = min(grado, max(1, len(x) - 1))
    coef = np.polyfit(x, y, grado_efectivo)
    poly = np.poly1d(coef)
    residuales = y - poly(x)
    sigma = float(np.std(residuales, ddof=1)) if len(residuales) > grado_efectivo + 1 else float(np.std(residuales))
    return poly, sigma


def construir_curva_y_bandas(x: np.ndarray, poly: np.poly1d, sigma: float, n_sigma: float, n_puntos: int = 200):
    x_min, x_max = float(np.min(x)), float(np.max(x))
    x_malla = np.linspace(x_min, x_max, n_puntos)
    y_curva = poly(x_malla)
    return x_malla, y_curva, y_curva + n_sigma * sigma, y_curva - n_sigma * sigma


def clasificar_puntos_motor(x_motor, y_motor, poly, sigma, n_sigma):
    y_esperada = poly(x_motor)
    return np.abs(y_motor - y_esperada) > (n_sigma * sigma)


# ---------------------------------------------------------------------------
# Datos del motor (desde fdf, el DataFrame ya filtrado de app.py)
# ---------------------------------------------------------------------------

def _serie_por_punto(fdf: pd.DataFrame, raw_name: str) -> pd.DataFrame | None:
    """Un valor por point_id para ese raw_name (promedia si hay mas de una
    fila, ej. distintas unidades del mismo raw_name)."""
    s = fdf[fdf["raw_name"] == raw_name]
    if s.empty:
        return None
    return (
        s.groupby(["point_id", "stable_point_key", "consecutivo", "description", "test_date", "source_file"], as_index=False, dropna=False)
         ["value"].mean()
         .rename(columns={"value": raw_name})
    )


def obtener_puntos_motor(fdf: pd.DataFrame, sel_var: str, var_x: str, var_y: str):
    """var_x, var_y: codigos de la correlacion (ej. 'N1R', 'N2R').
    Devuelve (x, y, df_merge) o (None, None, None) si falta algo."""
    mapeo = MAPEO_VARIABLES.get(sel_var, {})
    raw_x = mapeo.get(var_x)
    raw_y = mapeo.get(var_y)
    if raw_x is None or raw_y is None:
        return None, None, None

    gx = _serie_por_punto(fdf, raw_x)
    gy = _serie_por_punto(fdf, raw_y)
    if gx is None or gy is None:
        return None, None, None

    merged = gx.merge(gy[["point_id", raw_y]], on="point_id", how="inner")
    if merged.empty:
        return None, None, None
    return merged[raw_x].to_numpy(), merged[raw_y].to_numpy(), merged


# ---------------------------------------------------------------------------
# Grafica
# ---------------------------------------------------------------------------

def graficar_par(par: ParCorrelacion, motor_x, motor_y, motor_df, grado: int, n_sigma: float):
    x = par.datos["x"].to_numpy()
    y = par.datos["y"].to_numpy()

    poly, sigma = ajustar_curva_y_sigma(x, y, grado)
    x_malla, y_curva, y_sup, y_inf = construir_curva_y_bandas(x, poly, sigma, n_sigma)

    fig = go.Figure()

    # Banda de control: relleno naranja mas opaco + lineas punteadas en los
    # bordes superior e inferior, para que se distinga claramente de la curva.
    color_banda = "rgba(255,140,0,0.22)"
    color_borde_banda = "rgb(230,120,0)"
    fig.add_trace(go.Scatter(
        x=x_malla, y=y_sup, mode="lines",
        line=dict(color=color_borde_banda, width=1.5, dash="dot"),
        name=f"+{n_sigma}sigma", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=x_malla, y=y_inf, mode="lines",
        line=dict(color=color_borde_banda, width=1.5, dash="dot"),
        fill="tonexty", fillcolor=color_banda,
        name=f"Banda +/-{n_sigma}sigma", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=x_malla, y=y_curva, mode="lines",
        line=dict(color="rgb(60,90,200)", width=2.5),
        name=f"Curva correlacion (grado {grado})",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="markers",
        marker=dict(color="rgb(60,90,200)", size=6, symbol="circle-open"),
        name="Puntos de correlacion",
    ))

    n_dentro = n_fuera = 0
    point_ids_fuera = np.array([], dtype=object)
    if motor_x is not None and len(motor_x) > 0:
        fuera = clasificar_puntos_motor(motor_x, motor_y, poly, sigma, n_sigma)
        n_fuera = int(np.sum(fuera))
        n_dentro = int(len(fuera) - n_fuera)

        hover_desc = motor_df["description"].to_numpy() if motor_df is not None else None
        hover_fecha = motor_df["test_date"].to_numpy() if motor_df is not None else None
        hover_consec = motor_df["consecutivo"].to_numpy() if motor_df is not None else None
        hover_source = motor_df["source_file"].fillna("").to_numpy() if motor_df is not None else None

        def _custom(mask):
            if motor_df is None:
                return None
            return np.stack([hover_desc[mask], hover_fecha[mask], hover_consec[mask], hover_source[mask]], axis=-1)

        if n_dentro > 0:
            m = ~fuera
            fig.add_trace(go.Scatter(
                x=motor_x[m], y=motor_y[m], mode="markers",
                marker=dict(color="rgb(30,170,90)", size=8),
                name="Motor - dentro de banda",
                customdata=_custom(m),
                hovertemplate=(
                    "x=%{x:.3f}<br>y=%{y:.3f}"
                    "<br>%{customdata[0]}<br>%{customdata[1]}<br>reporte %{customdata[2]}"
                    "<br>archivo %{customdata[3]}<extra></extra>"
                ) if motor_df is not None else None,
            ))
        if n_fuera > 0:
            m = fuera
            point_ids_fuera = motor_df["point_id"].to_numpy()[m] if motor_df is not None else np.array([])
            fig.add_trace(go.Scatter(
                x=motor_x[m], y=motor_y[m], mode="markers",
                marker=dict(color="red", size=12, symbol="circle",
                           line=dict(color="black", width=1.5)),
                name="Motor - FUERA de banda",
                customdata=_custom(m),
                hovertemplate=(
                    "x=%{x:.3f}<br>y=%{y:.3f}"
                    "<br>%{customdata[0]}<br>%{customdata[1]}<br>reporte %{customdata[2]}"
                    "<br>archivo %{customdata[3]}<extra></extra>"
                ) if motor_df is not None else None,
            ))

    fig.update_layout(
        title=f"{par.nombre}  (sigma={sigma:.4g})",
        xaxis_title=par.var_x, yaxis_title=par.var_y,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=60, b=40), height=560,
    )
    return fig, n_dentro, n_fuera, point_ids_fuera


# ---------------------------------------------------------------------------
# UI de puntos ocultos
# ---------------------------------------------------------------------------

def _scopes_de_ocultamiento():
    """Todos los scopes que administra esta vista, con su etiqueta legible."""
    scopes = [
        (HIDDEN_SCOPE, "toda la vista"),
        (GLOBAL_HIDDEN_SCOPE, "GLOBAL (toda la app)"),
    ]
    scopes += [(_scope_par(nombre), f"solo {nombre}") for nombre in BLOQUES_COLUMNAS]
    return scopes


def _render_panel_ocultos(sel_var: str):
    """Expander con puntos ocultos (todos los alcances) y boton para restaurarlos."""
    items = []
    for scope, etiqueta in _scopes_de_ocultamiento():
        for d in list_hidden_points_detail(scope=scope):
            d["scope"] = scope
            d["alcance"] = etiqueta
            items.append(d)
    if not items:
        return
    # 'Restaurar todos' NO toca el alcance global: un punto oculto
    # globalmente puede haber sido decision de otra persona para OTRA
    # variante, y no debe desaparecer por limpiar la vista de esta.
    items_locales = [i for i in items if i["scope"] != GLOBAL_HIDDEN_SCOPE]
    items_globales = [i for i in items if i["scope"] == GLOBAL_HIDDEN_SCOPE]
    with st.expander(f"{len(items)} punto(s) oculto(s)", expanded=False):
        st.caption(
            "Estos puntos siguen intactos en motores.db; solo estan excluidos "
            "segun su alcance: un par especifico, toda Correlacion Ref. o "
            "toda la app (global)."
        )
        if items_locales and st.button(
            f"Restaurar todos los de esta vista ({len(items_locales)})",
            key="corr_ref_unhide_all",
            help="Restaura solo 'toda la vista' y 'un par especifico'. NO toca "
                 "los ocultos globales (afectan a toda la app, se restauran aparte).",
        ):
            unhide_all_points(scope=HIDDEN_SCOPE)
            for nombre_par in BLOQUES_COLUMNAS:
                unhide_all_points(scope=_scope_par(nombre_par))
            _limpiar_selecciones_tabla(sel_var)
            st.rerun()
        if items_globales:
            st.warning(
                f"{len(items_globales)} punto(s) oculto(s) GLOBALMENTE (afectan "
                "toda la app, no solo esta vista). Restaurarlos aqui los hace "
                "visibles de nuevo en Tendencia, Anomalias, Datos, etc."
            )
            if st.button(
                f"Restaurar tambien los {len(items_globales)} globales",
                key="corr_ref_unhide_all_global",
            ):
                unhide_all_points(scope=GLOBAL_HIDDEN_SCOPE)
                _limpiar_selecciones_tabla(sel_var)
                st.rerun()
        st.divider()
        for item in items:
            c1, c2 = st.columns([5, 1])
            with c1:
                motivo = item["reason"] or "(sin motivo especificado)"
                key_short = (item.get("stable_point_key") or "")[:10]
                st.caption(
                    f"[{item['alcance']}] point_id {item['point_id']} - key {key_short} - "
                    f"{motivo} - ocultado {item['created_at']}"
                )
            with c2:
                btn_key = item.get("stable_point_key") or item["point_id"]
                if st.button("Restaurar", key=f"corr_ref_unhide_{item['scope']}_{btn_key}"):
                    unhide_point(
                        item["point_id"], scope=item["scope"],
                        stable_point_key=item.get("stable_point_key"),
                    )
                    _limpiar_selecciones_tabla(sel_var)
                    st.rerun()

def _limpiar_selecciones_tabla(sel_var: str):
    """Borra el estado de seleccion de checkboxes de TODAS las tablas de
    'fuera de banda' de esta variante. Necesario porque ocultar/restaurar un
    punto cambia el tamano de esas tablas (en todos los pares, no solo el que
    se toco), y Streamlit conserva la seleccion (indices de fila) entre
    reruns bajo la misma key: sin esto, un indice viejo puede quedar fuera de
    rango de la tabla nueva y tronar con IndexError."""
    prefijo = f"corr_ref_tabla_fuera_{sel_var}_"
    for k in list(st.session_state.keys()):
        if k.startswith(prefijo):
            del st.session_state[k]


def _render_boton_ocultar(evento, tabla_fuera: pd.DataFrame, nombre_par: str, sel_var: str, sel_lbl: str):
    """Boton para ocultar los puntos seleccionados (checkbox) en la tabla de
    fuera de banda. 'evento' es lo que devuelve st.dataframe(..., on_select=...).

    Requiere Streamlit >= 1.35 (soporte de on_select/selection_mode en
    st.dataframe). Si tu version es anterior, actualiza streamlit."""
    filas_sel = evento.selection.rows if evento is not None and evento.selection else []
    # Blindaje: si la seleccion quedo desalineada con esta tabla (ej. por un
    # rerun anterior que no alcanzo a limpiarla), se ignoran los indices que
    # ya no existen en vez de tronar.
    filas_sel = [i for i in filas_sel if 0 <= i < len(tabla_fuera)]
    if not filas_sel:
        st.caption("Marca el checkbox de una o mas filas en la tabla de arriba para poder ocultarlas.")
        return

    seleccion = tabla_fuera.iloc[filas_sel].drop_duplicates("point_id")
    ids_sel = sorted(set(seleccion["point_id"].tolist()))

    alcance = st.radio(
        "Alcance del ocultamiento",
        [ALCANCE_PAR, ALCANCE_VISTA, ALCANCE_GLOBAL],
        horizontal=True,
        key=f"corr_ref_alcance_{sel_var}_{nombre_par}",
        help=(
            "Solo este par: el punto sigue visible en las demas correlaciones. "
            "Toda Correlacion Ref.: se excluye de los 6 pares. "
            "Global: se excluye de TODAS las pestanas de la app."
        ),
    )
    scope_sel = {
        ALCANCE_PAR: _scope_par(nombre_par),
        ALCANCE_VISTA: HIDDEN_SCOPE,
        ALCANCE_GLOBAL: GLOBAL_HIDDEN_SCOPE,
    }[alcance]

    if st.button(
        f"Ocultar {len(ids_sel)} punto(s) seleccionado(s) ({alcance.lower()})",
        key=f"corr_ref_ocultar_btn_{sel_var}_{nombre_par}",
    ):
        for _, row in seleccion.iterrows():
            hide_point(
                int(row["point_id"]), scope=scope_sel,
                stable_point_key=row.get("stable_point_key"),
                reason=f"Marcado mal calculado en {nombre_par} ({sel_lbl})",
            )
        _limpiar_selecciones_tabla(sel_var)
        st.success(f"{len(ids_sel)} punto(s) ocultado(s) ({alcance.lower()}). Recargando...")
        st.rerun()


# ---------------------------------------------------------------------------
# Render (llamado desde app.py)
# ---------------------------------------------------------------------------

def render(fdf: pd.DataFrame, sel_var: str, sel_lbl: str):
    st.subheader(f"Correlacion vs Historico - {sel_lbl}")
    st.caption(
        "Puntos reales del motor contra la curva de correlacion de referencia "
        "de la celda de pruebas, con bandas de control +/-N sigma."
    )

    pares, origen, _avisos = cargar_correlacion(sel_var)
    if pares is None:
        if origen:
            st.error(origen)
        return
    st.success(f"Correlacion cargada de {origen} - {len(pares)} pares.")

    # Puntos ocultados manualmente (no se borran de motores.db, solo se
    # excluyen). Los globales ya vienen filtrados desde app.py; aqui se aplica
    # el alcance "toda la vista". El alcance "solo este par" se aplica mas
    # abajo, par por par.
    _render_panel_ocultos(sel_var)
    fdf_vis = _filtrar_ocultos(fdf, HIDDEN_SCOPE)

    mapeo = MAPEO_VARIABLES.get(sel_var, {})
    if any(parametro_tiene_correccion(sel_var, raw) for raw in mapeo.values()):
        if checkbox_correccion(
            key="unit_corr_correlacion_ref",
            ayuda="Corrige los pares que usen un parametro con regla activa.",
        ):
            fdf_vis = fdf_vis.copy()
            apply_unit_corrections(fdf_vis)

    col_a, col_b = st.columns(2)
    with col_a:
        grado = st.select_slider(
            "Grado del polinomio de ajuste", GRADOS_DISPONIBLES, value=2,
            key="corr_ref_grado",
        )
    with col_b:
        n_sigma = st.slider(
            "N (bandas +/-N sigma)", min_value=0.5, max_value=6.0, value=3.0, step=0.5,
            key="corr_ref_nsigma",
        )

    raws_en_datos = set(fdf_vis["raw_name"].unique())
    faltantes_raw = sorted({
        f"{v} -> {mapeo.get(v)}" for par in pares.values() for v in (par.var_x, par.var_y)
        if mapeo.get(v) not in raws_en_datos
    })
    if faltantes_raw:
        st.warning(
            f"Estos raw_name no aparecen en los datos filtrados de {sel_lbl}: "
            f"{', '.join(faltantes_raw)}. Si nunca han aparecido, corre "
            "resync_measurements.py despues de actualizar mapping.yaml. Si es "
            "solo por los filtros de fecha/description de la barra lateral, ajustalos."
        )

    cols_tabla_datos = ["point_id", "stable_point_key", "consecutivo", "description", "fecha_iso",
                        "point_number", "source_file", "param_label", "value", "unit"]

    resumen_filas = []
    for nombre_par, par in pares.items():
        # ocultos especificos de ESTE par (los de vista/global ya no estan en fdf_vis)
        fdf_par = _filtrar_ocultos(fdf_vis, _scope_par(nombre_par))
        motor_x, motor_y, motor_df = obtener_puntos_motor(fdf_par, sel_var, par.var_x, par.var_y)
        fig, n_dentro, n_fuera, ids_fuera = graficar_par(par, motor_x, motor_y, motor_df, grado, n_sigma)

        st.plotly_chart(fig, use_container_width=True,
                        key=f"corr_ref_chart_{sel_var}_{nombre_par}")

        hoja_actual = HOJA_POR_VARIANTE.get(sel_var)
        if (hoja_actual, nombre_par, "y") in PARES_CON_CONVERSION_K_A_C:
            st.caption(
                "i El EGTR de este Excel de correlacion viene en Kelvin; se "
                "convirtio a C automaticamente (resta de 273.15) para poder "
                "compararlo contra el EGTR2 real del motor."
            )

        if n_fuera > 0:
            raw_x = mapeo.get(par.var_x)
            raw_y = mapeo.get(par.var_y)
            tabla_fuera = (
                fdf_par[fdf_par["point_id"].isin(ids_fuera) & fdf_par["raw_name"].isin([raw_x, raw_y])]
                [cols_tabla_datos]
                .rename(columns={"fecha_iso": "fecha"})
                .sort_values(["consecutivo", "param_label"])
                .reset_index(drop=True)
            )
            st.markdown(f" **{n_fuera} punto(s) fuera de banda - {nombre_par}**")
            evento = st.dataframe(
                tabla_fuera, use_container_width=True, hide_index=True,
                on_select="rerun", selection_mode="multi-row",
                key=f"corr_ref_tabla_fuera_{sel_var}_{nombre_par}",
            )
            _render_boton_ocultar(evento, tabla_fuera, nombre_par, sel_var, sel_lbl)
        else:
            st.caption(f" Todos los puntos del motor dentro de banda en {nombre_par}.")

        if motor_x is not None:
            resumen_filas.append({
                "Par": nombre_par,
                "Puntos motor": len(motor_x),
                "Dentro de banda": n_dentro,
                "Fuera de banda": n_fuera,
            })
        else:
            resumen_filas.append({
                "Par": nombre_par, "Puntos motor": 0,
                "Dentro de banda": "-", "Fuera de banda": "-",
            })
        st.divider()

    st.markdown("**Resumen**")
    st.dataframe(pd.DataFrame(resumen_filas), use_container_width=True, hide_index=True)
