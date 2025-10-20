from __future__ import annotations

import logging
from importlib import reload

import pytest

from ce_bridge_service import app as app_module


@pytest.fixture(autouse=True)
def reset_logging():
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)


def test_configure_logging_debug_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CE_DEBUG", "1")
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    reload(app_module)
    app_module.configure_logging()
    logger = logging.getLogger("ce_bridge_service")
    assert logger.isEnabledFor(logging.DEBUG)


def test_configure_logging_warning_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CE_DEBUG", raising=False)
    monkeypatch.setenv("CE_LOG_FILE", str(tmp_path / "bridge.log"))
    reload(app_module)
    app_module.configure_logging()
    logger = logging.getLogger("ce_bridge_service")
    assert logger.getEffectiveLevel() >= logging.WARNING
