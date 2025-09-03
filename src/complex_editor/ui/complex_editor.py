"""Simplified Complex Editor window used for creating and editing complexes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox, QAbstractItemDelegate

from ..domain import ComplexDevice, MacroDef, MacroInstance, SubComponent
from .param_editor_dialog import ParamEditorDialog


@dataclass
class _Row:
    macro_id: int | None = None
    # Store pins as *strings* so the user can erase or type anything.
    pins: List[str] = field(default_factory=lambda: ["", "", "", ""])
    params: Dict[str, str] = field(default_factory=dict)


class ComplexSubComponentsModel(QtCore.QAbstractTableModel):
    """Table model holding sub-component rows with per-cell error highlights."""

    headers = ["#", "Macro", "Pin A", "Pin B", "Pin C", "Pin D", "Parameters", "Edit…"]

    def __init__(self, macro_map: Dict[int, MacroDef]):
        super().__init__()
        self.rows: List[_Row] = []
        self.macro_map = macro_map
        # (row, col) -> (QColor, tooltip)
        self._cell_marks: dict[tuple[int, int], tuple[QColor, str]] = {}

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

        # Error highlights/tooltips
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            mark = self._cell_marks.get((index.row(), index.column()))
            if mark:
                return mark[0]
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            mark = self._cell_marks.get((index.row(), index.column()))
            if mark:
                return mark[1]

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return index.row() + 1
            if col == 1 and row.macro_id is not None:
                macro = self.macro_map.get(row.macro_id)
                return macro.name if macro else row.macro_id
            if 2 <= col <= 5:
                # Show text as-is (empty allowed)
                return row.pins[col - 2]
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
        # Macro + Pin columns are editable; we do not restrict typing here.
        if index.column() in {1, 2, 3, 4, 5}:
            flags |= QtCore.Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role):  # pragma: no cover - simple edit
        if role != QtCore.Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row = self.rows[index.row()]
        col = index.column()
        if col == 1:
            # Only update if a valid selection was made; ignore canceled edits.
            try:
                new_id = int(value)
            except (TypeError, ValueError):
                return False
            if row.macro_id != new_id:
                row.macro_id = new_id
                # Reset params when macro changes
                row.params.clear()
                # refresh summary column when macro changes
                self.dataChanged.emit(self.index(index.row(), 6), self.index(index.row(), 6))
        elif 2 <= col <= 5:
            # Accept any text (including empty); ignore canceled edits (value is None).
            if value is None:
                return False
            row.pins[col - 2] = str(value).strip()
        else:
            return False
        self.dataChanged.emit(index, index)
        return True

    # ---------------------------------------------------------- error marks
    def clear_pin_marks(self) -> None:
        if not self._cell_marks:
            return
        self._cell_marks.clear()
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
            )

    def mark_invalid(self, r: int, c: int, reason: str) -> None:
        self._cell_marks[(r, c)] = (QColor(255, 204, 204), reason)  # light red
        idx = self.index(r, c)
        self.dataChanged.emit(idx, idx)

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

    # Relaxed validity for enabling Save button (no pin checks here).
    def is_semivalid(self) -> bool:
        return any(r.macro_id is not None for r in self.rows)

    def to_subcomponents(self) -> List[SubComponent]:
        """Convert rows to domain objects, assuming validation passed."""
        def _p2i(s: str) -> int:
            s = (s or "").strip()
            try:
                v = int(s, 10)
                return v if v > 0 else 0
            except Exception:
                return 0

        result: List[SubComponent] = []
        for r in self.rows:
            if r.macro_id is None:
                continue
            macro = self.macro_map.get(r.macro_id)
            name = macro.name if macro else str(r.macro_id)
            inst = MacroInstance(name, dict(r.params))
            pins_tuple = (_p2i(r.pins[0]), _p2i(r.pins[1]), _p2i(r.pins[2]), _p2i(r.pins[3]))
            result.append(SubComponent(inst, pins_tuple))
        return result


class MacroComboDelegate(QtWidgets.QStyledItemDelegate):
    """Combo-box delegate for selecting macros (popup sized to contents; no eliding)."""

    def __init__(self, macro_map: Dict[int, MacroDef], parent=None) -> None:
        super().__init__(parent)
        # Sort by name for easier scanning
        self._map = dict(sorted(macro_map.items(), key=lambda kv: kv[1].name.lower()))

    def createEditor(self, parent, option, index):  # pragma: no cover - UI
        combo = QtWidgets.QComboBox(parent)

        # Fill items: text=name, data=id
        for mid, macro in self._map.items():
            combo.addItem(macro.name, int(mid))

        # Type-to-search; keep text un-elided
        combo.setEditable(True)
        combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        combo.setMinimumContentsLength(20)
        combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setMaxVisibleItems(25)
        combo.setStyleSheet("QComboBox { combobox-popup: 0; }")  # allow wide popup

        # Custom view so we can disable eliding and widen popup
        view = QtWidgets.QListView(combo)
        view.setUniformItemSizes(False)
        view.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        combo.setView(view)

        # Make the popup wide enough for the longest macro name
        fm = combo.view().fontMetrics()
        max_text = max((fm.horizontalAdvance(m.name) for m in self._map.values()), default=0)
        combo.view().setMinimumWidth(max(260, max_text + 32))

        # Case-insensitive "contains" completer
        comp = combo.completer()
        if comp is not None:
            comp.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)

        # Pop open immediately for quick selection
        QtCore.QTimer.singleShot(0, combo.showPopup)
        return combo

    def setEditorData(self, editor, index):  # pragma: no cover - UI
        row = index.model().rows[index.row()]
        target_id = row.macro_id
        if isinstance(editor, QtWidgets.QComboBox):
            if target_id is not None:
                i = editor.findData(int(target_id))
                if i >= 0:
                    editor.setCurrentIndex(i)
        else:
            if target_id is not None:
                name = self._map.get(int(target_id), None)
                if name:
                    editor.setText(name.name)

    def setModelData(self, editor, model, index):  # pragma: no cover - UI
        if isinstance(editor, QtWidgets.QComboBox):
            mid = editor.currentData()
            if mid is None:
                # Fallback by name if user typed
                name = editor.currentText().strip().lower()
                mid = next((i for i, m in self._map.items() if m.name.lower() == name), None)
            if mid is not None:
                model.setData(index, int(mid), QtCore.Qt.ItemDataRole.EditRole)
            return

        # Fallback if an unexpected editor appears
        if hasattr(editor, "text"):
            name = editor.text().strip().lower()
            mid = next((i for i, m in self._map.items() if m.name.lower() == name), None)
            if mid is not None:
                model.setData(index, int(mid), QtCore.Qt.ItemDataRole.EditRole)




class PinLineDelegate(QtWidgets.QStyledItemDelegate):
    """Line-edit delegate allowing empty/free text; validation is deferred to Save."""

    def __init__(self, model: ComplexSubComponentsModel, max_pin_spin: QtWidgets.QSpinBox, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._pin_spin = max_pin_spin  # kept to update placeholder with the max pins

    def createEditor(self, parent, option, index):  # pragma: no cover - UI
        le = QtWidgets.QLineEdit(parent)
        # Show valid range hint and NC note
        try:
            max_pins = int(self._pin_spin.value())
        except Exception:
            max_pins = 0
        hint = f"1..{max_pins} " if max_pins else ""
        le.setPlaceholderText(f"{hint}(empty = NC)")
        # Avoid showing the overlay clear-button (big X) on double-click
        le.setClearButtonEnabled(False)
        le.setMaxLength(6)  # plenty for pin count
        return le

    def setEditorData(self, editor, index):  # pragma: no cover - UI
        txt = self._model.rows[index.row()].pins[index.column() - 2]
        editor.setText(txt)

    def setModelData(self, editor, model, index):  # pragma: no cover - UI
        model.setData(index, editor.text(), QtCore.Qt.ItemDataRole.EditRole)


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

        # Alternative PN(s): input + list with add/remove controls
        self.alt_pn_edit = QtWidgets.QLineEdit()
        self.alt_pn_edit.setPlaceholderText("Type alternative PN and press Enter")
        self.alt_pn_add_btn = QtWidgets.QPushButton("Add")
        self.alt_pn_rm_btn = QtWidgets.QPushButton("Remove")
        self.alt_pn_list = QtWidgets.QListWidget()
        self.alt_pn_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        # wire events
        self.alt_pn_add_btn.clicked.connect(self._on_alias_add)
        self.alt_pn_rm_btn.clicked.connect(self._on_alias_remove)
        self.alt_pn_edit.returnPressed.connect(self._on_alias_add)

        _alias_row = QtWidgets.QWidget()
        _alias_row_h = QtWidgets.QHBoxLayout(_alias_row)
        _alias_row_h.setContentsMargins(0, 0, 0, 0)
        _alias_row_h.addWidget(self.alt_pn_edit)
        _alias_row_h.addWidget(self.alt_pn_add_btn)
        _alias_row_h.addWidget(self.alt_pn_rm_btn)

        _alias_box = QtWidgets.QWidget()
        _alias_v = QtWidgets.QVBoxLayout(_alias_box)
        _alias_v.setContentsMargins(0, 0, 0, 0)
        _alias_v.addWidget(_alias_row)
        _alias_v.addWidget(self.alt_pn_list)
        form.addRow("Alternative PNs", _alias_box)
        # Make alias list expand within the form and be reasonably small by default
        self.alt_pn_list.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.alt_pn_list.setMinimumHeight(60)

        self.pin_spin = QtWidgets.QSpinBox()
        self.pin_spin.setMinimum(1)
        self.pin_spin.setMaximum(1000)
        form.addRow("Number of pins", self.pin_spin)

        self.model = ComplexSubComponentsModel(macro_map)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        # Avoid DoubleClicked to reduce noisy "edit: editing failed" logs on non-editable columns
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        # --- table header / sizing (replace your existing header setup) ---
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        # Make the Macro column (col 1) interactive & wide enough to read names
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 260)     # default width for "Macro"
        self.table.setWordWrap(False)         # avoid ellipsis inside cells
        # Put form (with aliases) and table in a vertical splitter for adjustable heights
        form_box = QtWidgets.QWidget()
        form_box.setLayout(form)
        splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(form_box)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 0)  # top (form) gets less stretch
        splitter.setStretchFactor(1, 1)  # table expands
        # Default sizes: keep the form smaller vertically by default
        splitter.setSizes([220, 600])
        layout.addWidget(splitter)

        # Delegates (keep references to avoid GC)
        self._macro_delegate = MacroComboDelegate(macro_map, self.table)
        self.table.setItemDelegateForColumn(1, self._macro_delegate)
        self._pin_delegate = PinLineDelegate(self.model, self.pin_spin, self.table)
        for col in range(2, 6):
            self.table.setItemDelegateForColumn(col, self._pin_delegate)
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

        # Enable Save when PN present and at least one macro is chosen.
        self.pn_edit.textChanged.connect(self._update_state)
        self.pin_spin.valueChanged.connect(self._update_state)  # revalidate on Save; no clamping here
        self.model.dataChanged.connect(self._update_state)
        self.model.rowsInserted.connect(self._update_state)
        self.model.rowsRemoved.connect(self._update_state)

    # -------------------------------------------------------------- callbacks
    def _add_row(self) -> None:
        row = self.model.add_row()
        # Immediately open the Macro chooser for smooth flow
        idx = self.model.index(row, 1)
        self.table.setCurrentIndex(idx)
        self.table.edit(idx)

    def _remove_row(self) -> None:
        row = self.table.currentIndex().row()
        self.model.remove_row(row)
        self._update_state()

    def _dup_row(self) -> None:
        # Ensure any in-progress edits are committed before duplicating
        self._force_commit_table_editor()
        row = self.table.currentIndex().row()
        self.model.duplicate_row(row)
        # Re-enable Save if criteria met
        self._update_state()

    def _table_clicked(self, index: QtCore.QModelIndex) -> None:
        if index.column() in (6, 7):
            self._open_param_editor(index.row())
            return
        # Clicking the Macro column should open the combo immediately
        if index.column() == 1:
            self.table.edit(index)
            return
        # Single-click pin cells should enter edit immediately
        if 2 <= index.column() <= 5:
            self.table.edit(index)
            return



    def _open_param_editor(self, row: int) -> None:
        r = self.model.rows[row]
        if r.macro_id is None:
            return
        macro = self.macro_map.get(r.macro_id)
        if macro is None:
            return
        dlg = ParamEditorDialog(macro, r.params, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            # Preserve existing parameters when reopening without changes by
            # saving all current values (defaults are dropped at serialization).
            r.params = dlg.params(only_changed=False)
            idx = self.model.index(row, 6)
            self.model.dataChanged.emit(idx, idx)

    def _update_state(self) -> None:
        # Do NOT clamp or validate pins live. Just enable Save if PN is set and any macro selected.
        pn_ok = bool(self.pn_edit.text().strip())
        any_macro = self.model.is_semivalid()
        self.save_btn.setEnabled(pn_ok and any_macro)

    def _force_commit_table_editor(self) -> None:
        ed = self.table.focusWidget()
        # If the editor is the embedded QLineEdit child, climb to its parent delegate editor
        if isinstance(ed, QtWidgets.QLineEdit) and isinstance(
            ed.parent(), (QtWidgets.QSpinBox, QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox)
        ):
            ed = ed.parent()
        if isinstance(ed, (QtWidgets.QSpinBox, QtWidgets.QComboBox, QtWidgets.QLineEdit)):
            self.table.commitData(ed)
            self.table.closeEditor(ed, QtWidgets.QAbstractItemDelegate.EndEditHint.NoHint)

    # ------------------------------ validation on Save (mark red + message)
    def _pin_columns(self) -> dict[str, int]:
        # Fixed layout: columns 2..5 are A..D
        return {"A": 2, "B": 3, "C": 4, "D": 5}

    def _validate_and_mark_pins(self) -> tuple[bool, list[str]]:
        self.model.clear_pin_marks()
        max_pin = int(self.pin_spin.value())
        errors: list[str] = []
        cols = self._pin_columns()

        for r_idx, r in enumerate(self.model.rows):
            for pin_name, col in cols.items():
                txt = (r.pins[col - 2] or "").strip()
                if txt == "":
                    # Empty allowed (NC)
                    continue
                try:
                    val = int(txt, 10)
                except Exception:
                    msg = f"Row {r_idx + 1}, Pin {pin_name}: not an integer ({txt!r})"
                    errors.append(msg)
                    self.model.mark_invalid(r_idx, col, msg)
                    continue
                if val < 1:
                    msg = f"Row {r_idx + 1}, Pin {pin_name}: must be ≥ 1 (got {val})"
                    errors.append(msg)
                    self.model.mark_invalid(r_idx, col, msg)
                    continue
                if val > max_pin:
                    msg = f"Row {r_idx + 1}, Pin {pin_name}: exceeds total pins ({val} > {max_pin})"
                    errors.append(msg)
                    self.model.mark_invalid(r_idx, col, msg)
                    continue
        return (len(errors) == 0), errors

    # ----------------------------------------------------------- public API
    def load_device(self, device: ComplexDevice) -> None:
        self.device_id = device.id
        self.pn_edit.setText(device.pn)
        # Aliases
        self.alt_pn_edit.clear()
        self.alt_pn_list.clear()
        aliases = list(getattr(device, "aliases", []) or [])
        if not aliases and getattr(device, "alt_pn", ""):
            aliases = [str(device.alt_pn).strip()]
        seen = set()
        for a in aliases:
            s = str(a).strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            self.alt_pn_list.addItem(s)
        self.pin_spin.setValue(device.pin_count)
        for sc in device.subcomponents:
            row = self.model.add_row()
            self.model.rows[row].macro_id = self._macro_id_by_name(sc.macro.name)
            # Load existing pins as strings (0 -> empty)
            pins = list(sc.pins) + [0, 0, 0, 0]
            pins = pins[:4]
            self.model.rows[row].pins = [("" if (p is None or int(p) <= 0) else str(int(p))) for p in pins]
            self.model.rows[row].params = dict(sc.macro.params)
        self.model.dataChanged.emit(QtCore.QModelIndex(), QtCore.QModelIndex())
        self._update_state()

    def build_device(self) -> ComplexDevice:
        """Return a ComplexDevice reflecting the UI (after Save validation)."""
        self._force_commit_table_editor()
        dev = ComplexDevice(0, [], MacroInstance("", {}))
        dev.pn = self.pn_edit.text().strip()
        # Collect aliases from list (+ include any pending text not added yet)
        aliases = [self.alt_pn_list.item(i).text().strip() for i in range(self.alt_pn_list.count())]
        pending = self.alt_pn_edit.text().strip()
        if pending:
            aliases.append(pending)
        canon = []
        seen = set()
        for a in aliases:
            s = str(a).strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            canon.append(s)
        dev.aliases = canon
        dev.alt_pn = canon[0] if canon else ""
        dev.pin_count = int(self.pin_spin.value())
        dev.id = self.device_id
        dev.subcomponents = self.model.to_subcomponents()
        return dev

    # ------------------------------ aliases helpers
    def _on_alias_add(self) -> None:  # pragma: no cover - UI wiring
        s = self.alt_pn_edit.text().strip()
        if not s:
            return
        existing = {self.alt_pn_list.item(i).text().strip().lower() for i in range(self.alt_pn_list.count())}
        if s.lower() in existing:
            self.alt_pn_edit.clear()
            return
        self.alt_pn_list.addItem(s)
        self.alt_pn_edit.clear()
        self._update_state()

    def _on_alias_remove(self) -> None:  # pragma: no cover - UI wiring
        for item in self.alt_pn_list.selectedItems():
            row = self.alt_pn_list.row(item)
            self.alt_pn_list.takeItem(row)
        self._update_state()

    # -------------------------------------------------------------- accept logic
    def _on_accept(self) -> None:
        self._force_commit_table_editor()
        if not self.pn_edit.text().strip():
            QtWidgets.QApplication.beep()
            QMessageBox.warning(self, "Missing PN", "Please provide a PN before saving.")
            return

        ok, errors = self._validate_and_mark_pins()
        if not ok:
            QtWidgets.QApplication.beep()
            text = "Please fix the highlighted pin fields.\n\n" + "\n".join(errors[:15])
            if len(errors) > 15:
                text += f"\n… and {len(errors) - 15} more."
            QMessageBox.warning(self, "Invalid pins", text)
            return

        self.accept()

    def _macro_id_by_name(self, name: str) -> int | None:
        for mid, m in self.macro_map.items():
            if m.name == name:
                return mid
        return None
