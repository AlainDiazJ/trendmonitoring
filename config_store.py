#!/usr/bin/env python3
"""
config_store.py — Almacen de CONFIGURACION del usuario (separado de los datos).

Guarda en 'config.db' cosas que NO son datos de prueba sino ajustes del usuario:
  - umbrales fijos por (variante, parametro, description)
  - puntos ocultos en vistas comparativas (ej. Correlacion Ref.)
  - (mas adelante) anotaciones, vistas favoritas

Se mantiene aparte de 'motores.db' a proposito: motores.db son los hechos
auditables que vienen de los Exceles y se puede regenerar con el ETL sin perder
esta configuracion; y esta configuracion se puede editar sin tocar los datos.

Lo usa el dashboard (app.py). No requiere instalar nada extra: usa sqlite3 estandar.
"""

import sqlite3
from pathlib import Path

CONFIG_DB = "config.db"


def _ensure_hidden_points_stable_columns(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(hidden_points)").fetchall()}
    if "stable_point_key" not in cols:
        con.execute("ALTER TABLE hidden_points ADD COLUMN stable_point_key TEXT")
    if "migrated_from_point_id" not in cols:
        con.execute("ALTER TABLE hidden_points ADD COLUMN migrated_from_point_id INTEGER")


def _con(db_path=CONFIG_DB):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True) if Path(db_path).parent != Path("") else None
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS thresholds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant     TEXT NOT NULL,
            param_label TEXT NOT NULL,
            description TEXT NOT NULL,
            low  REAL,
            high REAL,
            UNIQUE(variant, param_label, description)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,   -- ISO yyyy-mm-dd
            name       TEXT NOT NULL,
            description TEXT,
            scope      TEXT NOT NULL DEFAULT 'ALL'  -- 'ALL' o variante
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS hidden_points (
            point_id   INTEGER NOT NULL,
            scope      TEXT NOT NULL DEFAULT 'correlacion_ref',
            reason     TEXT,
            created_at TEXT,
            PRIMARY KEY (point_id, scope)
        )
    """)
    _ensure_hidden_points_stable_columns(con)
    con.commit()
    return con


def get_threshold(variant, param_label, description, db_path=CONFIG_DB):
    """Devuelve (low, high) para esa combinacion, o (None, None) si no hay."""
    con = _con(db_path)
    row = con.execute(
        "SELECT low, high FROM thresholds WHERE variant=? AND param_label=? AND description=?",
        (variant, param_label, description),
    ).fetchone()
    con.close()
    return (row[0], row[1]) if row else (None, None)


def set_threshold(variant, param_label, description, low, high, db_path=CONFIG_DB):
    """Inserta o actualiza el umbral fijo. low/high pueden ser None."""
    con = _con(db_path)
    con.execute("""
        INSERT INTO thresholds (variant, param_label, description, low, high)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(variant, param_label, description)
        DO UPDATE SET low=excluded.low, high=excluded.high
    """, (variant, param_label, description, low, high))
    con.commit()
    con.close()


def delete_threshold(variant, param_label, description, db_path=CONFIG_DB):
    con = _con(db_path)
    con.execute(
        "DELETE FROM thresholds WHERE variant=? AND param_label=? AND description=?",
        (variant, param_label, description),
    )
    con.commit()
    con.close()


def list_thresholds(db_path=CONFIG_DB):
    """Lista todos los umbrales definidos (para revision)."""
    con = _con(db_path)
    rows = con.execute(
        "SELECT variant, param_label, description, low, high FROM thresholds ORDER BY variant, param_label"
    ).fetchall()
    con.close()
    return rows


# ===========================================================================
# EVENTOS (marcas temporales: actualizaciones, recalibraciones, etc.)
# ===========================================================================
def add_event(event_date, name, description, scope="ALL", db_path=CONFIG_DB):
    """event_date en ISO 'yyyy-mm-dd'. scope: 'ALL' o una variante guardada en test_points.variant."""
    con = _con(db_path)
    con.execute(
        "INSERT INTO events (event_date, name, description, scope) VALUES (?, ?, ?, ?)",
        (event_date, name, description, scope),
    )
    con.commit()
    con.close()


def update_event(event_id, event_date, name, description, scope, db_path=CONFIG_DB):
    con = _con(db_path)
    con.execute(
        "UPDATE events SET event_date=?, name=?, description=?, scope=? WHERE id=?",
        (event_date, name, description, scope, event_id),
    )
    con.commit()
    con.close()


def delete_event(event_id, db_path=CONFIG_DB):
    con = _con(db_path)
    con.execute("DELETE FROM events WHERE id=?", (event_id,))
    con.commit()
    con.close()


def list_events(scope=None, db_path=CONFIG_DB):
    """Lista eventos. Si scope se pasa, devuelve los de ese scope
    mas los 'ALL'. Si scope es None, devuelve todos. Retorna lista de dicts."""
    con = _con(db_path)
    if scope is None:
        rows = con.execute(
            "SELECT id, event_date, name, description, scope FROM events ORDER BY event_date"
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, event_date, name, description, scope FROM events "
            "WHERE scope=? OR scope='ALL' ORDER BY event_date", (scope,)
        ).fetchall()
    con.close()
    return [dict(id=r[0], event_date=r[1], name=r[2], description=r[3], scope=r[4])
            for r in rows]


# ===========================================================================
# VISTAS FAVORITAS (combinaciones de filtros guardadas)
# ===========================================================================
import json as _json


def _ensure_views_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        )
    """)


