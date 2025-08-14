from __future__ import annotations

import json
import os, sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.buffer_persistence import load_buffer, save_buffer
from complex_editor.utils.macro_xml_translator import xml_to_params, params_to_xml


def test_buffer_roundtrip(tmp_path: Path) -> None:
    macros = {"RELAIS": {"PowerCoil": "0"}}
    xml = params_to_xml(macros).decode("utf-16")
    data = [
        {
            "id": 1,
            "name": "CX",
            "total_pins": 2,
            "pins": ["1", "2"],
            "subcomponents": [
                {
                    "id": 1,
                    "id_function": 16,
                    "function_name": "RELAIS",
                    "pins": {"A": "1", "B": "2", "S": xml},
                }
            ],
        }
    ]
    path = tmp_path / "buffer.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_buffer(path)
    macros_loaded = xml_to_params(loaded[0]["subcomponents"][0]["pins"]["S"])
    assert macros_loaded["RELAIS"]["PowerCoil"] == "0"
    macros_loaded["RELAIS"]["PowerCoil"] = "1"
    loaded[0]["subcomponents"][0]["pins"]["S"] = params_to_xml(macros_loaded).decode(
        "utf-16"
    )
    save_buffer(path, loaded)

    again = load_buffer(path)
    macros_again = xml_to_params(again[0]["subcomponents"][0]["pins"]["S"])
    assert macros_again["RELAIS"]["PowerCoil"] == "1"
