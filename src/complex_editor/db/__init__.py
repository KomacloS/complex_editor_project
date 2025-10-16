"""Database access helpers for Complex-Editor."""

from .access_driver import (
    connect,
    fetch_comp_desc_rows,
    fetch_macro_pairs,
    make_backup,
    table_exists,
)
from .schema_introspect import discover_macro_map
from .pn_exporter import export_pn_to_mdb, ExportOptions, ExportReport, ExportCanceled, SubsetExportError

__all__ = [
    "connect",
    "fetch_comp_desc_rows",
    "fetch_macro_pairs",
    "make_backup",
    "table_exists",
    "discover_macro_map",
    "export_pn_to_mdb",
    "ExportOptions",
    "ExportReport",
    "ExportCanceled",
    "SubsetExportError",
]

