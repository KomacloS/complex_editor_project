import sys
import pytest
from pathlib import Path
from complex_editor.core.app_context import AppContext

has_access = True
try:
    import pyodbc
    pyodbc.connect(r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=:memory:")
except Exception:
    has_access = False


@pytest.mark.skipif(not has_access, reason="Access ODBC driver required")
def test_first_run_creates_valid_mdb(tmp_path):
    db_file = tmp_path / "first_run.mdb"
    ctx = AppContext()
    mdb = ctx.open_main_db(db_file)
    assert db_file.exists() and db_file.stat().st_size > 1_000
    assert mdb.list_complexes() == []

