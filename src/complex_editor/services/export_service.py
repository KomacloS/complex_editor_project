from __future__ import annotations

from ..domain import ComplexDevice, macro_to_xml
from ..db import table_exists


def insert_complex(conn, complex_dev: ComplexDevice) -> int:
    """Insert *complex_dev* into tabCompDesc and return new ID."""
    cursor = conn.cursor()
    if not table_exists(cursor, "tabCompDesc"):
        raise RuntimeError("tabCompDesc table missing")

    cursor.execute("SELECT MAX(IDCompDesc) FROM tabCompDesc")
    max_id = cursor.scalar()
    next_id = (max_id or 0) + 1

    pin_s = macro_to_xml(complex_dev.macro).encode("utf-16le")
    query = (
        "INSERT INTO tabCompDesc "
        "(IDCompDesc, IDFunction, PinA, PinB, PinC, PinD, PinS) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    cursor.execute(
        query,
        (
            next_id,
            complex_dev.id_function,
            complex_dev.pins[0],
            complex_dev.pins[1],
            complex_dev.pins[2],
            complex_dev.pins[3],
            pin_s,
        ),
    )
    return next_id
