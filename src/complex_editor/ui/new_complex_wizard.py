from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from ..domain import MacroDef, MacroInstance, SubComponent, ComplexDevice


class BasicsPage(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QFormLayout(self)
        self.pin_spin = QtWidgets.QSpinBox()
        self.pin_spin.setRange(2, 256)
        self.pin_spin.setValue(2)
        self.pn_edit = QtWidgets.QLineEdit()
        self.alt_edit = QtWidgets.QLineEdit()
        layout.addRow("Pin-count", self.pin_spin)
        layout.addRow("Primary PN", self.pn_edit)
        layout.addRow("Alternate PNs", self.alt_edit)


class SubCompListPage(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)
        btns = QtWidgets.QVBoxLayout()
        self.add_btn = QtWidgets.QPushButton("Add")
        self.dup_btn = QtWidgets.QPushButton("Duplicate")
        self.del_btn = QtWidgets.QPushButton("Delete")
        btns.addWidget(self.add_btn)
        btns.addWidget(self.dup_btn)
        btns.addWidget(self.del_btn)
        btns.addStretch()
        layout.addLayout(btns)


# ────────── MacroPinsPage ──────────────────────────────────────────
class MacroPinsPage(QtWidgets.QWidget):
    """Pick a macro and map its logical pins to physical pads."""

    def __init__(self, macro_map: dict[int, MacroDef]) -> None:
        super().__init__()
        self.macro_map = macro_map or {}

        vbox = QtWidgets.QVBoxLayout(self)

        # ── macro selector ──────────────────────────────────────────────
        self.macro_combo = QtWidgets.QComboBox()
        if not self.macro_map:                      # nothing loaded yet
            self.macro_combo.addItem("⚠  No macros loaded")
            self.macro_combo.setEnabled(False)
        else:
            for id_func, macro in sorted(self.macro_map.items()):
                self.macro_combo.addItem(macro.name, id_func)
            self.macro_combo.setCurrentIndex(0)
        vbox.addWidget(self.macro_combo)

        # ── ordered-pin table ───────────────────────────────────────────
        self.pin_table = QtWidgets.QTableWidget(0, 2, self)
        self.pin_table.setHorizontalHeaderLabels(["Pin", "Order #"])
        hdr = self.pin_table.horizontalHeader()
        hdr.setSectionResizeMode(                 # PyQt-6 style enum
            0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        vbox.addWidget(self.pin_table)

        # watch edits so the wizard can enable / disable “Next ▶”
        self.pin_table.itemChanged.connect(self._on_table_change)


    # ------------------------------------------------------------------
    # public helpers used by the wizard
    # ------------------------------------------------------------------
    def set_pin_count(self, total_pins: int, used: set[int]) -> None:
        """
        Fill the table with pin numbers 1 … total_pins and create a
        `QSpinBox` in the *Order #* column so the user can decide the
        mapping.  Already-used physical pads are disabled.
        """
        self.pin_table.blockSignals(True)
        self.pin_table.setRowCount(total_pins)

        for row in range(total_pins):
            pin_no = row + 1

            # column 0 – read-only pin number
            num_item = QtWidgets.QTableWidgetItem(str(pin_no))
            num_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.pin_table.setItem(row, 0, num_item)

            # column 1 – editable order spinner
            spin = QtWidgets.QSpinBox()
            spin.setRange(0, total_pins)
            spin.setValue(0)
            if pin_no in used:                    # pad already mapped elsewhere
                spin.setEnabled(False)
            self.pin_table.setCellWidget(row, 1, spin)

        self.pin_table.blockSignals(False)
        self._on_table_change()                   # update validity immediately


    def checked_pins(self) -> list[int]:
        """
        Return physical pin numbers **ordered by** the number the user entered.
        Only entries >0 are taken into account.
        """
        mapping = {}
        for row in range(self.pin_table.rowCount()):
            spin: QtWidgets.QSpinBox = self.pin_table.cellWidget(row, 1)
            order = spin.value()
            if order:
                mapping[order] = row + 1      # order → real pin
        # Ascending order list of real pins
        return [mapping[i] for i in sorted(mapping)]

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _on_table_change(self) -> None:
        """
        Mark duplicate order numbers in red and expose a boolean
        flag (`self.parent().parent()._mapping_ok`) so the wizard
        can enable / disable its *Next* button.
        """
        seen: dict[int, int] = {}         # order → row
        duplicates: set[int] = set()

        for row in range(self.pin_table.rowCount()):
            spin: QtWidgets.QSpinBox = self.pin_table.cellWidget(row, 1)
            val = spin.value()
            spin.setStyleSheet("")        # clear previous colour

            if val == 0:
                continue                  # 0 means “unused”
            if val in seen:
                duplicates.update({row, seen[val]})
            seen[val] = row

        # Colour duplicates red
        for row in duplicates:
            self.pin_table.cellWidget(row, 1).setStyleSheet("background:#FFCCCC;")

        mapping_ok = bool(seen) and not duplicates
        wiz = self.parentWidget().parent()        # the QDialog
        wiz._mapping_ok = mapping_ok
        wiz._update_nav()


class ParamPage(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.form = QtWidgets.QFormLayout()
        layout.addLayout(self.form)
        self.copy_btn = QtWidgets.QPushButton("Copy Params From...")
        layout.addWidget(self.copy_btn)

    def build_widgets(self, macro: MacroDef, params: dict[str, str]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.widgets: dict[str, QtWidgets.QWidget] = {}
        self.required: set[str] = {p.name for p in macro.params if p.default is None}
        for p in macro.params:
            label = QtWidgets.QLabel(p.name)
            if p.type == "INT":
                w = QtWidgets.QSpinBox()
                if p.min is not None:
                    w.setMinimum(int(p.min))
                if p.max is not None:
                    w.setMaximum(int(p.max))
            elif p.type == "FLOAT":
                w = QtWidgets.QDoubleSpinBox()
                if p.min is not None:
                    w.setMinimum(float(p.min))
                if p.max is not None:
                    w.setMaximum(float(p.max))
            elif p.type == "BOOL":
                w = QtWidgets.QCheckBox()
            elif p.type == "ENUM":
                w = QtWidgets.QComboBox()
                choices = (p.default or p.min or "").split(";")
                if len(choices) > 1:
                    w.addItems(choices)
            else:
                w = QtWidgets.QLineEdit()
            self.widgets[p.name] = w
            self.form.addRow(label, w)
            val = params.get(p.name, p.default)
            if isinstance(w, QtWidgets.QSpinBox) and val is not None:
                w.setValue(int(val))
            elif isinstance(w, QtWidgets.QDoubleSpinBox) and val is not None:
                w.setValue(float(val))
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(str(val).lower() in ("1", "true", "yes"))
            elif isinstance(w, QtWidgets.QComboBox) and val is not None:
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
            elif isinstance(w, QtWidgets.QLineEdit) and val is not None:
                w.setText(str(val))

    def param_values(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, w in self.widgets.items():
            if isinstance(w, QtWidgets.QSpinBox):
                result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QCheckBox):
                result[name] = "1" if w.isChecked() else "0"
            elif isinstance(w, QtWidgets.QComboBox):
                result[name] = w.currentText()
            elif isinstance(w, QtWidgets.QLineEdit):
                result[name] = w.text()
        return result

    def required_filled(self) -> bool:
        for name in self.required:
            w = self.widgets.get(name)
            if isinstance(w, QtWidgets.QLineEdit) and not w.text().strip():
                return False
            if isinstance(w, QtWidgets.QComboBox) and not w.currentText():
                return False
        return True


class CopyParamsDialog(QtWidgets.QDialog):
    def __init__(self, names: list[str], parent=None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        self.list.addItems(names)
        layout.addWidget(self.list)
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(btn_box)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

    def selected_row(self) -> int:
        return self.list.currentRow()


class ReviewPage(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Macro", "Pins", "Params"])
        layout.addWidget(self.table)
        self.save_btn = QtWidgets.QPushButton("Save")
        layout.addWidget(self.save_btn)

    def populate(self, comps: list[SubComponent]) -> None:
        self.table.setRowCount(len(comps))
        for i, sc in enumerate(comps):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(sc.macro.name))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(
                ",".join(str(p) for p in sc.pins)))
            keys = ",".join(sorted(sc.macro.params.keys()))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(keys))


class NewComplexWizard(QtWidgets.QDialog):
    def __init__(self, macro_map: dict[int, MacroDef], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Complex")
        self.resize(600, 500)
        self.macro_map = macro_map
        self.sub_components: list[SubComponent] = []
        self.current_index: Optional[int] = None

        layout = QtWidgets.QVBoxLayout(self)
        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack)
        nav = QtWidgets.QHBoxLayout()
        self.back_btn = QtWidgets.QPushButton("Back")
        self.next_btn = QtWidgets.QPushButton("Next")
        nav.addWidget(self.back_btn)
        nav.addStretch()
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)

        self.basics_page = BasicsPage()
        self.list_page = SubCompListPage()
        self.macro_page = MacroPinsPage(macro_map)
        self.param_page = ParamPage()
        self.review_page = ReviewPage()

        self.stack.addWidget(self.basics_page)
        self.stack.addWidget(self.list_page)
        self.stack.addWidget(self.macro_page)
        self.stack.addWidget(self.param_page)
        self.stack.addWidget(self.review_page)

        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)
        self.list_page.add_btn.clicked.connect(self._add_sub)
        self.list_page.dup_btn.clicked.connect(self._dup_sub)
        self.list_page.del_btn.clicked.connect(self._del_sub)
        self.param_page.copy_btn.clicked.connect(self._copy_params)
        self.review_page.save_btn.clicked.connect(self._finish)
        self._mapping_ok = False     # ② flag updated by pin-table

        self._update_nav()

    # ------------------------------------------------------------------ actions
    def _add_sub(self) -> None:
        sc = SubComponent(MacroInstance("", {}), [])
        self.sub_components.append(sc)
        self.list_page.list.addItem("<new>")
        self.current_index = len(self.sub_components) - 1
        self._open_macro_page()

    def _dup_sub(self) -> None:
        row = self.list_page.list.currentRow()
        if row < 0:
            return
        orig = self.sub_components[row]
        new_sc = SubComponent(
            MacroInstance(orig.macro.name, orig.macro.params.copy()), []
        )
        self.sub_components.append(new_sc)
        self.list_page.list.addItem("<dup>")
        self.current_index = len(self.sub_components) - 1
        self._open_macro_page()

    def _del_sub(self) -> None:
        row = self.list_page.list.currentRow()
        if row < 0:
            return
        self.sub_components.pop(row)
        self.list_page.list.takeItem(row)

    def _open_macro_page(self) -> None:
        used = {p for i, sc in enumerate(self.sub_components)
                if i != self.current_index for p in sc.pins}
        count = self.basics_page.pin_spin.value()
        self.macro_page.set_pin_count(count, used)
        self.stack.setCurrentWidget(self.macro_page)
        self._update_nav()

    def _open_param_page(self) -> None:
        index = self.macro_page.macro_combo.currentData()
        macro = self.macro_map.get(int(index)) if index is not None else None
        if not macro:
            macro = list(self.macro_map.values())[0]
        pins = self.macro_page.checked_pins()
        sc = self.sub_components[self.current_index]
        sc.macro.name = macro.name
        sc.pins = pins
        self.param_page.build_widgets(macro, sc.macro.params)
        self.stack.setCurrentWidget(self.param_page)
        self._update_nav()

    def _save_params(self) -> None:
        sc = self.sub_components[self.current_index]
        sc.macro.params = self.param_page.param_values()
        text = f"{sc.macro.name} ({','.join(str(p) for p in sc.pins)})"
        self.list_page.list.item(self.current_index).setText(text)

    def _copy_params(self) -> None:
        names = [sc.macro.name for i, sc in enumerate(self.sub_components)
                 if i != self.current_index]
        if not names:
            return
        dlg = CopyParamsDialog(names, self)
        self.param_page._copy_dialog = dlg
        def apply_copy():
            sel = dlg.selected_row()
            if sel >= 0:
                if sel >= self.current_index:
                    sel += 1
                source = self.sub_components[sel]
                target = self.sub_components[self.current_index]
                target.macro.params = source.macro.params.copy()
                macro = next((m for m in self.macro_map.values() if m.name == target.macro.name), None)
                if macro:
                    self.param_page.build_widgets(macro, target.macro.params)
        dlg.accepted.connect(apply_copy)
        dlg.open()

    def _back(self) -> None:
        page = self.stack.currentWidget()
        if page is self.list_page:
            self.stack.setCurrentWidget(self.basics_page)
        elif page is self.macro_page:
            self.stack.setCurrentWidget(self.list_page)
        elif page is self.param_page:
            self.stack.setCurrentWidget(self.macro_page)
        elif page is self.review_page:
            self.stack.setCurrentWidget(self.list_page)
        self._update_nav()

    def _next(self) -> None:
        page = self.stack.currentWidget()
        if page is self.basics_page:
            self.stack.setCurrentWidget(self.list_page)
        elif page is self.macro_page:
            self._open_param_page()
        elif page is self.param_page:
            self._save_params()
            self.stack.setCurrentWidget(self.list_page)
        elif page is self.list_page:
            self.review_page.populate(self.sub_components)
            self.stack.setCurrentWidget(self.review_page)
        self._update_nav()

    def _finish(self) -> None:
        if self.stack.currentWidget() is self.param_page:
            self._save_params()
        pin_count = self.basics_page.pin_spin.value()
        pins = [str(i) for i in range(1, pin_count + 1)]
        self.result_device = ComplexDevice(0, pins, MacroInstance("", {}))
        self.accept()

    def _update_nav(self) -> None:
        """Enable/disable Back & Next based on current page content."""
        page = self.stack.currentWidget()
        self.back_btn.setEnabled(page is not self.basics_page or page is self.review_page)

        if page is self.macro_page:
            # macro must be chosen and mapping valid
            self.next_btn.setEnabled(self._mapping_ok)
        elif page is self.param_page:
            self.next_btn.setEnabled(self.param_page.required_filled())
        elif page is self.review_page:
            self.next_btn.setEnabled(False)
            self.review_page.save_btn.setText("Finish")
        else:
            self.next_btn.setEnabled(True)
            self.review_page.save_btn.setText("Save")

