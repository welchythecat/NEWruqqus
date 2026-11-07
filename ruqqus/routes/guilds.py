"""
Guilds -- browse, view, create, join, and moderate the communities that posts
are filed under.

Anyone may create a guild (there is no application or approval step).  A guild
has its own moderators, separate from the site's: a guild moderator can change
that guild's description and appoint or remove other moderators of that guild,
and has no power anywhere else.  Site admins retain power over every guild.

Membership is open -- joining and leaving is a click, with no approval.

URLs are ``/guilds`` for the directory and ``/+<name>`` for a single guild.
See MIGRATION_NOTES.md §5 for what is historical here and what is new.
"""

import re
import time

import mistletoe

from flask import *
from sqlalchemy import *

from ruqqus.classes import *
from ruqqus.helpers.base36 import *
from ruqqus.helpers.markdown import *
from ruqqus.helpers.sanitize import *
from ruqqus.helpers.wrappers import *
from ruqqus.__main__ import app, cache, db, limiter

# Guild names sit directly in the URL, so they are restricted to characters
# that need no escaping and cannot be used to walk the path.  3 characters is
# the floor for readability; 32 keeps the URL short and matches the board_name
# column with room to spare.
GUILD_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def _render_description(body):
    """Markdown in, sanitized HTML out -- the same pipeline posts use."""
    with UserRenderer() as renderer:
        rendered = renderer.render(mistletoe.Document(body or ""))
    return sanitize(rendered, linkgen=True), body or ""


def _guild_or_404(board_name):
    guild = db.query(Guild).filter_by(board_name=board_name).first()
    if not guild:
        abort(404)
    return guild


def _is_site_admin(v):
    """Site admins outrank every guild moderator."""
    return bool(v and v.admin_level >= 3)


def _require_moderator(guild, v):
    """403 unless ``v`` may moderate this particular guild."""
    if not guild.is_moderator(v) and not _is_site_admin(v):
        abort(403)


# --------------------------------------------------------------------------
# The directory
# --------------------------------------------------------------------------
@app.route("/guilds", methods=["GET"])
@auth_desired
def guilds_list(v=None):
    page = max(int(request.args.get("page", 1)), 1)

    # Most-subscribed first.  The count lives in a subquery so the ORDER BY
    # can use it without turning the member_count property into N queries.
    member_counts = (
        db.query(GuildMember.board_id, func.count(GuildMember.id).label("n"))
        .group_by(GuildMember.board_id)
        .subquery()
    )

    rows = (
        db.query(Guild)
        .outerjoin(member_counts, member_counts.c.board_id == Guild.id)
        .filter(Guild.is_banned == False)  # noqa: E712
        .order_by(func.coalesce(member_counts.c.n, 0).desc(), Guild.board_name)
        .offset(25 * (page - 1))
        .limit(26)
        .all()
    )

    next_exists = len(rows) == 26
    guilds = rows[:25]

    return render_template(
        "guilds.html",
        v=v,
        listing=guilds,
        page=page,
        next_exists=next_exists,
    )


# --------------------------------------------------------------------------
# One guild
# --------------------------------------------------------------------------
@app.route("/+<board_name>", methods=["GET"])
@auth_desired
def guild_page(board_name, v=None):
    guild = _guild_or_404(board_name)

    page = max(int(request.args.get("page", 1)), 1)
    sort_method = request.args.get("sort", "hot")

    ids = guild_list(guild.id, sort=sort_method, page=page)

    next_exists = len(ids) == 26
    ids = ids[:25]

    if ids:
        i = 1
        tups = []
        for x in ids:
            tups.append((x, i))
            i += 1
        tups = str(tups).lstrip("[").rstrip("]")

        posts = db.query(Submission).from_statement(
            text(
                f"""
                select submissions.*, submissions.ups, submissions.downs
                from submissions
                join (values {tups}) as x(id, n) on submissions.id=x.id
                order by x.n"""
            )
        ).all()
    else:
        posts = []

    return render_template(
        "guild.html",
        v=v,
        guild=guild,
        listing=posts,
        sort_method=sort_method,
        page=page,
        next_exists=next_exists,
    )


@cache.memoize(timeout=30)
def guild_list(guild_id, sort="hot", page=1):
    """
    Ids of the posts filed under ``guild_id``, newest 26 first.

    ``guild_id`` is a plain argument, so it is part of the memoization key --
    two guilds cannot be handed each other's cached pages.

    The guild's pinned post sorts first.  That is the same treatment the
    site-wide sticky gets on the front page, and for the same reason: a pin
    nobody sees at the top is not a pin.  Sorting it first is also what keeps
    it off the later pages -- it is row 1, so page 2 onward can never reach
    it, and it is not shown twice.
    """
    posts = db.query(Submission).filter(
        Submission.board_id == guild_id,
        Submission.is_banned == False,  # noqa: E712
        Submission.is_deleted == False,  # noqa: E712
    )

    if sort == "hot":
        posts = posts.order_by(
            Submission.guild_pinned.desc(), text("submissions.rank_hot desc")
        )
    elif sort == "new":
        posts = posts.order_by(
            Submission.guild_pinned.desc(), Submission.created_utc.desc()
        )
    elif sort == "disputed":
        posts = posts.order_by(
            Submission.guild_pinned.desc(), text("submissions.rank_fiery desc")
        )
    elif sort == "top":
        posts = posts.order_by(
            Submission.guild_pinned.desc(), text("submissions.score desc")
        )
    elif sort == "activity":
        posts = posts.order_by(
            Submission.guild_pinned.desc(), text("submissions.rank_activity desc")
        )
    else:
        abort(422)

    return [x.id for x in posts.offset(25 * (page - 1)).limit(26).all()]


