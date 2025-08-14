import os, sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PyQt6 import QtWidgets
from complex_editor.ui.widgets.step_indicator import StepIndicator


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_step_indicator_highlight(qapp):
    widget = StepIndicator(["A", "B", "C", "D"])
    widget.set_current(2)
    assert widget._current == 2
    assert "font-weight:bold" in widget._labels[2].styleSheet()
    assert "font-weight:bold" not in widget._labels[1].styleSheet()
