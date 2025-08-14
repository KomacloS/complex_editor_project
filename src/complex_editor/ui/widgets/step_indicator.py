from __future__ import annotations

from typing import List

from PyQt6 import QtWidgets, QtCore


class StepIndicator(QtWidgets.QWidget):
    """Simple horizontal step indicator used by the wizard."""

    step_clicked = QtCore.pyqtSignal(int)

    def __init__(self, steps: List[str], parent=None) -> None:
        super().__init__(parent)
        self._labels: List[QtWidgets.QPushButton] = []
        self._current = -1
        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(4)
        for idx, name in enumerate(steps):
            btn = QtWidgets.QPushButton(name)
            btn.setFlat(True)
            btn.setStyleSheet("padding:4px;border:1px solid #888;")
            btn.clicked.connect(lambda _=False, i=idx: self.step_clicked.emit(i))
            layout.addWidget(btn)
            self._labels.append(btn)
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
