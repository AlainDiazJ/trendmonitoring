import pytest

import config_store as cfg


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "config_test.db")


def test_threshold_roundtrip(db_path):
    assert cfg.get_threshold("1A", "EGTK [C]", "TAKEOFF", db_path=db_path) == (None, None)

    cfg.set_threshold("1A", "EGTK [C]", "TAKEOFF", 100.0, 900.0, db_path=db_path)
    assert cfg.get_threshold("1A", "EGTK [C]", "TAKEOFF", db_path=db_path) == (100.0, 900.0)

    # set de nuevo sobre la misma llave actualiza, no duplica
    cfg.set_threshold("1A", "EGTK [C]", "TAKEOFF", 110.0, 890.0, db_path=db_path)
    assert cfg.get_threshold("1A", "EGTK [C]", "TAKEOFF", db_path=db_path) == (110.0, 890.0)
    assert len(cfg.list_thresholds(db_path=db_path)) == 1

    cfg.delete_threshold("1A", "EGTK [C]", "TAKEOFF", db_path=db_path)
    assert cfg.get_threshold("1A", "EGTK [C]", "TAKEOFF", db_path=db_path) == (None, None)


def test_events_scope_all_se_incluye_para_cualquier_variante(db_path):
    cfg.add_event("2026-01-01", "Recalibracion celda", "", scope="ALL", db_path=db_path)
    cfg.add_event("2026-02-01", "Cambio de sensor 1A", "", scope="1A", db_path=db_path)
    cfg.add_event("2026-03-01", "Cambio de sensor 1B", "", scope="1B", db_path=db_path)

    eventos_1a = cfg.list_events(scope="1A", db_path=db_path)
    nombres = {e["name"] for e in eventos_1a}
    assert nombres == {"Recalibracion celda", "Cambio de sensor 1A"}

    eventos_todos = cfg.list_events(db_path=db_path)
    assert len(eventos_todos) == 3


def test_events_delete(db_path):
    cfg.add_event("2026-01-01", "Evento", "", db_path=db_path)
    [ev] = cfg.list_events(db_path=db_path)
    cfg.delete_event(ev["id"], db_path=db_path)
    assert cfg.list_events(db_path=db_path) == []


def test_hidden_points_scope_par_no_afecta_a_scope_vista(db_path):
    cfg.hide_point(1, scope="correlacion_ref::N1R vs EGTR", reason="mal capturado", db_path=db_path)

    assert cfg.list_hidden_points(scope="correlacion_ref::N1R vs EGTR", db_path=db_path) == {1}
    assert cfg.list_hidden_points(scope="correlacion_ref", db_path=db_path) == set()


def test_hidden_points_stable_key_sobrevive_a_cambio_de_point_id(db_path):
    cfg.hide_point(1, scope="correlacion_ref", stable_point_key="k-abc", db_path=db_path)

    # el punto vuelve a ingestarse con otro point_id pero misma stable_point_key
    cfg.hide_point(99, scope="correlacion_ref", stable_point_key="k-abc", db_path=db_path)

    detalle = cfg.list_hidden_points_detail(scope="correlacion_ref", db_path=db_path)
    assert len(detalle) == 1
    assert detalle[0]["point_id"] == 99
    assert detalle[0]["stable_point_key"] == "k-abc"


def test_unhide_point_por_stable_key(db_path):
    cfg.hide_point(1, scope="correlacion_ref", stable_point_key="k-abc", db_path=db_path)
    cfg.unhide_point(1, scope="correlacion_ref", stable_point_key="k-abc", db_path=db_path)
    assert cfg.list_hidden_points(scope="correlacion_ref", db_path=db_path) == set()


def test_unhide_all_points(db_path):
    cfg.hide_point(1, scope="correlacion_ref", db_path=db_path)
    cfg.hide_point(2, scope="correlacion_ref", db_path=db_path)
    cfg.hide_point(3, scope="global", db_path=db_path)

    cfg.unhide_all_points(scope="correlacion_ref", db_path=db_path)
    assert cfg.list_hidden_points(scope="correlacion_ref", db_path=db_path) == set()
    # el scope global no se toca
    assert cfg.list_hidden_points(scope="global", db_path=db_path) == {3}


def test_views_roundtrip(db_path):
    assert cfg.list_views(db_path=db_path) == []

    cfg.save_view("EGT TKO 1B", {"variant": "1B", "param": "EGTR2 [C]"}, db_path=db_path)
    assert cfg.get_view("EGT TKO 1B", db_path=db_path) == {"variant": "1B", "param": "EGTR2 [C]"}

    # guardar de nuevo con el mismo nombre reemplaza el payload
    cfg.save_view("EGT TKO 1B", {"variant": "1B", "param": "EGTK3 [C]"}, db_path=db_path)
    assert cfg.get_view("EGT TKO 1B", db_path=db_path) == {"variant": "1B", "param": "EGTK3 [C]"}
    assert len(cfg.list_views(db_path=db_path)) == 1

    cfg.delete_view("EGT TKO 1B", db_path=db_path)
    assert cfg.get_view("EGT TKO 1B", db_path=db_path) is None


def test_anom_status_default_pendiente(db_path):
    firma = cfg.anom_signature("1A", "EGTK [C]", 5, "outlier")
    assert cfg.get_anom_status(firma, db_path=db_path) == {"status": "Pendiente", "note": ""}

    cfg.set_anom_status(firma, "Revisada", "confirmado con mantenimiento", db_path=db_path)
    estado = cfg.get_anom_status(firma, db_path=db_path)
    assert estado["status"] == "Revisada"
    assert estado["note"] == "confirmado con mantenimiento"
