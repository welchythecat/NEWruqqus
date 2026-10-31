"""
Moderation: bans, approval, stickies, distinguishes, flags.

Coverage of ``routes/admin_api.py``, ``routes/flagging.py`` and the permission
matrix encoded in ``admin_level_required``.

Admin levels used by the codebase
---------------------------------
0  ordinary user
1  may distinguish/remove individual comments
3  may ban users, ban/restore posts, sticky, and manage admins
"""

from __future__ import annotations

import pytest

from tests.conftest import db, formkey
from ruqqus.classes import Comment, CommentFlag, Flag, Submission, User


def as_admin(make_user, level=3):
    return make_user(admin_level=level)


def post_as(client, user, path, **fields):
    payload = dict(fields)
    payload.setdefault("formkey", formkey(client, user.id))
    return client.post(path, data=payload)


# --------------------------------------------------------------------------
# The permission matrix
# --------------------------------------------------------------------------
class TestPermissions:
    """Who may call what.  This is the table the spec calls 'moderation permissions'."""

    def test_anonymous_is_rejected_everywhere(self, client, make_post, make_comment):
        post = make_post()
        comment = make_comment(post=post)
        for path in (
            f"/api/ban_user/1",
            f"/api/unban_user/1",
            f"/api/ban_post/{post.base36id}",
            f"/api/unban_post/{post.base36id}",
            f"/api/distinguish/{post.base36id}",
            f"/api/sticky/{post.base36id}",
            f"/api/ban_comment/{comment.base36id}",
            f"/api/unban_comment/{comment.base36id}",
            f"/api/distinguish_comment/{comment.base36id}",
            f"/api/undistinguish_comment/{comment.base36id}",
        ):
            assert client.post(path).status_code == 401, path

    def test_ordinary_user_is_rejected_everywhere(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        post = make_post()
        comment = make_comment(post=post)
        for path in (
            f"/api/ban_user/1",
            f"/api/unban_user/1",
            f"/api/ban_post/{post.base36id}",
            f"/api/unban_post/{post.base36id}",
            f"/api/sticky/{post.base36id}",
            f"/api/ban_comment/{comment.base36id}",
        ):
            response = post_as(client, user, path)
            assert response.status_code == 403, f"{path} -> {response.status_code}"

    def test_level_one_cannot_ban_users(self, client, make_user):
        """ban_user needs level 3, not merely level 1."""
        mod = as_admin(make_user, level=1)
        victim = make_user()

        response = post_as(client, mod, f"/api/ban_user/{victim.id}", reason="x")
        assert response.status_code == 403

    def test_level_one_cannot_ban_posts(self, client, make_user, make_post):
        mod = as_admin(make_user, level=1)
        post = make_post()

        response = post_as(client, mod, f"/api/ban_post/{post.base36id}")
        assert response.status_code == 403

    def test_level_one_cannot_sticky(self, client, make_user, make_post):
        mod = as_admin(make_user, level=1)
        response = post_as(client, mod, f"/api/sticky/{make_post().base36id}")
        assert response.status_code == 403

    def test_level_one_can_moderate_comments(self, client, make_user, make_post, make_comment):
        mod = as_admin(make_user, level=1)
        target = make_comment(post=make_post())

        response = post_as(client, mod, f"/api/ban_comment/{target.base36id}")
        assert response.status_code == 204

    def test_banned_admin_cannot_moderate(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        db.query(User).filter_by(id=admin.id).first().is_banned = 1
        db.commit()

        response = post_as(client, admin, f"/api/ban_post/{make_post().base36id}")
        assert response.status_code == 403


# --------------------------------------------------------------------------
# Banning and unbanning users
# --------------------------------------------------------------------------
class TestBanUser:
    def test_ban_sets_is_banned_to_the_acting_admins_id(self, client, make_user):
        admin = as_admin(make_user, level=3)
        victim = make_user()

        response = post_as(
            client, admin, f"/api/ban_user/{victim.id}", reason="spam"
        )

        assert response.status_code == 302
        banned = db.query(User).filter_by(id=victim.id).first()
        assert banned.is_banned == admin.id
        assert banned.ban_reason == "spam"

    def test_banned_by_resolves_the_admin(self, client, make_user):
        """``users.is_banned`` stores the admin's id, not a boolean."""
        admin = as_admin(make_user, level=3)
        victim = make_user()
        post_as(client, admin, f"/api/ban_user/{victim.id}", reason="spam")

        banned = db.query(User).filter_by(id=victim.id).first()
        assert banned.banned_by is not None
        assert banned.banned_by.id == admin.id

    def test_unban_clears_is_banned(self, client, make_user):
        admin = as_admin(make_user, level=3)
        victim = make_user()
        post_as(client, admin, f"/api/ban_user/{victim.id}", reason="spam")
        post_as(client, admin, f"/api/unban_user/{victim.id}")

        unbanned = db.query(User).filter_by(id=victim.id).first()
        assert unbanned.is_banned == 0
        assert unbanned.banned_by is None

    def test_ban_reason_defaults_to_empty(self, client, make_user):
        admin = as_admin(make_user, level=3)
        victim = make_user()
        post_as(client, admin, f"/api/ban_user/{victim.id}")

        banned = db.query(User).filter_by(id=victim.id).first()
        assert banned.ban_reason == ""

    def test_unknown_user_returns_400(self, client, make_user):
        admin = as_admin(make_user, level=3)
        assert post_as(client, admin, "/api/ban_user/999999").status_code == 400

    def test_requires_a_formkey(self, client, make_user):
        admin = as_admin(make_user, level=3)
        victim = make_user()

        response = client.post(
            f"/api/ban_user/{victim.id}", data={"reason": "spam"}
        )
        assert response.status_code == 401

    def test_banned_user_cannot_submit(self, client, as_user, make_user):
        victim = as_user()
        admin = as_admin(make_user, level=3)
        post_as(client, admin, f"/api/ban_user/{victim.id}", reason="spam")

        response = client.get("/submit")
        assert response.status_code == 403


# --------------------------------------------------------------------------
# Banning and restoring posts
# --------------------------------------------------------------------------
class TestBanPost:
    def test_ban_post_hides_it(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        post = make_post(title="Soon to be banned")

        response = post_as(client, admin, f"/api/ban_post/{post.base36id}")

        assert response.status_code == 302
        banned = db.query(Submission).filter_by(id=post.id).first()
        assert banned.is_banned is True
        assert banned.is_approved == 0
        assert banned.stickied is False

    def test_unban_post_approves_it_as_the_acting_admin(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        post = make_post(is_banned=True)

        post_as(client, admin, f"/api/unban_post/{post.base36id}")

        restored = db.query(Submission).filter_by(id=post.id).first()
        assert restored.is_banned is False
        assert restored.is_approved == admin.id
        assert restored.approved_utc > 0

    def test_unknown_post_returns_400(self, client, make_user):
        admin = as_admin(make_user, level=3)
        response = post_as(client, admin, "/api/ban_post/zz")
        assert response.status_code in (400, 404)

    def test_requires_a_formkey(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        post = make_post()

        response = client.post(f"/api/ban_post/{post.base36id}")
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Distinguishing
# --------------------------------------------------------------------------
class TestDistinguish:
    def test_author_admin_can_distinguish_their_own_post(
        self, client, make_user, make_post
    ):
        admin = as_admin(make_user, level=3)
        post = make_post(author=admin)

        response = post_as(client, admin, f"/api/distinguish/{post.base36id}")

        assert response.status_code == 302
        assert db.query(Submission).filter_by(id=post.id).first().distinguish_level == 3

    def test_distinguish_toggles_off(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        post = make_post(author=admin)

        post_as(client, admin, f"/api/distinguish/{post.base36id}")
        post_as(client, admin, f"/api/distinguish/{post.base36id}")

        assert db.query(Submission).filter_by(id=post.id).first().distinguish_level == 0

    def test_cannot_distinguish_someone_elses_post(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        post = make_post()  # authored by someone else

        response = post_as(client, admin, f"/api/distinguish/{post.base36id}")
        assert response.status_code == 403

    def test_unknown_post_returns_404(self, client, make_user):
        admin = as_admin(make_user, level=3)
        assert post_as(client, admin, "/api/distinguish/zz").status_code in (400, 404)

    def test_comment_distinguish_records_the_admin_level(
        self, client, make_user, make_post, make_comment
    ):
        mod = as_admin(make_user, level=1)
        target = make_comment(post=make_post())

        response = post_as(client, mod, f"/api/distinguish_comment/{target.base36id}")
        assert response.status_code == 204
        assert (
            db.query(Comment).filter_by(id=target.id).first().distinguish_level == 1
        )

    def test_comment_undistinguish_clears_it(
        self, client, make_user, make_post, make_comment
    ):
        mod = as_admin(make_user, level=1)
        target = make_comment(post=make_post(), is_banned=False)

        post_as(client, mod, f"/api/distinguish_comment/{target.base36id}")
        post_as(client, mod, f"/api/undistinguish_comment/{target.base36id}")

        assert (
            db.query(Comment).filter_by(id=target.id).first().distinguish_level == 0
        )


# --------------------------------------------------------------------------
# Stickying
# --------------------------------------------------------------------------
class TestSticky:
    def test_sticky_marks_the_post(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        post = make_post()

        response = post_as(client, admin, f"/api/sticky/{post.base36id}")

        assert response.status_code == 302
        assert db.query(Submission).filter_by(id=post.id).first().stickied is True

    def test_sticky_toggles_off(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        post = make_post()

        post_as(client, admin, f"/api/sticky/{post.base36id}")
        post_as(client, admin, f"/api/sticky/{post.base36id}")

        assert db.query(Submission).filter_by(id=post.id).first().stickied is False

    def test_sticking_a_second_post_unsticks_the_first(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        first = make_post()
        second = make_post()

        post_as(client, admin, f"/api/sticky/{first.base36id}")
        post_as(client, admin, f"/api/sticky/{second.base36id}")

        assert db.query(Submission).filter_by(id=first.id).first().stickied is False
        assert db.query(Submission).filter_by(id=second.id).first().stickied is True

    def test_unsticking_does_not_touch_another_post(self, client, make_user, make_post):
        admin = as_admin(make_user, level=3)
        first = make_post()
        second = make_post()

        post_as(client, admin, f"/api/sticky/{first.base36id}")
        post_as(client, admin, f"/api/sticky/{first.base36id}")  # unstick

        assert db.query(Submission).filter_by(id=second.id).first().stickied is False


# --------------------------------------------------------------------------
# Comment moderation
# --------------------------------------------------------------------------
class TestCommentModeration:
    def test_ban_comment(self, client, make_user, make_post, make_comment):
        mod = as_admin(make_user, level=1)
        target = make_comment(post=make_post())

        response = post_as(client, mod, f"/api/ban_comment/{target.base36id}")

        assert response.status_code == 204
        banned = db.query(Comment).filter_by(id=target.id).first()
        assert banned.is_banned is True
        assert banned.is_approved == 0

    def test_unban_comment_approves_as_the_acting_mod(
        self, client, make_user, make_post, make_comment
    ):
        mod = as_admin(make_user, level=1)
        target = make_comment(post=make_post(), is_banned=True)

        post_as(client, mod, f"/api/unban_comment/{target.base36id}")

        restored = db.query(Comment).filter_by(id=target.id).first()
        assert restored.is_banned is False
        assert restored.is_approved == mod.id

    def test_unknown_comment_returns_404(self, client, make_user):
        mod = as_admin(make_user, level=1)
        assert post_as(client, mod, "/api/ban_comment/zz").status_code in (400, 404)


# --------------------------------------------------------------------------
# Flagging
# --------------------------------------------------------------------------
class TestFlagging:
    def test_flagging_a_post_records_a_flag(self, client, as_user, make_post):
        user = as_user()
        post = make_post()

        response = client.post(f"/api/flag/post/{post.base36id}")

        assert response.status_code == 204
        assert post.id in [f.post_id for f in db.query(Flag).all()]

    def test_flagging_twice_is_rejected(self, client, as_user, make_post):
        user = as_user()
        post = make_post()

        client.post(f"/api/flag/post/{post.base36id}")
        response = client.post(f"/api/flag/post/{post.base36id}")

        assert response.status_code == 422

    def test_flagging_a_comment_records_a_flag(
        self, client, as_user, make_post, make_comment
    ):
        as_user()
        target = make_comment(post=make_post())

        response = client.post(f"/api/flag/comment/{target.base36id}")

        assert response.status_code == 204
        assert target.id in [f.comment_id for f in db.query(CommentFlag).all()]

    def test_requires_login(self, client, make_post):
        assert client.post(f"/api/flag/post/{make_post().base36id}").status_code == 401

    def test_banned_user_cannot_flag(self, client, as_user, make_post):
        user = as_user()
        db.query(User).filter_by(id=user.id).first().is_banned = 99
        db.commit()

        assert client.post(f"/api/flag/post/{make_post().base36id}").status_code == 403


# --------------------------------------------------------------------------
# Pinned defect
# --------------------------------------------------------------------------
class TestPinnedDefects:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "CSRF: /api/flag/post and /api/flag/comment are @is_not_banned only "
            "-- no @validate_formkey -- so any site can flag on a logged-in "
            "user's behalf."
        ),
    )
    def test_flagging_requires_a_formkey(self, client, as_user, make_post):
        as_user()
        response = client.post(f"/api/flag/post/{make_post().base36id}")
        assert response.status_code == 401

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/flagging.py:19 inserts Flag(post_id=pid) with no check that "
            "the post exists, so a bogus id is an unhandled IntegrityError "
            "rather than a 404."
        ),
    )
    def test_flagging_an_unknown_post_returns_404(self, client, as_user):
        from ruqqus.helpers.base36 import base36encode

        as_user()
        response = client.post(f"/api/flag/post/{base36encode(999999)}")
        assert response.status_code in (400, 404)
