import os, sys, json, types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.new_complex_wizard import NewComplexWizard
from complex_editor.io.buffer_loader import WizardPrefill


def test_buffer_preload(qtbot):
    path = os.path.join(os.path.dirname(__file__), "..", "tools", "buffer.json")
    with open(path, encoding="utf-8") as f:
        complexes = json.load(f)["complexes"]
    sc = None
    for cx in complexes:
        for sub in cx["subcomponents"]:
            if "S" in sub.get("pins", {}):
                sc = sub
                break
        if sc:
            break
    assert sc is not None
    s_xml = sc["pins"]["S"]
    pin_letters = [k for k in sorted(sc["pins"].keys()) if k in {"A", "B", "C", "D"}]
    pins = [int(sc["pins"][k]) for k in pin_letters]
    prefill = WizardPrefill(
        complex_name="CX",
        sub_components=[
            {
                "macro_name": sc["function_name"],
                "id_function": sc["id_function"],
                "pins": pins,
                "pins_s": s_xml,
            }
        ],
    )
    wiz = NewComplexWizard.from_wizard_prefill(prefill)
    qtbot.addWidget(wiz)
    wiz.activate_pin_mapping_for(0)
    wiz._open_param_page()
    assert wiz.param_page.warn_label.isHidden()
    assert wiz.sub_components[0].macro.params != {}
