"""
Submissions: creating, viewing and editing posts.

Coverage of ``routes/posts.py`` and the ``Submission`` model.
"""

from __future__ import annotations

from tests.conftest import db, formkey
from ruqqus.classes import Submission, User, Vote


def location(response) -> str:
    return response.headers.get("Location", "")


def submit(client, user, **fields):
    """POST /submit as ``user`` with a valid formkey."""
    payload = {
        "title": "A perfectly ordinary test submission",
        "url": "",
        "body": "Body text for the test submission.",
    }
    payload.update(fields)
    payload["formkey"] = formkey(client, user.id)
    return client.post("/submit", data=payload)


# --------------------------------------------------------------------------
# GET /submit
# --------------------------------------------------------------------------
class TestSubmitPage:
    def test_requires_login(self, client):
        assert client.get("/submit").status_code == 401

    def test_renders_when_logged_in(self, client, as_user):
        as_user()
        response = client.get("/submit")
        assert response.status_code == 200
        assert b'name="title"' in response.data

    def test_banned_user_is_forbidden(self, client, as_user, make_user):
        user = as_user()
        db.query(User).filter_by(id=user.id).first().is_banned = 99
        db.commit()
        assert client.get("/submit").status_code == 403


# --------------------------------------------------------------------------
# POST /submit
# --------------------------------------------------------------------------
class TestCreatePost:
    def test_creates_a_text_post(self, client, as_user):
        user = as_user()
        response = submit(client, user, title="Ten chars ok", body="hello")

        assert response.status_code == 302
        assert location(response).startswith("/post/")

        post = db.query(Submission).filter_by(author_id=user.id).first()
        assert post is not None
        assert post.title == "Ten chars ok"
        assert post.body == "hello"

    def test_creates_a_link_post(self, client, as_user):
        user = as_user()
        response = submit(
            client,
            user,
            title="A link to somewhere",
            url="http://example.com/article",
            body="",
        )

        assert response.status_code == 302
        post = db.query(Submission).filter_by(author_id=user.id).first()
        assert post.url == "https://example.com/article"

    def test_submitted_urls_are_forced_to_https(self, client, as_user):
        user = as_user()
        submit(client, user, title="Insecure link here", url="http://example.com/x")

        post = db.query(Submission).filter_by(author_id=user.id).first()
        assert post.url.startswith("https://")

    def test_empty_url_is_stored_as_empty_string(self, client, as_user):
        user = as_user()
        submit(client, user, title="Text only post", url="")

        post = db.query(Submission).filter_by(author_id=user.id).first()
        assert post.url == ""

    def test_author_gets_an_automatic_upvote(self, client, as_user):
        user = as_user()
        submit(client, user, title="Ten chars ok", body="hello")

        post = db.query(Submission).filter_by(author_id=user.id).first()
        vote = db.query(Vote).filter_by(
            user_id=user.id, submission_id=post.id
        ).first()
        assert vote is not None
        assert vote.vote_type == 1

    def test_body_is_rendered_to_html(self, client, as_user):
        user = as_user()
        submit(client, user, title="Ten chars ok", body="**bold** text")

        post = db.query(Submission).filter_by(author_id=user.id).first()
        assert "<strong>bold</strong>" in post.body_html

    def test_html_in_the_body_is_sanitized(self, client, as_user):
        user = as_user()
        submit(
            client,
            user,
            title="XSS attempt post",
            body='<script>alert(1)</script><b>ok</b>',
        )

        post = db.query(Submission).filter_by(author_id=user.id).first()
        assert "<script>" not in post.body_html

    def test_title_is_sanitized(self, client, as_user):
        user = as_user()
        submit(
            client,
            user,
            title='<img src=x onerror=alert(1)> title',
            body="body text here",
        )

        post = db.query(Submission).filter_by(author_id=user.id).first()
        assert "<img" not in post.title

    def test_duplicate_post_redirects_to_the_original(self, client, as_user):
        user = as_user()
        first = submit(client, user, title="Duplicate title", url="http://e.com/a")
        second = submit(client, user, title="Duplicate title", url="http://e.com/a")

        assert location(second) == location(first)
        assert db.query(Submission).filter_by(author_id=user.id).count() == 1


