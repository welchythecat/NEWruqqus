"""Guilds (communities).

Adds the ``boards`` table, the ``board_members`` table, and
``submissions.board_id``.

Reconciliation with the historical ``schema.txt`` dump -- see
MIGRATION_NOTES.md §5:

* The dump had ``boards(id, board_name, is_banned, created_utc)`` and
  ``submissions.board_id`` with a foreign key to ``boards(id)``.  Those are
  restored here under the original table and column names, so a database that
  still carries the old table keeps its guilds.
* The dump had **no** membership or moderator table.  ``board_members`` is an
  addition made for this feature, not a restoration, and it is the only new
  table here.
* ``boards.id`` stays ``Integer`` to match both the dump and
  ``submissions.board_id``, which is what the foreign key compares against.

Revision ID: 0002_guilds
Revises: 0001_initial
Create Date: 2026-10-31

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_guilds"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ------------------------------------------------------------------
    # boards -- the guilds themselves.  Name and core columns are the
    # historical ones; the rest are additions.
    # ------------------------------------------------------------------
    op.create_table(
        "boards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_name", sa.String(length=64), nullable=True),
        sa.Column("is_banned", sa.Boolean(), nullable=True),
        sa.Column("created_utc", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("description_html", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_boards_board_name", "boards", ["board_name"], unique=True)

    # ------------------------------------------------------------------
    # board_members -- membership plus the per-guild moderator flag.
    # ------------------------------------------------------------------
    op.create_table(
        "board_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("is_mod", sa.Boolean(), nullable=True),
        sa.Column("created_utc", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_board_members_board_user",
        "board_members",
        ["board_id", "user_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # submissions.board_id -- nullable, so posts made before guilds existed
    # and posts filed nowhere both stay valid.
    # ------------------------------------------------------------------
    op.add_column("submissions", sa.Column("board_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "submissions_board_id_fkey",
        "submissions",
        "boards",
        ["board_id"],
        ["id"],
    )


def downgrade() -> None:

    op.drop_constraint("submissions_board_id_fkey", "submissions", type_="foreignkey")
    op.drop_column("submissions", "board_id")

    op.drop_index("ix_board_members_board_user", table_name="board_members")
    op.drop_table("board_members")

    op.drop_index("ix_boards_board_name", table_name="boards")
    op.drop_table("boards")