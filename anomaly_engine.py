#!/usr/bin/env python3
"""
anomaly_engine.py - Detecta anomalias en los datos de una variante.

Consolida cuatro fuentes:
  - Outliers de banda (puntos fuera de la media +/- N*sigma)
  - Cruces de umbral fijo (puntos sobre/bajo low/high definidos por el usuario)
  - Disparos de CUSUM (deriva sostenida)
  - Rachas largas (N reportes consecutivos subiendo o bajando)

Devuelve un DataFrame con una fila por anomalia, listo para tabular.
"""

import numpy as np
import pandas as pd

# Parametros del nucleo de interes (todas las variantes). El motor itera solo
# sobre los param_label cuyo prefijo coincida con estos nombres canonicos.
# Lista ampliada con variantes confirmadas en los Buffer de LEAP-1A y 1B.
PARAMS_NUCLEO = (
    # EGT (todas las variantes de la cadena de correccion)
    "EGT", "EGTMEAS",
    "EGTK", "EGTK1", "EGTK2", "EGTK3", "EGTK3M",
    "EGTR2", "EGTR2HD", "EGTR2HDM",
    "EGTHD", "EGTHDM", "EGTHD_MAR", "EGTHDM_MAR",
    # Velocidades de eje
    "N1", "N1K", "N2", "N2K", "N2R25",
    # Flujo de combustible
    "WF36", "WF36pph", "WF36kgh", "WFK", "WFR",
    # Empuje (todas las unidades)
    "FN", "FNK", "FNlbf", "FNdaN",
    # Flujo secundario / admision CFM56
    "W2AR", "P2", "T25",
    # Presiones de celda
    "PCELLF", "PCELLFpsig", "PCELLR", "PCELLRpsig",
    "FPCELL", "FPCELLkPaa", "RPCELL", "RPCELLkPaa",
    # Condiciones ambientales y de admision
    "T2", "PAMB", "PAMBpsia", "PAMBkPa", "HUM", "RH",
    # Energia de combustible
    "FHV",
)


def _param_relevante(label):
    """True si el nombre del parametro (antes del corchete de unidad) esta en
    la lista del nucleo, o empieza por un prefijo de la lista. Tolerante a
    variantes de nombre."""
    if not label:
        return False
    # 'EGTK [degC]' -> 'EGTK'; 'EGTR2HD' -> 'EGTR2HD'
    nombre = label.split(" ")[0].split("[")[0].strip()
    if nombre in PARAMS_NUCLEO:
        return True
    # Match por prefijo (cubre sufijos de unidad pegados: EGTKdegC, FNlbf...)
    return any(nombre.startswith(p) and len(nombre) <= len(p) + 6
               for p in PARAMS_NUCLEO)


def _outliers_banda(serie, consec, mu, sd, n_sigma):
    """Devuelve lista de dicts con outliers fuera de mu +/- n_sigma*sd."""
    if sd is None or sd == 0:
        return []
    ucl = mu + n_sigma * sd
    lcl = mu - n_sigma * sd
    out = []
    for i, v in enumerate(serie):
        if pd.isna(v):
            continue
        if v > ucl or v < lcl:
            desv_sigma = (v - mu) / sd if sd > 0 else 0
            out.append({
                "tipo": "Outlier banda",
                "reporte": int(consec.iloc[i]),
                "valor": float(v),
                "esperado": float(mu),
                "desviacion": f"{desv_sigma:+.2f}sigma",
                "severidad": _severidad_sigma(abs(desv_sigma)),
                "detalle": f"Fuera de +/-{n_sigma}sigma (LCL={lcl:.2f}, UCL={ucl:.2f})",
            })
    return out


def _cruces_umbral(serie, consec, low, high):
    """Devuelve lista de cruces de umbrales fijos."""
    out = []
    for i, v in enumerate(serie):
        if pd.isna(v):
            continue
        if high is not None and v > high:
            out.append({
                "tipo": "Cruza umbral alto",
                "reporte": int(consec.iloc[i]),
                "valor": float(v),
                "esperado": float(high),
                "desviacion": f"+{v - high:.2f}",
                "severidad": "Alta",
                "detalle": f"Sobre umbral fijo high={high}",
            })
        if low is not None and v < low:
            out.append({
                "tipo": "Cruza umbral bajo",
                "reporte": int(consec.iloc[i]),
                "valor": float(v),
                "esperado": float(low),
                "desviacion": f"{v - low:.2f}",
                "severidad": "Alta",
                "detalle": f"Bajo umbral fijo low={low}",
            })
    return out


def _cusum(serie, consec, mu, sd, k=0.5, h=4.0):
    """Devuelve disparos de CUSUM (primer punto que cruza H, una sola entrada
    por direccion para no saturar)."""
    if sd is None or sd == 0 or len(serie) < 3:
        return []
    z = (serie - mu) / sd
    sh = np.zeros(len(z))
    sl = np.zeros(len(z))
    for i in range(len(z)):
        ph = sh[i - 1] if i > 0 else 0.0
        pl = sl[i - 1] if i > 0 else 0.0
        sh[i] = max(0.0, ph + z.iloc[i] - k)
        sl[i] = min(0.0, pl + z.iloc[i] + k)
    out = []
    # primer disparo al alza
    idx_h = np.argmax(sh > h) if (sh > h).any() else None
    if idx_h is not None:
        out.append({
            "tipo": "CUSUM al alza",
            "reporte": int(consec.iloc[idx_h]),
            "valor": float(serie.iloc[idx_h]),
            "esperado": float(mu),
            "desviacion": f"+{sh[idx_h]:.1f}sigma acum",
            "severidad": "Media",
            "detalle": f"Deriva sostenida al alza (H={h}sigma, k={k}sigma)",
        })
    idx_l = np.argmax(sl < -h) if (sl < -h).any() else None
    if idx_l is not None:
        out.append({
            "tipo": "CUSUM a la baja",
            "reporte": int(consec.iloc[idx_l]),
            "valor": float(serie.iloc[idx_l]),
            "esperado": float(mu),
            "desviacion": f"{sl[idx_l]:.1f}sigma acum",
            "severidad": "Media",
            "detalle": f"Deriva sostenida a la baja (H={h}sigma, k={k}sigma)",
        })
    return out


