import os, sys, types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.widgets.step_indicator import StepIndicator


def test_step_indicator(qtbot):
    ind = StepIndicator(["Basics", "Subcomponents", "Parameters", "Review"])
    qtbot.addWidget(ind)
    ind.set_current(2)
    assert ind.current_index == 2
    assert "background" in ind._labels[2].styleSheet()
