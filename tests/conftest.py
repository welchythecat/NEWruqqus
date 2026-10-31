"""
pytest fixtures for Ruqqus.

Why this file looks the way it does
-----------------------------------
``ruqqus.__main__`` is a module-level singleton: *importing* it builds the
Flask app **and** the SQLAlchemy engine from ``config.DATABASE_URL``.  There is
no application factory to re-point afterwards, so the test database must be
chosen in the environment **before** that import.  Everything below the
"environment" block happens strictly after.

Tests run against real PostgreSQL and never SQLite.  The schema depends on
PostgreSQL row-wise functions (``ups(submissions)``, ``comments.rank_hot``) and
on ``random()``; neither exists in SQLite.

Creating the test database
--------------------------
The suite needs one empty database that it may drop/recreate tables in.  It is
created automatically if it does not exist::

    createdb ruqqus_test                     # or let the suite do it
    RUQQUS_TEST_DATABASE_URL=postgresql://user:pass@host:5432/other_db pytest

``DATABASE_URL`` is always overridden -- tests can never touch a real site
database, whatever is in your ``.env``.

Working with ORM objects in tests
---------------------------------
``teardown_request`` calls ``db.remove()``, so any ORM instance held across a
request becomes detached and expired.  Factories here therefore return plain
dataclass records (``UserRecord`` etc.), not ORM objects.  When you need the
ORM object, re-query it::

    user = make_user()
    client.post("/login", data={...})
    assert db.query(User).get(user.id).is_banned   # fresh query
"""

from __future__ import annotations

import os
import re
import sys
import time as _time
from dataclasses import dataclass
from hmac import new as _hmac_new
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# Project on sys.path (this file lives in <root>/tests/)
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --------------------------------------------------------------------------
# Environment -- MUST be settled before ruqqus.__main__ is imported.
#
# Values that affect hermeticity are forced, not defaulted: a developer's
# exported CACHE_ENABLED=true or MAIL_BACKEND=smtp must not make the suite
# reach for Redis or send real mail.
# --------------------------------------------------------------------------
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://ruqqus:ruqqus@localhost:5432/ruqqus_test"
)

