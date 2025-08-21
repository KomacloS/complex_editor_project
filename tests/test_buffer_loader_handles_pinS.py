import json
from pathlib import Path

from complex_editor.ui.buffer_loader import load_editor_complexes_from_buffer


def _make_xml():
    return (
        '<?xml version="1.0"?><R><Macros><Macro Name="FAN">'
        '<Param Name="Speed" Value="3"/></Macro></Macros></R>'
    )


def test_loads_params_from_PinS_key(tmp_path: Path):
    xml = _make_xml()
    buf = [
        {
            "id": 1,
            "name": "DEV",
            "pins": ["1"],
            "subcomponents": [
                {
                    "function_name": "FAN",
                    "pins": {"A": "1", "PinS": xml},
                }
            ],
        }
    ]
    path = tmp_path / "buf.json"
    path.write_text(json.dumps(buf), encoding="utf-8")

    complexes = load_editor_complexes_from_buffer(path)
    sc = complexes[0].subcomponents[0]
    assert sc.macro_params.get("Speed") == "3"


def test_loads_params_from_top_level_S(tmp_path: Path):
    xml = _make_xml()
    buf = [
        {
            "id": 1,
            "name": "DEV",
            "pins": ["1"],
            "subcomponents": [
                {
                    "function_name": "FAN",
                    "S": xml,
                    "pins": {"A": "1"},
                }
            ],
        }
    ]
    path = tmp_path / "buf.json"
    path.write_text(json.dumps(buf), encoding="utf-8")

    complexes = load_editor_complexes_from_buffer(path)
    sc = complexes[0].subcomponents[0]
    assert sc.macro_params.get("Speed") == "3"


def test_skips_74cx08m(tmp_path: Path):
    xml = _make_xml()
    buf = [
        {
            "id": 1,
            "name": "DEV",
            "pins": ["1"],
            "subcomponents": [
                {
                    "function_name": "74CX08M",
                    "pins": {"A": "1", "S": xml},
                }
            ],
        }
    ]
    path = tmp_path / "buf.json"
    path.write_text(json.dumps(buf), encoding="utf-8")

    complexes = load_editor_complexes_from_buffer(path)
    sc = complexes[0].subcomponents[0]
    assert sc.macro_params == {}
