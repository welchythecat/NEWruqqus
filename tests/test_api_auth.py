"""
Cross-cutting concerns: CSRF formkeys and authentication requirements.

The formkey is the project's CSRF mechanism (``helpers/security.generate_hash``)
and predates this migration.  It is ``HMAC(session_id + user_id)`` -- bound to
both the session and the account -- and is emitted in ~35 templates.
"""

from __future__ import annotations

import pytest

from tests.conftest import db, formkey
from ruqqus.classes import User
from ruqqus.helpers.security import generate_hash


def location(response) -> str:
    return response.headers.get("Location", "")


def _session_id(client) -> str:
    with client.session_transaction() as sess:
        return sess["session_id"]


# --------------------------------------------------------------------------
# formkey mechanics
# --------------------------------------------------------------------------
class TestFormkey:
    def test_formkey_matches_the_user_helper(self, client, as_user):
        """The test helper must agree with ``User.formkey`` or every test lies."""
        user = as_user()
        client.get("/robots.txt")

        from_form = formkey(client, user.id)
        with client.session_transaction() as sess:
            session_id = sess["session_id"]

        assert from_form == generate_hash(f"{session_id}{user.id}")

    def test_formkey_is_bound_to_the_user_id(self, client, as_user, make_user):
        user = as_user()
        other = make_user()
        client.get("/robots.txt")

        assert formkey(client, user.id) != formkey(client, other.id)

    def test_formkey_is_bound_to_the_session(self, client, as_user):
        user = as_user()
        client.get("/robots.txt")
        first = formkey(client, user.id)

        with client.session_transaction() as sess:
            sess["session_id"] = "a" * 32

        assert formkey(client, user.id) != first

    def test_formkey_is_stable_within_a_session(self, client, as_user):
        user = as_user()
        client.get("/robots.txt")

        assert formkey(client, user.id) == formkey(client, user.id)

    def test_user_validate_formkey_accepts_the_right_key(self, client, as_user):
        """Round-trip the helper's key through a real formkey-gated route."""
        user = as_user()
        client.get("/robots.txt")
        key = formkey(client, user.id)

        assert client.post("/logout", data={"formkey": key}).status_code == 302

    def test_user_validate_formkey_rejects_a_wrong_key(self, client, as_user):
        as_user()
        client.get("/robots.txt")

        assert client.post("/logout", data={"formkey": "0" * 32}).status_code == 401

    def test_another_users_formkey_is_rejected(self, client, as_user, make_user):
        """A formkey minted for user A must not authorise user B's action."""
        user = as_user()
        other = make_user()
        client.get("/robots.txt")

        # valid for `other`, wrong for `user`
        wrong_key = generate_hash(
            f"{_session_id(client)}{other.id}"
        )
        assert wrong_key != formkey(client, user.id)
        assert client.post("/logout", data={"formkey": wrong_key}).status_code == 401


# --------------------------------------------------------------------------
# Routes that must reject anonymous users
# --------------------------------------------------------------------------
class TestAuthRequired:
    @pytest.mark.parametrize(
        "path",
        [
            "/me",
            "/settings",
            "/settings/profile",
            "/settings/security",
            "/my_info",
            "/notifications",
            "/submit",
        ],
    )
    def test_get_rejects_anonymous(self, client, path):
        assert client.get(path).status_code == 401, path

    @pytest.mark.parametrize(
        "path",
        [
            "/logout",
            "/submit",
            "/api/comment",
            "/api/vote/post/1/1",
            "/api/vote/comment/1/1",
            "/api/flag/post/1",
            "/api/flag/comment/1",
            "/edit_post/1",
            "/edit_comment/1",
            "/delete/comment/1",
        ],
    )
    def test_post_rejects_anonymous(self, client, path):
        assert client.post(path).status_code == 401, path

    @pytest.mark.parametrize(
        "path",
        [
            "/api/ban_user/1",
            "/api/unban_user/1",
            "/api/ban_post/1",
            "/api/unban_post/1",
            "/api/distinguish/1",
            "/api/sticky/1",
            "/api/ban_comment/1",
            "/api/unban_comment/1",
            "/api/distinguish_comment/1",
            "/api/undistinguish_comment/1",
        ],
    )
    def test_admin_post_rejects_anonymous(self, client, path):
        assert client.post(path).status_code == 401, path

    def test_public_routes_stay_public(self, client):
        for path in ("/", "/login", "/signup", "/forgot", "/health", "/robots.txt"):
            assert client.get(path, headers={"User-Agent": "pytest"}).status_code in (
                200,
                302,
            ), path


