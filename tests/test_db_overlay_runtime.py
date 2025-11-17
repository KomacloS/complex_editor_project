from __future__ import annotations

import tempfile
from pathlib import Path

from complex_editor.config.loader import DbOverlayConfig
from complex_editor.db_overlay.models import FunctionBundle, ParameterSpec
from complex_editor.db_overlay.runtime import DbOverlayRuntime


class _FakeScanner:
    def __init__(self, bundles):
        self._bundles = bundles

    def scan(self):
        return list(self._bundles)


def _sample_bundle() -> FunctionBundle:
    params = (
        ParameterSpec(
            position=1,
            name="Value",
            type="FLOAT",
            inout="input",
            optional=False,
            default="0",
            min_value="-1",
            max_value="1",
            unit_id=None,
            unit_name=None,
            enum_domain=(),
            parameter_class_id=1,
            parameter_class_name="FLOAT",
        ),
    )
    return FunctionBundle(
        id_function=42,
        id_macro_kind=99,
        function_name="DB_MACRO",
        macro_kind_name="DB_MACRO",
        params=params,
    )


def _touch_db_file(path: Path) -> None:
    path.write_bytes(b"overlay")


def test_runtime_registers_dynamic_schema(tmp_path: Path):
    db_path = tmp_path / "main_db.mdb"
    _touch_db_file(db_path)
    bundle = _sample_bundle()
    runtime = DbOverlayRuntime(
        DbOverlayConfig(enabled=True),
        scanner_cls=lambda _cursor: _FakeScanner([bundle]),
    )
    runtime.bind_to_database(db_path=db_path, cursor_factory=lambda: object())
    runtime.approve_bundle((bundle.id_function, bundle.id_macro_kind), persist=True)
    schema = runtime.runtime_schema()
    assert any(key.startswith(bundle.function_name) for key in schema)


def test_prepare_export_target_updates_allowlist(tmp_path: Path):
    db_path = tmp_path / "main_db.mdb"
    _touch_db_file(db_path)
    bundle = _sample_bundle()
    runtime = DbOverlayRuntime(
        DbOverlayConfig(enabled=True),
        scanner_cls=lambda _cursor: _FakeScanner([bundle]),
    )
    runtime.bind_to_database(db_path=db_path, cursor_factory=lambda: object())
    runtime.approve_bundle((bundle.id_function, bundle.id_macro_kind), persist=True)

    target_path = tmp_path / "export.mdb"
    _touch_db_file(target_path)

    recorded: dict[str, object] = {}
    runtime._replicate_bundles = lambda conn, bundles: recorded.setdefault("bundles", bundles)  # type: ignore[assignment]
    runtime._update_destination_allowlist = (
        lambda path, bundles: recorded.setdefault("allowlist", (path, bundles))
    )

    runtime.prepare_export_target(
        target_path=target_path,
        connection=object(),
        macro_ids={bundle.id_function},
    )

    assert "bundles" in recorded
    assert recorded["allowlist"][0] == target_path
    copied_bundles = recorded["allowlist"][1]
    assert copied_bundles[0].id_function == bundle.id_function


def test_approving_bundle_clears_diff(tmp_path: Path):
    db_path = tmp_path / "main_db.mdb"
    _touch_db_file(db_path)
    bundle = _sample_bundle()
    runtime = DbOverlayRuntime(
        DbOverlayConfig(enabled=True),
        scanner_cls=lambda _cursor: _FakeScanner([bundle]),
    )
    runtime.bind_to_database(db_path=db_path, cursor_factory=lambda: object())
    state = runtime.state()
    assert state.diff and state.diff.added

    runtime.approve_bundle((bundle.id_function, bundle.id_macro_kind), persist=True)

    refreshed = runtime.state()
    assert refreshed.diff
    assert refreshed.diff.added == {}


def test_discover_macro_map_uses_runtime(monkeypatch):
    from complex_editor.db import schema_introspect

    class DummyRuntime:
        def state(self):
            class S:
                ready = True
                fingerprint_pending = False
                diff = None

            return S()

        def macro_map(self):
            from complex_editor.domain import MacroDef, MacroParam

            return {
                5: MacroDef(5, "DB_MACRO", [MacroParam("X", "INT", None, None, None)])
            }

    monkeypatch.setattr(schema_introspect, "get_runtime", lambda: DummyRuntime())
    result = schema_introspect.discover_macro_map(None)
    assert 5 in result
    assert result[5].name == "DB_MACRO"
