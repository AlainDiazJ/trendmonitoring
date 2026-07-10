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

# Rutas (absolutas) de config.db donde ya se corrio el dedupe + creacion de
# indices de hidden_points en este proceso. _con() abre una conexion nueva en
# CADA llamada (una por funcion publica de este modulo), asi que sin este
# guard el DELETE de dedupe (un table scan con GROUP BY) se repetiria decenas
# de veces por rerun de Streamlit -- ver _ensure_hidden_points_indexes.
_HIDDEN_POINTS_SCHEMA_READY = set()


def _ensure_hidden_points_stable_columns(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(hidden_points)").fetchall()}
    if "stable_point_key" not in cols:
        con.execute("ALTER TABLE hidden_points ADD COLUMN stable_point_key TEXT")
    if "migrated_from_point_id" not in cols:
        con.execute("ALTER TABLE hidden_points ADD COLUMN migrated_from_point_id INTEGER")


def _ensure_hidden_points_indexes(con):
    """Dedupe + indices de hidden_points.

    La PK sigue siendo (point_id, scope) por compatibilidad, pero la llave
    real de un ocultamiento es (scope, stable_point_key): si se regenera
    motores.db, el mismo punto vuelve con otro point_id y sin este indice se
    acumularian filas duplicadas para la misma llave estable. Antes de crear
    el indice unico se eliminan duplicados existentes (se conserva la fila
    mas reciente).
    """
    con.execute("""
        DELETE FROM hidden_points
        WHERE stable_point_key IS NOT NULL
          AND rowid NOT IN (
              SELECT MAX(rowid) FROM hidden_points
              WHERE stable_point_key IS NOT NULL
              GROUP BY scope, stable_point_key
          )
    """)
    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hidden_scope_stable_key
        ON hidden_points(scope, stable_point_key)
        WHERE stable_point_key IS NOT NULL
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_hidden_scope ON hidden_points(scope)")


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
    ruta_abs = str(Path(db_path).resolve())
    if ruta_abs not in _HIDDEN_POINTS_SCHEMA_READY:
        _ensure_hidden_points_stable_columns(con)
        _ensure_hidden_points_indexes(con)
        _HIDDEN_POINTS_SCHEMA_READY.add(ruta_abs)
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
#
# El scope define el alcance del ocultamiento:
#   - 'correlacion_ref'              -> toda la vista Correlacion Ref.
#   - 'correlacion_ref::<par>'       -> solo ese par (ej. 'correlacion_ref::N1R vs EGTR')
#   - GLOBAL_HIDDEN_SCOPE ('global') -> toda la app (lo filtra app.py al cargar)
# ===========================================================================
GLOBAL_HIDDEN_SCOPE = "global"
def hide_point(point_id, scope="correlacion_ref", reason="", stable_point_key=None, db_path=CONFIG_DB):
    """Oculta un punto. Prefiere stable_point_key; point_id queda como fallback."""
    from datetime import datetime as _dt
    con = _con(db_path)
    now = _dt.now().isoformat(timespec="seconds")
    if stable_point_key:
        # El mismo punto puede volver con otro point_id tras regenerar la
        # base: se reemplaza cualquier fila previa de esta llave estable en
        # este scope, para no violar idx_hidden_scope_stable_key.
        con.execute(
            "DELETE FROM hidden_points WHERE scope=? AND stable_point_key=? AND point_id<>?",
            (scope, stable_point_key, int(point_id)),
        )
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
# PERFILES DE BASELINE APROBADOS
# Un baseline aprobado congela formalmente que rango de fechas se considera
# "normal" para (variante, parametro, description), junto con la media y
# sigma calculadas en ese momento. Las bandas y anomalias que lo usan quedan
# ancladas a esos valores congelados: no cambian al ocultar puntos, recargar
# datos ni mover filtros. Eso convierte las bandas de control de algo
# exploratorio a algo defendible y compartido entre usuarios.
# ===========================================================================
def _migrar_baseline_unique_name_global(con):
    """Si baseline_profiles existe con la constraint vieja UNIQUE(name) a
    secas, la reconstruye con UNIQUE(name, variant, param_label,
    description): un nombre de perfil (ej. 'Baseline 2024') solo debe ser
    unico DENTRO de un mismo (variante, parametro, description), no en toda
    la app; si no, guardar un perfil con un nombre ya usado para OTRO
    parametro sobreescribia el perfil ajeno en silencio.

    Si dos filas viejas colisionan bajo la constraint nueva (mismo name +
    variant + param_label + description), se conserva la mas reciente
    (id mayor).
    """
    existe = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='baseline_profiles'"
    ).fetchone()
    if not existe:
        return
    # PRAGMA index_list(t) -> filas (seq, name, unique, origin, partial):
    # el flag "unique" es la columna 2 (0/1), NO el origin ('c'/'u'/'pk').
    tiene_unique_global = any(
        r[2] == 1 and [c[2] for c in con.execute(f"PRAGMA index_info({r[1]})")] == ["name"]
        for r in con.execute("PRAGMA index_list(baseline_profiles)").fetchall()
    )
    if not tiene_unique_global:
        return
    con.execute("ALTER TABLE baseline_profiles RENAME TO baseline_profiles_old_unique_name")
    con.execute("""
        CREATE TABLE baseline_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            variant     TEXT NOT NULL,
            param_label TEXT NOT NULL,
            description TEXT NOT NULL,
            date_from   TEXT NOT NULL,
            date_to     TEXT NOT NULL,
            mean        REAL,
            sigma       REAL,
            n_points    INTEGER,
            approved_by TEXT,
            approved_at TEXT,
            notes       TEXT,
            UNIQUE(name, variant, param_label, description)
        )
    """)
    con.execute("""
        INSERT INTO baseline_profiles
            (id, name, variant, param_label, description, date_from, date_to,
             mean, sigma, n_points, approved_by, approved_at, notes)
        SELECT id, name, variant, param_label, description, date_from, date_to,
               mean, sigma, n_points, approved_by, approved_at, notes
        FROM baseline_profiles_old_unique_name AS o
        WHERE o.id = (
            SELECT MAX(id) FROM baseline_profiles_old_unique_name AS o2
            WHERE o2.name=o.name AND o2.variant=o.variant
              AND o2.param_label=o.param_label AND o2.description=o.description
        )
    """)
    con.execute("DROP TABLE baseline_profiles_old_unique_name")
    # Commit inmediato: esta migracion (rename+create+insert+drop) no debe
    # depender de que la funcion publica que la disparo (p. ej.
    # list_baseline_profiles, que es de solo lectura y no hace commit)
    # confirme la transaccion; sin esto, cerrar la conexion sin commit
    # revierte el DDL en silencio y la migracion parece "no haber pasado".
    con.commit()


