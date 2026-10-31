#!/usr/bin/env python3
"""Bring a database restored from an old Ruqqus pg_dump up to the current schema.

The original site's database differs from the ORM models in several places (see
AUDIT.md section 5 and migrations/versions/0001_initial_schema.py).  This
script takes a database that was restored from a pre-shutdown dump -- the shape
documented in ``schema.txt`` -- and makes it usable by the current code.

It is deliberately **additive**:

* columns the models need but the dump lacks are added;
* columns the models declare wider than the dump are widened;
* ``users.ban_state`` is translated into ``users.is_banned`` + ``ban_reason``;
* the row-wise SQL functions are replaced with the current definitions from
  ``ruqqus/helpers/db_prep.py`` (the dump's versions reference ``ban_state`` and
  would break);
* the indexes from the initial migration are created;
* the database is stamped as being at revision ``0001_initial``.

Nothing is dropped by default -- old columns and the orphaned ``boards``,
``dms``, ``ips`` and ``userflags`` tables are left in place so no data is lost.
Pass ``--drop-orphans`` to remove them once you are happy with the migration.

Usage
-----
    # Migrate the database named by DATABASE_URL (or .env):
    python scripts/migrate_old_db.py

    # See every statement without changing anything:
    python scripts/migrate_old_db.py --dry-run

    # Migrate somewhere else:
    python scripts/migrate_old_db.py --dsn postgresql://user:pass@host/olddb

The script is idempotent: running it twice is safe and changes nothing the
second time.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the project root importable.  We deliberately add the *project root*,
# never this script's own directory, so a stray file in scripts/ cannot shadow
# a standard-library module.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402

from ruqqus.config import DATABASE_URL, normalise_database_url  # noqa: E402
from ruqqus.helpers.db_prep import SQL_FUNCTIONS  # noqa: E402

#: Alembic revision this script leaves the database at.
TARGET_REVISION = "0001_initial"

#: Tables the models define.  Anything else in a restored dump is orphaned.
KNOWN_TABLES = frozenset(
    {
        "users", "submissions", "comments", "votes", "commentvotes",
        "flags", "commentflags", "notifications", "badge_defs", "badges",
        "alts", "domains", "images",
    }
)

#: Columns in a restored dump that no code reads any more.
ORPHAN_COLUMNS = {
    "users": ["ban_state"],
    "submissions": ["board_id", "over_18"],
    "votes": ["target_fullname"],
    "domains": ["anon_free_embed"],
}

#: Tables in a restored dump that no code reads any more.
ORPHAN_TABLES = ["boards", "dms", "ips", "userflags"]


# ---------------------------------------------------------------------------
# Planned DDL
# ---------------------------------------------------------------------------
# Each entry is (table, description, sql).  Every statement is idempotent so the
# script can be re-run safely.

ADD_COLUMNS: list[tuple[str, str, str]] = [
    (
        "users",
        "add users.is_banned (0 = active, otherwise the banning admin's id)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned integer DEFAULT 0",
    ),
    (
        "users",
        "add users.ban_reason",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason varchar DEFAULT ''",
    ),
    (
        "submissions",
        "add submissions.edited_utc",
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS edited_utc bigint DEFAULT 0",
    ),
    (
        "submissions",
        "add submissions.approved_utc",
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS approved_utc integer DEFAULT 0",
    ),
    (
        "comments",
        "add comments.approved_utc",
        "ALTER TABLE comments ADD COLUMN IF NOT EXISTS approved_utc integer DEFAULT 0",
    ),
    (
        "domains",
        "add domains.show_thumbnail",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS show_thumbnail boolean DEFAULT false",
    ),
]

#: Widening is always safe (PostgreSQL only needs to check, never truncate).
WIDEN_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "widen users.username to varchar", "ALTER TABLE users ALTER COLUMN username TYPE varchar"),
    ("users", "widen users.email to varchar", "ALTER TABLE users ALTER COLUMN email TYPE varchar"),
    ("users", "widen users.passhash to varchar", "ALTER TABLE users ALTER COLUMN passhash TYPE varchar"),
    ("users", "widen users.reddit_username to varchar", "ALTER TABLE users ALTER COLUMN reddit_username TYPE varchar"),
    ("users", "widen users.bio to varchar", "ALTER TABLE users ALTER COLUMN bio TYPE varchar"),
    ("users", "widen users.bio_html to varchar", "ALTER TABLE users ALTER COLUMN bio_html TYPE varchar"),
    ("users", "widen users.real_id to varchar", "ALTER TABLE users ALTER COLUMN real_id TYPE varchar"),
    ("submissions", "widen submissions.title to varchar(500)", "ALTER TABLE submissions ALTER COLUMN title TYPE varchar(500)"),
    ("submissions", "widen submissions.url to varchar(500)", "ALTER TABLE submissions ALTER COLUMN url TYPE varchar(500)"),
    ("comments", "widen comments.body_html to varchar", "ALTER TABLE comments ALTER COLUMN body_html TYPE varchar"),
    ("domains", "widen domains.domain to varchar", "ALTER TABLE domains ALTER COLUMN domain TYPE varchar"),
    (
        "domains",
        "change domains.reason from integer to varchar",
        "ALTER TABLE domains ALTER COLUMN reason TYPE varchar USING reason::text",
    ),
]

#: Primary keys and foreign keys the models declare as BigInteger while the
#: dump used integer.  Widening avoids int32 overflow and matches the models,
#: so a migrated database and one built by `alembic upgrade head` are identical.
#: Skipped with --no-widen-ids.
WIDEN_IDS: list[tuple[str, str, str]] = [
    ("submissions", "widen submissions.id to bigint", "ALTER TABLE submissions ALTER COLUMN id TYPE bigint"),
    ("comments", "widen comments.id to bigint", "ALTER TABLE comments ALTER COLUMN id TYPE bigint"),
    ("badge_defs", "widen badge_defs.id to bigint", "ALTER TABLE badge_defs ALTER COLUMN id TYPE bigint"),
    ("images", "widen images.id to bigint", "ALTER TABLE images ALTER COLUMN id TYPE bigint"),
    ("submissions", "widen submissions.author_id to bigint", "ALTER TABLE submissions ALTER COLUMN author_id TYPE bigint"),
    ("comments", "widen comments.author_id to bigint", "ALTER TABLE comments ALTER COLUMN author_id TYPE bigint"),
    ("comments", "widen comments.parent_submission to bigint", "ALTER TABLE comments ALTER COLUMN parent_submission TYPE bigint"),
]

#: Same set as migrations/versions/0001_initial_schema.py.
CREATE_INDEXES: list[tuple[str, str, str]] = [
    ("submissions", "index submissions.author_id", "CREATE INDEX IF NOT EXISTS ix_submissions_author_id ON submissions (author_id)"),
    ("submissions", "index submissions.created_utc", "CREATE INDEX IF NOT EXISTS ix_submissions_created_utc ON submissions (created_utc)"),
    ("submissions", "index submissions.stickied", "CREATE INDEX IF NOT EXISTS ix_submissions_stickied ON submissions (stickied)"),
    ("comments", "index comments.parent_submission", "CREATE INDEX IF NOT EXISTS ix_comments_parent_submission ON comments (parent_submission)"),
    ("comments", "index comments.author_id", "CREATE INDEX IF NOT EXISTS ix_comments_author_id ON comments (author_id)"),
    ("comments", "index comments.parent_fullname", "CREATE INDEX IF NOT EXISTS ix_comments_parent_fullname ON comments (parent_fullname)"),
    ("votes", "index votes.submission_id", "CREATE INDEX IF NOT EXISTS ix_votes_submission_id ON votes (submission_id)"),
    ("votes", "index votes.user_id", "CREATE INDEX IF NOT EXISTS ix_votes_user_id ON votes (user_id)"),
    ("commentvotes", "index commentvotes.comment_id", "CREATE INDEX IF NOT EXISTS ix_commentvotes_comment_id ON commentvotes (comment_id)"),
    ("commentvotes", "index commentvotes.user_id", "CREATE INDEX IF NOT EXISTS ix_commentvotes_user_id ON commentvotes (user_id)"),
    ("flags", "index flags.post_id", "CREATE INDEX IF NOT EXISTS ix_flags_post_id ON flags (post_id)"),
    ("commentflags", "index commentflags.comment_id", "CREATE INDEX IF NOT EXISTS ix_commentflags_comment_id ON commentflags (comment_id)"),
    ("notifications", "index notifications.user_id", "CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id)"),
    ("badges", "index badges.user_id", "CREATE INDEX IF NOT EXISTS ix_badges_user_id ON badges (user_id)"),
    ("alts", "index alts.user1", "CREATE INDEX IF NOT EXISTS ix_alts_user1 ON alts (user1)"),
    ("alts", "index alts.user2", "CREATE INDEX IF NOT EXISTS ix_alts_user2 ON alts (user2)"),
]


class Plan:
    """Collects statements so --dry-run can show the full run before doing it."""

    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.executed = 0
        self.skipped = 0

    def run(self, connection, description: str, statement: str) -> None:
        print(f"  {description}")
        if self.dry_run:
            print(f"      SQL> {statement}")
            self.skipped += 1
            return
        connection.execute(statement)
        self.executed += 1


def existing_columns(connection, table: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    ).fetchall()
    return {row[0] for row in rows}


def existing_tables(connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
    ).fetchall()
    return {row[0] for row in rows}


def apply_all(connection, plan: Plan, statements: list[tuple[str, str, str]],
              tables: set[str]) -> None:
    for table, description, statement in statements:
        if table not in tables:
            print(f"  (skip) {description} -- table {table!r} is missing")
            plan.skipped += 1
            continue
        plan.run(connection, description, statement)


def pick_banned_by(connection, explicit: int | None) -> int:
    """Return the user id recorded against legacy bans.

    ``users.is_banned`` stores the *banning admin's id* (0 means not banned --
    see routes/admin_api.py).  A legacy dump only records ``ban_state < 0``, so
    we cannot recover which admin applied the ban; we attribute it to an admin
    the operator names, or to the earliest admin account.
    """
    if explicit is not None:
        exists = connection.execute(
            "SELECT 1 FROM users WHERE id = %s", (explicit,)
        ).fetchone()
        if not exists:
            raise SystemExit(f"--banned-by {explicit} does not exist in users.id")
        return explicit

    row = connection.execute(
        "SELECT id FROM users WHERE admin_level >= 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if row:
        print(
            f"  Legacy bans will be attributed to admin user id={row[0]}. "
            "Use --banned-by to override."
        )
        return int(row[0])

    raise SystemExit(
        "Found users with ban_state < 0 but no admin account to attribute the "
        "ban to.  Create an admin, or pass --banned-by <user_id>."
    )


def migrate_bans(connection, plan: Plan, banned_by: int) -> None:
    print("\nTranslating users.ban_state into users.is_banned + users.ban_reason")

    # ban_state >= 0 (or NULL) means the account was in good standing.
    plan.run(
        connection,
        "clear users.is_banned for accounts that were in good standing",
        "UPDATE users SET is_banned = 0 "
        "WHERE ban_state IS NULL OR ban_state >= 0",
    )

    # ban_state < 0 means the account was banned.
    plan.run(
        connection,
        "set users.is_banned for accounts that were banned",
        f"UPDATE users SET is_banned = {banned_by} "
        "WHERE ban_state IS NOT NULL AND ban_state < 0",
    )

    # Keep the original value readable; only fill an empty reason so re-running
    # the script cannot append to itself.
    plan.run(
        connection,
        "record the legacy ban_state in users.ban_reason",
        "UPDATE users SET ban_reason = "
        "  'Migrated from legacy ban_state=' || ban_state "
        "WHERE ban_state IS NOT NULL AND ban_state < 0 "
        "  AND COALESCE(ban_reason, '') = ''",
    )


def install_functions(connection, plan: Plan) -> None:
    print("\nInstalling current row-wise SQL functions")
    if plan.dry_run:
        print(f"      {len(SQL_FUNCTIONS)} CREATE OR REPLACE FUNCTION statements")
        plan.skipped += len(SQL_FUNCTIONS)
        return
    for statement in SQL_FUNCTIONS:
        connection.execute(statement)
        plan.executed += 1


def stamp_alembic(connection, plan: Plan) -> None:
    print("\nStamping the Alembic revision")
    plan.run(
        connection,
        "create alembic_version if missing",
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "  version_num varchar(32) NOT NULL,"
        "  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
        ")",
    )
    if plan.dry_run:
        print(f"      (would ensure alembic_version = {TARGET_REVISION!r})")
        return

    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (%s)",
            (TARGET_REVISION,),
        )
        plan.executed += 1
        print(f"  stamped as {TARGET_REVISION!r}")
    elif row[0] == TARGET_REVISION:
        print(f"  already at {TARGET_REVISION!r}")
    else:
        print(
            f"  WARNING: alembic_version is {row[0]!r}, not {TARGET_REVISION!r}."
            "  Leaving it alone -- run `alembic upgrade head` if you want to"
            "  move forward."
        )


def drop_orphans(connection, plan: Plan, tables: set[str]) -> None:
    print("\nDropping orphaned columns and tables (--drop-orphans)")
    for table, columns in ORPHAN_COLUMNS.items():
        if table not in tables:
            continue
        present = existing_columns(connection, table) if not plan.dry_run else set(columns)
        for column in columns:
            if column not in present:
                continue
            plan.run(
                connection,
                f"drop {table}.{column}",
                f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}",
            )

    for table in ORPHAN_TABLES:
        if table not in tables:
            continue
        plan.run(connection, f"drop table {table}", f"DROP TABLE IF EXISTS {table}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate a restored legacy Ruqqus database to the current schema.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="PostgreSQL connection string (default: DATABASE_URL from the environment/.env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print every statement without executing any of them",
    )
    parser.add_argument(
        "--banned-by",
        type=int,
        default=None,
        metavar="USER_ID",
        help="user id to record as the banning admin for legacy bans "
             "(default: the earliest admin account)",
    )
    parser.add_argument(
        "--drop-orphans",
        action="store_true",
        help="also drop columns and tables the code no longer reads "
             "(destructive; off by default)",
    )
    parser.add_argument(
        "--no-widen-ids",
        action="store_true",
        help="leave primary/foreign key columns as integer instead of widening "
             "them to bigint",
    )
    args = parser.parse_args()

    dsn = normalise_database_url(args.dsn) if args.dsn else DATABASE_URL
    plan = Plan(dry_run=args.dry_run)

    print(f"Connecting to {dsn.split('@')[-1]}")
    if args.dry_run:
        print("DRY RUN -- nothing will be changed.\n")

    with psycopg.connect(dsn, autocommit=False) as connection:
        tables = existing_tables(connection)

        if "users" not in tables:
            raise SystemExit(
                "This database has no `users` table, so there is nothing to "
                "migrate.\n"
                "If you want a fresh install, run:  alembic upgrade head"
            )

        if "submissions" not in tables or "comments" not in tables:
            raise SystemExit(
                "This database is missing core tables (submissions/comments). "
                "It does not look like a Ruqqus dump; refusing to modify it."
            )

        print(f"Found tables: {', '.join(sorted(tables))}")
        legacy_bans = "ban_state" in existing_columns(connection, "users")
        print(
            "Legacy schema detected (users.ban_state)."
            if legacy_bans
            else "Already on the new schema; re-running is a no-op."
        )

        print("\nAdding columns the models require")
        apply_all(connection, plan, ADD_COLUMNS, tables)

        print("\nWidening columns to match the models")
        apply_all(connection, plan, WIDEN_COLUMNS, tables)

        if not args.no_widen_ids:
            print("\nWidening id columns to bigint")
            apply_all(connection, plan, WIDEN_IDS, tables)
        else:
            print("\nSkipping id widening (--no-widen-ids)")

        print("\nCreating indexes")
        apply_all(connection, plan, CREATE_INDEXES, tables)

        if legacy_bans:
            banned_by = pick_banned_by(connection, args.banned_by)
            migrate_bans(connection, plan, banned_by)
        elif args.banned_by is not None:
            print("\n--banned-by ignored: there is no users.ban_state to translate")

        install_functions(connection, plan)
        stamp_alembic(connection, plan)

        if args.drop_orphans:
            drop_orphans(connection, plan, tables)
        else:
            leftover = [
                f"{table}.{column}"
                for table, columns in ORPHAN_COLUMNS.items()
                for column in columns
                if table in tables and column in existing_columns(connection, table)
            ]
            leftover += [t for t in ORPHAN_TABLES if t in tables]
            if leftover:
                print(
                    "\nLeft in place (no code reads them; pass --drop-orphans to "
                    "remove):\n  " + ", ".join(leftover)
                )

        if args.dry_run:
            connection.rollback()
            print(f"\nDry run complete: {plan.skipped} statements not executed.")
        else:
            connection.commit()
            print(f"\nDone: {plan.executed} statements executed.")
            print("Next:  alembic current   # should print " + TARGET_REVISION)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
