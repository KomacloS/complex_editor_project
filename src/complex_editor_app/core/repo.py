"""Repository adapter wiring the Tkinter UI into the production logic."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from complex_editor.core.app_context import AppContext
from complex_editor.db import schema_introspect
from complex_editor.db.mdb_api import MDB
from complex_editor.param_spec import ALLOWED_PARAMS, resolve_macro_name
from complex_editor.util.macro_xml_translator import params_to_xml, xml_to_params_tolerant
from complex_editor.util.rules_loader import get_learned_rules

from .models import Catalog, Complex, Macro, MacroParameterSpec, Subcomponent, build_sample_catalog
from .pins import parse_pin_field

LOG = logging.getLogger(__name__)


def _coerce_default(param_type: str, value: object) -> object:
    if value in (None, ""):
        return None
    try:
        if param_type == "int":
            return int(float(value))
        if param_type == "float":
            return float(value)
        if param_type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}
    except (TypeError, ValueError):
        LOG.debug("Failed to coerce %s default %r", param_type, value)
    return value


def _canonical_macro_name(name: str) -> str:
    return resolve_macro_name(name) or name


def _build_catalog_from_macro_map(macro_map: Dict[int, schema_introspect.MacroDef]) -> Catalog:
    macros: Dict[str, Macro] = {}
    seen: Dict[str, str] = {}
    for macro_def in macro_map.values():
        display_name = macro_def.name.strip()
        canonical = _canonical_macro_name(display_name)
        yaml_spec = ALLOWED_PARAMS.get(canonical, {})
        parameters: Dict[str, MacroParameterSpec] = {}
        for param in macro_def.params:
            raw = yaml_spec.get(param.name, {})
            logical_type = str(raw.get("type") or param.type or "str").lower()
            default = raw.get("default", param.default)
            minimum = raw.get("min", param.min)
            maximum = raw.get("max", param.max)
            step = raw.get("step")
            choices = raw.get("choices")
            dependencies = raw.get("dependencies", {})
            parameters[param.name] = MacroParameterSpec(
                name=param.name,
                type=logical_type,
                default=_coerce_default(logical_type, default),
                required=bool(raw.get("required", False)),
                choices=list(choices or []) if choices else None,
                minimum=float(minimum) if minimum not in (None, "") else None,
                maximum=float(maximum) if maximum not in (None, "") else None,
                step=float(step) if step not in (None, "") else None,
                help=str(raw.get("help", "")),
                dependencies=dict(dependencies),
            )
        macros[display_name] = Macro(display_name, display_name, parameters)
        seen[_canonical_macro_name(display_name).lower()] = display_name

    # Include YAML-only macros so the editor remains feature complete.
    for yaml_name, spec in ALLOWED_PARAMS.items():
        canonical = _canonical_macro_name(yaml_name).lower()
        if canonical in seen:
            continue
        parameters: Dict[str, MacroParameterSpec] = {}
        for param_name, raw in spec.items():
            logical_type = str(raw.get("type", "str")).lower()
            parameters[param_name] = MacroParameterSpec(
                name=param_name,
                type=logical_type,
                default=_coerce_default(logical_type, raw.get("default")),
                required=bool(raw.get("required", False)),
                choices=list(raw.get("choices", []) or []) or None,
                minimum=float(raw["min"]) if "min" in raw else None,
                maximum=float(raw["max"]) if "max" in raw else None,
                step=float(raw["step"]) if "step" in raw else None,
                help=str(raw.get("help", "")),
                dependencies=dict(raw.get("dependencies", {})),
            )
        macros[yaml_name] = Macro(yaml_name, yaml_name, parameters)

    return Catalog(macros)


def _decode_pin(pin: object) -> str:
    if pin in (None, "", 0):
        return ""
    try:
        value = int(pin)
        return str(value) if value > 0 else ""
    except Exception:
        return str(pin)


def _decode_pin_s(raw: object) -> str:
    if not raw:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        for encoding in ("utf-16", "utf-8", "latin-1"):
            try:
                return raw.decode(encoding)
            except Exception:
                continue
        return ""
    return str(raw)


def _normalize_pin_key(key: str) -> str:
    key = key.strip().upper()
    if key in {"A", "B", "C", "D", "S"}:
        return key
    if key.startswith("PIN") and len(key) >= 4:
        suffix = key[-1]
        if suffix in {"A", "B", "C", "D", "S"}:
            return suffix
    return key


def _normalize_pin_value(value: object) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _legacy_subcomponent_params(
    macro_name: str, s_payload: object, rules: Optional[object]
) -> Dict[str, object]:
    text = _decode_pin_s(s_payload)
    if not text:
        return {}
    try:
        xml_map = xml_to_params_tolerant(text, rules=rules)
    except Exception:
        LOG.debug("Legacy buffer PinS payload for '%s' could not be parsed", macro_name)
        return {}
    canonical = macro_name
    if rules and getattr(rules, "macro_aliases", None):
        canonical = rules.macro_aliases.get(macro_name, macro_name)
    payload = xml_map.get(canonical) or xml_map.get(macro_name)
    if not payload and xml_map:
        payload = next(iter(xml_map.values()))
    return dict(payload or {})


def _legacy_extract_pins(entry: Dict[str, object]) -> tuple[Dict[str, str], object]:
    pins: Dict[str, str] = {}
    s_payload: object = entry.get("PinS") or entry.get("S") or entry.get("pins_s")
    raw = entry.get("pins") or entry.get("Pins") or entry.get("pin_map") or entry.get("PinMap")
    if isinstance(raw, dict):
        for key, value in raw.items():
            norm = _normalize_pin_key(str(key))
            if norm == "S":
                s_payload = value
            elif norm in {"A", "B", "C", "D"}:
                pins[norm] = _normalize_pin_value(value)
    for key, value in entry.items():
        if key in {"pins", "Pins", "pin_map", "PinMap"}:
            continue
        norm = _normalize_pin_key(str(key))
        if norm == "S":
            s_payload = value
        elif norm in {"A", "B", "C", "D"} and norm not in pins:
            pins[norm] = _normalize_pin_value(value)
    for leg in ("A", "B", "C", "D"):
        pins.setdefault(leg, "")
    return pins, s_payload


def _legacy_complexes(payload: object, rules: Optional[object]) -> Iterable[Complex]:
    if isinstance(payload, dict):
        items = payload.get("complexes") or payload.get("Complexes") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    for idx, entry in enumerate(items, start=1):
        if not isinstance(entry, dict):
            continue
        identifier = str(entry.get("identifier") or entry.get("id") or idx)
        part_number = str(entry.get("part_number") or entry.get("name") or identifier)
        alt = [str(x) for x in (entry.get("alternate_part_numbers") or []) if str(x)]
        aliases = [str(x) for x in (entry.get("aliases") or []) if str(x)]
        pin_count = entry.get("pin_count")
        if pin_count is None:
            pins_list = entry.get("pins") or []
            if isinstance(pins_list, list):
                pin_count = sum(1 for pin in pins_list if str(pin))
            else:
                pin_count = 0
        try:
            pin_count_int = int(pin_count)
        except Exception:
            pin_count_int = 0
        sub_rows = entry.get("subcomponents") or entry.get("Subcomponents") or []
        subcomponents: List[Subcomponent] = []
        for pos, row in enumerate(sub_rows, start=1):
            if not isinstance(row, dict):
                continue
            macro_raw = str(
                row.get("macro")
                or row.get("Macro")
                or row.get("function_name")
                or row.get("FunctionName")
                or row.get("name")
                or ""
            )
            macro_name = macro_raw
            if rules and getattr(rules, "macro_aliases", None):
                macro_name = rules.macro_aliases.get(macro_raw, macro_raw)
            pins, s_payload = _legacy_extract_pins(row)
            parameters = _legacy_subcomponent_params(macro_name, s_payload, rules)
            function_id = row.get("id_function") or row.get("IDFunction") or row.get("IdFunction")
            try:
                function_id_int = int(function_id) if function_id is not None else None
            except Exception:
                function_id_int = None
            subcomponents.append(
                Subcomponent(
                    position=int(row.get("position") or pos),
                    macro=macro_name or macro_raw,
                    pin_a=pins.get("A", ""),
                    pin_b=pins.get("B", ""),
                    pin_c=pins.get("C", ""),
                    pin_d=pins.get("D", ""),
                    parameters=parameters,
                    function_id=function_id_int,
                )
            )
        yield Complex(
            identifier=identifier,
            part_number=part_number,
            alternate_part_numbers=alt,
            aliases=aliases,
            pin_count=pin_count_int,
            subcomponents=subcomponents,
        )


def _parse_buffer(payload: object, rules: Optional[object]) -> Dict[str, Complex]:
    cache: Dict[str, Complex] = {}
    complexes_iterable: Iterable[Complex]
    if isinstance(payload, dict) and "complexes" in payload:
        complexes_iterable = []
        raw_complexes = payload.get("complexes") or []
        for idx, entry in enumerate(raw_complexes, start=1):
            if not isinstance(entry, dict):
                continue
            identifier = str(entry.get("identifier") or entry.get("id") or idx)
            part_number = str(entry.get("part_number") or entry.get("name") or identifier)
            alt = [str(x) for x in (entry.get("alternate_part_numbers") or []) if str(x)]
            aliases = [str(x) for x in (entry.get("aliases") or []) if str(x)]
            try:
                pin_count = int(entry.get("pin_count") or 0)
            except Exception:
                pin_count = 0
            subcomponents: List[Subcomponent] = []
            sub_entries = sorted(
                entry.get("subcomponents") or [],
                key=lambda item: int(item.get("position", 0)) if isinstance(item, dict) else 0,
            )
            for pos, row in enumerate(sub_entries, start=1):
                if not isinstance(row, dict):
                    continue
                macro_name = str(row.get("macro") or "")
                pins = {
                    "A": _normalize_pin_value(row.get("pin_a")),
                    "B": _normalize_pin_value(row.get("pin_b")),
                    "C": _normalize_pin_value(row.get("pin_c")),
                    "D": _normalize_pin_value(row.get("pin_d")),
                }
                parameters = {
                    str(k): v for k, v in (row.get("parameters") or {}).items()
                }
                function_id = row.get("function_id")
                try:
                    function_id_int = int(function_id) if function_id is not None else None
                except Exception:
                    function_id_int = None
                subcomponents.append(
                    Subcomponent(
                        position=int(row.get("position") or pos),
                        macro=macro_name,
                        pin_a=pins.get("A", ""),
                        pin_b=pins.get("B", ""),
                        pin_c=pins.get("C", ""),
                        pin_d=pins.get("D", ""),
                        parameters=parameters,
                        function_id=function_id_int,
                    )
                )
            cache[identifier] = Complex(
                identifier=identifier,
                part_number=part_number,
                alternate_part_numbers=alt,
                aliases=aliases,
                pin_count=pin_count,
                subcomponents=subcomponents,
            )
        return cache
    complexes_iterable = _legacy_complexes(payload, rules)
    for complex_obj in complexes_iterable:
        cache[complex_obj.identifier] = complex_obj
    return cache


def _demo_complexes() -> Iterable[Complex]:
    resistor = Complex(
        identifier="cmp-100",
        part_number="CMP-100",
        alternate_part_numbers=["CMP-100A"],
        aliases=["demo-board"],
        pin_count=16,
        subcomponents=[
            Subcomponent(
                position=1,
                macro="Resistor",
                pin_a="1",
                pin_b="2",
                pin_c="",
                pin_d="",
                parameters={"value": 10000.0, "tolerance": "1%"},
            ),
            Subcomponent(
                position=2,
                macro="BufferGate",
                pin_a="3",
                pin_b="4",
                parameters={"channels": 2, "schmitt": True},
            ),
        ],
    )

    led_chain = Complex(
        identifier="cmp-200",
        part_number="CMP-200",
        alternate_part_numbers=["CMP-200B"],
        aliases=["indicator"],
        pin_count=12,
        subcomponents=[
            Subcomponent(
                position=1,
                macro="LED",
                pin_a="5",
                pin_b="6",
                parameters={"color": "green", "forward_voltage": 2.1},
            ),
            Subcomponent(
                position=2,
                macro="LED",
                pin_a="7",
                pin_b="8",
                parameters={"color": "red", "forward_voltage": 1.9},
            ),
        ],
    )

    for item in (resistor, led_chain):
        item.db_id = None
        yield item


def _clone_complex(obj: Complex) -> Complex:
    clone = replace(obj)
    clone.alternate_part_numbers = list(obj.alternate_part_numbers)
    clone.aliases = list(obj.aliases)
    clone.subcomponents = []
    for sub in obj.subcomponents:
        new_sub = replace(sub)
        new_sub.parameters = dict(sub.parameters)
        clone.subcomponents.append(new_sub)
    return clone


class Repository:
    """Bridge between the Tkinter UI and the production backends."""

    def __init__(
        self,
        *,
        buffer_path: Optional[Path] = None,
        mdb_path: Optional[Path] = None,
        context: Optional[AppContext] = None,
    ) -> None:
        self.buffer_path = buffer_path
        self.ctx = context or AppContext()
        self.db: MDB | None = None
        self._macro_map: Dict[int, schema_introspect.MacroDef] = {}
        self._macro_id_by_name: Dict[str, int] = {}
        self._complex_cache: Dict[str, Complex] = {}
        self._rules = get_learned_rules()
        self.mode: str

        if buffer_path is not None and Path(buffer_path).exists():
            self.mode = "buffer"
            self.catalog = _build_catalog_from_macro_map({})
            self._load_from_buffer(Path(buffer_path))
            return

        self.mode = "db"
        try:
            self.db = self.ctx.open_main_db(mdb_path) if mdb_path else self.ctx.open_main_db(None)
        except Exception as exc:  # pragma: no cover - depends on environment
            LOG.error("Failed to open MDB: %s", exc)
            self.mode = "demo"
            self.catalog = build_sample_catalog()
            self._complex_cache = {c.identifier: c for c in _demo_complexes()}
            return

        try:
            cursor = self.db._conn.cursor()  # type: ignore[attr-defined]
        except Exception:
            cursor = None
        try:
            self._macro_map = schema_introspect.discover_macro_map(cursor) if cursor else {}
        except Exception as exc:  # pragma: no cover - defensive
            LOG.warning("Failed to discover macro map: %s", exc)
            self._macro_map = {}
        self.catalog = _build_catalog_from_macro_map(self._macro_map)
        self._macro_id_by_name = {
            macro_def.name.strip().lower(): macro_id for macro_id, macro_def in self._macro_map.items()
        }
        if self.db is not None:
            try:
                for fid, name in self.db.list_functions():
                    key = str(name).strip().lower()
                    self._macro_id_by_name.setdefault(key, int(fid))
            except Exception as exc:  # pragma: no cover - defensive
                LOG.debug("Failed to list functions for macro lookup: %s", exc)
        self._load_all_complexes()

    # ------------------------------------------------------------------
    def _load_from_buffer(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._complex_cache = {}
            return
        except json.JSONDecodeError as exc:
            LOG.error("Failed to parse buffer '%s': %s", path, exc)
            self._complex_cache = {}
            return
        self._complex_cache = _parse_buffer(payload, self._rules)

    def _load_all_complexes(self) -> None:
        if self.mode != "db" or not self.db:
            return
        cache: Dict[str, Complex] = {}
        try:
            rows = self.db.list_complexes()
        except Exception as exc:
            LOG.error("Failed to list complexes: %s", exc)
            rows = []
        for comp_id, _name, _subs in rows:
            complex_obj = self._load_single_complex(int(comp_id))
            cache[complex_obj.identifier] = complex_obj
        self._complex_cache = cache

    def _load_single_complex(self, comp_id: int) -> Complex:
        assert self.db is not None
        raw = self.db.get_complex(comp_id)
        aliases = list(getattr(raw, "aliases", []) or [])
        subcomponents: List[Subcomponent] = []
        for idx, sc in enumerate(getattr(raw, "subcomponents", []) or [], start=1):
            macro_def = self._macro_map.get(sc.id_function)
            macro_name = macro_def.name.strip() if macro_def else f"Function {sc.id_function}"
            pins = sc.pins or {}
            pin_s_text = _decode_pin_s(pins.get("S"))
            params: Dict[str, str] = {}
            if pin_s_text:
                try:
                    xml_map = xml_to_params_tolerant(pin_s_text, rules=self._rules)
                except Exception:
                    xml_map = {}
                params = dict(xml_map.get(macro_name) or (next(iter(xml_map.values())) if xml_map else {}))
            subcomponents.append(
                Subcomponent(
                    position=idx,
                    macro=macro_name,
                    pin_a=_decode_pin(pins.get("A")),
                    pin_b=_decode_pin(pins.get("B")),
                    pin_c=_decode_pin(pins.get("C")),
                    pin_d=_decode_pin(pins.get("D")),
                    parameters=params,
                    function_id=int(sc.id_function),
                )
            )
        identifier = str(getattr(raw, "id_comp_desc", comp_id))
        return Complex(
            identifier=identifier,
            part_number=str(getattr(raw, "name", "")),
            alternate_part_numbers=list(aliases),
            aliases=list(aliases),
            pin_count=int(getattr(raw, "total_pins", 0) or 0),
            subcomponents=subcomponents,
            db_id=int(getattr(raw, "id_comp_desc", comp_id) or comp_id),
        )

    # ------------------------------------------------------------------
    def list_complexes(self) -> List[Complex]:
        if not self._complex_cache and self.mode == "db":
            self._load_all_complexes()
        return [
            _clone_complex(c)
            for c in sorted(self._complex_cache.values(), key=lambda c: c.part_number.lower())
        ]

    def get_complex(self, identifier: str) -> Optional[Complex]:
        if identifier in self._complex_cache:
            return _clone_complex(self._complex_cache[identifier])
        if self.mode == "db" and identifier.isdigit():
            complex_obj = self._load_single_complex(int(identifier))
            self._complex_cache[identifier] = complex_obj
            return _clone_complex(complex_obj)
        return None

    # ------------------------------------------------------------------
    def upsert_complex(self, complex_obj: Complex) -> Complex:
        if self.mode == "buffer":
            return self._save_to_buffer(complex_obj)
        if self.mode != "db" or not self.db:
            raise RuntimeError("Database not available")
        saved = self._persist_to_db(complex_obj)
        self._complex_cache[saved.identifier] = saved
        return _clone_complex(saved)

    # ------------------------------------------------------------------
    def _macro_id_for_name(self, name: str) -> Optional[int]:
        lookup = self._macro_id_by_name.get(name.strip().lower())
        if lookup is not None:
            return lookup
        # Fallback via canonical name to catch YAML-only definitions.
        canonical = _canonical_macro_name(name).lower()
        for macro_id, macro_def in self._macro_map.items():
            if _canonical_macro_name(macro_def.name).lower() == canonical:
                self._macro_id_by_name[name.strip().lower()] = macro_id
                return macro_id
        return None

    def _persist_to_db(self, complex_obj: Complex) -> Complex:
        from complex_editor.db.mdb_api import ComplexDevice as DbComplex, SubComponent as DbSub

        aliases = list(dict.fromkeys([*(complex_obj.alternate_part_numbers or []), *(complex_obj.aliases or [])]))
        subcomponents: List[DbSub] = []
        rows = sorted(complex_obj.subcomponents, key=lambda sc: sc.position)
        for row in rows:
            macro_id = self._macro_id_for_name(row.macro)
            if macro_id is None:
                raise ValueError(f"Unknown macro '{row.macro}'")
            pins_lists = {
                "A": parse_pin_field(row.pin_a),
                "B": parse_pin_field(row.pin_b),
                "C": parse_pin_field(row.pin_c),
                "D": parse_pin_field(row.pin_d),
            }
            pin_values: Dict[str, int] = {}
            for leg, values in pins_lists.items():
                if len(values) > 1:
                    raise ValueError(f"Row {row.position} pin {leg} maps to multiple pins; split across rows.")
                pin_values[leg] = values[0] if values else 0
            param_payload = {key: str(value) for key, value in (row.parameters or {}).items()}
            xml_blob = params_to_xml({row.macro: param_payload}, encoding="utf-16")
            if isinstance(xml_blob, (bytes, bytearray)):
                pin_values["S"] = xml_blob.decode("utf-16", errors="ignore")
            else:
                pin_values["S"] = str(xml_blob or "")
            subcomponents.append(
                DbSub(
                    id_sub_component=None,
                    id_function=int(macro_id),
                    value=0.0,
                    id_unit=1,
                    tol_p=0.0,
                    tol_n=0.0,
                    force_bits=0,
                    pins=pin_values,
                )
            )

        db_device = DbComplex(
            id_comp_desc=complex_obj.db_id,
            name=str(complex_obj.part_number).strip(),
            total_pins=int(complex_obj.pin_count),
            subcomponents=subcomponents,
            aliases=aliases,
        )

        if complex_obj.db_id is None:
            new_id = self.db.add_complex(db_device)
            saved = self._load_single_complex(int(new_id))
        else:
            self.db.update_complex(int(complex_obj.db_id), updated=db_device)
            saved = self._load_single_complex(int(complex_obj.db_id))
        return saved

    def _save_to_buffer(self, complex_obj: Complex) -> Complex:
        assert self.buffer_path is not None
        target = Path(self.buffer_path)
        existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"complexes": []}
        complexes = existing.get("complexes", [])
        serialized = self._serialize_complex(complex_obj)
        for idx, row in enumerate(complexes):
            if str(row.get("identifier")) == complex_obj.identifier:
                complexes[idx] = serialized
                break
        else:
            complexes.append(serialized)
        existing["complexes"] = complexes
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        stored = _clone_complex(complex_obj)
        self._complex_cache[stored.identifier] = stored
        return _clone_complex(stored)

    def _serialize_complex(self, complex_obj: Complex) -> Dict[str, object]:
        return {
            "identifier": complex_obj.identifier,
            "part_number": complex_obj.part_number,
            "alternate_part_numbers": list(complex_obj.alternate_part_numbers),
            "aliases": list(complex_obj.aliases),
            "pin_count": int(complex_obj.pin_count),
            "subcomponents": [
                {
                    "position": sc.position,
                    "macro": sc.macro,
                    "pin_a": sc.pin_a,
                    "pin_b": sc.pin_b,
                    "pin_c": sc.pin_c,
                    "pin_d": sc.pin_d,
                    "parameters": dict(sc.parameters),
                }
                for sc in complex_obj.subcomponents
            ],
        }


__all__ = ["Repository"]

