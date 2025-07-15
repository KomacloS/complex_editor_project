from __future__ import annotations

import os
import sys
import types

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from complex_editor.db.schema_introspect import discover_macro_map  # noqa: E402


class C:
    def tables(self, **kw):
        return iter([])

    def columns(self, *a, **k):
        raise AssertionError

    def execute(self, q):
        raise AssertionError


def test_macro_yaml_loaded():
    mm = discover_macro_map(C())
    by_name = {m.name: m for m in mm.values()}
    assert "VOLTAGE_REGULATOR" in by_name
    assert "RESISTOR" in by_name
    assert by_name["RESISTOR"].params
