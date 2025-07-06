from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.complex_editor import ComplexEditor  # noqa: E402
from complex_editor.db.schema_introspect import discover_macro_map  # noqa: E402


class FakeCursorNoTables:
    def tables(self, table=None, tableType=None):
        if False:
            yield

    def columns(self, table):
        raise AssertionError("columns should not be called")

    def execute(self, query):
        raise AssertionError("execute should not be called")


def test_param_loop(qtbot):
    macro_map = discover_macro_map(FakeCursorNoTables())
    editor = ComplexEditor(macro_map)
    qtbot.addWidget(editor)
    macro = macro_map[1]
    editor._build_param_widgets(macro)
    first_count = editor.param_form.rowCount()
    editor._build_param_widgets(macro)
    assert editor.param_form.rowCount() == first_count
    assert len(editor.param_widgets) >= 3
    assert editor.param_form.rowCount() > 1
    for name, widget in editor.param_widgets.items():
        assert name in widget.toolTip()
