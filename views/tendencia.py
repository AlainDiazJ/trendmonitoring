#!/usr/bin/env python3
"""views/tendencia.py — pestana Tendencia (grafica principal, bandas,
baseline, regresion, drift/CUSUM, umbrales, eventos y exportacion).

Extraida de app.py sin cambios de logica.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import config_store as cfg
from services.unit_corrections import (
    apply_unit_corrections,
    checkbox_correccion,
    parametro_tiene_correccion,
)

def pos_evento_en_consecutivo(fecha_evento, pts_df):
    """Traduce la fecha de un evento a una posicion en el eje X numerico.

    El eje de tendencia usa el consecutivo real del reporte. Por eso la
    posicion del evento se interpola entre los consecutivos visibles que
    rodean su fecha, en vez de usar indices 0..n-1. Asi la linea queda en la
    misma fecha aunque se filtre el rango visible.

    Devuelve None si no hay fechas validas.
    """
    p = (pts_df.dropna(subset=["fecha", "consecutivo"])
                .drop_duplicates("consecutivo")
                .sort_values("consecutivo")
                .reset_index(drop=True))
    if p.empty:
        return None

    fe = pd.to_datetime(fecha_evento)
    if fe <= p["fecha"].iloc[0]:
        return float(p["consecutivo"].iloc[0]) - 0.5
    if fe >= p["fecha"].iloc[-1]:
        return float(p["consecutivo"].iloc[-1]) + 0.5

    for i in range(len(p) - 1):
        f0, f1 = p["fecha"].iloc[i], p["fecha"].iloc[i + 1]
        if f0 <= fe <= f1:
            c0 = float(p["consecutivo"].iloc[i])
            c1 = float(p["consecutivo"].iloc[i + 1])
            frac = (fe - f0) / (f1 - f0) if f1 != f0 else 0
            return c0 + frac * (c1 - c0)
    return None


def render(filtros):
    fdf = filtros.fdf
    dfv_hist = filtros.dfv_hist
    sel_var = filtros.sel_var
    sel_lbl = filtros.sel_lbl
    sel_desc = filtros.sel_desc

    st.subheader(f"Tendencia - {sel_lbl}")

    # Cada version cruda (EGTK, EGTK3, FN, FNK...) es un parametro individual.
    todos_params = sorted(fdf["param_label"].unique())

    modo_comp = st.checkbox(
        "Modo comparacion: varios parametros con su propio eje Y", value=False,
        help="Compara parametros de magnitudes distintas, sin limite. "
             "Comparten el eje X (consecutivo). Con muchos parametros la "
             "vista Normalizado 0-100% suele ser mas legible.",
    )

    if not modo_comp:
        # --- Un solo parametro ---
        # Si hay un parametro guardado por una vista y existe en la lista, usarlo.
        if "f_param" in st.session_state and st.session_state["f_param"] in todos_params:
            default_idx = todos_params.index(st.session_state["f_param"])
        else:
            default_idx = next((i for i, p in enumerate(todos_params)
                                if p.startswith("EGTK ") or p.startswith("EGTR2 ")), 0)
        p_sel = st.selectbox("Parametro", todos_params, index=default_idx, key="f_param")

        sub = fdf[fdf["param_label"] == p_sel].copy().sort_values("consecutivo")

        if parametro_tiene_correccion(sel_var, p_sel):
            if checkbox_correccion(key="unit_corr_tendencia"):
                apply_unit_corrections(sub)
                apply_unit_corrections(dfv_hist)

        # eje X solo con consecutivos activos
        orden = sorted(sub["consecutivo"].unique())

        # ---- Controles de vista en la BARRA LATERAL (plegables) ----
        with st.sidebar.expander("Bandas / baseline", expanded=False):
            mostrar_bandas = st.checkbox("Mostrar bandas (+/-Nsigma)", value=False)
            n_sigma = st.slider("N (sigma)", min_value=1, max_value=6, value=3, step=1)
            baseline_modo = st.selectbox(
                "Baseline estadistico",
                ["Historico completo", "Visible", "Rango manual", "Baseline aprobado"],
                index=0,
                help="Define de donde salen media y sigma. La ventana visible solo "
                     "controla lo que ves. 'Baseline aprobado' usa media/sigma "
                     "congeladas de un perfil guardado.",
                key="baseline_modo_tend",
            )
            baseline_fechas = None
            if baseline_modo == "Rango manual":
                _bf = dfv_hist["fecha"].dropna()
                if not _bf.empty:
                    baseline_fechas = st.date_input(
                        "Fechas baseline",
                        value=(_bf.min().date(), _bf.max().date()),
                        min_value=_bf.min().date(),
                        max_value=_bf.max().date(),
                        key="baseline_fechas_tend",
                    )

            baseline_perfil = None
            if baseline_modo == "Baseline aprobado":
                _desc_perfil = sel_desc[0] if len(sel_desc) == 1 else None
                perfiles = cfg.list_baseline_profiles(
                    variant=sel_var, param_label=p_sel, description=_desc_perfil,
                )
                if not perfiles:
                    st.caption(
                        "No hay baselines aprobados para este parametro"
                        + ("" if _desc_perfil else " (filtra a UN solo Description)")
                        + ". Se usa historico completo. Guarda uno abajo."
                    )
                else:
                    _nombre_perfil = st.selectbox(
                        "Perfil aprobado", [p["name"] for p in perfiles],
                        key="baseline_perfil_tend",
                    )
                    baseline_perfil = next(
                        p for p in perfiles if p["name"] == _nombre_perfil
                    )
                    st.caption(
                        f"media {baseline_perfil['mean']:.3f} - "
                        f"sigma {baseline_perfil['sigma']:.3f} - "
                        f"{baseline_perfil['n_points']} puntos - "
                        f"{baseline_perfil['date_from']} a {baseline_perfil['date_to']} - "
                        f"aprobado por {baseline_perfil['approved_by'] or '(sin nombre)'}"
                    )
                    if baseline_perfil["notes"]:
                        st.caption(f"Nota: {baseline_perfil['notes']}")
                    if baseline_perfil["sigma"] is None or baseline_perfil["sigma"] <= 0:
                        st.error(
                            "Este baseline tiene sigma invalida (<= 0): se "
                            "IGNORA y las bandas usan historico completo. "
                            "Revisalo o borralo."
                        )
                    elif (baseline_perfil["n_points"] or 0) < 10:
                        st.warning(
                            f"Baseline con solo {baseline_perfil['n_points']} "
                            "punto(s): media/sigma poco robustas. Usalo con "
                            "reserva o aprueba uno con mas historial."
                        )
                    if st.button("Borrar este baseline", key="baseline_perfil_del"):
                        cfg.delete_baseline_profile(baseline_perfil["id"])
                        st.rerun()

        with st.sidebar.expander("Tendencia / regresion", expanded=False):
            mostrar_reg = st.checkbox("Linea de tendencia (regresion)", value=False)
            proy = st.slider("Proyectar N reportes adelante", 0, 10, 3, step=1,
                             help="Extiende la recta de regresion para anticipar deriva.")

        with st.sidebar.expander("Deteccion de drift", expanded=False):
            mostrar_drift = st.checkbox("Activar deteccion de drift", value=False)
            ventana_mm = st.slider("Ventana media movil", 2, 12, 5, step=1)
            cusum_k = st.slider("CUSUM: holgura k (en sigma)", 0.0, 2.0, 0.5, step=0.1,
                                help="Margen que se ignora antes de acumular. Tipico 0.5 sigma.")
            cusum_h = st.slider("CUSUM: limite H (en sigma)", 2.0, 8.0, 4.0, step=0.5,
                                help="Umbral de alarma de la suma acumulada. Tipico 4-5 sigma.")

        # un solo Description activo es requisito para bandas/umbrales con sentido
        un_solo_desc = len(sel_desc) == 1

        def obtener_base_calc(param_label, desc, visible_df):
            if baseline_modo == "Visible":
                return visible_df, "visible"
            base = dfv_hist[
                (dfv_hist["param_label"] == param_label)
                & (dfv_hist["description"] == desc)
            ].copy()
            if baseline_modo == "Rango manual" and isinstance(baseline_fechas, tuple) and len(baseline_fechas) == 2:
                d0b, d1b = baseline_fechas
                base = base[(base["fecha"].dt.date >= d0b) & (base["fecha"].dt.date <= d1b)]
                return base, f"rango manual {d0b.isoformat()} a {d1b.isoformat()}"
            return base, "historico completo"

        def stats_baseline(param_label, desc, visible_df):
            """Devuelve (media, sigma, n, label) segun el baseline activo,
            o None si no hay suficientes datos.

            Con un baseline aprobado se usan los valores CONGELADOS del
            perfil (no se recalculan): las bandas quedan ancladas a lo que
            se aprobo, aunque cambien filtros u ocultamientos. Sin perfil
            seleccionado, cae a historico completo.
            """
            if baseline_modo == "Baseline aprobado" and baseline_perfil is not None:
                # sigma <= 0 seria un baseline degenerado (bandas de ancho
                # cero -> todo marcado como outlier); se ignora y se cae al
                # historico. La UI ya avisa con st.error al seleccionarlo.
                if (baseline_perfil["mean"] is not None
                        and baseline_perfil["sigma"] is not None
                        and baseline_perfil["sigma"] > 0):
                    return (
                        float(baseline_perfil["mean"]),
                        float(baseline_perfil["sigma"]),
                        int(baseline_perfil["n_points"] or 0),
                        f"baseline aprobado: {baseline_perfil['name']}",
                    )
            base, label = obtener_base_calc(param_label, desc, visible_df)
            vals = base["value"].astype(float).dropna()
            if len(vals) < 2:
                return None
            return float(vals.mean()), float(vals.std(ddof=1)), len(vals), label

        # ---- Guardar la seleccion actual como baseline aprobado ----
        with st.sidebar.expander("Guardar baseline aprobado", expanded=False):
            if not un_solo_desc:
                st.caption("Filtra a UN solo Description para guardar un baseline.")
            else:
                base_bp, label_bp = obtener_base_calc(p_sel, sel_desc[0], sub)
                vals_bp = base_bp["value"].astype(float).dropna()
                fechas_bp = base_bp["fecha"].dropna()
                if len(vals_bp) < 2 or fechas_bp.empty:
                    st.caption("No hay suficientes puntos (minimo 2, con fecha) "
                               "en la seleccion actual de baseline.")
                else:
                    media_bp = float(vals_bp.mean())
                    sigma_bp = float(vals_bp.std(ddof=1))
                    d0_bp = fechas_bp.min().date().isoformat()
                    d1_bp = fechas_bp.max().date().isoformat()
                    st.caption(
                        f"Se congelara la base actual ({label_bp}): "
                        f"media {media_bp:.3f}, sigma {sigma_bp:.3f}, "
                        f"{len(vals_bp)} puntos, {d0_bp} a {d1_bp}."
                    )
                    if len(vals_bp) < 10:
                        st.warning(
                            f"Solo {len(vals_bp)} punto(s) en la base: el "
                            "baseline quedara poco robusto. Se puede guardar, "
                            "pero considera un rango con mas historial."
                        )
                    if sigma_bp <= 0:
                        st.warning(
                            "Sigma de la base actual es 0 (todos los valores "
                            "identicos): las bandas de este baseline no seran "
                            "utilizables."
                        )
                    nombre_bp = st.text_input(
                        "Nombre del baseline",
                        value=f"Baseline {p_sel.split(' ')[0]} {sel_desc[0]} {sel_lbl} {d1_bp[:4]}",
                        key="bp_name",
                    )
                    aprobado_por_bp = st.text_input("Aprobado por", key="bp_by")
                    notas_bp = st.text_area("Comentario", key="bp_notes", height=68,
                                            placeholder="Ej: periodo estable antes de recalibracion")
                    if st.button("Guardar baseline aprobado", key="bp_save"):
                        if nombre_bp.strip():
                            cfg.save_baseline_profile(
                                nombre_bp.strip(), sel_var, p_sel, sel_desc[0],
                                d0_bp, d1_bp, media_bp, sigma_bp, len(vals_bp),
                                approved_by=aprobado_por_bp.strip(),
                                notes=notas_bp.strip(),
                            )
                            st.success("Baseline aprobado guardado.")
                            st.rerun()
                        else:
                            st.warning("El nombre es obligatorio.")

        # ---- Umbrales fijos (limites manuales) por variante+parametro+description ----
        with st.sidebar.expander("Umbrales fijos (limites)", expanded=False):
            if not un_solo_desc:
                st.caption("Filtra a UN solo Description para definir o ver umbrales.")
                low_fijo = high_fijo = None
                mostrar_umbral = False
            else:
                desc_actual = sel_desc[0]
                low_guardado, high_guardado = cfg.get_threshold(sel_var, p_sel, desc_actual)
                st.caption(f"Para {p_sel} - {desc_actual}")
                mostrar_umbral = st.checkbox("Aplicar umbrales fijos", value=False)
                c_lo, c_hi = st.columns(2)
                with c_lo:
                    low_in = st.number_input(
                        "Limite inferior", value=float(low_guardado) if low_guardado is not None else 0.0,
                        format="%.3f", key="low_fijo")
                    usar_low = st.checkbox("usar inf.", value=low_guardado is not None, key="ulow")
                with c_hi:
                    high_in = st.number_input(
                        "Limite superior", value=float(high_guardado) if high_guardado is not None else 0.0,
                        format="%.3f", key="high_fijo")
                    usar_high = st.checkbox("usar sup.", value=high_guardado is not None, key="uhigh")
                low_fijo = low_in if usar_low else None
                high_fijo = high_in if usar_high else None
                cbtn1, cbtn2 = st.columns(2)
                with cbtn1:
                    if st.button("Guardar umbral"):
                        cfg.set_threshold(sel_var, p_sel, desc_actual, low_fijo, high_fijo)
                        st.success("Guardado.")
                with cbtn2:
                    if st.button("Borrar umbral"):
                        cfg.delete_threshold(sel_var, p_sel, desc_actual)
                        st.success("Borrado.")

        fig = px.line(
            sub, x="consecutivo", y="value", markers=True,
            labels={"value": p_sel, "consecutivo": "No de reporte (consecutivo)"},
            hover_data={"description": True, "test_date": True, "source_file": True},
            title=f"{p_sel} - {sel_lbl}",
        )
        regresion_export = None
        media_movil_export = None
        eventos_export = []

        if mostrar_bandas:
            if not un_solo_desc:
                st.info("Para mostrar bandas, filtra a UN solo Description en la barra "
                        "lateral (mezclar ratings distintos da una media sin sentido).")
            else:
                # media/sigma desde el baseline elegido (congeladas si es aprobado)
                stats_b = stats_baseline(p_sel, sel_desc[0], sub)
                if stats_b is not None:
                    media, sigma, n_base, baseline_label = stats_b
                    ucl = media + n_sigma * sigma
                    lcl = media - n_sigma * sigma

                    # lineas horizontales: media y limites
                    fig.add_hline(y=media, line_dash="solid", line_color="green",
                                  annotation_text="media", annotation_position="right")
                    fig.add_hline(y=ucl, line_dash="dash", line_color="red",
                                  annotation_text=f"+{n_sigma}sigma", annotation_position="right")
                    fig.add_hline(y=lcl, line_dash="dash", line_color="red",
                                  annotation_text=f"-{n_sigma}sigma", annotation_position="right")

                    # resaltar puntos fuera de banda
                    fuera = sub[(sub["value"] > ucl) | (sub["value"] < lcl)]
                    if not fuera.empty:
                        import plotly.graph_objects as go
                        fig.add_trace(go.Scatter(
                            x=fuera["consecutivo"], y=fuera["value"], mode="markers",
                            marker=dict(color="red", size=14, symbol="x"),
                            name="Fuera de banda",
                            customdata=fuera[["description", "test_date", "source_file"]],
                            hovertemplate="FUERA DE BANDA<br>consec %{x}<br>valor %{y}<br>"
                                          "%{customdata[0]}<br>fecha %{customdata[1]}<br>"
                                          "archivo %{customdata[2]}<extra></extra>",
                        ))

                    st.caption(
                        f"Media = {media:.3f} - sigma = {sigma:.3f} - "
                        f"+/-{n_sigma}sigma -> [{lcl:.3f}, {ucl:.3f}] - "
                        f"base: {baseline_label} "
                        f"({n_base} puntos) - "
                        f"{len(fuera) if un_solo_desc else 0} fuera de banda"
                    )
                else:
                    st.info("No hay suficientes puntos (a2) para calcular las bandas.")

        # ---- Linea de tendencia / regresion ----
        if mostrar_reg:
            import numpy as np
            import plotly.graph_objects as go
            sreg = sub.dropna(subset=["value"]).sort_values("consecutivo")
            if len(sreg) >= 2:
                x = sreg["consecutivo"].astype(float).values
                y = sreg["value"].astype(float).values
                pendiente, interseccion = np.polyfit(x, y, 1)
                x_fin = x.max() + proy
                x_line = np.array([x.min(), x_fin])
                y_line = pendiente * x_line + interseccion
                fig.add_trace(go.Scatter(
                    x=x_line, y=y_line, mode="lines",
                    line=dict(color="orange", dash="dot", width=2),
                    name=f"Tendencia (pend={pendiente:+.3f}/reporte)",
                ))
                regresion_export = {
                    "x": x_line.tolist(),
                    "y": y_line.tolist(),
                    "pendiente": float(pendiente),
                    "interseccion": float(interseccion),
                    "proy": int(proy),
                    "x_min": float(x.min()),
                    "x_max": float(x_fin),
                }

                # marcar zona de proyeccion con un area
                if proy > 0:
                    st.caption(
                        f"Pendiente = {pendiente:+.4f} por reporte - "
                        f"interseccion = {interseccion:.3f} - "
                        f"proyeccion a +{proy}: {pendiente * x_fin + interseccion:.3f}"
                    )
                else:
                    st.caption(f"Pendiente = {pendiente:+.4f} por reporte - "
                               f"interseccion = {interseccion:.3f}")
            else:
                st.info("No hay suficientes puntos (a2) para la regresion.")

        # ---- Umbrales fijos: lineas en la grafica ----
        cruces_umbral = pd.DataFrame()
        if un_solo_desc and mostrar_umbral and (low_fijo is not None or high_fijo is not None):
            if high_fijo is not None:
                fig.add_hline(y=high_fijo, line_dash="dashdot", line_color="purple",
                              annotation_text=f"limite sup {high_fijo:.1f}",
                              annotation_position="left")
            if low_fijo is not None:
                fig.add_hline(y=low_fijo, line_dash="dashdot", line_color="purple",
                              annotation_text=f"limite inf {low_fijo:.1f}",
                              annotation_position="left")
            # puntos que cruzan el umbral fijo
            cond = pd.Series(False, index=sub.index)
            if high_fijo is not None:
                cond = cond | (sub["value"] > high_fijo)
            if low_fijo is not None:
                cond = cond | (sub["value"] < low_fijo)
            cruces_umbral = sub[cond].copy()
            if not cruces_umbral.empty:
                import plotly.graph_objects as go
                fig.add_trace(go.Scatter(
                    x=cruces_umbral["consecutivo"], y=cruces_umbral["value"],
                    mode="markers", marker=dict(color="purple", size=14, symbol="diamond"),
                    name="Cruza umbral fijo",
                    customdata=cruces_umbral[["description", "test_date", "source_file"]],
                    hovertemplate="CRUZA UMBRAL<br>consec %{x}<br>valor %{y}<br>"
                                  "%{customdata[0]}<br>fecha %{customdata[1]}<br>"
                                  "archivo %{customdata[2]}<extra></extra>",
                ))

        # ---- Drift: media movil sobre la grafica ----
        if mostrar_drift:
            import plotly.graph_objects as go
            sdr = sub.sort_values("consecutivo")
            mm = sdr["value"].rolling(window=ventana_mm, min_periods=1).mean()
            fig.add_trace(go.Scatter(
                x=sdr["consecutivo"], y=mm, mode="lines",
                line=dict(color="darkorange", width=2.5),
                name=f"Media movil ({ventana_mm})",
                customdata=sdr[["description", "test_date", "source_file"]],
                hovertemplate="reporte %{x}<br>media movil %{y:.3f}<br>"
                              "%{customdata[0]}<br>fecha %{customdata[1]}<br>"
                              "archivo %{customdata[2]}<extra></extra>",
            ))
            media_movil_export = {
                "x": sdr["consecutivo"].astype(float).tolist(),
                "y": mm.astype(float).tolist(),
                "ventana": int(ventana_mm),
            }

        # ---- Eventos: lineas verticales con etiqueta ----
        mostrar_eventos = st.checkbox(
            "Mostrar eventos en la grafica", value=False,
            help="Marca actualizaciones, recalibraciones, etc. en su posicion temporal.",
        )
        if mostrar_eventos:
            eventos = cfg.list_events(scope=sel_var)
            # posiciones de los reportes visibles (para interpolar)
            pts_vis = sub[["consecutivo", "fecha"]].drop_duplicates()
            n_dibujados = 0
            for ev in eventos:
                xcoord = pos_evento_en_consecutivo(ev["event_date"], pts_vis)
                if xcoord is None:
                    continue
                # solo dibujar si cae dentro del rango visible (con margen 0.5)
                if xcoord < min(orden) - 0.5 or xcoord > max(orden) + 0.5:
                    continue
                fig.add_vline(x=xcoord, line_width=2, line_dash="dot", line_color="teal")
                fig.add_annotation(x=xcoord, yref="paper", y=1.0, showarrow=False,
                                   text=ev["name"], textangle=-90,
                                   font=dict(color="teal", size=11),
                                   xanchor="left", yanchor="top")
                eventos_export.append((float(xcoord), ev["name"], ev["event_date"]))
                n_dibujados += 1
            if n_dibujados == 0:
                st.caption("No hay eventos dentro del rango visible para esta variante.")

        fig.update_layout(height=520)
        st.plotly_chart(fig, use_container_width=True)

        # ---- Drift: CUSUM + alerta de racha (debajo de la grafica) ----
        if mostrar_drift:
            import numpy as np
            import plotly.graph_objects as go
            sdr = sub.sort_values("consecutivo")
            serie = sdr["value"].astype(float).reset_index(drop=True)
            consec = sdr["consecutivo"].astype(int).reset_index(drop=True)

            if len(serie) >= 3:
                # base de media/sigma: baseline elegido si hay un solo Description
                # (congelada si es un baseline aprobado)
                stats_d = stats_baseline(p_sel, sel_desc[0], sub) if un_solo_desc else None
                if stats_d is not None:
                    mu, sd, _n_d, _lbl_d = stats_d
                else:
                    mu = serie.mean()
                    sd = serie.std(ddof=1)
                sd = sd if sd and sd > 0 else 1.0

                # CUSUM tabular (acumula desviaciones normalizadas)
                k = cusum_k  # holgura en sigmas
                h = cusum_h  # limite en sigmas
                z = (serie - mu) / sd
                sh = np.zeros(len(z))  # suma alta (detecta subidas)
                sl = np.zeros(len(z))  # suma baja (detecta bajadas)
                for i in range(len(z)):
                    prev_h = sh[i-1] if i > 0 else 0.0
                    prev_l = sl[i-1] if i > 0 else 0.0
                    sh[i] = max(0.0, prev_h + z[i] - k)
                    sl[i] = min(0.0, prev_l + z[i] + k)

                figd = go.Figure()
                xcat = consec.astype(str)
                cusum_hover = sdr[["test_date", "source_file"]].astype(str).to_numpy()
                figd.add_trace(go.Scatter(
                    x=xcat, y=sh, mode="lines+markers",
                    name="CUSUM+ (subidas)", line=dict(color="crimson"),
                    customdata=cusum_hover,
                    hovertemplate="reporte %{x}<br>CUSUM+ %{y:.3f}<br>"
                                  "fecha %{customdata[0]}<br>archivo %{customdata[1]}"
                                  "<extra></extra>",
                ))
                figd.add_trace(go.Scatter(
                    x=xcat, y=sl, mode="lines+markers",
                    name="CUSUM- (bajadas)", line=dict(color="royalblue"),
                    customdata=cusum_hover,
                    hovertemplate="reporte %{x}<br>CUSUM- %{y:.3f}<br>"
                                  "fecha %{customdata[0]}<br>archivo %{customdata[1]}"
                                  "<extra></extra>",
                ))
                figd.add_hline(y=h, line_dash="dash", line_color="crimson")
                figd.add_hline(y=-h, line_dash="dash", line_color="royalblue")
                figd.update_layout(height=300, title="CUSUM (suma acumulada de desviaciones, en sigma)",
                                   xaxis_title="No de reporte", yaxis_title="CUSUM (sigma)",
                                   margin=dict(t=40))
                st.plotly_chart(figd, use_container_width=True)

                # alarmas CUSUM
                alarma_sube = consec[sh > h].tolist()
                alarma_baja = consec[sl < -h].tolist()
                if alarma_sube:
                    st.warning(f"as  CUSUM detecta DERIVA AL ALZA. Primer reporte que dispara: "
                               f"{alarma_sube[0]} (limite H={h}sigma).")
                if alarma_baja:
                    st.warning(f"as  CUSUM detecta DERIVA A LA BAJA. Primer reporte que dispara: "
                               f"{alarma_baja[0]} (limite H={h}sigma).")
                if not alarma_sube and not alarma_baja:
                    st.success("CUSUM no detecta deriva sostenida con los parametros actuales.")

                # ---- Alerta de racha (N reportes consecutivos subiendo/bajando) ----
                diffs = serie.diff().dropna()
                def racha_final(signo):
                    cnt = 0
                    for d in reversed(diffs.tolist()):
                        if (signo > 0 and d > 0) or (signo < 0 and d < 0):
                            cnt += 1
                        else:
                            break
                    return cnt
                r_sube = racha_final(1)
                r_baja = racha_final(-1)
                UMBRAL_RACHA = 4
                if r_sube >= UMBRAL_RACHA:
                    st.warning(f"as  Racha: el parametro lleva {r_sube} reportes consecutivos SUBIENDO.")
                elif r_baja >= UMBRAL_RACHA:
                    st.warning(f"as  Racha: el parametro lleva {r_baja} reportes consecutivos BAJANDO.")
                else:
                    st.caption(f"Racha actual: {r_sube} subiendo / {r_baja} bajando "
                               f"(alerta a partir de {UMBRAL_RACHA}).")
            else:
                st.info("Se necesitan al menos 3 puntos para la deteccion de drift.")

        # ---- Alerta visual + tabla de cruces de umbral fijo ----
        if un_solo_desc and mostrar_umbral and (low_fijo is not None or high_fijo is not None):
            if not cruces_umbral.empty:
                st.error(f"as  {len(cruces_umbral)} punto(s) cruzan el umbral fijo definido.")
                tcr = cruces_umbral[["consecutivo", "description", "test_date", "value"]].copy()
                tcr = tcr.rename(columns={"consecutivo": "Reporte", "description": "Description",
                                          "test_date": "Fecha", "value": "Valor"})
                st.dataframe(tcr.sort_values("Reporte"), use_container_width=True, hide_index=True)
            else:
                st.success("Ningun punto cruza el umbral fijo con los filtros actuales.")

        # ---- Deteccion automatica de outliers (lista) ----
        if mostrar_bandas and un_solo_desc:
            # recalcular base igual que arriba para listar
            stats_o = stats_baseline(p_sel, sel_desc[0], sub)
            if stats_o is not None:
                media, sigma, _n_o, baseline_label = stats_o
                ucl = media + n_sigma * sigma
                lcl = media - n_sigma * sigma
                fuera = sub[(sub["value"] > ucl) | (sub["value"] < lcl)].copy()
                st.markdown(f"**Outliers detectados (fuera de +/-{n_sigma}sigma): {len(fuera)}**")
                if not fuera.empty:
                    fuera["desviacion_sigma"] = (fuera["value"] - media) / (sigma if sigma > 0 else float("nan"))
                    tabla = fuera[["consecutivo", "description", "test_date",
                                   "value", "desviacion_sigma"]].copy()
                    tabla = tabla.rename(columns={
                        "consecutivo": "Reporte", "description": "Description",
                        "test_date": "Fecha", "value": "Valor",
                        "desviacion_sigma": "Desv (sigma)"})
                    tabla["Desv (sigma)"] = tabla["Desv (sigma)"].round(2)
                    st.dataframe(tabla.sort_values("Reporte"),
                                 use_container_width=True, hide_index=True)
                else:
                    st.caption("Ningun punto fuera de banda con los filtros actuales.")

        # ---- Exportar reporte (Excel / PDF) ----
        st.markdown("---")
        st.markdown("**Exportar reporte**")
        # reunir estadisticas actuales (si hay bandas calculadas)
        stats_export = {}
        stats_grafica = None
        if un_solo_desc:
            stats_e = stats_baseline(p_sel, sel_desc[0], sub)
            if stats_e is not None:
                media_e, sigma_e, n_e, baseline_label_export = stats_e
                ucl_e = media_e + n_sigma * sigma_e
                lcl_e = media_e - n_sigma * sigma_e
                fuera_e = sub[(sub["value"] > ucl_e) | (sub["value"] < lcl_e)]
                stats_export = {
                    "Media": round(media_e, 4), "Sigma": round(sigma_e, 4),
                    f"+{n_sigma}sigma (UCL)": round(ucl_e, 4),
                    f"-{n_sigma}sigma (LCL)": round(lcl_e, 4),
                    "N puntos (base)": n_e,
                    "Outliers (visibles)": len(fuera_e),
                    "Base de calculo": baseline_label_export,
                }
                stats_grafica = {"media": media_e, "ucl": ucl_e, "lcl": lcl_e,
                                 "n_sigma": n_sigma}

        if regresion_export:
            stats_export.update({
                "Regresion pendiente por reporte": round(regresion_export["pendiente"], 6),
                "Regresion interseccion": round(regresion_export["interseccion"], 6),
                "Regresion proyeccion reportes": regresion_export["proy"],
            })

        if st.session_state.get("f_fecha_modo", "Historico completo") == "Historico completo":
            rango_fechas_txt = "Historico completo"
        else:
            _fechas_export = st.session_state.get("f_fechas")
            if isinstance(_fechas_export, (tuple, list)) and len(_fechas_export) == 2:
                rango_fechas_txt = f"{_fechas_export[0].isoformat()} a {_fechas_export[1].isoformat()}"
            else:
                rango_fechas_txt = "Historico visible completo"

        desc_txt = "; ".join(sel_desc) if sel_desc else "(ninguna)"
        baseline_export_txt = baseline_modo
        if baseline_modo == "Rango manual" and isinstance(baseline_fechas, tuple) and len(baseline_fechas) == 2:
            baseline_export_txt = (
                f"Rango manual {baseline_fechas[0].isoformat()} a {baseline_fechas[1].isoformat()}"
            )
        elif baseline_modo == "Baseline aprobado" and baseline_perfil is not None:
            baseline_export_txt = (
                f"Baseline aprobado '{baseline_perfil['name']}' "
                f"({baseline_perfil['date_from']} a {baseline_perfil['date_to']}, "
                f"aprobado por {baseline_perfil['approved_by'] or 'sin nombre'})"
            )
        eventos_txt = (
            "; ".join(f"{ev[2]} - {ev[1]}" for ev in eventos_export)
            if eventos_export else "Ninguno dibujado"
        )
        umbrales_export = None
        if un_solo_desc and mostrar_umbral and (low_fijo is not None or high_fijo is not None):
            umbrales_export = {"low": low_fijo, "high": high_fijo}

        config_export = {
            "Variante de motor": sel_lbl,
            "Parametro": p_sel,
            "Descriptions seleccionadas": desc_txt,
            "Rango de fechas": rango_fechas_txt,
            "Puntos visibles en grafica": sub["consecutivo"].nunique(),
            "Rango de reportes visible": f"{min(orden)} a {max(orden)}" if orden else "Sin datos",
            "Modo comparacion": "No",
            "Bandas de control visibles": "Si" if mostrar_bandas else "No",
            "N sigma": n_sigma,
            "Base de calculo de bandas": baseline_export_txt,
            "Umbrales fijos visibles": "Si" if (un_solo_desc and mostrar_umbral) else "No",
            "Limite inferior fijo": low_fijo if (un_solo_desc and low_fijo is not None) else "No usado",
            "Limite superior fijo": high_fijo if (un_solo_desc and high_fijo is not None) else "No usado",
            "Regresion visible": "Si" if mostrar_reg else "No",
            "Regresion proyectar N reportes": proy,
            "Deteccion de drift visible": "Si" if mostrar_drift else "No",
            "Ventana media movil": ventana_mm,
            "CUSUM k (sigma)": cusum_k,
            "CUSUM H (sigma)": cusum_h,
            "Eventos visibles": "Si" if mostrar_eventos else "No",
            "Eventos dibujados": eventos_txt,
        }

        meta_export = {
            "Variante": sel_lbl,
            "Parametro": p_sel,
            "Description": sel_desc[0] if un_solo_desc else f"varios ({len(sel_desc)})",
            "Rango de fechas": rango_fechas_txt,
            "Generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "Puntos en reporte": sub["consecutivo"].nunique(),
        }
        datos_export = sub[["consecutivo", "description", "test_date",
                            "value", "unit"]].sort_values("consecutivo").rename(
            columns={"consecutivo": "Reporte", "description": "Description",
                     "test_date": "Fecha", "value": "Valor", "unit": "Unidad"})

        import report_export as rx
        try:
            png_bytes = rx.grafica_tendencia_png(
                sub, p_sel, sel_lbl,
                stats_grafica if mostrar_bandas else None,
                eventos_pos=eventos_export if mostrar_eventos else None,
                regresion=regresion_export if mostrar_reg else None,
                umbrales=umbrales_export,
                media_movil=media_movil_export if mostrar_drift else None,
            )
        except Exception as e:
            png_bytes = None
            st.caption(f"No se pudo generar la grafica para exportar: {e}")

        cexp1, cexp2 = st.columns(2)
        with cexp1:
            try:
                xlsx_bytes = rx.exportar_excel(
                    datos_export, stats_export, meta_export, config_export, png_bytes
                )
                st.download_button(
                    "Descargar Excel", data=xlsx_bytes,
                    file_name=f"reporte_{sel_var}_{p_sel.split(' ')[0]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as e:
                st.caption(f"No se pudo generar Excel: {e}")
        with cexp2:
            try:
                pdf_bytes = rx.exportar_pdf(datos_export, stats_export, meta_export,
                                            png_bytes, config_export)
                st.download_button(
                    "Descargar PDF", data=pdf_bytes,
                    file_name=f"reporte_{sel_var}_{p_sel.split(' ')[0]}.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.caption(f"No se pudo generar PDF: {e}")

    else:
        # --- Varios parametros, cada uno con su eje Y ---
        sel_multi = st.multiselect(
            "Parametros a comparar", todos_params,
            default=todos_params[:2], key="tend_multi",
            help="Sin limite de cantidad. Con muchos parametros de magnitudes "
                 "distintas la vista Normalizado 0-100% suele ser mas legible "
                 "que Ejes Y separados.",
        )
        vista = st.radio(
            "Escala", ["Ejes Y separados (valores reales)", "Normalizado 0-100%"],
            horizontal=True,
        )

        if not sel_multi:
            st.info("Selecciona al menos un parametro.")
        else:
            import plotly.graph_objects as go
            # consecutivos activos (union de los parametros elegidos)
            base = fdf[fdf["param_label"].isin(sel_multi)]
            orden = sorted(base["consecutivo"].unique())
            xcat = [str(c) for c in orden]

            fig = go.Figure()
            colores = px.colors.qualitative.Plotly

            if vista.startswith("Normalizado"):
                # todos en un solo eje, escalados a 0-100%
                for i, p in enumerate(sel_multi):
                    s = base[base["param_label"] == p].sort_values("consecutivo")
                    v = s["value"].astype(float)
                    rng = v.max() - v.min()
                    vn = (v - v.min()) / rng * 100 if rng != 0 else v * 0 + 50
                    fig.add_trace(go.Scatter(
                        x=s["consecutivo"].astype(str), y=vn, mode="lines+markers",
                        name=p, line=dict(color=colores[i % len(colores)]),
                        customdata=s[["description", "value", "test_date", "source_file"]],
                        hovertemplate=("%{x}<br>" + p + "<br>real=%{customdata[1]}"
                                       "<br>%{customdata[0]}<br>fecha %{customdata[2]}"
                                       "<br>archivo %{customdata[3]}<extra></extra>"),
                    ))
                fig.update_yaxes(title_text="Valor normalizado (0-100%)")
                fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=xcat))
            else:
                # cada parametro su propio eje Y. Los ejes extra se apilan a la
                # derecha: el dominio del eje X se encoge para dejarles una
                # banda propia fuera del area de trazado (si no, sus ticks
                # quedan encimados sobre los datos).
                n_right = len(sel_multi) - 1
                step = 0.055
                dom_right = max(0.5, 1 - step * n_right)
                for i, p in enumerate(sel_multi):
                    s = base[base["param_label"] == p].sort_values("consecutivo")
                    axis_id = "y" if i == 0 else f"y{i+1}"
                    fig.add_trace(go.Scatter(
                        x=s["consecutivo"].astype(str), y=s["value"], mode="lines+markers",
                        name=p, yaxis=axis_id, line=dict(color=colores[i % len(colores)]),
                        customdata=s[["description", "test_date", "source_file"]],
                        hovertemplate=("%{x}<br>" + p + "=%{y}<br>%{customdata[0]}"
                                       "<br>fecha %{customdata[1]}"
                                       "<br>archivo %{customdata[2]}<extra></extra>"),
                    ))
                # configurar ejes Y multiples
                layout_axes = {"xaxis": dict(title="No de reporte (consecutivo)",
                                             categoryorder="array", categoryarray=xcat,
                                             domain=[0, dom_right])}
                for i, p in enumerate(sel_multi):
                    col = colores[i % len(colores)]
                    if i == 0:
                        layout_axes["yaxis"] = dict(
                            title=dict(text=p, font=dict(color=col)),
                            tickfont=dict(color=col))
                    else:
                        pos = dom_right + (i - 1) * step
                        layout_axes[f"yaxis{i+1}"] = dict(
                            title=dict(text=p, font=dict(color=col)),
                            overlaying="y", side="right", position=pos,
                            tickfont=dict(color=col),
                            anchor="free", automargin=True,
                        )
                fig.update_layout(**layout_axes)

            fig.update_layout(
                height=560, legend=dict(orientation="h", y=1.12),
                margin=dict(l=60, r=min(350, 80 + 45 * (len(sel_multi) - 1)), t=60, b=60),
            )
            st.plotly_chart(fig, use_container_width=True)
            if vista.startswith("Ejes") and len(sel_multi) > 2:
                st.caption("Con mas de 2 parametros los ejes Y se apilan a la derecha.")
            if vista.startswith("Ejes") and len(sel_multi) > 8:
                st.warning("Con mas de 8 parametros la vista de ejes separados es "
                           "dificil de leer; considera Normalizado 0-100%.")

            # ---- Exportar Excel (grafica + tabla de datos) ----
            st.markdown("---")
            from services.comparison_export import build_comparison_table
            tabla_comp = build_comparison_table(base, sel_multi)

            if st.session_state.get("f_fecha_modo", "Historico completo") == "Historico completo":
                _rango_comp_txt = "Historico completo"
            else:
                _f = st.session_state.get("f_fechas")
                _rango_comp_txt = (
                    f"{_f[0].isoformat()} a {_f[1].isoformat()}"
                    if isinstance(_f, (tuple, list)) and len(_f) == 2
                    else "Historico visible completo"
                )
            meta_comp = {
                "Variante": sel_lbl,
                "Parametros comparados": ", ".join(sel_multi),
                "Rango de fechas": _rango_comp_txt,
                "Puntos en reporte": len(orden),
                "Generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                "Nota": "La grafica exportada esta normalizada 0-100% para "
                        "legibilidad; los valores reales estan en la tabla.",
            }
            config_comp = {
                "Variante de motor": sel_lbl,
                "Parametros a comparar": ", ".join(sel_multi),
                "Escala en pantalla": vista,
                "Rango de fechas": _rango_comp_txt,
            }
            stats_comp = {}
            for p in sel_multi:
                vals = base.loc[base["param_label"] == p, "value"].astype(float)
                if not vals.empty:
                    stats_comp[f"{p} (min / media / max)"] = (
                        f"{vals.min():.3f} / {vals.mean():.3f} / {vals.max():.3f}"
                    )

            st.caption(
                "La grafica exportada va normalizada 0-100% para que se puedan "
                "leer todos los parametros juntos; los valores reales estan en "
                "la tabla del Excel."
            )
            import report_export as rx
            try:
                png_comp = rx.grafica_comparacion_png(base, sel_multi, sel_lbl, colores)
            except Exception as e:
                png_comp = None
                st.caption(f"No se pudo generar la grafica para exportar: {e}")
            try:
                xlsx_comp = rx.exportar_excel(tabla_comp, stats_comp, meta_comp, config_comp, png_comp)
                st.download_button(
                    "Descargar Excel (comparacion)", data=xlsx_comp,
                    file_name=f"comparacion_{sel_var}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as e:
                st.caption(f"No se pudo generar Excel: {e}")

