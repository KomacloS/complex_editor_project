from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Sequence

import pyodbc


def do_insert(conn: pyodbc.Connection, table: str, cols: Sequence[str], vals: Sequence[Any]) -> None:
    cur = conn.cursor()
    cols_sql = ", ".join(f"[{c}]" for c in cols)
    params = ", ".join("?" for _ in vals)
    print(f"SQL: INSERT INTO {table} ({cols_sql}) VALUES ({params})")
    for i, (c, v) in enumerate(zip(cols, vals), start=1):
        vp = repr(v)
        if len(vp) > 300:
            vp = vp[:300] + "..."
        print(f"  {i:02d}. {c:<16} {type(v).__name__:<12} {vp}")
    cur.execute(f"INSERT INTO {table} ({cols_sql}) VALUES ({params})", *vals)
    cur.execute("SELECT @@IDENTITY")
    new_id = int(cur.fetchone()[0])
    print(f"@@IDENTITY = {new_id}")


def main() -> None:
    p = argparse.ArgumentParser(description="Reproduce insert into detCompDesc with provided cols/vals JSON")
    p.add_argument("--template", required=True, help="Path to template MDB to copy")
    p.add_argument("--target", required=True, help="Path to target MDB (will overwrite)")
    p.add_argument("--json", dest="json_path", required=True, help='Path to JSON file with {"cols":[],"vals":[]}')
    p.add_argument("--table", default="detCompDesc", help="Table name (default detCompDesc)")
    args = p.parse_args()

    src = Path(args.template).expanduser().resolve()
    dst = Path(args.target).expanduser().resolve()
    data_path = Path(args.json_path).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"Template not found: {src}")
    if not data_path.exists():
        raise SystemExit(f"JSON payload not found: {data_path}")

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    cols = payload.get("cols") or []
    vals = payload.get("vals") or []
    if not isinstance(cols, list) or not isinstance(vals, list):
        raise SystemExit("Payload must contain lists 'cols' and 'vals'")
    if len(cols) != len(vals):
        raise SystemExit("cols and vals must be same length")

    if dst.exists():
        dst.unlink()
    shutil.copyfile(src, dst)

    conn = pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={dst}")
    try:
        try:
            do_insert(conn, args.table, cols, vals)
        except pyodbc.DataError as exc:
            print("pyodbc.DataError:")
            print("  class:", exc.__class__.__name__)
            print("  args:", getattr(exc, "args", ()))
            raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

