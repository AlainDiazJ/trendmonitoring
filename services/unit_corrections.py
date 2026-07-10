#!/usr/bin/env python3
"""services/unit_corrections.py — correccion de unidades en la lectura.

Algunos reportes de flujo de combustible se capturaron mal desde el
instrumento/Excel de origen: el NUMERO viene en magnitud kg/h aunque la
columna de unidad ya diga "pph" (la etiqueta es correcta, el dato es
sistematicamente el equivocado en ciertos reportes). Por eso la deteccion
NO puede basarse en el string de unidad guardado -- ya dice "pph" en las
filas malas -- sino en (variante, parametro, fecha del reporte): dentro de
la ventana de fechas indicada, TODOS los puntos de ese parametro estan mal
capturados (confirmado con el usuario, no es una mezcla de buenos y malos
en la misma ventana).

La correccion se hace EN LA LECTURA (no se reingesta ni se edita
motores.db): se multiplica el valor por KG_H_A_LB_H. La unidad NO se toca:
ya es la correcta ("pph"), solo el numero estaba mal.

Sigue el mismo patron table-driven que la conversion Kelvin->Celsius de
views/correlacion_ref.py (PARES_CON_CONVERSION_K_A_C): una tabla de reglas
+ una funcion vectorizada que aplica la correccion solo donde coincide.
"""

import pandas as pd
import streamlit as st

KG_H_A_LB_H = 2.20462262

# (variante, {raw_names}, operador de fecha, fecha de corte ISO)
# operador "<"  -> se corrigen reportes ANTES de la fecha de corte
# operador ">"  -> se corrigen reportes DESPUES de la fecha de corte
# Ambos son estrictos: el dia exacto de corte NO se corrige en ninguna regla.
# No se filtra por 'unit': la etiqueta guardada ya es la imperial correcta
# ("pph"); el defecto es solo la magnitud del valor en esos reportes.
CORRECCIONES_KGH_A_LBH = [
    ("1A",       {"WF36", "WFK"},      "<", "2026-03-01"),
    ("1B",       {"WFMR2", "WF36pph"}, "<", "2026-03-01"),
    ("CFM56-7B", {"WFK"},              ">", "2026-03-01"),
]


def parametro_tiene_correccion(variant, param_label):
    """True si el parametro seleccionado cae en una regla de correccion."""
    if not variant or not param_label:
        return False
    raw_name = str(param_label).split(" [", 1)[0].strip()
    for rule_variant, raw_names, _operador, _fecha_corte in CORRECCIONES_KGH_A_LBH:
        if variant == rule_variant and raw_name in raw_names:
            return True
    return False


def checkbox_correccion(key, ayuda=None):
    """Checkbox 'Aplicar correccion kg/h -> lb/h', desactivado por defecto.

    Cada vista decide primero con parametro_tiene_correccion() si el
    parametro que tiene seleccionado en ESE momento la necesita, y solo
    entonces llama a este checkbox con una key propia (no compartida entre
    pestanas): asi el estado nunca queda atado al parametro de otra vista.
    """
    aplicar = st.checkbox(
        "Aplicar correccion kg/h -> lb/h", value=False,
        help=ayuda or "Corrige el flujo de combustible en los reportes donde "
                       "el dato se capturo mal (ver services/unit_corrections.py).",
        key=key,
    )
    if not aplicar:
        st.caption("Correccion de flujo apagada: se muestran valores crudos.")
    return aplicar


def apply_unit_corrections(df):
    """Aplica CORRECCIONES_KGH_A_LBH sobre el DataFrame ya cargado.

    Requiere que df ya tenga las columnas 'variant', 'raw_name', 'value' y
    'fecha' (datetime64). Multiplica 'value' in-place por KG_H_A_LB_H en las
    filas que caen en alguna regla (variante + parametro + ventana de
    fecha); no toca 'unit' (la etiqueta ya es la correcta).

    Fechas no parseables (NaT) nunca cumplen '<' ni '>', asi que esas filas
    no se corrigen (ya se avisan aparte por date_parse_status).

    Esta funcion se llama una sola vez por carga, sobre los valores crudos
    que vienen de motores.db (services/data_loader.load_data), que nunca se
    modifica: no hay riesgo de aplicar la correccion dos veces sobre un
    valor ya corregido en el flujo normal de la app.
    """
    for variant, raw_names, operador, fecha_corte in CORRECCIONES_KGH_A_LBH:
        corte = pd.Timestamp(fecha_corte)
        if operador == "<":
            cumple_fecha = df["fecha"] < corte
        elif operador == ">":
            cumple_fecha = df["fecha"] > corte
        else:
            raise ValueError(f"operador de fecha no soportado: {operador!r}")

        mask = (
            (df["variant"] == variant)
            & df["raw_name"].isin(raw_names)
            & cumple_fecha
        )
        if mask.any():
            df.loc[mask, "value"] = df.loc[mask, "value"] * KG_H_A_LB_H

    return df
