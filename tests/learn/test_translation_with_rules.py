import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from complex_editor.learn.spec import LearnedRules, LearnedParam
from complex_editor.util.macro_xml_translator import xml_to_params_tolerant


def test_translation_with_rules():
    rules = LearnedRules(
        macro_aliases={"G_A_T_E": "GATE"},
        per_macro={
            "GATE": LearnedParam(
                param_aliases={"Start_Freq": "StartFreq"},
                enum_extra_values={"FAST"},
            )
        },
    )
    xml = (
        "<R><Macros><Macro Name='G_A_T_E'>"
        "<Param Name='Start_Freq' Value='1,25'/><Param Name='Mode' Value='FAST'/></Macro>"
        "</Macros></R>"
    )
    res = xml_to_params_tolerant(xml, rules=rules)
    assert "GATE" in res
    assert res["GATE"]["StartFreq"] == "1.25"
    assert res["GATE"]["Mode"] == "FAST"

