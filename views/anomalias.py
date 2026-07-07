#!/usr/bin/env python3
"""views/anomalias.py — pestana Anomalias (outliers, umbrales, CUSUM y
rachas consolidados, con estados persistentes por firma).

Extraida de app.py sin cambios de logica.
"""

import pandas as pd
import streamlit as st

import config_store as cfg

def render(filtros):
    fdf = filtros.fdf
    dfv_hist = filtros.dfv_hist
    sel_var = filtros.sel_var
    sel_lbl = filtros.sel_lbl
    sel_desc = filtros.sel_desc

    st.subheader(f"Anomalias - {sel_lbl}")
    st.caption("Vista consolidada de outliers, cruces de umbral, deriva CUSUM "
               "y rachas largas. Recorre todos los parametros del nucleo y "
               "respeta tus filtros de fecha y Description.")

    import anomaly_engine as ae

    # Controles
    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        n_sigma_a = st.slider("N sigma (outliers)", 1, 6, 3, key="anom_nsig")
    with cc2:
        cusum_k_a = st.slider("CUSUM k (sigma)", 0.0, 2.0, 0.5, step=0.1, key="anom_k")
    with cc3:
        cusum_h_a = st.slider("CUSUM H (sigma)", 2.0, 8.0, 4.0, step=0.5, key="anom_h")


    with st.expander("Baseline de deteccion", expanded=False):
        baseline_modo_a = st.selectbox(
            "Baseline estadistico para anomalias",
            ["Historico completo", "Visible", "Rango manual", "Baseline aprobado"],
            index=0,
            key="baseline_modo_anom",
            help="Media/sigma para outliers y CUSUM. La lista de anomalias sigue "
                 "respetando los filtros visibles. 'Baseline aprobado' usa los "
                 "perfiles congelados donde existan; el resto usa historico completo.",
        )
        baseline_fechas_a = None
        if baseline_modo_a == "Rango manual":
            _bfa = dfv_hist["fecha"].dropna()
            if not _bfa.empty:
                baseline_fechas_a = st.date_input(
                    "Fechas baseline anomalias",
                    value=(_bfa.min().date(), _bfa.max().date()),
                    min_value=_bfa.min().date(),
                    max_value=_bfa.max().date(),
                    key="baseline_fechas_anom",
                )

    def construir_baseline_stats_anom():
        if baseline_modo_a == "Visible":
            base = fdf.copy()
            label = "visible"
        else:
            base = dfv_hist[dfv_hist["description"].isin(sel_desc)].copy()
            label = "historico completo"
            if baseline_modo_a == "Rango manual" and isinstance(baseline_fechas_a, tuple) and len(baseline_fechas_a) == 2:
                d0a, d1a = baseline_fechas_a
                base = base[(base["fecha"].dt.date >= d0a) & (base["fecha"].dt.date <= d1a)]
                label = f"rango manual {d0a.isoformat()} a {d1a.isoformat()}"
        out = {}
        if base.empty:
            return out, label, 0
        for (param, desc), g in base.groupby(["param_label", "description"]):
            vals = g["value"].astype(float).dropna()
            if len(vals) >= 2:
                sd = vals.std(ddof=1)
                if sd and sd > 0:
                    out[(param, desc)] = {
                        "mu": vals.mean(),
                        "sd": sd,
                        "n": len(vals),
                        "label": label,
                    }
        # Baseline aprobado: donde exista un perfil congelado para
        # (parametro, description), sus media/sigma REEMPLAZAN a las
        # calculadas; las combinaciones sin perfil conservan el historico.
        if baseline_modo_a == "Baseline aprobado":
            n_perfiles = 0
            vistos = set()
            for perfil in cfg.list_baseline_profiles(variant=sel_var):
                clave = (perfil["param_label"], perfil["description"])
                if clave in vistos:
                    continue  # la lista viene mas reciente primero
                vistos.add(clave)
                if perfil["mean"] is None or not perfil["sigma"] or perfil["sigma"] <= 0:
                    continue
                out[clave] = {
                    "mu": float(perfil["mean"]),
                    "sd": float(perfil["sigma"]),
                    "n": int(perfil["n_points"] or 0),
                    "label": f"aprobado: {perfil['name']}",
                }
                n_perfiles += 1
            label = (f"baseline aprobado ({n_perfiles} perfil(es); "
                     "resto historico completo)")
        return out, label, len(base[["point_id", "param_label"]].drop_duplicates())

    baseline_stats_a, baseline_label_a, baseline_n_a = construir_baseline_stats_anom()
    st.caption(f"Baseline activo para anomalias: {baseline_label_a} - {baseline_n_a} mediciones base.")

    # Recoger umbrales fijos guardados (todos los de esta variante)
    thr_dict = {}
    for r in cfg.list_thresholds():
        v, pl, dscr, low, high = r
        if v == sel_var:
            thr_dict[(pl, dscr)] = (low, high)

    # Ejecutar deteccion sobre fdf (ya filtrado por variante, fechas, description)
    anom_df = ae.detectar_anomalias(
        fdf, sel_var, thresholds_por_clave=thr_dict,
        n_sigma=n_sigma_a, cusum_k=cusum_k_a, cusum_h=cusum_h_a, racha_umbral=4,
        baseline_stats=baseline_stats_a,
    )

    if anom_df.empty:
        st.success("a Sin anomalias detectadas con los filtros y parametros actuales.")
    else:
        # Cargar estados guardados y enriquecer con fecha + stable key del punto.
        estados = cfg.list_anom_statuses()
        meta_anom = (
            fdf[["param_label", "description", "consecutivo", "fecha_iso", "stable_point_key"]]
            .drop_duplicates(["param_label", "description", "consecutivo"])
            .rename(columns={
                "param_label": "parametro",
                "consecutivo": "reporte",
                "fecha_iso": "fecha",
            })
        )
        anom_df = anom_df.merge(
            meta_anom,
            on=["parametro", "description", "reporte"],
            how="left",
        )

        firmas = []
        firmas_legacy = []
        estados_resueltos = []
        notas_resueltas = []
        migradas = 0
        for _, r in anom_df.iterrows():
            stable_key = r.get("stable_point_key")
            if pd.isna(stable_key):
                stable_key = None
            firma = cfg.anom_signature(
                sel_var, r["parametro"], r["reporte"], r["tipo"], r["description"],
                stable_point_key=stable_key,
            )
            firma_legacy = cfg.anom_signature(
                sel_var, r["parametro"], r["reporte"], r["tipo"], r["description"],
            )
            estado_new = estados.get(firma)
            estado_old = estados.get(firma_legacy)
            if estado_new is None and estado_old is not None and stable_key:
                cfg.set_anom_status(firma, estado_old.get("status", "Pendiente"), estado_old.get("note", ""))
                estado_new = estado_old
                estados[firma] = estado_old
                migradas += 1
            estado_final = estado_new or estado_old or {"status": "Pendiente", "note": ""}
            firmas.append(firma)
            firmas_legacy.append(firma_legacy)
            estados_resueltos.append(estado_final.get("status", "Pendiente"))
            notas_resueltas.append(estado_final.get("note", ""))

        anom_df["firma"] = firmas
        anom_df["firma_legacy"] = firmas_legacy
        anom_df["estado"] = estados_resueltos
        anom_df["nota"] = notas_resueltas
        if migradas:
            st.caption(f"Migrados {migradas} estado(s) de anomalia a stable_point_key.")

        # Metricas resumen
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total", len(anom_df))
        m2.metric("Alta", (anom_df["severidad"] == "Alta").sum())
        m3.metric("Pendientes",
                  (anom_df["estado"] == "Pendiente").sum())
        m4.metric("Revisadas",
                  (anom_df["estado"] == "Revisada").sum())

        # Filtros locales de la pestana
        st.markdown("**Filtros de la lista**")
        fa1, fa2, fa3 = st.columns(3)
        with fa1:
            f_sev = st.multiselect("Severidad", ["Alta", "Media", "Baja"],
                                   default=["Alta", "Media", "Baja"], key="anom_fsev")
        with fa2:
            f_est = st.multiselect("Estado", ["Pendiente", "Revisada", "Descartada"],
                                   default=["Pendiente"], key="anom_fest")
        with fa3:
            tipos_disp = sorted(anom_df["tipo"].unique())
            f_tipo = st.multiselect("Tipo", tipos_disp, default=tipos_disp, key="anom_ftipo")

        vista = anom_df[anom_df["severidad"].isin(f_sev)
                        & anom_df["estado"].isin(f_est)
                        & anom_df["tipo"].isin(f_tipo)].copy()

        # Orden: severidad (Alta > Media > Baja), luego por reporte desc
        sev_ord = {"Alta": 0, "Media": 1, "Baja": 2}
        vista["_so"] = vista["severidad"].map(sev_ord)
        vista = vista.sort_values(["_so", "reporte"], ascending=[True, False]).drop(columns=["_so"])

        st.markdown(f"**{len(vista)} anomalias** (de {len(anom_df)} totales)")

        # Tabla editable: el usuario puede cambiar estado y nota
        col_show = ["severidad", "tipo", "fecha", "parametro", "reporte", "description",
                    "valor", "esperado", "desviacion", "baseline", "detalle", "estado", "nota"]
        edit_df = st.data_editor(
            vista[col_show + ["firma"]].set_index("firma"),
            column_config={
                "estado": st.column_config.SelectboxColumn(
                    "Estado", options=["Pendiente", "Revisada", "Descartada"],
                    required=True,
                ),
                "nota": st.column_config.TextColumn("Nota", help="Comentario libre"),
                "fecha": st.column_config.TextColumn(
                    "Fecha", help="Formato AAAA-MM-DD para ordenar cronologicamente"),
                "valor": st.column_config.NumberColumn("Valor", format="%.2f"),
                "esperado": st.column_config.NumberColumn("Esperado", format="%.2f"),
            },
            disabled=["severidad", "tipo", "fecha", "parametro", "reporte", "description",
                      "valor", "esperado", "desviacion", "baseline", "detalle"],
            use_container_width=True, height=420, key="anom_editor",
        )

        if st.button("Guardar cambios de estado", key="anom_save"):
            cambios = 0
            for firma_idx, fila in edit_df.iterrows():
                prev = estados.get(firma_idx, {"status": "Pendiente", "note": ""})
                if (fila["estado"] != prev["status"]) or (fila["nota"] != prev["note"]):
                    cfg.set_anom_status(firma_idx, fila["estado"], fila["nota"])
                    cambios += 1
            if cambios:
                st.success(f"Guardados {cambios} cambio(s) de estado.")
                st.rerun()
            else:
                st.info("Sin cambios para guardar.")


