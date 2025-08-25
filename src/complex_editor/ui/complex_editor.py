"""Simplified Complex Editor window used for creating and editing complexes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from PyQt6 import QtCore, QtWidgets

from ..domain import ComplexDevice, MacroDef, MacroInstance, SubComponent
from .param_editor_dialog import ParamEditorDialog
from .validators import validate_pins, validate_pin_table


@dataclass
class _Row:
    macro_id: int | None = None
    pins: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    params: Dict[str, str] = field(default_factory=dict)


class ComplexSubComponentsModel(QtCore.QAbstractTableModel):
    """Table model holding sub-component rows."""

    headers = ["#", "Macro", "Pin A", "Pin B", "Pin C", "Pin D", "Parameters", "Edit…"]

    def __init__(self, macro_map: Dict[int, MacroDef]):
        super().__init__()
        self.rows: List[_Row] = []
        self.macro_map = macro_map

    # --------------------------------------------------------------- Qt API
    def rowCount(self, parent=QtCore.QModelIndex()):  # pragma: no cover - trivial
        return len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):  # pragma: no cover
        return len(self.headers)

    def headerData(self, section, orientation, role):  # pragma: no cover
        if (
            role == QtCore.Qt.ItemDataRole.DisplayRole
            and orientation == QtCore.Qt.Orientation.Horizontal
        ):
            return self.headers[section]
        return None

    def data(self, index, role):  # pragma: no cover - simple display
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return index.row() + 1
            if col == 1 and row.macro_id is not None:
                macro = self.macro_map.get(row.macro_id)
                return macro.name if macro else row.macro_id
            if 2 <= col <= 5:
                return row.pins[col - 2] or ""
            if col == 6:
                return "; ".join(f"{k}={v}" for k, v in row.params.items()) or "[not set]"
            if col == 7:
                return "Edit…"
        return None

    def flags(self, index):  # pragma: no cover - behaviour
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        flags = (
            QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsDragEnabled
            | QtCore.Qt.ItemFlag.ItemIsDropEnabled
        )
        if index.column() in {1, 2, 3, 4, 5}:
            flags |= QtCore.Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role):  # pragma: no cover - simple edit
        if role != QtCore.Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row = self.rows[index.row()]
        col = index.column()
        if col == 1:
            row.macro_id = int(value)
            row.params.clear()
            # refresh summary column when macro changes
            self.dataChanged.emit(self.index(index.row(), 6), self.index(index.row(), 6))
        elif 2 <= col <= 5:
            try:
                row.pins[col - 2] = int(value)
            except (TypeError, ValueError):
                row.pins[col - 2] = 0
        else:
            return False
        self.dataChanged.emit(index, index)
        return True

    # ---------------------------------------------------------- row ops
    def add_row(self) -> int:
        self.beginInsertRows(QtCore.QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(_Row())
        self.endInsertRows()
        return len(self.rows) - 1

    def remove_row(self, row: int) -> None:
        if 0 <= row < len(self.rows):
            self.beginRemoveRows(QtCore.QModelIndex(), row, row)
            del self.rows[row]
            self.endRemoveRows()

    def duplicate_row(self, row: int) -> None:
        if 0 <= row < len(self.rows):
            clone = _Row(
                macro_id=self.rows[row].macro_id,
                pins=list(self.rows[row].pins),
                params=dict(self.rows[row].params),
            )
            self.beginInsertRows(QtCore.QModelIndex(), row + 1, row + 1)
            self.rows.insert(row + 1, clone)
            self.endInsertRows()

    # Qt drag/drop support -------------------------------------------------
    def mimeTypes(self):  # pragma: no cover - trivial
        return ["application/x-row"]

    def mimeData(self, indexes):  # pragma: no cover - UI
        mime = QtCore.QMimeData()
        if indexes:
            mime.setData("application/x-row", str(indexes[0].row()).encode())
        return mime

    def supportedDropActions(self):  # pragma: no cover - trivial
        return QtCore.Qt.DropAction.MoveAction

    def dropMimeData(self, data, action, row, column, parent):  # pragma: no cover - UI
        if action != QtCore.Qt.DropAction.MoveAction:
            return False
        if not data.hasFormat("application/x-row"):
            return False
        src = int(bytes(data.data("application/x-row")).decode())
        if row == -1:
            row = parent.row()
        if row == -1:
            row = self.rowCount()
        if src < row:
            row -= 1
        if src == row:
            return False
        self.beginMoveRows(QtCore.QModelIndex(), src, src, QtCore.QModelIndex(), row)
        self.rows.insert(row, self.rows.pop(src))
        self.endMoveRows()
        self.dataChanged.emit(
            self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1)
        )
        return True

    def is_valid(self, max_pin: int) -> bool:
        rows = [r.pins for r in self.rows if r.macro_id is not None]
        ok, _ = validate_pin_table(rows, max_pin)
        if not ok:
            return False
        return all(r.macro_id is not None for r in self.rows)

    def to_subcomponents(self) -> List[SubComponent]:
        result: List[SubComponent] = []
        for r in self.rows:
            if r.macro_id is None:
                continue
            macro = self.macro_map.get(r.macro_id)
            name = macro.name if macro else str(r.macro_id)
            inst = MacroInstance(name, dict(r.params))
            result.append(SubComponent(inst, tuple(r.pins)))
        return result


class MacroComboDelegate(QtWidgets.QStyledItemDelegate):
    """Combo-box delegate for selecting macros."""

    def __init__(self, macro_map: Dict[int, MacroDef], parent=None) -> None:
        super().__init__(parent)
        self._map = macro_map

    def createEditor(self, parent, option, index):  # pragma: no cover - UI
        spin = QtWidgets.QSpinBox(parent)
        spin.setMinimum(1)
        spin.setMaximum(self._pin_spin.value())
        spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)

        # Ensure text is committed on Enter / focus out
        spin.editingFinished.connect(lambda: self.commitData.emit(spin))
        spin.editingFinished.connect(lambda: self.closeEditor.emit(spin))

        # Keep the editor's max in sync if "Number of pins" changes while editing
        try:
            self._pin_spin.valueChanged.connect(spin.setMaximum)
        except Exception:
            # if already connected in repeated calls, ignore
            pass

        # Optional: prevents half-typed values from changing the spinbox mid-typing
        spin.setKeyboardTracking(False)
        return spin


    def setEditorData(self, editor, index):  # pragma: no cover - UI
        row = index.model().rows[index.row()]
        if row.macro_id is not None:
            i = editor.findData(row.macro_id)
            if i >= 0:
                editor.setCurrentIndex(i)

    def setModelData(self, editor, model, index):  # pragma: no cover - UI
        # Ensure typed text is parsed
        try:
            editor.interpretText()
        except Exception:
            pass

        new_val = int(editor.value())
        row = index.row()
        col = index.column() - 2  # A=0, B=1, C=2, D=3 within the row model
        max_pin = self._pin_spin.value()

        # Range check only; we will handle duplicates by swapping
        if new_val < 1 or new_val > max_pin:
            QtWidgets.QApplication.beep()
            return

        pins = self._model.rows[row].pins
        old_val = pins[col]

        if new_val == old_val:
            # Nothing to do
            return

        # If the new pin already exists in this row, SWAP instead of rejecting
        if new_val in pins:
            other_col = pins.index(new_val)  # 0..3 in row space
            # Put the old value where the duplicate lived
            model.setData(model.index(row, other_col + 2), old_val, QtCore.Qt.ItemDataRole.EditRole)

        # Now set the edited cell to the new value
        model.setData(index, new_val, QtCore.Qt.ItemDataRole.EditRole)




class PinSpinDelegate(QtWidgets.QStyledItemDelegate):
    """Spin-box delegate enforcing pin range and uniqueness."""

    def __init__(self, pin_spin: QtWidgets.QSpinBox, model: ComplexSubComponentsModel, parent=None) -> None:
        super().__init__(parent)
        self._pin_spin = pin_spin
        self._model = model

    def createEditor(self, parent, option, index):  # pragma: no cover - UI
        spin = QtWidgets.QSpinBox(parent)
        spin.setMinimum(1)
        spin.setMaximum(self._pin_spin.value())
        # Hide arrows so numbers are fully visible
        spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        # Important: let the view own commit/close; don't emit commitData/closeEditor yourself
        spin.setKeyboardTracking(False)  # only commit on Enter/focus-out
        # Keep max in sync with "Number of pins"
        try:
            self._pin_spin.valueChanged.connect(spin.setMaximum)
        except Exception:
            pass
        return spin



    def setEditorData(self, editor, index):  # pragma: no cover - UI
        val = self._model.rows[index.row()].pins[index.column() - 2]
        if val:
            editor.setValue(val)

    def setModelData(self, editor, model, index):  # pragma: no cover - UI
        # Make sure typed text is parsed
        try:
            editor.interpretText()
        except Exception:
            pass

        new_val = int(editor.value())
        row = index.row()
        col = index.column() - 2  # columns 2..5 map to pins A..D
        max_pin = self._pin_spin.value()

        # Range check only; duplicates are handled by swapping
        if new_val < 1 or new_val > max_pin:
            QtWidgets.QApplication.beep()
            return

        pins = self._model.rows[row].pins
        old_val = pins[col]
        if new_val == old_val:
            return

        # If new value exists elsewhere in the same row -> swap
        if new_val in pins:
            other_col = pins.index(new_val)
            # move old value into the other slot
            model.setData(model.index(row, other_col + 2), old_val, QtCore.Qt.ItemDataRole.EditRole)

        # Set edited cell
        model.setData(index, new_val, QtCore.Qt.ItemDataRole.EditRole)


class ComplexEditor(QtWidgets.QDialog):
    """Main editor dialog for complexes."""

    def __init__(self, macro_map: Dict[int, MacroDef], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Complex Editor")
        self.macro_map = macro_map
        self.device_id: int | None = None

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.pn_edit = QtWidgets.QLineEdit()
        form.addRow("PN", self.pn_edit)
        self.alt_pn_edit = QtWidgets.QLineEdit()
        form.addRow("Alternative PN", self.alt_pn_edit)
        self.pin_spin = QtWidgets.QSpinBox()
        self.pin_spin.setMinimum(1)
        self.pin_spin.setMaximum(1000)
        form.addRow("Number of pins", self.pin_spin)
        layout.addLayout(form)

        self.model = ComplexSubComponentsModel(macro_map)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.table)

        # delegates for combo-box and pin selection
        self._macro_delegate = MacroComboDelegate(macro_map, self.table)
        self.table.setItemDelegateForColumn(1, self._macro_delegate)
        pin_delegate = PinSpinDelegate(self.pin_spin, self.model, self.table)
        for col in range(2, 6):
            self.table.setItemDelegateForColumn(col, pin_delegate)
        self.table.clicked.connect(self._table_clicked)

        btn_bar = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Add")
        rm_btn = QtWidgets.QPushButton("Remove")
        dup_btn = QtWidgets.QPushButton("Duplicate")
        add_btn.clicked.connect(self._add_row)
        rm_btn.clicked.connect(self._remove_row)
        dup_btn.clicked.connect(self._dup_row)
        btn_bar.addWidget(add_btn)
        btn_bar.addWidget(rm_btn)
        btn_bar.addWidget(dup_btn)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.setEnabled(False)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        self.save_btn.clicked.connect(self._on_accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box = QtWidgets.QHBoxLayout()
        btn_box.addStretch()
        btn_box.addWidget(self.save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

        # ensure the dialog is wide enough to show all table columns
        self.resize(1000, 600)

        self.pn_edit.textChanged.connect(self._update_state)
        self.pin_spin.valueChanged.connect(self._update_state)
        self.model.dataChanged.connect(self._update_state)
        self.model.rowsInserted.connect(self._update_state)
        self.model.rowsRemoved.connect(self._update_state)

    # -------------------------------------------------------------- callbacks
    def _add_row(self) -> None:
        row = self.model.add_row()
        self._open_param_editor(row)

    def _remove_row(self) -> None:
        row = self.table.currentIndex().row()
        self.model.remove_row(row)

    def _dup_row(self) -> None:
        row = self.table.currentIndex().row()
        self.model.duplicate_row(row)

    def _table_clicked(self, index: QtCore.QModelIndex) -> None:
        if index.column() == 7:
            self._open_param_editor(index.row())

    def _open_param_editor(self, row: int) -> None:
        r = self.model.rows[row]
        if r.macro_id is None:
            return
        macro = self.macro_map.get(r.macro_id)
        if macro is None:
            return
        dlg = ParamEditorDialog(macro, r.params, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            r.params = dlg.params()
            idx = self.model.index(row, 6)
            self.model.dataChanged.emit(idx, idx)

    def _update_state(self) -> None:
        max_pin = self.pin_spin.value()
        # clamp any pins above the new limit
        changed = False
        for r in self.model.rows:
            for i, p in enumerate(r.pins):
                if p > max_pin:
                    r.pins[i] = max_pin
                    changed = True
        if changed:
            self.model.blockSignals(True)
            self.model.dataChanged.emit(QtCore.QModelIndex(), QtCore.QModelIndex())
            self.model.blockSignals(False)
        valid = bool(self.pn_edit.text().strip()) and self.model.is_valid(max_pin)
        self.save_btn.setEnabled(valid)

    def _force_commit_table_editor(self) -> None:
        ed = self.table.focusWidget()
        if isinstance(ed, QtWidgets.QLineEdit) and isinstance(ed.parent(), (QtWidgets.QSpinBox, QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox)):
            ed = ed.parent()
        if isinstance(ed, (QtWidgets.QSpinBox, QtWidgets.QComboBox, QtWidgets.QLineEdit)):
            self.table.commitData(ed)
            self.table.closeEditor(ed, QtWidgets.QAbstractItemDelegate.EndEditHint.NoHint)

    # ----------------------------------------------------------- public API
    def load_device(self, device: ComplexDevice) -> None:
        self.device_id = device.id
        self.pn_edit.setText(device.pn)
        self.alt_pn_edit.setText(device.alt_pn)
        self.pin_spin.setValue(device.pin_count)
        for sc in device.subcomponents:
            row = self.model.add_row()
            self.model.rows[row].macro_id = self._macro_id_by_name(sc.macro.name)
            self.model.rows[row].pins = list(sc.pins) + [0, 0, 0, 0]
            self.model.rows[row].pins = self.model.rows[row].pins[:4]
            self.model.rows[row].params = dict(sc.macro.params)
        self.model.dataChanged.emit(QtCore.QModelIndex(), QtCore.QModelIndex())
        self._update_state()

    def build_device(self) -> ComplexDevice:
        """Return a :class:`~complex_editor.domain.ComplexDevice` reflecting the UI.

        The ``alt_pn`` field is included for completeness but the current MDB
        schema does not persist it.
        """

        self._force_commit_table_editor()
        dev = ComplexDevice(0, [], MacroInstance("", {}))
        dev.pn = self.pn_edit.text().strip()
        dev.alt_pn = self.alt_pn_edit.text().strip()
        dev.pin_count = int(self.pin_spin.value())
        dev.id = self.device_id
        dev.subcomponents = self.model.to_subcomponents()
        return dev

    # -------------------------------------------------------------- accept logic
    def _on_accept(self) -> None:
        self._force_commit_table_editor()
        if not self.model.is_valid(self.pin_spin.value()) or not self.pn_edit.text().strip():
            QtWidgets.QApplication.beep()
            return
        self.accept()

    def _macro_id_by_name(self, name: str) -> int | None:
        for mid, m in self.macro_map.items():
            if m.name == name:
                return mid
        return None
