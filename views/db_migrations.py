#!/usr/bin/env python3
"""
db_migrations.py — Migracion ligera de schema + backfill para motores.db.

Permite que app.py abra bases viejas (generadas antes de que existieran
stable_point_key y las columnas de fecha ISO) sin tronar en el SELECT:

1. MIGRACION: agrega a test_points las columnas nuevas que falten
   (mismas columnas que etl.ensure_schema_migrations, aqui via sqlite3
   directo porque app.py no usa SQLAlchemy).
2. BACKFILL: rellena esas columnas para los puntos que ya existian:
   - stable_point_key <- row_hash (la llave de idempotencia siempre existio)
   - test_date_iso / test_datetime_iso / date_parse_status / date_parse_rule
     se calculan con etl.parse_excel_date_time, la MISMA logica que usa el
     ETL para puntos nuevos (DD/MM/YYYY preferido, ambiguos marcados).

El backfill es idempotente: solo procesa filas con date_parse_status NULL
(el ETL siempre escribe un status, aunque sea 'error' o 'missing'), asi que
en una base ya migrada esta funcion no toca nada.
"""

import sqlite3

from etl import DATE_COLUMNS, parse_excel_date_time


def ensure_schema_and_backfill(db_path):
    """Migra el schema de test_points y rellena datos viejos.

    Devuelve un dict resumen:
      {"added_columns": [...], "keys_backfilled": n, "dates_backfilled": n}
    Si la base no tiene tabla test_points (base nueva sin ETL corrido),
    no hace nada y devuelve el resumen vacio.
    """
    resumen = {"added_columns": [], "keys_backfilled": 0, "dates_backfilled": 0}
    con = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(test_points)")}
        if not cols:
            return resumen

        # --- 1. Migracion: columnas nuevas que falten ---
        for col, sql_type in DATE_COLUMNS.items():
            if col not in cols:
                con.execute(f"ALTER TABLE test_points ADD COLUMN {col} {sql_type}")
                resumen["added_columns"].append(col)
                cols.add(col)

        # --- 2a. Backfill de stable_point_key desde row_hash ---
        if "row_hash" in cols:
            cur = con.execute(
                "UPDATE test_points SET stable_point_key = row_hash "
                "WHERE stable_point_key IS NULL AND row_hash IS NOT NULL"
            )
            resumen["keys_backfilled"] = cur.rowcount

        # --- 2b. Backfill de fechas ISO ---
        # date_parse_status NULL marca las filas que el ETL nuevo nunca toco.
        filas = con.execute(
            "SELECT id, test_date, test_time FROM test_points "
            "WHERE date_parse_status IS NULL"
        ).fetchall()
        for pid, test_date, test_time in filas:
            info = parse_excel_date_time(test_date, test_time)
            con.execute(
                "UPDATE test_points SET "
                "  test_date_raw = COALESCE(test_date_raw, ?), "
                "  test_date_iso = ?, "
                "  test_datetime_iso = ?, "
                "  date_parse_status = ?, "
                "  date_parse_rule = ? "
                "WHERE id = ?",
                (
                    info["test_date_raw"],
                    info["test_date_iso"],
                    info["test_datetime_iso"],
                    info["date_parse_status"],
                    info["date_parse_rule"],
                    pid,
                ),
            )
        resumen["dates_backfilled"] = len(filas)

        con.commit()
        return resumen
    finally:
        con.close()


if __name__ == "__main__":
    import sys

    ruta = sys.argv[1] if len(sys.argv) > 1 else "data/motores.db"
    print(f"Migrando {ruta} ...")
    r = ensure_schema_and_backfill(ruta)
    print(f"Columnas agregadas: {r['added_columns'] or 'ninguna'}")
    print(f"stable_point_key rellenadas: {r['keys_backfilled']}")
    print(f"Fechas backfilleadas: {r['dates_backfilled']}")
