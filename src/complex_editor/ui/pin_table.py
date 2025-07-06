from __future__ import annotations

from PyQt6 import QtWidgets


class PinTable(QtWidgets.QTableWidget):
    """Simple table for editing pin names."""

    def __init__(self, parent=None) -> None:
        super().__init__(0, 1, parent)
        self.setHorizontalHeaderLabels(["Pin"])
        self.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )

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
