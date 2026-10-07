"""`python -m trailcard` / `trailcard` entry point."""

from __future__ import annotations

import argparse

import uvicorn

from .server import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Trailcard: local-first outdoor quest cards")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
