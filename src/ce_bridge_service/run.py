from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from complex_editor.config.loader import CONFIG_ENV_VAR, load_config

from .app import create_app


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Complex Editor bridge service")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to complex_editor.yml (defaults to standard loader search).",
    )
    parser.add_argument("--host", type=str, default=None, help="Override bridge host")
    parser.add_argument("--port", type=int, default=None, help="Override bridge port")
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Override bearer token (warning: prints in plain text)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.config is not None:
        os.environ[CONFIG_ENV_VAR] = str(Path(args.config).expanduser())

    cfg = load_config()
    bridge_cfg = cfg.bridge

    if args.host:
        bridge_cfg.host = args.host
    if args.port:
        bridge_cfg.port = int(args.port)
        bridge_cfg.base_url = f"http://{bridge_cfg.host}:{bridge_cfg.port}"
    if args.token is not None:
        bridge_cfg.auth_token = args.token

    if not cfg.database.mdb_path.exists():
        raise SystemExit(f"Database not found at {cfg.database.mdb_path}")

    app = create_app(
        get_mdb_path=lambda: cfg.database.mdb_path,
        auth_token=bridge_cfg.auth_token or None,
        wizard_handler=None,
    )

    config = uvicorn.Config(
        app,
        host=bridge_cfg.host,
        port=int(bridge_cfg.port),
        log_level="info",
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:  # pragma: no cover - CLI convenience
        pass


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
