from __future__ import annotations

import logging
from pathlib import Path
from typing import List
from types import SimpleNamespace

import sys

import pytest  # type: ignore
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ce_bridge_service.app import (  # noqa: E402
    TemplateResolutionError,
    _resolve_template_path,
    create_app,
)
from ce_bridge_service.types import BridgeCreateResult  # noqa: E402
from complex_editor.db.mdb_api import _validate_and_coerce_for_access  # noqa: E402


def _make_headless_client(
    tmp_path: Path,
    *,
    allow_flag: bool = False,
    saver_available: bool = True,
    saver_raises_not_impl: bool = False,
):
    dataset = [(5087, "PN5087", 0)]
    saved: List[tuple[Path, List[int]]] = []

    data_file = tmp_path / "source.mdb"
    data_file.write_text("dummy")

    def factory(path: Path):
        class DummyMDBBase:
            def __init__(self, db_path: Path):
                self.path = Path(db_path)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def list_complexes(self):
                return dataset

            def get_aliases(self, comp_id: int):
                return []

        if saver_available:

            class DummyMDB(DummyMDBBase):
                def save_subset_to_mdb(self, target_path: Path, comp_ids, template_path: Path | None = None):
                    if saver_raises_not_impl:
                        raise NotImplementedError("headless saver disabled")
                    target_path = Path(target_path)
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text("subset")
                    saved.append((target_path, list(comp_ids)))

        else:

            class DummyMDB(DummyMDBBase):
                pass

        return DummyMDB(path)

    app = create_app(
        get_mdb_path=lambda: data_file,
        auth_token=None,
        wizard_handler=None,
        mdb_factory=factory,
        bridge_host="127.0.0.1",
        bridge_port=8765,
        focus_handler=None,
        allow_headless_exports=allow_flag,
    )
    client = TestClient(app)
    return client, saved


def test_template_resolver_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_TEMPLATE_MDB", raising=False)

    payload_tpl = tmp_path / "payload_template.mdb"
    payload_tpl.write_bytes(b"payload")
    assert _resolve_template_path(str(payload_tpl)) == payload_tpl

    env_tpl = tmp_path / "env_template.mdb"
    env_tpl.write_bytes(b"env")
    monkeypatch.setenv("CE_TEMPLATE_MDB", str(env_tpl))
    assert _resolve_template_path(None) == env_tpl

    monkeypatch.delenv("CE_TEMPLATE_MDB", raising=False)
    asset_tpl = _resolve_template_path(None)
    assert asset_tpl.name == "Empty_mdb.mdb"
    assert asset_tpl.exists() and asset_tpl.stat().st_size > 0


def test_template_resolver_failure(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_TEMPLATE_MDB", raising=False)
    bad_tpl = tmp_path / "bad_template.mdb"
    bad_tpl.write_bytes(b"")
    with pytest.raises(TemplateResolutionError) as excinfo:
        _resolve_template_path(str(bad_tpl))
    assert excinfo.value.attempted == str(bad_tpl)


def test_headless_export_rejected_without_override(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    client, saved = _make_headless_client(tmp_path, allow_flag=False)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "bom.mdb"}

    resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 503
    body = resp.json()
    assert body["reason"] == "bridge_headless"
    assert body["status"] == 503
    assert body["allow_headless"] is False
    assert not saved

    health = client.get("/admin/health")
    assert health.status_code == 200
    health_data = health.json()
    assert health_data == {
        "ready": False,
        "headless": True,
        "allow_headless": False,
    }


def test_headless_export_allowed_via_flag(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    client, saved = _make_headless_client(tmp_path, allow_flag=True)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "bom.mdb"}

    resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 200
    assert saved and saved[0][1] == [5087]


def test_headless_export_allowed_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CE_ALLOW_HEADLESS_EXPORTS", "1")
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    client, saved = _make_headless_client(tmp_path, allow_flag=False)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "bom.mdb"}

    resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 200
    assert saved and saved[0][1] == [5087]


