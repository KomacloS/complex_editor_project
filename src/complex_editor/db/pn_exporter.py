from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

import pyodbc

from .mdb_api import DRIVER, MDB, ComplexDevice, ALIAS_T

pyodbc.pooling = False

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


class ExportCanceled(Exception):
    """Raised when the user cancels an export in progress."""


@dataclass(frozen=True, slots=True)
class ExportOptions:
    """Exporter tuning flags."""

    strict_schema_compat: bool = True
    include_macros: bool = True
    include_macro_param_defs: bool = True
    fail_if_target_not_empty: bool = True


@dataclass(frozen=True, slots=True)
class ExportReport:
    """Summary metadata returned when an export completes successfully."""

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


def _report(progress_cb: Optional[ProgressCallback], message: str, current: int, total: int) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(message, current, total)
    except Exception:  # pragma: no cover - defensive guard
        logger.exception("Progress callback raised unexpectedly")


def _ensure_not_canceled(cancel_cb: Optional[CancelCallback]) -> None:
    if cancel_cb is None:
        return
    try:
        if cancel_cb():
            raise ExportCanceled()
    except ExportCanceled:
        raise
    except Exception:  # pragma: no cover - defensive guard
        logger.exception("Cancel callback raised unexpectedly")


def _copy_template(template_path: Path, target_path: Path) -> None:
    template_path = template_path.resolve()
    target_path = target_path.resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if template_path == target_path:
        raise RuntimeError("Template path and export target cannot be the same file.")
    if not template_path.exists():
        raise FileNotFoundError(f"Template MDB not found at {template_path}")
    template_size = template_path.stat().st_size
    if template_size == 0:
        raise RuntimeError(f"Selected template appears to be empty: {template_path}")
    shutil.copyfile(template_path, target_path)
    copied_size = target_path.stat().st_size if target_path.exists() else 0
    if copied_size == 0:
        raise RuntimeError(
            f"Failed to copy template to export target. Template: {template_path} -> Target: {target_path}. "
            "Verify the template file and try again."
        )


def _collect_complex_devices(
    db: MDB,
    pn_names: Sequence[str],
    *,
    progress_cb: Optional[ProgressCallback],
    cancel_cb: Optional[CancelCallback],
) -> tuple[list[ComplexDevice], set[int], int, set[int], int]:
    rows = db.list_complexes()
    name_to_ids: dict[str, list[int]] = {}
    for cid, name, _ in rows:
        key = (name or "").strip().lower()
        if not key:
            continue
        name_to_ids.setdefault(key, []).append(int(cid))

    devices: list[ComplexDevice] = []
    macro_ids: set[int] = set()
    alias_total = 0
    keep_ids: set[int] = set()
    subcomponent_total = 0
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
        keep_ids.add(comp_id)
        device = db.get_complex(comp_id)
        device.id_comp_desc = None
        for sub in getattr(device, "subcomponents", []) or []:
            macro_id = getattr(sub, "id_function", None)
            if macro_id is not None:
                try:
                    macro_ids.add(int(macro_id))
                except Exception:
                    continue
            sub.id_sub_component = None
        aliases = getattr(device, "aliases", []) or []
        alias_total += len(aliases)
        subcomponent_total += len(getattr(device, "subcomponents", []) or [])
        devices.append(device)
    return devices, macro_ids, alias_total, keep_ids, subcomponent_total


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


def _prune_alias_table(db: MDB, keep_ids: set[int]) -> None:
    cur = db._conn.cursor()
    try:
        fk_col, alias_col, pk_col = db._alias_schema(cur)
    except RuntimeError:
        return
    if keep_ids:
        placeholders = ",".join("?" for _ in keep_ids)
        cur.execute(
            f"DELETE FROM {ALIAS_T} WHERE {fk_col} NOT IN ({placeholders})",
            *keep_ids,
        )
    else:
        cur.execute(f"DELETE FROM {ALIAS_T}")


def _export_using_template(
    *,
    template_path: Path,
    target_path: Path,
    devices: list[ComplexDevice],
    pn_names: Sequence[str],
    macro_ids: set[int],
    alias_total: int,
    subcomponent_total: int,
    progress_cb: Optional[ProgressCallback],
    cancel_cb: Optional[CancelCallback],
) -> ExportReport:
    _copy_template(template_path, target_path)

    _ensure_not_canceled(cancel_cb)
    try:
        if target_path.stat().st_size == 0:
            raise RuntimeError(
                "Export database at target path is empty after copying template."
            )
    except OSError as exc:
        raise RuntimeError(f"Unable to prepare export target: {target_path}") from exc

    try:
        with MDB(target_path) as target_db:
            if macro_ids:
                missing = _validate_macros_available(target_db._conn, macro_ids)
                if missing:
                    raise RuntimeError(
                        "Template database is missing macro definitions for IDs: "
                        + ", ".join(str(mid) for mid in sorted(missing))
                    )

            for idx, device in enumerate(devices, start=1):
                _ensure_not_canceled(cancel_cb)
                _report(
                    progress_cb,
                    f"Writing {pn_names[idx-1]}",
                    idx,
                    max(len(devices), 1),
                )
                try:
                    target_db.create_complex(device)
                except pyodbc.DataError as exc:
                    raise RuntimeError(
                        "Template schema mismatch detected while inserting subcomponents.\n"
                        f"Template path: {template_path}\n"
                        "Ensure the empty template matches the source database schema."
                    ) from exc
            target_db._conn.commit()
    except pyodbc.Error as exc:  # pragma: no cover - defensive
        logger.exception("Unable to open export database at %s", target_path)
        raise RuntimeError(
            f"Unable to open export database:\n{target_path}\n\n{exc}"
        ) from exc

    return ExportReport(
        target_path=target_path,
        pn_names=tuple(pn_names),
        complex_count=len(pn_names),
        subcomponent_count=subcomponent_total,
        alias_count=alias_total,
        elapsed_seconds=0.0,
    )


