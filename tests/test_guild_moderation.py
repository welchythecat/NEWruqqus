"""
Guild moderators moderating their own guild.

Two things are under test.

The permission rule itself lives in ``Submission.can_moderate`` and
``Comment.can_moderate``, and it is deliberately the *same* object that both
the endpoints and the moderation menus consult.  Before guilds the menu and the
route disagreed in both directions -- the post menu was drawn at
``admin_level >= 1`` while ``/api/ban_post`` required 3, so a level 1 moderator
saw a Remove button that 403'd, and the comment menu was drawn at
``admin_level >= 3`` while ``/api/ban_comment`` allowed 1, so a level 1
moderator could remove comments but was never shown the control.  A button you
can see is now always a button that works.

The second thing is what did *not* change.  Guild moderators are an addition to
the site-staff rules, not a widening of them: post moderation still requires
``admin_level >= 3`` of site staff, comment moderation still requires
``admin_level >= 1``, and a guild moderator's reach stops at their own guild's
boundary.  The regression tests at the bottom pin those thresholds so a future
refactor cannot quietly promote site moderators.
"""

from __future__ import annotations

from tests.conftest import db, formkey
from ruqqus.classes import Comment, Guild, GuildMember, Submission, User


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def post_as(client, user, path, **fields):
    """
    POST ``path`` while authenticated as ``user``.

    Logging in is not incidental -- it is what sets ``session["user_id"]``, and
    without it the route can only ever exercise its "not logged in" branch.
    """
    response = client.post(
        "/login",
        data={"username": user.username, "password": user.password, "redirect": "/"},
    )
    assert response.status_code == 302, (
        f"login failed for {user.username!r}: "
        f"{response.status_code} {response.data[:200]!r}"
    )

    payload = dict(fields)
    payload.setdefault("formkey", formkey(client, user.id))
    return client.post(path, data=payload)


def user_row(record) -> User:
    return db.query(User).filter_by(id=record.id).first()


def post_row(record) -> Submission:
    return db.query(Submission).filter_by(id=record.id).first()


def comment_row(record) -> Comment:
    return db.query(Comment).filter_by(id=record.id).first()


def promote(guild, user) -> None:
    """Give ``user`` an ``is_mod`` membership row in ``guild``."""
    row = (
        db.query(GuildMember)
        .filter_by(board_id=guild.id, user_id=user.id)
        .first()
    )
    if row is None:
        db.add(GuildMember(board_id=guild.id, user_id=user.id, is_mod=True))
    else:
        row.is_mod = True
    db.commit()


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------
class TestSubmissionCanModerate:
    def test_site_administrator_moderates_anywhere(self, make_user, make_post):
        admin = make_user(admin_level=3)
        assert post_row(make_post()).can_moderate(user_row(admin)) is True

    def test_site_level_two_cannot_moderate_posts(self, make_user, make_post):
        """Post moderation is level 3 for site staff.  Levels 1 and 2 are not 3."""
        mod = make_user(admin_level=2)
        assert post_row(make_post()).can_moderate(user_row(mod)) is False

    def test_site_level_one_cannot_moderate_posts(self, make_user, make_post):
        mod = make_user(admin_level=1)
        assert post_row(make_post()).can_moderate(user_row(mod)) is False

    def test_ordinary_user_moderates_nothing(self, make_user, make_post):
        user = make_user()
        assert post_row(make_post()).can_moderate(user_row(user)) is False

    def test_no_user_at_all_moderates_nothing(self, make_post):
        assert post_row(make_post()).can_moderate(None) is False

    def test_guild_moderator_moderates_their_own_guild(
        self, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="modme", creator=mod)
        post = make_post(guild=guild)

        assert post_row(post).can_moderate(user_row(mod)) is True

    def test_guild_moderator_cannot_moderate_another_guild(
        self, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="ownguild", creator=mod)
        other = make_guild(board_name="otherguild", creator=make_user())

        assert post_row(make_post(guild=other)).can_moderate(user_row(mod)) is False

    def test_guild_moderator_cannot_moderate_an_unfiled_post(
        self, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="ownguild", creator=mod)

        assert post_row(make_post()).can_moderate(user_row(mod)) is False

    def test_a_promoted_member_moderates_without_founding_the_guild(
        self, make_user, make_guild, make_post
    ):
        founder = make_user()
        guild = make_guild(board_name="promoteme", creator=founder)
        mod = make_user()
        promote(guild, mod)

        assert post_row(make_post(guild=guild)).can_moderate(user_row(mod)) is True

    def test_an_unpromoted_member_moderates_nothing(
        self, make_user, make_guild, make_post
    ):
        founder = make_user()
        guild = make_guild(board_name="plainmembers", creator=founder)
        member = make_user()
        db.add(GuildMember(board_id=guild.id, user_id=member.id, is_mod=False))
        db.commit()

        assert post_row(make_post(guild=guild)).can_moderate(user_row(member)) is False

    def test_the_founder_moderates_without_a_membership_row(
        self, make_user, make_guild, make_post
    ):
        """
        ``Guild.is_moderator`` honours ``created_by`` on its own.

        A guild can lose its membership rows -- a downgrade, a hand edit -- and
        still have a founder.  The founder does not stop being a moderator
        because of that, and this is what keeps the menu and the route in
        agreement about it.
        """
        founder = make_user()
        guild = make_guild(
            board_name="founderonly", creator=founder, founder_joins=False
        )

        assert post_row(make_post(guild=guild)).can_moderate(user_row(founder)) is True


