import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.domain.models import MacroDef, MacroParam
from complex_editor.ui.dialogs.macro_params_dialog import MacroParamsDialog


def test_macro_params_dialog_roundtrip(qtbot):
    macro = MacroDef(
        id_function=1,
        name="T",
        params=[
            MacroParam("COUNT", "INT", "0", "0", "10"),
            MacroParam("FLAG", "BOOL", "0", None, None),
        ],
    )
    dlg = MacroParamsDialog(macro, {"COUNT": "5"})
    qtbot.addWidget(dlg)
    dlg._widgets["COUNT"].setValue(3)
    dlg._widgets["FLAG"].setChecked(True)
    dlg._on_accept()
    assert dlg.values() == {"COUNT": "3", "FLAG": "1"}
