"""
Accounts: registration, login, logout, sessions.

Coverage of ``routes/login.py`` and the ``User`` password helpers.
"""

from __future__ import annotations

import pytest

from tests.conftest import db, formkey, signup_payload
from ruqqus.classes import User
from ruqqus.classes.badges import Badge

AGENT = "pytest-agent/1.0"


def location(response) -> str:
    """The redirect target, for asserting on ``new_signup()``'s error query."""
    return response.headers.get("Location", "")


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
class TestPasswordHashing:
    def test_hash_is_not_the_plaintext(self):
        user = User(username="hashme", password="hunter2hunter2")
        assert user.passhash != "hunter2hunter2"
        assert "hunter2" not in user.passhash

    def test_hash_carries_its_algorithm(self):
        """Werkzeug prefixes the method, so pre-existing hashes keep verifying."""
        user = User(username="hashme", password="hunter2hunter2")
        assert user.passhash.startswith("pbkdf2:")

    def test_two_users_same_password_different_hashes(self):
        a = User(username="useraaaa", password="samepassword")
        b = User(username="userbbbb", password="samepassword")
        assert a.passhash != b.passhash

    def test_verify_pass_accepts_correct_password(self):
        user = User(username="hashme", password="hunter2hunter2")
        assert user.verifyPass("hunter2hunter2") is True

    def test_verify_pass_rejects_wrong_password(self):
        user = User(username="hashme", password="hunter2hunter2")
        assert user.verifyPass("hunter2") is False

    def test_verify_pass_rejects_empty_password(self):
        user = User(username="hashme", password="hunter2hunter2")
        assert user.verifyPass("") is False


