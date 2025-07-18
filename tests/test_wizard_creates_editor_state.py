from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from complex_editor.db.schema_introspect import discover_macro_map  # noqa: E402
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from complex_editor.ui.complex_editor import ComplexEditor  # noqa: E402
from complex_editor.domain import ComplexDevice, MacroInstance  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402


class FakeCursorNoTables:
    def tables(self, table=None, tableType=None):
        if False:
            yield

    def columns(self, table):
        raise AssertionError

    def execute(self, query):
        raise AssertionError


def test_wizard_creates_editor_state(qtbot):
    macro_map = discover_macro_map(FakeCursorNoTables())
    qtbot.addWidget(QtWidgets.QWidget())

    wizard = NewComplexWizard(macro_map)
    qtbot.addWidget(wizard)
    wizard.basics_page.pin_spin.setValue(4)
    wizard._next()  # to list
    wizard.list_page.add_btn.click()
    idx = wizard.macro_page.macro_combo.findText("RESISTOR")
    wizard.macro_page.macro_combo.setCurrentIndex(idx)
    wizard.macro_page.pin_table.cellWidget(0, 1).setCurrentText("1")
    wizard.macro_page.pin_table.cellWidget(1, 1).setCurrentText("2")
    wizard._next()  # param -> list
    wizard._next()  # list -> review
    wizard.review_page.save_btn.click()

    pins = [str(p) for p in wizard.sub_components[0].pins]
    rid = next(k for k, m in macro_map.items() if m.name == "RESISTOR")
    dev = ComplexDevice(rid, pins, MacroInstance("RESISTOR", {}))
    editor = ComplexEditor(macro_map)
    qtbot.addWidget(editor)
    editor.load_from_model(dev)
    assert editor.pin_table.pins() == pins
    assert editor.param_form.rowCount() > 1
