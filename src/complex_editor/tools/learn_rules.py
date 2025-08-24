from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Iterable, Tuple

from ..db.mdb_api import MDB
from ..db import schema_introspect
from ..io.buffer_loader import load_complex_from_buffer_json
from ..learn.learner import learn_from_rows


def rows_from_mdb(db: MDB):
    cur = db._conn.cursor()
    macros = schema_introspect.discover_macro_map(cur) or {}
    rows = []
    for cx in db.list_complexes():
        full = db.get_complex(cx.id_comp_desc)
        for sc in getattr(full, "subcomponents", []) or []:
            rows.append(("", sc.pins.get("S", "")))
    return rows, macros


def rows_from_buffer(path: Path):
    data = load_complex_from_buffer_json(path)
    rows = []
    # ``load_complex_from_buffer_json`` may return either a list of complexes
    # or a single :class:`BufferComplex`.  Support both shapes.
    if isinstance(data, list):
        for cx in data:
            for sc in cx.get("subcomponents", []):
                rows.append(
                    (
                        sc.get("function_name") or "",
                        (sc.get("pins") or {}).get("S", ""),
                    )
                )
    else:
        for sc in getattr(data, "sub_components", []):
            pin_s = getattr(sc, "pin_s", None)
            if pin_s is None and getattr(sc, "pin_map", None):
                pin_s = sc.pin_map.get("S", "")
            rows.append((sc.macro_name or "", pin_s or ""))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mdb", type=Path)
    ap.add_argument("--buffer", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows: list[Tuple[str, str]] = []
    macros = {}
    if args.mdb:
        db = MDB(args.mdb)
        r, macros = rows_from_mdb(db)
        rows.extend(r)
    if args.buffer:
        rows.extend(rows_from_buffer(args.buffer))
        if not macros:
            macros = schema_introspect.discover_macro_map(None) or {}

    rules = learn_from_rows(rows, macros)
    args.out.write_text(rules.to_json(), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()