# --------------------------------------------------------------------------
# Routes that must reject a missing or wrong formkey
# --------------------------------------------------------------------------
class TestFormkeyRequired:
    """Every state-changing route must be CSRF-protected."""

    def test_logout_without_formkey_is_rejected(self, client, as_user):
        as_user()
        assert client.post("/logout").status_code == 401

    def test_submit_without_formkey_is_rejected(self, client, as_user):
        as_user()
        response = client.post(
            "/submit", data={"title": "Ten chars ok", "body": "hello"}
        )
        assert response.status_code == 401

    def test_comment_without_formkey_is_rejected(self, client, as_user, make_post):
        as_user()
        post = make_post()
        response = client.post(
            "/api/comment",
            data={
                "submission": post.base36id,
                "parent_fullname": post.fullname,
                "body": "hi",
            },
        )
        assert response.status_code == 401

    def test_vote_without_formkey_is_rejected(self, client, as_user, make_post):
        as_user()
        post = make_post()
        response = client.post(f"/api/vote/post/{post.base36id}/1")
        assert response.status_code == 401

    def test_edit_post_without_formkey_is_rejected(self, client, as_user, make_post):
        user = as_user()
        post = make_post(author=user)
        response = client.post(f"/edit_post/{post.base36id}", data={"body": "x"})
        assert response.status_code == 401

    def test_edit_comment_without_formkey_is_rejected(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post(), author=user)
        response = client.post(
            f"/edit_comment/{target.base36id}", data={"body": "x"}
        )
        assert response.status_code == 401

    def test_delete_comment_without_formkey_is_rejected(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post(), author=user)
        response = client.post(f"/delete/comment/{target.base36id}")
        assert response.status_code == 401

    def test_ban_user_without_formkey_is_rejected(self, client, make_user):
        admin = make_user(admin_level=3)
        victim = make_user()
        response = client.post(f"/api/ban_user/{victim.id}", data={"reason": "x"})
        assert response.status_code == 401

    def test_ban_post_without_formkey_is_rejected(self, client, make_user, make_post):
        make_user(admin_level=3)
        post = make_post()
        response = client.post(f"/api/ban_post/{post.base36id}")
        assert response.status_code == 401

    def test_distinguish_without_formkey_is_rejected(self, client, make_user, make_post):
        admin = make_user(admin_level=3)
        post = make_post(author=admin)
        response = client.post(f"/api/distinguish/{post.base36id}")
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
class TestSettings:
    def test_profile_settings_renders(self, client, as_user):
        as_user()
        assert client.get("/settings/profile").status_code == 200

    def test_security_settings_renders(self, client, as_user):
        as_user()
        assert client.get("/settings/security").status_code == 200

    def test_settings_redirects_to_profile(self, client, as_user):
        as_user()
        response = client.get("/settings")
        assert response.status_code == 302
        assert location(response).endswith("/settings/profile")


# --------------------------------------------------------------------------
# Pinned defect
# --------------------------------------------------------------------------
class TestPinnedDefects:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Open redirect: login_post() and login_get() pass "
            "request.form/args['redirect'] straight to flask.redirect(), so "
            "?redirect=https://evil.example hands an attacker a trusted-domain "
            "redirect. Must validate against SITE_URL or a leading '/'."
        ),
    )
    def test_login_does_not_redirect_off_site(self, client, make_user):
        user = make_user()
        response = client.post(
            "/login",
            data={
                "username": user.username,
                "password": user.password,
                "redirect": "https://evil.example/phish",
            },
        )
        assert response.status_code == 302
        target = location(response)
        assert target.startswith("/") and not target.startswith("//"), target

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Open redirect: edit_comment() redirects to "
            "request.form['current_page'] unvalidated."
        ),
    )
    def test_edit_comment_does_not_redirect_off_site(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post(), author=user)

        response = client.post(
            f"/edit_comment/{target.base36id}",
            data={
                "body": "x",
                "current_page": "https://evil.example/phish",
                "formkey": formkey(client, user.id),
            },
        )
        assert response.status_code == 302
        dest = location(response)
        assert dest.startswith("/") and not dest.startswith("//"), dest

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/login.py:332 and :362 call int(request.args/form['time']) "
            "with no default, so a /reset link missing the parameter raises "
            "TypeError instead of returning 400."
        ),
    )
    def test_reset_link_without_a_timestamp_is_not_a_500(self, client):
        response = client.get("/reset?id=1&token=x")
        assert response.status_code in (400, 404)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/login.py:252 does int(request.form['referred_by']) with a "
            "0 default; a non-numeric value raises ValueError instead of being "
            "ignored."
        ),
    )
    def test_non_numeric_referred_by_is_not_a_500(self, client):
        from tests.conftest import signup_payload

        client.get("/signup", headers={"User-Agent": "pytest-agent/1.0"})
        with client.session_transaction() as sess:
            token = sess.get("signup_token")

        payload = signup_payload(
            username="referred1",
            signup_token=token,
            referred_by="not-a-number",
        )
        response = client.post(
            "/signup",
            data=payload,
            headers={"User-Agent": "pytest-agent/1.0"},
        )
        assert response.status_code in (200, 302)
