from __future__ import annotations

from typing import List

from PyQt6 import QtWidgets


class StepIndicator(QtWidgets.QWidget):
    """Simple horizontal step indicator used by the wizard."""

    def __init__(self, steps: List[str], parent=None) -> None:
        super().__init__(parent)
        self._labels: List[QtWidgets.QLabel] = []
        self._current = -1
        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(4)
        for name in steps:
            lbl = QtWidgets.QLabel(name)
            lbl.setStyleSheet("padding:4px;border:1px solid #888;")
            layout.addWidget(lbl)
            self._labels.append(lbl)
        layout.addStretch()
        self.set_current(0)

    def set_current(self, index: int) -> None:
        self._current = index
        for i, lbl in enumerate(self._labels):
            if i == index:
                lbl.setStyleSheet(
                    "padding:4px;border:1px solid #888;background:#007acc;color:white;font-weight:bold;"
                )
            else:
                lbl.setStyleSheet("padding:4px;border:1px solid #888;")

    @property
    def current_index(self) -> int:
        return self._current
