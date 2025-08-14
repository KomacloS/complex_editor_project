from __future__ import annotations

import os, sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.adapters import to_editor_model
from complex_editor.utils.macro_xml_translator import params_to_xml


def test_adapter_populates_macro_params() -> None:
    macros = {"RELAIS": {"PowerCoil": "0"}, "ALT": {"Foo": "1"}}
    xml = params_to_xml(macros).decode("utf-16")
    sc = SimpleNamespace(id_function=16, pins={"A": "1", "B": "2", "S": xml})
    cx = SimpleNamespace(
        total_pins=2, subcomponents=[sc], id_comp_desc=1, name="CX"
    )
    db = SimpleNamespace(list_functions=lambda: [(16, "RELAIS")])

    model = to_editor_model(db, cx)
    assert len(model.subcomponents) == 1
    sub = model.subcomponents[0]
    assert sub.selected_macro == "RELAIS"
    assert sub.macro_params == {"PowerCoil": "0"}
    assert "ALT" in sub.all_macros

    sub.selected_macro = "ALT"
    sub.macro_params = sub.all_macros["ALT"]
    assert sub.macro_params == {"Foo": "1"}
