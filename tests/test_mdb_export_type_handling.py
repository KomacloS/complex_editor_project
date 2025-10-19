from __future__ import annotations

import json
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Sequence

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pytest  # type: ignore

from complex_editor.db.mdb_api import _validate_and_coerce_for_access, DataMismatch
from complex_editor.db import pn_exporter


class _FakeCol:
    def __init__(self, name: str, type_name: str, size: int | None, digits: int | None, nullable: int = 1):
        self.COLUMN_NAME = name
        self.TYPE_NAME = type_name
        self.COLUMN_SIZE = size
        self.DECIMAL_DIGITS = digits
        self.NULLABLE = nullable


class _FakeCursor:
    def __init__(self, cols: Sequence[_FakeCol]):
        self._cols = list(cols)

    def columns(self, table: str):  # pragma: no cover - simple generator
        for c in self._cols:
            yield c


def test_validate_and_coerce_numeric_and_text_and_date():
    cur = _FakeCursor(
        [
            _FakeCol("IDCompDesc", "INTEGER", 10, None, 0),
            _FakeCol("Value", "TEXT", 8, None, 1),
            _FakeCol("TolP", "DOUBLE", 8, 3, 1),
            _FakeCol("Enabled", "BIT", None, None, 1),
            _FakeCol("When", "DATETIME", None, None, 1),
        ]
    )
    cols = ["IDCompDesc", "Value", "TolP", "Enabled", "When"]
    vals = ["123", "ABCDEFGHIJK", "12.34", "true", "2024-10-01 12:34:56"]
    out_cols, coerced, actions = _validate_and_coerce_for_access(cur, "detCompDesc", cols, vals)
    assert list(out_cols) == cols
    assert coerced[0] == 123  # int
    assert isinstance(coerced[2], float) and abs(coerced[2] - 12.34) < 1e-9
    assert coerced[3] in (1, 0)
    # Value truncated to 8 chars
    assert coerced[1] == "ABCDEFGH"
    assert any(a.get("action") == "truncate" and a.get("col") == "Value" for a in actions)


def test_validate_and_coerce_unparseable_raises():
    cur = _FakeCursor([_FakeCol("TolP", "DOUBLE", 8, 3, 1)])
    with pytest.raises(DataMismatch):
        _validate_and_coerce_for_access(cur, "detCompDesc", ["TolP"], ["abc"])


def test_bridge_handles_pyodbc_data_error_without_typeerror(monkeypatch, tmp_path):
    # Simulate DataError raised inside export path
    try:
        import pyodbc  # type: ignore
    except Exception:  # pragma: no cover - environment without pyodbc
        pytest.skip("pyodbc not available")

    class FakeMDB:
        def __init__(self, path: Path):
            self.path = Path(path)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_complexes(self):
            return [(5087, "PN5087", 0)]

        def get_aliases(self, comp_id: int) -> List[str]:
            return []

        def create_complex(self, device):
            # Raise a DataError similar to 22018
            raise pyodbc.DataError("22018", "[Microsoft][ODBC Microsoft Access Driver] Data type mismatch in criteria expression.")

        def get_complex(self, comp_id: int):
            class _Dev:
                def __init__(self):
                    self.id_comp_desc = comp_id
                    self.name = f"PN{comp_id}"
                    self.total_pins = 0
                    self.subcomponents = []
                    self.aliases = []

            return _Dev()

    # Patch pn_exporter.MDB used during collection and export
    monkeypatch.setattr(pn_exporter, "MDB", FakeMDB)

    template = ROOT / "src" / "complex_editor" / "assets" / "Empty_mdb.mdb"
    if not template.exists():  # pragma: no cover - guard for CI env
        pytest.skip("template MDB not found")

    out = tmp_path / "out.mdb"
    with pytest.raises(pn_exporter.SubsetExportError) as ei:
        pn_exporter.export_pn_to_mdb(
            source_db_path=template,
            template_path=template,
            target_path=out,
            pn_list=["PN5087"],
            options=pn_exporter.ExportOptions(),
        )
    err = ei.value
    assert err.reason == "db_engine_error"
    payload = err.payload
    # Ensure payload is structured and no follow-on TypeError occurred
    assert "detail" in payload
    # Our enhancement should hint table and mismatch
    assert payload.get("offending_table", "").lower() in ("detcompdesc", "")
