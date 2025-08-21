from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from ..db import fetch_comp_desc_rows


class ComplexListModel(QtCore.QAbstractTableModel):
    """Simple table model for both DB and buffer rows."""

    HEADERS_DB = ["ID", "Macro", "PinA", "PinB", "PinC", "PinD", "PinS"]
    HEADERS_BUFFER = ["ID", "Name", "#Subs"]

    def __init__(self, rows=None, headers=None, macro_map=None):
        super().__init__()
        self.rows = list(rows or [])
        self.headers = headers or list(self.HEADERS_DB)
        self.macro_map = macro_map or {}

    def load(self, rows, macro_map=None, headers=None):
        self.beginResetModel()
        self.rows = list(rows)
        if headers is not None:
            self.headers = list(headers)
        if macro_map is not None:
            self.macro_map = macro_map
        self.endResetModel()

    def rowCount(self, parent=None):  # type: ignore[override]
        return len(self.rows)

    def columnCount(self, parent=None):  # type: ignore[override]
        return len(self.headers)

    def data(self, index, role):  # type: ignore[override]
        if not index.isValid():
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            row = self.rows[index.row()]
            # DB rows come either as tuples or row objects with the legacy
            # column attributes.  Buffer rows are ``EditorComplex`` instances.
            if hasattr(row, "subcomponents") and hasattr(row, "name"):
                # buffer model
                values = [
                    getattr(row, "id", 0),
                    getattr(row, "name", ""),
                    len(getattr(row, "subcomponents", []) or []),
                ]
                return str(values[index.column()])

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

    def headerData(self, section, orientation, role):  # type: ignore[override]
        if (
            role == QtCore.Qt.ItemDataRole.DisplayRole
            and orientation == QtCore.Qt.Orientation.Horizontal
        ):
            return self.headers[section]
        return None


class ComplexListPanel(QtWidgets.QWidget):
    complexSelected = QtCore.pyqtSignal(object)
    editRequested = QtCore.pyqtSignal(object)
    newComplexRequested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        btn_new = QtWidgets.QPushButton("New Complex")
        btn_new.clicked.connect(self.newComplexRequested.emit)
        layout.addWidget(btn_new)
        self.view = QtWidgets.QTableView()
        self.model = ComplexListModel([])
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.view.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.view.clicked.connect(self._on_clicked)
        self.view.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.view)
        self._refresh_cb = None

    def load_rows(self, cursor, macro_map):
        rows = fetch_comp_desc_rows(cursor, 1000)
        self.model.load(rows, macro_map, headers=self.model.HEADERS_DB)

    def load_buffer_models(self, editor_complexes, macro_map):
        self.model.load(
            editor_complexes, macro_map, headers=self.model.HEADERS_BUFFER
        )

    def set_refresh_callback(self, cb):
        self._refresh_cb = cb

    def refresh_and_select(self, complex_id: int) -> None:
        """Refresh list and select the row with ``complex_id`` if present."""
        if self._refresh_cb:
            self._refresh_cb()
        for row, data in enumerate(self.model.rows):
            if hasattr(data, "id"):
                cid = getattr(data, "id")
            else:
                cid = getattr(data, "IDCompDesc", data[0])
            if int(cid) == int(complex_id):
                index = self.model.index(row, 0)
                self.view.selectRow(index.row())
                break

    def _on_clicked(self, index: QtCore.QModelIndex) -> None:
        if not index.isValid():
            return
        row = self.model.rows[index.row()]
        self.complexSelected.emit(row)

    def _on_double_clicked(self, index: QtCore.QModelIndex) -> None:
        if not index.isValid():
            return
        row = self.model.rows[index.row()]
        self.editRequested.emit(row)