# --------------------------------------------------------------------------
# GET /login
# --------------------------------------------------------------------------
class TestLoginPage:
    def test_renders_for_anonymous_visitor(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert b"password" in response.data.lower()

    def test_logged_in_user_is_redirected(self, client, as_user):
        as_user()
        assert client.get("/login").status_code == 302

    def test_redirect_target_appears_in_the_form(self, client):
        response = client.get("/login?redirect=/submit")
        assert response.status_code == 200
        assert b"/submit" in response.data


# --------------------------------------------------------------------------
# POST /login
# --------------------------------------------------------------------------
class TestLogin:
    def test_correct_password_logs_in(self, client, make_user, login):
        user = make_user()
        response = login(user)

        assert response.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("user_id") == user.id

    def test_wrong_password_is_rejected(self, client, make_user, login):
        user = make_user()
        response = login(user, password="not-the-password")

        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_unknown_user_is_rejected(self, client):
        response = client.post(
            "/login", data={"username": "nosuchuser", "password": "whatever"}
        )
        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_login_by_email_works(self, client, make_user):
        user = make_user(email="findme@example.com")
        response = client.post(
            "/login",
            data={"username": "findme@example.com", "password": user.password},
        )
        assert response.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("user_id") == user.id

    def test_login_is_case_insensitive_on_username(self, client, make_user):
        user = make_user(username="MixedCase")
        response = client.post(
            "/login",
            data={"username": "mixedcase", "password": user.password},
        )
        assert response.status_code == 302

    def test_successful_login_rotates_session_id(self, client, make_user, login):
        """A fresh session_id on login limits the value of a stolen session."""
        user = make_user()
        client.get("/robots.txt")
        with client.session_transaction() as sess:
            before = sess.get("session_id")

        login(user)

        with client.session_transaction() as sess:
            assert sess.get("session_id") != before

    def test_failed_login_does_not_authenticate(self, client, make_user, login):
        user = make_user()
        login(user, password="wrong")
        assert client.get("/me").status_code == 401

    def test_empty_username_does_not_authenticate(self, client):
        response = client.post(
            "/login", data={"username": "", "password": "whatever"}
        )
        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert "user_id" not in sess


# --------------------------------------------------------------------------
# GET /me and POST /logout
# --------------------------------------------------------------------------
class TestSession:
    def test_me_requires_login(self, client):
        assert client.get("/me").status_code == 401

    def test_me_redirects_to_own_profile(self, client, as_user):
        user = as_user()
        response = client.get("/me")
        assert response.status_code == 302
        assert location(response).endswith(f"/@{user.username}")

    def test_logout_clears_the_session(self, client, as_user, formkey):
        user = as_user()
        response = client.post("/logout", data={"formkey": formkey(user.id)})

        assert response.status_code == 302
        with client.session_transaction() as sess:
            assert "user_id" not in sess
            assert "session_id" not in sess

    def test_logout_requires_a_formkey(self, client, as_user):
        as_user()
        assert client.post("/logout").status_code == 401

    def test_logout_rejects_a_formkey_from_a_different_session(self, client, as_user):
        """
        The formkey is HMAC(session_id + user_id), so it must not survive a
        change of session_id -- that is what stops a leaked formkey from a
        rendered page being replayed after the victim logs in again.
        """
        user = as_user()
        client.get("/robots.txt")
        valid_key = formkey(user.id)

        # same user, different session -> the old key must stop working
        with client.session_transaction() as sess:
            sess["session_id"] = "f" * 32

        response = client.post("/logout", data={"formkey": valid_key})
        assert response.status_code == 401

    def test_logout_rejects_a_forged_formkey(self, client, as_user):
        user = as_user()
        assert client.post("/logout", data={"formkey": "0" * 32}).status_code == 401
        assert formkey(user.id) != "0" * 32


# --------------------------------------------------------------------------
# GET /signup -- renders the form and mints the one-shot signup token
# --------------------------------------------------------------------------
class TestSignupPage:
    def test_renders_for_anonymous_visitor(self, client):
        response = client.get("/signup", headers={"User-Agent": AGENT})
        assert response.status_code == 200
        assert b'name="formkey"' in response.data
        assert b'name="now"' in response.data

    def test_mints_a_signup_token_in_the_session(self, client):
        client.get("/signup", headers={"User-Agent": AGENT})
        with client.session_transaction() as sess:
            assert sess.get("signup_token")

    def test_requires_a_user_agent(self, client):
        """The signup formkey is bound to the User-Agent; without one -> 403."""
        response = client.get(
            "/signup", environ_overrides={"HTTP_USER_AGENT": ""}
        )
        assert response.status_code == 403

    def test_logged_in_user_is_redirected(self, client, as_user):
        as_user()
        response = client.get("/signup", headers={"User-Agent": AGENT})
        assert response.status_code == 302


# --------------------------------------------------------------------------
# POST /signup -- validation
#
# Every case here is decided before the user row is written, so they pass.
# Account creation itself is in TestSignupCreatesAnAccount, xfail'd on the
# badge_defs blocker.
# --------------------------------------------------------------------------
class TestSignupValidation:
    def test_password_mismatch_is_rejected(self, signup):
        response = signup(
            username="newuser1",
            password="longenough1",
            password_confirm="different",
        )
        assert response.status_code == 302
        assert "error=" in location(response)
        assert "Passwords+did+not+match" in location(response)

    def test_short_password_is_rejected(self, signup):
        response = signup(username="newuser1", password="short")
        assert response.status_code == 302
        assert "error=" in location(response)

    def test_short_username_is_rejected(self, signup):
        response = signup(username="abc")
        assert response.status_code == 302
        assert "error=Invalid+username" in location(response)

    def test_long_username_is_rejected(self, signup):
        response = signup(username="a" * 26)
        assert response.status_code == 302
        assert "error=Invalid+username" in location(response)

    def test_username_with_special_characters_is_rejected(self, signup):
        response = signup(username="bad!user")
        assert response.status_code == 302
        assert "error=Invalid+username" in location(response)

    def test_duplicate_username_is_rejected(self, signup, make_user):
        existing = make_user(username="takenname")
        response = signup(username=existing.username)
        assert response.status_code == 302
        assert "error=" in location(response)

    def test_duplicate_email_is_rejected(self, signup, make_user):
        existing = make_user(email="taken@example.com")
        response = signup(username="freshname", email=existing.email)
        assert response.status_code == 302
        assert "error=" in location(response)

    def test_wrong_formkey_is_rejected(self, client):
        """A tampered formkey must not create an account."""
        client.get("/signup", headers={"User-Agent": AGENT})
        with client.session_transaction() as sess:
            token = sess.get("signup_token")

        payload = signup_payload(
            username="forgeduser", signup_token=token, formkey_value="0" * 32
        )
        response = client.post(
            "/signup", data=payload, headers={"User-Agent": AGENT}
        )

        assert response.status_code == 302
        assert db.query(User).filter_by(username="forgeduser").first() is None

    def test_wrong_user_agent_invalidates_the_formkey(self, client):
        """The formkey is bound to the User-Agent it was minted with."""
        client.get("/signup", headers={"User-Agent": AGENT})
        with client.session_transaction() as sess:
            token = sess.get("signup_token")

        payload = signup_payload(
            username="agentuser", signup_token=token, agent=AGENT
        )
        response = client.post(
            "/signup",
            data=payload,
            headers={"User-Agent": "a-completely-different-agent"},
        )

        assert response.status_code == 302
        assert db.query(User).filter_by(username="agentuser").first() is None

    def test_form_timestamp_in_the_future_is_rejected(self, signup):
        """``now - form_timestamp < 5`` blocks instant submissions."""
        response = signup(username="toofast1", age_seconds=-60)
        assert response.status_code == 302
        assert "error=" in location(response)

    def test_signed_up_username_is_still_free_after_a_validation_error(self, signup):
        signup(username="retryme", password="short")
        assert db.query(User).filter_by(username="retryme").first() is None


# --------------------------------------------------------------------------
# POST /signup -- account creation
#
# xfail on the badge_defs blocker: badges.badge_id has a real FK to
# badge_defs.id, the migration seeds no rows, and sign_up_post inserts
# badge_id=1 on every account.  The user row commits first, so a signup
# currently leaves an account behind and then raises.
# --------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "BLOCKER: signup inserts Badge(badge_id=1) but badge_defs is empty on "
        "a fresh install -> ForeignKeyViolation after the user row commits. "
        "Fix: seed badge_defs id=1 (beta.png) and id=2 (mail.png) in the "
        "migration. See the Phase 4 report."
    ),
)
class TestSignupCreatesAnAccount:
    def test_signup_creates_a_user_and_redirects(self, signup):
        response = signup(username="brandnew", email="brandnew@example.com")

        assert response.status_code == 302
        assert "error=" not in location(response)
        user = db.query(User).filter_by(username="brandnew").first()
        assert user is not None
        assert user.email == "brandnew@example.com"

    def test_signup_awards_the_beta_badge(self, signup):
        signup(username="badged", email="badged@example.com")

        user = db.query(User).filter_by(username="badged").first()
        badges = db.query(Badge).filter_by(user_id=user.id).all()
        assert [b.badge_id for b in badges] == [1]

    def test_signup_logs_the_user_in(self, client, signup):
        response = signup(username="autologin", email="autologin@example.com")

        assert response.status_code == 302
        user = db.query(User).filter_by(username="autologin").first()
        with client.session_transaction() as sess:
            assert sess.get("user_id") == user.id

    def test_signup_password_is_hashed(self, signup):
        signup(username="plaintext", password="supersecret1")

        user = db.query(User).filter_by(username="plaintext").first()
        assert user.passhash != "supersecret1"
        assert user.verifyPass("supersecret1") is True

    def test_signup_accepts_no_email(self, signup):
        response = signup(username="noemail1", email="")

        assert response.status_code == 302
        user = db.query(User).filter_by(username="noemail1").first()
        assert user is not None
        assert user.email is None

    def test_signup_is_all_or_nothing(self, signup):
        """
        Either the account is fully created or nothing is persisted.

        Today the user row commits and the badge insert then raises, leaving
        an account that was never completed.  The route should wrap user +
        badge creation in a single transaction.
        """
        response = signup(username="allornothing", email="aon@example.com")

        user = db.query(User).filter_by(username="allornothing").first()
        if response.status_code == 302 and "error=" not in location(response):
            assert user is not None
        else:
            assert user is None, (
                "signup failed but still persisted a user row -- the route "
                "must not leave a partial account behind"
            )
