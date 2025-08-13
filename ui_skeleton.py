# ruff: noqa: E402

import argparse
import logging
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
    args = parser.parse_args()

    log = logging.getLogger("ui_skeleton")

    if args.buffer is not None:
        log.info("Starting GUI in buffer mode: %s", args.buffer)
        run_gui(mdb_file=None, buffer_path=args.buffer)
    else:
        mdb_file = Path.home() / "Documents" / "ComplexBuilder" / "main_db.mdb"
        log.info("Starting GUI in DB mode: %s", mdb_file)
        run_gui(mdb_file)
