#!/usr/bin/env python3
"""
resync_measurements.py — Rellena mediciones NUEVAS en puntos YA ingeridos.

POR QUÉ EXISTE
---------------
etl.py es idempotente por archivo (row_hash): si un archivo ya se cargó, al
volver a correr etl.py se marca como 'skipped' y no se toca. Eso es correcto
para no duplicar, pero significa que si editas mapping.yaml para agregar
canonicos nuevos (por ejemplo N1R, N2R2, WFK, W2AR, FNR2 para la pagina de
Correlacion vs Historico), esos valores NUNCA se agregan a los puntos que ya
estaban en la base, porque el archivo entero se salta.

Este script resuelve eso: para cada test_point que YA existe en motores.db,
vuelve a abrir su archivo Excel de origen, relee el Buffer con el
mapping.yaml ACTUAL, y agrega SOLO las mediciones (canonical, raw_name) que
todavia no existan para ese punto. No toca ni duplica lo que ya estaba.

PRIVACIDAD
----------
Igual que etl.py: los valores SI se leen (es su proposito) y se guardan solo
en esta base local.

COMO SE USA
-----------
    py resync_measurements.py --db data\\motores.db --mapping mapping.yaml ^
        --folder "C:\\pruebas_leap_1A" --folder "C:\\pruebas_leap_1B"

Puedes pasar --folder varias veces (una por cada carpeta donde busques los
archivos originales). El script busca cada 'source_file' guardado en la base
dentro de todas las carpetas dadas.

Es seguro correrlo varias veces: si ya no hay nada nuevo que agregar, no hace
nada.
"""

import argparse
from pathlib import Path
from collections import defaultdict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Reusa el esquema y las funciones de lectura/mapeo de etl.py tal cual, para
# no duplicar logica ni arriesgar inconsistencias entre los dos scripts.
from etl import (
    Base, Engine, TestPoint, Measurement, IngestLog,
    read_buffer, load_effective_mapping, get_measurements, ensure_schema_migrations,
)


def find_source_path(source_file, folders):
    """Busca 'source_file' (solo el nombre) dentro de las carpetas dadas.

    Primero prueba el nombre directo dentro de cada carpeta; si no esta ahi,
    busca recursivamente (Loaded/ puede tener subcarpetas por variante).
    Devuelve el primer Path que exista, o None si no aparece en ninguna."""
    name = Path(str(source_file)).name
    for folder in folders:
        folder = Path(folder)
        candidate = folder / name
        if candidate.exists():
            return candidate
        matches = list(folder.rglob(name))
        if matches:
            return matches[0]
    return None


def existing_keys_por_punto(session):
    """Devuelve dict {point_id: set((canonical, raw_name))} con lo que ya
    esta guardado, para no duplicar."""
    rows = session.execute(
        select(Measurement.point_id, Measurement.canonical, Measurement.raw_name)
    ).all()
    out = defaultdict(set)
    for point_id, canonical, raw_name in rows:
        out[point_id].add((canonical, raw_name))
    return out


def run(db_path, mapping_path, folders, variants=None):
    """variants: opcional, iterable de variantes internas ("1A","1B",...) a
    procesar. None (default, uso normal por CLI) procesa todos los puntos.
    Pasar variants acota el trabajo (usado por el dialogo "Cargar nuevos
    parametros" para no recorrer ni marcar 'sin archivo' puntos de modelos
    que el usuario no selecciono).

    Devuelve un dict resumen (n_ok, n_sin_nuevo, n_sin_archivo, n_sin_buffer,
    total_agregadas), o None si la base no existe.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"[!] No existe la base: {db_path.resolve()}")
        return None

    mapping = load_effective_mapping(mapping_path)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)  # no-op si ya existen las tablas
    ensure_schema_migrations(engine)

    with Session(engine) as session:
        puntos = session.execute(select(TestPoint)).scalars().all()
        if variants:
            puntos = [p for p in puntos if p.variant in variants]
        print(f"Puntos en la base: {len(puntos)}")

        ya_tiene = existing_keys_por_punto(session)

        n_ok = n_sin_archivo = n_sin_buffer = n_sin_nuevo = 0
        total_agregadas = 0

        for tp in puntos:
            path = find_source_path(tp.source_file, folders)
            if path is None:
                n_sin_archivo += 1
                continue

            buf = read_buffer(path)
            if buf is None:
                n_sin_buffer += 1
                print(f"  [SIN BUFFER] {tp.source_file}: no se encontro hoja 'Buffer'")
                continue

            meas = get_measurements(buf, mapping, tp.variant)
            presentes = ya_tiene.get(tp.id, set())

            agregadas_aqui = 0
            for canon, raw, val, unit in meas:
                key = (canon, raw)
                if key in presentes:
                    continue  # ya estaba, no se duplica
                session.add(Measurement(
                    point_id=tp.id, canonical=canon, raw_name=raw,
                    value=val, unit=unit,
                ))
                presentes.add(key)
                agregadas_aqui += 1

            if agregadas_aqui == 0:
                n_sin_nuevo += 1
            else:
                n_ok += 1
                total_agregadas += agregadas_aqui
                print(f"  [OK] {tp.source_file}: +{agregadas_aqui} mediciones nuevas")

        session.commit()

    print("\nResumen del resync:")
    print(f"  Puntos con mediciones nuevas agregadas : {n_ok}")
    print(f"  Puntos ya al dia (nada que agregar)     : {n_sin_nuevo}")
    print(f"  Puntos cuyo archivo no se encontro      : {n_sin_archivo}")
    print(f"  Puntos con archivo pero sin hoja Buffer : {n_sin_buffer}")
    print(f"  Total de mediciones nuevas agregadas    : {total_agregadas}")
    if n_sin_archivo:
        print(
            "\n  Nota: si 'archivo no encontrado' > 0, revisa que pasaste TODAS "
            "las carpetas originales con --folder (una o varias veces)."
        )

    return {
        "n_ok": n_ok,
        "n_sin_nuevo": n_sin_nuevo,
        "n_sin_archivo": n_sin_archivo,
        "n_sin_buffer": n_sin_buffer,
        "total_agregadas": total_agregadas,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Rellena mediciones nuevas (de un mapping.yaml actualizado) "
                    "en puntos ya ingeridos, sin duplicar."
    )
    ap.add_argument("--db", default="data/motores.db", help="Ruta del archivo SQLite")
    ap.add_argument("--mapping", default="mapping.yaml", help="Ruta del mapping.yaml actualizado")
    ap.add_argument(
        "--folder", action="append", required=True,
        help="Carpeta con los archivos originales. Repite --folder por cada carpeta.",
    )
    args = ap.parse_args()
    run(args.db, args.mapping, args.folder)