class TestCommentCanModerate:
    def test_site_level_one_moderates_comments(self, make_user, make_post, make_comment):
        """Comment moderation is level 1 for site staff.  That is historical."""
        mod = make_user(admin_level=1)
        target = make_comment(post=make_post())

        assert comment_row(target).can_moderate(user_row(mod)) is True

    def test_ordinary_user_cannot_moderate_comments(
        self, make_user, make_post, make_comment
    ):
        user = make_user()
        target = make_comment(post=make_post())

        assert comment_row(target).can_moderate(user_row(user)) is False

    def test_no_user_at_all_cannot_moderate_comments(self, make_post, make_comment):
        assert comment_row(make_comment(post=make_post())).can_moderate(None) is False

    def test_guild_moderator_moderates_comments_under_their_guild(
        self, make_user, make_guild, make_post, make_comment
    ):
        mod = make_user()
        guild = make_guild(board_name="commentown", creator=mod)
        target = make_comment(post=make_post(guild=guild))

        assert comment_row(target).can_moderate(user_row(mod)) is True

    def test_guild_moderator_cannot_moderate_comments_under_another_guild(
        self, make_user, make_guild, make_post, make_comment
    ):
        mod = make_user()
        make_guild(board_name="commentmine", creator=mod)
        other = make_guild(board_name="commenttheirs", creator=make_user())
        target = make_comment(post=make_post(guild=other))

        assert comment_row(target).can_moderate(user_row(mod)) is False

    def test_guild_moderator_cannot_moderate_comments_under_an_unfiled_post(
        self, make_user, make_guild, make_post, make_comment
    ):
        mod = make_user()
        make_guild(board_name="commentnone", creator=mod)
        target = make_comment(post=make_post())

        assert comment_row(target).can_moderate(user_row(mod)) is False


