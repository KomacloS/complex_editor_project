from __future__ import annotations

from typing import Dict

from .access_driver import fetch_macro_pairs


CANDIDATE_MACRO_COLS = ["MacroName", "FunctionName", "Macro", "Function"]


def discover_macro_map(cursor) -> Dict[int, str]:
    """Discover mapping from IDFunction to macro name using MDB schema."""
    macro_map: Dict[int, str] = {}
    for t in cursor.tables(tableType="TABLE"):
        table = t.table_name
        columns = [c.column_name for c in cursor.columns(table=table)]
        if "IDFunction" not in columns:
            continue
        macro_col = next((c for c in CANDIDATE_MACRO_COLS if c in columns), None)
        if not macro_col:
            continue
        for id_function, name in fetch_macro_pairs(cursor, table, macro_col):
            if id_function is None or name is None:
                continue
            macro_map[int(id_function)] = str(name)
    return macro_map
