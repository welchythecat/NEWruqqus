"""
Centralised configuration for Ruqqus.

Every setting is read from the environment.  A `.env` file in the project root
is loaded if present, so a local checkout can be configured once instead of
exporting variables in every shell.

This module deliberately imports nothing from the rest of the package: it is
imported first by ``ruqqus.__main__`` and must never pull in Flask or
SQLAlchemy.

Naming
------
The original codebase used several non-obvious names (``domain``,
``MASTER_KEY``, ``HEROKU_REDIS_PURPLE_URL``, ``MAILGUN_KEY``).  The new
primary names below are documented in ``.env.example``; the old names keep
working as deprecated aliases so an existing deployment can migrate without
being locked out.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
    def load_dotenv(*args, **kwargs):
        return False

# The project root is the directory containing the ``ruqqus`` package.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Load .env from the project root.  Existing real environment variables win.
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("ruqqus.config")


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or unusable."""


def _get(name: str, default=None, aliases: tuple = ()):
    """Return the first non-empty value among ``name`` and ``aliases``."""
    for key in (name, *aliases):
        value = os.environ.get(key)
        if value not in (None, ""):
            return value
    return default


def _require(name: str, aliases: tuple = (), hint: str = ""):
    value = _get(name, aliases=aliases)
    if value is None:
        message = (
            f"Required configuration {name!r} is not set."
            + (f" {hint}" if hint else "")
            + " See .env.example for the full list of settings."
        )
        raise ConfigError(message)
    return value


def _bool(name: str, default: bool = False, aliases: tuple = ()) -> bool:
    raw = _get(name, aliases=aliases)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, aliases: tuple = ()) -> int:
    raw = _get(name, aliases=aliases)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None


# --------------------------------------------------------------------------
# Core secrets
# --------------------------------------------------------------------------

#: Flask session signing key.  ``MASTER_KEY`` is the deprecated original name.
SECRET_KEY: str = _require(
    "SECRET_KEY",
    aliases=("MASTER_KEY",),
    hint="Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"",
)

#: Key used to sign password-reset and e-mail-verification links.
#: Falls back to SECRET_KEY so a minimal install still works, but a distinct
#: value is recommended: a leak of one then does not compromise the other.
TOKEN_SIGNING_KEY: str = _get("TOKEN_SIGNING_KEY", default=SECRET_KEY)


# --------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------

#: Canonical base URL of the site, without a trailing slash.
#: ``domain`` is the deprecated original name (it was lowercase).
SITE_URL: str = _get("SITE_URL", default=None, aliases=("domain",)) or "http://localhost:8000"
SITE_URL = SITE_URL.rstrip("/")

#: Derived: the host[:port] portion, used for Flask SERVER_NAME.
SERVER_NAME: str = urlparse(SITE_URL).netloc or "localhost:8000"

#: Derived: scheme, used when building absolute links.
PREFERRED_URL_SCHEME: str = urlparse(SITE_URL).scheme or "http"

#: Derived: True when running locally (no HTTPS redirect, cache disabled).
IS_LOCAL: bool = any(
    host in SERVER_NAME for host in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")
)


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

#: PostgreSQL connection string, e.g. postgresql://user:pass@host:5432/ruqqus
#:
#: SQLAlchemy 2.x resolves a bare ``postgresql://`` scheme to the *psycopg2*
#: driver, which this project does not install (we use psycopg 3), and it
#: rejects the legacy ``postgres://`` scheme outright.  Normalise the three
#: common spellings to the psycopg 3 dialect so an operator can paste the URL
#: from anywhere and it just works.  Only the scheme prefix is rewritten --
#: credentials, host, port, database and any query string are untouched.
_DATABASE_URL_SCHEME_ALIASES = {
    "postgres://": "postgresql+psycopg://",
    "postgresql://": "postgresql+psycopg://",
    "postgresql+psycopg2://": "postgresql+psycopg://",
}


def normalise_database_url(url: str) -> str:
    for old, new in _DATABASE_URL_SCHEME_ALIASES.items():
        if url.startswith(old):
            log.debug("Rewrote DATABASE_URL scheme %r -> %r", old, new)
            return new + url[len(old):]
    return url


DATABASE_URL: str = normalise_database_url(
    _require(
        "DATABASE_URL",
        hint="Example: postgresql://ruqqus:ruqqus@localhost:5432/ruqqus",
    )
)


# --------------------------------------------------------------------------
# Redis / caching
# --------------------------------------------------------------------------

#: Redis connection string used for caching and rate-limit storage.
#: ``HEROKU_REDIS_*`` are deprecated aliases from the original Heroku deploy.
REDIS_URL: str = _get(
    "REDIS_URL",
    default="redis://localhost:6379/0",
    aliases=("HEROKU_REDIS_PURPLE_URL", "HEROKU_REDIS_ORANGE_URL"),
)

#: Force the cache on or off.  Defaults to off on localhost, on elsewhere.
CACHE_ENABLED: bool = _bool("CACHE_ENABLED", default=not IS_LOCAL)


# --------------------------------------------------------------------------
# E-mail
# --------------------------------------------------------------------------

#: "console" (log to stdout - the default, needs no third party) or "smtp".
MAIL_BACKEND: str = (_get("MAIL_BACKEND", default="console") or "console").lower()
if MAIL_BACKEND not in {"console", "smtp"}:
    raise ConfigError(
        f"MAIL_BACKEND must be 'console' or 'smtp', got {MAIL_BACKEND!r}"
    )

#: From-address used for all outgoing mail.
MAIL_FROM: str = _get("MAIL_FROM", default="Ruqqus <noreply@localhost>")

#: SMTP settings, only read when MAIL_BACKEND=smtp.
SMTP_HOST: str = _get("SMTP_HOST", default="")
SMTP_PORT: int = _int("SMTP_PORT", 587)
SMTP_USER: str = _get("SMTP_USER", default="")
SMTP_PASSWORD: str = _get("SMTP_PASSWORD", default="")
SMTP_USE_TLS: bool = _bool("SMTP_USE_TLS", default=True)
SMTP_TIMEOUT: int = _int("SMTP_TIMEOUT", 10)

if MAIL_BACKEND == "smtp" and not SMTP_HOST:
    raise ConfigError("MAIL_BACKEND=smtp requires SMTP_HOST to be set")


# --------------------------------------------------------------------------
# Server behaviour
# --------------------------------------------------------------------------

#: Number of reverse proxies in front of the app (sets X-Forwarded-* trust).
#: Set to 0 when the app is exposed directly.
BEHIND_PROXY: bool = _bool("BEHIND_PROXY", default=True)

#: Dev-server port used by ``python -m ruqqus``.
PORT: int = _int("PORT", 8000)

#: Root logger level.
LOG_LEVEL: str = (_get("LOG_LEVEL", default="INFO") or "INFO").upper()

#: Directory for any future user uploads.  Not used yet - see MIGRATION_NOTES.md.
UPLOAD_DIR: Path = Path(_get("UPLOAD_DIR", default=str(PROJECT_ROOT / "uploads")))
