#!/usr/bin/env python3
"""services/unit_corrections.py — correccion de unidades en la lectura.

Algunos reportes de flujo de combustible se capturaron en kg/h cuando el
historico de la flota esta en lb/h (pph). Mezclar ambas unidades en una
misma serie contamina medias, sigmas, bandas y anomalias. La correccion se
hace EN LA LECTURA (no se reingesta ni se edita motores.db): se multiplica
el valor por KG_H_A_LB_H y se reetiqueta a la unidad imperial que ya usa ese
parametro, para que la serie quede unificada.

Sigue el mismo patron table-driven que la conversion Kelvin->Celsius de
views/correlacion_ref.py (PARES_CON_CONVERSION_K_A_C): una tabla de reglas
+ una funcion vectorizada que aplica la correccion solo donde coincide.
"""

import pandas as pd

KG_H_A_LB_H = 2.20462262

# Unidades que se interpretan como "kg/h" en motores.db. El ETL normaliza
# 'kg/h' -> 'kg_h' (mapping.yaml: unit_normalization), pero se acepta
# tambien el string crudo con variantes de separador por robustez.
_UNIDADES_KGH = {"kg/h", "kg_h", "kgh", "kg/hr"}

# Unidad imperial de reemplazo por defecto si el parametro no tiene ninguna
# fila ya en imperial de la que tomar la etiqueta exacta (ver _etiqueta_imperial).
_UNIDAD_IMPERIAL_DEFAULT = "pph"

# (variante, {raw_names}, operador de fecha, fecha de corte ISO)
# operador "<"  -> se corrigen reportes ANTES de la fecha de corte
# operador ">"  -> se corrigen reportes DESPUES de la fecha de corte
# Ambos son estrictos: el dia exacto de corte NO se corrige en ninguna regla.
CORRECCIONES_KGH_A_LBH = [
    ("1A",       {"WF36", "WFK"},      "<", "2026-03-01"),
    ("1B",       {"WFMR2", "WF36pph"}, "<", "2026-03-01"),
    ("CFM56-7B", {"WFK"},              ">", "2026-03-01"),
]


def _etiqueta_imperial(df, variant, raw_name, mask_kgh):
    """Unidad a usar tras convertir: la que ya usan las filas NO-kg/h de este
    mismo (variant, raw_name), para que la serie convertida se una a la
    serie historica correcta (mismo param_label). Si no hay ninguna fila de
    referencia, cae al default."""
    ref = df[
        (df["variant"] == variant)
        & (df["raw_name"] == raw_name)
        & ~mask_kgh
        & df["unit"].notna()
    ]["unit"]
    if not ref.empty:
        moda = ref.mode()
        if not moda.empty:
            return moda.iloc[0]
    return _UNIDAD_IMPERIAL_DEFAULT


def apply_unit_corrections(df):
    """Aplica CORRECCIONES_KGH_A_LBH sobre el DataFrame ya cargado.

    Requiere que df ya tenga las columnas 'variant', 'raw_name', 'value',
    'unit' y 'fecha' (datetime64). Modifica 'value' y 'unit' in-place para
    las filas que caen en alguna regla; el resto queda intacto.

    Idempotente: una vez convertida, la fila deja de tener unit en
    _UNIDADES_KGH, asi que una segunda pasada no la vuelve a tocar.
    Fechas no parseables (NaT) nunca cumplen '<' ni '>', asi que esas filas
    tampoco se convierten (ya se avisan aparte por date_parse_status).
    """
    unit_lower = df["unit"].astype(str).str.strip().str.lower()

    for variant, raw_names, operador, fecha_corte in CORRECCIONES_KGH_A_LBH:
        corte = pd.Timestamp(fecha_corte)
        if operador == "<":
            cumple_fecha = df["fecha"] < corte
        elif operador == ">":
            cumple_fecha = df["fecha"] > corte
        else:
            raise ValueError(f"operador de fecha no soportado: {operador!r}")

        mask_kgh = (
            (df["variant"] == variant)
            & df["raw_name"].isin(raw_names)
            & unit_lower.isin(_UNIDADES_KGH)
            & cumple_fecha
        )
        if not mask_kgh.any():
            continue

        for raw_name in raw_names:
            mask_param = mask_kgh & (df["raw_name"] == raw_name)
            if not mask_param.any():
                continue
            etiqueta = _etiqueta_imperial(df, variant, raw_name, mask_kgh)
            df.loc[mask_param, "value"] = df.loc[mask_param, "value"] * KG_H_A_LB_H
            df.loc[mask_param, "unit"] = etiqueta

    return df
