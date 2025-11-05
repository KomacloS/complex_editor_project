import pytest

from complex_editor_app.core.pins import PinParseError, Row, parse_pin_field, validate_pins


def test_parse_pin_field_accepts_tokens():
    assert parse_pin_field("") == []
    assert parse_pin_field("NC") == []
    assert parse_pin_field("1,3,5") == [1, 3, 5]
    assert parse_pin_field("2-4") == [2, 3, 4]


def test_parse_pin_field_invalid_token():
    with pytest.raises(PinParseError):
        parse_pin_field("abc")


def test_validate_pins_detects_conflicts():
    rows = [
        Row(index=1, macro="Resistor", pins={"A": [1], "B": [], "C": [], "D": []}),
        Row(index=2, macro="Resistor", pins={"A": [1], "B": [], "C": [], "D": []}),
    ]
    errors = validate_pins(rows, pin_count=10)
    assert errors
    assert any("reused" in err.message for err in errors)


def test_validate_pins_out_of_range():
    rows = [Row(index=1, macro="LED", pins={"A": [99], "B": [], "C": [], "D": []})]
    errors = validate_pins(rows, pin_count=5)
    assert errors
    assert errors[0].column == "A"
