from __future__ import annotations

import os
import sys
import types

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.db.schema_introspect import discover_macro_map  # noqa: E402


class EmptyCursor:
    def tables(self, table=None, tableType=None):
        if False:
            yield

    def columns(self, table):
        raise AssertionError("columns should not be called")

    def execute(self, query):
        raise AssertionError("execute should not be called")


def test_fallback_macro():
    result = discover_macro_map(EmptyCursor())
    assert result
    assert any(m.name == "RESISTOR" for m in result.values())
