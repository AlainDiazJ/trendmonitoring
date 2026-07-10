#!/usr/bin/env python3
"""
diagnostico_fechas.py — Revisa que formatos tiene realmente test_date en
motores.db, y cuantas filas fallan al parsearse con el formato fijo que usa
app.py ("%d/%m/%Y").

No modifica nada, solo lee y reporta. Sirve para confirmar (o descartar) que
el problema de orden en el filtro de fechas es por formatos mixtos.

USO
---
    py diagnostico_fechas.py --db data\\motores.db
"""

import argparse
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pandas as pd

# Mismo formato que usa app.py actualmente, para reproducir el problema tal cual.
FORMATO_ACTUAL = "%d/%m/%Y"


def clasificar_forma(s):
    """Reduce un valor de test_date a un 'patron de forma' (sin ver el valor
    exacto) para agrupar formatos parecidos. Ej: '07/06/2016' -> 'DD/DD/DDDD',
    '2016-06-07 00:00:00' -> 'DDDD-DD-DD DD:DD:DD'."""
    if s is None:
        return "(None)"
    s = str(s).strip()
    if s == "":
        return "(vacio)"
    return re.sub(r"\d", "D", s)


def run(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"[!] No existe la base: {db_path.resolve()}")
        return

    con = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT id AS point_id, variant, test_date, source_file FROM test_points", con
    )
    con.close()

    print("=" * 72)
    print(f"DIAGNOSTICO DE test_date — {db_path.resolve()}")
    print(f"Total de puntos: {len(df)}")
    print("=" * 72)

    # ---- 1) Formas encontradas (patron de digitos/separadores) ----
    df["forma"] = df["test_date"].apply(clasificar_forma)
    conteo_formas = Counter(df["forma"])
    print("\nFORMAS DISTINTAS ENCONTRADAS EN test_date (patron -> cuantas filas):")
    for forma, n in conteo_formas.most_common():
        ejemplo = df.loc[df["forma"] == forma, "test_date"].iloc[0]
        print(f"  {forma:30s}  {n:6d} filas   ej: {ejemplo!r}")

    if len(conteo_formas) > 1:
        print(
            "\n  -> Hay MAS DE UNA FORMA distinta. Esto confirma que test_date "
            "no es un formato uniforme (algunas vienen de celdas de fecha nativas "
            "de Excel, otras como texto plano, o de versiones distintas del "
            "software de la celda)."
        )
    else:
        print("\n  -> Solo una forma encontrada. El problema de orden no es por "
              "formato mixto; hay que buscar la causa en otro lado.")

    # ---- 2) Cuantas filas fallan con el formato fijo actual de app.py ----
    parsed = pd.to_datetime(df["test_date"], format=FORMATO_ACTUAL, errors="coerce")
    n_ok = parsed.notna().sum()
    n_fail = parsed.isna().sum()
    print(f"\nPARSEO CON EL FORMATO ACTUAL DE app.py ('{FORMATO_ACTUAL}'):")
    print(f"  Se parsean OK : {n_ok}")
    print(f"  Fallan (NaT)  : {n_fail}")

    if n_fail > 0:
        print("\n  Ejemplos de filas que fallan (se van al final del orden en app.py):")
        fallidas = df.loc[parsed.isna(), ["point_id", "variant", "test_date", "source_file"]]
        for row in fallidas.head(15).itertuples():
            print(f"    point_id={row.point_id}  variant={row.variant}  "
                  f"test_date={row.test_date!r}  source_file={row.source_file}")
        if n_fail > 15:
            print(f"    ... y {n_fail - 15} mas.")

    # ---- 3) Casos ambiguos: dia y mes ambos <= 12 (DD/MM vs MM/DD indistinguible) ----
    patron_ddmmaaaa = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
    ambiguos = 0
    ejemplos_ambiguos = []
    for val in df["test_date"].dropna().unique():
        m = patron_ddmmaaaa.match(str(val).strip())
        if m:
            a, b, _ = m.groups()
            if int(a) <= 12 and int(b) <= 12 and a != b:
                ambiguos += 1
                if len(ejemplos_ambiguos) < 10:
                    ejemplos_ambiguos.append(val)
    print(f"\nVALORES 'DD/MM/AAAA' AMBIGUOS (dia y mes ambos <=12, ej. 05/08/2022):")
    print(f"  {ambiguos} valor(es) distinto(s) donde no se puede saber por la sola "
          f"cadena si es DD/MM o MM/DD.")
    if ejemplos_ambiguos:
        print(f"  Ejemplos: {ejemplos_ambiguos}")
    print(
        "  -> Estos NO fallan al parsear (ambas interpretaciones son fechas validas), "
        "pero si alguna de tus fuentes exporta en MM/DD/AAAA (formato US) mezclada "
        "con DD/MM/AAAA, aqui es donde el orden se corrompe SIN avisar (no hay NaT, "
        "solo dia y mes invertidos)."
    )

    # ---- 4) Prueba definitiva: hay filas donde el 2do componente es >12? ----
    # Si field_a>12 -> DD/MM confirmado para esa fila (mes no puede ser >12).
    # Si field_b>12 -> MM/DD confirmado para esa fila (el que es >12 solo puede
    # ser el dia, asi que el orden real es MM/DD, formato US).
    # Si aparecen los DOS casos en la misma base, hay mezcla real de formato.
    confirmado_ddmm = df.loc[df["test_date"].astype(str).str.match(r"^(1[3-9]|2\d|3[01])/\d{2}/\d{4}$"),
                             ["point_id", "variant", "test_date", "source_file"]]
    confirmado_mmdd = df.loc[df["test_date"].astype(str).str.match(r"^\d{2}/(1[3-9]|2\d|3[01])/\d{4}$"),
                             ["point_id", "variant", "test_date", "source_file"]]

    print(f"\nPRUEBA DEFINITIVA DE FORMATO (usando filas donde el dia real es >12, "
          f"asi que no hay ambiguedad posible):")
    print(f"  Filas que CONFIRMAN formato DD/MM/AAAA (primer numero >12): {len(confirmado_ddmm)}")
    print(f"  Filas que CONFIRMAN formato MM/DD/AAAA (segundo numero >12): {len(confirmado_mmdd)}")

    if len(confirmado_ddmm) > 0 and len(confirmado_mmdd) > 0:
        print(
            "\n  ⚠ HAY MEZCLA REAL DE FORMATO CONFIRMADA. Algunos archivos exportan "
            "en DD/MM/AAAA y otros en MM/DD/AAAA (formato US). El parser fijo de "
            "app.py NO puede distinguir uno del otro por si solo; hay que decidir "
            "la regla por archivo/lote de origen."
        )
        print("\n  Ejemplos que confirman DD/MM (dia >12 en 1era posicion):")
        for row in confirmado_ddmm.head(5).itertuples():
            print(f"    point_id={row.point_id}  test_date={row.test_date!r}  source_file={row.source_file}")
        print("\n  Ejemplos que confirman MM/DD (dia >12 en 2da posicion):")
        for row in confirmado_mmdd.head(5).itertuples():
            print(f"    point_id={row.point_id}  test_date={row.test_date!r}  source_file={row.source_file}")
    elif len(confirmado_ddmm) > 0:
        print(
            "\n  -> Solo se confirma DD/MM/AAAA en toda la base (nunca aparece un "
            "caso que fuerce MM/DD). El formato parece consistente; el problema de "
            "orden probablemente NO es por dia/mes invertido."
        )
    elif len(confirmado_mmdd) > 0:
        print(
            "\n  -> Solo se confirma MM/DD/AAAA en toda la base (formato US). Esto "
            "significa que el formato fijo '%d/%m/%Y' de app.py esta leyendo TODA "
            "la base al reves (dia y mes invertidos en TODAS las fechas), no solo "
            "en las ambiguas."
        )
    else:
        print(
            "\n  -> No hay ninguna fila con dia >12 en la base completa (todas las "
            "fechas caen dentro de los primeros 12 dias del mes). No se puede "
            "confirmar el formato por este metodo; revisa manualmente un par de "
            "test_date contra la fecha real de la prueba en el Excel origen."
        )

    print("\n[Listo. Este diagnostico no modifica la base, solo lee.]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/motores.db")
    args = ap.parse_args()
    run(args.db)
