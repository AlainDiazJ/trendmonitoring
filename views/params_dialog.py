#!/usr/bin/env python3
"""views/params_dialog.py — dialogo "Parametros": activar/desactivar
parametros en los desplegables de Tendencia/Correlacion (services/
param_visibility.py hace el filtrado real), y registrar parametros nuevos a
buscar via resync sobre los Exceles ya cargados en Loaded/.

Ocultar/activar es solo cosmetico (config.db); no toca motores.db. Cargar un
parametro nuevo si escribe en motores.db (via resync_measurements), y ademas
lo registra en config.db para que etl.run/etl.run_sync tambien lo busquen en
cargas futuras (etl.load_effective_mapping).

"Cargar nuevos parametros" acepta varias filas a la vez (una fila nueva
vacia aparece sola al llenar la ultima) y las resincroniza todas en UNA sola
corrida de resync_measurements.run, no una por una.
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
    "_params_new_rows", "_params_new_next_id",
)


def _variante_interna(display_label):
    return display_label.replace("LEAP-", "") if display_label.startswith("LEAP-") else display_label


def _limpiar_estado_trabajo():
    prefijos = ("_params_pick_hide_", "_params_pick_show_",
                "_params_new_raw_", "_params_new_variants_")
    for k in list(st.session_state.keys()):
        if k in _WORKING_KEYS or k.startswith(prefijos):
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
        "Busca estos nombres (tal como aparecen en la hoja Buffer) en los Exceles "
        "ya cargados de los modelos elegidos, y los deja registrados para que "
        "tambien se busquen en cargas futuras (boton Sync)."
    )

    # Filas dinamicas: una lista de ids en session_state. Se agrega una fila
    # nueva vacia automaticamente en cuanto la ultima fila tiene texto, para
    # poder cargar varios parametros sin reabrir el dialogo uno por uno.
    rows = st.session_state.setdefault("_params_new_rows", [0])
    st.session_state.setdefault("_params_new_next_id", 1)

    entradas = []
    for row_id in rows:
        c1, c2 = st.columns(2)
        with c1:
            raw = st.text_input(
                "Nombre del parametro (como en el Buffer)",
                key=f"_params_new_raw_{row_id}", placeholder="ej. PS3B",
            ).strip()
        with c2:
            variantes_sel = st.multiselect(
                "Modelos", VARIANTES_DISPLAY, key=f"_params_new_variants_{row_id}",
            )
        entradas.append((raw, variantes_sel))

    if entradas[-1][0]:
        # la ultima fila ya tiene texto: agrega una fila vacia debajo. Como
        # esa fila nueva nace vacia, este chequeo no se vuelve a disparar en
        # la siguiente pasada (crece de a una fila, sin bucles).
        next_id = st.session_state["_params_new_next_id"]
        rows.append(next_id)
        st.session_state["_params_new_next_id"] = next_id + 1
        st.rerun(scope="fragment")

    st.caption("Las filas vacias se ignoran.")

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Cancelar", key="_params_new_cancel", use_container_width=True):
            st.session_state["_params_view"] = "main"
            st.rerun(scope="fragment")
    with b2:
        if st.button("OK", key="_params_new_ok", type="primary", use_container_width=True):
            no_vacias = [(raw, variantes) for raw, variantes in entradas if raw]
            _confirmar_nuevos_parametros(no_vacias, loaded_dir)


def _confirmar_nuevos_parametros(entradas, loaded_dir):
    """entradas: lista de (raw_name, variantes_display_sel) con raw_name no
    vacio (las filas en blanco ya se filtraron antes de llamar esto)."""
    if not entradas:
        st.error("Agrega al menos un parametro con su(s) modelo(s).")
        return

    faltan_modelo = [raw for raw, variantes in entradas if not variantes]
    if faltan_modelo:
        st.error(f"Elige al menos un modelo para: {', '.join(faltan_modelo)}.")
        return

    mapping_efectivo = etl.load_effective_mapping("mapping.yaml")

    # pares (raw_name, variante_interna) deduplicados de todo el lote: si el
    # usuario repitio el mismo parametro+modelo en dos filas, no se registra
    # ni se avisa "ya existe" dos veces para lo mismo.
    pares = set()
    for raw, variantes_sel in entradas:
        for v in variantes_sel:
            pares.add((raw, _variante_interna(v)))

    nombres_lote = sorted({raw for raw, _v in pares})

    ya_existe_por_raw = {}
    a_registrar = set()
    for raw, v in sorted(pares):
        existe = any(
            raw in (por_var.get(v) or [])
            for por_var in mapping_efectivo.get("measurements", {}).values()
        )
        if existe:
            ya_existe_por_raw.setdefault(raw, []).append(v)
        else:
            a_registrar.add((raw, v))

    # Los mensajes se acumulan y se muestran DESPUES del rerun que cierra el
    # dialogo (un st.warning/success justo antes de st.rerun() nunca llega a
    # pintarse: el rerun reemplaza la pagina antes de que el navegador
    # muestre este frame). app.py los lee y los limpia en el siguiente render.
    mensajes = []
    for raw, variantes in ya_existe_por_raw.items():
        etiquetas = ", ".join(etl.display_engine_type(v) for v in variantes)
        mensajes.append(("warning", f"'{raw}' ya existe para: {etiquetas}. No se registro de nuevo ahi."))

    if not a_registrar:
        # nada nuevo que registrar: mostrar el aviso sin cerrar el dialogo
        for kind, msg in mensajes:
            getattr(st, kind)(msg)
        return

    for raw, v in a_registrar:
        cfg.add_custom_param(raw, v)

    variantes_a_resync = sorted({v for _raw, v in a_registrar})
    folders = [str(Path(loaded_dir) / etl.display_engine_type(v)) for v in variantes_a_resync]
    with st.spinner(f"Buscando {len(nombres_lote)} parametro(s) en los Exceles cargados..."):
        resumen = resync_measurements.run(DB_PATH, "mapping.yaml", folders, variants=variantes_a_resync)

    total = (resumen or {}).get("total_agregadas", 0)
    nombres_txt = ", ".join(nombres_lote)
    if total:
        mensajes.append(("success", f"{total} mediciones agregadas para: {nombres_txt}."))
    else:
        mensajes.append((
            "info",
            f"No se encontro ninguno de estos parametros en los Exceles cargados para "
            f"los modelos seleccionados: {nombres_txt}. Quedaron registrados y "
            "apareceran en cargas futuras (Sync) que si los contengan.",
        ))
    st.session_state["_params_flash"] = mensajes

    load_data.clear()
    _cerrar_dialogo()