def save_view(name, payload_dict, db_path=CONFIG_DB):
    """Guarda (o reemplaza) una vista. payload_dict: filtros como dict serializable."""
    con = _con(db_path)
    _ensure_views_table(con)
    con.execute("""
        INSERT INTO views (name, payload) VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET payload=excluded.payload
    """, (name, _json.dumps(payload_dict)))
    con.commit()
    con.close()


def list_views(db_path=CONFIG_DB):
    """Devuelve lista de dicts: {name, payload(dict)}."""
    con = _con(db_path)
    _ensure_views_table(con)
    rows = con.execute("SELECT name, payload FROM views ORDER BY name").fetchall()
    con.close()
    out = []
    for name, payload in rows:
        try:
            out.append({"name": name, "payload": _json.loads(payload)})
        except Exception:
            pass
    return out


def get_view(name, db_path=CONFIG_DB):
    con = _con(db_path)
    _ensure_views_table(con)
    row = con.execute("SELECT payload FROM views WHERE name=?", (name,)).fetchone()
    con.close()
    if row:
        try:
            return _json.loads(row[0])
        except Exception:
            return None
    return None


def delete_view(name, db_path=CONFIG_DB):
    con = _con(db_path)
    _ensure_views_table(con)
    con.execute("DELETE FROM views WHERE name=?", (name,))
    con.commit()
    con.close()