TEST_DATABASE_URL = os.environ.get(
    "RUQQUS_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["CACHE_ENABLED"] = "false"  # NullCache: no Redis needed to test
os.environ["MAIL_BACKEND"] = "console"  # never send real mail from a test
os.environ["BEHIND_PROXY"] = "false"  # no X-Forwarded-* trickery
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("TOKEN_SIGNING_KEY", "test-token-key-0123456789abcdef")
os.environ.setdefault("SITE_URL", "http://localhost:8000")
os.environ.setdefault("LOG_LEVEL", "ERROR")

# Now it is safe to build the app.
from ruqqus import config  # noqa: E402
from ruqqus.__main__ import app as flask_app  # noqa: E402
from ruqqus.__main__ import db, limiter  # noqa: E402
from ruqqus.classes import Comment, Submission, User, Vote  # noqa: E402
from ruqqus.helpers.security import generate_hash  # noqa: E402

TABLES = (
    "alts",
    "badge_defs",
    "badges",
    "commentflags",
    "commentvotes",
    "comments",
    "domains",
    "flags",
    "images",
    "notifications",
    "submissions",
    "users",
    "votes",
)


# --------------------------------------------------------------------------
# Database bootstrap
# --------------------------------------------------------------------------
def _ensure_database(url: str) -> None:
    """Create the test database if it does not already exist."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    target = make_url(url)
    name = target.database
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise RuntimeError(
            f"Refusing to auto-create a database with the name {name!r}. "
            "Set RUQQUS_TEST_DATABASE_URL to a normal identifier."
        )

    maintenance = create_engine(
        target.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with maintenance.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"),
                {"d": name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
                print(f"conftest: created test database {name!r}")
    finally:
        maintenance.dispose()


def _upgrade_schema() -> None:
    """Apply every Alembic migration (also installs the PostgreSQL functions)."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(cfg, "head")


def _truncate_all() -> None:
    from sqlalchemy import text

    db.execute(
        text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    )
    db.commit()


def _seed_splash_images() -> None:
    """
    Populate ``images`` from the splash art that ships in the repo.

    The row shape is derived mechanically from the filenames in
    ``ruqqus/assets/images/states/`` (``<state>-<number>.jpg``), so this is
    restoration, not invention.  The original ``text`` column values are not
    recoverable from the repository and are left NULL.
    """
    from ruqqus.classes.images import Image

    states_dir = PROJECT_ROOT / "ruqqus" / "assets" / "images" / "states"
    seen: set[tuple[str, int]] = set()

    for path in sorted(states_dir.glob("*")):
        match = re.fullmatch(r"([a-z]{2})-(\d+)\.(?:jpg|jpeg|png)", path.name)
        if not match:
            continue
        state, number = match.group(1), int(match.group(2))
        if (state, number) in seen:
            continue
        seen.add((state, number))
        db.add(Image(state=state, number=number, text=None))

    db.commit()


# --------------------------------------------------------------------------
# Session-scoped: build the schema exactly once
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def app():
    """The application under test, with rate limiting switched off."""
    flask_app.config.update(
        TESTING=True,
        PROPAGATE_EXCEPTIONS=True,
        RATELIMIT_ENABLED=False,
    )
    # Flask-Limiter exposes `enabled` as a plain instance attribute; the
    # enforcement path is gated on `self.initialized and self.enabled`.
    limiter.enabled = False

    return flask_app


@pytest.fixture(scope="session", autouse=True)
def _schema(app):
    _ensure_database(TEST_DATABASE_URL)
    _upgrade_schema()
    yield


# --------------------------------------------------------------------------
# Function-scoped: clean state for every test
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_db(_schema):
    _truncate_all()
    _seed_splash_images()
    yield
    db.remove()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """
    ``routes/login.py`` calls ``time.sleep(random.uniform(0, 2))`` on a failed
    login.  That is correct anti-enumeration behaviour in production and a
    multi-second tax per test here.
    """
    monkeypatch.setattr(_time, "sleep", lambda *_args, **_kwargs: None)


@pytest.fixture
def db_session(_clean_db):
    """The application's scoped session."""
    return db


@pytest.fixture
def client(app, _clean_db):
    return app.test_client()


# --------------------------------------------------------------------------
# Factories -- return plain records, never ORM instances
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    password: str
    email: str | None
    admin_level: int


@dataclass(frozen=True)
class PostRecord:
    id: int
    base36id: str
    permalink: str
    fullname: str
    author_id: int


@dataclass(frozen=True)
class CommentRecord:
    id: int
    base36id: str
    fullname: str
    permalink: str
    parent_submission: int
    author_id: int


@pytest.fixture
def make_user(db_session):
    """Create a user directly through the ORM, bypassing the signup route."""
    counter = {"n": 0}

    def _make(
        username: str | None = None,
        password: str = "correct-horse-battery",
        email: str | None = None,
        admin_level: int = 0,
        is_activated: bool = True,
    ) -> UserRecord:
        counter["n"] += 1
        if username is None:
            username = f"user{counter['n']:04d}"
        if email is None:
            email = f"{username}@example.com"

        user = User(
            username=username,
            password=password,
            email=email,
            admin_level=admin_level,
            is_activated=is_activated,
        )
        db_session.add(user)
        db_session.commit()

        return UserRecord(
            id=user.id,
            username=user.username,
            password=password,
            email=user.email,
            admin_level=user.admin_level,
        )

    return _make


@pytest.fixture
def make_post(db_session, make_user):
    """Create a submission directly through the ORM."""

    def _make(
        author: UserRecord | None = None,
        title: str = "A perfectly ordinary test submission",
        body: str = "Body text for the test submission.",
        url: str = "",
        is_banned: bool = False,
    ) -> PostRecord:
        if author is None:
            author = make_user()

        post = Submission(
            title=title,
            url=url,
            author_id=author.id,
            body=body,
            body_html=f"<p>{body}</p>",
            is_banned=is_banned,
        )
        db_session.add(post)
        db_session.commit()

        return PostRecord(
            id=post.id,
            base36id=post.base36id,
            permalink=post.permalink,
            fullname=post.fullname,
            author_id=post.author_id,
        )

    return _make


@pytest.fixture
def make_comment(db_session, make_user, make_post):
    """Create a comment directly through the ORM."""

    def _make(
        author: UserRecord | None = None,
        post: PostRecord | None = None,
        body: str = "A test comment.",
        parent_fullname: str | None = None,
        is_banned: bool = False,
        is_deleted: bool = False,
    ) -> CommentRecord:
        if post is None:
            post = make_post()
        if author is None:
            author = make_user()
        if parent_fullname is None:
            parent_fullname = post.fullname

        comment = Comment(
            author_id=author.id,
            body=body,
            body_html=f"<p>{body}</p>",
            parent_submission=post.id,
            parent_fullname=parent_fullname,
            is_banned=is_banned,
            is_deleted=is_deleted,
        )
        db_session.add(comment)
        db_session.commit()

        return CommentRecord(
            id=comment.id,
            base36id=comment.base36id,
            fullname=comment.fullname,
            permalink=comment.permalink,
            parent_submission=comment.parent_submission,
            author_id=comment.author_id,
        )

    return _make


# --------------------------------------------------------------------------
# Request helpers
# --------------------------------------------------------------------------
def formkey(client, user_id: int) -> str:
    """
    Compute the CSRF formkey for ``user_id`` in the client's current session.

    Mirrors ``User.formkey``: ``generate_hash(session_id + str(user_id))``.
    The request must already have established a ``session_id`` (``before_request``
    does this), so log in first.
    """
    with client.session_transaction() as sess:
        session_id = sess.get("session_id")
    if not session_id:
        raise RuntimeError(
            "No session_id yet -- make a request (e.g. log in) before asking "
            "for a formkey."
        )
    return generate_hash(f"{session_id}{user_id}")


@pytest.fixture
def login(client):
    """POST /login and return the response."""

    def _login(user: UserRecord, password: str | None = None):
        return client.post(
            "/login",
            data={
                "username": user.username,
                "password": password or user.password,
                "redirect": "/",
            },
        )

    return _login


@pytest.fixture
def as_user(client, login, make_user):
    """Log in as a (new, by default) user and return the record."""

    def _as(user: UserRecord | None = None) -> UserRecord:
        if user is None:
            user = make_user()
        response = login(user)
        assert response.status_code == 302, (
            f"login failed for {user.username!r}: "
            f"{response.status_code} {response.data[:200]!r}"
        )
        return user

    return _as


def signup_payload(
    username: str,
    password: str = "correct-horse-battery",
    email: str | None = None,
    password_confirm: str | None = None,
    referred_by: int | str = 0,
    now: int | None = None,
    formkey_value: str | None = None,
    signup_token: str = "test-signup-token",
    agent: str = "pytest",
    age_seconds: int = 30,
) -> dict:
    """
    Build the form body for ``POST /signup``.

    ``routes/login.py`` computes the signup formkey as::

        hmac.new(key=SECRET_KEY.encode("utf-16"),
                 msg=f"{now}{signup_token}{agent}".encode("utf-16")).hexdigest()

    Python < 3.13 defaulted ``digestmod`` to md5; Python 3.13 made it
    mandatory.  This helper spells out ``digestmod="md5"`` so it produces the
    value the application produced historically -- it must NOT be "fixed" to
    match a broken app.
    """
    if now is None:
        now = int(_time.time()) - age_seconds
    now = int(now)

    if formkey_value is None:
        message = f"{now}{signup_token}{agent}"
        formkey_value = _hmac_new(
            key=bytes(config.SECRET_KEY, "utf-16"),
            msg=bytes(message, "utf-16"),
            digestmod="md5",
        ).hexdigest()

    return {
        "username": username,
        "email": email or "",
        "password": password,
        "password_confirm": password_confirm or password,
        "referred_by": str(referred_by),
        "now": str(now),
        "formkey": formkey_value,
    }


@pytest.fixture
def signup(client):
    """
    Drive the signup flow: GET /signup (to mint a ``signup_token``) then POST.

    Returns the POST response.  The User-Agent is sent on both requests because
    the formkey is bound to it.
    """
    agent = "pytest-agent/1.0"

    def _signup(**kwargs):
        client.get("/signup", headers={"User-Agent": agent})

        with client.session_transaction() as sess:
            token = sess.get("signup_token", "test-signup-token")

        payload = signup_payload(agent=agent, signup_token=token, **kwargs)
        return client.post(
            "/signup",
            data=payload,
            headers={"User-Agent": agent},
        )

    return _signup


# --------------------------------------------------------------------------
# Re-exports for test modules
# --------------------------------------------------------------------------
__all__ = [
    "PROJECT_ROOT",
    "TABLES",
    "CommentRecord",
    "PostRecord",
    "UserRecord",
    "formkey",
    "signup_payload",
    "db",
    "User",
    "Submission",
    "Comment",
    "Vote",
    "config",
]
