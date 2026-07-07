#!/usr/bin/env python3
"""views/eventos.py — pestana Eventos (crear / editar / borrar marcas
temporales que se dibujan en Tendencia).

Extraida de app.py sin cambios de logica.
"""

import streamlit as st

import config_store as cfg

def render(filtros):
    variantes = filtros.variantes
    etiqueta = filtros.etiqueta

    st.subheader("Eventos")
    st.caption("Marcas temporales (actualizaciones de software, recalibraciones, "
               "cambios de sensor...) que se dibujan en la grafica de tendencia "
               "segun su fecha. Se guardan en config.db.")

    import datetime as _dt

    # --- Crear nuevo evento ---
    with st.expander("Crear nuevo evento", expanded=True):
        ce1, ce2 = st.columns(2)
        with ce1:
            ev_fecha = st.date_input("Fecha del evento", value=_dt.date.today(),
                                     key="ev_new_fecha")
            scope_options = ["ALL"] + variantes
            scope_lbl = {"ALL": "Todas las variantes"}
            scope_lbl.update({v: f"Solo {etiqueta[v]}" for v in variantes})
            ev_scope = st.selectbox(
                "Alcance", scope_options,
                format_func=lambda s: scope_lbl.get(s, s),
                key="ev_new_scope",
            )
        with ce2:
            ev_nombre = st.text_input("Nombre", key="ev_new_nombre",
                                      placeholder="Ej: Actualizacion de software")
            ev_desc = st.text_area("Descripcion", key="ev_new_desc", height=80,
                                   placeholder="Detalle del evento")
        if st.button("Agregar evento"):
            if ev_nombre.strip():
                cfg.add_event(ev_fecha.isoformat(), ev_nombre.strip(),
                              ev_desc.strip(), ev_scope)
                st.success(f"Evento '{ev_nombre}' agregado.")
                st.rerun()
            else:
                st.warning("El nombre es obligatorio.")

    # --- Lista de eventos existentes con editar/borrar ---
    st.markdown("**Eventos registrados**")
    eventos = cfg.list_events()  # todos
    if not eventos:
        st.caption("Aun no hay eventos. Crea uno arriba.")
    else:
        scope_lbl = {"ALL": "Todas"}
        scope_lbl.update({v: etiqueta[v] for v in variantes})
        scope_options = ["ALL"] + variantes
        for ev in eventos:
            if ev["scope"] not in scope_options:
                scope_options_ev = scope_options + [ev["scope"]]
                scope_lbl[ev["scope"]] = ev["scope"]
            else:
                scope_options_ev = scope_options
            with st.expander(f"{ev['event_date']} - {ev['name']} "
                             f"[{scope_lbl.get(ev['scope'], ev['scope'])}]"):
                ed1, ed2 = st.columns(2)
                with ed1:
                    nf = st.date_input("Fecha", value=_dt.date.fromisoformat(ev["event_date"]),
                                       key=f"ed_fecha_{ev['id']}")
                    ns = st.selectbox("Alcance", scope_options_ev,
                                      index=scope_options_ev.index(ev["scope"]),
                                      format_func=lambda s: scope_lbl.get(s, s),
                                      key=f"ed_scope_{ev['id']}")
                with ed2:
                    nn = st.text_input("Nombre", value=ev["name"], key=f"ed_nombre_{ev['id']}")
                    nd = st.text_area("Descripcion", value=ev["description"] or "",
                                      key=f"ed_desc_{ev['id']}", height=80)
                bg1, bg2 = st.columns(2)
                with bg1:
                    if st.button("Guardar cambios", key=f"save_{ev['id']}"):
                        cfg.update_event(ev["id"], nf.isoformat(), nn.strip(),
                                         nd.strip(), ns)
                        st.success("Actualizado.")
                        st.rerun()
                with bg2:
                    if st.button("Borrar", key=f"del_{ev['id']}"):
                        cfg.delete_event(ev["id"])
                        st.success("Borrado.")
                        st.rerun()
