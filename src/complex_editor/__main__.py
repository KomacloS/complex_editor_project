from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    PACKAGE_ROOT = Path(__file__).resolve().parent
    sys.path.insert(0, str(PACKAGE_ROOT.parent))
    __package__ = "complex_editor"

    import complex_editor.logging_cfg  # noqa: F401
    from complex_editor import __version__  # type: ignore
    from complex_editor.config.loader import CONFIG_ENV_VAR, load_config  # type: ignore
else:
    from . import logging_cfg  # noqa: F401
    from . import __version__
    from .config.loader import CONFIG_ENV_VAR, load_config


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Complex Editor launcher")
    parser.add_argument("--start-bridge", action="store_true", help="Ensure the HTTP bridge is running")
    parser.add_argument("--shutdown-bridge", action="store_true", help="Shutdown a running HTTP bridge")
    parser.add_argument("--host", type=str, default=None, help="Override bridge host for this run")
    parser.add_argument("--port", type=int, default=None, help="Override bridge port for this run")
    parser.add_argument("--token", type=str, default=None, help="Override bridge bearer token for this run")
    parser.add_argument("--config", type=Path, default=None, help="Path to configuration file")
    parser.add_argument("--buffer", type=Path, default=None, help="Open the GUI against a buffer JSON file")
    parser.add_argument("--load-buffer", type=Path, default=None, help="Preview a buffer JSON in the wizard")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--run-bridge-server", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _forward_bridge_args(args: argparse.Namespace) -> list[str]:
    forwarded: list[str] = []
    if args.config is not None:
        forwarded.extend(["--config", str(Path(args.config).expanduser())])
    if args.host is not None:
        forwarded.extend(["--host", args.host])
    if args.port is not None:
        forwarded.extend(["--port", str(int(args.port))])
    if args.token is not None:
        forwarded.extend(["--token", args.token])
    if args.start_bridge:
        forwarded.append("--start-bridge")
    if args.shutdown_bridge:
        forwarded.append("--shutdown-bridge")
    return forwarded


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.run_bridge_server:
        if args.config is not None:
            os.environ[CONFIG_ENV_VAR] = str(Path(args.config).expanduser())

        cfg = load_config()
        bridge_cfg = cfg.bridge
        if args.host is not None:
            bridge_cfg.host = args.host
        if args.port is not None:
            bridge_cfg.port = int(args.port)
        if args.token is not None:
            bridge_cfg.auth_token = args.token
        bridge_cfg.base_url = f"http://{bridge_cfg.host}:{bridge_cfg.port}"
        from ce_bridge_service import run as bridge_run

        return bridge_run.serve_from_config(cfg)

    if args.start_bridge and args.shutdown_bridge:
        raise SystemExit("--start-bridge and --shutdown-bridge cannot be used together")

    if args.port is not None and (args.port <= 0 or args.port > 65535):
        raise SystemExit("Bridge port must be between 1 and 65535")

    if args.config is not None:
        os.environ[CONFIG_ENV_VAR] = str(Path(args.config).expanduser())

    if args.start_bridge or args.shutdown_bridge:
        # Load configuration to surface validation errors early before delegating.
        load_config()
        from ce_bridge_service import run as bridge_run

        forwarded = _forward_bridge_args(args)
        return bridge_run.main(forwarded)

    if args.load_buffer is not None and args.buffer is not None:
        raise SystemExit("--buffer and --load-buffer are mutually exclusive")

    if args.load_buffer is not None:
        from PyQt6 import QtWidgets  # type: ignore
        from .io.buffer_loader import load_complex_from_buffer_json, to_wizard_prefill
        from .ui.new_complex_wizard import NewComplexWizard

        app = QtWidgets.QApplication(sys.argv)
        buf = load_complex_from_buffer_json(args.load_buffer)
        prefill = to_wizard_prefill(buf, lambda name: None, lambda m: m)
        wiz = NewComplexWizard.from_wizard_prefill(prefill)
        wiz.show()
        sys.exit(app.exec())

    from .ui.main_window import run_gui

    if args.buffer is not None:
        run_gui(mdb_file=None, buffer_path=args.buffer)
    else:
        run_gui()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
