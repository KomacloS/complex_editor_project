from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ..domain import ComplexDevice, MacroInstance, macro_to_xml
from ..services import insert_complex
from ..db import make_backup


class ComplexEditor(QtWidgets.QWidget):
    """Form for editing/creating a complex device."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.pin_edits = [QtWidgets.QLineEdit() for _ in range(4)]
        validator = QtGui.QRegularExpressionValidator(QtCore.QRegularExpression("[A-Za-z0-9]+"))
        for i, edit in enumerate(self.pin_edits):
            edit.setValidator(validator)
            form.addRow(f"Pin {chr(65 + i)}", edit)
        self.macro_combo = QtWidgets.QComboBox()
        form.addRow("Macro", self.macro_combo)
        layout.addLayout(form)
        self.param_form = QtWidgets.QFormLayout()
        layout.addLayout(self.param_form)
        self.xml_preview = QtWidgets.QPlainTextEdit()
        self.xml_preview.setReadOnly(True)
        layout.addWidget(self.xml_preview)
        self.save_btn = QtWidgets.QPushButton("Save")
        layout.addWidget(self.save_btn)
