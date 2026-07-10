#!/usr/bin/env python3
"""services/deletion_service.py — retiro de puntos y cuarentena de Exceles.

Extraido de app.py sin cambios de logica. Los Excel de origen nunca se
borran: se mueven a quarantine/AAAA-MM-DD/ y el registro queda en config.db
(excel_quarantine_log, ver config_store).
"""

import sqlite3
from pathlib import Path


def delete_test_point(db_path, point_id):
    """Borra un punto completo y todas sus mediciones asociadas."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        n_meas = cur.execute(
            "SELECT COUNT(*) FROM measurements WHERE point_id=?",
            (int(point_id),),
        ).fetchone()[0]
        cur.execute("DELETE FROM measurements WHERE point_id=?", (int(point_id),))
        cur.execute("DELETE FROM test_points WHERE id=?", (int(point_id),))
        n_points = cur.rowcount
        con.commit()
        return n_points, n_meas
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


QUARANTINE_DIR = "quarantine"


def quarantine_source_excels(source_files, source_folder, quarantine_root=QUARANTINE_DIR):
    """Mueve los Excel de origen a una carpeta de cuarentena (NO los borra).

    Los Excel son la evidencia primaria de cada punto; retirarlos del
    dashboard no debe destruirlos. Quedan en quarantine/AAAA-MM-DD/ junto a
    la app, y el registro de la accion se guarda en config.db
    (excel_quarantine_log).

    Devuelve (moved, missing, errors); moved es lista de (origen, destino).
    """
    import shutil
    from datetime import datetime

    folder = Path(source_folder).expanduser()
    dest_dir = Path(quarantine_root).expanduser() / datetime.now().strftime("%Y-%m-%d")
    moved = []
    missing = []
    errors = []

    for source_file in sorted(set(source_files)):
        if not source_file:
            continue
        src = Path(str(source_file))
        path = src if src.is_absolute() else folder / src.name
        try:
            if path.exists() and path.is_file():
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                seq = 1
                while dest.exists():
                    dest = dest_dir / f"{path.stem}_{seq}{path.suffix}"
                    seq += 1
                shutil.move(str(path), str(dest))
                moved.append((str(path), str(dest)))
            else:
                missing.append(str(path))
        except Exception as e:
            errors.append(f"{path}: {e}")

    return moved, missing, errors
