"""CLI entry points for Complex-Editor."""

from __future__ import annotations

import argparse
import sys

from .db import (
    connect,
    discover_macro_map,
    fetch_comp_desc_rows,
    make_backup,
    table_exists,
)
from .domain import ComplexDevice, MacroInstance, macro_to_xml
from .services import insert_complex


def list_complexes_cmd(args: argparse.Namespace) -> int:
    conn = connect(args.mdb_path)
    cursor = conn.cursor()
    if not table_exists(cursor, "tabCompDesc"):
        print("Error: table tabCompDesc not found in MDB.")
        return 1
    macro_map = discover_macro_map(cursor)
    rows = fetch_comp_desc_rows(cursor, args.limit)
    for row in rows:
        id_comp = getattr(row, "IDCompDesc", row[0])
        id_func = getattr(row, "IDFunction", row[1])
        macro_def = macro_map.get(int(id_func))
        macro = macro_def.name if macro_def else f"ID {id_func}"
        pin_a = getattr(row, "PinA", row[2])
        pin_b = getattr(row, "PinB", row[3])
        pin_c = getattr(row, "PinC", row[4])
        pin_d = getattr(row, "PinD", row[5])
        pin_s = getattr(row, "PinS", row[6])
        print(
            f"{id_comp}\t{macro}\t{pin_a}\t{pin_b}\t{pin_c}\t{pin_d}\t"
            f"{'yes' if pin_s else 'no'}"
        )
    return 0


def dump_macros_cmd(args: argparse.Namespace) -> int:
    conn = connect(args.mdb_path)
    cursor = conn.cursor()
    macro_map = discover_macro_map(cursor)
    if args.id is not None:
        macro = macro_map.get(int(args.id))
        if not macro:
            print(f"Macro ID {args.id} not found")
            return 1
        print(f"{macro.id_function}\t{macro.name}")
        for p in macro.params:
            print(f"  {p.name}\t{p.type}\t{p.default}\t{p.min}\t{p.max}")
        return 0
    for macro in macro_map.values():
        print(f"{macro.id_function}\t{macro.name}\t{len(macro.params)}")
    return 0


def make_pinxml_cmd(args: argparse.Namespace) -> int:
    params_pairs = []
    for item in args.param:
        if "=" not in item:
            print(f"Invalid --param: {item}")
            return 1
        name, value = item.split("=", 1)
        params_pairs.append((name, value))
    macro = MacroInstance(args.macro, dict(params_pairs))
    xml_str = macro_to_xml(macro)
    hex_dump = " ".join(f"{b:02x}" for b in xml_str.encode("utf-16le"))
    print(hex_dump)
    return 0


def add_complex_cmd(args: argparse.Namespace) -> int:
    params_pairs = []
    for item in args.param:
        if "=" not in item:
            print(f"Invalid --param: {item}")
            return 1
        name, value = item.split("=", 1)
        params_pairs.append((name, value))

    if len(args.pins) < 2 or len(args.pins) > 4:
        print("Error: --pins expects between 2 and 4 values")
        return 1

    conn = connect(args.mdb_path)
    conn.autocommit = False
    try:
        make_backup(args.mdb_path)
        device = ComplexDevice(
            id_function=args.idfunc,
            pins=args.pins,
            macro=MacroInstance(args.macro, dict(params_pairs)),
        )
        try:
            new_id = insert_complex(conn, device)
        except Exception as e:
            conn.rollback()
            print(str(e))
            return 1
        conn.commit()
        print(f"Inserted complex {new_id} (macro {device.macro.name})")
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complex-Editor CLI")
    parser.add_argument("--version", action="version", version="0.0.1")
    sub = parser.add_subparsers(dest="command", required=True)
    list_p = sub.add_parser("list-complexes", help="List complexes from MDB")
    list_p.add_argument("mdb_path")
    list_p.add_argument("--limit", type=int, default=10)
    list_p.set_defaults(func=list_complexes_cmd)

    dump_p = sub.add_parser("dump-macros", help="Dump macro definitions")
    dump_p.add_argument("mdb_path")
    dump_p.add_argument("--id", type=int)
    dump_p.set_defaults(func=dump_macros_cmd)

    xml_p = sub.add_parser("make-pinxml", help="Build PinS XML for a macro")
    xml_p.add_argument("--macro", required=True)
    xml_p.add_argument("--param", action="append", default=[])
    xml_p.set_defaults(func=make_pinxml_cmd)

    add_p = sub.add_parser("add-complex", help="Insert a complex into an MDB")
    add_p.add_argument("mdb_path")
    add_p.add_argument("--idfunc", type=int, required=True)
    add_p.add_argument("--pins", nargs="+", type=str, required=True)
    add_p.add_argument("--macro", required=True)
    add_p.add_argument("--param", action="append", default=[])
    add_p.set_defaults(func=add_complex_cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

