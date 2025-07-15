# ruff: noqa: E402
from complex_editor.bootstrap import add_repo_src_to_syspath

add_repo_src_to_syspath()

from complex_editor.ui.main_window import run_gui

if __name__ == "__main__":
    run_gui()
