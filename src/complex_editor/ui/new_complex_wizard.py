from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets

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


class MacroPinsPage(QtWidgets.QWidget):
    def __init__(self, macro_map: dict[int, MacroDef]) -> None:
        super().__init__()
        self.macro_map = macro_map
        layout = QtWidgets.QVBoxLayout(self)
        self.macro_combo = QtWidgets.QComboBox()
        for id_func, macro in sorted(macro_map.items()):
            self.macro_combo.addItem(macro.name, id_func)
        layout.addWidget(self.macro_combo)
        self.pin_list = QtWidgets.QListWidget()
        layout.addWidget(self.pin_list)

    def set_pin_count(self, count: int, used: set[int]) -> None:
        self.pin_list.clear()
        for i in range(1, count + 1):
            item = QtWidgets.QListWidgetItem(str(i))
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            if i in used:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.pin_list.addItem(item)

    def checked_pins(self) -> list[int]:
        pins: list[int] = []
        for i in range(self.pin_list.count()):
            it = self.pin_list.item(i)
            if it.checkState() == QtCore.Qt.CheckState.Checked:
                pins.append(i + 1)
        return pins


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
        page = self.stack.currentWidget()
        self.back_btn.setEnabled(page is not self.basics_page)
        if page is self.review_page:
            self.next_btn.setEnabled(False)
        else:
            self.next_btn.setEnabled(True)

