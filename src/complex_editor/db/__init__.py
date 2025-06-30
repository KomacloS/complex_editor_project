"""Database access helpers for Complex-Editor."""

from .access_driver import connect, fetch_comp_desc_rows, fetch_macro_pairs, table_exists
from .schema_introspect import discover_macro_map

__all__ = [
    "connect",
    "fetch_comp_desc_rows",
    "fetch_macro_pairs",
    "table_exists",
    "discover_macro_map",
]

