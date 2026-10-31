"""
Tests for guilds -- the communities that posts are filed under.

Model-level behaviour lives here.  Once the routes land, the request-level
contract (``GET /+<name>``, join/leave, moderator powers) goes in its own
class further down this file.

Background on what is historical and what is new is in
MIGRATION_NOTES.md §5: ``boards`` and ``submissions.board_id`` mirror the
original schema, while ``board_members`` -- membership and per-guild
moderators -- is an addition, not a restoration.
"""

import pytest

from tests.conftest import db, formkey
from ruqqus.classes import Guild, GuildMember, Submission, User


class TestGuildIdentity:
    """Names, URLs and the fullname prefix."""

    def test_table_names_match_the_historical_schema(self, make_guild):
        """
        ``boards`` and ``board_members`` are not typos.

        The original schema called the guild table ``boards``; keeping that
        name is what lets a database that still has the old table keep its
        guilds through an upgrade.  See MIGRATION_NOTES.md §5.
        """
        assert Guild.__tablename__ == "boards"
        assert GuildMember.__tablename__ == "board_members"

    def test_url_scheme_is_plus_name(self, make_guild):
        # /+name was the scheme picked for guild URLs.
        guild = make_guild(board_name="photography")
        assert guild.url == "/+photography"
        assert guild.permalink == "/+photography"

    def test_url_uses_the_board_name_not_the_id(self, make_guild):
        guild = make_guild(board_name="asciionly")
        assert guild.url == "/+asciionly"
        assert str(guild.id) not in guild.url

    def test_fullname_uses_the_free_t_prefix(self, make_guild):
        """
        t1_ is User, t2_ Submission, t3_ Comment, so t4_ is the next free one.

        The underscore-delimited prefix is what ``fullname`` parsing relies on
        to tell object types apart, so a guild must not collide with a user,
        submission or comment of the same id.
        """
        guild = make_guild()
        assert guild.fullname.startswith("t4_")
        assert not guild.fullname.startswith(("t1_", "t2_", "t3_"))

    def test_fullname_round_trips_through_base36(self, make_guild):
        guild = make_guild()
        assert guild.fullname == f"t4_{guild.base36id}"

    def test_fullnames_do_not_collide_across_types(self, make_guild, make_post):
        """
        A guild, a post and a user that happen to share a numeric id must
        still produce different fullnames.
        """
        guild = make_guild()
        post = make_post()

        assert guild.fullname != post.fullname

        if guild.id == post.id:
            # The interesting case: same number, different type.
            assert guild.base36id == post.base36id
            assert guild.fullname.split("_", 1)[0] != post.fullname.split("_", 1)[0]

    def test_board_name_is_unique(self, make_guild):
        make_guild(board_name="taken")
        with pytest.raises(Exception):
            db.add(Guild(board_name="taken", created_by=None))
            db.commit()
        db.rollback()

    def test_created_utc_is_stamped_by_the_constructor(self, make_guild):
        guild = make_guild()
        row = db.query(Guild).filter_by(id=guild.id).first()
        assert row.created_utc > 0


