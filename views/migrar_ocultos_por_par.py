#!/usr/bin/env python3
"""
migrar_ocultos_por_par.py — Migra ocultamientos viejos de Correlacion Ref.
al alcance por par (opt-in, con dry-run).

CONTEXTO
--------
Antes de existir el alcance por par, ocultar un punto en Correlacion Ref.
lo quitaba de TODA la vista (los 6 pares), aunque el motivo registrado
mencionara un solo par. Como el 'reason' lo genera la app con formato fijo
("Marcado mal calculado en <par> (<variante>)"), se puede recuperar la
intencion original y mover cada ocultamiento a su scope por par:

    correlacion_ref  ->  correlacion_ref::N1R vs EGTR   (por ejemplo)

ATENCION: migrar hace que cada punto REAPAREZCA en los otros 5 pares donde
hoy esta oculto. Ese es justamente el objetivo del alcance por par, pero
cambia lo que se ve en pantalla; por eso este script NO corre solo desde la
app: es una decision explicita del usuario.

USO
---
    py migrar_ocultos_por_par.py               # dry-run: solo reporta
    py migrar_ocultos_por_par.py --aplicar     # ejecuta la migracion
    py migrar_ocultos_por_par.py --db ruta/a/config.db
"""

import argparse
import re

import config_store
from views.correlacion_ref import BLOQUES_COLUMNAS, HIDDEN_SCOPE

# Formato exacto con el que correlacion_ref.py registra el motivo.
PATRON_REASON = re.compile(r"^Marcado mal calculado en (?P<par>.+?) \(")


def analizar(con):
    """Clasifica los ocultos de scope 'correlacion_ref' en migrables por par
    y no migrables (reason manual o par desconocido)."""
    filas = con.execute(
        "SELECT rowid, point_id, stable_point_key, reason FROM hidden_points "
        "WHERE scope=?", (HIDDEN_SCOPE,),
    ).fetchall()
    migrables = {}      # nombre_par -> [rowid, ...]
    no_migrables = []   # (rowid, point_id, reason)
    for rowid, pid, _key, reason in filas:
        m = PATRON_REASON.match(reason or "")
        par = m.group("par") if m else None
        if par in BLOQUES_COLUMNAS:
            migrables.setdefault(par, []).append(rowid)
        else:
            no_migrables.append((rowid, pid, reason))
    return len(filas), migrables, no_migrables


def aplicar(con, migrables):
    """Mueve cada fila migrable a su scope por par.

    UPDATE OR IGNORE: si ya existe un ocultamiento por par para la misma
    (scope, stable_point_key) —p. ej. el usuario ya lo oculto por par despues
    de la actualizacion— el indice unico lo bloquea; esa fila vieja queda
    duplicada de una intencion ya cubierta y se elimina.
    """
    migradas = 0
    duplicadas = 0
    for par, rowids in migrables.items():
        scope_nuevo = f"{HIDDEN_SCOPE}::{par}"
        for rowid in rowids:
            con.execute(
                "UPDATE OR IGNORE hidden_points SET scope=? WHERE rowid=?",
                (scope_nuevo, rowid),
            )
            sigue_vieja = con.execute(
                "SELECT 1 FROM hidden_points WHERE rowid=? AND scope=?",
                (rowid, HIDDEN_SCOPE),
            ).fetchone()
            if sigue_vieja:
                con.execute("DELETE FROM hidden_points WHERE rowid=?", (rowid,))
                duplicadas += 1
            else:
                migradas += 1
    con.commit()
    return migradas, duplicadas


def main():
    ap = argparse.ArgumentParser(
        description="Migra ocultos de Correlacion Ref. al alcance por par")
    ap.add_argument("--db", default=config_store.CONFIG_DB,
                    help="Ruta de config.db (default: config.db)")
    ap.add_argument("--aplicar", action="store_true",
                    help="Ejecuta la migracion (sin esto, solo reporta)")
    args = ap.parse_args()

    # _con garantiza columnas, dedupe e indices antes de trabajar.
    con = config_store._con(args.db)

    total, migrables, no_migrables = analizar(con)
    print(f"Base: {args.db}")
    print(f"Ocultos con scope '{HIDDEN_SCOPE}' (toda la vista): {total}")
    if not total:
        print("Nada que migrar.")
        con.close()
        return

    n_migrables = sum(len(v) for v in migrables.values())
    print(f"Migrables segun su reason: {n_migrables}")
    for par in BLOQUES_COLUMNAS:
        if par in migrables:
            print(f"  {len(migrables[par]):5d} -> '{HIDDEN_SCOPE}::{par}'")
    print(f"No migrables (reason manual/desconocido, se quedan en toda la vista): "
          f"{len(no_migrables)}")
    for _rowid, pid, reason in no_migrables[:10]:
        print(f"    point_id {pid}: {reason!r}")
    if len(no_migrables) > 10:
        print(f"    ... y {len(no_migrables) - 10} mas")

    print("\nATENCION: cada punto migrado REAPARECERA en los otros 5 pares.")
    if not args.aplicar:
        print("Modo dry-run: NO se cambio nada. Corre con --aplicar para ejecutar.")
        con.close()
        return

    migradas, duplicadas = aplicar(con, migrables)
    con.close()
    print(f"\nMigradas: {migradas}")
    if duplicadas:
        print(f"Eliminadas por duplicar un ocultamiento por par ya existente: {duplicadas}")
    print("Listo. Abre la app y revisa Correlacion Ref. > puntos ocultos.")


if __name__ == "__main__":
    main()
