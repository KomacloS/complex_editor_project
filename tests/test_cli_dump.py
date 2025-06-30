from __future__ import annotations

import types
import os
import sys
import types as py_types

sys.modules.setdefault("pyodbc", py_types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor import cli  # noqa: E402
from complex_editor.db import access_driver  # noqa: E402


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
            return [(1, "MACRO1"), (2, "MACRO2")]
        return [
            (1, "P1", "INT", "0", "0", "10"),
            (1, "P2", "BOOL", None, None, None),
            (2, "Q", "ENUM", "A", None, None),
        ]


class FakeConnection:
    def cursor(self):
        return FakeCursor()


def fake_connect(path):
    return FakeConnection()


def test_dump_macros_all(monkeypatch, capsys):
    monkeypatch.setattr(access_driver, "connect", fake_connect)
    monkeypatch.setattr(cli, "connect", fake_connect)
    exit_code = cli.main(["dump-macros", "dummy.mdb"])
    assert exit_code == 0
    out_lines = capsys.readouterr().out.strip().splitlines()
    assert out_lines[0].startswith("1\tMACRO1\t2")
    assert out_lines[1].startswith("2\tMACRO2\t1")


def test_dump_macros_one(monkeypatch, capsys):
    monkeypatch.setattr(access_driver, "connect", fake_connect)
    monkeypatch.setattr(cli, "connect", fake_connect)
    exit_code = cli.main(["dump-macros", "dummy.mdb", "--id", "1"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "P1" in out and "INT" in out

