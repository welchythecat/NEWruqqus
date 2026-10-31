"""
Comments: replying, editing, deleting, notifications.

Coverage of ``routes/comments.py`` and the ``Comment`` model.
"""

from __future__ import annotations

import pytest

from tests.conftest import db, formkey
from ruqqus.classes import Comment, CommentVote, Notification, Submission, User


def location(response) -> str:
    return response.headers.get("Location", "")


def comment(client, user, post, **fields):
    """POST /api/comment as ``user`` with a valid formkey."""
    payload = {
        "submission": post.base36id,
        "parent_fullname": post.fullname,
        "body": "A test comment body.",
    }
    payload.update(fields)
    payload["formkey"] = formkey(client, user.id)
    return client.post("/api/comment", data=payload)


# --------------------------------------------------------------------------
# POST /api/comment
# --------------------------------------------------------------------------
class TestCreateComment:
    def test_creates_a_top_level_comment(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        response = comment(client, user, post, body="first!")

        assert response.status_code == 302
        created = db.query(Comment).filter_by(author_id=user.id).first()
        assert created is not None
        assert created.body == "first!"
        assert created.parent_submission == post.id
        assert created.is_top_level is True

    def test_redirects_to_the_comment_anchor(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        response = comment(client, user, post)

        assert location(response).startswith(post.permalink)
        assert "#comment-" in location(response)

    def test_author_gets_an_automatic_upvote(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        comment(client, user, post)

        created = db.query(Comment).filter_by(author_id=user.id).first()
        vote = db.query(CommentVote).filter_by(
            user_id=user.id, comment_id=created.id
        ).first()
        assert vote is not None
        assert vote.vote_type == 1

    def test_notifies_the_parent_post_author(self, client, as_user, make_user, make_post):
        author = make_user()
        post = make_post(author=author)
        commenter = as_user()

        comment(client, commenter, post, body="hey, nice post")

        notifications = db.query(Notification).filter_by(user_id=author.id).all()
        assert len(notifications) == 1
        assert notifications[0].comment is not None

    def test_does_not_notify_yourself(self, client, as_user, make_post):
        user = as_user()
        post = make_post(author=user)

        comment(client, user, post)

        assert db.query(Notification).filter_by(user_id=user.id).count() == 0

    def test_body_is_rendered_to_html(self, client, as_user, make_post):
        user = as_user()
        comment(client, user, make_post(), body="**bold** comment")

        created = db.query(Comment).filter_by(author_id=user.id).first()
        assert "<strong>bold</strong>" in created.body_html

    def test_html_in_the_body_is_sanitized(self, client, as_user, make_post):
        user = as_user()
        comment(
            client,
            user,
            make_post(),
            body='<script>alert(1)</script><b>ok</b>',
        )

        created = db.query(Comment).filter_by(author_id=user.id).first()
        assert "<script>" not in created.body_html

    def test_duplicate_comment_is_not_created_twice(
        self, client, as_user, make_post
    ):
        user = as_user()
        post = make_post()
        first = comment(client, user, post, body="same thing")
        second = comment(client, user, post, body="same thing")

        assert location(second) == location(first)
        assert db.query(Comment).filter_by(author_id=user.id).count() == 1


class TestReplyToComment:
    def test_reply_creates_a_child_comment(self, client, as_user, make_post, make_comment):
        user = as_user()
        post = make_post()
        parent = make_comment(post=post)

        response = comment(
            client, user, post, body="a reply", parent_fullname=parent.fullname
        )

        assert response.status_code == 302
        reply = db.query(Comment).filter_by(author_id=user.id).first()
        assert reply.is_top_level is False
        assert reply.parent_fullname == parent.fullname

    def test_reply_notifies_the_comment_author(
        self, client, as_user, make_user, make_post, make_comment
    ):
        parent_author = make_user()
        post = make_post()
        parent = make_comment(post=post, author=parent_author)
        replier = as_user()

        comment(client, replier, post, parent_fullname=parent.fullname)

        assert db.query(Notification).filter_by(user_id=parent_author.id).count() == 1


class TestCreateCommentValidation:
    def test_requires_login(self, client, make_post):
        post = make_post()
        response = client.post(
            "/api/comment",
            data={
                "submission": post.base36id,
                "parent_fullname": post.fullname,
                "body": "hi",
                "formkey": "x",
            },
        )
        assert response.status_code == 401

    def test_requires_a_valid_formkey(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        response = client.post(
            "/api/comment",
            data={
                "submission": post.base36id,
                "parent_fullname": post.fullname,
                "body": "hi",
                "formkey": "0" * 32,
            },
        )
        assert response.status_code == 401
        assert db.query(Comment).count() == 0

    def test_banned_user_cannot_comment(self, client, as_user, make_post):
        user = as_user()
        db.query(User).filter_by(id=user.id).first().is_banned = 99
        db.commit()

        response = comment(client, user, make_post())
        assert response.status_code == 403

    def test_cannot_comment_on_a_banned_post(self, client, as_user, make_post):
        user = as_user()
        post = make_post(is_banned=True)

        response = comment(client, user, post)
        assert response.status_code == 403

    def test_cannot_comment_on_a_deleted_post(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        db.query(Submission).filter_by(id=post.id).first().is_deleted = True
        db.commit()

        response = comment(client, user, post)
        assert response.status_code == 403


# --------------------------------------------------------------------------
# POST /edit_comment/<cid>
# --------------------------------------------------------------------------
class TestEditComment:
    def test_author_can_edit(self, client, as_user, make_post, make_comment):
        user = as_user()
        post = make_post()
        target = make_comment(post=post, author=user)

        response = client.post(
            f"/edit_comment/{target.base36id}",
            data={"body": "edited!", "formkey": formkey(client, user.id)},
        )

        assert response.status_code == 302
        updated = db.query(Comment).filter_by(id=target.id).first()
        assert updated.body == "edited!"
        assert updated.edited_timestamp > 0

    def test_body_is_resanitized_on_edit(self, client, as_user, make_post, make_comment):
        user = as_user()
        target = make_comment(post=make_post(), author=user)

        client.post(
            f"/edit_comment/{target.base36id}",
            data={
                "body": '<script>alert(1)</script>safe',
                "formkey": formkey(client, user.id),
            },
        )

        updated = db.query(Comment).filter_by(id=target.id).first()
        assert "<script>" not in updated.body_html

    def test_non_author_cannot_edit(self, client, as_user, make_post, make_comment):
        target = make_comment(post=make_post())
        other = as_user()

        response = client.post(
            f"/edit_comment/{target.base36id}",
            data={"body": "hijacked", "formkey": formkey(client, other.id)},
        )

        assert response.status_code == 403
        assert db.query(Comment).filter_by(id=target.id).first().body != "hijacked"

    def test_unknown_comment_returns_404(self, client, as_user):
        user = as_user()
        response = client.post(
            "/edit_comment/zz",
            data={"body": "x", "formkey": formkey(client, user.id)},
        )
        assert response.status_code in (400, 404)

    def test_banned_comment_cannot_be_edited(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post(), author=user, is_banned=True)

        response = client.post(
            f"/edit_comment/{target.base36id}",
            data={"body": "nope", "formkey": formkey(client, user.id)},
        )
        assert response.status_code == 403

    def test_deleted_comment_cannot_be_edited(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post(), author=user, is_deleted=True)

        response = client.post(
            f"/edit_comment/{target.base36id}",
            data={"body": "nope", "formkey": formkey(client, user.id)},
        )
        assert response.status_code == 403

    def test_requires_a_formkey(self, client, as_user, make_post, make_comment):
        user = as_user()
        target = make_comment(post=make_post(), author=user)

        response = client.post(
            f"/edit_comment/{target.base36id}", data={"body": "x"}
        )
        assert response.status_code == 401


# --------------------------------------------------------------------------
# POST /delete/comment/<cid>
# --------------------------------------------------------------------------
class TestDeleteComment:
    def test_author_can_delete(self, client, as_user, make_post, make_comment):
        user = as_user()
        target = make_comment(post=make_post(), author=user)

        response = client.post(
            f"/delete/comment/{target.base36id}",
            data={"formkey": formkey(client, user.id)},
        )

        assert response.status_code == 204
        assert db.query(Comment).filter_by(id=target.id).first().is_deleted is True

    def test_non_author_cannot_delete(self, client, as_user, make_post, make_comment):
        target = make_comment(post=make_post())
        other = as_user()

        response = client.post(
            f"/delete/comment/{target.base36id}",
            data={"formkey": formkey(client, other.id)},
        )

        assert response.status_code == 403
        assert db.query(Comment).filter_by(id=target.id).first().is_deleted is False

    def test_requires_login(self, client, make_post, make_comment):
        target = make_comment(post=make_post())
        response = client.post(
            f"/delete/comment/{target.base36id}", data={"formkey": "x"}
        )
        assert response.status_code == 401

    def test_requires_a_formkey(self, client, as_user, make_post, make_comment):
        user = as_user()
        target = make_comment(post=make_post(), author=user)

        response = client.post(f"/delete/comment/{target.base36id}")
        assert response.status_code == 401

    def test_unknown_comment_returns_404(self, client, as_user):
        user = as_user()
        response = client.post(
            "/delete/comment/zz",
            data={"formkey": formkey(client, user.id)},
        )
        assert response.status_code in (400, 404)


# --------------------------------------------------------------------------
# Comment permalinks
# --------------------------------------------------------------------------
class TestCommentPermalinks:
    def test_comment_permalink_renders_the_post(self, client, make_post, make_comment):
        post = make_post()
        target = make_comment(post=post)

        response = client.get(f"/post/{post.base36id}/comment/{target.base36id}")
        assert response.status_code == 200

    def test_comment_from_another_post_returns_404(
        self, client, make_post, make_comment
    ):
        post_a = make_post()
        post_b = make_post()
        target = make_comment(post=post_a)

        response = client.get(f"/post/{post_b.base36id}/comment/{target.base36id}")
        assert response.status_code == 404

    def test_cid_redirect_is_admin_only(self, client, as_user, make_post, make_comment):
        target = make_comment(post=make_post())
        as_user()  # ordinary user
        assert client.get(f"/cid/{target.base36id}").status_code == 403

    def test_cid_redirects_for_admins(self, client, as_user, make_post, make_comment):
        admin = as_user()
        db.query(User).filter_by(id=admin.id).first().admin_level = 1
        db.commit()

        target = make_comment(post=make_post())
        response = client.get(f"/cid/{target.base36id}")
        assert response.status_code == 302


# --------------------------------------------------------------------------
# Pinned defect
# --------------------------------------------------------------------------
class TestPinnedDefects:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/comments.py:87-94: parent_fullname is split and the parent "
            "queried with no validation. A fullname pointing at a missing row "
            "leaves `parent` as None and the next line AttributeErrors instead "
            "of returning 404; a malformed fullname raises IndexError."
        ),
    )
    def test_comment_on_a_missing_parent_returns_404(self, client, as_user, make_post):
        from ruqqus.helpers.base36 import base36encode

        user = as_user()
        post = make_post()
        missing = f"t2_{base36encode(999999)}"

        response = comment(client, user, post, parent_fullname=missing)
        assert response.status_code in (400, 404)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "routes/comments.py:87: parent_fullname.split('_')[1] IndexErrors "
            "when the submitted parent_fullname has no underscore."
        ),
    )
    def test_malformed_parent_fullname_is_not_a_500(self, client, as_user, make_post):
        user = as_user()
        response = comment(client, user, make_post(), parent_fullname="garbage")
        assert response.status_code in (400, 404, 422)
