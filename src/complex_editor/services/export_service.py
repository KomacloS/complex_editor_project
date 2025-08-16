from __future__ import annotations

from ..db import table_exists
from ..domain import ComplexDevice
from ..util.macro_xml_translator import params_to_xml
from ..param_spec import ALLOWED_PARAMS


def insert_complex(conn, complex_dev: ComplexDevice) -> int:
    """Insert *complex_dev* into tabCompDesc and return new ID."""
    cursor = conn.cursor()
    if not table_exists(cursor, "tabCompDesc"):
        raise RuntimeError("tabCompDesc table missing")

    cursor.execute("SELECT MAX(IDCompDesc) FROM tabCompDesc")
    row = cursor.fetchone()
    max_id = row[0] if row and row[0] is not None else 0
    next_id = max_id + 1

    pin_s = params_to_xml(
        {complex_dev.macro.name: complex_dev.macro.params},
        encoding="utf-16",
        schema=ALLOWED_PARAMS,
    )
    if len(complex_dev.pins) < 2:
        raise ValueError("At least two pins required")

    pins = (complex_dev.pins + [None, None, None, None])[:4]

    query = (
        "INSERT INTO tabCompDesc "
        "(IDCompDesc, IDFunction, PinA, PinB, PinC, PinD, PinS) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    params = (next_id, complex_dev.id_function, *pins, pin_s)
    cursor.execute(query, params)
    return next_id
