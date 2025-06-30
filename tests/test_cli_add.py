from __future__ import annotations

import os
import sys
import types
from pathlib import Path

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor import cli  # noqa: E402
from complex_editor.db import access_driver  # noqa: E402
from complex_editor.services import export_service  # noqa: E402


class FakeConnection:
    def __init__(self):
        self.autocommit = True
        self.committed = False
        self.closed = False

    def cursor(self):
        return object()

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_cli_add(monkeypatch, capsys):
    conn = FakeConnection()
    backup_calls: list[Path] = []
    insert_calls = []

    monkeypatch.setattr(access_driver, "connect", lambda path: conn)
    monkeypatch.setattr(cli, "connect", lambda path: conn)
    monkeypatch.setattr(access_driver, "make_backup", lambda path: backup_calls.append(Path(path)))
    monkeypatch.setattr(cli, "make_backup", lambda path: backup_calls.append(Path(path)))
    monkeypatch.setattr(export_service, "insert_complex", lambda c, d: (insert_calls.append((c, d)) or 123))
    monkeypatch.setattr(cli, "insert_complex", lambda c, d: export_service.insert_complex(c, d))

    exit_code = cli.main([
        "add-complex",
        "dummy.mdb",
        "--idfunc",
        "42",
        "--pins",
        "A1",
        "B2",
        "C3",
        "D4",
        "--macro",
        "GATE",
        "--param",
        "PathPin_A=0101",
        "--param",
        "PathPin_B=HLHL",
    ])

    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    assert out == "Inserted complex 123 (macro GATE)"
    assert backup_calls and backup_calls[0] == Path("dummy.mdb")
    assert insert_calls and insert_calls[0][0] is conn
