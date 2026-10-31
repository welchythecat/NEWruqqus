# ---------------------------------------------------------------------------
# Ruqqus - common tasks
#
#   make help          list every target
#   make setup         one-time local setup (venv + deps + .env)
#   make up            start everything with Docker Compose
#
# Requires GNU make (pre-installed on Linux/macOS; on Windows use WSL2 or
# Git Bash -- see INSTALL.md).
# ---------------------------------------------------------------------------

SHELL := /bin/sh
.DEFAULT_GOAL := help

PYTHON  ?= python3
VENV    ?= .venv
BIN     := $(VENV)/bin
PIP     := $(BIN)/pip
PY      := $(BIN)/python
COMPOSE ?= docker compose

# Fail early with a readable message if the venv is missing.
define need-venv
	@test -x $(PY) || { \
	  echo "No virtualenv at $(VENV). Run 'make setup' first."; exit 1; }
endef

.PHONY: help setup install install-dev migrate migrate-check run dev test lint \
        format create-admin up down build logs ps backup restore clean

help: ## Show this help
	@echo "Ruqqus - available targets:"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------
setup: ## One-time setup: create .venv, install deps, create .env
	@test -x $(PY) || $(PYTHON) -m venv $(VENV)
	$(MAKE) install
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  echo "Created .env from .env.example -- edit it now:"; \
	  echo "  1. set SECRET_KEY   (python3 -c \"import secrets; print(secrets.token_hex(32))\")"; \
	  echo "  2. set DATABASE_URL to your PostgreSQL server"; \
	fi
	@echo "Setup complete. Next: make migrate && make dev"

install: ## Install runtime dependencies
	@$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev: ## Install runtime + test/lint dependencies
	@$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
migrate: ## Apply all database migrations
	$(need-venv)
	$(BIN)/alembic upgrade head

migrate-check: ## Show the current migration revision
	$(need-venv)
	$(BIN)/alembic current

migrate-down: ## Roll back the most recent migration
	$(need-venv)
	$(BIN)/alembic downgrade -1

# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------
run: ## Run the production server locally (gunicorn)
	$(need-venv)
	sh scripts/startup.sh

dev: ## Run the development server with auto-reload
	$(need-venv)
	$(PY) run_dev.py --debug

create-admin: ## Create or promote an administrator account
	$(need-venv)
	$(PY) scripts/create_admin.py

# --------------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------------
test: ## Run the test suite
	$(need-venv)
	$(PY) -m pytest -q

lint: ## Lint with ruff (no changes made)
	$(need-venv)
	$(BIN)/ruff check .

format: ## Auto-format with ruff
	$(need-venv)
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------
build: ## Build the application image
	$(COMPOSE) build

up: ## Start app + PostgreSQL + Redis in the background
	$(COMPOSE) up -d --build

down: ## Stop and remove the containers (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow the application log
	$(COMPOSE) logs -f app

ps: ## Show container status
	$(COMPOSE) ps

# --------------------------------------------------------------------------
# Backup / restore
# --------------------------------------------------------------------------
BACKUP_DIR ?= backups
BACKUP_FILE ?= $(BACKUP_DIR)/ruqqus-$$(date +%Y%m%d-%H%M%S).sql.gz

backup: ## Dump the PostgreSQL database to backups/
	@mkdir -p $(BACKUP_DIR)
	$(COMPOSE) exec -T db sh -c 'pg_dump -U $${POSTGRES_USER:-ruqqus} $${POSTGRES_DB:-ruqqus}' | gzip > $(BACKUP_FILE)
	@echo "Wrote $(BACKUP_FILE)"

restore: ## Restore from a dump: make restore FILE=backups/xxx.sql.gz
	@test -n "$(FILE)" || { echo "usage: make restore FILE=backups/xxx.sql.gz"; exit 1; }
	gunzip -c $(FILE) | $(COMPOSE) exec -T db sh -c 'psql -U $${POSTGRES_USER:-ruqqus} $${POSTGRES_DB:-ruqqus}'

# --------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------
clean: ## Remove caches and build artefacts (does not touch the database)
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	@echo "Cleaned."
