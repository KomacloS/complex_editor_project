from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtGui import QDesktopServices

from complex_editor.config.loader import BridgeConfig
from complex_editor.core.app_context import AppContext
from complex_editor.db.mdb_api import MDB


BridgeStatusCb = Optional[Callable[[], bool]]
BridgeStartCb = Optional[Callable[[BridgeConfig], bool]]
BridgeStopCb = Optional[Callable[[], None]]
BridgeSnippetCb = Optional[Callable[[BridgeConfig], str]]


class IntegrationSettingsDialog(QtWidgets.QDialog):
    """Settings dialog for database integration and optional HTTP bridge."""

    def __init__(
        self,
        ctx: AppContext,
        *,
        is_bridge_running: BridgeStatusCb = None,
        start_bridge: BridgeStartCb = None,
        stop_bridge: BridgeStopCb = None,
        client_snippet: BridgeSnippetCb = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Integration Settings")
        self.ctx = ctx
        self._is_bridge_running = is_bridge_running
        self._start_bridge = start_bridge
        self._stop_bridge = stop_bridge
        self._client_snippet = client_snippet
        self._mdb_path = ctx.current_db_path()

        self._build_ui()
        self._apply_config_to_ui()
        self._refresh_bridge_panel()
        self._update_bom_open_state()

    # ------------------------------------------------------------------ UI setup
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self.db_group = QtWidgets.QGroupBox("Database")
        db_layout = QtWidgets.QVBoxLayout()
        path_row = QtWidgets.QHBoxLayout()
        self.mdb_path_edit = QtWidgets.QLineEdit()
        self.mdb_path_edit.setReadOnly(True)
        path_row.addWidget(self.mdb_path_edit)
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(self.browse_btn)
        db_layout.addLayout(path_row)

        btn_row = QtWidgets.QHBoxLayout()
        self.create_btn = QtWidgets.QPushButton("Create/Copy...")
        self.create_btn.clicked.connect(self._on_create_copy)
        btn_row.addWidget(self.create_btn)
        self.test_btn = QtWidgets.QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._on_test_connection)
        btn_row.addWidget(self.test_btn)
        btn_row.addStretch()
        db_layout.addLayout(btn_row)
        self.db_group.setLayout(db_layout)
        layout.addWidget(self.db_group)

        self.bom_group = QtWidgets.QGroupBox("BOM_DB Link")
        bom_layout = QtWidgets.QHBoxLayout()
        self.bom_link_edit = QtWidgets.QLineEdit()
        self.bom_link_edit.textChanged.connect(lambda _: self._update_bom_open_state())
        bom_layout.addWidget(self.bom_link_edit)
        self.open_bom_btn = QtWidgets.QPushButton("Open in browser")
        self.open_bom_btn.clicked.connect(self._on_open_bom_link)
        bom_layout.addWidget(self.open_bom_btn)
        self.bom_group.setLayout(bom_layout)
        layout.addWidget(self.bom_group)

        self.bridge_group = QtWidgets.QGroupBox("HTTP Bridge")
        bridge_layout = QtWidgets.QGridLayout()
        self.bridge_enabled_box = QtWidgets.QCheckBox("Enable HTTP Bridge")
        self.bridge_enabled_box.toggled.connect(self._refresh_bridge_panel)
        bridge_layout.addWidget(self.bridge_enabled_box, 0, 0, 1, 2)

        bridge_layout.addWidget(QtWidgets.QLabel("Host"), 1, 0)
        self.bridge_host_edit = QtWidgets.QLineEdit()
        self.bridge_host_edit.textChanged.connect(self._on_bridge_host_changed)
        bridge_layout.addWidget(self.bridge_host_edit, 1, 1)

        bridge_layout.addWidget(QtWidgets.QLabel("Port"), 2, 0)
        self.bridge_port_spin = QtWidgets.QSpinBox()
        self.bridge_port_spin.setRange(1, 65535)
        self.bridge_port_spin.valueChanged.connect(self._on_bridge_port_changed)
        bridge_layout.addWidget(self.bridge_port_spin, 2, 1)

        bridge_layout.addWidget(QtWidgets.QLabel("Base URL"), 3, 0)
        self.bridge_base_url_edit = QtWidgets.QLineEdit()
        self.bridge_base_url_edit.setReadOnly(True)
        bridge_layout.addWidget(self.bridge_base_url_edit, 3, 1)

        bridge_layout.addWidget(QtWidgets.QLabel("Auth token"), 4, 0)
        self.bridge_token_edit = QtWidgets.QLineEdit()
        self.bridge_token_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Normal)
        bridge_layout.addWidget(self.bridge_token_edit, 4, 1)

        bridge_layout.addWidget(QtWidgets.QLabel("Request timeout (s)"), 5, 0)
        self.bridge_timeout_spin = QtWidgets.QSpinBox()
        self.bridge_timeout_spin.setRange(1, 600)
        bridge_layout.addWidget(self.bridge_timeout_spin, 5, 1)

        btn_bridge_row = QtWidgets.QHBoxLayout()
        self.bridge_start_btn = QtWidgets.QPushButton("Start")
        self.bridge_start_btn.clicked.connect(self._on_bridge_start)
        btn_bridge_row.addWidget(self.bridge_start_btn)
        self.bridge_stop_btn = QtWidgets.QPushButton("Stop")
        self.bridge_stop_btn.clicked.connect(self._on_bridge_stop)
        btn_bridge_row.addWidget(self.bridge_stop_btn)
        self.bridge_snippet_btn = QtWidgets.QPushButton("Copy Client Snippet")
        self.bridge_snippet_btn.clicked.connect(self._on_copy_snippet)
        btn_bridge_row.addWidget(self.bridge_snippet_btn)
        btn_bridge_row.addStretch()
        bridge_layout.addLayout(btn_bridge_row, 6, 0, 1, 2)

        self.bridge_group.setLayout(bridge_layout)
        layout.addWidget(self.bridge_group)

        layout.addStretch()

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _apply_config_to_ui(self) -> None:
        cfg = self.ctx.config
        self.mdb_path_edit.setText(str(cfg.database.mdb_path))
        self.bom_link_edit.setText(cfg.links.bom_db_hint)

        bridge = cfg.bridge
        self.bridge_enabled_box.setChecked(bridge.enabled)
        self.bridge_host_edit.setText(bridge.host)
        self.bridge_port_spin.setValue(int(bridge.port))
        self.bridge_base_url_edit.setText(bridge.base_url)
        self.bridge_token_edit.setText(bridge.auth_token)
        self.bridge_timeout_spin.setValue(int(bridge.request_timeout_seconds))

    # ----------------------------------------------------------------- callbacks
    def _set_mdb_path(self, path: Path) -> None:
        self._mdb_path = path
        self.mdb_path_edit.setText(str(path))

    def _on_browse(self) -> None:
        start_dir = str(self._mdb_path.parent) if self._mdb_path else str(Path.home())
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Access database",
            start_dir,
            "Access database (*.mdb *.accdb);;All files (*)",
        )
        if file_name:
            self._set_mdb_path(Path(file_name))

    def _on_create_copy(self) -> None:
        start_dir = str(self._mdb_path.parent) if self._mdb_path else str(Path.home())
        file_name, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Create Access database",
            start_dir,
            "Access database (*.mdb)",
        )
        if not file_name:
            return
        dest = Path(file_name)
        overwrite = False
        if dest.exists():
            res = QtWidgets.QMessageBox.question(
                self,
                "Overwrite?",
                f"{dest} exists. Replace it with a copy of the template?",
            )
            if res != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            self.ctx.create_database(dest, overwrite=overwrite)
        except Exception as exc:  # pragma: no cover - UI feedback only
            QtWidgets.QMessageBox.critical(
                self,
                "Create failed",
                f"Could not create database:\n{exc}",
            )
            return
        self._set_mdb_path(dest)
        QtWidgets.QMessageBox.information(
            self,
            "Database created",
            f"Template copied to {dest}",
        )

    def _on_test_connection(self) -> None:
        path = Path(self.mdb_path_edit.text())
        if not path.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Missing file",
                f"Database path does not exist:\n{path}",
            )
            return
        try:
            db = MDB(path)
            db.__exit__(None, None, None)
        except Exception as exc:  # pragma: no cover - depends on environment
            QtWidgets.QMessageBox.critical(
                self,
                "Connection failed",
                f"Could not connect to database:\n{exc}",
            )
            return
        QtWidgets.QMessageBox.information(
            self,
            "Connection OK",
            f"Successfully opened {path}",
        )

    def _update_bom_open_state(self) -> None:
        text = self.bom_link_edit.text().strip()
        parsed = urlparse(text)
        self.open_bom_btn.setEnabled(bool(parsed.scheme and parsed.netloc))

    def _on_open_bom_link(self) -> None:
        link = self.bom_link_edit.text().strip()
        if not link:
            return
        QtGui = QtWidgets  # type: ignore[attr-defined]
        try:
            from PyQt6.QtGui import QDesktopServices
        except ImportError:  # pragma: no cover
            QtWidgets.QMessageBox.warning(self, "Unavailable", "Desktop services not available")
            return
        QDesktopServices.openUrl(QtCore.QUrl(link))

    def _on_bridge_host_changed(self, _: str) -> None:
        self._update_bridge_base_url()

    def _on_bridge_port_changed(self, _: int) -> None:
        self._update_bridge_base_url()

    def _update_bridge_base_url(self) -> None:
        host = self.bridge_host_edit.text().strip() or "127.0.0.1"
        port = int(self.bridge_port_spin.value())
        self.bridge_base_url_edit.setText(f"http://{host}:{port}")

    def _refresh_bridge_panel(self) -> None:
        enabled = self.bridge_enabled_box.isChecked()
        for widget in (
            self.bridge_host_edit,
            self.bridge_port_spin,
            self.bridge_token_edit,
            self.bridge_timeout_spin,
        ):
            widget.setEnabled(enabled)
        running = self._is_bridge_running() if self._is_bridge_running else False
        self.bridge_start_btn.setEnabled(enabled and not running and self._start_bridge is not None)
        self.bridge_stop_btn.setEnabled(running and self._stop_bridge is not None)
        self.bridge_snippet_btn.setEnabled(self._client_snippet is not None)
        self._update_bridge_base_url()

    def _on_bridge_start(self) -> None:
        if not self._start_bridge:
            QtWidgets.QMessageBox.information(self, "Unavailable", "Bridge start handler not wired yet.")
            return
        cfg = self._gather_bridge_config()
        ok = self._start_bridge(cfg)
        if ok:
            QtWidgets.QMessageBox.information(self, "Bridge", "Bridge started")
        else:
            QtWidgets.QMessageBox.warning(self, "Bridge", "Failed to start bridge")
        self._refresh_bridge_panel()

    def _on_bridge_stop(self) -> None:
        if not self._stop_bridge:
            QtWidgets.QMessageBox.information(self, "Unavailable", "Bridge stop handler not wired yet.")
            return
        self._stop_bridge()
        QtWidgets.QMessageBox.information(self, "Bridge", "Bridge stopped")
        self._refresh_bridge_panel()

    def _on_copy_snippet(self) -> None:
        if not self._client_snippet:
            QtWidgets.QMessageBox.information(self, "Unavailable", "Snippet handler not wired yet.")
            return
        cfg = self._gather_bridge_config()
        snippet = self._client_snippet(cfg)
        QtWidgets.QApplication.clipboard().setText(snippet)
        QtWidgets.QMessageBox.information(self, "Copied", "Client snippet copied to clipboard")

    def _gather_bridge_config(self) -> BridgeConfig:
        return BridgeConfig(
            enabled=self.bridge_enabled_box.isChecked(),
            base_url=self.bridge_base_url_edit.text().strip(),
            auth_token=self.bridge_token_edit.text().strip(),
            host=self.bridge_host_edit.text().strip() or "0.0.0.0",
            port=int(self.bridge_port_spin.value()),
            request_timeout_seconds=int(self.bridge_timeout_spin.value()),
        )

    def _on_accept(self) -> None:
        if not self._validate_before_save():
            return
        cfg = self.ctx.config
        new_path = Path(self.mdb_path_edit.text()).expanduser()
        current_path = self.ctx.current_db_path()
        if new_path != current_path:
            try:
                self.ctx.update_mdb_path(new_path, create_if_missing=False)
            except FileNotFoundError:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid database",
                    f"Selected database file does not exist.\n{new_path}",
                )
                return
        cfg.links.bom_db_hint = self.bom_link_edit.text().strip()
        bridge_cfg = self._gather_bridge_config()
        cfg.bridge.enabled = bridge_cfg.enabled
        cfg.bridge.base_url = bridge_cfg.base_url
        cfg.bridge.auth_token = bridge_cfg.auth_token
        cfg.bridge.host = bridge_cfg.host
        cfg.bridge.port = bridge_cfg.port
        cfg.bridge.request_timeout_seconds = bridge_cfg.request_timeout_seconds
        self.ctx.persist_config()
        self.accept()

    def _validate_before_save(self) -> bool:
        path = Path(self.mdb_path_edit.text())
        if not path.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid database",
                "Selected database file does not exist.",
            )
            return False
        host = self.bridge_host_edit.text().strip()
        if self.bridge_enabled_box.isChecked() and not host:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid host",
                "Provide a host name for the bridge.",
            )
            return False
        return True


__all__ = ["IntegrationSettingsDialog"]
