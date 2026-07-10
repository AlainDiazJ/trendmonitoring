#!/usr/bin/env python3
"""services/param_visibility.py — que parametros aparecen en los desplegables
de Tendencia y Correlacion (no toca Anomalias/Modificadores/Correlacion Ref.,
que usan sus propias listas fijas de parametros nucleo).

Ocultar es solo cosmetico: los datos siguen en motores.db, se guarda unicamente
el conjunto de raw_name que el usuario decidio esconder (config.db).
"""

import config_store as cfg


def parametros_visibles(fdf, db_path=cfg.CONFIG_DB):
    """Lista ordenada de param_label visibles (no ocultos) en fdf."""
    hidden = cfg.list_hidden_params(db_path)
    base = fdf[~fdf["raw_name"].isin(hidden)] if hidden else fdf
    return sorted(base["param_label"].unique())
