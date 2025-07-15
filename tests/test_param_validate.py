from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets  # noqa: E402
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from complex_editor.db.schema_introspect import discover_macro_map  # noqa: E402


class FakeCursorNoTables:
    def tables(self, table=None, tableType=None):
        if False:
            yield

    def columns(self, table):
        raise AssertionError

    def execute(self, query):
        raise AssertionError


def test_validation_and_overrides(qtbot):
    macro_map = discover_macro_map(FakeCursorNoTables())
    wiz = NewComplexWizard(macro_map)
    qtbot.addWidget(wiz)
    wiz.basics_page.pin_spin.setValue(4)
    wiz._next()
    wiz.list_page.add_btn.click()
    idx = wiz.macro_page.macro_combo.findText("CAPACITOR")
    wiz.macro_page.macro_combo.setCurrentIndex(idx)
    wiz.macro_page.pin_table.cellWidget(0, 1).setCurrentText("1")
    wiz.macro_page.pin_table.cellWidget(1, 1).setCurrentText("2")
    wiz._next()
    spin = wiz.param_page.widgets.get("Value")
    assert isinstance(spin, QtWidgets.QSpinBox)
    spin.setValue(1)
    wiz.param_page._validate()
    assert spin.styleSheet() == ""
    assert wiz.next_btn.isEnabled()
    wiz._next()
    assert wiz.sub_components[0].macro.overrides == [("Value", "1")]

    wiz.list_page.add_btn.click()
    wiz.macro_page.macro_combo.setCurrentIndex(idx)
    wiz.macro_page.pin_table.cellWidget(0, 1).setCurrentText("3")
    wiz.macro_page.pin_table.cellWidget(1, 1).setCurrentText("4")
    wiz._next()
    wiz._next()
    assert wiz.sub_components[1].macro.overrides == []

