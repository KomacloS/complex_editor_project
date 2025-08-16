import os, sys, types
from pathlib import Path

import pytest

# Ensure dependencies stubbed and modules discoverable
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from complex_editor.db.mdb_api import ComplexDevice, SubComponent  # noqa: E402
from complex_editor.ui.adapters import to_editor_model  # noqa: E402


class DummyDB:
    def list_functions(self):
        return [(1, "FAN")]


def test_pin_s_translation_error_flag() -> None:
    sc = SubComponent(
        id_sub_component=1,
        id_function=1,
        value="",
        id_unit=None,
        tol_p=None,
        tol_n=None,
        force_bits=None,
        pins={"A": 1, "B": 2, "S": "<not xml>"},
    )
    cx = ComplexDevice(id_comp_desc=1, name="CX", total_pins=2, subcomponents=[sc])
    model = to_editor_model(DummyDB(), cx)
    assert model.subcomponents[0].pin_s_error
