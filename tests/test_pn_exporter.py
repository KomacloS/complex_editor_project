from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

try:  # pragma: no cover - exercised only when pyodbc is unavailable
    import pyodbc  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for CI environments
    pyodbc = types.ModuleType("pyodbc")

    class _Error(Exception):
        ...

    class _DataError(_Error):
        ...

    class _IntegrityError(_Error):
        ...

    pyodbc.Error = _Error
    pyodbc.DataError = _DataError
    pyodbc.IntegrityError = _IntegrityError
    pyodbc.pooling = False
    sys.modules["pyodbc"] = pyodbc

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from complex_editor.db import pn_exporter  # noqa: E402
from complex_editor.db.mdb_api import ComplexDevice, ALIAS_T  # noqa: E402


class _FakeDB:
    def __init__(self):
        self.calls: list[int] = []

    def get_complex(self, cid: int) -> ComplexDevice:
        self.calls.append(cid)
        return ComplexDevice(
            id_comp_desc=cid,
            name=f"PN{cid}",
            total_pins=0,
            subcomponents=[],
            aliases=[f"ALIAS{cid}"],
        )


def test_collect_complex_devices_dedupes_comp_ids():
    db = _FakeDB()
    devices, macro_ids, macro_usage, alias_total, export_ids, sub_total, pn_out = pn_exporter._collect_complex_devices(  # type: ignore[attr-defined]
        db,
        pn_names=[],
        comp_ids=[5, "5", 7, 0, -1, "abc", 7],
        progress_cb=None,
        cancel_cb=None,
    )

    assert export_ids == [5, 7]
    assert [dev.name for dev in devices] == ["PN5", "PN7"]
    assert alias_total == 2
    assert sub_total == 0
    assert pn_out == ["PN5", "PN7"]
    assert macro_ids == set()
    assert macro_usage == {}


class _StubCursor:
    def __init__(self, existing_names: set[str] | None = None, alias_hits: set[str] | None = None):
        self.existing_names = set(existing_names or [])
        self.alias_hits = set(alias_hits or [])
        self.statements: list[tuple[str, tuple]] = []
        self._rows: list[tuple] = []

    def execute(self, sql: str, *params):
        self.statements.append((sql, params))
        normalized = sql.lower()
        if "count(1)" in normalized and "[name]" in normalized:
            value = 1 if params and params[0] in self.existing_names else 0
            self._rows = [(value,)]
        elif "select distinct" in normalized and ALIAS_T.lower() in normalized:
            hits = [alias for alias in params if alias in self.alias_hits]
            self._rows = [(alias,) for alias in hits]
        else:
            self._rows = []
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else (0,)

    def fetchall(self):
        return list(self._rows)


class _StubConn:
    def __init__(self, existing_names: set[str] | None = None, alias_hits: set[str] | None = None):
        self.cursor_obj = _StubCursor(existing_names, alias_hits)
        self.commit_calls = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_calls += 1


class _BaseStubMDB:
    def __init__(self, path: Path, *, existing_names: set[str] | None = None, alias_hits: set[str] | None = None):
        self.path = Path(path)
        self._conn = _StubConn(existing_names, alias_hits)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _alias_schema(self, cur):
        return ("IDCompDesc", "AliasName", None)


class _DuplicateMDB(_BaseStubMDB):
    def __init__(self, path: Path):
        super().__init__(path)

    def create_complex(self, device: ComplexDevice) -> None:
        raise pyodbc.IntegrityError(
            "23000",
            "[Microsoft][ODBC Microsoft Access Driver] Duplicate value violates table 'tabCompAlias' "
            "in index 'idxAliasName'. (-1605)",
        )


def test_export_duplicate_error_surfaces_conflict_details(monkeypatch, tmp_path):
    template = tmp_path / "template.mdb"
    template.write_bytes(b"\x00\x01")
    target = tmp_path / "out" / "subset.mdb"

    device = ComplexDevice(
        id_comp_desc=None,
        name="PN5",
        total_pins=0,
        subcomponents=[],
        aliases=["PN5ALT"],
    )

    monkeypatch.setattr(pn_exporter, "MDB", _DuplicateMDB)

    with pytest.raises(pn_exporter.SubsetExportError) as ei:
        pn_exporter._export_using_template(
            template_path=template,
            target_path=target,
            devices=[device],
            pn_names=("PN5",),
            macro_ids=set(),
            macro_usage={},
            alias_total=1,
            subcomponent_total=0,
            export_ids=[5],
            progress_cb=None,
            cancel_cb=None,
        )

    err = ei.value
    assert err.reason == "data_invalid"
    payload = err.payload
    assert payload["offending_comp_ids"] == [5]
    assert payload["conflict_table"] == "tabCompAlias"
    assert payload["index_name"] == "idxAliasName"


