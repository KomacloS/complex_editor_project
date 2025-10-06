# ruff: noqa: E402

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from complex_editor.bootstrap import add_repo_src_to_syspath

add_repo_src_to_syspath()
import complex_editor.logging_cfg  # noqa: F401

from pathlib import Path
from complex_editor.ui.main_window import run_gui

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--buffer", type=Path, default=None)
    parser.add_argument("--load-buffer", type=Path, default=None)
    args = parser.parse_args()

    if args.load_buffer is not None:
        from PyQt6 import QtWidgets  # noqa: E402
        from complex_editor.io.buffer_loader import (  # noqa: E402
            load_complex_from_buffer_json,
            to_wizard_prefill,
        )
        from complex_editor.ui.new_complex_wizard import (  # noqa: E402
            NewComplexWizard,
        )

        app = QtWidgets.QApplication(sys.argv)
        buf = load_complex_from_buffer_json(args.load_buffer)
        prefill = to_wizard_prefill(buf, lambda name: None, lambda m: m)
        wiz = NewComplexWizard.from_wizard_prefill(prefill)
        wiz.show()
        sys.exit(app.exec())
    elif args.buffer is not None:
        run_gui(mdb_file=None, buffer_path=args.buffer)
    else:
        run_gui()
