from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pyodbc


def dump_table_schema(conn: pyodbc.Connection, table: str) -> Dict[str, Dict[str, Any]]:
    cur = conn.cursor()
    out: Dict[str, Dict[str, Any]] = {}
    for r in cur.columns(table=table):
        name = str(getattr(r, "column_name", getattr(r, "COLUMN_NAME", "")) or "").strip()
        if not name:
            continue
        data_type = getattr(r, "data_type", getattr(r, "DATA_TYPE", None))
        type_name = getattr(r, "type_name", getattr(r, "TYPE_NAME", ""))
        column_size = getattr(r, "column_size", getattr(r, "COLUMN_SIZE", None))
        decimal_digits = getattr(r, "decimal_digits", getattr(r, "DECIMAL_DIGITS", None))
        nullable_val = getattr(r, "nullable", getattr(r, "NULLABLE", None))
        try:
            is_nullable = bool(int(nullable_val)) if nullable_val is not None else True
        except Exception:
            is_nullable = True
        out[name] = {
            "data_type": data_type,
            "type_name": type_name,
            "column_size": int(column_size) if column_size not in (None, "") else None,
            "decimal_digits": int(decimal_digits) if decimal_digits not in (None, "") else None,
            "nullable": is_nullable,
        }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Dump MDB table schema as JSON using pyodbc")
    p.add_argument("--mdb", required=True, help="Path to .mdb/.accdb file")
    p.add_argument("--table", default="detCompDesc", help="Table name to inspect")
    args = p.parse_args()

    mdb_path = Path(args.mdb).expanduser().resolve()
    if not mdb_path.exists():
        raise SystemExit(f"MDB file not found: {mdb_path}")

    conn = pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={mdb_path}")
    try:
        schema = dump_table_schema(conn, args.table)
    finally:
        conn.close()
    print(json.dumps(schema, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

