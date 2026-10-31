"""
Voting on posts and comments.

Coverage of ``routes/votes.py``, ``Vote``/``CommentVote`` and the PostgreSQL
``ups()``/``downs()`` row-wise functions that tally them.
"""

from __future__ import annotations

from tests.conftest import db, formkey
from ruqqus.classes import Comment, CommentVote, Submission, User, Vote


def vote_post(client, user, post, x):
    return client.post(
        f"/api/vote/post/{post.base36id}/{x}",
        data={"formkey": formkey(client, user.id)},
    )


def vote_comment(client, user, comment, x):
    return client.post(
        f"/api/vote/comment/{comment.base36id}/{x}",
        data={"formkey": formkey(client, user.id)},
    )


# --------------------------------------------------------------------------
# POST /api/vote/post/<post_id>/<x>
# --------------------------------------------------------------------------
class TestPostVotes:
    def test_upvote_returns_204_and_records_a_vote(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        response = vote_post(client, user, post, 1)

        assert response.status_code == 204
        vote = db.query(Vote).filter_by(
            user_id=user.id, submission_id=post.id
        ).first()
        assert vote is not None
        assert vote.vote_type == 1

    def test_downvote_records_a_vote(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        vote_post(client, user, post, -1)

        vote = db.query(Vote).filter_by(
            user_id=user.id, submission_id=post.id
        ).first()
        assert vote.vote_type == -1

    def test_changing_a_vote_updates_the_same_row(self, client, as_user, make_post):
        user = as_user()
        post = make_post()

        vote_post(client, user, post, 1)
        vote_post(client, user, post, -1)

        votes = db.query(Vote).filter_by(
            user_id=user.id, submission_id=post.id
        ).all()
        assert len(votes) == 1
        assert votes[0].vote_type == -1

    def test_removing_a_vote_sets_it_to_zero(self, client, as_user, make_post):
        user = as_user()
        post = make_post()

        vote_post(client, user, post, 1)
        vote_post(client, user, post, 0)

        vote = db.query(Vote).filter_by(
            user_id=user.id, submission_id=post.id
        ).first()
        assert vote.vote_type == 0

    def test_votes_are_tallied_by_the_database(self, client, as_user, make_user, make_post):
        """``Submission.ups`` is ``ups(submissions)``, not a stored counter."""
        post = make_post()
        voter_a = as_user()
        voter_b = as_user(make_user())

        vote_post(client, voter_a, post, 1)
        vote_post(client, voter_b, post, 1)

        fresh = db.query(Submission).filter_by(id=post.id).first()
        assert fresh.ups == 2
        assert fresh.downs == 0

    def test_downvotes_are_counted_separately(self, client, as_user, make_user, make_post):
        post = make_post()
        vote_post(client, as_user(), post, 1)
        vote_post(client, as_user(make_user()), post, -1)

        fresh = db.query(Submission).filter_by(id=post.id).first()
        assert fresh.ups == 1
        assert fresh.downs == 1

    def test_score_is_ups_minus_downs(self, client, as_user, make_user, make_post):
        post = make_post()
        vote_post(client, as_user(), post, 1)
        vote_post(client, as_user(make_user()), post, 1)
        vote_post(client, as_user(make_user()), post, -1)

        fresh = db.query(Submission).filter_by(id=post.id).first()
        assert fresh.score == 1

    def test_each_user_gets_one_vote(self, client, as_user, make_post):
        user = as_user()
        post = make_post()

        vote_post(client, user, post, 1)
        vote_post(client, user, post, 1)
        vote_post(client, user, post, 1)

        assert db.query(Vote).filter_by(
            user_id=user.id, submission_id=post.id
        ).count() == 1


class TestPostVoteValidation:
    def test_invalid_vote_value_returns_400(self, client, as_user, make_post):
        user = as_user()
        assert vote_post(client, user, make_post(), 7).status_code == 400

    def test_unknown_post_returns_404(self, client, as_user):
        from ruqqus.helpers.base36 import base36encode

        user = as_user()
        response = client.post(
            f"/api/vote/post/{base36encode(999999)}/1",
            data={"formkey": formkey(client, user.id)},
        )
        assert response.status_code == 404

    def test_banned_post_cannot_be_voted_on(self, client, as_user, make_post):
        user = as_user()
        post = make_post(is_banned=True)

        assert vote_post(client, user, post, 1).status_code == 403

    def test_requires_login(self, client, make_post):
        post = make_post()
        response = client.post(
            f"/api/vote/post/{post.base36id}/1", data={"formkey": "x"}
        )
        assert response.status_code == 401

    def test_requires_a_valid_formkey(self, client, as_user, make_post):
        user = as_user()
        post = make_post()
        response = client.post(
            f"/api/vote/post/{post.base36id}/1",
            data={"formkey": "0" * 32},
        )
        assert response.status_code == 401
        assert db.query(Vote).count() == 0

    def test_banned_user_cannot_vote(self, client, as_user, make_post):
        user = as_user()
        db.query(User).filter_by(id=user.id).first().is_banned = 99
        db.commit()

        assert vote_post(client, user, make_post(), 1).status_code == 403


# --------------------------------------------------------------------------
# POST /api/vote/comment/<comment_id>/<x>
# --------------------------------------------------------------------------
class TestCommentVotes:
    def test_upvote_returns_204_and_records_a_vote(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post())
        response = vote_comment(client, user, target, 1)

        assert response.status_code == 204
        vote = db.query(CommentVote).filter_by(
            user_id=user.id, comment_id=target.id
        ).first()
        assert vote.vote_type == 1

    def test_changing_a_vote_updates_the_same_row(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post())

        vote_comment(client, user, target, 1)
        vote_comment(client, user, target, -1)

        votes = db.query(CommentVote).filter_by(
            user_id=user.id, comment_id=target.id
        ).all()
        assert len(votes) == 1
        assert votes[0].vote_type == -1

    def test_comment_votes_are_tallied_by_the_database(
        self, client, as_user, make_user, make_post, make_comment
    ):
        target = make_comment(post=make_post())
        vote_comment(client, as_user(), target, 1)
        vote_comment(client, as_user(make_user()), target, -1)

        fresh = db.query(Comment).filter_by(id=target.id).first()
        assert fresh.ups == 1
        assert fresh.downs == 1
        assert fresh.score == 0

    def test_invalid_vote_value_returns_400(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        assert vote_comment(client, user, make_comment(post=make_post()), 9).status_code == 400

    def test_unknown_comment_returns_404(self, client, as_user):
        from ruqqus.helpers.base36 import base36encode

        user = as_user()
        response = client.post(
            f"/api/vote/comment/{base36encode(999999)}/1",
            data={"formkey": formkey(client, user.id)},
        )
        assert response.status_code == 404

    def test_banned_comment_cannot_be_voted_on(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post(), is_banned=True)

        assert vote_comment(client, user, target, 1).status_code == 403

    def test_requires_a_valid_formkey(
        self, client, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post())
        response = client.post(
            f"/api/vote/comment/{target.base36id}/1",
            data={"formkey": "0" * 32},
        )
        assert response.status_code == 401
        assert db.query(CommentVote).count() == 0


# --------------------------------------------------------------------------
# Vote helpers on the User model
# --------------------------------------------------------------------------
class TestVoteStatusHelpers:
    def test_vote_status_on_post_reports_the_vote(self, as_user, make_post):
        user = as_user()
        post = make_post()
        db.add(Vote(user_id=user.id, vote_type=-1, submission_id=post.id))
        db.commit()

        fresh = db.query(User).filter_by(id=user.id).first()
        fresh_post = db.query(Submission).filter_by(id=post.id).first()
        assert fresh.vote_status_on_post(fresh_post) == -1

    def test_vote_status_on_post_is_zero_without_a_vote(self, as_user, make_post):
        user = as_user()
        post = make_post()

        fresh = db.query(User).filter_by(id=user.id).first()
        fresh_post = db.query(Submission).filter_by(id=post.id).first()
        assert fresh.vote_status_on_post(fresh_post) == 0

    def test_vote_status_on_comment_reports_the_vote(
        self, as_user, make_post, make_comment
    ):
        user = as_user()
        target = make_comment(post=make_post())
        db.add(CommentVote(user_id=user.id, vote_type=1, comment_id=target.id))
        db.commit()

        fresh = db.query(User).filter_by(id=user.id).first()
        fresh_comment = db.query(Comment).filter_by(id=target.id).first()
        assert fresh.vote_status_on_comment(fresh_comment) == 1
