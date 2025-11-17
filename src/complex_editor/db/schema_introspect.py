from __future__ import annotations

from typing import Dict
import logging

from complex_editor.param_spec import ALLOWED_PARAMS, resolve_macro_name
from complex_editor.db_overlay.runtime import get_runtime

from ..domain import MacroDef, MacroParam
from .access_driver import fetch_macro_pairs

CANDIDATE_MACRO_COLS = ["MacroName", "FunctionName", "Macro", "Function"]

# Only the first three columns are mandatory. Min/Max are nice-to-have.
CORE_PARAM_COLS = {"ParamName", "ParamType", "DefValue"}
# Helper list used for SELECT queries
PARAM_COLS = ["ParamName", "ParamType", "DefValue", "MinValue", "MaxValue"]


def _fill_from_yaml_specs(macro_map: Dict[int, MacroDef]) -> Dict[int, MacroDef]:
    log = logging.getLogger(__name__)
    for m in macro_map.values():
        if m.params:
            continue
        spec = ALLOWED_PARAMS.get(resolve_macro_name(m.name.strip()), {})
        if not spec:
            log.warning("Macro %s has no parameter definition in DB or YAML", m.name)
            continue
        m.params = [
            MacroParam(
                name=pname,
                type=spec[pname].get("type", "STR"),
                default=spec[pname].get("default"),
                min=spec[pname].get("min"),
                max=spec[pname].get("max"),
            )
            for pname in spec
        ]

    existing = {m.name.strip() for m in macro_map.values()}
    next_id = max(macro_map.keys(), default=0) + 1
    for name, spec in ALLOWED_PARAMS.items():
        if name in existing:
            continue
        macro_map[next_id] = MacroDef(
            id_function=next_id,
            name=name,
            params=[
                MacroParam(
                    name=pname,
                    type=spec[pname].get("type", "STR"),
                    default=spec[pname].get("default"),
                    min=spec[pname].get("min"),
                    max=spec[pname].get("max"),
                )
                for pname in spec
            ],
        )
        next_id += 1
    return macro_map


def _fetch_param_rows(cursor, table: str) -> list[tuple]:
    cols = ", ".join(["IDFunction"] + PARAM_COLS)
    query = f"SELECT {cols} FROM [{table}]"
    return cursor.execute(query).fetchall()


def discover_macro_map(cursor_or_conn) -> Dict[int, MacroDef]:
    """Discover mapping from IDFunction to :class:`MacroDef`.

    Parameters
    ----------
    cursor_or_conn:
        Either a ``pyodbc`` cursor or connection.  If a connection is
        provided a cursor is requested from it.  ``None`` is accepted and
        results in a macro map built solely from the local YAML specs.
    """

    log = logging.getLogger(__name__)
    runtime = get_runtime()
    if runtime:
        state = runtime.state()
        if state.ready:
            macro_map = runtime.macro_map()
            return _fill_from_yaml_specs(macro_map)
        if state.fingerprint_pending:
            log.warning("DB overlay pending fingerprint confirmation; suppressing DB macros")
            return _fill_from_yaml_specs({})

    macro_map: Dict[int, MacroDef] = {}

    cursor = None
    if cursor_or_conn is not None:
        if hasattr(cursor_or_conn, "cursor"):
            cursor = cursor_or_conn.cursor()
        else:
            conn = getattr(cursor_or_conn, "_conn", None)
            if conn is not None and hasattr(conn, "cursor"):
                cursor = conn.cursor()
            else:
                cursor = cursor_or_conn

    # If there's no DB connection, build the macro map solely from YAML.
    if cursor is None:
        return _fill_from_yaml_specs({})

    tables = {}
    try:
        for t in cursor.tables(tableType="TABLE"):
            table = t.table_name
            columns = [c.column_name for c in cursor.columns(table=table)]
            tables[table] = columns
    except Exception:
        log.exception("Failed to inspect MDB tables")
        return macro_map

    macro_tables = [
        (table, next((c for c in CANDIDATE_MACRO_COLS if c in cols), None))
        for table, cols in tables.items()
        if "IDFunction" in cols and any(c in cols for c in CANDIDATE_MACRO_COLS)
    ]

    param_tables = [
        table
        for table, cols in tables.items()
        if "IDFunction" in cols and CORE_PARAM_COLS.issubset(cols)
    ]

    for table, macro_col in macro_tables:
        if not macro_col:
            continue
        for id_function, name in fetch_macro_pairs(cursor, table, macro_col):
            if id_function is None or name is None:
                continue
            id_func = int(id_function)
            clean_name = str(name).strip()          # ← new
            if id_func not in macro_map:
                macro_map[id_func] = MacroDef(id_func, clean_name, [])

    for table in param_tables:
        for row in _fetch_param_rows(cursor, table):
            id_func = int(getattr(row, "IDFunction", row[0]))
            if id_func not in macro_map:
                continue
            param = MacroParam(
                name=str(getattr(row, "ParamName", row[1]) or ""),
                type=str(getattr(row, "ParamType", row[2]) or ""),
                default=(
                    str(getattr(row, "DefValue", row[3]))
                    if getattr(row, "DefValue", row[3]) is not None
                    else None
                ),
                min=(
                    str(getattr(row, "MinValue", row[4]))
                    if getattr(row, "MinValue", row[4]) is not None
                    else None
                ),
                max=(
                    str(getattr(row, "MaxValue", row[5]))
                    if getattr(row, "MaxValue", row[5]) is not None
                    else None
                ),
            )
            macro_map[id_func].params.append(param)

    for m in macro_map.values():
        if m.params:
            continue
        spec = ALLOWED_PARAMS.get(resolve_macro_name(m.name.strip()), {})
        if not spec:
            log.warning("Macro %s has no parameter definition in DB or YAML", m.name)
            continue
        m.params = [
            MacroParam(
                name=pname,
                type=spec[pname].get("type", "STR"),
                default=spec[pname].get("default"),
                min=spec[pname].get("min"),
                max=spec[pname].get("max"),
            )
            for pname in spec
        ]

    existing = {m.name.strip() for m in macro_map.values()}
    next_id = max(macro_map.keys(), default=0) + 1
    for name, spec in ALLOWED_PARAMS.items():
        if name in existing:
            continue
        macro_map[next_id] = MacroDef(
            id_function=next_id,
            name=name,
            params=[
                MacroParam(
                    name=pname,
                    type=spec[pname].get("type", "STR"),
                    default=spec[pname].get("default"),
                    min=spec[pname].get("min"),
                    max=spec[pname].get("max"),
                )
                for pname in spec
            ],
        )
        next_id += 1

    return _fill_from_yaml_specs(macro_map)
