from __future__ import annotations

import json
from pathlib import Path

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.buffer_ops import (
    load_buffer,
    save_buffer,
    get_all_macro_choices,
    generate_new_sub_id,
    format_pins_for_table,
    apply_add_sub,
    apply_edit_sub,
    apply_delete_sub,
)


def test_buffer_ops_crud(tmp_path: Path) -> None:
    buf_path = Path(__file__).parent / "fixtures" / "buffer_small.json"
    data = load_buffer(buf_path)

    assert set(get_all_macro_choices(data)) == {"MACRO1", "MACRO2"}
    assert format_pins_for_table({"B": "2", "A": "1"}) == "A=1,B=2"

    new_id = generate_new_sub_id(data)
    assert new_id == 11
    apply_add_sub(data, 1, "MACRO2", {"a": "2", "b": "1"})
    subs = data["complexes"][0]["subcomponents"]
    added = [s for s in subs if s["id"] == 11][0]
    assert added["function_name"] == "MACRO2" and added["id_function"] == 2
    assert added["pins"] == {"A": "2", "B": "1"}

    apply_edit_sub(data, 1, 11, "MACRO1", {"A": "2", "B": "2"})
    edited = [s for s in subs if s["id"] == 11][0]
    assert edited["function_name"] == "MACRO1" and edited["id_function"] == 1
    assert edited["pins"] == {"A": "2", "B": "2"}

    apply_delete_sub(data, 1, 11)
    subs = data["complexes"][0]["subcomponents"]
    assert all(s["id"] != 11 for s in subs)

    out = tmp_path / "out.json"
    save_buffer(out, data)
    loaded = json.loads(out.read_text())
    assert loaded["complexes"][0]["id"] == 1
