"""
Alembic environment for Ruqqus.

The connection string comes from ``DATABASE_URL`` via ``ruqqus.config``, so
``alembic.ini`` never has to carry credentials.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the project root importable when alembic is invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ruqqus import config  # noqa: E402
from ruqqus.__main__ import Base  # noqa: E402

config_ = context.config

if config_.config_file_name is not None:
    fileConfig(config_.config_file_name)

# Always use the configured DATABASE_URL.
config_.set_main_option("sqlalchemy.url", config.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database connection."""
    url = config_.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    # Look up the section set_main_option() above wrote to.  Passing
    # ``config_file_name`` here (the Alembic template's spelling) asks for a
    # *section* named "alembic.ini", which does not exist, so get_section()
    # returns {} and engine_from_config() raises KeyError: 'url'.
    connectable = engine_from_config(
        dict(config_.get_section(config_.config_ini_section, {}) or {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
