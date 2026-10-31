"""
The "my guilds" feed on the front page.

``/?feed=mine`` narrows ``/`` to the guilds the signed-in user has joined.
``/?feed=all``, or no parameter at all, is the historical global listing and is
unchanged.

Two things here are about more than filtering.

The personalisation argument reaches ``frontlist`` as a *parameter*.  That
function is ``@cache.memoize``'d, and a memoization key is built from the
arguments the function was called with.  If the user were read out of
``session`` inside the body instead, one user's personal feed would be stored
under a key every visitor shares and handed to strangers for the next 30
seconds.  The test suite runs with caching switched off, so the function is
recomputed on every request and that leak is invisible to every functional test
below -- which is why ``TestCacheKeyGuard`` pins the thing that actually
prevents it.

And once the feed is a query parameter, every sort link on the page is a place
that can silently drop it.  ``TestSortLinksKeepTheFeed`` covers each of them.
"""

from __future__ import annotations

import inspect
import re

from tests.conftest import db
from ruqqus.classes import Guild, GuildMember, Submission
from ruqqus.routes.front import frontlist


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def join(guild, user) -> None:
    """Put ``user`` in ``guild`` as an ordinary member."""
    db.add(GuildMember(board_id=guild.id, user_id=user.id, is_mod=False))
    db.commit()


