from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from ..db import fetch_comp_desc_rows


class ComplexListModel(QtCore.QAbstractTableModel):
    HEADERS = ["ID", "Macro", "PinA", "PinB", "PinC", "PinD", "PinS"]

    def __init__(self, rows=None, macro_map=None):
        super().__init__()
        self.rows = list(rows or [])
        self.macro_map = macro_map or {}

    def load(self, rows, macro_map):
        self.beginResetModel()
        self.rows = list(rows)
        self.macro_map = macro_map
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self.rows)

    def columnCount(self, parent=None):
        return len(self.HEADERS)

    def data(self, index, role):
        if not index.isValid():
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            row = self.rows[index.row()]
            id_comp = getattr(row, "IDCompDesc", row[0])
            id_func = getattr(row, "IDFunction", row[1])
            macro = self.macro_map.get(int(id_func))
            macro_name = macro.name if macro else str(id_func)
            pin_a = getattr(row, "PinA", row[2])
            pin_b = getattr(row, "PinB", row[3])
            pin_c = getattr(row, "PinC", row[4])
            pin_d = getattr(row, "PinD", row[5])
            pin_s = "yes" if getattr(row, "PinS", row[6]) else ""
            values = [id_comp, macro_name, pin_a, pin_b, pin_c, pin_d, pin_s]
            return str(values[index.column()])
        return None

    def headerData(self, section, orientation, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole and orientation == QtCore.Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None


class ComplexListPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QTableView()
        self.model = ComplexListModel([])
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.view)

    def load_rows(self, cursor, macro_map):
        rows = fetch_comp_desc_rows(cursor, 1000)
        self.model.load(rows, macro_map)
