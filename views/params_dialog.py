#!/usr/bin/env python3
"""views/params_dialog.py — dialogo "Parametros": activar/desactivar
parametros en los desplegables de Tendencia/Correlacion (services/
param_visibility.py hace el filtrado real), y registrar parametros nuevos a
buscar via resync sobre los Exceles ya cargados en Loaded/.

Ocultar/activar es solo cosmetico (config.db); no toca motores.db. Cargar un
parametro nuevo si escribe en motores.db (via resync_measurements), y ademas
lo registra en config.db para que etl.run/etl.run_sync tambien lo busquen en
cargas futuras (etl.load_effective_mapping).
"""

from pathlib import Path

import streamlit as st

import config_store as cfg
import etl
import resync_measurements
from services.data_loader import DB_PATH, load_data

VARIANTES_DISPLAY = ["LEAP-1A", "LEAP-1B", "CFM56-5A", "CFM56-7B"]

_WORKING_KEYS = (
    "_params_hidden_working", "_params_view", "_params_search",
    "_params_pick_hide_seq", "_params_pick_show_seq",
    "_params_new_raw", "_params_new_variants",
)


def _variante_interna(display_label):
    return display_label.replace("LEAP-", "") if display_label.startswith("LEAP-") else display_label


def _limpiar_estado_trabajo():
    for k in list(st.session_state.keys()):
        if k in _WORKING_KEYS or k.startswith("_params_pick_hide_") or k.startswith("_params_pick_show_"):
            st.session_state.pop(k, None)


def iniciar_estado():
    """Llamar justo antes de abrir el dialogo (al pulsar el boton), para que
    cada apertura arranque desde el estado persistido, sin arrastrar cambios
    a medio hacer de una apertura anterior cancelada o cerrada con la X."""
    _limpiar_estado_trabajo()
    st.session_state["_params_hidden_working"] = set(cfg.list_hidden_params())
    st.session_state["_params_view"] = "main"


def _cerrar_dialogo():
    _limpiar_estado_trabajo()
    st.rerun()


def _universo_parametros(df):
    """dict raw_name -> etiqueta 'RAWNAME (LEAP-1A, CFM56-7B)'."""
    out = {}
    for raw_name, grp in df.groupby("raw_name"):
        variantes = sorted({etl.display_engine_type(v) for v in grp["variant"].dropna().unique()})
        out[raw_name] = f"{raw_name} ({', '.join(variantes)})"
    return out


@st.dialog("Parametros")
def abrir_dialogo(df, loaded_dir):
    vista = st.session_state.get("_params_view", "main")
    if vista == "nuevos":
        _vista_nuevos(loaded_dir)
    else:
        _vista_main(df)


def _vista_main(df):
    universo = _universo_parametros(df)
    hidden = st.session_state.setdefault("_params_hidden_working", set(cfg.list_hidden_params()))

    q = st.text_input("Buscar", key="_params_search", placeholder="ej. WF").strip().lower()
    activos = sorted(rn for rn in universo if rn not in hidden and q in rn.lower())
    inactivos = sorted(rn for rn in universo if rn in hidden and q in rn.lower())

    # Los multiselect de "seleccionar para mover" usan una key con numero de
    # secuencia: streamlit no permite reasignar la key de un widget ya
    # instanciado en el mismo run, asi que en vez de "vaciar" la seleccion
    # tras mover, se cambia de key (widget nuevo, sin seleccion) en el
    # siguiente rerun. Tambien evita pasarle a un multiselect una seleccion
    # guardada que ya no esta en las opciones (activos/inactivos encogio).
    seq_hide = st.session_state.setdefault("_params_pick_hide_seq", 0)
    seq_show = st.session_state.setdefault("_params_pick_show_seq", 0)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Parametros Activos** ({len(activos)})")
        pick_hide = st.multiselect(
            "Seleccionar para ocultar", activos,
            format_func=lambda rn: universo[rn], key=f"_params_pick_hide_{seq_hide}",
        )
        if st.button("Quitar »", key="_params_btn_hide", disabled=not pick_hide):
            st.session_state["_params_hidden_working"] |= set(pick_hide)
            st.session_state["_params_pick_hide_seq"] += 1
            st.rerun(scope="fragment")
    with c2:
        st.markdown(f"**Parametros Inactivos** ({len(inactivos)})")
        pick_show = st.multiselect(
            "Seleccionar para activar", inactivos,
            format_func=lambda rn: universo[rn], key=f"_params_pick_show_{seq_show}",
        )
        if st.button("« Agregar", key="_params_btn_show", disabled=not pick_show):
            st.session_state["_params_hidden_working"] -= set(pick_show)
            st.session_state["_params_pick_show_seq"] += 1
            st.rerun(scope="fragment")

    st.caption("Los inactivos se ocultan solo de los desplegables de Tendencia y "
               "Correlacion; los datos siguen intactos en la base.")
    st.markdown("---")
    b1, b2, b3 = st.columns([0.44, 0.28, 0.28])
    with b1:
        if st.button("Cargar nuevos parametros", key="_params_btn_nuevos"):
            st.session_state["_params_view"] = "nuevos"
            st.rerun(scope="fragment")
    with b2:
        if st.button("Cancelar", key="_params_btn_cancel", use_container_width=True):
            _cerrar_dialogo()
    with b3:
        if st.button("OK", key="_params_btn_ok", type="primary", use_container_width=True):
            cfg.set_hidden_params(st.session_state["_params_hidden_working"])
            _cerrar_dialogo()


