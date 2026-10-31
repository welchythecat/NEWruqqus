# Installing Ruqqus

Ruqqus is a Flask + PostgreSQL + Redis web application. There are two ways to
run it:

| Path | Best for | Section |
|---|---|---|
| **Docker Compose** (recommended) | Everything, including Windows | [Quick start with Docker](#quick-start-with-docker) |
| **No Docker** | Debugging, development, hosts without Docker | [Windows](#windows-1011) · [Linux](#linux-ubuntudebian-fedora) · [macOS](#macos) |

Both paths end at the same place: a running site, a migrated database, and an
administrator account.

> **Status note:** the dependency stack was modernised in Phase 2 of this
> migration (Flask 3, SQLAlchemy 2, psycopg 3). The security hardening
> (Phase 3) and the test suite (Phase 4) are tracked separately — see
> `CHANGELOG.md` and `MIGRATION_NOTES.md` for what is and is not in place yet.

---

## Contents

1. [What you need](#what-you-need)
2. [Quick start with Docker](#quick-start-with-docker)
3. [Windows 10/11](#windows-1011)
4. [Linux (Ubuntu/Debian, Fedora)](#linux-ubuntudebian-fedora)
5. [macOS](#macos)
6. [VPS deployment](#vps-deployment-ubuntu-server)
7. [Creating the first admin user](#creating-the-first-admin-user)
8. [Verifying it works](#verifying-it-works)
9. [Configuration reference](#configuration-reference)
10. [Troubleshooting](#troubleshooting)

---

## What you need

**Runtime**

| Component | Minimum | Notes |
|---|---|---|
| Python | 3.12 | 3.12 or 3.13 |
| PostgreSQL | 15 | 16 recommended |
| Redis | 7 | Optional in development — the cache falls back to `NullCache` |
| Docker + Compose v2 | 24 / 2.20 | Only for the Docker path |

**Common to every path**

```bash
git clone <your-fork-url> ruqqus
cd ruqqus
```

Every command below is run from that directory.

---

## Quick start with Docker

This is the shortest path and works identically on Windows, macOS and Linux.

### 1. Create your configuration

**Linux / macOS / WSL2 / Git Bash:**

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
py -c "import secrets; print(secrets.token_hex(32))"
```

Open `.env` in any editor and set exactly two values:

```ini
SECRET_KEY=paste-the-64-character-hex-string-here
POSTGRES_PASSWORD=pick-a-long-random-database-password
```

> `docker compose` reads `.env` for `${VARIABLE}` substitution. It needs
> `SECRET_KEY` and `POSTGRES_PASSWORD`; everything else has a working default.

### 2. Start everything

```bash
docker compose up -d --build
```

First build takes a few minutes. You can watch progress with:

```bash
docker compose logs -f app
```

When it settles you should see gunicorn start. Check the health endpoint:

```bash
curl -i http://localhost:8000/health
```

Expected:

```
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "ok", "version": "0.5.0", "checks": {"database": "ok", "cache": "ok"}}
```

### 3. Create the first admin

```bash
docker compose exec app python scripts/create_admin.py \
    --username admin --email admin@example.com
```

It prompts for a password twice and does not echo it. See
[Creating the first admin user](#creating-the-first-admin-user) for options.

### 4. Open the site

<http://localhost:8000> — log in with the account you just made.

**That's it.** The remaining sections are for running without Docker, and for
putting the site on a real server.

### Stopping and starting again

```bash
docker compose down      # stop (database contents are kept)
docker compose up -d     # start again
```

### Wiping everything and starting over

```bash
docker compose down -v   # DELETES the database and all uploads
docker compose up -d --build
```

---

## Windows 10/11

You have three options. **Pick Docker Desktop unless you have a reason not
to** — Redis has no official Windows build, so the no-Docker route means WSL2.

| Option | Effort | Notes |
|---|---|---|
| **A. Docker Desktop** | Low | [Quick start with Docker](#quick-start-with-docker) above applies unchanged |
| **B. WSL2 (Ubuntu)** | Medium | Full Linux toolchain; follow the [Linux](#linux-ubuntudebian-fedora) steps *inside* WSL2 |
| **C. Native PowerShell** | High | Redis is the sticking point; see below |

### Option A — Docker Desktop

1. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/) and enable the WSL2 backend.
2. Install [Git for Windows](https://git-scm.com/download/win) (gives you Git Bash).
3. Open **Git Bash** and follow [Quick start with Docker](#quick-start-with-docker).

### Option B — WSL2 (recommended if you want no Docker)

```powershell
# In an *elevated* PowerShell:
wsl --install -d Ubuntu
```

Restart, open **Ubuntu** from the Start menu, create your Linux user, then:

```bash
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip \
    postgresql redis-server
```

Continue from step 2 of [Linux (Ubuntu/Debian)](#linux-ubuntudebian-fedora).

> Your files live in the WSL2 filesystem (`\\wsl$\Ubuntu\home\<you>\...`).
> Keep the checkout there rather than under `/mnt/c/...` — cross-filesystem
> I/O is roughly 10x slower and PostgreSQL on `/mnt/c` is unreliable.

### Option C — Native PowerShell (no Docker, no WSL2)

**Prerequisites**

```powershell
# Python 3.12+ and PostgreSQL 16
winget install Python.Python.3.12
winget install PostgreSQL.PostgreSQL.16

# Redis has no official Windows build. Either:
winget install Memurai.MemuraiDeveloper      # Redis-compatible, free for dev
# ...or skip Redis entirely (the cache falls back to NullCache).
```

Open **PowerShell** and clone and set up:

```powershell
cd $env:USERPROFILE\Downloads
git clone <your-fork-url> ruqqus
cd ruqqus

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> If `Activate.ps1` is blocked, run
> `Set-ExecutionPolicy -Scope Process Bypass` first, or use
> `.\.venv\Scripts\python.exe` in place of `python` everywhere below.

**Create the database**

```powershell
# The EDB installer adds PostgreSQL to PATH in a *new* shell. Open a fresh one.
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE ROLE ruqqus LOGIN PASSWORD 'choose-a-password';"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE ruqqus OWNER ruqqus;"
```

**Configure**

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
notepad .env
```

Set at least:

```ini
SECRET_KEY=paste-the-hex-string-from-above
DATABASE_URL=postgresql://ruqqus:choose-a-password@localhost:5432/ruqqus
```

If you skipped Redis, also set `CACHE_ENABLED=false`. Otherwise set
`REDIS_URL=redis://localhost:6379/0`.

**Build the database schema and run**

```powershell
alembic upgrade head
python run_dev.py --debug
```

Then follow [Creating the first admin user](#creating-the-first-admin-user)
and [Verifying it works](#verifying-it-works).

---

## Linux (Ubuntu/Debian, Fedora)

### Prerequisites

**Ubuntu / Debian**

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip \
    postgresql postgresql-contrib redis-server
```

**Fedora**

```bash
sudo dnf install -y git python3 python3-pip postgresql-server redis
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql redis
```

Both distributions: PostgreSQL and Redis should now be running.

```bash
systemctl is-active postgresql redis    # expect: active / active
```

### Create a database and role

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE ruqqus LOGIN PASSWORD 'choose-a-password';
CREATE DATABASE ruqqus OWNER ruqqus;
SQL
```

### Install

```bash
git clone <your-fork-url> ruqqus
cd ruqqus

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
nano .env
```

Set at least:

```ini
SECRET_KEY=paste-the-hex-string-from-above
DATABASE_URL=postgresql://ruqqus:choose-a-password@localhost:5432/ruqqus
REDIS_URL=redis://localhost:6379/0
```

### Build the schema and run

```bash
alembic upgrade head
python run_dev.py --debug
```

For a production-style local run instead (gunicorn):

```bash
sh scripts/startup.sh
```

Then follow [Creating the first admin user](#creating-the-first-admin-user)
and [Verifying it works](#verifying-it-works).

### Using make instead

If you have `make`, the same steps are:

```bash
make setup      # venv + deps + .env
make migrate    # alembic upgrade head
make create-admin
make dev        # or: make run
```

---

## macOS

### Prerequisites

Install [Homebrew](https://brew.sh), then:

```bash
brew install python@3.12 postgresql@16 redis git
brew services start postgresql@16
brew services start redis
```

Homebrew does not put `postgresql@16` on your `PATH` automatically:

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

> On Intel Macs the prefix is `/usr/local/opt/postgresql@16`.

### Create a database and role

```bash
psql postgres <<'SQL'
CREATE ROLE ruqqus LOGIN PASSWORD 'choose-a-password';
CREATE DATABASE ruqqus OWNER ruqqus;
SQL
```

### Install

```bash
git clone <your-fork-url> ruqqus
cd ruqqus

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Configure and run

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
nano .env                       # set SECRET_KEY and DATABASE_URL
alembic upgrade head
python run_dev.py --debug
```

Then follow [Creating the first admin user](#creating-the-first-admin-user)
and [Verifying it works](#verifying-it-works).

---

## VPS deployment (Ubuntu server)

Target: **Ubuntu 24.04 LTS**, one server, Docker Compose, automatic HTTPS.

### 1. Server hardening

```bash
# Create a non-root user (skip if your host already made one)
adduser deploy
usermod -aG sudo deploy
usermod -aG docker deploy        # after installing Docker, step 2

# Firewall: allow only SSH and HTTP(S)
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

> Do **not** open port 8000 in the firewall. Traffic should reach the app only
> through the reverse proxy.

### 2. Docker and Compose

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out and back in for the group change to apply
docker compose version           # expect: Docker Compose version v2.x
```

### 3. Deploy the application

```bash
sudo mkdir -p /srv/ruqqus
sudo chown $USER:$USER /srv/ruqqus
cd /srv/ruqqus

git clone <your-fork-url> .
cp .env.example .env
```

Edit `.env`. For a public server you need at minimum:

```ini
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
POSTGRES_PASSWORD=<long random value>
SITE_URL=https://ruqqus.example.com
BEHIND_PROXY=true
```

Start it:

```bash
docker compose up -d --build
docker compose ps                # all three services should be "healthy"
```

### 4. Reverse proxy with automatic HTTPS

**Option A — Caddy (recommended: one file, automatic Let's Encrypt)**

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

Replace `/etc/caddy/Caddyfile` with:

```
ruqqus.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

Caddy obtains and renews the Let's Encrypt certificate automatically. There is
nothing else to do.

**Option B — Nginx + Certbot**

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/ruqqus`:

```nginx
server {
    listen 80;
    server_name ruqqus.example.com;

    client_max_body_size 8m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/ruqqus /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d ruqqus.example.com
# choose "Redirect" when asked; certbot renews itself via a systemd timer
sudo systemctl list-timers | grep certbot
```

Whichever you chose, confirm HTTPS works:

```bash
curl -i https://ruqqus.example.com/health
```

### 5. Restrict the app port to loopback

Now that the proxy is in place, edit `docker-compose.yml` so the app is not
reachable directly:

```yaml
    ports:
      - "127.0.0.1:8000:8000"
```

```bash
docker compose up -d
```

### 6. Restart policy

`docker compose.yml` already sets `restart: unless-stopped` on all three
services, so Docker restarts them after a crash or a reboot. Verify:

```bash
sudo reboot
# ...reconnect...
docker compose ps
```

### 7. Create the first admin

```bash
docker compose exec app python scripts/create_admin.py \
    --username admin --email admin@example.com
```

### 8. Backups

**Database (nightly, kept 14 days)**

```bash
sudo mkdir -p /srv/ruqqus/backups
sudo chown $USER:$USER /srv/ruqqus/backups

crontab -e
```

```cron
# m h dom mon dow command
17 3 * * *  cd /srv/ruqqus && /usr/bin/make backup >> /srv/ruqqus/backups/backup.log 2>&1
17 4 * * *  find /srv/ruqqus/backups -name 'ruqqus-*.sql.gz' -mtime +14 -delete
```

Test it now rather than at 3am:

```bash
cd /srv/ruqqus && make backup
ls -lh backups/
```

**Off-site.** Copy the dumps somewhere the server is not:

```bash
# Example: rsync to another host
rsync -avz /srv/ruqqus/backups/ backup@backup-host:/srv/ruqqus-backups/
```

**Restore**

```bash
cd /srv/ruqqus
make restore FILE=backups/ruqqus-20261030-031700.sql.gz
docker compose restart app
```

**Uploads** (`uploads/` volume, reserved for future use):

```bash
docker compose run --rm --no-deps -v /srv/ruqqus/backups:/backup app \
    tar czf /backup/uploads-$(date +%Y%m%d).tar.gz -C /app uploads
```

### 9. Updating

```bash
cd /srv/ruqqus

make backup                      # always back up first

git pull
docker compose up -d --build     # rebuilds and restarts; runs migrations
docker compose ps                # wait for "healthy"
curl -s https://ruqqus.example.com/health
```

`scripts/startup.sh` runs `alembic upgrade head` on every start, so migrations
are applied automatically. If a deploy goes wrong:

```bash
docker compose logs --tail=100 app
git log -1 --oneline             # find the last good commit
git checkout <that-commit>
docker compose up -d --build
```

### 10. Ops checklist

- [ ] `ufw status` shows only 22, 80, 443
- [ ] `docker compose ps` — all three services healthy
- [ ] `curl -i https://<domain>/health` returns 200
- [ ] `curl -I http://<domain>/` returns `301` to `https://`
- [ ] Nightly `make backup` runs and files appear in `backups/`
- [ ] A restore has been tested at least once
- [ ] `docker compose exec db psql -U ruqqus -c '\du'` — only expected roles

---

## Creating the first admin user

```bash
python scripts/create_admin.py --username admin --email admin@example.com
```

Inside Docker:

```bash
docker compose exec app python scripts/create_admin.py \
    --username admin --email admin@example.com
```

The script prompts for a password twice (not echoed). Full options:

| Flag | Meaning |
|---|---|
| `--username` | Required. 5–25 letters, digits or underscores |
| `--email` | Optional but recommended — enables password reset |
| `--password` | Supply non-interactively (CI, scripting) |
| `--level 1-3` | `1` = moderate comments, `3` = full admin (default) |
| `--promote-only` | Raise an existing account; never create or set a password |

It is idempotent — running it again just updates the level.

Admin levels used by the code:

| Level | Can do |
|---|---|
| 0 | Ordinary user |
| 1 | Distinguish/remove individual comments |
| 3 | Ban users, ban/restore posts, sticky, manage admins |

---

## Verifying it works

Run these from any machine that can reach the site.

**1. Health endpoint**

```bash
curl -i http://localhost:8000/health
```

Expect `HTTP/1.1 200 OK` and `"status": "ok"`. A `503` means one of
`database`/`cache` is `"failed"` — the JSON body says which.

**2. Pages render**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/            # 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/login       # 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/help/about  # 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/assets/style/main.css  # 200
```

If `/assets/style/main.css` is not `200`, the site will look unstyled — see
Troubleshooting.

**3. Log in and post**

1. Open `http://localhost:8000/login` and sign in with the admin account.
2. `http://localhost:8000/submit` — create a text post.
3. Open the post and leave a comment.
4. Reload — both should still be there.

**4. Database objects**

```bash
docker compose exec db psql -U ruqqus -d ruqqus -c '\dt'
```

Expect 13 tables plus `alembic_version`:

```
alts, badge_defs, badges, commentflags, commentvotes, comments,
domains, flags, images, notifications, submissions, users, votes
```

```bash
docker compose exec db psql -U ruqqus -d ruqqus -c '\df ups'
```

Expect two overloads: `ups(submissions)` and `ups(comments)`. These are
row-wise functions — they are *not* columns, and if they are missing, post
scores will not render.

**5. Migration state**

```bash
docker compose exec app alembic current
```

Expect `0001_initial (head)`.

---

## Configuration reference

Every setting is documented in [`.env.example`](.env.example). The ones you
are most likely to touch:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **yes** | — | Signs login sessions. Rotating it logs everyone out |
| `DATABASE_URL` | **yes** | — | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | **yes** (Docker) | — | Password for the database role |
| `SITE_URL` | recommended | `http://localhost:8000` | Canonical URL; used in e-mails and HTTPS redirects |
| `REDIS_URL` | no | `redis://localhost:6379/0` | Cache and rate-limit storage |
| `CACHE_ENABLED` | no | on except localhost | Set `false` to disable caching entirely |
| `MAIL_BACKEND` | no | `console` | `console` logs mail; `smtp` sends it |
| `SMTP_HOST` etc. | if smtp | — | See `.env.example` |
| `BEHIND_PROXY` | no | `true` | Trust `X-Forwarded-*` from Caddy/Nginx |
| `WEB_CONCURRENCY` | no | `2` | gunicorn worker count |
| `TOKEN_SIGNING_KEY` | no | falls back to `SECRET_KEY` | Signs e-mail links. Set a distinct value in production |

The old environment names still work as aliases: `MASTER_KEY` → `SECRET_KEY`,
`domain` → `SITE_URL`, `HEROKU_REDIS_*` → `REDIS_URL`. `MAILGUN_KEY`,
`reddit_id` and `reddit_secret` are gone.

---

## Troubleshooting

### `Error: Required configuration 'SECRET_KEY' is not set`

`.env` is missing or unreadable, or you are running from a different directory.
Check:

```bash
ls -la .env
grep -c SECRET_KEY .env
```

`.env` is loaded from the project root (the directory containing `ruqqus/`).

### `Error: Required configuration 'DATABASE_URL' is not set`

Same cause. Set `DATABASE_URL` in `.env`, or export it in your shell.

### `psycopg.OperationalError: connection refused` / `could not connect to server`

PostgreSQL is not running, or the host/port is wrong.

```bash
systemctl is-active postgresql                 # Linux
brew services list | grep postgres             # macOS
docker compose ps                              # Docker
```

Inside Docker the host must be `db`, not `localhost`. `docker compose`
constructs `DATABASE_URL` for you — if you override it, keep the hostname `db`.

### `relation "users" does not exist`

Migrations have not been applied.

```bash
alembic upgrade head
# or
docker compose exec app alembic upgrade head
```

### `password authentication failed for user "ruqqus"`

The password in `DATABASE_URL` does not match the role. Recreate it:

```bash
sudo -u postgres psql -c "ALTER ROLE ruqqus PASSWORD 'choose-a-password';"
```

Then update `DATABASE_URL` (and `POSTGRES_PASSWORD` for Docker) to match.

### `FATAL: database "ruqqus" does not exist`

```bash
sudo -u postgres psql -c "CREATE DATABASE ruqqus OWNER ruqqus;"
alembic upgrade head
```

### The site loads but has no styling (plain HTML)

`/assets/style/main.css` is not being served.

```bash
curl -I http://localhost:8000/assets/style/main.css
ls ruqqus/assets/style/main.css        # must exist and be non-empty
```

If the file is missing, your checkout is incomplete — `main.css` is committed
and needs no build step. If the request `404`s but the file exists, you are
probably running from the wrong directory; the app resolves `ruqqus/assets`
relative to the package, so start it from the project root.

### `TypeError: ... 'NoneType' ...` when loading a page

Almost always a missing row-wise SQL function (scores/counts come from
PostgreSQL functions, not columns).

```bash
docker compose exec db psql -U ruqqus -d ruqqus -c '\df'
```

You should see `ups`, `downs`, `age`, `score`, `rank_hot`, `rank_fiery`,
`comment_count`, `flag_count`, `energy`, `referral_count`, `splash` and the
notification helpers. If they are missing:

```bash
python -m ruqqus.helpers.db_prep
```

### `Connection refused` from `/health` but the process is running

You set `PORT` to something other than the port the app bound to. The health
probe reads `PORT`; gunicorn binds `0.0.0.0:$PORT`. Keep them equal.

### Redis errors (`Connection refused ... 6379`)

Redis is not running. Either start it, or turn the cache off:

```ini
CACHE_ENABLED=false
```

In Docker this means the `redis` service is not up — `docker compose ps`.

### `Permission denied` writing to `uploads/`

The directory is owned by root from an earlier run as root.

```bash
sudo chown -R 1000:1000 uploads
```

(UID 1000 is the `ruqqus` user created in the Dockerfile.)

### Port 8000 is already in use

```bash
# Linux / macOS
lsof -i :8000
# Windows PowerShell
netstat -ano | findstr :8000
```

Either stop that process, or change the host port:

```ini
# docker-compose.yml
ports:
  - "8080:8000"
```

### `make: command not found`

`make` is optional. Every target is a short command listed above — run those
directly. On Windows, use WSL2 or Git Bash, or skip `make` entirely.

### Windows: `running scripts is disabled on this system`

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

### Windows: PostgreSQL starts but `psql` is not found

The EDB installer only adds it to `PATH` for *new* shells. Open a new terminal,
or call it explicitly:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres
```

### `alembic` / `gunicorn` / `ruff`: command not found

Your virtualenv is not active, or you are outside it.

```bash
source .venv/bin/activate        # Linux / macOS
.\.venv\Scripts\Activate.ps1     # Windows
which alembic                    # should point inside .venv
```

Or call it explicitly: `.venv/bin/alembic upgrade head`.

### Docker build fails with a network error

Retry — PyPI mirrors occasionally time out:

```bash
docker compose build --no-cache
```

### Everything starts but the site is slow

Usually the cache is disabled on a non-localhost `SITE_URL`, or Redis is down.
Check the startup banner from `run_dev.py`, which prints the cache backend:

```bash
python run_dev.py
# cache         NullCache      <- caching is off
```

### Where are the logs?

| Mode | Command |
|---|---|
| Docker | `docker compose logs -f app` |
| `run_dev.py` | stdout of that terminal |
| gunicorn | stdout of `scripts/startup.sh` |
| systemd | `journalctl -u ruqqus -f` |
| Outgoing mail | `docker compose logs app` — the `console` mail backend prints the full message here, including verification links |

### Still stuck

1. `docker compose ps` (or `make ps`) — is everything healthy?
2. `curl -i http://localhost:8000/health` — what does the JSON say?
3. `docker compose logs --tail=200 app` — the last 200 lines almost always have it.
4. Check `AUDIT.md` for known issues in the original codebase.
