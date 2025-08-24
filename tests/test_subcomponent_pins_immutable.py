from complex_editor.domain import MacroInstance, SubComponent
import pytest

def test_subcomponent_pins_are_immutable():
    sc = SubComponent(MacroInstance("GATE", {}), [1, 2])
    with pytest.raises(TypeError):
        sc.pins[0] = 3
