# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Multi-stage build for Ruqqus.
#
#   Stage 1 (builder)  - install Python dependencies into a virtualenv
#   Stage 2 (runtime)  - copy the virtualenv + application code, run as non-root
#
# Build:  docker build -t ruqqus .
# Run:    docker compose up        (preferred - see docker-compose.yml)
#
# Everything in requirements.txt ships a manylinux wheel (psycopg[binary],
# mistletoe, bleach, ...), so no C compiler is needed and the build stays fast.
# ---------------------------------------------------------------------------


# ===========================================================================
# Stage 1 - dependencies
# ===========================================================================
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Build into a virtualenv so stage 2 is a clean copy, not a site-packages sync.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

COPY requirements.txt .
RUN pip install -r requirements.txt


# ===========================================================================
# Stage 2 - runtime
# ===========================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    WEB_CONCURRENCY=2

# Run as a dedicated non-root user.  Fixed UID/GID so bind mounts and the
# `uploads` volume have predictable ownership on the host.
RUN groupadd --gid 1000 ruqqus \
    && useradd --uid 1000 --gid ruqqus --create-home --shell /usr/sbin/nologin ruqqus

WORKDIR /app

# --- runtime dependencies -------------------------------------------------
COPY --from=builder /opt/venv /opt/venv

# --- application code -----------------------------------------------------
COPY --chown=ruqqus:ruqqus alembic.ini requirements.txt ./
COPY --chown=ruqqus:ruqqus migrations   ./migrations
COPY --chown=ruqqus:ruqqus ruqqus       ./ruqqus
COPY --chown=ruqqus:ruqqus scripts      ./scripts

# --- writable directories -------------------------------------------------
# uploads/ is reserved for user uploads (see MIGRATION_NOTES.md); it is created
# now so the volume mount has the right owner even before anything writes to it.
RUN mkdir -p /app/uploads \
    && chown -R ruqqus:ruqqus /app/uploads

USER ruqqus

EXPOSE 8000

# Probes GET /health (see ruqqus/routes/health.py).  Uses a tiny stdlib script
# because python:slim ships neither curl nor wget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "scripts/healthcheck.py"]

# scripts/startup.sh runs `alembic upgrade head` (idempotent) then execs
# gunicorn.  It is the same entrypoint the Procfile uses, so there is one boot
# path to keep correct.
CMD ["sh", "scripts/startup.sh"]