def _ensure_baseline_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS baseline_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            variant     TEXT NOT NULL,
            param_label TEXT NOT NULL,
            description TEXT NOT NULL,
            date_from   TEXT NOT NULL,  -- ISO yyyy-mm-dd
            date_to     TEXT NOT NULL,  -- ISO yyyy-mm-dd
            mean        REAL,
            sigma       REAL,
            n_points    INTEGER,
            approved_by TEXT,
            approved_at TEXT,
            notes       TEXT,
            UNIQUE(name, variant, param_label, description)
        )
    """)
    _migrar_baseline_unique_name_global(con)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_baseline_lookup
        ON baseline_profiles(variant, param_label, description)
    """)


def save_baseline_profile(name, variant, param_label, description,
                          date_from, date_to, mean, sigma, n_points,
                          approved_by="", notes="", db_path=CONFIG_DB):
    """Guarda (o reemplaza) un perfil de baseline aprobado.

    El nombre solo debe ser unico DENTRO de (variant, param_label,
    description): dos perfiles de parametros distintos pueden compartir
    nombre (ej. "Baseline 2024") sin pisarse entre si.
    """
    from datetime import datetime as _dt
    con = _con(db_path)
    _ensure_baseline_table(con)
    con.execute("""
        INSERT INTO baseline_profiles
            (name, variant, param_label, description, date_from, date_to,
             mean, sigma, n_points, approved_by, approved_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name, variant, param_label, description) DO UPDATE SET
            date_from=excluded.date_from, date_to=excluded.date_to,
            mean=excluded.mean, sigma=excluded.sigma,
            n_points=excluded.n_points, approved_by=excluded.approved_by,
            approved_at=excluded.approved_at, notes=excluded.notes
    """, (name, variant, param_label, description, date_from, date_to,
          mean, sigma, n_points, approved_by,
          _dt.now().isoformat(timespec="seconds"), notes))
    con.commit()
    con.close()


