"""
Health and readiness endpoint.

    GET /health   ->  200 {"status": "ok", ...}
                  ->  503 {"status": "degraded", ...} if a dependency is down

Used by Docker healthchecks, systemd watchdogs and load balancers.  Exempt
from rate limiting so probes never get throttled.
"""

from __future__ import annotations

from flask import jsonify
from sqlalchemy import text

from ruqqus import config
from ruqqus.__main__ import app, db, limiter


@app.route("/health", methods=["GET"])
@limiter.exempt
def health():
    checks = {}
    healthy = True

    # --- database ---
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        healthy = False
        checks["database"] = f"error: {exc.__class__.__name__}"

    # --- redis / cache ---
    if config.CACHE_ENABLED:
        try:
            from ruqqus.__main__ import cache as _cache
            _cache.set("_health_probe", "1", timeout=5)
            checks["cache"] = "ok"
        except Exception as exc:
            healthy = False
            checks["cache"] = f"error: {exc.__class__.__name__}"
    else:
        checks["cache"] = "disabled"

    payload = {
        "status": "ok" if healthy else "degraded",
        "version": app.config.get("VERSION"),
        "checks": checks,
    }
    return jsonify(payload), 200 if healthy else 503
