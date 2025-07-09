from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

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


def test_next_disabled_until_pin_checked(qtbot):
    macro_map = discover_macro_map(FakeCursorNoTables())
    wiz = NewComplexWizard(macro_map)
    qtbot.addWidget(wiz)
    wiz.basics_page.pin_spin.setValue(4)
    wiz._next()  # to list
    wiz.list_page.add_btn.click()
    assert not wiz.next_btn.isEnabled()
    wiz.macro_page.pin_table.cellWidget(0, 1).setValue(1)
    wiz._update_nav()
    assert wiz.next_btn.isEnabled()
    wiz.macro_page.pin_table.cellWidget(1, 1).setValue(1)
    wiz._update_nav()
    assert not wiz.next_btn.isEnabled()
    wiz.macro_page.pin_table.cellWidget(1, 1).setValue(2)
    wiz._update_nav()
    assert wiz.next_btn.isEnabled()
