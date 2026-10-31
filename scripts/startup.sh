#!/bin/sh
# Boot Ruqqus in production.
#
# Applies any outstanding database migrations, then starts the WSGI server.
# Used by the Procfile; also the documented boot command for a plain VPS or
# systemd service.  `alembic upgrade head` is idempotent, so running it on every
# boot is safe.
#
# Environment:
#   PORT             port to bind          (default 8000)
#   WEB_CONCURRENCY  gunicorn worker count (default 2)
#
# Extra arguments are passed straight through to gunicorn, so
#   scripts/startup.sh --timeout 120
# works as expected.
set -eu

alembic upgrade head

exec gunicorn ruqqus.__main__:app \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --access-logfile - \
    --error-logfile - \
    "$@"
