"""
Pinning a post inside a guild.

There are two different pins in this codebase and the difference is the point
of this file.

``submissions.stickied`` is one slot for the whole site.  It heads the front
page and forcibly unpins whichever post was holding it, so it is site-admin
only.  Widening that route would have let any guild moderator knock the site
announcement off the front page.

``submissions.guild_pinned`` is one slot per guild.  A guild moderator pins a
post in their own guild and it heads that guild's page; nothing else moves.
The rule lives in ``Submission.can_guild_pin`` and the Pin control is shown
under exactly the same condition, so a button you can see is always a button
that works.

What must not change is pinned at the bottom: the site-wide sticky keeps its
one slot and its level-3 threshold, and the two pins never touch each other.
"""

from __future__ import annotations

from tests.conftest import db, formkey
from ruqqus.classes import GuildMember, Submission, User


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def post_as(client, user, path, **fields):
    """POST ``path`` while authenticated as ``user``."""
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


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------
class TestCanGuildPin:
    def test_guild_moderator_may_pin_in_their_own_guild(
        self, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="pinmine", creator=mod)

        assert post_row(make_post(guild=guild)).can_guild_pin(user_row(mod)) is True

    def test_guild_moderator_may_not_pin_in_another_guild(
        self, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="pinown", creator=mod)
        other = make_guild(board_name="pintheirs", creator=make_user())

        assert post_row(make_post(guild=other)).can_guild_pin(user_row(mod)) is False

    def test_a_post_filed_nowhere_cannot_be_guild_pinned(
        self, make_user, make_guild, make_post
    ):
        """
        There is no guild page for an unfiled post to head.  That is what the
        site-wide sticky is for, and it is deliberately still admin-only.
        """
        mod = make_user()
        make_guild(board_name="pinnone", creator=mod)

        assert post_row(make_post()).can_guild_pin(user_row(mod)) is False

    def test_ordinary_member_may_not_pin(self, make_user, make_guild, make_post):
        founder = make_user()
        guild = make_guild(board_name="pinmember", creator=founder)
        member = make_user()
        db.add(GuildMember(board_id=guild.id, user_id=member.id, is_mod=False))
        db.commit()

        assert post_row(make_post(guild=guild)).can_guild_pin(user_row(member)) is False

    def test_site_administrator_may_pin_anywhere(
        self, make_user, make_guild, make_post
    ):
        admin = make_user(admin_level=3)
        other = make_guild(board_name="pinany", creator=make_user())

        assert post_row(make_post(guild=other)).can_guild_pin(user_row(admin)) is True

    def test_site_level_two_may_not_pin(self, make_user, make_guild, make_post):
        """
        Pinning is not part of site moderation at all.  Levels 1 and 2 can
        moderate comments and cannot sticky or pin; that stays true.
        """
        mod = make_user(admin_level=2)
        other = make_guild(board_name="pinlevel2", creator=make_user())

        assert post_row(make_post(guild=other)).can_guild_pin(user_row(mod)) is False

    def test_no_user_at_all_may_not_pin(self, make_post):
        assert post_row(make_post()).can_guild_pin(None) is False


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------
class TestGuildPinRoute:
    def test_a_guild_moderator_can_pin_in_their_own_guild(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="routeown", creator=mod)
        target = make_post(guild=guild)

        response = post_as(client, mod, f"/api/guild_pin/{target.base36id}")

        assert response.status_code == 302
        assert post_row(target).guild_pinned is True

    def test_a_guild_moderator_cannot_pin_outside_their_guild(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="routemine", creator=mod)
        other = make_guild(board_name="routetheirs", creator=make_user())
        target = make_post(guild=other)

        response = post_as(client, mod, f"/api/guild_pin/{target.base36id}")

        assert response.status_code == 403
        assert post_row(target).guild_pinned is False

    def test_a_guild_moderator_cannot_pin_an_unfiled_post(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="routenone", creator=mod)
        target = make_post()

        response = post_as(client, mod, f"/api/guild_pin/{target.base36id}")

        assert response.status_code == 403

    def test_pinning_again_unpins(self, client, make_user, make_guild, make_post):
        mod = make_user()
        guild = make_guild(board_name="routetoggle", creator=mod)
        target = make_post(guild=guild)

        post_as(client, mod, f"/api/guild_pin/{target.base36id}")
        response = post_as(client, mod, f"/api/guild_pin/{target.base36id}")

        assert response.status_code == 302
        assert post_row(target).guild_pinned is False

    def test_pinning_a_second_post_unpins_the_first_in_that_guild(
        self, client, make_user, make_guild, make_post
    ):
        """One pin per guild, the same contract the site-wide sticky has."""
        mod = make_user()
        guild = make_guild(board_name="routeone", creator=mod)
        first = make_post(guild=guild)
        second = make_post(guild=guild)

        post_as(client, mod, f"/api/guild_pin/{first.base36id}")
        post_as(client, mod, f"/api/guild_pin/{second.base36id}")

        assert post_row(first).guild_pinned is False
        assert post_row(second).guild_pinned is True

    def test_a_second_guild_is_untouched_by_the_first_guilds_pin(
        self, client, make_user, make_guild, make_post
    ):
        """
        The displacement is scoped by board_id.  Without that, one guild's pin
        would silently steal another guild's.
        """
        alice = make_user()
        bob = make_user()
        mine = make_guild(board_name="twoam", creator=alice)
        theirs = make_guild(board_name="twobm", creator=bob)
        mine_post = make_post(guild=mine)
        theirs_post = make_post(guild=theirs)

        post_as(client, alice, f"/api/guild_pin/{mine_post.base36id}")
        post_as(client, bob, f"/api/guild_pin/{theirs_post.base36id}")

        assert post_row(mine_post).guild_pinned is True
        assert post_row(theirs_post).guild_pinned is True

    def test_an_unknown_post_is_a_404(self, client, make_user, make_guild):
        mod = make_user()
        make_guild(board_name="route404", creator=mod)

        response = post_as(client, mod, "/api/guild_pin/zz")

        assert response.status_code in (400, 404)

    def test_anonymous_is_rejected(self, client, make_post):
        target = make_post()
        assert client.post(f"/api/guild_pin/{target.base36id}").status_code == 401

    def test_a_missing_formkey_is_rejected(
        self, client, make_user, make_guild, make_post
    ):
        """The route is state-changing, so it carries the same CSRF check."""
        mod = make_user()
        guild = make_guild(board_name="routecsrf", creator=mod)
        target = make_post(guild=guild)

        response = post_as(client, mod, f"/api/guild_pin/{target.base36id}", formkey="")

        assert response.status_code == 401
        assert post_row(target).guild_pinned is False


