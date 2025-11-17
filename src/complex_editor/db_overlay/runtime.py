from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping

from complex_editor.config.loader import DbOverlayConfig
from complex_editor.domain.models import MacroDef, MacroParam
from complex_editor.param_spec import set_dynamic_param_specs

from .diff import BundleDiff, diff_bundles
from .models import AllowlistDocument, FunctionBundle, RuntimeCatalog, build_schema_from_bundles, DbFingerprint, AllowlistEntry
from .scanner import AccessMacroScanner, OverlayScannerError
from .store import AllowlistStore, AllowlistStoreError

logger = logging.getLogger(__name__)

CursorFactory = Callable[[], object]


@dataclass
class OverlayState:
    ready: bool
    fingerprint_pending: bool
    diff: BundleDiff | None


class DbOverlayRuntime:
    def __init__(
        self,
        config: DbOverlayConfig | None = None,
        *,
        scanner_cls=AccessMacroScanner,
    ) -> None:
        self.config = config or DbOverlayConfig()
        self.scanner_cls = scanner_cls
        self._store: AllowlistStore | None = None
        self._document: AllowlistDocument | None = None
        self._bundles: dict[tuple[int, int], FunctionBundle] = {}
        self._session_bundles: dict[tuple[int, int], FunctionBundle] = {}
        self._diff: BundleDiff | None = None
        self._pending_fingerprint: DbFingerprint | None = None
        self._fingerprint: DbFingerprint | None = None
        self._state = "disabled"
        self._active_catalog: RuntimeCatalog | None = None
        self._cursor_factory: CursorFactory | None = None
        self._db_path: Path | None = None

    # --------------------------- configuration ---------------------------
    def configure(self, config: DbOverlayConfig | None) -> None:
        self.config = config or DbOverlayConfig()
        if not self.config.enabled:
            self._disable()
        else:
            self._state = "idle"

    # --------------------------- public API ------------------------------
    def bind_to_database(self, *, db_path: Path, cursor_factory: CursorFactory) -> None:
        self._cursor_factory = cursor_factory
        self._db_path = Path(db_path)
        if not self.config.enabled:
            self._disable()
            return
        try:
            fingerprint = DbFingerprint.compute(self._db_path)
        except FileNotFoundError:
            logger.warning("DB overlay fingerprint failed; MDB missing: %s", db_path)
            self._disable()
            return
        folder = self._db_path.parent
        try:
            store = AllowlistStore(folder, file_name=self.config.yaml_name)
        except AllowlistStoreError:
            logger.exception("Failed initialising allowlist store")
            self._disable()
            return
        document = store.load()
        if document.fingerprint is None:
            document.fingerprint = fingerprint
            try:
                store.write(document, action="init", details={"reason": "init"})
            except Exception:
                logger.exception("Unable to persist initial allowlist file")
        elif document.fingerprint.sha256 != fingerprint.sha256:
            logger.warning(
                "DB overlay fingerprint mismatch detected (stored=%s, current=%s)",
                document.fingerprint.sha256,
                fingerprint.sha256,
            )
            self._pending_fingerprint = fingerprint
            self._document = document
            self._store = store
            self._state = "awaiting_fingerprint"
            self._diff = None
            self._bundles.clear()
            self._refresh_catalog()
            return
        self._fingerprint = fingerprint
        self._store = store
        self._document = document
        try:
            cursor = cursor_factory()
        except Exception:
            logger.exception("Unable to create cursor for overlay scan")
            self._disable()
            return
        scanner = self.scanner_cls(cursor)
        try:
            bundles = list(scanner.scan())
        except OverlayScannerError:
            logger.exception("Overlay scanning failed; falling back to XML")
            self._disable()
            return
        except Exception:
            logger.exception("Unexpected overlay scan failure")
            self._disable()
            return
        self._bundles = {bundle.identity: bundle for bundle in bundles}
        self._session_bundles = {}
        self._diff = diff_bundles(bundles, document)
        self._state = "ready"
        self._refresh_catalog()

    def refresh(self) -> None:
        if not self.config.enabled:
            return
        if self._db_path is None or self._cursor_factory is None:
            return
        if self._pending_fingerprint is not None:
            return
        self.bind_to_database(db_path=self._db_path, cursor_factory=self._cursor_factory)

    def accept_fingerprint(self) -> None:
        if self._store is None or self._document is None or self._pending_fingerprint is None:
            return
        self._document.fingerprint = self._pending_fingerprint
        try:
            self._store.write(
                self._document,
                action="fingerprint_update",
                details={"sha256": self._pending_fingerprint.sha256},
            )
        except Exception:
            logger.exception("Failed to persist fingerprint update")
        self._pending_fingerprint = None
        self.refresh()

    def approve_bundle(self, identity: tuple[int, int], *, persist: bool, user: str | None = None) -> None:
        bundle = self._bundles.get(identity)
        if bundle is None:
            raise KeyError(f"Bundle {identity} not discovered in current scan")
        if persist:
            if not self._document or not self._store:
                raise RuntimeError("Allowlist not initialised")
            entry = AllowlistEntry.from_bundle(bundle, active=True)
            self._document.merge_entry(entry)
            try:
                self._store.write(
                    self._document,
                    action="approve",
                    user=user,
                    details={"id_function": bundle.id_function, "id_macro_kind": bundle.id_macro_kind},
                )
            except Exception:
                logger.exception("Failed persisting allowlist approval")
            if self._diff:
                self._diff.added.pop(identity, None)
                self._diff.changed.pop(identity, None)
        else:
            if not self.config.allow_session_approvals:
                raise RuntimeError("Session approvals disabled by configuration")
            self._session_bundles[identity] = bundle
        self._refresh_catalog()

    def deactivate_bundle(self, identity: tuple[int, int], *, persist: bool, user: str | None = None) -> None:
        if persist:
            if not self._document or not self._store:
                return
            self._document.deactivate(identity)
            try:
                self._store.write(
                    self._document,
                    action="deactivate",
                    user=user,
                    details={"identity": identity},
                )
            except Exception:
                logger.exception("Failed persisting allowlist deactivation")
        else:
            self._session_bundles.pop(identity, None)
        self._refresh_catalog()

    def runtime_schema(self) -> Mapping[str, Mapping[str, object]]:
        if self._active_catalog:
            return self._active_catalog.schema
        return {}

    def macro_map(self) -> Dict[int, MacroDef]:
        catalog = self._active_catalog
        if not catalog:
            return {}
        by_function: dict[int, FunctionBundle] = {}
        for bundle in catalog.bundles.values():
            by_function.setdefault(bundle.id_function, bundle)
        macro_map: dict[int, MacroDef] = {}
        for fid, bundle in by_function.items():
            params = [
                MacroParam(
                    name=spec.name,
                    type=spec.type,
                    default=spec.default,
                    min=spec.min_value,
                    max=spec.max_value,
                )
                for spec in bundle.params
            ]
            macro_map[fid] = MacroDef(
                id_function=bundle.id_function,
                name=bundle.function_name,
                params=params,
            )
        return macro_map

    def state(self) -> OverlayState:
        return OverlayState(
            ready=self._state == "ready",
            fingerprint_pending=self._state == "awaiting_fingerprint",
            diff=self._diff,
        )

    def export_schema(self) -> Mapping[str, Mapping[str, object]]:
        return dict(self.runtime_schema())

    def prepare_export_target(self, *, target_path: Path, connection, macro_ids: Iterable[int]) -> None:
        if not self.config.enabled or not self._active_catalog:
            return
        needed_ids = {int(mid) for mid in macro_ids if mid is not None}
        if not needed_ids:
            return
        bundles = [
            bundle
            for bundle in self._active_catalog.bundles.values()
            if bundle.id_function in needed_ids
        ]
        if not bundles:
            return
        try:
            self._replicate_bundles(connection, bundles)
        except Exception:
            logger.exception("Failed to replicate DB overlay bundles into export target")
            return
        try:
            self._update_destination_allowlist(target_path, bundles)
        except Exception:
            logger.exception("Failed to update destination allowlist for export target")

    # ---------------------------- internals -----------------------------
    def _disable(self) -> None:
        self._state = "disabled"
        self._store = None
        self._document = None
        self._bundles.clear()
        self._session_bundles.clear()
        self._diff = None
        self._pending_fingerprint = None
        self._fingerprint = None
        self._active_catalog = None
        set_dynamic_param_specs(None)

    def _refresh_catalog(self) -> None:
        if not self._document or not self._bundles:
            self._active_catalog = None
            set_dynamic_param_specs(None)
            return
        active: dict[tuple[int, int], FunctionBundle] = {}
        for ident, entry in self._document.entry_map().items():
            if not entry.active:
                continue
            bundle = self._bundles.get(ident)
            if bundle is None:
                continue
            if entry.signature_hash != bundle.signature_hash:
                continue
            active[ident] = bundle
        if self.config.allow_session_approvals:
            active.update(self._session_bundles)
        schema = build_schema_from_bundles(active.values())
        self._active_catalog = RuntimeCatalog(schema=schema, bundles=active)
        set_dynamic_param_specs(schema if schema else None)

    def _replicate_bundles(self, connection, bundles: list[FunctionBundle]) -> None:
        try:
            import pyodbc  # type: ignore  # noqa: F401
        except Exception:  # pragma: no cover - optional dependency
            logger.warning("pyodbc unavailable; skipping bundle replication")
            return

        cursor = connection.cursor()
        column_cache: dict[str, set[str]] = {}

        def columns(table: str) -> set[str]:
            if table not in column_cache:
                try:
                    column_cache[table] = {
                        c.column_name for c in cursor.columns(table=table)
                    }
                except Exception:
                    column_cache[table] = set()
            return column_cache[table]

        for bundle in bundles:
            self._ensure_row(
                cursor,
                table="tabFunction",
                pk="IDFunction",
                pk_value=bundle.id_function,
                payload={"Name": bundle.function_name},
                available=columns("tabFunction"),
            )
            self._ensure_row(
                cursor,
                table="tabMacroKind",
                pk="IDMacroKind",
                pk_value=bundle.id_macro_kind,
                payload={"Name": bundle.macro_kind_name},
                available=columns("tabMacroKind"),
            )
            self._ensure_mapping(cursor, bundle, available=columns("detFunctionMacroKind"))
            for spec in bundle.params:
                if spec.parameter_class_id is not None:
                    self._ensure_row(
                        cursor,
                        table="tabParameterClass",
                        pk="IDParameterClass",
                        pk_value=spec.parameter_class_id,
                        payload={
                            "Name": spec.parameter_class_name or f"Class_{spec.parameter_class_id}",
                            "TypeName": spec.type,
                        },
                        available=columns("tabParameterClass"),
                    )
                if spec.unit_id is not None:
                    self._ensure_row(
                        cursor,
                        table="tabUnit",
                        pk="IDUnit",
                        pk_value=spec.unit_id,
                        payload={"Name": spec.unit_name or f"Unit_{spec.unit_id}"},
                        available=columns("tabUnit"),
                    )
                self._ensure_param_row(cursor, bundle, spec, available=columns("detMacroKindParameterClass"))

        try:
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _ensure_row(self, cursor, *, table: str, pk: str, pk_value: int, payload: Mapping[str, object], available: set[str]) -> None:
        if pk not in available:
            return
        cursor.execute(f"SELECT COUNT(1) FROM {table} WHERE [{pk}]=?", pk_value)
        row = cursor.fetchone()
        if row and int(row[0] or 0) > 0:
            return
        columns = [pk] + [col for col in payload.keys() if col in available and col != pk]
        if not columns:
            return
        values = [pk_value] + [payload[col] for col in columns[1:]]
        placeholders = ",".join("?" for _ in columns)
        col_expr = ",".join(f"[{col}]" for col in columns)
        cursor.execute(f"INSERT INTO {table} ({col_expr}) VALUES ({placeholders})", values)

    def _ensure_mapping(self, cursor, bundle: FunctionBundle, *, available: set[str]) -> None:
        if not {"IDFunction", "IDMacroKind"}.issubset(available):
            return
        cursor.execute(
            "SELECT COUNT(1) FROM detFunctionMacroKind WHERE IDFunction=? AND IDMacroKind=?",
            bundle.id_function,
            bundle.id_macro_kind,
        )
        row = cursor.fetchone()
        if row and int(row[0] or 0) > 0:
            return
        cursor.execute(
            "INSERT INTO detFunctionMacroKind (IDFunction, IDMacroKind) VALUES (?, ?)",
            bundle.id_function,
            bundle.id_macro_kind,
        )

    def _ensure_param_row(self, cursor, bundle: FunctionBundle, spec, *, available: set[str]) -> None:
        required = {"IDMacroKind", "Position", "Name"}
        if not required.issubset(available):
            return
        cursor.execute(
            "SELECT COUNT(1) FROM detMacroKindParameterClass WHERE IDMacroKind=? AND Position=?",
            bundle.id_macro_kind,
            spec.position,
        )
        row = cursor.fetchone()
        if row and int(row[0] or 0) > 0:
            return
        columns = ["IDMacroKind", "Position", "Name"]
        values = [bundle.id_macro_kind, spec.position, spec.name]
        optional_fields = {
            "InOut": spec.inout,
            "Optional": 1 if spec.optional else 0,
            "DefaultValue": spec.default,
            "MinValue": spec.min_value,
            "MaxValue": spec.max_value,
            "IDUnit": spec.unit_id,
            "IDParameterClass": spec.parameter_class_id,
        }
        for key, value in optional_fields.items():
            if key in available and value is not None:
                columns.append(key)
                values.append(value)
        placeholders = ",".join("?" for _ in columns)
        col_expr = ",".join(f"[{col}]" for col in columns)
        cursor.execute(
            f"INSERT INTO detMacroKindParameterClass ({col_expr}) VALUES ({placeholders})",
            values,
        )

    def _update_destination_allowlist(self, target_path: Path, bundles: list[FunctionBundle]) -> None:
        dest_fp = DbFingerprint.compute(Path(target_path))
        store = AllowlistStore(target_path.parent, file_name=self.config.yaml_name)
        document = store.load()
        document.fingerprint = dest_fp
        for bundle in bundles:
            entry = AllowlistEntry.from_bundle(bundle, active=True)
            document.merge_entry(entry)
        store.write(
            document,
            action="import",
            details={"bundle_count": len(bundles)},
        )


_GLOBAL_RUNTIME: DbOverlayRuntime | None = None


def configure_runtime(config: DbOverlayConfig | None) -> DbOverlayRuntime:
    global _GLOBAL_RUNTIME
    if _GLOBAL_RUNTIME is None:
        _GLOBAL_RUNTIME = DbOverlayRuntime(config)
    else:
        _GLOBAL_RUNTIME.configure(config)
    return _GLOBAL_RUNTIME


def get_runtime() -> DbOverlayRuntime | None:
    return _GLOBAL_RUNTIME


def reset_runtime() -> None:
    global _GLOBAL_RUNTIME
    _GLOBAL_RUNTIME = None
