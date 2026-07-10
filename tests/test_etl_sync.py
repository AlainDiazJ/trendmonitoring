from pathlib import Path

from openpyxl import Workbook

import etl

MAPPING_PATH = Path(__file__).resolve().parent.parent / "mapping.yaml"


def _write_buffer_xlsx(path, rows, sheet_name="Buffer"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_run_sync_moves_ok_files_to_loaded_variant_and_leaves_errors_in_unloaded(tmp_path):
    unloaded = tmp_path / "Unloaded"
    loaded = tmp_path / "Loaded"
    unloaded.mkdir()
    db_path = tmp_path / "data" / "motores.db"

    # archivo valido: variante "1A" por el nombre, con un punto identificable
    valid_name = "reporte_1A_pointA.xlsx"
    _write_buffer_xlsx(unloaded / valid_name, [
        ["Serial Number", "SN-001", None],
        ["Point Number", "1", None],
        ["DATE", "01/01/2024", None],
        ["Description", "MAXI CONTINU", None],
    ])

    # archivo invalido: sin hoja "Buffer" -> error, se queda en Unloaded
    invalid_name = "sin_buffer.xlsx"
    _write_buffer_xlsx(unloaded / invalid_name, [["a", "b", "c"]], sheet_name="Sheet1")

    resultado = etl.run_sync(unloaded, loaded, db_path, MAPPING_PATH)

    assert resultado["ok"] == 1
    assert resultado["moved"] == 1
    assert resultado["error"] == 1
    assert db_path.exists()

    assert not (unloaded / valid_name).exists()
    assert (loaded / "LEAP-1A" / valid_name).exists()

    assert (unloaded / invalid_name).exists()
    assert not any((loaded / "LEAP-1A").glob(invalid_name))


def test_run_sync_second_pass_skips_duplicate_and_leaves_it_in_unloaded(tmp_path):
    unloaded = tmp_path / "Unloaded"
    loaded = tmp_path / "Loaded"
    unloaded.mkdir()
    db_path = tmp_path / "data" / "motores.db"

    name = "reporte_1B_pointA.xlsx"
    _write_buffer_xlsx(unloaded / name, [
        ["Serial Number", "SN-002", None],
        ["Point Number", "1", None],
        ["DATE", "01/02/2024", None],
    ])

    etl.run_sync(unloaded, loaded, db_path, MAPPING_PATH)
    # el archivo original ya se movio; recrea uno identico para simular
    # que alguien lo volvio a dejar en Unloaded
    _write_buffer_xlsx(unloaded / name, [
        ["Serial Number", "SN-002", None],
        ["Point Number", "1", None],
        ["DATE", "01/02/2024", None],
    ])

    resultado = etl.run_sync(unloaded, loaded, db_path, MAPPING_PATH)

    assert resultado["skipped"] == 1
    assert resultado["moved"] == 0
    assert (unloaded / name).exists()
