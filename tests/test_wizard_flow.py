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


def test_wizard_flow(qtbot):
    macro_map = discover_macro_map(FakeCursorNoTables())
    wizard = NewComplexWizard(macro_map)
    qtbot.addWidget(wizard)
    wizard.basics_page.pin_spin.setValue(4)
    wizard._next()  # to list page
    wizard.list_page.add_btn.click()
    idx = wizard.macro_page.macro_combo.findText("RESISTOR")
    wizard.macro_page.macro_combo.setCurrentIndex(idx)
    wizard.macro_page.pin_table.cellWidget(0, 1).setCurrentText("1")
    wizard.macro_page.pin_table.cellWidget(1, 1).setCurrentText("2")
    wizard._next()
    val_widget = wizard.param_page.widgets.get("Value")
    if isinstance(val_widget, QtWidgets.QSpinBox):
        val_widget.setValue(10)
    wizard._next()  # save params back to list
    wizard.list_page.list.setCurrentRow(0)
    wizard.list_page.dup_btn.click()
    wizard.macro_page.pin_table.cellWidget(0, 1).setCurrentText("3")
    wizard.macro_page.pin_table.cellWidget(1, 1).setCurrentText("4")
    wizard._next()
    val_widget2 = wizard.param_page.widgets.get("Value")
    if isinstance(val_widget2, QtWidgets.QSpinBox):
        assert val_widget2.value() == 10
    wizard._next()
    wizard._next()  # list -> review
    wizard.review_page.save_btn.click()

    assert len(wizard.sub_components) == 2
    assert wizard.sub_components[0].pins == (1, 2)
    assert wizard.sub_components[1].pins == (3, 4)
    assert wizard.sub_components[0].macro.params == wizard.sub_components[1].macro.params
