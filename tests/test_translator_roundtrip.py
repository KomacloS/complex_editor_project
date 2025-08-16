import os, sys
from pathlib import Path
import yaml
import pytest

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


def test_fan_roundtrip() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    params = {'FAN': {'BurstNr': '5', 'StartFreq': '200', 'StopFreq': '50000'}}
    xml = mxt.params_to_xml(params, ctx={}, rules=rules)
    text = xml.decode('utf-16')
    assert '<Macro Name="FNODE"' in text
    inv_map = yaml.safe_load((DATA / 'xml_macro_to_function_map.yaml').read_text())
    parsed = mxt.xml_to_params(xml, inv_map=inv_map)
    assert 'FAN' in parsed
    assert parsed['FAN']['BurstNr'] == '5'


def test_params_to_xml_skips_defaults() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    params = {'FAN': {'BurstNr': '0', 'StartFreq': '0', 'StopFreq': '50000'}}
    xml = mxt.params_to_xml(params, ctx={}, rules=rules)
    text = xml.decode('utf-16')
    assert 'BurstNr' not in text
    assert 'StartFreq' not in text
    assert '<Param Name="StopFreq"' in text


def test_gate_check_length_validation() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    params = {'GATE': {'PathPin_A': '0101', 'Check_A': '11'}}
    with pytest.raises(ValueError):
        mxt.params_to_xml(params, ctx={}, rules=rules)
    params_ok = {'GATE': {'PathPin_A': '0101', 'Check_A': '1111'}}
    xml = mxt.params_to_xml(params_ok, ctx={}, rules=rules)
    text = xml.decode('utf-16')
    assert '<Param Name="Check_A" Value="1111"' in text
    params_empty = {'GATE': {'PathPin_A': '0101'}}
    xml2 = mxt.params_to_xml(params_empty, ctx={}, rules=rules)
    assert 'Check_A' not in xml2.decode('utf-16')
