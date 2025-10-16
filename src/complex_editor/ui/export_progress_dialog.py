from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class ExportProgressDialog(QtWidgets.QDialog):
    """Modal dialog displaying export progress with cancel support."""

    cancel_requested = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Selected PN")
        self.setModal(True)
        self._allow_close = False

        layout = QtWidgets.QVBoxLayout(self)
        self._label = QtWidgets.QLabel("Preparing…")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._progress = QtWidgets.QProgressBar()
        self._progress.setMinimum(0)
        self._progress.setMaximum(0)  # start indeterminate
        layout.addWidget(self._progress)

        button_box = QtWidgets.QDialogButtonBox()
        self._cancel_btn = button_box.addButton(
            "Cancel",
            QtWidgets.QDialogButtonBox.ButtonRole.RejectRole,
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(button_box)

    def set_stage_text(self, text: str) -> None:
        self._label.setText(text)

    def update_progress(self, message: str, current: int, total: int) -> None:
        self.set_stage_text(message)
        if total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(min(max(current, 0), total))

    def set_cancel_enabled(self, enabled: bool) -> None:
        self._cancel_btn.setEnabled(enabled)

    def allow_close(self, allowed: bool) -> None:
        self._allow_close = allowed

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        if not self._allow_close:
            event.ignore()
            return
        super().closeEvent(event)

    def _on_cancel(self) -> None:
        self.set_cancel_enabled(False)
        self.cancel_requested.emit()


__all__ = ["ExportProgressDialog"]
