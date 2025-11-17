"""Dialogs related to database overlay approvals."""

from __future__ import annotations

import getpass
from typing import Mapping

from PyQt6 import QtCore, QtWidgets

from complex_editor.db_overlay.models import FunctionBundle
from complex_editor.db_overlay.runtime import DbOverlayRuntime

__all__ = ["DbOverlayApprovalDialog"]


class DbOverlayApprovalDialog(QtWidgets.QDialog):
    """Prompt the user to persist newly discovered DB macro bundles."""

    def __init__(
        self,
        runtime: DbOverlayRuntime,
        bundles: Mapping[tuple[int, int], FunctionBundle],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import database functions")
        self._runtime = runtime
        self._bundles = dict(bundles)
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "New database-defined functions were discovered. "
            "Select the entries you trust and import them into the allowlist."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Function", "Macro kind", "Parameters"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        layout.addWidget(self.tree, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        self.select_all_btn = QtWidgets.QPushButton("Select all")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checks(QtCore.Qt.CheckState.Checked))
        btn_row.addWidget(self.select_all_btn)
        self.select_none_btn = QtWidgets.QPushButton("Select none")
        self.select_none_btn.clicked.connect(lambda: self._set_all_checks(QtCore.Qt.CheckState.Unchecked))
        btn_row.addWidget(self.select_none_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.button_box = QtWidgets.QDialogButtonBox()
        self.import_btn = self.button_box.addButton(
            "Import selected", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.button_box.addButton(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._on_import)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _populate(self) -> None:
        for ident, bundle in sorted(self._bundles.items()):
            label = bundle.function_name or f"Function {bundle.id_function}"
            macro = bundle.macro_kind_name or ""
            params = str(len(bundle.params))
            item = QtWidgets.QTreeWidgetItem([label, macro, params])
            flags = item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags)
            item.setCheckState(0, QtCore.Qt.CheckState.Checked)
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ident)
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)

    def _set_all_checks(self, state: QtCore.Qt.CheckState) -> None:
        for idx in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(idx)
            item.setCheckState(0, state)

    def _selected_identities(self) -> list[tuple[int, int]]:
        selected: list[tuple[int, int]] = []
        for idx in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(idx)
            if item.checkState(0) == QtCore.Qt.CheckState.Checked:
                ident = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if isinstance(ident, tuple) and len(ident) == 2:
                    selected.append((int(ident[0]), int(ident[1])))
        return selected

    def _on_import(self) -> None:
        identities = self._selected_identities()
        if not identities:
            QtWidgets.QMessageBox.information(
                self,
                "Nothing selected",
                "Select at least one function to import.",
            )
            return
        errors: list[str] = []
        username = self._current_user()
        for ident in identities:
            try:
                self._runtime.approve_bundle(ident, persist=True, user=username)
            except Exception as exc:  # pragma: no cover - UI safeguard
                errors.append(str(exc))
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                "Import incomplete",
                "\n".join(errors),
            )
        self.accept()

    @staticmethod
    def _current_user() -> str | None:
        try:
            return getpass.getuser()
        except Exception:  # pragma: no cover - platform quirk
            return None
