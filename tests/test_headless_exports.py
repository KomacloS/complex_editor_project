from __future__ import annotations

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
    client, saved = _make_headless_client(tmp_path, allow_flag=True)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "bom.mdb"}

    resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 200
    assert saved and saved[0][1] == [5087]


def test_headless_export_allowed_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CE_ALLOW_HEADLESS_EXPORTS", "1")
    client, saved = _make_headless_client(tmp_path, allow_flag=False)

    out_dir = tmp_path / "exports"
    payload = {"comp_ids": [5087], "out_dir": str(out_dir), "mdb_name": "bom.mdb"}

    resp = client.post("/exports/mdb", json=payload)
    assert resp.status_code == 200
    assert saved and saved[0][1] == [5087]


def test_headless_export_fallback_not_implemented(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)

    def fake_export(source_db_path, template_path, target_path, pn_list, comp_ids, options=None, progress_cb=None, cancel_cb=None):
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("pn-exporter")
        return SimpleNamespace(target_path=target, pn_names=tuple(), complex_count=len(comp_ids))

    monkeypatch.setattr("complex_editor.db.pn_exporter.export_pn_to_mdb", fake_export)
    monkeypatch.setattr("complex_editor.db.pn_exporter.ExportOptions", lambda: SimpleNamespace())

    with caplog.at_level("INFO"):
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

    def fake_export(source_db_path, template_path, target_path, pn_list, comp_ids, options=None, progress_cb=None, cancel_cb=None):
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("pn-exporter-missing")
        return SimpleNamespace(target_path=target, pn_names=tuple(), complex_count=len(comp_ids))

    monkeypatch.setattr("complex_editor.db.pn_exporter.export_pn_to_mdb", fake_export)
    monkeypatch.setattr("complex_editor.db.pn_exporter.ExportOptions", lambda: SimpleNamespace())

    with caplog.at_level("INFO"):
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


def test_headless_export_invalid_template_returns_409(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_ALLOW_HEADLESS_EXPORTS", raising=False)
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
