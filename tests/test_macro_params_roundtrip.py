import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from complex_editor.util.macro_xml_translator import xml_to_params, params_to_xml


def test_macro_params_roundtrip() -> None:
    sample = (
        '<?xml version="1.0" encoding="utf-16"?>\n'
        '<R><Macros>'
        '<Macro Name="RELAIS"><Param Name="PowerCoil" Value="0"/></Macro>'
        '<Macro Name="ALT"><Param Name="Foo" Value="1"/></Macro>'
        '</Macros></R>'
    ).encode("utf-16")
    params = xml_to_params(sample)
    assert params["RELAIS"]["PowerCoil"] == "0"
    params["RELAIS"]["PowerCoil"] = "2"
    xml = params_to_xml(params)
    again = xml_to_params(xml)
    assert again["RELAIS"]["PowerCoil"] == "2"
    assert again["ALT"]["Foo"] == "1"
