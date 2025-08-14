from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.util.macro_xml_translator import xml_to_params, params_to_xml


def test_macro_params_roundtrip() -> None:
    sample = (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<R><Macros>'
        '<Macro Name="DIODE"><Param Name="Current" Value="10e-3"/></Macro>'
        '<Macro Name="ZENER"><Param Name="Value" Value="1"/></Macro>'
        '</Macros></R>'
    ).encode("utf-16")
    params = xml_to_params(sample)
    assert params["DIODE"]["Current"] == "10e-3"
    params["ZENER"]["Value"] = "2"
    rebuilt = params_to_xml(params)
    again = xml_to_params(rebuilt)
    assert again["ZENER"]["Value"] == "2"
    assert again["DIODE"]["Current"] == "10e-3"
