from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
import fitz  # PyMuPDF


class DatasheetViewer(QtWidgets.QWidget):
    """Very small PDF/PNG viewer using PyMuPDF."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel("No datasheet loaded")
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

    def load_file(self, path: str) -> None:
        doc = fitz.open(path)
        if not doc.page_count:
            return
        page = doc.load_page(0)
        pix = page.get_pixmap()
        fmt = "PNG"
        data = pix.tobytes(fmt)
        image = QtGui.QImage.fromData(data, fmt)
        self.label.setPixmap(QtGui.QPixmap.fromImage(image))
