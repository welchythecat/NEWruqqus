"""
Harness self-checks and pinned defects.

These first prove the test rig itself is sound (schema installed, row-wise
functions present, rate limiting really off) before any feature test is
trusted.  ``TestPinnedDefects`` at the bottom holds the bugs this suite found
that Phase 3 must fix -- each is ``xfail(strict=True)``, so it turns into a
hard failure the moment the bug is fixed and the marker becomes stale.
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import PROJECT_ROOT, TABLES, db
from ruqqus.classes import User
from ruqqus.classes.badges import BadgeDef
from ruqqus.classes.images import Image, random_image


# --------------------------------------------------------------------------
# The rig
# --------------------------------------------------------------------------
def test_app_is_in_testing_mode(app):
    assert app.config["TESTING"] is True
    assert app.config["PROPAGATE_EXCEPTIONS"] is True


def test_rate_limiting_is_switched_off(app):
    """Both halves of the kill switch: app config and the Limiter attribute."""
    assert app.config["RATELIMIT_ENABLED"] is False
    from ruqqus.__main__ import limiter

    assert limiter.enabled is False


def test_rate_limits_do_not_fire(client):
    """
    Empirical proof that limiting is off.

    ``/robots.txt`` carries only the default ``100/minute`` limit, so 120
    requests in a single burst must yield no 429.  This is the test that fails
    loudly if ``limiter.enabled = False`` ever stops working.
    """
    for _ in range(120):
        response = client.get("/robots.txt")
        assert response.status_code != 429, (
            "rate limiting fired inside the test suite -- conftest.py did not "
            "successfully disable Flask-Limiter"
        )


def test_health_endpoint_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"] == "ok"
    # CACHE_ENABLED=false, so the cache check is reported as disabled.
    assert payload["checks"]["cache"] == "disabled"
    assert payload["version"]


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
def test_schema_has_all_tables(db_session):
    from sqlalchemy import text

    rows = db_session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
    ).scalars().all()

    for table in TABLES:
        assert table in rows, f"migration did not create {table!r}"
    assert "alembic_version" in rows


def test_schema_has_no_leftover_legacy_tables(db_session):
    """``boards``, ``dms``, ``ips`` and ``userflags`` were dropped on purpose."""
    from sqlalchemy import text

    rows = set(
        db_session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars().all()
    )

    for table in ("boards", "dms", "ips", "userflags"):
        assert table not in rows


def test_alembic_head_is_0001_initial(db_session):
    from sqlalchemy import text

    version = db_session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar()
    assert version == "0001_initial"


# --------------------------------------------------------------------------
# PostgreSQL row-wise functions
#
# Scores and counts come from functions, not columns.  If these are missing,
# post pages 500 deep inside ``tree_comments`` with no useful message.
# --------------------------------------------------------------------------
def test_postgres_row_functions_are_installed(db_session):
    from sqlalchemy import text

    expected = {
        "ups",
        "downs",
        "age",
        "score",
        "rank_hot",
        "rank_fiery",
        "comment_count",
        "flag_count",
        "energy",
        "referral_count",
        "splash",
    }

    found = set(
        db_session.execute(
            text(
                "SELECT proname FROM pg_proc "
                "WHERE pronamespace = 'public'::regnamespace"
            )
        ).scalars().all()
    )

    missing = expected - found
    assert not missing, (
        f"row-wise functions missing from the database: {sorted(missing)}"
    )


def test_ups_function_has_both_overloads(db_session):
    """``ups(submissions)`` and ``ups(comments)`` are two distinct functions."""
    from sqlalchemy import text

    rows = db_session.execute(
        text(
            "SELECT (SELECT t.typname FROM pg_type t WHERE t.oid = p.proargtypes[0]) "
            "AS argtype "
            "FROM pg_proc p "
            "WHERE p.proname = 'ups' "
            "  AND p.pronamespace = 'public'::regnamespace "
            "ORDER BY argtype"
        )
    ).all()

    argtypes = {row.argtype for row in rows}
    assert argtypes == {"submissions", "comments"}, (
        f"expected ups(submissions) and ups(comments), got {sorted(argtypes)}"
    )


# --------------------------------------------------------------------------
# Static assets the templates depend on
# --------------------------------------------------------------------------
def test_error_templates_exist():
    """``abort(4xx/5xx)`` renders ``errors/<code>.html``; a missing one is a 500."""
    errors_dir = PROJECT_ROOT / "ruqqus" / "templates" / "errors"
    for code in (400, 401, 403, 404, 405, 422, 429, 500):
        assert (errors_dir / f"{code}.html").is_file(), (
            f"missing error template errors/{code}.html"
        )


def test_splash_images_are_seeded(db_session):
    """``random_image()`` must return something, or the auth pages have no art."""
    assert db_session.query(Image).count() > 0
    assert random_image() is not None


def test_splash_image_rows_match_shipped_assets(db_session):
    """
    Every seeded row must point at a file that exists.

    ``Image.path`` is ``/assets/images/states/<state>-<number>.jpg`` -- a row
    with no matching file renders a broken <img> on every auth page.
    """
    states_dir = PROJECT_ROOT / "ruqqus" / "assets" / "images" / "states"
    on_disk = {p.name for p in states_dir.glob("*")}

    for image in db_session.query(Image).all():
        stem = f"{image.state.lower()}-{image.number}"
        assert f"{stem}.jpg" in on_disk or f"{stem}.jpeg" in on_disk, (
            f"Image row {image.state}-{image.number} has no asset on disk"
        )


# --------------------------------------------------------------------------
# Regression guards for defects already fixed
# --------------------------------------------------------------------------
def test_signup_hmac_calls_specify_digestmod():
    """
    ``hmac.new()`` without ``digestmod`` raises TypeError on Python 3.13+.

    Python < 3.13 silently defaulted to md5; 3.13 made the argument
    mandatory, which broke GET and POST /signup outright.  Spelling out
    ``digestmod="md5"`` keeps the token values identical while restoring
    3.13 support.  This test keeps it from coming back.
    """
    source = (PROJECT_ROOT / "ruqqus" / "routes" / "login.py").read_text(
        encoding="utf-8"
    )
    calls = re.findall(r"hmac\.new\((.*?)\)\.hexdigest\(\)", source, re.S)
    assert len(calls) == 2, f"expected 2 hmac.new() calls, found {len(calls)}"
    for call in calls:
        assert "digestmod" in call, (
            "hmac.new() without digestmod breaks on Python 3.13+: "
            + re.sub(r"\s+", " ", call).strip()[:80]
        )


# --------------------------------------------------------------------------
# Pinned defects -- found by this suite, fixed in Phase 3
#
# xfail(strict=True) means: today these fail (documenting the bug); the moment
# the bug is fixed they XPASS and strict mode turns that into a failure, which
# forces the marker to be removed.  Nothing here can rot silently.
# --------------------------------------------------------------------------
class TestPinnedDefects:
    """Bugs this suite found.  Each entry names file, line and consequence."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BLOCKER: badges.badge_id has a real FK to badge_defs.id, but the "
            "migration seeds no rows while routes/login.py:273 inserts "
            "badge_id=1 on every signup. Account creation fails with a "
            "ForeignKeyViolation on a fresh install."
        ),
    )
    def test_badge_defs_are_seeded(self, db_session):
        # The repo ships beta.png and mail.png, and the code comments call
        # badge 1 the "beta badge"; badge 2 is awarded on e-mail verification.
        for badge_id, expected_icon in ((1, "beta.png"), (2, "mail.png")):
            badge = db_session.query(BadgeDef).filter_by(id=badge_id).first()
            assert badge is not None, f"badge_defs has no row with id={badge_id}"
            assert badge.icon == expected_icon

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/admin_api.py:149 dereferences `post` outside the null "
            "check, which only guards the un-sticky branch. A missing post_id "
            "AttributeErrors instead of returning 404."
        ),
    )
    def test_sticky_missing_post_returns_404(self, client, as_user, make_post):
        admin = as_user()
        db.query(User).filter_by(id=admin.id).first().admin_level = 3
        db.commit()

        response = client.post(
            "/api/sticky/zz",
            data={"formkey": formkey(client, admin.id)},
        )
        assert response.status_code in (400, 404)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "helpers/base36.py:23 base36decode() calls int(s, 36) and lets "
            "ValueError escape. Any non-base36 path segment becomes a 500 "
            "instead of a 400/404."
        ),
    )
    def test_non_base36_post_id_is_not_a_500(self, client):
        response = client.get("/post/not-a-base36-id!!")
        assert response.status_code in (400, 404)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/login.py:69 does `if \"@\" in username` where username = "
            "request.form.get(\"username\") is None when the field is omitted, "
            "so POST /login raises TypeError instead of failing cleanly."
        ),
    )
    def test_login_without_username_is_not_a_500(self, client):
        response = client.post("/login", data={"password": "x"})
        assert response.status_code in (200, 400)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "CSRF: /api/sticky, /api/ban_comment, /api/unban_comment, "
            "/api/distinguish_comment, /api/undistinguish_comment and both "
            "/api/flag/* routes are missing @validate_formkey, unlike every "
            "other state-changing route."
        ),
    )
    def test_state_changing_routes_require_formkey(self, client, as_user, make_post):
        user = as_user()
        db.query(User).filter_by(id=user.id).first().admin_level = 3
        db.commit()
        post = make_post(author=user)

        # No formkey at all must not be allowed to change state.
        response = client.post(f"/api/sticky/{post.base36id}")
        assert response.status_code == 401

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/login.py:208-211: the 120s signup-token expiry is "
            "commented out and the `return` below it is dead code nested in "
            "new_signup(), so signup tokens never expire."
        ),
    )
    def test_signup_form_key_expires_after_two_minutes(self, signup):
        response = signup(username="lateuser", age_seconds=600)
        assert (
            b"There was a problem" in response.data
            or response.status_code in (302, 400)
        )
