import os, sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from mdb_comm.macro_selector import load_rules, eval_criteria, choose_macro

DATA = Path(__file__).resolve().parent.parent / 'src' / 'mdb_comm' / 'data'

def test_eval_criteria_numeric() -> None:
    assert eval_criteria('?HWSET>=2', {'HWSET': 2})

def test_eval_criteria_version() -> None:
    assert eval_criteria('?BRDVIVAVER<11.0.0.0', {'BRDVIVAVER': '10.9.0.0'})

def test_choose_macro_mosfet() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    assert choose_macro('MOSFET', {'HWSET': 1}, rules) == 'TRANSISTOR'
    assert choose_macro('MOSFET', {'HWSET': 2}, rules) == 'TRANSISTOR2'

def test_choose_macro_relais() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    assert choose_macro('RELAIS', {'HWSET': 1}, rules) == 'RELAIS'
    assert choose_macro('RELAIS', {'HWSET': 3}, rules) == 'RELAY2'

def test_choose_macro_transistor_version() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    assert choose_macro('TRANSISTOR', {'BRDVIVAVER': '10.9.0.0'}, rules) == 'TRANSISTOR'
    assert choose_macro('TRANSISTOR', {'BRDVIVAVER': '11.2.0.0'}, rules) == 'DIODE_BE'

def test_ignore_selection_criteria() -> None:
    rules = load_rules(DATA / 'macro_selection_rules.yaml')
    assert choose_macro('LEDCHECK_CONF', {}, rules) == 'LEDCHECK_CONF'
