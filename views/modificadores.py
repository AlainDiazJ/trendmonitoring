#!/usr/bin/env python3
"""views/modificadores.py — pestana Modificadores (vigilancia de niveles de
factores de celda por rating; detecta recalibraciones).

Extraida de app.py sin cambios de logica.
"""

import pandas as pd
import streamlit as st

def render(filtros):
    dfv_hist = filtros.dfv_hist
    sel_var = filtros.sel_var
    sel_lbl = filtros.sel_lbl

    st.subheader(f"Modificadores de celda - {sel_lbl}")
    st.caption("Los modificadores deben mantenerse en un nivel constante a lo "
               "largo del historico, POR RATING. Si dentro de un mismo rating "
               "aparecen varios niveles, alguien recalibro la celda entre esos "
               "reportes. Esta pagina ignora los filtros de fecha y Description "
               "del sidebar: muestra el historico completo por rating.")

    MODS_POR_VARIANTE = {
        "1A": ["FMFN", "FMEGT", "FMN2", "FMW2", "FMWF"],
        "1B": ["CFFN", "CFN2", "CFEGT", "CFw2A", "CFWFM"],
    }
    mods_var = MODS_POR_VARIANTE.get(sel_var, [])

    if not mods_var:
        st.info(f"No hay modificadores definidos para la variante {sel_lbl}.")
    else:
        mod_data = dfv_hist[dfv_hist["param_label"].apply(
            lambda x: any(str(x).split(" ")[0].split("[")[0].strip() == m
                          for m in mods_var)
        )].copy()

        if mod_data.empty:
            st.warning(
                f"No se encontraron modificadores en la base de datos para {sel_lbl}. "
                f"Esperados: {', '.join(mods_var)}. "
                "Verifica que el ETL los este cargando (mapping.yaml)."
            )
        else:
            import numpy as np
            import plotly.graph_objects as go

            tol_pct = st.slider(
                "Tolerancia para considerar 'mismo nivel' (% del valor)",
                0.1, 5.0, 1.0, step=0.1,
                help="Cambios menores a esta tolerancia se consideran ruido "
                     "normal. Solo cambios mayores cuentan como recalibracion.",
                key="mod_tol",
            )

            def detectar_niveles(valores, tolerancia_pct):
                """Agrupa valores casi iguales. Devuelve lista de
                (idx_inicio, idx_fin, valor_representativo)."""
                if len(valores) == 0:
                    return []
                niveles = []
                ini = 0
                grupo = [valores[0]]
                for i in range(1, len(valores)):
                    media = float(np.mean(grupo))
                    if media == 0:
                        mismo = abs(valores[i]) < 1e-9
                    else:
                        mismo = (abs(valores[i] - media) / abs(media) * 100
                                 < tolerancia_pct)
                    if mismo:
                        grupo.append(valores[i])
                    else:
                        niveles.append((ini, i - 1, float(np.mean(grupo))))
                        ini = i
                        grupo = [valores[i]]
                niveles.append((ini, len(valores) - 1, float(np.mean(grupo))))
                return niveles

            # ---- Recorre por (rating, modificador) y acumula resultados ----
            ratings = sorted(mod_data["description"].dropna().unique())
            mods_presentes_global = sorted(mod_data["param_label"].unique())

            # estructura: resultados_por_rating[rating] = {
            #   "mods": {param_label: {niveles, consec, fechas, vals}},
            #   "n_estables": int, "n_con_cambios": int,
            # }
            resultados_por_rating = {}
            transiciones_totales = []  # tabla unica al final
            total_mods_vigilados = 0
            total_estables = 0
            total_con_cambios = 0

            for rating in ratings:
                sub_rating = mod_data[mod_data["description"] == rating]
                mods_presentes = sorted(sub_rating["param_label"].unique())
                info_mods = {}
                n_estables = 0
                n_con_cambios = 0

                for m in mods_presentes:
                    s = (sub_rating[sub_rating["param_label"] == m]
                         .sort_values("consecutivo")
                         .drop_duplicates("consecutivo")
                         .reset_index(drop=True))
                    if s.empty:
                        continue
                    vals = s["value"].astype(float).tolist()
                    consec = s["consecutivo"].astype(int).tolist()
                    fechas = s["test_date"].astype(str).tolist()
                    source_files = s["source_file"].fillna("").astype(str).tolist()
                    niveles = detectar_niveles(vals, tol_pct)
                    info_mods[m] = {
                        "niveles": niveles, "consec": consec,
                        "fechas": fechas, "source_files": source_files, "vals": vals,
                    }
                    if len(niveles) > 1:
                        n_con_cambios += 1
                        for k in range(1, len(niveles)):
                            idx_t = niveles[k][0]
                            transiciones_totales.append({
                                "Rating": rating,
                                "Modificador": m,
                                "Reporte": consec[idx_t],
                                "Fecha": fechas[idx_t],
                                "Nivel anterior": niveles[k - 1][2],
                                "Nivel nuevo": niveles[k][2],
                                "Delta %": ((niveles[k][2] - niveles[k - 1][2])
                                            / niveles[k - 1][2] * 100
                                            if niveles[k - 1][2] != 0
                                            else float("inf")),
                            })
                    else:
                        n_estables += 1

                resultados_por_rating[rating] = {
                    "mods": info_mods,
                    "n_estables": n_estables,
                    "n_con_cambios": n_con_cambios,
                }
                total_mods_vigilados += len(info_mods)
                total_estables += n_estables
                total_con_cambios += n_con_cambios

            # ---- Resumen global arriba ----
            gm1, gm2, gm3, gm4 = st.columns(4)
            gm1.metric("Ratings analizados", len(ratings))
            gm2.metric("Modificadores vigilados (total)", total_mods_vigilados)
            gm3.metric("Estables (1 nivel)", total_estables)
            gm4.metric("Con cambios", total_con_cambios)

            if total_con_cambios > 0:
                st.error(f"as  {total_con_cambios} caso(s) de modificador-en-rating "
                         "muestran mas de un nivel. Hubo recalibracion(es) en "
                         "el historico. Detalle por rating abajo, transiciones "
                         "consolidadas al final.")
            else:
                st.success("a Todos los modificadores estan en un solo nivel "
                           "dentro de cada rating: no hubo recalibracion en el "
                           "historico.")

            # ---- Bloque por rating ----
            for rating in ratings:
                info = resultados_por_rating[rating]
                mods_aqui = list(info["mods"].keys())
                if not mods_aqui:
                    continue

                st.markdown("---")
                st.markdown(f"### {rating}")
                rm1, rm2, rm3 = st.columns(3)
                rm1.metric("Modificadores en este rating", len(mods_aqui))
                rm2.metric("Estables", info["n_estables"])
                rm3.metric("Con cambios", info["n_con_cambios"])

                n_cols = 2
                for i in range(0, len(mods_aqui), n_cols):
                    fila = st.columns(n_cols)
                    bloque = mods_aqui[i:i + n_cols]
                    for j in range(n_cols):
                        if j >= len(bloque):
                            continue
                        m = bloque[j]
                        with fila[j]:
                            try:
                                d = info["mods"][m]
                                niveles = d["niveles"]
                                consec = d["consec"]
                                fechas = d["fechas"]
                                source_files = d["source_files"]
                                vals = d["vals"]
                                n_niv = len(niveles)
                                color = "#2ca02c" if n_niv == 1 else "crimson"
                                figm = go.Figure()
                                figm.add_trace(go.Scatter(
                                    x=[str(c) for c in consec], y=vals,
                                    mode="lines",
                                    line=dict(color=color, width=1.5),
                                    customdata=list(zip(fechas, source_files)),
                                    hovertemplate=("reporte %{x}<br>"
                                                   "valor %{y:.6f}"
                                                   "<br>fecha %{customdata[0]}"
                                                   "<br>archivo %{customdata[1]}"
                                                   "<extra></extra>"),
                                    showlegend=False,
                                ))
                                for k in range(1, n_niv):
                                    idx_t = niveles[k][0]
                                    figm.add_vline(
                                        x=idx_t, line_color="red",
                                        line_dash="dot", line_width=2,
                                    )
                                etiqueta = ("a 1 nivel" if n_niv == 1
                                            else f"as  {n_niv} niveles")
                                figm.update_layout(
                                    title=f"{m} a {etiqueta}",
                                    height=260,
                                    margin=dict(t=40, b=30, l=50, r=10),
                                    xaxis_title="reporte",
                                    xaxis=dict(showticklabels=False),
                                )
                                # key incluye rating para evitar colisiones
                                safe_rating = "".join(
                                    c if c.isalnum() else "_" for c in rating
                                )[:40]
                                st.plotly_chart(
                                    figm, use_container_width=True,
                                    key=f"mod_chart_{sel_var}_{safe_rating}_{m}",
                                )
                            except Exception as _ex:
                                st.error(f"Error dibujando {m} en {rating}: "
                                         f"{type(_ex).__name__}: {_ex}")

            # ---- Tabla unica de transiciones al final ----
            if transiciones_totales:
                st.markdown("---")
                st.markdown(f"**Transiciones detectadas a consolidado "
                            f"({len(transiciones_totales)})**")
                st.caption("Si una misma Fecha aparece en varios ratings, es "
                           "una recalibracion real de celda (afecta a todos los "
                           "ratings simultaneamente). Si solo aparece en uno, "
                           "vale la pena revisar ese dato.")
                tabla = pd.DataFrame(transiciones_totales)
                tabla = tabla.sort_values(["Fecha", "Rating", "Modificador"]) \
                             .reset_index(drop=True)
                st.dataframe(
                    tabla.style.format({
                        "Nivel anterior": "{:.6f}",
                        "Nivel nuevo": "{:.6f}",
                        "Delta %": "{:+.3f}%",
                    }),
                    use_container_width=True,
                    height=min(420, 80 + 35 * len(tabla)),
                )


