from __future__ import annotations

import pyodbc


def connect(mdb_path: str) -> pyodbc.Connection:
    """Return pyodbc connection to the given MDB path."""
    conn_str = (
        "Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={mdb_path};"
    )
    return pyodbc.connect(conn_str, autocommit=True)


def table_exists(cursor: pyodbc.Cursor, table: str) -> bool:
    """Return True if the table exists in the MDB."""
    for row in cursor.tables(table=table, tableType="TABLE"):
        if row.table_name.lower() == table.lower():
            return True
    return False


def fetch_comp_desc_rows(cursor: pyodbc.Cursor, limit: int):
    """Fetch rows from tabCompDesc limited by ``limit``."""
    query = (
        f"SELECT TOP {limit} "
        "IDCompDesc, IDFunction, PinA, PinB, PinC, PinD, PinS "
        "FROM tabCompDesc"
    )
    return cursor.execute(query).fetchall()


def fetch_macro_pairs(cursor: pyodbc.Cursor, table: str, macro_col: str):
    """Return (IDFunction, macro_name) pairs from the given table."""
    query = f"SELECT IDFunction, [{macro_col}] FROM [{table}]"
    return cursor.execute(query).fetchall()