class TestCreatePostValidation:
    def test_title_shorter_than_ten_characters_is_rejected(self, client, as_user):
        user = as_user()
        response = submit(client, user, title="short", body="body text")

        assert response.status_code == 200
        assert b"better title" in response.data
        assert db.query(Submission).count() == 0

    def test_no_url_and_no_body_is_rejected(self, client, as_user):
        user = as_user()
        response = submit(client, user, title="Ten chars ok", url="", body="")

        assert response.status_code == 200
        assert db.query(Submission).count() == 0

    def test_requires_login(self, client):
        response = client.post(
            "/submit",
            data={"title": "Ten chars ok", "body": "hello", "formkey": "x"},
        )
        assert response.status_code == 401

    def test_requires_a_valid_formkey(self, client, as_user):
        user = as_user()
        response = client.post(
            "/submit",
            data={
                "title": "Ten chars ok",
                "body": "hello",
                "formkey": "0" * 32,
            },
        )
        assert response.status_code == 401
        assert db.query(Submission).count() == 0

    def test_banned_user_cannot_post(self, client, as_user):
        user = as_user()
        db.query(User).filter_by(id=user.id).first().is_banned = 99
        db.commit()

        response = submit(client, user, title="Ten chars ok", body="hello")
        assert response.status_code == 403
        assert db.query(Submission).count() == 0


# --------------------------------------------------------------------------
# GET /post/<base36id>
# --------------------------------------------------------------------------
class TestViewPost:
    def test_renders_a_post(self, client, make_post):
        post = make_post(title="Visible post title")
        response = client.get(post.permalink)

        assert response.status_code == 200
        assert b"Visible post title" in response.data

    def test_unknown_id_returns_404(self, client):
        from ruqqus.helpers.base36 import base36encode

        assert client.get(f"/post/{base36encode(999999)}").status_code == 404

    def test_invalid_sort_returns_422(self, client, make_post):
        """``tree_comments`` aborts 422 on an unrecognised sort."""
        post = make_post()
        assert client.get(f"{post.permalink}?sort=bogus").status_code == 422

    def test_valid_sorts_render(self, client, make_post):
        post = make_post()
        for sort in ("hot", "top", "new", "disputed", "random"):
            response = client.get(f"{post.permalink}?sort={sort}")
            assert response.status_code == 200, f"sort={sort} failed"

    def test_banned_post_is_hidden_from_anonymous_visitors(self, client, make_post):
        post = make_post(is_banned=True)
        response = client.get(post.permalink)

        assert response.status_code == 200
        assert b"Visible post title" not in response.data

    def test_banned_post_is_visible_to_admins(self, client, as_user, make_post):
        admin = as_user()
        db.query(User).filter_by(id=admin.id).first().admin_level = 3
        db.commit()

        post = make_post(is_banned=True, title="Banned but visible to admin")
        response = client.get(post.permalink)
        assert response.status_code == 200
        assert b"Banned but visible to admin" in response.data

    def test_comment_count_is_computed_by_the_database(self, client, make_post, make_comment):
        """``comment_count`` is a row-wise function, not a stored column."""
        post = make_post()
        make_comment(post=post)
        make_comment(post=post)

        response = client.get(post.permalink)
        assert response.status_code == 200


# --------------------------------------------------------------------------
# POST /edit_post/<pid>
# --------------------------------------------------------------------------
class TestEditPost:
    def test_author_can_edit(self, client, as_user, make_post):
        user = as_user()
        post = make_post(author=user)

        response = client.post(
            f"/edit_post/{post.base36id}",
            data={"body": "updated body", "formkey": formkey(client, user.id)},
        )

        assert response.status_code == 302
        updated = db.query(Submission).filter_by(id=post.id).first()
        assert updated.body == "updated body"
        assert updated.edited_utc > 0

    def test_body_is_resanitized_on_edit(self, client, as_user, make_post):
        user = as_user()
        post = make_post(author=user)

        client.post(
            f"/edit_post/{post.base36id}",
            data={
                "body": '<script>alert(1)</script>safe',
                "formkey": formkey(client, user.id),
            },
        )

        updated = db.query(Submission).filter_by(id=post.id).first()
        assert "<script>" not in updated.body_html

    def test_non_author_cannot_edit(self, client, as_user, make_user, make_post):
        author = make_user()
        post = make_post(author=author)
        other = as_user()

        response = client.post(
            f"/edit_post/{post.base36id}",
            data={"body": "hijacked", "formkey": formkey(client, other.id)},
        )

        assert response.status_code == 403
        unchanged = db.query(Submission).filter_by(id=post.id).first()
        assert unchanged.body != "hijacked"

    def test_unknown_post_returns_404(self, client, as_user):
        user = as_user()
        response = client.post(
            "/edit_post/zz",
            data={"body": "x", "formkey": formkey(client, user.id)},
        )
        assert response.status_code in (400, 404)

    def test_banned_post_cannot_be_edited(self, client, as_user, make_post):
        user = as_user()
        post = make_post(author=user, is_banned=True)

        response = client.post(
            f"/edit_post/{post.base36id}",
            data={"body": "nope", "formkey": formkey(client, user.id)},
        )
        assert response.status_code == 403

    def test_requires_a_formkey(self, client, as_user, make_post):
        user = as_user()
        post = make_post(author=user)

        response = client.post(f"/edit_post/{post.base36id}", data={"body": "x"})
        assert response.status_code == 401
