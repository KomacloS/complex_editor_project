from __future__ import annotations

import contextlib
import datetime as _dt
import logging
from pathlib import Path
from typing import Mapping

from ..utils import yaml_adapter as yaml
from .models import AllowlistDocument, AllowlistEntry, DbFingerprint

logger = logging.getLogger(__name__)


class AllowlistStoreError(RuntimeError):
    pass


class AllowlistStore:
    """Persistence helper for ``function_param_allowed.yaml`` within a folder."""

    FILE_NAME = "function_param_allowed.yaml"

    def __init__(self, folder: Path, *, file_name: str | None = None) -> None:
        self.folder = Path(folder).expanduser().resolve()
        self.file_name = file_name or self.FILE_NAME
        if self.folder.is_file():
            raise AllowlistStoreError("Allowlist store folder must be a directory")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / self.file_name
        if not self.path.parent.samefile(self.folder):
            raise AllowlistStoreError("Allowlist YAML must live inside the MDB folder")

    # ------------------------------ public API ------------------------------
    def load(self) -> AllowlistDocument:
        if not self.path.exists():
            return AllowlistDocument(version=1, fingerprint=None, entries=[], audit_log=[])
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        fingerprint = DbFingerprint.from_mapping(data.get("fingerprint"))
        entries_data = data.get("bundles") or []
        entries: list[AllowlistEntry] = []
        for item in entries_data:
            try:
                entry = AllowlistEntry(
                    id_function=int(item["id_function"]),
                    id_macro_kind=int(item["id_macro_kind"]),
                    function_name=str(item.get("function_name") or ""),
                    macro_kind_name=str(item.get("macro_kind_name") or ""),
                    params=list(item.get("params") or []),
                    signature_hash=str(item.get("signature_hash") or ""),
                    structure_hash=str(item.get("structure_hash") or ""),
                    active=bool(item.get("active", False)),
                    trace=item.get("trace") or {},
                )
            except Exception:
                logger.warning("Skipping malformed allowlist entry: %s", item)
                continue
            entries.append(entry)
        audit = list(data.get("audit", []))
        version = int(data.get("version", 1))
        return AllowlistDocument(version=version, fingerprint=fingerprint, entries=entries, audit_log=audit)

    def write(self, document: AllowlistDocument, *, action: str, user: str | None = None, details: Mapping[str, object] | None = None) -> None:
        payload = {
            "version": document.version,
            "fingerprint": document.fingerprint.as_dict() if document.fingerprint else None,
            "bundles": [
                {
                    "id_function": entry.id_function,
                    "id_macro_kind": entry.id_macro_kind,
                    "function_name": entry.function_name,
                    "macro_kind_name": entry.macro_kind_name,
                    "params": entry.params,
                    "signature_hash": entry.signature_hash,
                    "structure_hash": entry.structure_hash,
                    "active": bool(entry.active),
                    "trace": entry.trace,
                }
                for entry in document.entries
            ],
            "audit": document.audit_log + [
                {
                    "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
                    "action": action,
                    **({"user": user} if user else {}),
                    **(dict(details) if details else {}),
                }
            ],
        }
        serialized = yaml.safe_dump(payload, sort_keys=False)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with _lock_file(lock_path):
            self.path.write_text(serialized, encoding="utf-8")


@contextlib.contextmanager
def _lock_file(path: Path):
    """Best-effort advisory lock using ``fcntl`` when available."""

    try:
        import fcntl  # type: ignore
    except ImportError:  # pragma: no cover - Windows fallback
        handle = path.open("w+")
        try:
            yield handle
        finally:
            handle.close()
        return

    handle = path.open("w+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield handle
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