# ===========================================================================
# ESTADOS DE ANOMALIAS (Pendiente / Revisada / Descartada)
# Persistencia por "firma" de anomalia: variante + parametro + reporte + tipo
# ===========================================================================
def _ensure_anom_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS anom_status (
            signature TEXT PRIMARY KEY,
            status    TEXT NOT NULL,
            note      TEXT,
            updated_at TEXT
        )
    """)


def anom_signature(variant, param, reporte, tipo, description="", stable_point_key=None):
    """Firma que identifica una anomalia entre sesiones.

    Si stable_point_key esta disponible, la firma no depende del consecutivo
    visible/reporte, que puede cambiar al reordenar o regenerar la base.
    """
    if stable_point_key:
        return f"point:{stable_point_key}|{param}|{tipo}|{description}"
    return f"{variant}|{param}|{reporte}|{tipo}|{description}"


def set_anom_status(signature, status, note="", db_path=CONFIG_DB):
    """status: 'Pendiente' / 'Revisada' / 'Descartada'."""
    from datetime import datetime as _dt
    con = _con(db_path)
    _ensure_anom_table(con)
    con.execute("""
        INSERT INTO anom_status (signature, status, note, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(signature) DO UPDATE SET
            status=excluded.status, note=excluded.note, updated_at=excluded.updated_at
    """, (signature, status, note, _dt.now().isoformat(timespec="seconds")))
    con.commit()
    con.close()


def get_anom_status(signature, db_path=CONFIG_DB):
    con = _con(db_path)
    _ensure_anom_table(con)
    row = con.execute(
        "SELECT status, note FROM anom_status WHERE signature=?", (signature,)
    ).fetchone()
    con.close()
    if row:
        return {"status": row[0], "note": row[1] or ""}
    return {"status": "Pendiente", "note": ""}


def list_anom_statuses(db_path=CONFIG_DB):
    """Devuelve dict {signature: {status, note, updated_at}}."""
    con = _con(db_path)
    _ensure_anom_table(con)
    rows = con.execute(
        "SELECT signature, status, note, updated_at FROM anom_status"
    ).fetchall()
    con.close()
    return {r[0]: {"status": r[1], "note": r[2] or "", "updated_at": r[3]} for r in rows}


# ===========================================================================
# PUNTOS OCULTOS EN VISTAS COMPARATIVAS (ej. Correlacion Ref.)
# No borra nada de motores.db: marca stable_point_key cuando esta disponible,
# y conserva point_id como compatibilidad con datos anteriores.
# ===========================================================================
def hide_point(point_id, scope="correlacion_ref", reason="", stable_point_key=None, db_path=CONFIG_DB):
    """Oculta un punto. Prefiere stable_point_key; point_id queda como fallback."""
    from datetime import datetime as _dt
    con = _con(db_path)
    now = _dt.now().isoformat(timespec="seconds")
    con.execute("""
        INSERT INTO hidden_points (point_id, scope, reason, created_at, stable_point_key, migrated_from_point_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(point_id, scope) DO UPDATE SET
            reason=excluded.reason,
            created_at=excluded.created_at,
            stable_point_key=COALESCE(excluded.stable_point_key, hidden_points.stable_point_key),
            migrated_from_point_id=COALESCE(hidden_points.migrated_from_point_id, excluded.migrated_from_point_id)
    """, (int(point_id), scope, reason, now, stable_point_key, int(point_id)))
    con.commit()
    con.close()


def unhide_point(point_id, scope="correlacion_ref", stable_point_key=None, db_path=CONFIG_DB):
    """Restaura un punto oculto por stable key o, si falta, por point_id."""
    con = _con(db_path)
    if stable_point_key:
        con.execute(
            "DELETE FROM hidden_points WHERE scope=? AND stable_point_key=?",
            (scope, stable_point_key),
        )
    else:
        con.execute(
            "DELETE FROM hidden_points WHERE point_id=? AND scope=?",
            (int(point_id), scope),
        )
    con.commit()
    con.close()


def unhide_all_points(scope="correlacion_ref", db_path=CONFIG_DB):
    """Restaura TODOS los puntos ocultos de ese scope."""
    con = _con(db_path)
    con.execute("DELETE FROM hidden_points WHERE scope=?", (scope,))
    con.commit()
    con.close()


def list_hidden_points(scope="correlacion_ref", db_path=CONFIG_DB):
    """Compatibilidad: devuelve set de point_id ocultos."""
    con = _con(db_path)
    rows = con.execute(
        "SELECT point_id FROM hidden_points WHERE scope=?", (scope,)
    ).fetchall()
    con.close()
    return {r[0] for r in rows}


def list_hidden_point_keys(scope="correlacion_ref", db_path=CONFIG_DB):
    """Devuelve set de stable_point_key ocultas."""
    con = _con(db_path)
    rows = con.execute(
        "SELECT stable_point_key FROM hidden_points WHERE scope=? AND stable_point_key IS NOT NULL",
        (scope,),
    ).fetchall()
    con.close()
    return {r[0] for r in rows}


def list_hidden_points_detail(scope="correlacion_ref", db_path=CONFIG_DB):
    """Lista puntos ocultos con point_id y stable_point_key para administracion."""
    con = _con(db_path)
    rows = con.execute(
        "SELECT point_id, stable_point_key, reason, created_at, migrated_from_point_id FROM hidden_points "
        "WHERE scope=? ORDER BY created_at DESC",
        (scope,),
    ).fetchall()
    con.close()
    return [
        {
            "point_id": r[0],
            "stable_point_key": r[1],
            "reason": r[2] or "",
            "created_at": r[3],
            "migrated_from_point_id": r[4],
        }
        for r in rows
    ]


# ===========================================================================
# CUARENTENA DE EXCELES (trazabilidad de archivos retirados del dashboard)
# Los Excel de origen son la evidencia primaria de cada punto: nunca se
# borran, se mueven a una carpeta de cuarentena y aqui queda el registro.
# ===========================================================================
def _ensure_quarantine_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS excel_quarantine_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file       TEXT NOT NULL,
            original_path     TEXT,
            quarantine_path   TEXT,
            point_ids         TEXT,  -- ids separados por coma
            stable_point_keys TEXT,  -- llaves separadas por coma
            reason            TEXT,
            created_at        TEXT
        )
    """)


def log_excel_quarantine(source_file, original_path, quarantine_path,
                         point_ids=None, stable_point_keys=None, reason="",
                         db_path=CONFIG_DB):
    """Registra un Excel movido a cuarentena y los puntos retirados con el."""
    from datetime import datetime as _dt
    con = _con(db_path)
    _ensure_quarantine_table(con)
    con.execute("""
        INSERT INTO excel_quarantine_log
            (source_file, original_path, quarantine_path, point_ids,
             stable_point_keys, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        source_file, original_path, quarantine_path,
        ",".join(str(p) for p in point_ids) if point_ids else None,
        ",".join(str(k) for k in stable_point_keys if k) if stable_point_keys else None,
        reason, _dt.now().isoformat(timespec="seconds"),
    ))
    con.commit()
    con.close()


def list_excel_quarantine(db_path=CONFIG_DB):
    """Historial de cuarentena, mas reciente primero. Lista de dicts."""
    con = _con(db_path)
    _ensure_quarantine_table(con)
    rows = con.execute("""
        SELECT id, source_file, original_path, quarantine_path, point_ids,
               stable_point_keys, reason, created_at
        FROM excel_quarantine_log ORDER BY id DESC
    """).fetchall()
    con.close()
    return [
        {
            "id": r[0], "source_file": r[1], "original_path": r[2],
            "quarantine_path": r[3], "point_ids": r[4] or "",
            "stable_point_keys": r[5] or "", "reason": r[6] or "",
            "created_at": r[7],
        }
        for r in rows
    ]


if __name__ == "__main__":
    # Prueba rapida
    set_threshold("1B", "EGTR2 [degC]", "TEST 003 : TAKE-OFF", 700.0, 850.0)
    print("Guardado. Umbrales actuales:")
    for r in list_thresholds():
        print("  ", r)
    print("get:", get_threshold("1B", "EGTR2 [degC]", "TEST 003 : TAKE-OFF"))
