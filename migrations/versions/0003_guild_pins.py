"""Per-guild pins.

Adds ``submissions.guild_pinned``, the pin a guild moderator sets on a post in
their own guild.  It is a separate column from ``submissions.stickied`` on
purpose: ``stickied`` is a single site-wide slot (the front-page announcement,
site-admin only) and sharing it would let a guild moderator knock that
announcement off the front page.  See Submission.can_guild_pin.

Existing rows are left as they are -- a post already pinning the front page is
not a guild pin, and every existing ``stickied`` row stays untouched.

Revision ID: 0003_guild_pins
Revises: 0002_guilds
Create Date: 2026-11-03

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_guild_pins"
down_revision = "0002_guilds"
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.add_column(
        "submissions",
        sa.Column("guild_pinned", sa.Boolean(), nullable=True),
    )
    # The column name is the index name's whole reason to exist: the guild
    # listing filters on it, and one pin per guild is the only query it runs.
    op.create_index(
        "ix_submissions_guild_pinned",
        "submissions",
        ["board_id", "guild_pinned"],
    )


def downgrade() -> None:

    op.drop_index("ix_submissions_guild_pinned", table_name="submissions")
    op.drop_column("submissions", "guild_pinned")