class TestGuildMembership:
    """Joining, leaving, and counting."""

    def test_founder_is_a_member_when_they_join(self, make_guild, make_user):
        creator = make_user()
        guild = make_guild(creator=creator)
        assert guild_member_count(guild.id) == 1
        assert is_member(guild.id, creator.id)

    def test_founder_may_opt_out_of_membership(self, make_guild, make_user):
        creator = make_user()
        guild = make_guild(creator=creator, founder_joins=False)
        assert guild_member_count(guild.id) == 0
        assert not is_member(guild.id, creator.id)

    def test_members_are_counted(self, make_guild, make_user):
        creator = make_user()
        guild = make_guild(creator=creator)
        for _ in range(3):
            join(guild.id, make_user().id)
        assert guild_member_count(guild.id) == 4

    def test_non_members_are_not_members(self, make_guild, make_user):
        guild = make_guild()
        outsider = make_user()
        assert not is_member(guild.id, outsider.id)

    def test_membership_row_is_unique_per_user_and_guild(self, make_guild, make_user):
        guild = make_guild()
        user = make_user()
        join(guild.id, user.id)

        with pytest.raises(Exception):
            join(guild.id, user.id)
        db.rollback()

    def test_the_same_user_may_join_two_guilds(self, make_guild, make_user):
        user = make_user()
        first = make_guild(board_name="first")
        second = make_guild(board_name="second")

        join(first.id, user.id)
        join(second.id, user.id)

        assert is_member(first.id, user.id)
        assert is_member(second.id, user.id)

    def test_leaving_removes_the_membership(self, make_guild, make_user):
        guild = make_guild()
        user = make_user()
        join(guild.id, user.id)
        assert is_member(guild.id, user.id)
        assert guild_member_count(guild.id) == 2  # founder plus this user

        leave(guild.id, user.id)
        assert not is_member(guild.id, user.id)
        # Leaving removes this user's membership row and nothing else: the
        # founder is still a member.
        assert guild_member_count(guild.id) == 1

    def test_an_empty_guild_counts_zero(self, make_guild):
        guild = make_guild(founder_joins=False)
        assert guild_member_count(guild.id) == 0


class TestGuildModeration:
    """Per-guild moderators, as distinct from site admins."""

    def test_founder_moderates(self, make_guild, make_user):
        creator = make_user()
        guild = make_guild(creator=creator)
        assert is_moderator(guild.id, creator.id)

    def test_founder_moderates_without_a_membership_row(self, make_guild, make_user):
        """
        The founder moderates regardless of the membership row, so a founder
        who left the guild still runs it.  Deliberate: it is the one tie that
        cannot be broken by kicking everyone out.
        """
        creator = make_user()
        guild = make_guild(creator=creator, founder_joins=False)
        assert not is_member(guild.id, creator.id)
        assert is_moderator(guild.id, creator.id)

    def test_ordinary_members_do_not_moderate(self, make_guild, make_user):
        guild = make_guild()
        member = make_user()
        join(guild.id, member.id)
        assert is_member(guild.id, member.id)
        assert not is_moderator(guild.id, member.id)

    def test_outsiders_do_not_moderate(self, make_guild, make_user):
        guild = make_guild()
        assert not is_moderator(guild.id, make_user().id)

    def test_a_moderator_of_one_guild_is_not_moderator_of_another(
        self, make_guild, make_user
    ):
        """
        Per-guild moderation is scoped to the guild.  This is the whole point
        of the feature: a moderator of /+photography has no power in /+cooking.
        """
        user = make_user()
        first = make_guild(board_name="photography")
        second = make_guild(board_name="cooking")

        join(first.id, user.id)
        promote(first.id, user.id)

        assert is_moderator(first.id, user.id)
        assert not is_moderator(second.id, user.id)

    def test_promotion_takes_effect(self, make_guild, make_user):
        guild = make_guild()
        user = make_user()
        join(guild.id, user.id)
        assert not is_moderator(guild.id, user.id)

        promote(guild.id, user.id)
        assert is_moderator(guild.id, user.id)

    def test_demotion_takes_effect(self, make_guild, make_user):
        guild = make_guild()
        user = make_user()
        join(guild.id, user.id)
        promote(guild.id, user.id)

        demote(guild.id, user.id)
        assert not is_moderator(guild.id, user.id)
        # Demotion keeps them a member -- it strips the badge, not the membership.
        assert is_member(guild.id, user.id)

    def test_moderator_list_includes_the_founder(self, make_guild, make_user):
        creator = make_user()
        guild = make_guild(creator=creator)
        assert moderator_names(guild.id) == [creator.username]

    def test_moderator_list_includes_the_founder_even_with_no_rows(
        self, make_guild, make_user
    ):
        # The founder is picked up from created_by, not from the membership
        # rows, so the list is not empty just because nobody joined.
        creator = make_user()
        guild = make_guild(creator=creator, founder_joins=False)
        assert guild_member_count(guild.id) == 0
        assert moderator_names(guild.id) == [creator.username]

    def test_moderator_list_has_no_duplicates_for_a_promoted_founder(
        self, make_guild, make_user
    ):
        """
        The founder is listed from ``created_by`` as well as from the
        membership rows, so promoting them must not list them twice.
        """
        creator = make_user()
        guild = make_guild(creator=creator)
        promote(guild.id, creator.id)
        assert moderator_names(guild.id) == [creator.username]

    def test_moderator_list_includes_promoted_members(self, make_guild, make_user):
        creator = make_user()
        guild = make_guild(creator=creator)
        mod = make_user()
        join(guild.id, mod.id)
        promote(guild.id, mod.id)

        assert sorted(moderator_names(guild.id)) == sorted(
            [creator.username, mod.username]
        )

    def test_moderator_list_on_a_founderless_guild(self, make_guild):
        """
        ``created_by`` is nullable, so a guild can have no owner at all.

        No route builds one of these, but ``Guild.moderators`` has to survive
        it rather than dereferencing None when it looks the founder up.
        """
        guild = make_guild(founderless=True)
        assert guild_member_count(guild.id) == 0
        assert moderator_names(guild.id) == []


