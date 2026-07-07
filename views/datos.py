#!/usr/bin/env python3
"""views/datos.py — pestana Datos (tabla filtrada, retiro de puntos con
cuarentena de Exceles e historial de cuarentena).

Extraida de app.py sin cambios de logica.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import config_store as cfg
from services.data_loader import DB_PATH, load_data
from services.deletion_service import (
    QUARANTINE_DIR,
    delete_test_point,
    quarantine_source_excels,
)

def render(filtros):
    fdf = filtros.fdf
    sel_lbl = filtros.sel_lbl

    st.subheader("Datos filtrados")
    st.caption(
        "Selecciona una fila de la tabla y usa el boton para retirar el punto "
        "completo al que pertenece esa medicion. El Excel de origen NO se "
        f"borra: se mueve a la carpeta '{QUARANTINE_DIR}/' junto a la app."
    )
    source_folder = st.text_input(
        "Carpeta donde estan los Excel de origen",
        value=st.session_state.get("source_excel_folder", ""),
        key="source_excel_folder",
        placeholder=r"C:\ruta\a\carpeta_de_pruebas",
        help="De ahi se toma el archivo indicado en source_file para moverlo a cuarentena.",
    )

    cols = ["point_id", "consecutivo", "description", "fecha_iso", "date_parse_status",
            "date_parse_rule", "point_number", "source_file", "param_label", "value", "unit"]
    datos_tabla = fdf[cols].rename(columns={"fecha_iso": "fecha"}) \
        .sort_values(["consecutivo", "param_label"]).reset_index(drop=True)
    tabla_event = st.dataframe(
        datos_tabla,
        use_container_width=True, height=480,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
    )

    selected_rows = tabla_event.selection.rows
    if selected_rows:
        filas_sel = datos_tabla.iloc[selected_rows]
        punto_ids = sorted({int(pid) for pid in filas_sel["point_id"].dropna().unique()})
        source_files = sorted(str(s) for s in filas_sel["source_file"].dropna().unique())
        n_med_visibles = int(fdf[fdf["point_id"].isin(punto_ids)].shape[0])
        st.info(
            f"Puntos seleccionados: {len(punto_ids)} | "
            f"mediciones visibles asociadas: {n_med_visibles} | "
            f"Exceles asociados: {len(source_files)}."
        )
        st.caption(
            "Se retiraran de la base los puntos completos asociados a las filas "
            "seleccionadas (con sus mediciones) y sus Excel de origen se moveran "
            "a cuarentena. Nada se destruye: el Excel se puede restaurar a mano."
        )
        motivo_retiro = st.text_input(
            "Motivo del retiro (queda en el registro de cuarentena)",
            key="quarantine_reason",
            placeholder="Ej: punto capturado con celda descalibrada",
        )
        permitir_sin_excel = st.checkbox(
            "Permitir retirar puntos aunque no se encuentre su Excel de origen",
            value=False,
            key="quarantine_allow_missing",
            help="Por default el retiro se BLOQUEA si falta cualquier Excel: el "
                 "archivo es la evidencia primaria del punto y no se retira el "
                 "registro sin ponerla antes en cuarentena. Marca esta casilla "
                 "solo si el Excel ya no existe (p. ej. se borro historicamente).",
        )
        puede_borrar = bool(source_folder.strip())
        if not puede_borrar:
            st.caption("Indica la carpeta de Exceles para habilitar el retiro.")
        if st.button("Retirar puntos y mover Exceles a cuarentena", type="primary",
                     disabled=not puede_borrar):
            try:
                # 0) verificacion previa (all-or-nothing): si falta CUALQUIER
                # Excel y no hay autorizacion explicita, no se toca nada:
                # ni archivos ni base.
                folder_q = Path(source_folder).expanduser()
                faltantes_previos = []
                for source_file in source_files:
                    src_q = Path(str(source_file))
                    ruta_q = src_q if src_q.is_absolute() else folder_q / src_q.name
                    if not (ruta_q.exists() and ruta_q.is_file()):
                        faltantes_previos.append(str(ruta_q))
                if faltantes_previos and not permitir_sin_excel:
                    st.error(
                        "Retiro BLOQUEADO: no se encontraron estos Excel de origen: "
                        + " | ".join(faltantes_previos)
                        + ". No se retiro ningun punto ni se movio ningun archivo. "
                        "Corrige la carpeta de Exceles, o marca la casilla de "
                        "arriba para retirar sin asegurar la evidencia."
                    )
                    st.stop()

                # 1) primero se pone a salvo la evidencia (mover Excel);
                # 2) luego se retiran los puntos de la base;
                # 3) al final se registra todo en config.db.
                moved_files, missing_files, file_errors = quarantine_source_excels(
                    source_files, source_folder,
                )
                if file_errors:
                    st.error("No se pudieron mover algunos Excel: " + " | ".join(file_errors))
                    st.stop()

                # puntos/llaves asociados a cada Excel, para el registro
                sel_puntos = (
                    fdf[fdf["point_id"].isin(punto_ids)]
                    [["point_id", "stable_point_key", "source_file"]]
                    .drop_duplicates("point_id")
                )

                total_points = 0
                total_meas = 0
                for punto_id in punto_ids:
                    n_points, n_meas = delete_test_point(DB_PATH, punto_id)
                    total_points += n_points
                    total_meas += n_meas
                load_data.clear()

                destino_por_origen = dict(moved_files)
                for source_file in source_files:
                    src = Path(str(source_file))
                    path = src if src.is_absolute() else Path(source_folder).expanduser() / src.name
                    afectados = sel_puntos[sel_puntos["source_file"].astype(str) == str(source_file)]
                    cfg.log_excel_quarantine(
                        source_file=str(source_file),
                        original_path=str(path),
                        quarantine_path=destino_por_origen.get(str(path)),
                        point_ids=afectados["point_id"].tolist(),
                        stable_point_keys=afectados["stable_point_key"].tolist(),
                        reason=motivo_retiro.strip(),
                    )

                if total_points:
                    st.success(
                        f"Se retiraron {total_points} punto(s), {total_meas} mediciones. "
                        f"{len(moved_files)} Excel(es) movidos a cuarentena."
                    )
                    if missing_files:
                        st.warning(
                            "Estos Excel no se encontraron y sus puntos se "
                            "retiraron SIN asegurar la evidencia (autorizado "
                            "por la casilla): " + " | ".join(missing_files)
                        )
                    st.rerun()
                else:
                    st.warning("No se encontraron esos puntos en la base.")
            except Exception as e:
                st.error(f"No se pudieron retirar los puntos: {e}")
    else:
        st.caption("No hay ninguna fila seleccionada.")
    st.caption(f"{len(fdf)} mediciones - {sel_lbl}")

    # ---- Historial de cuarentena ----
    historial_q = cfg.list_excel_quarantine()
    if historial_q:
        with st.expander(f"Historial de cuarentena ({len(historial_q)} registro(s))",
                         expanded=False):
            st.caption(
                "Exceles retirados del dashboard. El archivo sigue en la ruta "
                "de cuarentena indicada; para reincorporarlo, muevelo de vuelta "
                "a la carpeta de origen y vuelve a correr el ETL."
            )
            st.dataframe(
                pd.DataFrame(historial_q)[
                    ["created_at", "source_file", "quarantine_path", "point_ids", "reason"]
                ].rename(columns={
                    "created_at": "Fecha", "source_file": "Archivo",
                    "quarantine_path": "Ruta cuarentena", "point_ids": "point_id(s)",
                    "reason": "Motivo",
                }),
                use_container_width=True, hide_index=True,
            )


