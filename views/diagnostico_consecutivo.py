#!/usr/bin/env python3
"""
diagnostico_consecutivo.py — Reconstruye EXACTAMENTE la logica de 'consecutivo'
que usa app.py (mismo orden de sort, mismo formato de fecha) y busca casos
reales donde, al avanzar el consecutivo, la fecha retrocede. Eso es lo que
se veria como "fuera de orden" en las tablas de Datos y Correlacion Ref,
que ordenan por consecutivo.

No modifica nada, solo lee y reporta.

USO
---
    py diagnostico_consecutivo.py --db data\\motores.db
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

FORMATO_FECHA = "%d/%m/%Y"


def run(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"[!] No existe la base: {db_path.resolve()}")
        return

    con = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT id AS point_id, variant, test_date, test_time, point_number,
               description, source_file
        FROM test_points
    """, con)
    con.close()

    # ---- Reproducir EXACTO lo que hace app.py en load_data() ----
    df["fecha"] = pd.to_datetime(df["test_date"], format=FORMATO_FECHA, errors="coerce")
    df["pn_num"] = pd.to_numeric(df["point_number"], errors="coerce")
    puntos = (df.drop_duplicates("point_id")
                .sort_values(["variant", "fecha", "test_time", "pn_num", "point_id"],
                             na_position="last")
                .copy())
    puntos["consecutivo"] = puntos.groupby("variant").cumcount() + 1

    print("=" * 72)
    print(f"DIAGNOSTICO DE CONSECUTIVO — {db_path.resolve()}")
    print(f"Total de puntos: {len(puntos)}")
    print("=" * 72)

    for variant, grp in puntos.groupby("variant"):
        grp = grp.sort_values("consecutivo").reset_index(drop=True)
        print(f"\n--- Variante {variant} ({len(grp)} puntos) ---")

        violaciones = []
        max_fecha_vista = None
        max_fecha_point = None
        for row in grp.itertuples():
            if pd.isna(row.fecha):
                continue
            if max_fecha_vista is not None and row.fecha < max_fecha_vista:
                violaciones.append({
                    "consecutivo": row.consecutivo,
                    "point_id": row.point_id,
                    "fecha_aqui": row.fecha.date(),
                    "source_file": row.source_file,
                    "consecutivo_anterior_mayor": True,
                    "fecha_mas_alta_vista_antes": max_fecha_vista.date(),
                    "point_id_de_esa_fecha": max_fecha_point,
                })
            else:
                max_fecha_vista = row.fecha
                max_fecha_point = row.point_id

        if not violaciones:
            print("  ✓ Sin violaciones: la fecha nunca retrocede al avanzar el consecutivo.")
        else:
            print(f"  ⚠ {len(violaciones)} violacion(es) de orden cronologico encontradas:")
            for v in violaciones[:20]:
                print(
                    f"    consecutivo={v['consecutivo']:5d}  point_id={v['point_id']:6d}  "
                    f"fecha={v['fecha_aqui']}  <  ya se habia visto fecha "
                    f"{v['fecha_mas_alta_vista_antes']} en point_id={v['point_id_de_esa_fecha']}  "
                    f"({v['source_file']})"
                )
            if len(violaciones) > 20:
                print(f"    ... y {len(violaciones) - 20} mas.")

        # Puntos sin fecha valida (deberian ir al final, na_position='last')
        n_sin_fecha = grp["fecha"].isna().sum()
        if n_sin_fecha:
            print(f"  Puntos sin fecha valida (van al final del orden): {n_sin_fecha}")

    print("\n[Listo. Este diagnostico no modifica la base, solo lee.]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/motores.db")
    args = ap.parse_args()
    run(args.db)
