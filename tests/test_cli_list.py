from __future__ import annotations

import types

import os
import sys
import types as py_types

# Provide a dummy pyodbc module so import succeeds
sys.modules.setdefault("pyodbc", py_types.ModuleType("pyodbc"))

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from complex_editor import cli  # noqa: E402
from complex_editor.db import access_driver  # noqa: E402


class FakeCursor:
    def tables(self, table=None, tableType=None):
        if table is not None:
            if table == "tabCompDesc":
                yield types.SimpleNamespace(table_name="tabCompDesc")
            return
        yield types.SimpleNamespace(table_name="tabCompDesc")
        yield types.SimpleNamespace(table_name="tabFunction")

    def columns(self, table):
        if table == "tabCompDesc":
            cols = [
                "IDCompDesc",
                "IDFunction",
                "PinA",
                "PinB",
                "PinC",
                "PinD",
                "PinS",
            ]
        else:
            cols = ["IDFunction", "MacroName"]
        for c in cols:
            yield types.SimpleNamespace(column_name=c)

    def execute(self, query):
        self.last_query = query
        return self

    def fetchall(self):
        if "tabFunction" in self.last_query:
            return [(1, "MACRO1"), (2, "MACRO2")]
        return [
            (1, 1, "A1", "B1", "C1", "D1", "<xml>"),
            (2, 3, "A2", "B2", "C2", "D2", None),
        ]

    def fetchmany(self, num):
        return self.fetchall()[:num]


class FakeConnection:
    def cursor(self):
        return FakeCursor()


def fake_connect(path):
    return FakeConnection()


def test_list_complexes(monkeypatch, capsys):
    monkeypatch.setattr(access_driver, "connect", fake_connect)
    monkeypatch.setattr(cli, "connect", fake_connect)
    exit_code = cli.main(["list-complexes", "dummy.mdb", "--limit", "1"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "MACRO1" in out
