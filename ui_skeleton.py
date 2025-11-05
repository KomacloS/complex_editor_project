# ruff: noqa: E402

"""Entry point for launching the Tkinter complex editor demo."""

from __future__ import annotations

import argparse
import pathlib
import sys
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:  # pragma: no cover - optional legacy bootstrap
    from complex_editor.bootstrap import add_repo_src_to_syspath
except ModuleNotFoundError:  # pragma: no cover - legacy path missing
    add_repo_src_to_syspath = None  # type: ignore[assignment]
else:
    add_repo_src_to_syspath()

try:  # pragma: no cover - legacy logging config may not be present
    import complex_editor.logging_cfg  # noqa: F401
except ModuleNotFoundError:
    pass

from complex_editor_app.ui.main import main as run_tk_demo


def _resolve_path(path: Path | None) -> Path | None:
    """Normalize command-line paths to absolute filesystem locations."""

    if path is None:
        return None
    return path.expanduser().resolve()


def main(argv: list[str] | None = None) -> None:
    """Parse CLI options and launch the Tkinter demo UI."""

    parser = argparse.ArgumentParser(description="Launch the Tkinter Complex Editor demo UI.")
    parser.add_argument(
        "--buffer",
        type=Path,
        default=None,
        help="Optional JSON buffer file to load and persist complexes.",
    )
    parser.add_argument(
        "--load-buffer",
        type=Path,
        default=None,
        help="Deprecated alias for --buffer; retained for backwards compatibility.",
    )
    args = parser.parse_args(argv)

    buffer_path = args.load_buffer or args.buffer
    if args.load_buffer and not args.buffer:
        print("[ui_skeleton] --load-buffer is deprecated; use --buffer instead.", file=sys.stderr)

    run_tk_demo(buffer_path=_resolve_path(buffer_path))


if __name__ == "__main__":
    main()
