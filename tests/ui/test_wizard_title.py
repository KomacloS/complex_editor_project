import os, sys, types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402


def test_wizard_title_default(qtbot):
    wiz = NewComplexWizard(None)
    qtbot.addWidget(wiz)
    assert wiz.windowTitle() == "New Complex"


def test_wizard_title_custom(qtbot):
    wiz = NewComplexWizard(None, title="LM358M")
    qtbot.addWidget(wiz)
    assert wiz.windowTitle() == "LM358M"
