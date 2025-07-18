# ruff: noqa: E402

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
    mdb_file = Path.home() / "Documents" / "ComplexBuilder" / "main_db.mdb"
    run_gui(mdb_file)
