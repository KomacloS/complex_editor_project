import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from mdb_comm.macro_xml_translator import xml_to_params, params_to_xml


def test_param_alias_roundtrip():
    xml = (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<R><Macros><Macro Name="VOLTAGE_REG">'
        '<Param Name="InVolt" Value="5" />'
        '</Macro></Macros></R>'
    ).encode("utf-16")
    params = xml_to_params(xml)
    assert params["VOLTAGEREGULATOR"]["Value"] == "5"
    new_xml = params_to_xml({"VOLTAGEREGULATOR": {"Value": 5}})
    txt = new_xml.decode("utf-16")
    assert 'Name="InVolt" Value="5"' in txt
