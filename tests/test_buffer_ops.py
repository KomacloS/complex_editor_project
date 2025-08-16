import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from complex_editor.ui.buffer_ops import format_pins


def test_format_pins_skips_s_and_orders() -> None:
    pins = {"B": "2", "A": "1", "S": "<xml>", "H": "8", "J": "10"}
    assert format_pins(pins) == "A=1, B=2, H=8, J=10"
