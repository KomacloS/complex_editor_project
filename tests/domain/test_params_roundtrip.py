import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from complex_editor.util.macro_xml_translator import params_to_xml, xml_to_params


def test_params_roundtrip():
    data = {"GATE": {"StartFreq": "200", "StopFreq": "50000"}}
    xml = params_to_xml(data, encoding="utf-16")
    back = xml_to_params(xml)
    assert back == {"GATE": {"StartFreq": "200", "StopFreq": "50000"}}
