"""
Ruqqus application object.

Importing this module *is* the construction of the Flask app -- there is no
application factory.  That is deliberate: every model and route module does
``from ruqqus.__main__ import app, db, ...``, so those names must exist before
the imports at the bottom of this file run.

Production entry point:   gunicorn ruqqus.__main__:app
Local development:        python run_dev.py
"""

from __future__ import annotations

import logging
import secrets

from flask import Flask, g, redirect, request, session
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from werkzeug.middleware.proxy_fix import ProxyFix

from ruqqus import config
from ruqqus.helpers.markdown_filter import attach_markdown_filter

_version = "1.2.0"

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("ruqqus")

# --------------------------------------------------------------------------
# Flask application
# --------------------------------------------------------------------------
# static_folder is disabled: assets are served by the explicit
# /assets/<path:path> route in ruqqus/routes/static.py so that route keeps its
# rate-limit exemption.  There is no ruqqus/static/ directory.
app = Flask(
    __name__,
    template_folder="./templates",
    static_folder=None,
)

# Trust X-Forwarded-* from exactly one proxy (matches the original num_proxies=1).
if config.BEHIND_PROXY:
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1
    )

app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["VERSION"] = _version

# NOTE: SERVER_NAME is intentionally NOT set.  The original code set it from
# the `domain` env var, which made Flask reject requests whose Host header did
# not match exactly (so http://127.0.0.1:8000 404'd when `domain` said
# localhost).  Nothing here needs subdomain routing, and leaving it unset lets
# url_for(_external=True) use the request host.  Absolute links are built from
# config.SITE_URL instead.

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL

# Caching: NullCache locally (the original CACHE_TYPE="null"), Redis elsewhere.
if config.CACHE_ENABLED:
    app.config["CACHE_TYPE"] = "RedisCache"
    app.config["CACHE_REDIS_URL"] = config.REDIS_URL
else:
    app.config["CACHE_TYPE"] = "NullCache"
app.config["CACHE_DEFAULT_TIMEOUT"] = 60

# Rate limiting.  A shared Redis store is used only when caching is enabled;
# otherwise Flask-Limiter falls back to an in-process memory store.
app.config["RATELIMIT_STORAGE_URI"] = (
    config.REDIS_URL if config.CACHE_ENABLED else "memory://"
)
app.config["RATELIMIT_HEADERS_ENABLED"] = True

cache = Cache(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100/minute"],
    storage_uri=app.config["RATELIMIT_STORAGE_URI"],
    headers_enabled=True,
    # Was "fixed-window-elastic-expiry", which limits >= 5 removed along with
    # the FixedWindowElasticExpiryRateLimiter class -- the string now raises
    # ConfigurationError at import and the whole app refuses to boot.
    # "fixed-window" is Flask-Limiter's own default and the closest surviving
    # descendant.  NOTE: the elastic variant refreshed the window's TTL on
    # every hit, so a caller who kept hammering stayed blocked; a plain fixed
    # window releases the quota at the boundary instead.  limits 5.x has no
    # equivalent ("moving-window" and "sliding-window-counter" are both smooth
    # sliding windows).  Flip this to "moving-window" if the cliff matters.
    strategy="fixed-window",
)

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
_engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)

# scoped_session proxies attribute access to a per-context Session, so the
# whole codebase can keep calling db.query()/db.add()/db.commit() unchanged
# while no longer sharing one Session across concurrent workers.
db = scoped_session(sessionmaker(bind=_engine, autoflush=False, future=True))

Base = declarative_base()


# --------------------------------------------------------------------------
# Request lifecycle
# --------------------------------------------------------------------------
@app.before_request
def before_request():
    """Force HTTPS in production and make sure the session has an id."""

    # Never force HTTPS for local development.
    if (
        not config.IS_LOCAL
        and request.is_secure is False
        and request.headers.get("X-Forwarded-Proto", "http") != "https"
    ):
        return redirect(request.url.replace("http://", "https://", 1), code=301)

    if not session.get("session_id"):
        session["session_id"] = secrets.token_hex(16)


@app.teardown_request
def teardown_request(exception=None):
    """Discard the scoped session so state cannot leak between requests."""
    db.remove()


@app.after_request
def after_request(response):
    response.headers.add(
        "Access-Control-Allow-Headers",
        "Origin, X-Requested-With, Content-Type, Accept, x-auth",
    )
    return response


# --------------------------------------------------------------------------
# Template filters
# --------------------------------------------------------------------------
attach_markdown_filter(app)

# --------------------------------------------------------------------------
# Models and routes -- must come last: they import back from this module.
# --------------------------------------------------------------------------
import ruqqus.classes          # noqa: E402,F401  (registers the ORM models)
import ruqqus.routes           # noqa: E402,F401  (registers all view functions)
import ruqqus.helpers.jinja2   # noqa: E402,F401  (registers template filters)
import ruqqus.mail             # noqa: E402,F401  (registers e-mail routes)


def create_app():
    """
    Compatibility shim.

    This codebase builds the app at import time, so there is nothing to
    construct.  Returning the module-level app keeps ``flask --app
    ruqqus.__main__:create_app`` and test harnesses working.
    """
    return app
