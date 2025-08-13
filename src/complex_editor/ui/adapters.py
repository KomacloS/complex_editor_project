from __future__ import annotations

"""Adapters for converting DB models to editor-friendly models.

This module defines small dataclasses used by :mod:`complex_editor.ui` to load
complex devices into the :class:`~complex_editor.ui.complex_editor.ComplexEditor`
without pulling in any GUI dependencies.  The conversion is intentionally
read-only and side-effect free.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - for type checkers only
    from ..db.mdb_api import MDB, ComplexDevice, SubComponent


@dataclass
class EditorMacro:
    """Simplified macro representation for the editor."""

    name: str
    pins: Dict[str, str]
    params: Dict[str, Any]


@dataclass
class EditorComplex:
    """Simplified complex device used by the editor."""

    id: int
    name: str
    pins: List[str]
    subcomponents: List[EditorMacro]


def to_editor_model(db: "MDB", cx_db: "ComplexDevice") -> EditorComplex:
    """Convert a DB :class:`ComplexDevice` into an editor-friendly model.

    Parameters
    ----------
    db:
        Open :class:`MDB` instance used to resolve function names.
    cx_db:
        Complex device as returned by :meth:`MDB.get_complex`.

    Returns
    -------
    EditorComplex
        Object ready to be consumed by :func:`ComplexEditor.load_from_model`.
    """

    total = int(getattr(cx_db, "total_pins", 0) or 0)
    pins = [str(i) for i in range(1, total + 1)]

    # Build function-name lookup once.
    try:
        func_map = {int(fid): str(name) for fid, name in db.list_functions()}
    except Exception:  # pragma: no cover - defensive fallback
        func_map = {}

    sub_macros: List[EditorMacro] = []
    for sc in getattr(cx_db, "subcomponents", []) or []:
        fname = func_map.get(sc.id_function, f"Function {sc.id_function}")
        pin_map = {str(k): str(v) for k, v in (sc.pins or {}).items()}
        em = EditorMacro(name=fname, pins=pin_map, params={})
        # attach optional attributes used by the editor table
        if getattr(sc, "id_sub_component", None) is not None:
            em.sub_id = int(sc.id_sub_component)
        if getattr(sc, "value", None) not in (None, ""):
            em.value = str(sc.value)
        if getattr(sc, "force_bits", None) is not None:
            em.force_bits = int(sc.force_bits)
        sub_macros.append(em)

    return EditorComplex(
        id=int(getattr(cx_db, "id_comp_desc", 0) or 0),
        name=str(getattr(cx_db, "name", "")),
        pins=pins,
        subcomponents=sub_macros,
    )