def seed(make_user, make_guild, make_post):
    """
    Two users who share no guilds, one post each, plus an unfiled post.

    Returns ``(alice, bob, alice_post, bob_post, stray_post)``.
    """
    alice = make_user()
    bob = make_user()

    alice_guild = make_guild(board_name="alicesguild", creator=alice)
    bob_guild = make_guild(board_name="bobsguild", creator=bob)

    alice_post = make_post(guild=alice_guild, title="A post from Alice's guild")
    bob_post = make_post(guild=bob_guild, title="A post from Bob's guild")
    stray_post = make_post(title="A post filed nowhere at all")

    return alice, bob, alice_post, bob_post, stray_post


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------
class TestMyGuildsFeed:
    def test_it_shows_posts_from_your_guilds(
        self, client, as_user, make_user, make_guild, make_post
    ):
        alice, _, alice_post, _, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine")

        assert page.status_code == 200
        assert b"A post from Alice's guild" in page.data

    def test_it_hides_posts_from_guilds_you_are_not_in(
        self, client, as_user, make_user, make_guild, make_post
    ):
        alice, _, _, bob_post, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine")

        assert page.status_code == 200
        assert b"A post from Bob's guild" not in page.data

    def test_it_hides_unfiled_posts(
        self, client, as_user, make_user, make_guild, make_post
    ):
        alice, _, _, _, stray = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine")

        assert page.status_code == 200
        assert b"A post filed nowhere at all" not in page.data

    def test_two_users_get_different_feeds(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """
        The regression that matters most: one user's feed must not reach
        another.  Functionally this passes either way when the cache is off --
        see ``TestCacheKeyGuard`` for the structural half.
        """
        alice, bob, _, _, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        alice_page = client.get("/?feed=mine")
        as_user(bob)
        bob_page = client.get("/?feed=mine")

        assert b"A post from Alice's guild" in alice_page.data
        assert b"A post from Bob's guild" not in alice_page.data

        assert b"A post from Bob's guild" in bob_page.data
        assert b"A post from Alice's guild" not in bob_page.data

    def test_the_global_feed_is_unchanged(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """``/`` still shows everything, including posts filed nowhere."""
        alice, _, _, _, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/")

        assert page.status_code == 200
        assert b"A post from Alice's guild" in page.data
        assert b"A post from Bob's guild" in page.data
        assert b"A post filed nowhere at all" in page.data

    def test_a_member_who_is_not_a_moderator_still_gets_the_feed(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """Joining is enough.  The feed is not a moderator privilege."""
        alice = make_user()
        guild = make_guild(board_name="sharedguild", creator=make_user())
        member = make_user()
        join(guild, member)
        make_post(guild=guild, title="A post from a shared guild")

        as_user(member)
        page = client.get("/?feed=mine")

        assert page.status_code == 200
        assert b"A post from a shared guild" in page.data

    def test_it_needs_a_signed_in_user(self, client):
        """A personal feed with nobody to personalise it to is a 401."""
        assert client.get("/?feed=mine").status_code == 401

    def test_an_unknown_feed_is_a_422(self, client, as_user):
        as_user()
        assert client.get("/?feed=whatever").status_code == 422

    def test_the_explicit_all_feed_still_works(self, client, as_user, make_post):
        as_user()
        make_post(title="A post on the explicit all feed")

        page = client.get("/?feed=all")

        assert page.status_code == 200
        assert b"A post on the explicit all feed" in page.data


# --------------------------------------------------------------------------
# The sticky
# --------------------------------------------------------------------------
class TestStickyOnThePersonalFeed:
    def test_a_sticky_from_another_guild_does_not_head_the_personal_feed(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """
        A sticky is a site-wide announcement and is not necessarily filed
        under a guild the reader joined.  Putting it in a feed whose contract
        is "only my guilds" would break that contract.
        """
        alice = make_user()
        make_guild(board_name="stickyowns", creator=alice)
        make_guild(board_name="stickytheirs", creator=make_user())
        make_post(
            guild=db.query(Guild).filter_by(board_name="stickytheirs").first(),
            title="A pinned post from someone else's guild",
        )
        pinned = db.query(Submission).filter_by(
            title="A pinned post from someone else's guild"
        ).first()
        pinned.stickied = True
        db.commit()

        as_user(alice)
        page = client.get("/?feed=mine")

        assert page.status_code == 200
        assert b"A pinned post from someone else's guild" not in page.data

    def test_a_sticky_still_heads_the_global_front_page(
        self, client, as_user, make_user, make_guild, make_post
    ):
        make_guild(board_name="stickyglobal", creator=make_user())
        make_post(
            guild=db.query(Guild).filter_by(board_name="stickyglobal").first(),
            title="A pinned post on the front page",
        )
        pinned = db.query(Submission).filter_by(
            title="A pinned post on the front page"
        ).first()
        pinned.stickied = True
        db.commit()

        as_user()
        page = client.get("/")

        assert page.status_code == 200
        assert b"A pinned post on the front page" in page.data


# --------------------------------------------------------------------------
# Picking a sort must not lose the feed
# --------------------------------------------------------------------------
class TestSortLinksKeepTheFeed:
    def test_the_sort_links_carry_the_feed(
        self, client, as_user, make_user, make_guild, make_post
    ):
        alice, _, _, _, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine").data

        for sort in ("top", "new", "disputed", "activity"):
            assert re.search(
                rb"\?sort=" + sort.encode() + rb"(&amp;|&)feed=mine", page
            ), f"the {sort} link drops the feed"

    def test_the_hot_link_keeps_the_feed(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """"Hot" has no sort parameter of its own, so it is a whole href."""
        alice, _, _, _, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine").data

        assert re.search(rb'href="/\?feed=mine"', page)

    def test_the_pagination_links_carry_the_feed(
        self, client, as_user, make_user, make_guild, make_post
    ):
        alice, _, _, _, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine&page=2").data

        assert re.search(rb"\?sort=\w+(&amp;|&)feed=mine(&amp;|&)page=1", page)

    def test_picking_a_sort_keeps_the_feed_in_the_listing(
        self, client, as_user, make_user, make_guild, make_post
    ):
        alice, _, _, bob_post, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine&sort=new")

        assert page.status_code == 200
        assert b"A post from Alice's guild" in page.data
        assert b"A post from Bob's guild" not in page.data

    def test_the_all_posts_link_leaves_the_feed(
        self, client, as_user, make_user, make_guild, make_post
    ):
        """
        The way back out.  It must always point at ``/``, never at
        ``/?feed=mine``, or it would be a self-link on the personal feed --
        which is exactly what a blanket "replace href=/" did the first time.
        """
        alice, _, _, _, _ = seed(make_user, make_guild, make_post)

        as_user(alice)
        page = client.get("/?feed=mine").data

        line = next(
            (ln for ln in page.splitlines() if b"All posts" in ln),
            b"",
        )
        assert line, "the dashboard has no 'All posts' entry"
        assert b'href="/"' in line, f"'All posts' should link to /, got: {line!r}"
        assert b"feed=mine" not in line, (
            f"'All posts' must not carry the feed, got: {line!r}"
        )

    def test_the_dashboard_offers_the_feed(self, client, as_user, make_post):
        """The entry point has to exist on the global feed too."""
        as_user()
        make_post(title="A post to look at")

        page = client.get("/").data

        assert b"My guilds" in page
        assert re.search(rb'href="/\?feed=mine"', page)


# --------------------------------------------------------------------------
# The cache key
# --------------------------------------------------------------------------
class TestCacheKeyGuard:
    def test_frontlist_takes_the_user_as_an_argument(self):
        """
        This is the guard against cross-user cache leaks.

        ``@cache.memoize(timeout=30)`` builds its key from the arguments of the
        wrapped function.  A per-user filter only stays per-user if the user is
        one of those arguments; reading ``session`` inside the body would look
        exactly the same to every functional test above, because with
        ``CACHE_ENABLED=false`` the memoized function is recomputed on every
        call and nothing is ever stored or served.
        """
        target = getattr(frontlist, "__wrapped__", frontlist)
        params = inspect.signature(target).parameters

        assert "user_id" in params, (
            "frontlist() must take the user as an argument so the memoization "
            "key distinguishes one user's feed from another's"
        )
        assert params["user_id"].default is None, (
            "user_id must default to None so the unfiltered front page is its "
            "own cache entry rather than a per-user one"
        )

    def test_frontlist_returns_different_ids_for_different_users(
        self, make_user, make_guild, make_post
    ):
        """The parameter is honoured, not merely accepted."""
        alice, bob, alice_post, bob_post, _ = seed(make_user, make_guild, make_post)

        assert frontlist(sort="new", page=1, user_id=alice.id) == [alice_post.id]
        assert frontlist(sort="new", page=1, user_id=bob.id) == [bob_post.id]

    def test_frontlist_without_a_user_is_the_global_listing(
        self, make_user, make_guild, make_post
    ):
        _, _, alice_post, bob_post, stray = seed(make_user, make_guild, make_post)

        ids = frontlist(sort="new", page=1)

        assert stray.id in ids
        assert alice_post.id in ids
        assert bob_post.id in ids

    def test_frontlist_with_an_unknown_user_finds_nothing(
        self, make_user, make_guild, make_post
    ):
        """
        A user who has joined no guilds has an empty feed -- not the global one.

        Without this, a filter that silently matched everything would look
        like a working feed for every user who happened to be in a guild.
        """
        seed(make_user, make_guild, make_post)

        assert frontlist(sort="new", page=1, user_id=999999) == []