"""Initial schema for Ruqqus.

Creates every table declared in ``ruqqus/classes/`` and installs the
row-wise PostgreSQL functions from ``ruqqus/helpers/db_prep.py``.

Reconciliation notes (see AUDIT.md section 5):

* ``ruqqus/helpers/db_prep.py`` is authoritative over the historical
  ``schema.txt`` dump.  The dump predates the models: it has ``users.ban_state``
  where the code uses ``users.is_banned`` + ``users.ban_reason``, and it has
  ``submissions.board_id`` / ``submissions.over_18`` which no code reads.
  Those orphaned columns and the orphaned ``boards``, ``dms``, ``ips`` and
  ``userflags`` tables are intentionally NOT created -- see MIGRATION_NOTES.md.
* ``comments.parent_fullname`` is ``varchar(255)`` holding values such as
  ``t2_a1b``.  The ORM used to declare it ``BigInteger``, which would have
  rejected every insert; the model now matches this migration.
* ``ups``/``downs``/``age``/``score``/``rank_hot``/``rank_fiery``/
  ``comment_count``/``flag_count``/``rank_activity``/``energy``/
  ``referral_count`` and the notification ``created_utc``/``is_banned``/
  ``is_deleted`` are *not* columns.  They are row-wise functions (``t.ups``
  resolves to ``ups(t)``), which is why the models declare them with
  ``server_default=FetchedValue()``.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-30

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from ruqqus.helpers.db_prep import SQL_FUNCTIONS

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ------------------------------------------------------------------
    # Tables with no outgoing foreign keys
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("passhash", sa.String(), nullable=True),
        sa.Column("created_utc", sa.BigInteger(), nullable=True),
        sa.Column("admin_level", sa.Integer(), nullable=True),
        sa.Column("is_activated", sa.Boolean(), nullable=True),
        sa.Column("reddit_username", sa.String(), nullable=True),
        sa.Column("over_18", sa.Boolean(), nullable=True),
        sa.Column("creation_ip", sa.String(), nullable=True),
        sa.Column("most_recent_ip", sa.String(), nullable=True),
        sa.Column("bio", sa.String(), nullable=True),
        sa.Column("bio_html", sa.String(), nullable=True),
        sa.Column("real_id", sa.String(), nullable=True),
        sa.Column("referred_by", sa.Integer(), nullable=True),
        sa.Column("is_banned", sa.Integer(), nullable=True),
        sa.Column("ban_reason", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint("users_username_key", "users", ["username"])
    op.create_unique_constraint("users_email_key", "users", ["email"])
    op.create_unique_constraint(
        "users_reddit_username_key", "users", ["reddit_username"]
    )

    op.create_table(
        "domains",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("can_submit", sa.Boolean(), nullable=True),
        sa.Column("can_comment", sa.Boolean(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("show_thumbnail", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint("domains_domain_key", "domains", ["domain"])

    op.create_table(
        "badge_defs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=64), nullable=True),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint("badge_list_icon_key", "badge_defs", ["icon"])

    op.create_table(
        "images",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("state", sa.String(length=8), nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("text", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # Second level
    # ------------------------------------------------------------------
    op.create_table(
        "submissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("edited_utc", sa.BigInteger(), nullable=True),
        sa.Column("created_utc", sa.BigInteger(), nullable=True),
        sa.Column("is_banned", sa.Boolean(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("distinguish_level", sa.Integer(), nullable=True),
        sa.Column("created_str", sa.String(length=255), nullable=True),
        sa.Column("stickied", sa.Boolean(), nullable=True),
        sa.Column("body", sa.String(length=2000), nullable=True),
        sa.Column("body_html", sa.String(length=2200), nullable=True),
        sa.Column("embed_url", sa.String(length=256), nullable=True),
        sa.Column("domain_ref", sa.Integer(), nullable=True),
        sa.Column("is_approved", sa.Integer(), nullable=True),
        sa.Column("approved_utc", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["domain_ref"], ["domains.id"]),
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("body", sa.String(length=2000), nullable=True),
        sa.Column("parent_submission", sa.BigInteger(), nullable=True),
        # Holds a fullname string such as "t2_a1b" / "t3_c4d".
        sa.Column("parent_fullname", sa.String(length=255), nullable=True),
        sa.Column("created_utc", sa.BigInteger(), nullable=True),
        sa.Column("edited_timestamp", sa.BigInteger(), nullable=True),
        sa.Column("is_banned", sa.Boolean(), nullable=True),
        sa.Column("body_html", sa.String(), nullable=True),
        sa.Column("distinguish_level", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("is_approved", sa.Integer(), nullable=True),
        sa.Column("approved_utc", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_submission"], ["submissions.id"]),
    )

    # ------------------------------------------------------------------
    # Third level
    # ------------------------------------------------------------------
    op.create_table(
        "votes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("vote_type", sa.Integer(), nullable=True),
        sa.Column("submission_id", sa.Integer(), nullable=True),
        sa.Column("created_utc", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
    )

    op.create_table(
        "commentvotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("vote_type", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("created_utc", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"]),
    )

    op.create_table(
        "flags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_utc", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["post_id"], ["submissions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    op.create_table(
        "commentflags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("created_utc", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"]),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"]),
    )

    op.create_table(
        "badges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("badge_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=64), nullable=True),
        sa.Column("url", sa.String(length=256), nullable=True),
        sa.Column("created_utc", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["badge_id"], ["badge_defs.id"]),
    )

    op.create_table(
        "alts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user1", sa.Integer(), nullable=True),
        sa.Column("user2", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user1"], ["users.id"]),
        sa.ForeignKeyConstraint(["user2"], ["users.id"]),
    )

    # ------------------------------------------------------------------
    # Indexes for the hot lookups.  The historical dump had none (only primary
    # keys and unique constraints); these are a deliberate improvement and
    # change no query results.
    # ------------------------------------------------------------------
    op.create_index("ix_submissions_author_id", "submissions", ["author_id"])
    op.create_index("ix_submissions_created_utc", "submissions", ["created_utc"])
    op.create_index("ix_submissions_stickied", "submissions", ["stickied"])
    op.create_index("ix_comments_parent_submission", "comments", ["parent_submission"])
    op.create_index("ix_comments_author_id", "comments", ["author_id"])
    op.create_index("ix_comments_parent_fullname", "comments", ["parent_fullname"])
    op.create_index("ix_votes_submission_id", "votes", ["submission_id"])
    op.create_index("ix_votes_user_id", "votes", ["user_id"])
    op.create_index("ix_commentvotes_comment_id", "commentvotes", ["comment_id"])
    op.create_index("ix_commentvotes_user_id", "commentvotes", ["user_id"])
    op.create_index("ix_flags_post_id", "flags", ["post_id"])
    op.create_index("ix_commentflags_comment_id", "commentflags", ["comment_id"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_badges_user_id", "badges", ["user_id"])
    op.create_index("ix_alts_user1", "alts", ["user1"])
    op.create_index("ix_alts_user2", "alts", ["user2"])

    # ------------------------------------------------------------------
    # Row-wise PostgreSQL functions (ranking, counts, karma)
    # ------------------------------------------------------------------
    connection = op.get_bind()
    for statement in SQL_FUNCTIONS:
        connection.execute(sa.text(statement))


def downgrade() -> None:
    connection = op.get_bind()

    # Drop functions first; some are typed on table row types.
    for table in (
        "notifications", "users", "comments", "submissions",
    ):
        for name in (
            "ups", "downs", "age", "score", "rank_hot", "rank_fiery",
            "comment_count", "rank_activity", "flag_count", "energy",
            "referral_count", "created_utc", "is_banned", "is_deleted",
        ):
            connection.execute(sa.text(f"DROP FUNCTION IF EXISTS {name}({table})"))

    connection.execute(sa.text("DROP FUNCTION IF EXISTS splash(text)"))

    for table in (
        "alts", "badges", "notifications", "commentflags", "flags",
        "commentvotes", "votes", "comments", "submissions", "images",
        "badge_defs", "domains", "users",
    ):
        op.drop_table(table)
