from __future__ import annotations

from PyQt6 import QtWidgets


class StepIndicator(QtWidgets.QWidget):
    """Simple horizontal step indicator highlighting the current step."""

    def __init__(self, steps: list[str], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: list[QtWidgets.QLabel] = []
        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(6)
        for name in steps:
            lbl = QtWidgets.QLabel(name)
            lbl.setStyleSheet("padding:2px 6px;border:1px solid #999;border-radius:3px;")
            layout.addWidget(lbl)
            self._labels.append(lbl)
        layout.addStretch()
        self._current = -1
        self.set_current(0)

    def set_current(self, index: int) -> None:
        """Highlight the block at ``index`` and reset others."""
        self._current = index
        for i, lbl in enumerate(self._labels):
            if i == index:
                lbl.setStyleSheet(
                    "padding:2px 6px;border:1px solid #666;"
                    "border-radius:3px;background:#0078d4;color:white;font-weight:bold;"
                )
            else:
                lbl.setStyleSheet(
                    "padding:2px 6px;border:1px solid #999;border-radius:3px;color:black;"
                )
