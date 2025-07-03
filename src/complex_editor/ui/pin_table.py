from __future__ import annotations

from PyQt6 import QtCore, QtWidgets


class PinTable(QtWidgets.QTableWidget):
    """Endless pin list. Columns = ["Pin#", "Net name"]."""

    def __init__(self, parent=None) -> None:
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Pin#", "Net name"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.setRowCount(2)
        self.add_pin_btn = QtWidgets.QToolButton(text="+")
        self.del_pin_btn = QtWidgets.QToolButton(text="–")
        self.add_pin_btn.clicked.connect(self.add_row)
        self.del_pin_btn.clicked.connect(self.del_row)
        self._update_numbers()

    # ------------------------------ API ---------------------------------
    def pins(self) -> list[str]:
        values: list[str] = []
        for row in range(self.rowCount()):
            item = self.item(row, 1)
            if item:
                text = item.text().strip()
                if text:
                    values.append(text)
        return values

    def set_pins(self, pins: list[str]) -> None:
        self.setRowCount(max(2, len(pins)))
        for row, pin in enumerate(pins):
            self.setItem(row, 1, QtWidgets.QTableWidgetItem(pin))
        self._update_numbers()

    # ------------------------------ utils --------------------------------
    def add_row(self) -> None:
        self.insertRow(self.rowCount())
        self._update_numbers()
        self.setCurrentCell(self.rowCount() - 1, 1)

    def del_row(self) -> None:
        if self.rowCount() > 2:
            self.removeRow(self.rowCount() - 1)
            self._update_numbers()

    def _update_numbers(self) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if not item:
                item = QtWidgets.QTableWidgetItem()
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.setItem(row, 0, item)
            item.setText(str(row + 1))