def list_baseline_profiles(variant=None, param_label=None, description=None,
                           db_path=CONFIG_DB):
    """Perfiles aprobados, mas reciente primero. Filtros opcionales exactos."""
    con = _con(db_path)
    _ensure_baseline_table(con)
    q = ("SELECT id, name, variant, param_label, description, date_from, date_to, "
         "mean, sigma, n_points, approved_by, approved_at, notes "
         "FROM baseline_profiles WHERE 1=1")
    args = []
    for campo, valor in (("variant", variant), ("param_label", param_label),
                         ("description", description)):
        if valor is not None:
            q += f" AND {campo}=?"
            args.append(valor)
    q += " ORDER BY approved_at DESC, id DESC"
    rows = con.execute(q, args).fetchall()
    con.close()
    return [
        {
            "id": r[0], "name": r[1], "variant": r[2], "param_label": r[3],
            "description": r[4], "date_from": r[5], "date_to": r[6],
            "mean": r[7], "sigma": r[8], "n_points": r[9],
            "approved_by": r[10] or "", "approved_at": r[11], "notes": r[12] or "",
        }
        for r in rows
    ]


def delete_baseline_profile(profile_id, db_path=CONFIG_DB):
    con = _con(db_path)
    _ensure_baseline_table(con)
    con.execute("DELETE FROM baseline_profiles WHERE id=?", (int(profile_id),))
    con.commit()
    con.close()


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
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_quarantine_created
        ON excel_quarantine_log(created_at)
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


# ===========================================================================
# PARAMETROS OCULTOS (limpiar los desplegables de Tendencia/Correlacion)
# Global por raw_name: ocultar "EGTK" lo oculta en todas sus variantes/unidades.
# Solo se guardan los ocultos; todo lo demas es activo por defecto.
# ===========================================================================
def _ensure_hidden_params_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS hidden_params (
            raw_name   TEXT PRIMARY KEY,
            created_at TEXT
        )
    """)


def list_hidden_params(db_path=CONFIG_DB):
    """Devuelve el set de raw_name ocultos."""
    con = _con(db_path)
    _ensure_hidden_params_table(con)
    rows = con.execute("SELECT raw_name FROM hidden_params").fetchall()
    con.close()
    return {r[0] for r in rows}


def set_hidden_params(raw_names, db_path=CONFIG_DB):
    """Reemplaza el conjunto completo de raw_name ocultos."""
    from datetime import datetime as _dt
    con = _con(db_path)
    _ensure_hidden_params_table(con)
    con.execute("DELETE FROM hidden_params")
    now = _dt.now().isoformat(timespec="seconds")
    con.executemany(
        "INSERT INTO hidden_params (raw_name, created_at) VALUES (?, ?)",
        [(rn, now) for rn in raw_names],
    )
    con.commit()
    con.close()


# ===========================================================================
# PARAMETROS PERSONALIZADOS (raw_name nuevos agregados desde la app, sin
# tocar mapping.yaml). Se fusionan al vuelo en etl.load_effective_mapping.
# ===========================================================================
def _ensure_custom_params_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS custom_params (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical  TEXT NOT NULL,
            raw_name   TEXT NOT NULL,
            variant    TEXT NOT NULL,
            created_at TEXT,
            UNIQUE(raw_name, variant)
        )
    """)


def add_custom_param(raw_name, variant, canonical=None, db_path=CONFIG_DB):
    """Registra un raw_name a buscar para una variante. canonical por defecto
    es el propio raw_name en minusculas (solo se usa como llave interna del
    mapping efectivo, no se muestra al usuario)."""
    from datetime import datetime as _dt
    canonical = canonical or raw_name.strip().lower()
    con = _con(db_path)
    _ensure_custom_params_table(con)
    con.execute("""
        INSERT INTO custom_params (canonical, raw_name, variant, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(raw_name, variant) DO NOTHING
    """, (canonical, raw_name.strip(), variant, _dt.now().isoformat(timespec="seconds")))
    con.commit()
    con.close()


def list_custom_params(db_path=CONFIG_DB):
    """Lista de (canonical, raw_name, variant) registrados por el usuario."""
    con = _con(db_path)
    _ensure_custom_params_table(con)
    rows = con.execute(
        "SELECT canonical, raw_name, variant FROM custom_params ORDER BY id"
    ).fetchall()
    con.close()
    return rows


if __name__ == "__main__":
    # Prueba rapida
    set_threshold("1B", "EGTR2 [degC]", "TEST 003 : TAKE-OFF", 700.0, 850.0)
    print("Guardado. Umbrales actuales:")
    for r in list_thresholds():
        print("  ", r)
    print("get:", get_threshold("1B", "EGTR2 [degC]", "TEST 003 : TAKE-OFF"))
