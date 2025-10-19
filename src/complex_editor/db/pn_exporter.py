from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

import pyodbc

from .mdb_api import MDB, ComplexDevice

pyodbc.pooling = False

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubsetExportError(Exception):
    reason: str
    status_code: int
    payload: dict[str, object]
    message: str | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message or self.reason


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


class ExportCanceled(Exception):
    """Raised when the user cancels an export in progress."""


@dataclass(frozen=True, slots=True)
class ExportOptions:
    strict_schema_compat: bool = True
    include_macros: bool = True
    include_macro_param_defs: bool = True
    fail_if_target_not_empty: bool = True


@dataclass(frozen=True, slots=True)
class ExportReport:
    target_path: Path
    pn_names: tuple[str, ...]
    complex_count: int
    subcomponent_count: int
    alias_count: int
    elapsed_seconds: float


def _normalized_pns(pn_list: Sequence[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in pn_list:
        pn = (raw or "").strip()
        if not pn:
            continue
        key = pn.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(pn)
    return ordered


def _report(cb: Optional[ProgressCallback], message: str, current: int, total: int) -> None:
    if cb is None:
        return
    try:
        cb(message, current, total)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Progress callback raised unexpectedly")


def _ensure_not_canceled(cancel_cb: Optional[CancelCallback]) -> None:
    if cancel_cb is None:
        return
    try:
        if cancel_cb():
            raise ExportCanceled()
    except ExportCanceled:
        raise
    except Exception:  # pragma: no cover - defensive
        logger.exception("Cancel callback raised unexpectedly")


def _dedupe_aliases(aliases: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        cleaned = " ".join((alias or "").strip().split())
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _prepare_device(device: ComplexDevice) -> None:
    device.aliases = _dedupe_aliases(getattr(device, "aliases", []) or [])
    subs = getattr(device, "subcomponents", []) or []
    for sub in subs:
        sub.id_sub_component = None
        pins = getattr(sub, "pins", {}) or {}
        normalized: dict[str, int] = {}
        for key, value in pins.items():
            if key is None:
                continue
            normalized[key.upper().strip()] = value
        sub.pins = normalized


def _remove_existing_target(target_path: Path) -> None:
    if target_path.exists():
        try:
            target_path.unlink()
        except OSError as exc:
            raise SubsetExportError(
                "filesystem_error",
                409,
                {
                    "path": str(target_path),
                    "errno": getattr(exc, "errno", None),
                    "detail": str(exc),
                },
                message="Unable to overwrite existing export target.",
            ) from exc


def _delete_partial_target(target_path: Path) -> None:
    try:
        target_path.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed removing partial export target %s", target_path)


def _copy_template(template_path: Path, target_path: Path) -> None:
    template_path = template_path.resolve()
    target_path = target_path.resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if template_path == target_path:
        raise SubsetExportError(
            "template_missing_or_incompatible",
            409,
            {"detail": "Template path and export target cannot be identical."},
        )

    if not template_path.exists():
        raise FileNotFoundError(str(template_path))

    size = template_path.stat().st_size
    if size == 0:
        raise SubsetExportError(
            "template_missing_or_incompatible",
            409,
            {"template_path": str(template_path), "detail": "Template file is empty."},
        )

    shutil.copyfile(template_path, target_path)

    copied_size = target_path.stat().st_size if target_path.exists() else 0
    if copied_size == 0:
        raise SubsetExportError(
            "template_missing_or_incompatible",
            409,
            {
                "template_path": str(template_path),
                "detail": "Failed to copy template to export target.",
            },
        )


def _collect_complex_devices(
    db: MDB,
    pn_names: Sequence[str],
    comp_ids: Optional[Sequence[int]],
    *,
    progress_cb: Optional[ProgressCallback],
    cancel_cb: Optional[CancelCallback],
) -> tuple[list[ComplexDevice], set[int], int, list[int], int, list[str]]:
    devices: list[ComplexDevice] = []
    macro_ids: set[int] = set()
    alias_total = 0
    subcomponent_total = 0
    export_ids: list[int] = []
    pn_out: list[str] = []

    if comp_ids:
        ids = [int(cid) for cid in comp_ids if int(cid) > 0]
        for idx, cid in enumerate(ids, start=1):
            _ensure_not_canceled(cancel_cb)
            _report(progress_cb, f"Collecting ID {cid}", idx, max(len(ids), 1))
            device = db.get_complex(cid)
            export_ids.append(cid)
            pn_out.append(str(getattr(device, "name", "") or f"ID {cid}"))
            _prepare_device(device)
            for sub in getattr(device, "subcomponents", []) or []:
                macro = getattr(sub, "id_function", None)
                if macro is not None:
                    try:
                        macro_ids.add(int(macro))
                    except Exception:
                        continue
            alias_total += len(device.aliases or [])
            subcomponent_total += len(getattr(device, "subcomponents", []) or [])
            device.id_comp_desc = None
            devices.append(device)
        return devices, macro_ids, alias_total, export_ids, subcomponent_total, pn_out

    rows = db.list_complexes()
    name_to_ids: dict[str, list[int]] = {}
    for cid, name, _ in rows:
        key = (name or "").strip().lower()
        if not key:
            continue
        name_to_ids.setdefault(key, []).append(int(cid))

    total_steps = len(pn_names)
    for idx, pn in enumerate(pn_names, start=1):
        _ensure_not_canceled(cancel_cb)
        _report(progress_cb, f"Collecting {pn}", idx, max(total_steps, 1))
        key = pn.lower()
        try:
            candidates = name_to_ids[key]
        except KeyError as exc:
            raise LookupError(f"PN '{pn}' not found in source database") from exc
        comp_id = candidates[0]
        export_ids.append(comp_id)
        device = db.get_complex(comp_id)
        pn_value = str(getattr(device, "name", "") or pn)
        pn_out.append(pn_value)
        _prepare_device(device)
        for sub in getattr(device, "subcomponents", []) or []:
            macro = getattr(sub, "id_function", None)
            if macro is not None:
                try:
                    macro_ids.add(int(macro))
                except Exception:
                    continue
        alias_total += len(device.aliases or [])
        subcomponent_total += len(getattr(device, "subcomponents", []) or [])
        device.id_comp_desc = None
        devices.append(device)
    return devices, macro_ids, alias_total, export_ids, subcomponent_total, pn_out


def _validate_macros_available(conn: pyodbc.Connection, macro_ids: Iterable[int]) -> set[int]:
    ids = {int(mid) for mid in macro_ids if mid is not None}
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    sql = f"SELECT IDFunction FROM tabFunction WHERE IDFunction IN ({placeholders})"
    cur = conn.cursor()
    cur.execute(sql, *ids)
    present = {int(row[0]) for row in cur.fetchall()}
    return ids - present


def _is_duplicate_error(exc: pyodbc.Error) -> bool:
    args = getattr(exc, "args", ())
    if args:
        state = args[0]
        if isinstance(state, str) and state.startswith("23"):
            return True
    message = " ".join(str(part) for part in args).lower()
    return "-1605" in message or ("duplicate" in message and "index" in message)


def _extract_conflict_table(message: str) -> str:
    msg = message.lower()
    if "tabcompalias" in msg:
        return "tabCompAlias"
    if "detcompdesc" in msg:
        return "detCompDesc"
    if "tabcompdesc" in msg:
        return "tabCompDesc"
    return ""


def _extract_index_name(message: str) -> str:
    match = re.search(r"in index '([^']+)'", message)
    if match:
        return match.group(1)
    return ""


def _export_using_template(
    *,
    template_path: Path,
    target_path: Path,
    devices: list[ComplexDevice],
    pn_names: Sequence[str],
    macro_ids: set[int],
    alias_total: int,
    subcomponent_total: int,
    export_ids: Sequence[int],
    progress_cb: Optional[ProgressCallback],
    cancel_cb: Optional[CancelCallback],
) -> ExportReport:
    _copy_template(template_path, target_path)

    _ensure_not_canceled(cancel_cb)
    try:
        if target_path.stat().st_size == 0:
            raise SubsetExportError(
                "template_missing_or_incompatible",
                409,
                {"template_path": str(template_path), "detail": "Copied template is empty."},
            )
    except OSError as exc:
        raise SubsetExportError(
            "filesystem_error",
            409,
            {"detail": str(exc), "path": str(target_path), "errno": getattr(exc, "errno", None)},
        ) from exc

    try:
        with MDB(target_path) as target_db:
            if macro_ids:
                missing = _validate_macros_available(target_db._conn, macro_ids)
                if missing:
                    raise SubsetExportError(
                        "template_missing_or_incompatible",
                        409,
                        {
                            "template_path": str(template_path),
                            "detail": "Template database is missing macro definitions.",
                            "missing_macro_ids": sorted(missing),
                        },
                    )

            total = len(devices)
            for idx, device in enumerate(devices, start=1):
                _ensure_not_canceled(cancel_cb)
                label = pn_names[idx - 1] if idx - 1 < len(pn_names) else f"{idx}"
                _report(progress_cb, f"Writing {label}", idx, max(total, 1))
                try:
                    target_db.create_complex(device)
                except pyodbc.DataError as exc:
                    message = " ".join(str(part) for part in getattr(exc, "args", ()))
                    if _is_duplicate_error(exc):
                        payload = {
                            "offending_comp_ids": list(export_ids),
                            "conflict_table": _extract_conflict_table(message),
                            "detail": message,
                        }
                        index_name = _extract_index_name(message)
                        if index_name:
                            payload["index_name"] = index_name
                        raise SubsetExportError(
                            "data_invalid",
                            409,
                            payload,
                            message="Duplicate key detected while inserting subset.",
                        ) from exc
                    # Access 22018: Data type mismatch in criteria expression
                    reason_payload = {"detail": message}
                    if "22018" in message or "type mismatch" in message.lower():
                        reason_payload.update(
                            {
                                "offending_table": "detCompDesc",
                                "hint": "Access type mismatch (22018) likely; see insert logs",
                            }
                        )
                    raise SubsetExportError(
                        "db_engine_error",
                        500,
                        reason_payload,
                    ) from exc
            target_db._conn.commit()
    except SubsetExportError:
        raise
    except pyodbc.Error as exc:
        message = " ".join(str(part) for part in getattr(exc, "args", ()))
        raise SubsetExportError(
            "db_engine_error",
            500,
            {"detail": message},
        ) from exc

    return ExportReport(
        target_path=target_path,
        pn_names=tuple(pn_names),
        complex_count=len(devices),
        subcomponent_count=subcomponent_total,
        alias_count=alias_total,
        elapsed_seconds=0.0,
    )


def export_pn_to_mdb(
    source_db_path: Path,
    template_path: Path,
    target_path: Path,
    pn_list: Sequence[str],
    *,
    options: Optional[ExportOptions] = None,
    comp_ids: Optional[Sequence[int]] = None,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_cb: Optional[CancelCallback] = None,
) -> ExportReport:
    opts = options or ExportOptions()
    pn_names = _normalized_pns(pn_list)
    if not pn_names and not comp_ids:
        raise ValueError("pn_list or comp_ids must contain at least one entry")

    template_path = Path(template_path).expanduser().resolve()
    if not template_path.exists():
        raise FileNotFoundError(f"Template MDB not found at {template_path}")

    source_db_path = Path(source_db_path).expanduser().resolve()
    if not source_db_path.exists():
        raise FileNotFoundError(f"Source MDB not found at {source_db_path}")

    target_path = Path(target_path).expanduser().resolve()
    _remove_existing_target(target_path)

    logger.info(
        "export_pn_to_mdb start source=%s template=%s target=%s count=%s",
        source_db_path,
        template_path,
        target_path,
        len(comp_ids or pn_names),
    )

    start = time.perf_counter()

    _report(progress_cb, "Preparing export...", 0, max(len(pn_names), 1))

    with MDB(source_db_path) as source_db:
        devices, macro_ids, alias_total, export_ids, subcomponents_total, pn_out = _collect_complex_devices(
            source_db,
            pn_names,
            comp_ids,
            progress_cb=progress_cb,
            cancel_cb=cancel_cb,
        )

    try:
        report = _export_using_template(
            template_path=template_path,
            target_path=target_path,
            devices=devices,
            pn_names=pn_out,
            macro_ids=macro_ids if (opts.strict_schema_compat and opts.include_macros) else set(),
            alias_total=alias_total,
            subcomponent_total=subcomponents_total,
            export_ids=export_ids,
            progress_cb=progress_cb,
            cancel_cb=cancel_cb,
        )
    except SubsetExportError:
        _delete_partial_target(target_path)
        raise
    except Exception:
        _delete_partial_target(target_path)
        raise

    elapsed = time.perf_counter() - start
    final_report = ExportReport(
        target_path=report.target_path,
        pn_names=tuple(pn_out),
        complex_count=len(devices),
        subcomponent_count=subcomponents_total,
        alias_count=alias_total,
        elapsed_seconds=elapsed,
    )

    logger.info(
        "export_pn_to_mdb complete target=%s count=%s elapsed=%.2fs",
        final_report.target_path,
        final_report.complex_count,
        final_report.elapsed_seconds,
    )
    return final_report


__all__ = [
    "ExportOptions",
    "ExportReport",
    "ExportCanceled",
    "SubsetExportError",
    "export_pn_to_mdb",
]
