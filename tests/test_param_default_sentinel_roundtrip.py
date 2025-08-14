import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from complex_editor.util.macro_xml_translator import xml_to_params, params_to_xml


def test_param_default_sentinel_roundtrip() -> None:
    xml = (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<R><Macros>'
        '<Macro Name="POWER_CHECK"><Param Name="Value" Value="Default"/></Macro>'
        '</Macros></R>'
    ).encode('utf-16')
    params = xml_to_params(xml)
    assert params['POWER_CHECK']['Value'] == 'Default'
    rebuilt = params_to_xml(params)
    again = xml_to_params(rebuilt)
    assert again['POWER_CHECK']['Value'] == 'Default'
