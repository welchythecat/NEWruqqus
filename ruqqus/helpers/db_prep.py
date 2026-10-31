"""
PostgreSQL server-side functions that power Ruqqus ranking and counts.

These are *row-wise* functions: each takes a whole table row as its single
argument (``ups(submissions)``, ``energy(users)``, ...).  PostgreSQL lets a
column-like expression ``t.ups`` resolve to ``ups(t)``, which is why the ORM
models declare ``ups = Column(Integer, server_default=FetchedValue())`` even
though no such column exists.

This module is the single source of truth for these functions.  Both
``migrations/versions/0001_initial_schema.py`` and ``scripts/migrate_old_db.py``
import :data:`SQL_FUNCTIONS` from here.

Run standalone against a live database with:

    python -m ruqqus.helpers.db_prep

NOTE: the historical ``schema.txt`` dump declares these functions with
``users.ban_state > -1`` and ``STRICT``; this module uses ``users.is_banned=0``
and ``RETURNS NULL ON NULL INPUT``, matching the ORM models.  This module is
authoritative -- see AUDIT.md section 5.
"""

from __future__ import annotations

# Each entry is a complete, idempotent SQL statement.
SQL_FUNCTIONS: tuple[str, ...] = (
    # ===================== SUBMISSIONS =====================
    """
    CREATE OR REPLACE FUNCTION ups(submissions)
    RETURNS bigint AS '
      SELECT COUNT(*)
      FROM votes
      LEFT JOIN users
      ON votes.user_id = users.id
      WHERE users.is_banned=0
        AND votes.vote_type=1
        AND votes.submission_id=$1.id
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION downs(submissions)
    RETURNS bigint AS '
      SELECT COUNT(*)
      FROM votes
      LEFT JOIN users
      ON votes.user_id = users.id
      WHERE users.is_banned=0
        AND votes.vote_type=-1
        AND votes.submission_id=$1.id
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION age(submissions)
    RETURNS int AS '
      SELECT CAST( EXTRACT( EPOCH FROM CURRENT_TIMESTAMP) AS int) - $1.created_utc
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION score(submissions)
    RETURNS bigint AS '
      SELECT ($1.ups - $1.downs)
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION rank_hot(submissions)
    RETURNS float AS '
      SELECT CAST(($1.ups - $1.downs) AS float)/((CAST(($1.age+5000) AS FLOAT)/100.0)^(0.7))
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION rank_fiery(submissions)
    RETURNS float AS '
      SELECT SQRT(CAST(($1.ups * $1.downs) AS float))/((CAST(($1.age+5000) AS FLOAT)/100.0)^(0.7))
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION comment_count(submissions)
    RETURNS bigint AS '
      SELECT COUNT(*)
      FROM comments
      WHERE is_banned=false
        AND is_deleted=false
        AND parent_submission = $1.id
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION rank_activity(submissions)
    RETURNS float AS '
      SELECT CAST($1.comment_count AS float)/((CAST(($1.age+5000) AS FLOAT)/100.0)^(0.7))
    '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION flag_count(submissions)
    RETURNS bigint AS '
      SELECT COUNT(*)
      FROM flags
      JOIN users ON flags.user_id=users.id
      WHERE post_id=$1.id
      AND users.is_banned=0
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    # ===================== COMMENTS =====================
    """
    CREATE OR REPLACE FUNCTION ups(comments)
    RETURNS bigint AS '
      SELECT COUNT(*)
      FROM commentvotes
      LEFT JOIN users
      ON commentvotes.user_id = users.id
      WHERE users.is_banned=0
        AND commentvotes.vote_type=1
        AND commentvotes.comment_id=$1.id
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION downs(comments)
    RETURNS bigint AS '
      SELECT COUNT(*)
      FROM commentvotes
      LEFT JOIN users
      ON commentvotes.user_id = users.id
      WHERE users.is_banned=0
        AND commentvotes.vote_type=-1
        AND commentvotes.comment_id=$1.id
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION age(comments)
    RETURNS int AS '
      SELECT CAST( EXTRACT( EPOCH FROM CURRENT_TIMESTAMP) AS int) - $1.created_utc
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION flag_count(comments)
    RETURNS bigint AS '
      SELECT COUNT(*)
      FROM commentflags
      JOIN users ON commentflags.user_id=users.id
      WHERE comment_id=$1.id
      AND users.is_banned=0
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    # Comment ranking uses a different decay curve from submissions
    # ((age+100000)/6)^(1/3) rather than ((age+5000)/100)^0.7).  This matches
    # the historical schema dump and the Python Comment.rank_hot property.
    """
    CREATE OR REPLACE FUNCTION rank_hot(comments)
    RETURNS double precision AS '
      SELECT CAST(($1.ups - $1.downs) AS float)
             / ((CAST(($1.age+100000) AS FLOAT)/6.0)^(1.0/3.0))
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION rank_fiery(comments)
    RETURNS double precision AS '
      SELECT SQRT(CAST(($1.ups * $1.downs) AS float))
             / ((CAST(($1.age+100000) AS FLOAT)/6.0)^(1.0/3.0))
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION score(comments)
    RETURNS bigint AS '
      SELECT ($1.ups - $1.downs)
      '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    # ===================== USERS =====================
    """
    CREATE OR REPLACE FUNCTION energy(users)
    RETURNS numeric AS '
     SELECT COALESCE(
     (
      SELECT SUM(submissions.score)
      FROM submissions
      WHERE submissions.author_id=$1.id
        AND submissions.is_banned=false
        AND submissions.is_deleted=false
      ),
      0
      )
    '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION referral_count(users)
    RETURNS bigint AS'
        SELECT COUNT(*)
        FROM USERS
        WHERE users.is_banned=0
        AND users.referred_by=$1.id
    '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    # ===================== NOTIFICATIONS =====================
    # Notifications have no real created_utc/is_banned/is_deleted columns;
    # these row-wise functions copy them from the parent comment.
    """
    CREATE OR REPLACE FUNCTION created_utc(notifications)
    RETURNS integer AS '
      select created_utc from comments
      where comments.id=$1.comment_id
    '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION is_banned(notifications)
    RETURNS boolean AS '
      select is_banned from comments
      where comments.id=$1.comment_id
    '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    """
    CREATE OR REPLACE FUNCTION is_deleted(notifications)
    RETURNS boolean AS '
      select is_deleted from comments
      where comments.id=$1.comment_id
    '
    LANGUAGE SQL
    IMMUTABLE
    RETURNS NULL ON NULL INPUT
    """,
    # ===================== SPLASH IMAGES =====================
    """
    CREATE OR REPLACE FUNCTION splash(text)
    RETURNS setof images AS '
      SELECT *
      FROM images
      WHERE state=$1
      ORDER BY random()
      LIMIT 1
    '
    LANGUAGE SQL
    VOLATILE
    RETURNS NULL ON NULL INPUT
    """,
)


def apply_functions(connection) -> int:
    """Execute every statement on a DB-API connection.  Returns the count."""
    for statement in SQL_FUNCTIONS:
        connection.execute(statement)
    return len(SQL_FUNCTIONS)


def main() -> int:
    import os

    try:
        import psycopg
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "psycopg (v3) is required to run db_prep standalone: "
            "pip install 'psycopg[binary]'"
        )

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")

    with psycopg.connect(dsn, autocommit=True) as conn:
        count = apply_functions(conn)
    print(f"Installed {count} PostgreSQL functions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
