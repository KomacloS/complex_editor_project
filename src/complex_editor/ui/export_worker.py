from __future__ import annotations

import traceback
from pathlib import Path
from typing import Sequence

from PyQt6 import QtCore

from complex_editor.db.pn_exporter import (
    ExportCanceled,
    ExportOptions,
    ExportReport,
    SubsetExportError,
    export_pn_to_mdb,
)


class ExportPnWorker(QtCore.QObject):
    """Thin QObject wrapper around :func:`export_pn_to_mdb` for use with QThread."""

    progress = QtCore.pyqtSignal(str, int, int)
    finished = QtCore.pyqtSignal(ExportReport)
    failed = QtCore.pyqtSignal(str, str)
    canceled = QtCore.pyqtSignal()

    def __init__(
        self,
        source_path: Path,
        template_path: Path,
        target_path: Path,
        pn_names: Sequence[str],
        options: ExportOptions,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_path = Path(source_path)
        self._template_path = Path(template_path)
        self._target_path = Path(target_path)
        self._pn_names = tuple(pn_names)
        self._options = options
        self._cancel_requested = False

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            report = export_pn_to_mdb(
                self._source_path,
                self._template_path,
                self._target_path,
                self._pn_names,
                options=self._options,
                progress_cb=self._on_progress,
                cancel_cb=self._is_canceled,
            )
        except ExportCanceled:
            self.canceled.emit()
        except SubsetExportError as exc:  # pragma: no cover - surfaced to UI
            payload = dict(getattr(exc, "payload", {}))
            detail_lines = [f"{key}: {value}" for key, value in payload.items() if value is not None]
            detail = "\n".join(detail_lines) if detail_lines else str(exc)
            self.failed.emit(exc.reason, detail)
        except Exception as exc:  # pragma: no cover - surfaced to UI
            detail = traceback.format_exc()
            self.failed.emit(str(exc), detail)
        else:
            self.finished.emit(report)

    @QtCore.pyqtSlot()
    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _is_canceled(self) -> bool:
        return self._cancel_requested

    def _on_progress(self, message: str, current: int, total: int) -> None:
        self.progress.emit(message, current, total)


__all__ = ["ExportPnWorker"]
