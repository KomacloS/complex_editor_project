from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.utils.macro_xml_translator import xml_to_params, params_to_xml


def test_parse_sample_pins_s() -> None:
    sample = (
        '<?xml version="1.0" encoding="utf-16"?>\n'
        '<R><Macros><Macro Name="RELAIS">'
        '<Param Name="PowerCoil" Value="0"/>'
        '</Macro></Macros></R>'
    ).encode("utf-16")
    params = xml_to_params(sample)
    assert "RELAIS" in params
    assert params["RELAIS"]["PowerCoil"] == "0"


def test_roundtrip_utf16() -> None:
    macros = {"RELAIS": {"PowerCoil": "0"}, "ALT": {"Foo": "1"}}
    xml = params_to_xml(macros)
    parsed = xml_to_params(xml)
    assert parsed == macros
