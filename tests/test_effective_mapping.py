from pathlib import Path

import config_store as cfg
import etl

MAPPING_PATH = Path(__file__).resolve().parent.parent / "mapping.yaml"


def test_load_effective_mapping_without_custom_params_matches_plain_load(tmp_path):
    db_path = str(tmp_path / "config_test.db")
    plano = etl.load_mapping(MAPPING_PATH)
    efectivo = etl.load_effective_mapping(MAPPING_PATH, config_db=db_path)
    assert efectivo == plano


def test_load_effective_mapping_overlays_custom_param(tmp_path):
    db_path = str(tmp_path / "config_test.db")
    cfg.add_custom_param("PS3B", "1B", db_path=db_path)

    efectivo = etl.load_effective_mapping(MAPPING_PATH, config_db=db_path)
    assert efectivo["measurements"]["ps3b"]["1B"] == ["PS3B"]

    # no toca el archivo real en disco
    plano = etl.load_mapping(MAPPING_PATH)
    assert "ps3b" not in plano.get("measurements", {})


def test_load_effective_mapping_appends_to_existing_canonical_without_duplicating(tmp_path):
    db_path = str(tmp_path / "config_test.db")
    # n1 ya existe para "1A" en mapping.yaml (N1, N1K, N1R); agregar un raw
    # nuevo a un canonical existente no debe duplicar ni pisar los que ya hay
    cfg.add_custom_param("N1Q", "1A", canonical="n1", db_path=db_path)

    efectivo = etl.load_effective_mapping(MAPPING_PATH, config_db=db_path)
    raws = efectivo["measurements"]["n1"]["1A"]
    assert "N1Q" in raws
    assert "N1K" in raws  # lo que ya traia mapping.yaml sigue ahi
    assert raws.count("N1Q") == 1
