from __future__ import annotations

from typing import Iterable, cast
from PyQt6 import QtGui, QtWidgets


class PinTable(QtWidgets.QTableWidget):
    """Simple table for editing pin names."""

    def __init__(self, parent=None) -> None:
        super().__init__(0, 1, parent)
        self.setHorizontalHeaderLabels(["Pin"])
        hdr = cast(QtWidgets.QHeaderView, self.horizontalHeader())
        hdr.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)

    def set_pins(self, pins: list[str]) -> None:
        self.setRowCount(len(pins))
        for row, name in enumerate(pins):
            item = QtWidgets.QTableWidgetItem(name)
            self.setItem(row, 0, item)

    def pins(self) -> list[str]:
        result: list[str] = []
        for i in range(self.rowCount()):
            item = self.item(i, 0)
            result.append(item.text() if item else "")
        return result

    def highlight_pins(self, pad_numbers: Iterable[int]) -> None:
        """Color given pad rows yellow, others white."""
        yellow = QtGui.QColor("yellow")
        white = QtGui.QColor("white")
        numbers = set(pad_numbers)
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if not item:
                continue
            item.setBackground(yellow if (row + 1) in numbers else white)
