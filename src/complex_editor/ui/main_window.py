from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Dict

from PyQt6 import QtWidgets

from ..core.app_context import AppContext
from ..db.mdb_api import MDB
from ..db import discover_macro_map
from .complex_list import ComplexListPanel
from .complex_editor import ComplexEditor
from . import buffer_loader, buffer_persistence
from .new_complex_wizard import NewComplexWizard
from ..io.buffer_loader import WizardPrefill


class MainWindow(QtWidgets.QMainWindow):
    """Main window showing the complex list on the left and editor on the right."""

    def __init__(
        self,
        mdb_path: Optional[Path] = None,
        parent: Any | None = None,
        buffer_path: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)

        if mdb_path is None and buffer_path is None:
            raise ValueError("mdb_path or buffer_path required")

        self.ctx = AppContext()
        self.db: MDB | None = None
        self.buffer_path: Path | None = buffer_path
        self.macro_map: Dict[int, Any] = {}

        self.list_panel = ComplexListPanel()
        self.list = self.list_panel.view  # backward compatibility

        if mdb_path is not None:
            self.db = self.ctx.open_main_db(mdb_path)

        if self.db is not None:
            self.editor = ComplexEditor(db=self.db)
            self.editor.show()  # ensure visible for headless tests

            splitter = QtWidgets.QSplitter()
            splitter.addWidget(self.list_panel)
            splitter.addWidget(self.editor)
            self.setCentralWidget(splitter)

            self.list_panel.complexSelected.connect(self.editor.load_complex)
            self.list_panel.newComplexRequested.connect(self.editor.reset_to_new)
            self.editor.saved.connect(self.list_panel.refresh_and_select)

            try:
                cur = self.db._cur()
                macro_map = discover_macro_map(cur) or {}
                self.list_panel.load_rows(cur, macro_map)
                self.editor.set_macro_map(macro_map)
                self.list_panel.set_refresh_callback(
                    lambda: self.list_panel.load_rows(self.db._cur(), macro_map)
                )
            except Exception:
                pass
        else:
            # Buffer mode – list only, constructors opened on demand.
            self.setCentralWidget(self.list_panel)
            self.macro_map = discover_macro_map(None) or {}
            self._load_buffer_models()
            self.list_panel.editRequested.connect(self._edit_buffer_complex)
            self.list_panel.newComplexRequested.connect(self._new_buffer_complex)

        self.show()  # ensure visibility in headless tests

    # ----- buffer helpers -------------------------------------------------
    def _load_buffer_models(self) -> None:
        if not self.buffer_path:
            return
        models = buffer_loader.load_editor_complexes_from_buffer(self.buffer_path)
        self.list_panel.load_buffer_models(models, self.macro_map)

    def _prefill_from_model(self, model) -> WizardPrefill:
        rev_map = {m.name: mid for mid, m in self.macro_map.items()}
        subs: list[dict[str, Any]] = []
        for em in getattr(model, "subcomponents", []) or []:
            macro_name = getattr(em, "selected_macro", None) or getattr(em, "name", "")
            pins = [int(v) for k, v in sorted(em.pins.items())]
            subs.append(
                {
                    "macro_name": macro_name,
                    "id_function": rev_map.get(macro_name),
                    "pins": pins,
                }
            )
        prefill = WizardPrefill(model.name, subs)
        setattr(prefill, "pin_count", len(getattr(model, "pins", []) or []))
        return prefill

    def _serialize_device(self, dev, comp_id: int) -> dict:
        sub_raw = []
        for sc in getattr(dev, "subcomponents", []) or []:
            pins = {letter: str(pin) for letter, pin in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", sc.pins)}
            sub_raw.append(
                {
                    "id_function": getattr(getattr(sc, "macro", None), "id_function", None),
                    "function_name": getattr(getattr(sc, "macro", None), "name", ""),
                    "value": getattr(sc, "value", None),
                    "force_bits": getattr(sc, "force_bits", None),
                    "pins": pins,
                }
            )
        pins_list = [str(p) for p in getattr(dev, "pins", [])]
        return {
            "id": comp_id,
            "name": getattr(dev, "name", ""),
            "total_pins": len(pins_list),
            "pins": pins_list,
            "subcomponents": sub_raw,
        }

    def _save_device_to_buffer(self, dev, comp_id: int | None) -> int:
        if not self.buffer_path:
            return 0
        data = buffer_persistence.load_buffer(self.buffer_path)
        if comp_id is None or comp_id == 0:
            comp_id = max([int(c.get("id", 0)) for c in data] or [0]) + 1
            data.append(self._serialize_device(dev, comp_id))
        else:
            for idx, cx in enumerate(data):
                if int(cx.get("id", 0)) == comp_id:
                    data[idx] = self._serialize_device(dev, comp_id)
                    break
            else:
                data.append(self._serialize_device(dev, comp_id))
        buffer_persistence.save_buffer(self.buffer_path, data)
        self._load_buffer_models()
        self.list_panel.refresh_and_select(comp_id)
        return comp_id

    def _edit_buffer_complex(self, model) -> None:
        prefill = self._prefill_from_model(model)
        wiz = NewComplexWizard.from_existing(prefill, model.id, self)
        if wiz.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            dev = wiz.to_complex_device()
            self._save_device_to_buffer(dev, model.id)

    def _new_buffer_complex(self) -> None:
        wiz = NewComplexWizard(self.macro_map, self)
        if wiz.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            dev = wiz.to_complex_device()
            self._save_device_to_buffer(dev, None)


def run_gui(mdb_file: Path | None = None, buffer_path: Path | None = None) -> None:
    import sys
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(mdb_path=mdb_file, buffer_path=buffer_path)
    win.resize(1100, 600)
    win.show()
    sys.exit(app.exec())


__all__ = ["MainWindow", "run_gui"]

