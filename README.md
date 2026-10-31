<img width="1200" height="300" alt="NEWruqqus_text_logo" src="https://github.com/user-attachments/assets/8648830b-7345-4898-9e85-14da2fbaf33b" />

---

<div align="center">
  
[![Donate](https://img.shields.io/badge/Donate-Support%20this%20project-success?style=plastic&logo=githubsponsors&logoColor=white)](#donate)

[![Also check out REvoat](https://img.shields.io/badge/Also%20check%20out-Revoat-blue?style=plastic&logo=github&logoColor=white)](https://github.com/welchythecat/REvoat)

[![Discord](https://img.shields.io/badge/Discord-Join%20our%20server-5865F2?style=plastic&logo=discord&logoColor=white)](https://discord.gg/DEudNfXvWZ)


# NewRuqqus

NewRuqqus is a new and improved fork of ruqqus, an independent, 100% USA-based, free-speech-first social platform. That In an era of censorship and quarantines, they were bringing First Amendment rights into the digital space and were bringing it back

**This tree is a modernized fork of the original Ruqqus codebase (2019–2021). The
original site is gone; the code has been brought up to date so it runs on
current Python and current libraries, installs from scratch on Windows, Linux
and macOS, and can be deployed to a VPS.**
---

## Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Development](#development)
- [Contributing](#contributing)
- [Known issues](#known-issues)
- [License](#license)
- [Donate](#donate)

---

## Features

**Accounts**
Registration, login, logout, password reset by e-mail, e-mail verification,
profile pages with a bio, avatar colour derived from your username, account
settings, and an "alts" relationship between accounts.

**Posts**
Link posts and text posts, rendered Markdown bodies with YouTube and other
embeds, per-post permalink pages, listing pages with pagination, an Atom feed,
and domain tracking for submitted links.

**Comments**
Threaded comments on posts, Markdown rendering, permalinks, in-place editing,
deletion, and per-comment votes.

**Voting**
Upvotes and downvotes on both posts and comments, with score calculated
server-side in PostgreSQL.

**Guilds** *(not implemented — see [Known issues](#known-issues))*
The original schema has a `boards` table and a `submissions.board_id` column,
but this snapshot of the application contains no guild/board code at all: no
model, no routes, no templates. Posts are therefore flat and unclassified.

**Moderation**
Flagging of posts and comments, moderator and admin levels with promotion,
banning users, removing posts and comments, and stickying and distinguishing
posts and comments.

**Search**
Substring search across post titles, with hot/new/fiery/top sorting.

**Notifications**
Replies to your posts and comments surface on a notifications page, with an
unread count in the header.

**Operations**
Health endpoint at `/health`, rate limiting, response caching, database
migrations, a CLI to create administrators, Docker Compose deployment, and
backup/restore targets in the Makefile.

---

## Screenshots

<!-- TODO: add screenshots. Suggested set, so the layout is documented even
     before images exist:

       docs/screenshots/home.png    home / front page listing
       docs/screenshots/post.png    a post permalink with its comment thread
       docs/screenshots/user.png    user profile page
       docs/screenshots/settings.png  settings page (light and dark)
       docs/screenshots/login.png   login / signup form

     Drop the images into docs/screenshots/ and swap the line below for:

       ![Home page](docs/screenshots/home.png)

     (Written as an indented path rather than a live link so this file has no
     links to files that do not exist yet.)
-->

*Placeholder — screenshots not yet captured.* The look and feel is the original
Ruqqus design: Bootstrap 4, the stock colour scheme, and the original
templates. Nothing about the front end was redesigned in the modernization.

---

## Quick start

The fastest way to get a working site. Requires [Docker](https://docs.docker.com/get-docker/)
with the Compose plugin.

```bash
# 1. Configure
cp .env.example .env
```

Edit `.env` and set exactly two values:

```bash
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
POSTGRES_PASSWORD=<any long random string>
```

Both are deliberately left blank in `.env.example` so a missing value fails
loudly instead of running with a publicly known signing key.

```bash
# 2. Start the app, PostgreSQL and Redis
docker compose up -d --build

# 3. Create the first administrator
docker compose exec app python scripts/create_admin.py \
    --username admin --email you@example.com --password 'a-long-passphrase'

# 4. Open the site
#    http://localhost:8000
```

Log in at `/login` with the credentials you just created.

```bash
# Useful commands
docker compose logs -f app     # follow the app log
docker compose ps              # container status
docker compose down            # stop (data is kept)
docker compose down -v         # stop and delete all data
```

Check it is actually working:

```bash
curl -s http://localhost:8000/health
# {"checks": {"database": "ok", ...}, "status": "ok", "version": "..."}
```

---

## Installation

[INSTALL.md](INSTALL.md) is the full guide, tested step by step:

- [What you need](INSTALL.md#what-you-need)
- [Quick start with Docker](INSTALL.md#quick-start-with-docker)
- [Windows 10/11](INSTALL.md#windows-1011) — Docker Desktop, WSL2, or native PowerShell
- [Linux (Ubuntu/Debian, Fedora)](INSTALL.md#linux-ubuntudebian-fedora)
- [macOS](INSTALL.md#macos)
- [VPS deployment (Ubuntu server)](INSTALL.md#vps-deployment-ubuntu-server) — hardening, reverse proxy with automatic HTTPS, backups, updates
- [Creating the first admin user](INSTALL.md#creating-the-first-admin-user)
- [Verifying it works](INSTALL.md#verifying-it-works)
- [Configuration reference](INSTALL.md#configuration-reference)
- [Troubleshooting](INSTALL.md#troubleshooting)

If you are upgrading an existing Ruqqus deployment rather than starting fresh,
read [MIGRATION_NOTES.md](MIGRATION_NOTES.md) first — it lists every breaking
change, every removed feature, and why.

---

## Configuration

All configuration is read from environment variables. A `.env` file in the
project root is loaded automatically; real environment variables take
precedence over it.

**Required — the app will not start without these:**

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask's session-signing key. Anyone who obtains it can forge login sessions. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. Legacy alias: `MASTER_KEY`. |
| `DATABASE_URL` | PostgreSQL connection string. The scheme is normalised automatically, so `postgres://`, `postgresql://` and `postgresql+psycopg://` all work. Example: `postgresql://ruqqus:password@localhost:5432/ruqqus` |

**Docker Compose only** — these are read by Compose, not by the application:

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | *(none)* | Database password. Required by the Docker quick start. Compose builds `DATABASE_URL` from these three. |
| `POSTGRES_USER` | `ruqqus` | Database role. |
| `POSTGRES_DB` | `ruqqus` | Database name. |

**Everything else:**

| Variable | Default | Description |
|---|---|---|
| `TOKEN_SIGNING_KEY` | `SECRET_KEY` | Signs password-reset and e-mail-verification links. Use a distinct value in production so a leak of one key does not compromise the other. |
| `SITE_URL` | `http://localhost:8000` | Canonical base URL, without a trailing slash. Used for absolute links in e-mails and Atom feeds, and to decide when to redirect HTTP to HTTPS. Legacy alias: `domain`. |
| `REDIS_URL` | `redis://localhost:6379/0` | Response cache and rate-limit storage. Legacy aliases: `HEROKU_REDIS_PURPLE_URL`, `HEROKU_REDIS_ORANGE_URL`. |
| `CACHE_ENABLED` | off on localhost, on elsewhere | Force the cache on or off. When off, caching uses NullCache and rate limits live in process memory — fine for development. |
| `MAIL_BACKEND` | `console` | `console` prints every message to stdout instead of sending it; `smtp` sends real mail and requires `SMTP_HOST`. |
| `MAIL_FROM` | `Ruqqus <noreply@localhost>` | From-address for all outgoing mail. |
| `SMTP_HOST` | *(none)* | SMTP server. Required when `MAIL_BACKEND=smtp`. |
| `SMTP_PORT` | `587` | SMTP port. |
| `SMTP_USER` | *(none)* | SMTP username. |
| `SMTP_PASSWORD` | *(none)* | SMTP password. |
| `SMTP_USE_TLS` | `true` | Use STARTTLS. |
| `SMTP_TIMEOUT` | `10` | SMTP timeout in seconds. |
| `BEHIND_PROXY` | `true` | How many reverse proxies to trust. `true` trusts one layer of `X-Forwarded-*`, which is what Caddy and Nginx send. Set to `false` when the app is exposed directly. |
| `PORT` | `8000` | Port for the development server (`python run_dev.py`). Production reads the port from gunicorn's `-b` flag instead. |
| `LOG_LEVEL` | `INFO` | Root logger level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `UPLOAD_DIR` | `<project root>/uploads` | Reserved for future upload handling. The original code had none. |

**Removed variables** — setting these has no effect:

| Variable | Replaced by |
|---|---|
| `MAILGUN_KEY` | `MAIL_BACKEND=smtp` plus the `SMTP_*` variables |
| `reddit_id`, `reddit_secret` | — the Reddit integration was deleted |

[.env.example](.env.example) is the authoritative, fully commented reference.

---

## Project structure

```
.
├── ruqqus/                  The application package
│   ├── __main__.py          App factory: Flask, SQLAlchemy, Redis, cache, limiter
│   ├── config.py            Every setting, read from the environment
│   ├── classes/             SQLAlchemy models (User, Submission, Comment, Vote, ...)
│   ├── routes/              Flask blueprints: front, posts, comments, votes,
│   │                        login, settings, search, admin, flagging, errors, health
│   ├── helpers/             Markdown rendering, sanitising, formkeys, base36,
│   │                        embeds, Jinja filters, auth wrappers
│   ├── mail/                Outgoing mail and the e-mail-verification handler
│   ├── templates/           Jinja2 templates — the original front end
│   └── assets/              CSS (from SCSS), JavaScript, images
├── migrations/              Alembic migrations (0001_initial builds the schema)
├── tests/                   Pytest suite (246 cases)
├── scripts/                 create_admin.py, startup.sh, healthcheck.py,
│                            migrate_old_db.py, css.sh
├── docs/                    Project documentation site
├── Dockerfile               Application image
├── docker-compose.yml       App + PostgreSQL + Redis
├── Makefile                 Common tasks: setup, migrate, dev, test, backup, ...
├── run_dev.py               Development server entry point
├── alembic.ini              Migration configuration
├── requirements.txt         Runtime dependencies (pinned)
├── requirements-dev.txt     Runtime + test/lint dependencies
├── pytest.ini               Test configuration
├── ruff.toml                Lint and format configuration
├── schema.txt               Read-only reference dump of the original schema
├── .env.example             Documented configuration template
├── INSTALL.md               Full installation and deployment guide
├── MIGRATION_NOTES.md       What changed, what was removed, breaking changes
├── AUDIT.md                 Original codebase audit
└── LICENSE                  MPL-2.0
```

---

## Development

```bash
# One-time setup: creates .venv, installs dependencies, creates .env
make setup

# Build the schema
make migrate

# Run the development server with auto-reload
make dev

# Run the tests
make test

# Lint / auto-format
make lint
make format
```

Or without `make`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env          # then edit SECRET_KEY and DATABASE_URL
.venv/bin/alembic upgrade head
.venv/bin/python run_dev.py --debug
```

You need PostgreSQL running and a `DATABASE_URL` pointing at it. Redis is
optional in development — with `CACHE_ENABLED` off the cache falls back to
NullCache and rate limits are kept in memory.

### Tests

```bash
python -m pytest -q
```

The suite runs against a real PostgreSQL database. Set `RUQQUS_TEST_DATABASE_URL`
to a throwaway database; if unset, it falls back to `DATABASE_URL`. The CI
workflow ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the tests on
Python 3.12 and 3.13 against a PostgreSQL 16 service container, lints with ruff,
and runs `pip-audit` against both requirements files.

Tests that pin a known defect are marked `xfail(strict=True)`, so a defect that
gets fixed fails loudly rather than silently becoming a pass. The list of those
defects is in [MIGRATION_NOTES.md](MIGRATION_NOTES.md#8-known-defects-and-deferred-work).

### Building CSS

The stylesheets are compiled from SCSS. [`scripts/css.sh`](scripts/css.sh) is
the whole build:

```bash
sh scripts/css.sh
# sass ruqqus/assets/style/main.scss      ruqqus/assets/style/main.css
# sass ruqqus/assets/style/main_dark.scss ruqqus/assets/style/main_dark.css
```

Both `.css` files are committed, so you only need `sass` if you change the
`.scss` sources.

---

## Contributing

1. **Read [MIGRATION_NOTES.md](MIGRATION_NOTES.md)** before proposing changes
   to anything it covers. Several things in this codebase look like bugs and are
   not — `users.is_banned` is an integer holding the banning admin's id, for
   instance, and the `ups()`/`downs()` score columns are PostgreSQL functions.

2. **Keep the look and feel.** This fork's stated goal is to modernize the stack
   without redesigning the interface. Changes to templates, CSS or layout should
   fix broken markup or behaviour, not change how pages look. If a redesign is
   the point, say so explicitly in the PR.

3. **Keep the features.** Do not remove a feature silently. If something has to
   go or be stubbed — typically because it depends on a dead third-party
   service — record it in `MIGRATION_NOTES.md` with the reason and a replacement
   suggestion.

4. **Do not commit secrets.** No API keys, passwords, tokens or private URLs.
   `.env` is gitignored and must stay that way; put new settings in
   `.env.example` as placeholders with a comment explaining them.

5. **Keep the licence.** This project is MPL-2.0. Keep the `LICENSE` file, and
   keep any file you modify under MPL-2.0.

6. **Run the checks before submitting.**

   ```bash
   make test
   make lint
   ```

7. **Add tests for behaviour changes.** If you fix one of the `xfail` defects,
   the strict marker will make the suite fail — remove the `xfail` in the same
   change.

---

## Known issues

**Guilds (communities) are not implemented.** This is a listed core feature, and
it is absent from this snapshot of the application rather than disabled by the
modernization. The original database schema has the hooks — a `boards` table and
a `submissions.board_id` column — but there is no `Board` model, no guild
routes and no guild templates anywhere in the code, and no occurrence of the
word "guild". Posts are flat and unclassified. This migration keeps the hooks
out of the schema; re-adding them is a feature build, not a config change. Full
detail and a suggested route to implement it are in
[MIGRATION_NOTES.md](MIGRATION_NOTES.md#5-removed-and-replaced-features).

**Self-service signup returns 500.** `badge_defs` is not seeded by the
migration, and every signup inserts `badge_id=1`, which violates a foreign key.
The user row still commits, so a partial account is created that can log in —
the visitor just sees an error. **Workaround:** create accounts with
`scripts/create_admin.py`, which does not award badges. Full details and the
suggested fix are in [MIGRATION_NOTES.md](MIGRATION_NOTES.md#4-database-changes).

A number of security-hardening items (CSRF coverage, cookie flags, open
redirects, token expiry) are documented but not yet done — they were
deliberately deferred. See
[MIGRATION_NOTES.md §8](MIGRATION_NOTES.md#8-known-defects-and-deferred-work).

---

## License

Mozilla Public License Version 2.0. See [LICENSE](LICENSE).

Original Ruqqus source is © the Ruqqus contributors. MPL-2.0 is a file-level
copyleft: if you distribute this, modified files must stay under MPL-2.0 and you
must share your changes to them. See
[MIGRATION_NOTES.md §9](MIGRATION_NOTES.md#9-license-and-attribution) for how
that applies here.

## Donate

**BTC** - `bc1qh4hgx2nnsye0lf2w6rar8wj3j3j4cdwc0nnr7h`

**ETH** - `0x261df8c7CBDe616f335Dd81caB235Ec0bE914b2f`

**SOL** - `8NAwwC7pTCteMrf61uoiQYTZAoYEurWJ51gYtCgdHuM2`
