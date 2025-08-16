from __future__ import annotations

import os, sys
import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.param_spec import ALLOWED_PARAMS
from complex_editor.util.macro_xml_translator import xml_to_params, params_to_xml


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


def test_params_to_xml_skips_defaults() -> None:
    macros = {"FAN": {"BurstNr": "0", "StartFreq": "0", "StopFreq": "50000"}}
    xml = params_to_xml(macros, schema=ALLOWED_PARAMS)
    text = xml.decode("utf-16")
    assert "BurstNr" not in text
    assert "StartFreq" not in text
    assert '<Param Name="StopFreq" Value="50000"' in text


def test_gate_check_length_validation() -> None:
    with pytest.raises(ValueError):
        params_to_xml({"GATE": {"PathPin_A": "0101", "Check_A": "11"}})
    xml = params_to_xml({"GATE": {"PathPin_A": "0101", "Check_A": "1111"}})
    assert '<Param Name="Check_A" Value="1111"' in xml.decode("utf-16")
    xml2 = params_to_xml({"GATE": {"PathPin_A": "0101"}})
    assert "Check_A" not in xml2.decode("utf-16")
