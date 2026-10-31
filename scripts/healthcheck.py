#!/usr/bin/env python3
"""Container health probe.

Exits 0 when ``GET /health`` returns 200, 1 otherwise.  Used as the Docker
HEALTHCHECK command and by ``docker compose`` to gate ``depends_on``.

``python:3.12-slim`` ships neither ``curl`` nor ``wget``, so this uses only the
standard library.

Override the target with ``HEALTHCHECK_URL``, or the port with ``PORT``:

    HEALTHCHECK_URL=http://127.0.0.1:9000/health python scripts/healthcheck.py
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

DEFAULT_PORT = "8000"


def main() -> int:
    url = os.environ.get(
        "HEALTHCHECK_URL",
        f"http://127.0.0.1:{os.environ.get('PORT', DEFAULT_PORT)}/health",
    )
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            healthy = response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        healthy = False

    if not healthy:
        print(f"unhealthy: {url}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
