from __future__ import annotations

import logging
from typing import Dict, Iterable, Sequence

from .models import FunctionBundle, ParameterSpec

logger = logging.getLogger(__name__)


class OverlayScannerError(RuntimeError):
    pass


class AccessMacroScanner:
    """Extract normalized bundles from an Access MDB cursor."""

    def __init__(self, cursor) -> None:
        self.cursor = cursor

    # ------------------------------ helpers ------------------------------
    def _fetch(self, query: str) -> Sequence:
        try:
            return self.cursor.execute(query).fetchall()
        except Exception as exc:  # pragma: no cover - requires pyodbc
            raise OverlayScannerError(f"Failed executing query: {query}") from exc

    def _string(self, value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _bool(self, value) -> bool:
        if value in (None, "", 0, "0", False):
            return False
        return bool(value)

    # ----------------------------- main API ------------------------------
    def scan(self) -> Iterable[FunctionBundle]:
        functions = self._fetch("SELECT IDFunction, Name FROM tabFunction")
        func_map = {}
        for row in functions:
            try:
                fid = int(getattr(row, "IDFunction"))
            except Exception:
                continue
            func_map[fid] = self._string(getattr(row, "Name", None))

        macro_rows = self._fetch(
            "SELECT det.IDFunction, det.IDMacroKind, mk.Name AS MacroKindName "
            "FROM detFunctionMacroKind det "
            "INNER JOIN tabMacroKind mk ON det.IDMacroKind = mk.IDMacroKind"
        )
        macro_map: Dict[tuple[int, int], str] = {}
        for row in macro_rows:
            fid = int(getattr(row, "IDFunction"))
            mkid = int(getattr(row, "IDMacroKind"))
            macro_map[(fid, mkid)] = self._string(getattr(row, "MacroKindName", None) or getattr(row, "Name", ""))

        unit_rows = self._fetch("SELECT IDUnit, Name FROM tabUnit")
        units = {}
        for row in unit_rows:
            uid = getattr(row, "IDUnit", None)
            if uid in (None, ""):
                continue
            try:
                units[int(uid)] = self._string(getattr(row, "Name", None))
            except Exception:
                continue

        param_class_rows = self._fetch("SELECT IDParameterClass, Name, TypeName FROM tabParameterClass")
        param_classes: Dict[int, tuple[str, str]] = {}
        for row in param_class_rows:
            try:
                pid = int(row.IDParameterClass)
            except Exception:
                continue
            pname = self._string(getattr(row, "Name", None) or getattr(row, "ParameterClass", None))
            ptype = self._string(getattr(row, "TypeName", None) or getattr(row, "ParamType", None) or pname)
            param_classes[pid] = (pname or f"Class_{pid}", ptype or "STR")

        param_rows = self._fetch(
            "SELECT IDMacroKind, Position, Name, InOut, Optional, DefaultValue, MinValue, MaxValue, IDUnit, IDParameterClass "
            "FROM detMacroKindParameterClass ORDER BY IDMacroKind, Position"
        )
        params_by_macro: Dict[int, list[ParameterSpec]] = {}
        for row in param_rows:
            mkid = int(row.IDMacroKind)
            position = int(row.Position)
            pname = self._string(row.Name)
            inout = self._string(getattr(row, "InOut", None) or "input")
            optional = self._bool(getattr(row, "Optional", None))
            default = self._string(getattr(row, "DefaultValue", None)) or None
            min_v = self._string(getattr(row, "MinValue", None)) or None
            max_v = self._string(getattr(row, "MaxValue", None)) or None
            unit_id = getattr(row, "IDUnit", None)
            unit_name = units.get(int(unit_id)) if unit_id not in (None, "") else None
            param_class_id = getattr(row, "IDParameterClass", None)
            class_name, class_type = param_classes.get(int(param_class_id or 0), (None, None))
            spec = ParameterSpec(
                position=position,
                name=pname or f"Param_{position}",
                type=class_type or "STR",
                inout=inout or "input",
                optional=optional,
                default=default,
                min_value=min_v,
                max_value=max_v,
                unit_id=int(unit_id) if unit_id not in (None, "") else None,
                unit_name=unit_name,
                enum_domain=(),
                parameter_class_id=int(param_class_id) if param_class_id not in (None, "") else None,
                parameter_class_name=class_name,
            )
            params_by_macro.setdefault(mkid, []).append(spec)

        bundles: list[FunctionBundle] = []
        for (fid, mkid), macro_name in macro_map.items():
            func_name = func_map.get(fid, f"Function_{fid}")
            raw_params = sorted(params_by_macro.get(mkid, []), key=lambda spec: spec.position)
            last_position = 0
            seen_positions: set[int] = set()
            ordered: list[ParameterSpec] = []
            for spec in raw_params:
                if spec.position in seen_positions or spec.position <= last_position:
                    raise OverlayScannerError(
                        f"Invalid parameter ordering for macro kind {mkid}: positions must be unique and increasing"
                    )
                seen_positions.add(spec.position)
                last_position = spec.position
                ordered.append(spec)
            bundles.append(
                FunctionBundle(
                    id_function=fid,
                    id_macro_kind=mkid,
                    function_name=func_name,
                    macro_kind_name=macro_name or func_name,
                    params=tuple(ordered),
                    trace={"tables": ["tabFunction", "tabMacroKind", "detMacroKindParameterClass"]},
                )
            )
        return bundles

