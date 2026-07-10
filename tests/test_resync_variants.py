from pathlib import Path

from openpyxl import Workbook

import etl
import resync_measurements

MAPPING_PATH = Path(__file__).resolve().parent.parent / "mapping.yaml"


def _write_buffer_xlsx(path, rows, sheet_name="Buffer"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    wb.save(path)


def _seed_db(tmp_path):
    """Carga un punto 1A y un punto 1B a una base fresca; devuelve db_path.
    Los Excel originales quedan en 'source/' pero el resync se apunta a una
    carpeta distinta y vacia, asi que ningun source_file se va a encontrar
    (a proposito: eso es lo que deja contar cuantos puntos se consideraron)."""
    source = tmp_path / "source"
    source.mkdir()
    db_path = tmp_path / "data" / "motores.db"

    _write_buffer_xlsx(source / "reporte_1A.xlsx", [
        ["Serial Number", "SN-1A", None],
        ["Point Number", "1", None],
        ["DATE", "01/01/2024", None],
    ])
    _write_buffer_xlsx(source / "reporte_1B.xlsx", [
        ["Serial Number", "SN-1B", None],
        ["Point Number", "1", None],
        ["DATE", "01/01/2024", None],
    ])
    etl.run(source, db_path, MAPPING_PATH)
    return db_path


def test_run_returns_summary_dict_with_expected_keys(tmp_path):
    db_path = _seed_db(tmp_path)
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()

    resumen = resync_measurements.run(db_path, MAPPING_PATH, [str(empty_folder)])

    assert resumen is not None
    for k in ("n_ok", "n_sin_nuevo", "n_sin_archivo", "n_sin_buffer", "total_agregadas"):
        assert k in resumen
    # ninguno de los dos archivos originales esta en empty_folder
    assert resumen["n_sin_archivo"] == 2


def test_run_with_variants_filter_ignores_other_variant_points(tmp_path):
    db_path = _seed_db(tmp_path)
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()

    resumen = resync_measurements.run(
        db_path, MAPPING_PATH, [str(empty_folder)], variants=["1B"],
    )

    # solo el punto 1B se considera; el 1A ni se cuenta como "sin archivo"
    assert resumen["n_sin_archivo"] == 1


def test_run_returns_none_when_db_missing(tmp_path):
    missing_db = tmp_path / "no_existe" / "motores.db"
    assert resync_measurements.run(missing_db, MAPPING_PATH, []) is None