def _vista_nuevos(loaded_dir):
    st.markdown("**Cargar nuevos parametros**")
    st.caption(
        "Busca este nombre (tal como aparece en la hoja Buffer) en los Exceles "
        "ya cargados de los modelos elegidos, y lo deja registrado para que "
        "tambien se busque en cargas futuras (boton Sync)."
    )
    c1, c2 = st.columns(2)
    with c1:
        raw_name = st.text_input(
            "Nombre del parametro (como en el Buffer)",
            key="_params_new_raw", placeholder="ej. PS3B",
        ).strip()
    with c2:
        variantes_sel = st.multiselect("Modelos", VARIANTES_DISPLAY, key="_params_new_variants")

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Cancelar", key="_params_new_cancel", use_container_width=True):
            st.session_state["_params_view"] = "main"
            st.rerun(scope="fragment")
    with b2:
        if st.button("OK", key="_params_new_ok", type="primary", use_container_width=True):
            _confirmar_nuevo_parametro(raw_name, variantes_sel, loaded_dir)


def _confirmar_nuevo_parametro(raw_name, variantes_sel, loaded_dir):
    if not raw_name:
        st.error("Escribe el nombre del parametro (como aparece en el Buffer).")
        return
    if not variantes_sel:
        st.error("Elige al menos un modelo de motor.")
        return

    variantes_internas = [_variante_interna(v) for v in variantes_sel]
    mapping_efectivo = etl.load_effective_mapping("mapping.yaml")

    ya_existe, a_registrar = [], []
    for v in variantes_internas:
        existe = any(
            raw_name in (por_var.get(v) or [])
            for por_var in mapping_efectivo.get("measurements", {}).values()
        )
        (ya_existe if existe else a_registrar).append(v)

    # Los mensajes se acumulan y se muestran DESPUES del rerun que cierra el
    # dialogo (un st.warning/success justo antes de st.rerun() nunca llega a
    # pintarse: el rerun reemplaza la pagina antes de que el navegador
    # muestre este frame). app.py los lee y los limpia en el siguiente render.
    mensajes = []
    if ya_existe:
        etiquetas = ", ".join(etl.display_engine_type(v) for v in ya_existe)
        mensajes.append(("warning", f"'{raw_name}' ya existe para: {etiquetas}. No se registro de nuevo ahi."))
    if not a_registrar:
        # nada nuevo que registrar: mostrar el aviso sin cerrar el dialogo
        for kind, msg in mensajes:
            getattr(st, kind)(msg)
        return

    for v in a_registrar:
        cfg.add_custom_param(raw_name, v)

    folders = [str(Path(loaded_dir) / etl.display_engine_type(v)) for v in a_registrar]
    with st.spinner("Buscando el parametro en los Exceles cargados..."):
        resumen = resync_measurements.run(DB_PATH, "mapping.yaml", folders, variants=a_registrar)

    total = (resumen or {}).get("total_agregadas", 0)
    if total:
        mensajes.append(("success", f"{total} mediciones agregadas para '{raw_name}'."))
    else:
        mensajes.append((
            "info",
            f"No se encontro '{raw_name}' en los Exceles cargados para los modelos "
            "seleccionados. Quedo registrado y aparecera en cargas futuras (Sync) "
            "que si lo contengan.",
        ))
    st.session_state["_params_flash"] = mensajes

    load_data.clear()
    _cerrar_dialogo()
