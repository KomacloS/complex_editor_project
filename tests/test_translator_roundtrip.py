import os, sys
from pathlib import Path
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from mdb_comm.macro_selector import load_rules
from mdb_comm import macro_xml_translator as mxt

DATA = Path(__file__).resolve().parent.parent / 'src' / 'mdb_comm' / 'data'

def test_translator_roundtrip() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    ctx = {'HWSET': 3}
    params = {'RELAIS': {'PowerCoil': '0'}}
    xml = mxt.params_to_xml(params, ctx=ctx, rules=rules)
    text = xml.decode('utf-16')
    assert '<Macro Name="RELAY2"' in text
    inv_map = yaml.safe_load((DATA / 'xml_macro_to_function_map.yaml').read_text())
    parsed = mxt.xml_to_params(xml, inv_map=inv_map)
    assert 'RELAIS' in parsed
