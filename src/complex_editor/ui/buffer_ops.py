from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from ..db.mdb_api import SubComponent
from ..tools.make_gui_buffer import _serialize_sub, BufSubComponent


def load_buffer(path: Path) -> dict:
    """Load buffer JSON from *path* and return the parsed dict."""
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_buffer(path: Path, data: dict) -> None:
    """Write *data* back to *path* as pretty JSON."""
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def get_all_macro_choices(data: dict) -> list[str]:
    """Return a sorted list of all macro names known in *data*."""
    names = set((data.get("function_map") or {}).values())
    for cx in data.get("complexes", []):
        for sc in cx.get("subcomponents", []) or []:
            fname = sc.get("function_name")
            if fname:
                names.add(str(fname))
    return sorted(names)


def generate_new_sub_id(data: dict) -> int:
    """Return an unused subcomponent ID for *data*."""
    max_id = 0
    for cx in data.get("complexes", []):
        for sc in cx.get("subcomponents", []) or []:
            sid = sc.get("id")
            if isinstance(sid, int) and sid > max_id:
                max_id = sid
    return max_id + 1


def _macro_name_to_id(data: dict, macro: str) -> int:
    fmap = data.get("function_map", {})
    for k, v in fmap.items():
        if v == macro:
            try:
                return int(k)
            except ValueError:
                continue
    # Unknown macro; using 0 per instructions
    return 0


def format_pins_for_table(pins: Dict[str, str]) -> str:
    ordered_keys = [k for k in sorted(pins.keys()) if k.isalpha()]
    return ",".join(f"{k}={pins[k]}" for k in ordered_keys)


def _find_complex(data: dict, complex_id: int) -> Dict[str, Any]:
    for cx in data.get("complexes", []):
        if int(cx.get("id", 0)) == int(complex_id):
            return cx
    raise KeyError(f"Complex {complex_id} not found")


def apply_add_sub(data: dict, complex_id: int, macro: str, pins: Dict[str, str]) -> dict:
    """Add a subcomponent and return mutated *data*."""
    cx = _find_complex(data, complex_id)
    new_id = generate_new_sub_id(data)
    id_func = _macro_name_to_id(data, macro)
    sc = SubComponent(
        id_sub_component=new_id,
        id_function=id_func,
        pins={k.upper(): int(v) for k, v in pins.items()},
    )
    buf_sc: BufSubComponent = _serialize_sub(sc, {id_func: macro})
    cx.setdefault("subcomponents", []).append(asdict(buf_sc))
    return data


def apply_edit_sub(
    data: dict, complex_id: int, sub_id: int, macro: str, pins: Dict[str, str]
) -> dict:
    """Edit subcomponent *sub_id* in *complex_id* and return mutated *data*."""
    cx = _find_complex(data, complex_id)
    subs = cx.get("subcomponents", [])
    for i, sc in enumerate(subs):
        if int(sc.get("id", 0)) == int(sub_id):
            id_func = _macro_name_to_id(data, macro)
            new_sc = SubComponent(
                id_sub_component=sub_id,
                id_function=id_func,
                pins={k.upper(): int(v) for k, v in pins.items()},
            )
            buf_sc: BufSubComponent = _serialize_sub(new_sc, {id_func: macro})
            subs[i] = asdict(buf_sc)
            return data
    raise KeyError(f"Subcomponent {sub_id} not found")


def apply_delete_sub(data: dict, complex_id: int, sub_id: int) -> dict:
    """Delete subcomponent *sub_id* from *complex_id* and return mutated *data*."""
    cx = _find_complex(data, complex_id)
    subs = cx.get("subcomponents", [])
    cx["subcomponents"] = [sc for sc in subs if int(sc.get("id", 0)) != int(sub_id)]
    return data