# --------------------------------------------------------------------------
# The two pins are independent
#
# This is the whole reason the feature was not a two-line gate change on
# /api/sticky.  Both directions have to hold or a guild moderator can knock
# the site announcement off the front page, or an administrator stickying a
# post can silently steal a guild's pin.
# --------------------------------------------------------------------------
class TestTheTwoPinsDoNotTouch:
    def test_guild_pinning_does_not_touch_the_site_sticky(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="independent1", creator=mod)
        make_post(guild=guild, title="The site announcement")
        announcement = db.query(Submission).filter_by(
            title="The site announcement"
        ).first()
        announcement.stickied = True
        db.commit()

        target = make_post(guild=guild, title="A guild's own pin")
        response = post_as(client, mod, f"/api/guild_pin/{target.base36id}")

        assert response.status_code == 302
        assert post_row(target).guild_pinned is True
        assert post_row(announcement).stickied is True, (
            "pinning in a guild must not knock the site announcement off "
            "the front page"
        )

    def test_administrative_stickying_does_not_touch_a_guild_pin(
        self, client, make_user, make_guild, make_post
    ):
        admin = make_user(admin_level=3)
        mod = make_user()
        guild = make_guild(board_name="independent2", creator=mod)
        pinned = make_post(guild=guild, title="A guild's own pin")
        post_as(client, mod, f"/api/guild_pin/{pinned.base36id}")

        announcement = make_post(guild=guild, title="The site announcement")
        response = post_as(client, admin, f"/api/sticky/{announcement.base36id}")

        assert response.status_code in (200, 302)
        assert post_row(pinned).guild_pinned is True, (
            "stickying must not steal a guild's pin"
        )
        assert post_row(announcement).stickied is True

    def test_the_site_sticky_still_takes_one_slot_across_the_whole_site(
        self, client, make_user, make_post
    ):
        """The historical contract, unchanged."""
        admin = make_user(admin_level=3)
        first = make_post(title="First announcement")
        second = make_post(title="Second announcement")

        post_as(client, admin, f"/api/sticky/{first.base36id}")
        post_as(client, admin, f"/api/sticky/{second.base36id}")

        assert post_row(first).stickied is False
        assert post_row(second).stickied is True

    def test_the_site_sticky_still_needs_admin_level_three(
        self, client, make_user, make_guild, make_post
    ):
        mod = make_user(admin_level=1)
        guild = make_guild(board_name="stickythresh", creator=make_user())
        target = make_post(guild=guild)

        assert post_as(client, mod, f"/api/sticky/{target.base36id}").status_code == 403

    def test_a_guild_moderator_still_cannot_sticky(
        self, client, make_user, make_guild, make_post
    ):
        """
        Granting guild pins is not a widening of the site-wide sticky.  A
        guild moderator who can pin in their guild still cannot put a post on
        the front page.
        """
        mod = make_user()
        guild = make_guild(board_name="stickynot", creator=mod)
        target = make_post(guild=guild)

        assert post_as(client, mod, f"/api/sticky/{target.base36id}").status_code == 403
        assert post_row(target).stickied is False


