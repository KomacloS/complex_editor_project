from __future__ import annotations

import os
import sys
import types

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.domain import ComplexDevice, MacroInstance  # noqa: E402
from complex_editor.services import export_service  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        self.last_query = query
        return self

    def scalar(self):
        return 10


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def cursor(self):
        return self.cursor_obj


def test_insert_complex(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(export_service, "table_exists", lambda c, t: True)
    dev = ComplexDevice(
        id_function=42,
        pins=["A1", "B2", "C3", "D4"],
        macro=MacroInstance("GATE", {"PathPin_A": "0101"}),
    )
    new_id = export_service.insert_complex(conn, dev)
    assert new_id == 11
    assert "SELECT MAX" in conn.cursor_obj.calls[0][0]
    insert_sql, params = conn.cursor_obj.calls[1]
    assert "INSERT INTO tabCompDesc" in insert_sql
    xml_blob = params[-1]
    assert xml_blob.decode("utf-16le").startswith("<?xml")