# --------------------------------------------------------------------------
# Creating
# --------------------------------------------------------------------------
@app.route("/create_guild", methods=["GET"])
@auth_desired
def create_guild_get(v=None):
    return render_template("create_guild.html", v=v, error=None)


@app.route("/create_guild", methods=["POST"])
@limiter.limit("6/minute")
@is_not_banned
@validate_formkey
def create_guild_post(v):
    name = (request.form.get("name") or "").strip()
    description = request.form.get("description", "")

    def failed(error):
        return render_template(
            "create_guild.html",
            v=v,
            error=error,
            name=name,
            description=description,
        ), 422

    # The name goes straight into the URL, so it is validated strictly and the
    # error is shown rather than silently normalized.
    if not GUILD_NAME_RE.match(name):
        return failed(
            "Guild names must be 3-32 characters: letters, numbers and "
            "underscores only."
        )

    if len(description) > 512:
        return failed("That description is too long. 512 characters is the limit.")

    if db.query(Guild).filter_by(board_name=name).first():
        return failed(f"The name {name} is already taken.")

    description_html, description = _render_description(description)

    guild = Guild(
        board_name=name,
        created_by=v.id,
        description=description,
        description_html=description_html,
    )
    db.add(guild)
    db.commit()

    # The founder joins, and moderates.  The membership row is what puts the
    # guild in their list; the founder rule in Guild.is_moderator covers the
    # moderation side either way.
    db.add(GuildMember(board_id=guild.id, user_id=v.id, is_mod=True))
    db.commit()

    return redirect(guild.permalink)


# --------------------------------------------------------------------------
# Joining and leaving
# --------------------------------------------------------------------------
@app.route("/+<board_name>/join", methods=["POST"])
@limiter.limit("20/minute")
@is_not_banned
@validate_formkey
def guild_join(board_name, v):
    guild = _guild_or_404(board_name)

    if guild.is_banned:
        abort(403)

    if not guild.has_member(v):
        db.add(GuildMember(board_id=guild.id, user_id=v.id, is_mod=False))
        db.commit()

    return redirect(guild.permalink)


@app.route("/+<board_name>/leave", methods=["POST"])
@is_not_banned
@validate_formkey
def guild_leave(board_name, v):
    guild = _guild_or_404(board_name)

    db.query(GuildMember).filter_by(board_id=guild.id, user_id=v.id).delete()
    db.commit()

    return redirect(guild.permalink)


# --------------------------------------------------------------------------
# Guild settings, and the guild's own moderator team
# --------------------------------------------------------------------------
@app.route("/+<board_name>/edit", methods=["POST"])
@is_not_banned
@validate_formkey
def guild_edit(board_name, v):
    guild = _guild_or_404(board_name)
    _require_moderator(guild, v)

    description = request.form.get("description", "")
    if len(description) > 512:
        abort(422)

    guild.description_html, guild.description = _render_description(description)
    db.add(guild)
    db.commit()

    return redirect(guild.permalink)


@app.route("/+<board_name>/add_mod", methods=["POST"])
@is_not_banned
@validate_formkey
def guild_add_mod(board_name, v):
    guild = _guild_or_404(board_name)
    _require_moderator(guild, v)

    username = (request.form.get("username") or "").strip()
    user = db.query(User).filter_by(username=username).first()
    if not user:
        abort(404)

    # Anyone a moderator appoints has to be in the guild -- otherwise the
    # roster would list people who cannot see what they moderate.
    if not guild.has_member(user):
        abort(422)

    row = db.query(GuildMember).filter_by(board_id=guild.id, user_id=user.id).first()
    if row:
        row.is_mod = True
    else:
        db.add(GuildMember(board_id=guild.id, user_id=user.id, is_mod=True))
    db.commit()

    return redirect(guild.permalink)


@app.route("/+<board_name>/remove_mod", methods=["POST"])
@is_not_banned
@validate_formkey
def guild_remove_mod(board_name, v):
    guild = _guild_or_404(board_name)
    _require_moderator(guild, v)

    username = (request.form.get("username") or "").strip()
    user = db.query(User).filter_by(username=username).first()
    if not user:
        abort(404)

    # The founder moderates regardless of the membership row, so "removing"
    # them would be a no-op that looks like a mistake.  Refuse it outright.
    if guild.created_by == user.id:
        abort(403)

    row = db.query(GuildMember).filter_by(board_id=guild.id, user_id=user.id).first()
    if row and row.is_mod:
        row.is_mod = False
        db.add(row)
        db.commit()

    return redirect(guild.permalink)