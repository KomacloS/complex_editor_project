from __future__ import annotations

from typing import Dict
from pathlib import Path

from ..domain import MacroDef, MacroParam

from .access_driver import fetch_macro_pairs


CANDIDATE_MACRO_COLS = ["MacroName", "FunctionName", "Macro", "Function"]


PARAM_COLS = ["ParamName", "ParamType", "DefValue", "MinValue", "MaxValue"]


def _fetch_param_rows(cursor, table: str):
    cols = ", ".join(["IDFunction"] + PARAM_COLS)
    query = f"SELECT {cols} FROM [{table}]"
    return cursor.execute(query).fetchall()


def discover_macro_map(cursor) -> Dict[int, MacroDef]:
    """Discover mapping from IDFunction to :class:`MacroDef`."""
    # If there’s no DB connection, just load the YAML fallback immediately.
    if cursor is None:
        import yaml, importlib.resources

        pkg_files = importlib.resources.files("complex_editor.resources")
        yaml_path = pkg_files.joinpath("macro_fallback.yaml")
        if not yaml_path.is_file():
            alt = Path.cwd() / "macro_fallback.yaml"
            if alt.is_file():
                yaml_path = alt

        data = yaml_path.read_text()
        raw = yaml.safe_load(data).get("macros", [])
        macro_map: Dict[int, MacroDef] = {}
        for entry in raw:
            params = [
                MacroParam(
                    name=p.get("name"),
                    type=p.get("type"),
                    default=p.get("default"),
                    min=p.get("min"),
                    max=p.get("max"),
                )
                for p in entry.get("params", [])
            ]
            macro_map[entry["id_function"]] = MacroDef(
                id_function=entry["id_function"],
                name=entry["name"],
                params=params,
            )
        return macro_map

    macro_map: Dict[int, MacroDef] = {}
    tables = {}
    for t in cursor.tables(tableType="TABLE"):
        table = t.table_name
        columns = [c.column_name for c in cursor.columns(table=table)]
        tables[table] = columns

    macro_tables = [
        (table, next((c for c in CANDIDATE_MACRO_COLS if c in cols), None))
        for table, cols in tables.items()
        if "IDFunction" in cols
        and any(c in cols for c in CANDIDATE_MACRO_COLS)
    ]

    param_tables = [
        table
        for table, cols in tables.items()
        if "IDFunction" in cols and all(p in cols for p in PARAM_COLS)
    ]

    for table, macro_col in macro_tables:
        if not macro_col:
            continue
        for id_function, name in fetch_macro_pairs(cursor, table, macro_col):
            if id_function is None or name is None:
                continue
            id_func = int(id_function)
            if id_func not in macro_map:
                macro_map[id_func] = MacroDef(id_func, str(name), [])

    for table in param_tables:
        for row in _fetch_param_rows(cursor, table):
            id_func = int(getattr(row, "IDFunction", row[0]))
            if id_func not in macro_map:
                continue
            param = MacroParam(
                name=str(getattr(row, "ParamName", row[1])) if getattr(row, "ParamName", row[1]) is not None else None,
                type=str(getattr(row, "ParamType", row[2])) if getattr(row, "ParamType", row[2]) is not None else None,
                default=(
                    str(getattr(row, "DefValue", row[3])) if getattr(row, "DefValue", row[3]) is not None else None
                ),
                min=(
                    str(getattr(row, "MinValue", row[4])) if getattr(row, "MinValue", row[4]) is not None else None
                ),
                max=(
                    str(getattr(row, "MaxValue", row[5])) if getattr(row, "MaxValue", row[5]) is not None else None
                ),
            )
            macro_map[id_func].params.append(param)

    if not macro_map:
        import importlib.resources
        import yaml
        res_files = importlib.resources.files("complex_editor.resources")
        yaml_path = res_files.joinpath("macro_fallback.yaml")
        if not yaml_path.is_file():
            alt = Path.cwd() / "macro_fallback.yaml"
            if alt.is_file():
                yaml_path = alt
        data = yaml_path.read_text()
        for entry in yaml.safe_load(data)["macros"]:
            params = [
                MacroParam(
                    name=p.get("name"),
                    type=p.get("type"),
                    default=p.get("default"),
                    min=p.get("min"),
                    max=p.get("max"),
                )
                for p in entry.get("params", [])
            ]
            macro_map[entry["id_function"]] = MacroDef(
                id_function=entry["id_function"],
                name=entry["name"],
                params=params,
            )
    return macro_map
