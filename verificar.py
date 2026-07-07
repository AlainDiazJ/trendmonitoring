#!/usr/bin/env python3
"""
verificar.py — Resumen legible de la base motores.db (sin saber SQL).

Muestra: motores cargados, puntos por motor/variante, tipos de punto,
y para cada parámetro canónico: cuántas mediciones hay, en qué unidades,
y el rango de valores (min / max). Sirve para confirmar que los datos
reales entraron bien antes de construir el dashboard.

USO
---
    py verificar.py --db data\\motores.db
"""

import argparse
import sqlite3
from pathlib import Path


def run(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"[!] No existe la base: {db_path.resolve()}")
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    print("=" * 64)
    print(f"RESUMEN DE LA BASE: {db_path.resolve()}")
    print("=" * 64)

    # Motores
    print("\nMOTORES:")
    for sn, et, n in cur.execute("""
        SELECT e.serial_number, e.engine_type, COUNT(tp.id)
        FROM engines e LEFT JOIN test_points tp ON tp.engine_id = e.id
        GROUP BY e.id ORDER BY e.engine_type, e.serial_number"""):
        print(f"  {sn:16s} [{et}] — {n} punto(s)")

    # Puntos por variante y tipo
    print("\nPUNTOS POR VARIANTE Y TIPO:")
    for var, pt, n in cur.execute("""
        SELECT variant, COALESCE(point_type,'(sin tipo)'), COUNT(*)
        FROM test_points GROUP BY variant, point_type ORDER BY variant, point_type"""):
        print(f"  {var}  {pt:20s} — {n}")

    # Rango de fechas
    print("\nRANGO DE FECHAS (texto tal como vino):")
    for var, dmin, dmax in cur.execute("""
        SELECT variant, MIN(test_date), MAX(test_date)
        FROM test_points GROUP BY variant"""):
        print(f"  {var}: {dmin}  ->  {dmax}")

    # Parámetros: cobertura, unidades y rangos
    print("\nPARÁMETROS CANÓNICOS (mediciones / unidades / rango de valores):")
    print(f"  {'canónico':14s} {'n':>5s}  {'unidades':16s} {'min':>12s} {'max':>12s}")
    print("  " + "-" * 62)
    for canon, n, units, vmin, vmax in cur.execute("""
        SELECT canonical, COUNT(*), GROUP_CONCAT(DISTINCT unit),
               MIN(value), MAX(value)
        FROM measurements GROUP BY canonical ORDER BY canonical"""):
        units = units or ""
        print(f"  {canon:14s} {n:5d}  {units:16s} {vmin:12.3f} {vmax:12.3f}")

    # Chequeos de salud
    print("\nCHEQUEOS DE SALUD:")
    bad_unit = cur.execute("SELECT COUNT(*) FROM measurements WHERE unit LIKE '% %'").fetchone()[0]
    print(f"  Unidades con espacios sin normalizar (debe ser 0): {bad_unit}")
    null_val = cur.execute("SELECT COUNT(*) FROM measurements WHERE value IS NULL").fetchone()[0]
    print(f"  Mediciones con valor nulo: {null_val}")
    no_meas = cur.execute("""
        SELECT COUNT(*) FROM test_points tp
        WHERE NOT EXISTS (SELECT 1 FROM measurements m WHERE m.point_id = tp.id)""").fetchone()[0]
    print(f"  Puntos sin ninguna medición (debe ser 0): {no_meas}")

    # Log de ingesta
    print("\nÚLTIMA INGESTA (log):")
    for status, n in cur.execute("""
        SELECT status, COUNT(*) FROM ingest_log GROUP BY status"""):
        print(f"  {status}: {n}")

    con.close()
    print("\n[Listo. Este resumen no modifica la base, solo lee.]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/motores.db")
    args = ap.parse_args()
    run(args.db)