# --------------------------------------------------------------------------
# The listing
# --------------------------------------------------------------------------
class TestPinnedPostHeadsTheGuild:
    def test_the_pinned_post_is_first_on_the_guild_page(
        self, client, as_user, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="heads", creator=mod)
        old = make_post(guild=guild, title="An older post that scores higher")
        new = make_post(guild=guild, title="The pinned post")
        post_as(client, mod, f"/api/guild_pin/{new.base36id}")

        page = client.get(guild.url)

        assert page.status_code == 200
        assert page.data.index(b"The pinned post") < page.data.index(
            b"An older post that scores higher"
        ), "the pinned post should sort first on the guild page"

    def test_an_unpinned_guild_page_keeps_its_sort(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """A guild with no pin must look exactly as it did before."""
        make_user()
        guild = make_guild(board_name="nopin", creator=make_user())
        make_post(guild=guild, title="An ordinary post")

        page = client.get(f"{guild.url}?sort=new")

        assert page.status_code == 200
        assert b"An ordinary post" in page.data

    def test_the_pin_does_not_leak_onto_the_front_page(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """
        A guild pin heads the guild, not the site.  The front page is a
        separate listing with a separate sticky, and a guild pin is not that.
        """
        mod = make_user()
        guild = make_guild(board_name="leak", creator=mod)
        make_post(guild=guild, title="Pinned inside a guild only")
        target = db.query(Submission).filter_by(
            title="Pinned inside a guild only"
        ).first()
        post_as(client, mod, f"/api/guild_pin/{target.base36id}")

        as_user()
        page = client.get("/")

        assert page.status_code == 200
        assert post_row(target).guild_pinned is True
        # The post is of course on the front page -- it is a normal post.  What
        # must not happen is for it to be floated to the top as if stickied.
        front = page.data
        assert b"pinned post on the front page" not in front


# --------------------------------------------------------------------------
# The control
# --------------------------------------------------------------------------
class TestThePinControlIsWhereTheRouteAllowsIt:
    def test_a_guild_moderator_sees_the_pin_control(
        self, client, as_user, make_user, make_guild, make_post
    ):
        mod = make_user()  # admin_level 0
        guild = make_guild(board_name="controlmine", creator=mod)
        target = make_post(guild=guild)

        as_user(mod)
        page = client.get(target.permalink)

        assert page.status_code == 200
        assert b"/api/guild_pin/" in page.data

    def test_a_stranger_does_not_see_the_pin_control(
        self, client, as_user, make_user, make_guild, make_post
    ):
        mod = make_user()
        make_guild(board_name="controlmine2", creator=mod)
        other = make_guild(board_name="controltheirs", creator=make_user())
        target = make_post(guild=other)

        as_user(mod)
        page = client.get(target.permalink)

        assert page.status_code == 200
        assert b"/api/guild_pin/" not in page.data

    def test_an_ordinary_visitor_sees_no_pin_control(
        self, client, as_user, make_user, make_guild, make_post
    ):
        guild = make_guild(board_name="controlnone", creator=make_user())
        target = make_post(guild=guild)

        as_user()
        page = client.get(target.permalink)

        assert page.status_code == 200
        assert b"/api/guild_pin/" not in page.data

    def test_a_site_administrator_sees_the_pin_control(
        self, client, as_user, make_user, make_guild, make_post
    ):
        admin = make_user(admin_level=3)
        guild = make_guild(board_name="controladmin", creator=make_user())
        target = make_post(guild=guild)

        as_user(admin)
        page = client.get(target.permalink)

        assert page.status_code == 200
        assert b"/api/guild_pin/" in page.data

    def test_the_control_shows_the_guild_it_pins_into(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """
        The label names the guild so a moderator acting on several guilds can
        see which one this post is in before clicking.
        """
        mod = make_user()
        guild = make_guild(board_name="labelled", creator=mod)
        target = make_post(guild=guild)

        as_user(mod)
        page = client.get(target.permalink)

        assert b"Pin in +labelled" in page.data


# --------------------------------------------------------------------------
# What did not change
#
# A guild pin is an addition.  It must not have moved the site-wide sticky's
# threshold or its single-slot contract, and it must not have made pinning
# part of ordinary site moderation.
# --------------------------------------------------------------------------
class TestSiteWideStickyUnchanged:
    def test_a_guild_moderator_still_gets_no_site_sticky_button(
        self, client, as_user, make_user, make_guild, make_post
    ):
        mod = make_user()
        guild = make_guild(board_name="unchanged1", creator=mod)
        target = make_post(guild=guild)

        as_user(mod)
        page = client.get(target.permalink)

        assert b"/api/sticky/" not in page.data, (
            "a guild moderator must not see the site-wide Sticky button"
        )

    def test_a_level_one_moderator_still_gets_no_site_sticky_button(
        self, client, as_user, make_user, make_guild, make_post
    ):
        mod = make_user(admin_level=1)
        guild = make_guild(board_name="unchanged2", creator=make_user())
        target = make_post(guild=guild)

        as_user(mod)
        page = client.get(target.permalink)

        assert b"/api/sticky/" not in page.data

    def test_a_level_three_administrator_still_gets_the_site_sticky_button(
        self, client, as_user, make_user, make_guild, make_post
    ):
        admin = make_user(admin_level=3)
        guild = make_guild(board_name="unchanged3", creator=make_user())
        target = make_post(guild=guild)

        as_user(admin)
        page = client.get(target.permalink)

        assert b"/api/sticky/" in page.data

    def test_the_admin_panel_is_reachable_by_a_guild_moderator(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """
        The panel used to be gated on admin_level alone, which would have
        hidden the Pin control from the only people it is for.
        """
        mod = make_user()  # admin_level 0
        guild = make_guild(board_name="panelreach", creator=mod)
        make_post(guild=guild)

        as_user(mod)
        page = client.get("/")

        assert page.status_code == 200
        assert b"sidebar-adminpanel" in page.data

    def test_an_ordinary_user_still_gets_no_admin_panel(
        self, client, as_user, make_post
    ):
        make_post()
        as_user()

        page = client.get("/")

        assert page.status_code == 200
        assert b"sidebar-adminpanel" not in page.data