def _export_via_copy(
    *,
    source_db_path: Path,
    target_path: Path,
    pn_names: Sequence[str],
    keep_ids: set[int],
    alias_total: int,
    subcomponent_total: int,
    progress_cb: Optional[ProgressCallback],
    cancel_cb: Optional[CancelCallback],
) -> ExportReport:
    _report(progress_cb, "Cloning source database...", 0, 0)
    _ensure_not_canceled(cancel_cb)
    shutil.copyfile(source_db_path, target_path)

    _ensure_not_canceled(cancel_cb)
    with MDB(target_path) as target_db:
        cur = target_db._conn.cursor()
        cur.execute("SELECT IDCompDesc FROM tabCompDesc")
        all_ids = {int(row[0]) for row in cur.fetchall()}
        to_delete = sorted(all_ids - keep_ids)
        total = len(to_delete)
        for idx, cid in enumerate(to_delete, start=1):
            _ensure_not_canceled(cancel_cb)
            _report(
                progress_cb,
                f"Removing complex {cid}",
                idx,
                max(total, 1),
            )
            target_db.delete_complex(cid, cascade=True)
        _prune_alias_table(target_db, keep_ids)
        target_db._conn.commit()

    return ExportReport(
        target_path=target_path,
        pn_names=tuple(pn_names),
        complex_count=len(pn_names),
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
    progress_cb: Optional[ProgressCallback] = None,
    cancel_cb: Optional[CancelCallback] = None,
) -> ExportReport:
    """
    Export selected PNs from ``source_db_path`` into a fresh MDB at ``target_path``.
    """

    opts = options or ExportOptions()
    pn_names = _normalized_pns(pn_list)
    if not pn_names:
        raise ValueError("pn_list must contain at least one PN")

    template_path = Path(template_path).expanduser().resolve()
    if not template_path.exists():
        raise FileNotFoundError(f"Template MDB not found at {template_path}")
    source_db_path = Path(source_db_path).expanduser().resolve()
    if not source_db_path.exists():
        raise FileNotFoundError(f"Source MDB not found at {source_db_path}")
    target_path = Path(target_path).expanduser().resolve()

    logger.info(
        "export_pn_to_mdb start source=%s template=%s target=%s pn_count=%s",
        source_db_path,
        template_path,
        target_path,
        len(pn_names),
    )

    start = time.perf_counter()

    _report(progress_cb, "Preparing export...", 0, max(len(pn_names), 1))
    with MDB(source_db_path) as source_db:
        devices, macro_ids, alias_total, keep_ids, subcomponent_total = _collect_complex_devices(
            source_db,
            pn_names,
            progress_cb=progress_cb,
            cancel_cb=cancel_cb,
        )

    try:
        report = _export_using_template(
            template_path=template_path,
            target_path=target_path,
            devices=devices,
            pn_names=pn_names,
            macro_ids=macro_ids if opts.strict_schema_compat else set(),
            alias_total=alias_total,
            subcomponent_total=subcomponent_total,
            progress_cb=progress_cb,
            cancel_cb=cancel_cb,
        )
    except RuntimeError as exc:
        message = str(exc)
        if (
            "Template schema mismatch" in message
            or "empty after copying template" in message
            or "template appears to be empty" in message.lower()
        ):
            logger.warning(
                "Template-based export failed (%s). Falling back to copy-based export.",
                message,
            )
            report = _export_via_copy(
                source_db_path=source_db_path,
                target_path=target_path,
                pn_names=pn_names,
                keep_ids=keep_ids,
                alias_total=alias_total,
                subcomponent_total=subcomponent_total,
                progress_cb=progress_cb,
                cancel_cb=cancel_cb,
            )
        else:
            raise

    elapsed = time.perf_counter() - start
    final_report = ExportReport(
        target_path=report.target_path,
        pn_names=report.pn_names,
        complex_count=report.complex_count,
        subcomponent_count=report.subcomponent_count,
        alias_count=report.alias_count,
        elapsed_seconds=elapsed,
    )
    logger.info(
        "export_pn_to_mdb complete target=%s pn_count=%s subcomponents=%s aliases=%s elapsed=%.2fs",
        final_report.target_path,
        len(pn_names),
        final_report.subcomponent_count,
        final_report.alias_count,
        final_report.elapsed_seconds,
    )
    return final_report


__all__ = [
    "ExportOptions",
    "ExportReport",
    "ExportCanceled",
    "export_pn_to_mdb",
]