def test_headless_export_fallback_not_implemented(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.setenv("CE_DEBUG", "1")
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))

    def fake_export(source_db_path, template_path, target_path, pn_list, comp_ids, options=None, progress_cb=None, cancel_cb=None):
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("pn-exporter")
        return SimpleNamespace(target_path=target, pn_names=tuple(), complex_count=len(comp_ids))

    monkeypatch.setattr("complex_editor.db.pn_exporter.export_pn_to_mdb", fake_export)
    monkeypatch.setattr("complex_editor.db.pn_exporter.ExportOptions", lambda: SimpleNamespace())

    with caplog.at_level(logging.DEBUG):
        client, saved = _make_headless_client(tmp_path, allow_flag=True, saver_available=True, saver_raises_not_impl=True)

        out_dir = tmp_path / "exports"
        payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "fallback.mdb"}

        resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 200
    target_file = out_dir / "fallback.mdb"
    assert target_file.exists()
    assert target_file.read_text() == "pn-exporter"
    assert not saved  # original saver should not have succeeded
    assert any("fallback_to_export_pn_to_mdb" in rec.message for rec in caplog.records)


def test_headless_export_fallback_missing_saver(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.setenv("CE_DEBUG", "1")
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))

    def fake_export(source_db_path, template_path, target_path, pn_list, comp_ids, options=None, progress_cb=None, cancel_cb=None):
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("pn-exporter-missing")
        return SimpleNamespace(target_path=target, pn_names=tuple(), complex_count=len(comp_ids))

    monkeypatch.setattr("complex_editor.db.pn_exporter.export_pn_to_mdb", fake_export)
    monkeypatch.setattr("complex_editor.db.pn_exporter.ExportOptions", lambda: SimpleNamespace())

    with caplog.at_level(logging.DEBUG):
        client, saved = _make_headless_client(tmp_path, allow_flag=True, saver_available=False)

        out_dir = tmp_path / "exports"
        payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "missing.mdb"}

        resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 200
    target_file = out_dir / "missing.mdb"
    assert target_file.exists()
    assert target_file.read_text() == "pn-exporter-missing"
    assert not saved
    assert any("fallback_to_export_pn_to_mdb" in rec.message for rec in caplog.records)


