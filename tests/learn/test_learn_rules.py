import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from complex_editor.domain import MacroDef, MacroParam
from complex_editor.learn.learner import learn_from_rows


def test_learn_rules_macro_param_alias():
    macro_map = {
        1: MacroDef(
            1,
            "GATE",
            [
                MacroParam("StartFreq", "INT", None, None, None),
                MacroParam("Mode", "ENUM", "SLOW;MED", None, None),
            ],
        )
    }
    xml = (
        "<R><Macros><Macro Name='G_A_T_E'>"
        "<Param Name='Start_Freq' Value='1'/><Param Name='Mode' Value='FAST'/></Macro>"
        "</Macros></R>"
    )
    rules = learn_from_rows([("", xml)], macro_map)
    assert rules.macro_aliases["G_A_T_E"] == "GATE"
    assert rules.per_macro["GATE"].param_aliases["Start_Freq"] == "StartFreq"

