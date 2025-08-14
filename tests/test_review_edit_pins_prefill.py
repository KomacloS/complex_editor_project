import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from complex_editor.io.buffer_loader import WizardPrefill  # noqa: E402

import pytest


@pytest.fixture
def prefilled_wizard(qtbot):
    prefill = WizardPrefill(
        complex_name="CX",
        sub_components=[
            {"macro_name": "RESISTOR", "pins": [1, 2]},
            {"macro_name": "CAPACITOR", "pins": [5, 6]},
            {"macro_name": "GATE", "pins": [9, 10, 8]},
        ],
    )
    wiz = NewComplexWizard.from_wizard_prefill(prefill)
    qtbot.addWidget(wiz)
    return wiz


def test_edit_pins_from_review_prefills_mapping(qtbot, prefilled_wizard):
    review = prefilled_wizard.review_page
    review.table.selectRow(2)
    review.on_edit_pins_clicked()
    mapping = prefilled_wizard.pin_mapping_page
    assert mapping.macro_combo.currentText() == "GATE"
    assert mapping.pad_combo_at_row(0).currentText() == "9"
    assert mapping.pad_combo_at_row(1).currentText() == "10"
    assert mapping.pad_combo_at_row(2).currentText() == "8"
