from pathlib import Path

from resync_measurements import find_source_path
from services.deletion_service import quarantine_source_excels


def test_find_source_path_locates_file_in_variant_subfolder(tmp_path):
    loaded = tmp_path / "Loaded"
    variant_dir = loaded / "LEAP-1A"
    variant_dir.mkdir(parents=True)
    excel = variant_dir / "reporte_1A.xlsx"
    excel.write_bytes(b"fake xlsx content")

    found = find_source_path("reporte_1A.xlsx", [loaded])

    assert found == excel


def test_find_source_path_returns_none_when_not_found(tmp_path):
    loaded = tmp_path / "Loaded"
    loaded.mkdir()
    assert find_source_path("no_existe.xlsx", [loaded]) is None


def test_quarantine_source_excels_finds_file_in_variant_subfolder(tmp_path):
    loaded = tmp_path / "Loaded"
    variant_dir = loaded / "CFM56-7B"
    variant_dir.mkdir(parents=True)
    excel = variant_dir / "reporte_7B.xlsx"
    excel.write_bytes(b"fake xlsx content")

    quarantine_root = tmp_path / "quarantine"
    moved, missing, errors = quarantine_source_excels(
        ["reporte_7B.xlsx"], loaded, quarantine_root=quarantine_root
    )

    assert not missing
    assert not errors
    assert len(moved) == 1
    assert not excel.exists()
    dest = Path(moved[0][1])
    assert dest.exists()
    assert dest.parent.parent == quarantine_root
