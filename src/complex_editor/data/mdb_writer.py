from __future__ import annotations

from typing import List

import pyodbc

from complex_editor.util.macro_xml_translator import params_to_xml
from complex_editor.param_spec import ALLOWED_PARAMS


class MdbWriter:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: pyodbc.Connection | None = None

    def __enter__(self) -> "MdbWriter":
        self.conn = pyodbc.connect(
            rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.path}"
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.conn:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
            self.conn.close()
            self.conn = None

    # ------------------------------------------------------------------
    def save_sub_component(
        self,
        conn: pyodbc.Connection,
        sub_id: int,
        macros: List[dict],  # [{'name': …, 'params': {...}}, …]
    ) -> None:
        macro_map = {m["name"]: m.get("params", {}) for m in macros}
        xml_blob = params_to_xml(macro_map, encoding="utf-16", schema=ALLOWED_PARAMS)

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE detCompDesc
               SET PinS = ?
             WHERE IDSubComponent = ?
            """,
            xml_blob,
            sub_id,
        )
        cursor.commit()
