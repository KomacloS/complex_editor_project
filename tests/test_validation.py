from complex_editor_app.core.models import build_sample_catalog
from complex_editor_app.core.validation import parameter_summary, validate_parameters, validate_part_number


def test_validate_part_number():
    assert not validate_part_number("ABC-123")
    errors = validate_part_number("  ")
    assert errors and errors[0].field == "part_number"


def test_validate_parameters_dependencies():
    catalog = build_sample_catalog()
    macro = catalog.get("BufferGate")
    assert macro is not None
    errors = validate_parameters(macro, {"channels": 2, "schmitt": True, "drive_ma": 8})
    assert any(err.field == "drive_ma" for err in errors)


def test_parameter_summary_truncates():
    catalog = build_sample_catalog()
    macro = catalog.get("Resistor")
    assert macro is not None
    summary, tooltip = parameter_summary(macro, {"value": 4700.0, "tolerance": "0.1%"}, width=10)
    assert summary.endswith("…")
    assert "0.1%" in tooltip