# --------------------------------------------------------------------------
# The endpoints
# --------------------------------------------------------------------------
class TestGuildModeratorRoutes:
    def test_guild_moderator_can_remove_a_post_in_their_guild(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="removeme", creator=mod)
        post = make_post(guild=guild, title="Post to be removed")

        response = post_as(client, mod, f"/api/ban_post/{post.base36id}")

        assert response.status_code == 302
        banned = db.query(Submission).filter_by(id=post.id).first()
        assert banned.is_banned is True
        assert banned.is_approved == 0
        assert banned.stickied is False

    def test_guild_moderator_can_restore_a_post_in_their_guild(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="restoreme", creator=mod)
        post = make_post(guild=guild, is_banned=True)

        response = post_as(client, mod, f"/api/unban_post/{post.base36id}")

        assert response.status_code == 302
        restored = db.query(Submission).filter_by(id=post.id).first()
        assert restored.is_banned is False
        assert restored.is_approved == mod.id
        assert restored.approved_utc > 0

    def test_guild_moderator_cannot_remove_a_post_outside_their_guild(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="reachmine", creator=mod)
        other = make_guild(board_name="reachtheirs", creator=make_user())
        post = make_post(guild=other)

        response = post_as(client, mod, f"/api/ban_post/{post.base36id}")

        assert response.status_code == 403
        assert db.query(Submission).filter_by(id=post.id).first().is_banned is False

    def test_guild_moderator_cannot_remove_an_unfiled_post(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="reachnone", creator=mod)
        post = make_post()

        response = post_as(client, mod, f"/api/ban_post/{post.base36id}")

        assert response.status_code == 403

    def test_guild_moderator_cannot_restore_a_post_outside_their_guild(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="unreachmine", creator=mod)
        other = make_guild(board_name="unreachtheirs", creator=make_user())
        post = make_post(guild=other, is_banned=True)

        response = post_as(client, mod, f"/api/unban_post/{post.base36id}")

        assert response.status_code == 403
        assert db.query(Submission).filter_by(id=post.id).first().is_banned is True

    def test_guild_moderator_can_remove_a_comment_in_their_guild(
        self, client, make_user, make_guild, make_post, make_comment
    ):
        mod = make_user()
        guild = make_guild(board_name="commentremove", creator=mod)
        target = make_comment(post=make_post(guild=guild))

        response = post_as(client, mod, f"/api/ban_comment/{target.base36id}")

        assert response.status_code == 204
        banned = db.query(Comment).filter_by(id=target.id).first()
        assert banned.is_banned is True

    def test_guild_moderator_can_restore_a_comment_in_their_guild(
        self, client, make_user, make_guild, make_post, make_comment
    ):
        mod = make_user()
        guild = make_guild(board_name="commentrestore", creator=mod)
        target = make_comment(post=make_post(guild=guild), is_banned=True)

        response = post_as(client, mod, f"/api/unban_comment/{target.base36id}")

        assert response.status_code == 204
        restored = db.query(Comment).filter_by(id=target.id).first()
        assert restored.is_banned is False
        assert restored.is_approved == mod.id

    def test_guild_moderator_cannot_remove_a_comment_outside_their_guild(
        self, client, make_user, make_guild, make_post, make_comment
    ):
        mod = make_user()
        make_guild(board_name="commentreachmine", creator=mod)
        other = make_guild(board_name="commentreachtheirs", creator=make_user())
        target = make_comment(post=make_post(guild=other))

        response = post_as(client, mod, f"/api/ban_comment/{target.base36id}")

        assert response.status_code == 403
        assert db.query(Comment).filter_by(id=target.id).first().is_banned is False

    def test_the_moderation_menu_is_drawn_where_the_route_allows_it(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """
        The point of sharing one predicate: no button that 403's.
        """
        mod = make_user()
        guild = make_guild(board_name="menuworks", creator=mod)
        post = make_post(guild=guild, title="Post with a working menu")

        as_user(mod)
        page = client.get(post.permalink)
        assert page.status_code == 200
        assert b"moderate-post-" in page.data

    def test_the_moderation_menu_is_absent_where_the_route_forbids_it(
        self, client, as_user, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="menumine", creator=mod)
        other = make_guild(board_name="menutheirs", creator=make_user())
        post = make_post(guild=other, title="Post with no menu for this mod")

        as_user(mod)
        page = client.get(post.permalink)
        assert page.status_code == 200
        assert b"moderate-post-" not in page.data

    def test_an_ordinary_visitor_gets_no_moderation_menu(
        self, client, as_user, make_post
    ):
        post = make_post(title="Post with no menu for a bystander")

        as_user()
        page = client.get(post.permalink)
        assert page.status_code == 200
        assert b"moderate-post-" not in page.data


# --------------------------------------------------------------------------
# The scripts behind the buttons
#
# default.html used to load post_modding.js and comment_modding.js only when
# v.admin_level was set.  A guild moderator with admin_level 0 got a fully
# drawn menu whose buttons did nothing, because the click handlers were never
# on the page.  The menu and the endpoint are useless without these two
# <script> tags, so they are part of the same contract.
# --------------------------------------------------------------------------
class TestModerationScriptsLoad:
    def test_a_guild_moderator_gets_the_moderation_scripts(
        self, client, as_user, make_user, make_guild, make_post
    ):
        mod = make_user()  # admin_level 0 -- a guild moderator, not site staff
        guild = make_guild(board_name="scriptsguild", creator=mod)
        make_post(guild=guild)

        as_user(mod)
        page = client.get("/")

        assert page.status_code == 200
        assert b"/assets/js/post_modding.js" in page.data
        assert b"/assets/js/comment_modding.js" in page.data

    def test_an_ordinary_user_does_not_get_the_moderation_scripts(
        self, client, as_user, make_post
    ):
        make_post()
        as_user()

        page = client.get("/")

        assert page.status_code == 200
        assert b"/assets/js/post_modding.js" not in page.data
        assert b"/assets/js/comment_modding.js" not in page.data

    def test_a_site_moderator_still_gets_the_moderation_scripts(
        self, client, make_user, make_post
    ):
        """Level 1 is enough for comment moderation, so it is enough to load."""
        mod = make_user(admin_level=1)
        make_post()

        client.post(
            "/login",
            data={"username": mod.username, "password": mod.password, "redirect": "/"},
        )
        home = client.get("/")

        assert home.status_code == 200
        assert b"/assets/js/post_modding.js" in home.data


# --------------------------------------------------------------------------
# What did not change
#
# These are the pre-guild thresholds.  If one of them starts failing, a
# refactor has promoted or demoted site staff, and that needs a deliberate
# decision rather than an accident.
# --------------------------------------------------------------------------
class TestSiteStaffThresholdsUnchanged:
    def test_level_one_still_cannot_remove_posts(
        self, client, make_user, make_post
    ):
        mod = make_user(admin_level=1)
        post = make_post()

        assert post_as(client, mod, f"/api/ban_post/{post.base36id}").status_code == 403

    def test_level_two_still_cannot_remove_posts(self, client, make_user, make_post):
        mod = make_user(admin_level=2)
        post = make_post()

        assert post_as(client, mod, f"/api/ban_post/{post.base36id}").status_code == 403

    def test_level_three_still_removes_posts_anywhere(
        self, client, make_user, make_guild, make_post
    ):
        admin = make_user(admin_level=3)
        someone_elses = make_guild(board_name="nottheadminsguild", creator=make_user())
        post = make_post(guild=someone_elses)

        assert post_as(client, admin, f"/api/ban_post/{post.base36id}").status_code == 302

    def test_level_one_still_removes_comments_anywhere(
        self, client, make_user, make_guild, make_post, make_comment
    ):
        mod = make_user(admin_level=1)
        someone_elses = make_guild(board_name="notthemodsguild", creator=make_user())
        target = make_comment(post=make_post(guild=someone_elses))

        assert (
            post_as(client, mod, f"/api/ban_comment/{target.base36id}").status_code
            == 204
        )

    def test_anonymous_still_gets_401(self, client, make_post, make_comment):
        post = make_post()
        target = make_comment(post=post)

        for path in (
            f"/api/ban_post/{post.base36id}",
            f"/api/unban_post/{post.base36id}",
            f"/api/ban_comment/{target.base36id}",
            f"/api/unban_comment/{target.base36id}",
        ):
            assert client.post(path).status_code == 401, path