from __future__ import annotations

from typing import Dict, Iterable, List

from PyQt6 import QtWidgets


class PinAssignmentDialog(QtWidgets.QDialog):
    """Dialog to map macro pins to PCB pads with duplicate prevention."""

    def __init__(
        self,
        macro_pins: Iterable[str],
        pcb_pads: Iterable[str],
        mapping: Dict[str, str] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Pins")
        self._pins: List[str] = list(macro_pins)
        self._pads = [""] + list(pcb_pads)
        self._combos: List[QtWidgets.QComboBox] = []

        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(len(self._pins), 2)
        self.table.setHorizontalHeaderLabels(["Macro Pin", "PCB Pad"])
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        for r, pin in enumerate(self._pins):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(pin))
            combo = QtWidgets.QComboBox()
            combo.addItems(self._pads)
            combo.currentIndexChanged.connect(self._validate)
            self.table.setCellWidget(r, 1, combo)
            self._combos.append(combo)

        if mapping:
            for pin, pad in mapping.items():
                if pin in self._pins:
                    idx = self._pads.index(str(pad)) if str(pad) in self._pads else 0
                    self._combos[self._pins.index(pin)].setCurrentIndex(idx)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setStyleSheet("color:red")
        layout.addWidget(self.error_label)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._validate()

    # ------------------------------------------------------------------ utils
    def _mapping(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for pin, combo in zip(self._pins, self._combos):
            text = combo.currentText().strip()
            if text:
                result[pin] = text
        return result

    def _validate(self) -> None:
        mapping = self._mapping()
        pads = list(mapping.values())
        dup = len(pads) != len(set(pads))
        ok_btn = self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if dup:
            self.error_label.setText("Duplicate pad assignments")
            ok_btn.setEnabled(False)
        else:
            self.error_label.clear()
            ok_btn.setEnabled(len(mapping) == len(self._pins))

    def _on_accept(self) -> None:
        if not self.buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        ).isEnabled():
            return
        self._result = self._mapping()
        self.accept()

    # ------------------------------------------------------------------ API
    def mapping(self) -> Dict[str, str]:
        return getattr(self, "_result", {})