def test_partial_success_with_missing_ids(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    client, saved = _make_headless_client(tmp_path, allow_flag=True)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [5087, 9999], "out_dir": str(out_dir), "mdb_name": "partial.mdb"}

    with caplog.at_level(logging.WARNING):
        resp = client.post("/exports/mdb", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["exported_comp_ids"] == [5087]
    assert body["missing"] == ["9999"]
    assert Path(body["export_path"]).exists()
    assert saved and saved[0][1] == [5087]
    assert any("export partial: missing_comp_ids=[9999]" in rec.message for rec in caplog.records)


def test_all_missing_ids_returns_error(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    client, saved = _make_headless_client(tmp_path, allow_flag=True)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [9999, 8888], "out_dir": str(out_dir), "mdb_name": "missing_only.mdb"}

    resp = client.post("/exports/mdb", json=payload)

    assert resp.status_code == 404
    body = resp.json()
    assert body["reason"] == "comp_ids_not_found"
    assert body["detail"] == "No valid comp_ids to export."
    assert body["missing"] == ["9999", "8888"]
    assert not saved


def test_export_mdb_headless_allowed_xml_in_pins_success(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("CE_ALLOW_HEADLESS_EXPORTS", "1")
    monkeypatch.setenv("CE_DEBUG", "1")
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))

    xml_value = """<?xml version=\"1.0\" encoding=\"utf-16\"?>\n<det>""" + ("p" * 1500) + "</det>"

    def fake_export(source_db_path, template_path, target_path, pn_list, comp_ids, options=None, progress_cb=None, cancel_cb=None):
        table = "detCompDesc"
        fk = (comp_ids or [0])[0]

        class _FakeCol:
            def __init__(self, name: str, type_name: str, size: int | None, digits: int | None, nullable: int = 1):
                self.COLUMN_NAME = name
                self.TYPE_NAME = type_name
                self.COLUMN_SIZE = size
                self.DECIMAL_DIGITS = digits
                self.NULLABLE = nullable

        class _FakeCursor:
            def __init__(self, cols):
                self._cols = list(cols)

            def columns(self, table: str):
                for col in self._cols:
                    yield col

        cols = ["IDCompDesc", "PinS"]
        vals = [fk, xml_value]
        cursor = _FakeCursor([
            _FakeCol("IDCompDesc", "INTEGER", 10, None, 0),
            _FakeCol("PinS", "LONGCHAR", None, None, 1),
        ])

        coerced_cols, coerced_vals, coercions = _validate_and_coerce_for_access(cursor, table, cols, vals)

        def _preview(pcols, pvals):
            items = []
            for c, v in zip(pcols, pvals):
                rep = repr(v)
                if len(rep) > 200:
                    rep = rep[:200] + "..."
                items.append((c, type(v).__name__, rep))
            return items

        insert_logger = logging.getLogger("complex_editor.db.mdb_api.insert")
        insert_logger.debug(
            "INSERT prepare table=%s fk=%s cols=%s vals=%s",
            table,
            fk,
            ",".join(coerced_cols),
            _preview(coerced_cols, coerced_vals),
        )
        insert_logger.debug("coercions=%s", coercions)
        insert_logger.debug("INSERT committed table=%s fk=%s new_id=%s", table, fk, fk + 1000)

        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"mdb")
        return SimpleNamespace(target_path=target, pn_names=tuple(), complex_count=len(comp_ids or pn_list or []))

    monkeypatch.setattr("complex_editor.db.pn_exporter.export_pn_to_mdb", fake_export)
    monkeypatch.setattr("complex_editor.db.pn_exporter.ExportOptions", lambda: SimpleNamespace())

    insert_logger = logging.getLogger("complex_editor.db.mdb_api.insert")
    previous_level = insert_logger.level
    insert_logger.setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG):
            client, saved = _make_headless_client(tmp_path, allow_flag=True, saver_available=False)

            out_dir = tmp_path / "exports"
            payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "xmlpins.mdb"}

            resp = client.post("/exports/mdb", json=payload)
    finally:
        insert_logger.setLevel(previous_level)

    assert resp.status_code == 200
    target_file = out_dir / "xmlpins.mdb"
    assert target_file.exists()
    assert target_file.read_bytes() == b"mdb"
    assert not saved

    messages = [rec.message for rec in caplog.records]
    assert any("Resolved template_path=" in msg for msg in messages)
    assert any("INSERT prepare table=detCompDesc" in msg for msg in messages)
    assert any("coercions=[" in msg for msg in messages)
    assert any("INSERT committed table=detCompDesc" in msg for msg in messages)
    assert any("fallback_to_export_pn_to_mdb" in msg for msg in messages)


def test_headless_export_invalid_template_returns_409(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    client, saved = _make_headless_client(tmp_path, allow_flag=True)

    out_dir = tmp_path / "exports"
    bad_template = tmp_path / "bad.mdb"
    bad_template.write_bytes(b"")
    payload = {
        "comp_ids": [5087],
        "out_dir": str(out_dir),
        "mdb_name": "invalid.mdb",
        "template_path": str(bad_template),
    }

    resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 409
    body = resp.json()
    assert body["reason"] == "template_missing_or_incompatible"
    assert body["template_path"] == str(bad_template)
    assert not saved


def test_non_headless_export_unaffected(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))

    dataset = [(5087, "PN5087", 0)]
    saved: List[tuple[Path, List[int]]] = []
    data_file = tmp_path / "source.mdb"
    data_file.write_text("dummy")

    def factory(path: Path):
        class DummyMDB:
            def __init__(self, db_path: Path):
                self.path = Path(db_path)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def list_complexes(self):
                return dataset

            def get_aliases(self, comp_id: int):
                return []

            def save_subset_to_mdb(self, target_path: Path, comp_ids, template_path: Path | None = None):
                target_path = Path(target_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text("subset")
                saved.append((target_path, list(comp_ids)))

        return DummyMDB(path)

    app = create_app(
        get_mdb_path=lambda: data_file,
        auth_token=None,
        wizard_handler=lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        mdb_factory=factory,
        bridge_host="127.0.0.1",
        bridge_port=8765,
        focus_handler=lambda comp_id, mode: {"comp_id": comp_id, "mode": mode},
    )
    client = TestClient(app)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "bom.mdb"}
    resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 200
    assert saved and saved[0][1] == [5087]
