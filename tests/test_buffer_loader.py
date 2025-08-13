from __future__ import annotations

import json
from pathlib import Path

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.buffer_loader import load_editor_complexes_from_buffer


def test_load_editor_complexes_from_buffer(tmp_path: Path) -> None:
    buf = [
        {
            "id": 123,
            "name": "DEMO",
            "total_pins": 4,
            "pins": ["1", "2", "3", "4"],
            "subcomponents": [
                {
                    "id": 1,
                    "id_function": 6,
                    "function_name": "RESISTOR",
                    "value": None,
                    "force_bits": 0,
                    "pins": {"A": "1", "B": "2"},
                },
                {
                    "id": 2,
                    "id_function": 16,
                    "function_name": "RELAIS",
                    "value": "12.0",
                    "force_bits": 1,
                    "pins": {"A": "3", "B": "4"},
                },
            ],
        }
    ]
    path = tmp_path / "buffer.json"
    path.write_text(json.dumps(buf), encoding="utf-8")

    out = load_editor_complexes_from_buffer(path)
    assert len(out) == 1
    cx = out[0]
    assert cx.id == 123
    assert cx.name == "DEMO"
    assert cx.pins == ["1", "2", "3", "4"]
    assert len(cx.subcomponents) == 2
    assert cx.subcomponents[0].name == "RESISTOR"
    assert cx.subcomponents[0].pins == {"A": "1", "B": "2"}
    assert cx.subcomponents[0].params == {}
