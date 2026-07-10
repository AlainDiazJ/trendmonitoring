#!/usr/bin/env python3
"""services/data_loader.py — carga de motores.db para el dashboard.

Extraido de app.py sin cambios de logica. Migra/backfillea el schema antes
del SELECT (db_migrations) y normaliza fechas, descriptions y consecutivos.
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from db_migrations import ensure_schema_and_backfill
from services.unit_corrections import apply_unit_corrections

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

    # Correccion de flujo de combustible: en ciertos reportes el numero
    # viene en magnitud kg/h aunque la unidad ya diga "pph" (etiqueta
    # correcta, dato mal capturado). Se corrige por variante+parametro+fecha,
    # no por el texto de unidad. Debe correr antes de construir param_label
    # (que ya incluira la etiqueta correcta, sin cambios).
    apply_unit_corrections(df)

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