class TestGuildPosts:
    """How posts are filed under a guild."""

    def test_a_post_carries_its_guild(self, make_guild, make_post):
        guild = make_guild()
        post = make_post(guild=guild)
        assert post.board_id == guild.id

    def test_a_post_without_a_guild_is_valid(self, make_post):
        # Nullable on purpose: posts made before guilds existed, and posts
        # filed nowhere, both have to keep working.
        post = make_post()
        assert post.board_id is None

    def test_posts_are_counted_per_guild(self, make_guild, make_post):
        guild = make_guild()
        for _ in range(3):
            make_post(guild=guild)
        make_post()  # filed nowhere

        assert guild_post_count(guild.id) == 3

    def test_banned_posts_are_not_counted(self, make_guild, make_post):
        guild = make_guild()
        make_post(guild=guild)
        make_post(guild=guild, is_banned=True)

        assert guild_post_count(guild.id) == 1

    def test_two_guilds_keep_their_posts_apart(self, make_guild, make_post):
        first = make_guild(board_name="first")
        second = make_guild(board_name="second")
        make_post(guild=first)
        make_post(guild=second)

        assert guild_post_count(first.id) == 1
        assert guild_post_count(second.id) == 1


# --------------------------------------------------------------------------
# The request contract
# --------------------------------------------------------------------------
class TestGuildRoutes:
    """Browsing, creating, joining and moderating over HTTP."""

    # -- browsing ---------------------------------------------------------

    def test_the_directory_renders(self, client, as_user):
        as_user()
        response = client.get("/guilds")
        assert response.status_code == 200

    def test_the_directory_lists_a_guild(self, client, as_user, make_guild):
        as_user()
        make_guild(board_name="photography")

        response = client.get("/guilds")
        assert response.status_code == 200
        assert b"+photography" in response.data

    def test_the_directory_is_visible_without_an_account(self, client, make_guild):
        make_guild(board_name="photography")
        response = client.get("/guilds")
        assert response.status_code == 200
        assert b"+photography" in response.data

    def test_the_directory_hides_banned_guilds(self, client, as_user, make_guild):
        as_user()
        guild = make_guild(board_name="photography")
        db.query(Guild).filter_by(id=guild.id).update({"is_banned": True})
        db.commit()

        response = client.get("/guilds")
        assert response.status_code == 200
        assert b"+photography" not in response.data

    def test_the_guild_page_renders(self, client, as_user, make_guild):
        as_user()
        make_guild(board_name="photography")

        response = client.get("/+photography")
        assert response.status_code == 200
        assert b"+photography" in response.data

    def test_the_guild_page_404s_for_an_unknown_guild(self, client, as_user):
        as_user()
        assert client.get("/+doesnotexist").status_code == 404

    def test_the_guild_page_404s_without_an_account(self, client, make_guild):
        make_guild(board_name="photography")
        assert client.get("/+doesnotexist").status_code == 404

    def test_the_guild_page_shows_only_its_own_posts(
        self, client, as_user, make_guild, make_post
    ):
        as_user()
        guild = make_guild(board_name="photography")
        mine = make_post(guild=guild, title="A post that belongs in the guild")
        make_post(title="A post filed nowhere at all")

        response = client.get("/+photography")
        assert response.status_code == 200
        assert b"A post that belongs in the guild" in response.data
        assert b"A post filed nowhere at all" not in response.data
        assert mine.board_id == guild.id

    def test_the_guild_page_shows_the_moderator(
        self, client, as_user, make_guild, make_user
    ):
        creator = make_user()
        as_user()
        make_guild(board_name="photography", creator=creator)

        response = client.get("/+photography")
        assert response.status_code == 200
        assert creator.username.encode() in response.data

    # -- creating ---------------------------------------------------------

    def test_the_create_form_renders(self, client, as_user):
        as_user()
        assert client.get("/create_guild").status_code == 200

    def test_creating_a_guild_makes_one(self, client, as_user, make_user):
        creator = make_user()
        as_user(creator)

        response = client.post(
            "/create_guild",
            data={"name": "photography", "description": "Pictures.",
                  "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/+photography")

        guild = db.query(Guild).filter_by(board_name="photography").first()
        assert guild is not None
        assert guild.created_by == creator.id
        assert guild.description == "Pictures."

    def test_the_founder_is_a_member_and_a_moderator(
        self, client, as_user, make_user
    ):
        creator = make_user()
        as_user(creator)
        client.post(
            "/create_guild",
            data={"name": "photography", "formkey": formkey(client, creator.id)},
        )

        guild = db.query(Guild).filter_by(board_name="photography").first()
        assert is_member(guild.id, creator.id)
        assert is_moderator(guild.id, creator.id)

    def test_anyone_may_create_a_guild(self, client, as_user, make_user):
        # No approval step and no privilege: an ordinary account can do this.
        ordinary = make_user()
        assert ordinary.admin_level == 0

        as_user(ordinary)
        response = client.post(
            "/create_guild",
            data={"name": "photography", "formkey": formkey(client, ordinary.id)},
        )
        assert response.status_code == 302

    def test_a_bad_name_is_rejected(self, client, as_user, make_user):
        for bad in ("ab", "has spaces", "has-dash", "x" * 33, "", "a/b"):
            creator = make_user()
            as_user(creator)
            response = client.post(
                "/create_guild",
                data={"name": bad, "formkey": formkey(client, creator.id)},
            )
            assert response.status_code == 422, f"{bad!r} was accepted"
            assert not db.query(Guild).filter_by(board_name=bad).first()

    def test_a_taken_name_is_rejected(self, client, as_user, make_user, make_guild):
        make_guild(board_name="photography")

        creator = make_user()
        as_user(creator)
        response = client.post(
            "/create_guild",
            data={"name": "photography", "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 422
        assert db.query(Guild).filter_by(board_name="photography").count() == 1

    def test_creating_without_a_formkey_is_rejected(self, client, as_user, make_user):
        creator = make_user()
        as_user(creator)
        response = client.post("/create_guild", data={"name": "photography"})
        assert response.status_code == 401
        assert not db.query(Guild).filter_by(board_name="photography").first()

    def test_the_create_form_echoes_what_you_typed(
        self, client, as_user, make_user, make_guild
    ):
        # A validation error must not blank the form and lose the input.
        make_guild(board_name="photography")

        creator = make_user()
        as_user(creator)
        response = client.post(
            "/create_guild",
            data={"name": "photography", "description": "My thoughts",
                  "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 422
        assert b"My thoughts" in response.data

    # -- joining and leaving ----------------------------------------------

    def test_joining_makes_a_member(self, client, as_user, make_guild, make_user):
        guild = make_guild(board_name="photography", founder_joins=False)
        member = make_user()
        as_user(member)

        response = client.post(
            "/+photography/join",
            data={"formkey": formkey(client, member.id)},
        )
        assert response.status_code == 302
        assert is_member(guild.id, member.id)

    def test_joining_twice_is_harmless(
        self, client, as_user, make_guild, make_user
    ):
        guild = make_guild(board_name="photography", founder_joins=False)
        member = make_user()
        as_user(member)

        for _ in range(2):
            client.post(
                "/+photography/join",
                data={"formkey": formkey(client, member.id)},
            )

        assert guild_member_count(guild.id) == 1

    def test_leaving_removes_the_membership(
        self, client, as_user, make_guild, make_user
    ):
        guild = make_guild(board_name="photography", founder_joins=False)
        member = make_user()
        as_user(member)
        client.post("/+photography/join", data={"formkey": formkey(client, member.id)})
        assert is_member(guild.id, member.id)

        response = client.post(
            "/+photography/leave",
            data={"formkey": formkey(client, member.id)},
        )
        assert response.status_code == 302
        assert not is_member(guild.id, member.id)

    def test_joining_an_unknown_guild_404s(self, client, as_user, make_user):
        member = make_user()
        as_user(member)
        response = client.post(
            "/+doesnotexist/join", data={"formkey": formkey(client, member.id)}
        )
        assert response.status_code == 404

    def test_joining_requires_a_formkey(self, client, as_user, make_guild, make_user):
        guild = make_guild(board_name="photography", founder_joins=False)
        member = make_user()
        as_user(member)
        assert client.post("/+photography/join").status_code == 401
        assert not is_member(guild.id, member.id)

    # -- the guild's moderator team ---------------------------------------

    def test_a_guild_moderator_can_add_a_moderator(
        self, client, as_user, make_guild, make_user
    ):
        creator = make_user()
        guild = make_guild(board_name="photography", creator=creator)
        target = make_user()
        join(guild.id, target.id)

        as_user(creator)
        response = client.post(
            "/+photography/add_mod",
            data={"username": target.username, "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 302
        assert is_moderator(guild.id, target.id)

    def test_an_ordinary_member_cannot_add_a_moderator(
        self, client, as_user, make_guild, make_user
    ):
        guild = make_guild(board_name="photography", founder_joins=False)
        member = make_user()
        join(guild.id, member.id)
        target = make_user()
        join(guild.id, target.id)

        as_user(member)
        response = client.post(
            "/+photography/add_mod",
            data={"username": target.username, "formkey": formkey(client, member.id)},
        )
        assert response.status_code == 403
        assert not is_moderator(guild.id, target.id)

    def test_an_outsider_cannot_add_a_moderator(
        self, client, as_user, make_guild, make_user
    ):
        guild = make_guild(board_name="photography", founder_joins=False)
        outsider = make_user()
        target = make_user()
        join(guild.id, target.id)

        as_user(outsider)
        response = client.post(
            "/+photography/add_mod",
            data={"username": target.username, "formkey": formkey(client, outsider.id)},
        )
        assert response.status_code == 403
        assert not is_moderator(guild.id, target.id)

    def test_a_moderator_cannot_be_added_from_another_guild(
        self, client, as_user, make_guild, make_user
    ):
        """
        The appointment is scoped to the guild.  A moderator of /+photography
        cannot reach into /+cooking and promote someone there.
        """
        user = make_user()
        first = make_guild(board_name="photography", creator=user)
        second = make_guild(board_name="cooking", founder_joins=False)
        target = make_user()
        join(second.id, target.id)

        as_user(user)
        response = client.post(
            "/+cooking/add_mod",
            data={"username": target.username, "formkey": formkey(client, user.id)},
        )
        assert response.status_code == 403
        assert not is_moderator(second.id, target.id)
        assert is_moderator(first.id, user.id)

    def test_a_non_member_cannot_be_made_a_moderator(
        self, client, as_user, make_guild, make_user
    ):
        creator = make_user()
        guild = make_guild(board_name="photography", creator=creator)
        outsider = make_user()  # never joins

        as_user(creator)
        response = client.post(
            "/+photography/add_mod",
            data={"username": outsider.username, "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 422
        assert not is_moderator(guild.id, outsider.id)

    def test_adding_an_unknown_user_404s(
        self, client, as_user, make_guild, make_user
    ):
        creator = make_user()
        make_guild(board_name="photography", creator=creator)

        as_user(creator)
        response = client.post(
            "/+photography/add_mod",
            data={"username": "nobody-here", "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 404

    def test_a_moderator_can_be_removed(
        self, client, as_user, make_guild, make_user
    ):
        creator = make_user()
        guild = make_guild(board_name="photography", creator=creator)
        target = make_user()
        join(guild.id, target.id)
        promote(guild.id, target.id)

        as_user(creator)
        response = client.post(
            "/+photography/remove_mod",
            data={"username": target.username, "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 302
        assert not is_moderator(guild.id, target.id)
        # Stripping the badge does not kick them out of the guild.
        assert is_member(guild.id, target.id)

    def test_the_founder_cannot_be_removed_as_moderator(
        self, client, as_user, make_guild, make_user
    ):
        """
        The founder moderates via ``created_by``, so "removing" them would be a
        silent no-op.  The route refuses it rather than pretending it worked.
        """
        creator = make_user()
        guild = make_guild(board_name="photography", creator=creator)
        target = make_user()
        join(guild.id, target.id)
        promote(guild.id, target.id)

        # Even a fellow moderator cannot demote the founder.
        as_user(target)
        response = client.post(
            "/+photography/remove_mod",
            data={"username": creator.username, "formkey": formkey(client, target.id)},
        )
        assert response.status_code == 403
        assert is_moderator(guild.id, creator.id)

    def test_a_site_admin_outranks_guild_moderators(
        self, client, as_user, make_guild, make_user
    ):
        guild = make_guild(board_name="photography", founder_joins=False)
        target = make_user()
        join(guild.id, target.id)

        admin = make_user(admin_level=3)
        as_user(admin)
        response = client.post(
            "/+photography/add_mod",
            data={"username": target.username, "formkey": formkey(client, admin.id)},
        )
        assert response.status_code == 302
        assert is_moderator(guild.id, target.id)

    def test_a_guild_moderator_can_edit_the_description(
        self, client, as_user, make_guild, make_user
    ):
        creator = make_user()
        guild = make_guild(board_name="photography", creator=creator)

        as_user(creator)
        response = client.post(
            "/+photography/edit",
            data={"description": "New description",
                  "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 302

        row = db.query(Guild).filter_by(id=guild.id).first()
        assert row.description == "New description"
        assert "New description" in row.description_html

    def test_an_ordinary_member_cannot_edit_the_description(
        self, client, as_user, make_guild, make_user
    ):
        guild = make_guild(board_name="photography", founder_joins=False)
        member = make_user()
        join(guild.id, member.id)

        as_user(member)
        response = client.post(
            "/+photography/edit",
            data={"description": "Hijacked",
                  "formkey": formkey(client, member.id)},
        )
        assert response.status_code == 403
        row = db.query(Guild).filter_by(id=guild.id).first()
        assert row.description != "Hijacked"

    # -- filing a post under a guild --------------------------------------

    def test_submitting_files_the_post_under_the_guild(
        self, client, as_user, make_guild, make_user, make_post
    ):
        creator = make_user()
        guild = make_guild(board_name="photography", creator=creator)
        as_user(creator)

        response = client.post(
            "/submit",
            data={"title": "A post filed under a guild",
                  "body": "Body text.",
                  "guild": "photography",
                  "formkey": formkey(client, creator.id)},
        )
        assert response.status_code == 302

        post = db.query(Submission).filter_by(title="A post filed under a guild").first()
        assert post is not None
        assert post.board_id == guild.id

    def test_submitting_without_a_guild_still_works(
        self, client, as_user, make_user
    ):
        author = make_user()
        as_user(author)

        response = client.post(
            "/submit",
            data={"title": "A post filed nowhere at all",
                  "body": "Body text.",
                  "formkey": formkey(client, author.id)},
        )
        assert response.status_code == 302

        post = db.query(Submission).filter_by(title="A post filed nowhere at all").first()
        assert post is not None
        assert post.board_id is None

    def test_submitting_to_an_unknown_guild_is_an_error(
        self, client, as_user, make_user
    ):
        author = make_user()
        as_user(author)

        response = client.post(
            "/submit",
            data={"title": "A post aimed at nowhere",
                  "body": "Body text.",
                  "guild": "doesnotexist",
                  "formkey": formkey(client, author.id)},
        )
        # /submit reports validation problems by re-rendering the form with an
        # inline message, same as it does for a short title -- so 200 here,
        # not 422.  What matters is that nothing was filed.
        assert response.status_code == 200
        assert b"That guild does not exist." in response.data
        assert not db.query(Submission).filter_by(title="A post aimed at nowhere").first()

    def test_the_submit_form_offers_the_guilds(
        self, client, as_user, make_guild, make_user
    ):
        author = make_user()
        as_user(author)
        make_guild(board_name="photography", creator=author)

        response = client.get("/submit")
        assert response.status_code == 200
        assert b"photography" in response.data

    def test_a_post_page_shows_its_guild(
        self, client, as_user, make_guild, make_post, make_user
    ):
        creator = make_user()
        guild = make_guild(board_name="photography", creator=creator)
        post = make_post(guild=guild, title="A post filed under a guild")

        as_user(creator)
        response = client.get(post.permalink)
        assert response.status_code == 200
        assert b"+photography" in response.data

    def test_a_post_page_without_a_guild_still_renders(
        self, client, as_user, make_post
    ):
        post = make_post(title="A post filed nowhere at all")
        as_user()
        response = client.get(post.permalink)
        assert response.status_code == 200
        assert b"A post filed nowhere at all" in response.data


# --------------------------------------------------------------------------
# Small helpers that go through the ORM, mirroring what the routes will do.
# --------------------------------------------------------------------------
def guild_row(guild_id: int) -> Guild:
    row = db.query(Guild).filter_by(id=guild_id).first()
    assert row is not None, f"no guild with id {guild_id}"
    return row


def guild_member_count(guild_id: int) -> int:
    return guild_row(guild_id).member_count


def guild_post_count(guild_id: int) -> int:
    return guild_row(guild_id).post_count


def is_member(guild_id: int, user_id: int) -> bool:
    return guild_row(guild_id).has_member(db_user(user_id))


def is_moderator(guild_id: int, user_id: int) -> bool:
    return guild_row(guild_id).is_moderator(db_user(user_id))


def moderator_names(guild_id: int) -> list:
    return [u.username for u in guild_row(guild_id).moderators]


def join(guild_id: int, user_id: int) -> None:
    db.add(GuildMember(board_id=guild_id, user_id=user_id, is_mod=False))
    db.commit()


def leave(guild_id: int, user_id: int) -> None:
    db.query(GuildMember).filter_by(board_id=guild_id, user_id=user_id).delete()
    db.commit()


def promote(guild_id: int, user_id: int) -> None:
    row = db.query(GuildMember).filter_by(board_id=guild_id, user_id=user_id).first()
    assert row is not None, "cannot promote someone who is not a member"
    row.is_mod = True
    db.commit()


def demote(guild_id: int, user_id: int) -> None:
    row = db.query(GuildMember).filter_by(board_id=guild_id, user_id=user_id).first()
    assert row is not None, "cannot demote someone who is not a member"
    row.is_mod = False
    db.commit()


def db_user(user_id: int):
    user = db.query(User).filter_by(id=user_id).first()
    assert user is not None, f"no user with id {user_id}"
    return user