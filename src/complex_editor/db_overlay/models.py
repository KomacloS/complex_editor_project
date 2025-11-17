from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Sequence
import hashlib
import json
import os


@dataclass(frozen=True)
class DbFingerprint:
    """Immutable fingerprint of an MDB file."""

    path: str
    size: int
    mtime: float
    sha256: str

    @staticmethod
    def compute(path: Path) -> "DbFingerprint":
        real = Path(path).expanduser().resolve(strict=True)
        stat = real.stat()
        h = hashlib.sha256()
        with real.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return DbFingerprint(
            path=str(real),
            size=int(stat.st_size),
            mtime=float(stat.st_mtime),
            sha256=h.hexdigest(),
        )

    def as_dict(self) -> MutableMapping[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "sha256": self.sha256,
        }

    @staticmethod
    def from_mapping(data: Mapping[str, object] | None) -> "DbFingerprint | None":
        if not data:
            return None
        try:
            path = str(data["path"])
            size = int(data["size"])
            mtime = float(data["mtime"])
            sha = str(data["sha256"])
        except Exception:
            return None
        return DbFingerprint(path=path, size=size, mtime=mtime, sha256=sha)

    def matches_path(self, candidate: Path) -> bool:
        try:
            resolved = Path(candidate).expanduser().resolve(strict=True)
        except FileNotFoundError:
            return False
        return os.path.samefile(resolved, Path(self.path))


@dataclass(frozen=True)
class ParameterSpec:
    position: int
    name: str
    type: str
    inout: str
    optional: bool
    default: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    unit_id: int | None = None
    unit_name: str | None = None
    enum_domain: tuple[str, ...] = ()
    parameter_class_id: int | None = None
    parameter_class_name: str | None = None

    def to_schema_entry(self) -> dict[str, object]:
        entry: dict[str, object] = {"type": self.type}
        if self.default not in (None, ""):
            entry["default"] = self.default
        if self.min_value not in (None, ""):
            entry["min"] = self.min_value
        if self.max_value not in (None, ""):
            entry["max"] = self.max_value
        if self.enum_domain:
            entry["choices"] = list(self.enum_domain)
        if self.inout:
            entry["role"] = self.inout.lower()
        if self.unit_name:
            entry["unit"] = self.unit_name
        return entry

    def structural_payload(self) -> Mapping[str, object]:
        return {
            "position": self.position,
            "name": self.name,
            "type": self.type,
            "inout": self.inout,
            "optional": bool(self.optional),
            "unit": self.unit_name,
            "enum": list(self.enum_domain),
        }

    def signature_payload(self) -> Mapping[str, object]:
        payload = dict(self.structural_payload())
        payload.update(
            {
                "default": self.default,
                "min": self.min_value,
                "max": self.max_value,
            }
        )
        return payload


@dataclass(frozen=True)
class FunctionBundle:
    id_function: int
    id_macro_kind: int
    function_name: str
    macro_kind_name: str
    params: tuple[ParameterSpec, ...]
    source: str = "db"
    trace: Mapping[str, object] = field(default_factory=dict)
    signature_hash: str = field(init=False)
    structure_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "signature_hash", self._hash(self._payload(include_limits=True)))
        object.__setattr__(self, "structure_hash", self._hash(self._payload(include_limits=False)))

    def _payload(self, *, include_limits: bool) -> Mapping[str, object]:
        return {
            "id_function": self.id_function,
            "id_macro_kind": self.id_macro_kind,
            "function_name": self.function_name,
            "macro_kind_name": self.macro_kind_name,
            "params": [
                p.signature_payload() if include_limits else p.structural_payload()
                for p in self.params
            ],
        }

    @staticmethod
    def _hash(payload: Mapping[str, object]) -> str:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def identity(self) -> tuple[int, int]:
        return (self.id_function, self.id_macro_kind)

    def to_schema_fragment(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for spec in self.params:
            result[spec.name] = spec.to_schema_entry()
        return result


@dataclass
class AllowlistEntry:
    id_function: int
    id_macro_kind: int
    function_name: str
    macro_kind_name: str
    params: list[dict[str, object]]
    signature_hash: str
    structure_hash: str
    active: bool = False
    trace: Mapping[str, object] = field(default_factory=dict)

    def identity(self) -> tuple[int, int]:
        return (self.id_function, self.id_macro_kind)

    @staticmethod
    def from_bundle(bundle: FunctionBundle, *, active: bool) -> "AllowlistEntry":
        params = [
            {
                "position": spec.position,
                "name": spec.name,
                "type": spec.type,
                "inout": spec.inout,
                "optional": spec.optional,
                "default": spec.default,
                "min": spec.min_value,
                "max": spec.max_value,
                "unit": spec.unit_name,
                "unit_id": spec.unit_id,
                "enum_domain": list(spec.enum_domain),
                "parameter_class_id": spec.parameter_class_id,
                "parameter_class_name": spec.parameter_class_name,
            }
            for spec in bundle.params
        ]
        return AllowlistEntry(
            id_function=bundle.id_function,
            id_macro_kind=bundle.id_macro_kind,
            function_name=bundle.function_name,
            macro_kind_name=bundle.macro_kind_name,
            params=params,
            signature_hash=bundle.signature_hash,
            structure_hash=bundle.structure_hash,
            active=active,
            trace=bundle.trace,
        )


@dataclass
class AllowlistDocument:
    version: int
    fingerprint: DbFingerprint | None
    entries: list[AllowlistEntry] = field(default_factory=list)
    audit_log: list[dict[str, object]] = field(default_factory=list)

    def entry_map(self) -> dict[tuple[int, int], AllowlistEntry]:
        return {entry.identity(): entry for entry in self.entries}

    def active_entries(self) -> dict[tuple[int, int], AllowlistEntry]:
        return {key: entry for key, entry in self.entry_map().items() if entry.active}

    def merge_entry(self, entry: AllowlistEntry) -> None:
        mapping = self.entry_map()
        mapping[entry.identity()] = entry
        self.entries = list(mapping.values())

    def deactivate(self, identity: tuple[int, int]) -> None:
        for entry in self.entries:
            if entry.identity() == identity:
                entry.active = False
                break


@dataclass(frozen=True)
class BundleChange:
    current: AllowlistEntry
    discovered: FunctionBundle
    change_kind: str  # "soft" or "hard"


@dataclass(frozen=True)
class BundleDiff:
    added: dict[tuple[int, int], FunctionBundle]
    removed: dict[tuple[int, int], AllowlistEntry]
    changed: dict[tuple[int, int], BundleChange]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


@dataclass(frozen=True)
class RuntimeCatalog:
    schema: Mapping[str, Mapping[str, object]]
    bundles: Mapping[tuple[int, int], FunctionBundle]
    source_label: str = "db"

    def macro_names(self) -> Sequence[str]:
        return tuple(self.schema.keys())


def build_schema_from_bundles(bundles: Iterable[FunctionBundle]) -> dict[str, dict[str, object]]:
    schema: dict[str, dict[str, object]] = {}
    for bundle in bundles:
        if not bundle.params:
            continue
        key = bundle.function_name or f"Function_{bundle.id_function}"
        unique = key
        counter = 1
        while unique in schema and schema[unique] != bundle.to_schema_fragment():
            counter += 1
            unique = f"{key}#{counter}"
        schema[unique] = bundle.to_schema_fragment()
    return schema

