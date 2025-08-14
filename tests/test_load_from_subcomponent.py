import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from complex_editor.db.schema_introspect import discover_macro_map
from complex_editor.domain import MacroInstance, SubComponent
from complex_editor.ui.new_complex_wizard import MacroPinsPage


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_load_from_subcomponent_falls_back_to_name(qapp):
    macro_map = discover_macro_map(None)
    page = MacroPinsPage(macro_map)
    fan_id = next(fid for fid, m in macro_map.items() if m.name == "FAN")
    solder_id = next(fid for fid, m in macro_map.items() if m.name == "SOLDERING")
    mi = MacroInstance("FAN", {})
    mi.id_function = solder_id  # wrong id on purpose
    sc = SubComponent(mi, [1, 2])
    page.load_from_subcomponent(sc)
    assert page.macro_combo.currentText() == "FAN"
