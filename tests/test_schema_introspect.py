from __future__ import annotations

import os
import sys
import types
import types as py_types

# Provide a dummy pyodbc module so import succeeds
sys.modules.setdefault("pyodbc", py_types.ModuleType("pyodbc"))

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from complex_editor.db.schema_introspect import discover_macro_map  # noqa: E402


class FakeCursor:
    def tables(self, table=None, tableType=None):
        yield types.SimpleNamespace(table_name="tabFunction")
        yield types.SimpleNamespace(table_name="tabFuncMacro")

    def columns(self, table):
        if table == "tabFunction":
            cols = ["IDFunction", "MacroName"]
        else:
            cols = [
                "IDFunction",
                "ParamName",
                "ParamType",
                "DefValue",
                "MinValue",
                "MaxValue",
            ]
        for c in cols:
            yield types.SimpleNamespace(column_name=c)

    def execute(self, query):
        self.last_query = query
        return self

    def fetchall(self):
        if "tabFunction" in self.last_query:
            return [(1, "MACRO1")]
        return [
            (1, "P1", "INT", "1", "0", "10"),
            (1, "P2", "BOOL", None, None, None),
        ]


def test_discover_macro_map():
    result = discover_macro_map(FakeCursor())
    assert 1 in result
    macro = result[1]
    assert macro.name == "MACRO1"
    assert len(macro.params) == 2
    assert macro.params[0].name == "P1"
    assert macro.params[0].type == "INT"
    assert macro.params[0].default == "1"
    assert macro.params[0].min == "0"
    assert macro.params[0].max == "10"
    assert macro.params[1].name == "P2"
    assert macro.params[1].type == "BOOL"
