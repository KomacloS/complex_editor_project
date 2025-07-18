"""
mdb_api.py  –  thin, typed wrapper around AWG_COMPLEX.mdb

Features
────────
• Connect / close (context-manager friendly)
• CRUD for complexes and sub-components
• Duplicate complex (deep copy, no PK collisions)
• Simple searches (by name or LIKE pattern)
• Auto-validation helpers (pin names, function IDs)

Only dependency:  pyodbc
───────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple, Union

import pyodbc

# ─── schema constants ────────────────────────────────────────────────
DRIVER    = r"{Microsoft Access Driver (*.mdb, *.accdb)}"
MASTER_T  = "tabCompDesc"
DETAIL_T  = "detCompDesc"
FUNC_T    = "tabFunction"

PK_MASTER = "IDCompDesc"
PK_DETAIL = "IDSubComponent"

NAME_COL  = "Name"

# pinnable columns order preference
PIN_COLUMNS = [f"Pin{c}" for c in "ABCDEFGH"] + ["PinS"]


# ─── simple domain objects ───────────────────────────────────────────
@dataclass
class SubComponent:
    id_sub_component: Optional[int]
    id_function: int
    value: str = ""
    id_unit: int | None = None
    tol_p: float | None = None
    tol_n: float | None = None
    force_bits: int | None = None
    pins: Dict[str, int] | None = None       # {"A":4,"B":5,…}

    # internal – flatten to SQL row (without PK)
    def _flatten(self, fk_master: int) -> Tuple[List[str], List[Any]]:
        cols   = [PK_MASTER, "IDFunction", "Value",
                  "IDUnit", "TolP", "TolN", "ForceBits"]
        vals   = [fk_master, self.id_function, self.value,
                  self.id_unit, self.tol_p, self.tol_n, self.force_bits]

        for name, num in (self.pins or {}).items():
            if name.upper() not in "ABCDEFGH S":
                raise ValueError(f"Illegal pin '{name}'")
            cols.append(f"Pin{name.upper()}")
            vals.append(num)
        return cols, vals


@dataclass
class ComplexDevice:
    id_comp_desc: Optional[int]
    name: str
    total_pins: int
    subcomponents: List[SubComponent]


# ─── main API class ──────────────────────────────────────────────────
class MDB:
    """
    Friendly wrapper around the Access database.  Use as

        with MDB("AWG_COMPLEX.mdb") as db:
            for cx in db.list_complexes():
                print(cx)
    """

    # ── init / context mgr ─────────────────────────────────────────
    def __init__(self, file: Union[str, Path]):
        self.path = Path(file).resolve()
        self._conn = pyodbc.connect(
            rf"DRIVER={DRIVER};DBQ={self.path}", autocommit=False
        )

    def __enter__(self):  # context-manager support
        return self

    def __exit__(self, exc_type, *_):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()

    # ── utility ----------------------------------------------------
    def _cur(self):
        return self._conn.cursor()

    # ── lookup helpers --------------------------------------------
    def list_complexes(self) -> List[Tuple[int, str, str, int]]:
        """Return [(id,name,function_name,#subs), ...]."""
        cur = self._cur()
        cur.execute(
            f"""
            SELECT m.{PK_MASTER}, m.{NAME_COL}, f.Name,
                   COUNT(d.{PK_DETAIL})
            FROM {MASTER_T} AS m
            LEFT JOIN {DETAIL_T} AS d ON m.{PK_MASTER}=d.{PK_MASTER}
            LEFT JOIN {FUNC_T} AS f ON m.IDFunction=f.IDFunction
            GROUP BY m.{PK_MASTER}, m.{NAME_COL}, f.Name
            ORDER BY m.{PK_MASTER}
            """
        )
        return cur.fetchall()

    def search_complexes(self, pattern: str) -> List[Tuple[int, str]]:
        cur = self._cur()
        like = pattern.replace("*", "%")
        cur.execute(
            f"SELECT {PK_MASTER},{NAME_COL} FROM {MASTER_T} WHERE {NAME_COL} LIKE ?",
            like,
        )
        return cur.fetchall()

    def list_functions(self) -> List[Tuple[int, str]]:
        """Return (IDFunction, Name) pairs."""
        cur = self._cur()
        cur.execute("SELECT IDFunction, Name FROM tabFunction ORDER BY Name")
        return cur.fetchall()

    # ── getters ----------------------------------------------------
    def get_complex(self, comp_id: int) -> ComplexDevice:
        cur = self._cur()
        cur.execute(
            f"SELECT * FROM {MASTER_T} WHERE {PK_MASTER}=?", comp_id
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Complex ID {comp_id} not found")
        master_cols = [d[0] for d in cur.description]
        m = dict(zip(master_cols, row))

        cur.execute(
            f"SELECT * FROM {DETAIL_T} WHERE {PK_MASTER}=? ORDER BY {PK_DETAIL}",
            comp_id,
        )
        det_cols = [d[0] for d in cur.description]
        subs = []
        for r in cur.fetchall():
            d = dict(zip(det_cols, r))
            pins = {
                c[3:]: d[c]
                for c in PIN_COLUMNS
                if c in d and d[c] not in (None, 0, "")
            }
            subs.append(
                SubComponent(
                    d[PK_DETAIL],
                    d["IDFunction"],
                    d.get("Value") or "",
                    d.get("IDUnit"),
                    d.get("TolP"),
                    d.get("TolN"),
                    d.get("ForceBits"),
                    pins or None,
                )
            )
        return ComplexDevice(m[PK_MASTER], m[NAME_COL], m.get("TotalPinNumber", 0), subs)

    # ── creators ---------------------------------------------------
    def create_complex(self, cx: ComplexDevice) -> int:
        cur = self._cur()
        cur.execute(
            f"INSERT INTO {MASTER_T} (Name, TotalPinNumber) VALUES (?,?)",
            cx.name,
            cx.total_pins,
        )
        cur.execute("SELECT @@IDENTITY")
        new_id = int(cur.fetchone()[0])

        for sub in cx.subcomponents:
            self._insert_sub(cur, new_id, sub)
        return new_id

    def duplicate_complex(self, src_id: int, new_name: str) -> int:
        """Deep-copy master + sub rows.  Returns new master ID."""
        cx = self.get_complex(src_id)
        cx.id_comp_desc = None
        cx.name = new_name
        return self.create_complex(cx)

    def add_complex(self, complex_dev: ComplexDevice) -> int:
        """Public helper using the legacy service to insert a complex."""
        from ..services.export_service import insert_complex

        return insert_complex(self._conn, complex_dev)

    # ── modifiers --------------------------------------------------
    def update_complex(self, comp_id: int, **fields):
        if not fields:
            return
        sql = ", ".join(f"[{k}]=?" for k in fields)
        vals = list(fields.values()) + [comp_id]
        self._cur().execute(f"UPDATE {MASTER_T} SET {sql} WHERE {PK_MASTER}=?", *vals)

    def delete_complex(self, comp_id: int, cascade: bool = True):
        cur = self._cur()
        if cascade:
            cur.execute(f"DELETE FROM {DETAIL_T} WHERE {PK_MASTER}=?", comp_id)
        cur.execute(f"DELETE FROM {MASTER_T} WHERE {PK_MASTER}=?", comp_id)

    # sub-components
    def add_sub(self, comp_id: int, sub: SubComponent) -> int:
        cur = self._cur()
        return self._insert_sub(cur, comp_id, sub)

    def update_sub(self, sub_id: int, **fields):
        if not fields:
            return
        sql = ", ".join(f"[{k}]=?" for k in fields)
        vals = list(fields.values()) + [sub_id]
        self._cur().execute(f"UPDATE {DETAIL_T} SET {sql} WHERE {PK_DETAIL}=?", *vals)

    def delete_sub(self, sub_id: int):
        self._cur().execute(f"DELETE FROM {DETAIL_T} WHERE {PK_DETAIL}=?", sub_id)

    # ── internals --------------------------------------------------
    @staticmethod
    def _insert_sub(cur, fk_master: int, sub: SubComponent) -> int:
        cols, vals = sub._flatten(fk_master)
        sql_cols  = ", ".join(f"[{c}]" for c in cols)
        sql_qm    = ", ".join("?" for _ in vals)
        cur.execute(
            f"INSERT INTO {DETAIL_T} ({sql_cols}) VALUES ({sql_qm})",
            *vals,
        )
        cur.execute("SELECT @@IDENTITY")
        new_id = int(cur.fetchone()[0])
        sub.id_sub_component = new_id
        return new_id


# ─── quick CLI demo (run `python mdb_api.py your.mdb`) ───────────────
if __name__ == "__main__":  # pragma: no cover
    import argparse
    import textwrap
    import json

    p = argparse.ArgumentParser(
        description="Tiny interactive test-shell for mdb_api",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples
            --------
              # list complexes
              python mdb_api.py db.mdb list

              # duplicate ID 12 as 'MY_COPY'
              python mdb_api.py db.mdb dup 12 MY_COPY

              # dump complex 12 as JSON
              python mdb_api.py db.mdb show 12
            """
        ),
    )
    p.add_argument("file")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")
    sh = sub.add_parser("show")
    sh.add_argument("id", type=int)

    dp = sub.add_parser("dup")
    dp.add_argument("src_id", type=int)
    dp.add_argument("new_name")

    args = p.parse_args()

    with MDB(args.file) as db:
        if args.cmd == "list":
            for cid, name in db.list_complexes():
                print(f"{cid:4}  {name}")
        elif args.cmd == "show":
            cx = db.get_complex(args.id)
            print(json.dumps(cx, default=lambda o: o.__dict__, indent=2))
        elif args.cmd == "dup":
            nid = db.duplicate_complex(args.src_id, args.new_name)
            print(f"Duplicated → ID {nid}")
