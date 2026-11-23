"""Start the API server: ``ap-planner-server [--port 0] [--token T] [--static DIR]``.

The desktop app starts this as a sidecar. With ``--port 0`` a free port is chosen; the first
line on stdout is ``AP_SERVER_READY <port>`` so the app knows where to connect.
"""

import argparse
import os
import secrets
import socket
import sys
from pathlib import Path


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ap-planner-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = free port")
    parser.add_argument(
        "--token",
        default=os.environ.get("AP_API_TOKEN"),
        help="required as 'Authorization: Bearer <token>' (default: AP_API_TOKEN or random)",
    )
    parser.add_argument("--no-token", action="store_true", help="no auth (Docker behind a proxy)")
    parser.add_argument("--static", type=Path, default=None, help="serve the built frontend")
    args = parser.parse_args(argv)

    # Imported late: usecases switches into the player's folder (AP_HOME) on import.
    import uvicorn  # noqa: PLC0415

    from ap_planner.api import create_app  # noqa: PLC0415

    token = None if args.no_token else (args.token or secrets.token_urlsafe(24))
    port = args.port or _free_port(args.host)
    app = create_app(token=token, static_dir=args.static)
    print(f"AP_SERVER_READY {port}", flush=True)
    if token and not args.token:
        print(f"AP_SERVER_TOKEN {token}", flush=True)
    uvicorn.run(app, host=args.host, port=port, log_level="warning")
    sys.exit(0)


if __name__ == "__main__":
    main()