def _racha(serie, consec, umbral=4):
    """Detecta si la serie termina con racha >= umbral subiendo o bajando."""
    diffs = serie.diff().dropna()
    if len(diffs) == 0:
        return []
    # contar racha final
    cnt_sube = 0
    cnt_baja = 0
    for d in reversed(diffs.tolist()):
        if d > 0:
            if cnt_baja > 0:
                break
            cnt_sube += 1
        elif d < 0:
            if cnt_sube > 0:
                break
            cnt_baja += 1
        else:
            break
    out = []
    if cnt_sube >= umbral:
        out.append({
            "tipo": "Racha al alza",
            "reporte": int(consec.iloc[-1]),
            "valor": float(serie.iloc[-1]),
            "esperado": float(serie.iloc[-cnt_sube - 1]) if cnt_sube + 1 <= len(serie) else None,
            "desviacion": f"+{cnt_sube} reps",
            "severidad": "Media" if cnt_sube < 6 else "Alta",
            "detalle": f"{cnt_sube} reportes consecutivos subiendo",
        })
    if cnt_baja >= umbral:
        out.append({
            "tipo": "Racha a la baja",
            "reporte": int(consec.iloc[-1]),
            "valor": float(serie.iloc[-1]),
            "esperado": float(serie.iloc[-cnt_baja - 1]) if cnt_baja + 1 <= len(serie) else None,
            "desviacion": f"-{cnt_baja} reps",
            "severidad": "Media" if cnt_baja < 6 else "Alta",
            "detalle": f"{cnt_baja} reportes consecutivos bajando",
        })
    return out


def _severidad_sigma(abs_z):
    """Clasifica severidad por magnitud de desviacion (en sigmas)."""
    if abs_z >= 5:
        return "Alta"
    if abs_z >= 4:
        return "Media"
    return "Baja"


def detectar_anomalias(dfv, variant, thresholds_por_clave=None,
                       n_sigma=3, cusum_k=0.5, cusum_h=4.0, racha_umbral=4,
                       baseline_stats=None):
    """
    Recorre todos los parametros relevantes de la variante y devuelve un
    DataFrame con todas las anomalias detectadas.

    dfv: DataFrame ya filtrado por variante (puede traer varios Description).
        Debe tener: param_label, description, consecutivo, value, test_date.
    variant: '1A' / '1B' (se usa para componer la firma del estado).
    thresholds_por_clave: dict {(param_label, description): (low, high)} con
        umbrales fijos definidos por el usuario.
    baseline_stats: dict opcional {(param_label, description): {mu, sd, n, label}}
        para calcular outliers/CUSUM contra una normalidad fija en vez de
        recalcular media/sigma sobre la ventana visible.
    """
    if dfv is None or dfv.empty:
        return pd.DataFrame()

    thresholds_por_clave = thresholds_por_clave or {}
    baseline_stats = baseline_stats or {}
    filas = []

    params = [p for p in dfv["param_label"].dropna().unique() if _param_relevante(p)]
    for p in params:
        for desc in dfv["description"].dropna().unique():
            sub = dfv[(dfv["param_label"] == p) & (dfv["description"] == desc)]
            sub = sub.sort_values("consecutivo")
            if len(sub) < 2:
                continue
            serie = sub["value"].astype(float).reset_index(drop=True)
            consec = sub["consecutivo"].astype(int).reset_index(drop=True)
            base = baseline_stats.get((p, desc))
            if base and base.get("sd") not in (None, 0):
                mu = float(base["mu"])
                sd = float(base["sd"])
                base_label = base.get("label", "baseline")
            else:
                mu = serie.mean()
                sd = serie.std(ddof=1) if len(serie) > 1 else 0.0
                base_label = "ventana visible"

            anomalias = []
            anomalias += _outliers_banda(serie, consec, mu, sd, n_sigma)

            low, high = thresholds_por_clave.get((p, desc), (None, None))
            if low is not None or high is not None:
                anomalias += _cruces_umbral(serie, consec, low, high)

            anomalias += _cusum(serie, consec, mu, sd, k=cusum_k, h=cusum_h)
            anomalias += _racha(serie, consec, umbral=racha_umbral)

            for a in anomalias:
                a["variante"] = variant
                a["parametro"] = p
                a["description"] = desc
                a["baseline"] = base_label
                filas.append(a)

    if not filas:
        return pd.DataFrame()
    cols = ["severidad", "tipo", "parametro", "reporte", "description",
            "valor", "esperado", "desviacion", "detalle", "baseline", "variante"]
    return pd.DataFrame(filas)[cols]
