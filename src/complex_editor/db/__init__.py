"""Database access helpers for Complex-Editor."""

from .access_driver import connect, fetch_comp_desc_rows, fetch_macro_pairs, table_exists

__all__ = ["connect", "fetch_comp_desc_rows", "fetch_macro_pairs", "table_exists"]
