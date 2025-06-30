"""CLI entry points for Complex-Editor."""

from __future__ import annotations

import argparse
import sys

from .db import connect, discover_macro_map, fetch_comp_desc_rows, table_exists


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

