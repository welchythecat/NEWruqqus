#!/usr/bin/env python3
"""
Local development server.

Runs the Flask built-in server, which is the simplest cross-platform option
(no gunicorn on Windows).  Do not use this for production -- see INSTALL.md.

Usage:
    python run_dev.py [--host HOST] [--port PORT] [--debug]
"""

from __future__ import annotations

import argparse

from ruqqus import config
from ruqqus.__main__ import app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Ruqqus dev server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"Ruqqus dev server on http://{args.host}:{args.port}")
    print(f"  SITE_URL     = {config.SITE_URL}")
    print(f"  DATABASE_URL = {config.DATABASE_URL}")
    print(f"  cache        = {'redis' if config.CACHE_ENABLED else 'disabled'}")
    print(f"  mail backend = {config.MAIL_BACKEND}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