class _DiagnosticMDB(_BaseStubMDB):
    def __init__(self, path: Path):
        super().__init__(path, existing_names={"PN5"}, alias_hits={"PN5ALT"})

    def create_complex(self, device: ComplexDevice) -> None:
        raise pyodbc.IntegrityError(
            "23000",
            "[Microsoft][ODBC Microsoft Access Driver] Duplicate value violates unspecified index. (-1605)",
        )


def test_duplicate_error_adds_hints_when_table_unknown(monkeypatch, tmp_path):
    template = tmp_path / "template2.mdb"
    template.write_bytes(b"\x00\x01")
    target = tmp_path / "out" / "subset2.mdb"

    device = ComplexDevice(
        id_comp_desc=None,
        name="PN5",
        total_pins=0,
        subcomponents=[],
        aliases=["PN5ALT"],
    )

    monkeypatch.setattr(pn_exporter, "MDB", _DiagnosticMDB)

    with pytest.raises(pn_exporter.SubsetExportError) as ei:
        pn_exporter._export_using_template(
            template_path=template,
            target_path=target,
            devices=[device],
            pn_names=("PN5",),
            macro_ids=set(),
            macro_usage={},
            alias_total=1,
            subcomponent_total=0,
            export_ids=[5],
            progress_cb=None,
            cancel_cb=None,
        )

    payload = ei.value.payload
    assert payload["duplicate_name"] == "PN5"
    assert payload["existing_name_count"] == 1
    assert payload["duplicate_aliases"] == ["PN5ALT"]
    assert "diagnostics" in payload


class _CleanMDB(_BaseStubMDB):
    instances: list["_CleanMDB"] = []

    def __init__(self, path: Path):
        super().__init__(path, existing_names={"LEGACY"})
        self.created: list[str] = []
        _CleanMDB.instances.append(self)

    def create_complex(self, device: ComplexDevice) -> None:
        self.created.append(device.name)


def test_export_purges_template_before_writing(monkeypatch, tmp_path):
    template = tmp_path / "template3.mdb"
    template.write_bytes(b"\x00\x01")
    target = tmp_path / "out" / "subset3.mdb"

    device = ComplexDevice(
        id_comp_desc=None,
        name="PN_CLEAN",
        total_pins=0,
        subcomponents=[],
        aliases=[],
    )

    _CleanMDB.instances.clear()
    monkeypatch.setattr(pn_exporter, "MDB", _CleanMDB)

    report = pn_exporter._export_using_template(
        template_path=template,
        target_path=target,
        devices=[device],
        pn_names=("PN_CLEAN",),
        macro_ids=set(),
        macro_usage={},
        alias_total=0,
        subcomponent_total=0,
        export_ids=[1],
        progress_cb=None,
        cancel_cb=None,
    )

    assert report.complex_count == 1
    stub = _CleanMDB.instances[-1]
    statements = [sql for sql, _ in stub._conn.cursor_obj.statements]
    # Ensure purge touched all three tables before the insert.
    assert any("DELETE FROM tabCompAlias" in sql for sql in statements)
    assert any("DELETE FROM detCompDesc" in sql for sql in statements)
    assert any("DELETE FROM tabCompDesc" in sql for sql in statements)


class _MacroCheckMDB(_BaseStubMDB):
    def __init__(self, path: Path):
        super().__init__(path)

    def create_complex(self, device: ComplexDevice) -> None:  # pragma: no cover - not reached
        raise AssertionError("Should not insert when macros missing")


def test_missing_macro_payload_lists_pns(monkeypatch, tmp_path):
    template = tmp_path / "template4.mdb"
    template.write_bytes(b"\x00\x01")
    target = tmp_path / "out" / "subset4.mdb"

    device = ComplexDevice(
        id_comp_desc=None,
        name="PNX",
        total_pins=0,
        subcomponents=[],
        aliases=[],
    )

    monkeypatch.setattr(pn_exporter, "MDB", _MacroCheckMDB)
    monkeypatch.setattr(pn_exporter, "_validate_macros_available", lambda conn, ids: {154, 155})

    macro_usage = {154: {"PNX"}, 155: {"PNY", "PNZ"}}

    with pytest.raises(pn_exporter.SubsetExportError) as ei:
        pn_exporter._export_using_template(
            template_path=template,
            target_path=target,
            devices=[device],
            pn_names=("PNX",),
            macro_ids={154, 155},
            macro_usage=macro_usage,
            alias_total=0,
            subcomponent_total=0,
            export_ids=[1],
            progress_cb=None,
            cancel_cb=None,
        )

    payload = ei.value.payload
    assert payload["missing_macro_ids"] == [154, 155]
    assert payload["missing_macro_usage"] == {154: ["PNX"], 155: ["PNY", "PNZ"]}
