import os, sys, types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

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


def test_step_indicator_navigation(qtbot):
    macro_map = discover_macro_map(FakeCursorNoTables())
    wiz = NewComplexWizard(macro_map)
    qtbot.addWidget(wiz)
    # start on basics
    assert wiz.step_indicator.current_index == 0
    # click to subcomponents
    wiz.step_indicator._labels[1].click()
    assert wiz.stack.currentWidget() is wiz.list_page
    assert wiz.step_indicator.current_index == 1
    # clicking parameters step should do nothing
    wiz.step_indicator._labels[2].click()
    assert wiz.stack.currentWidget() is wiz.list_page
    assert wiz.step_indicator.current_index == 1
    # click to review
    wiz.step_indicator._labels[3].click()
    assert wiz.stack.currentWidget() is wiz.review_page
    assert wiz.step_indicator.current_index == 3
