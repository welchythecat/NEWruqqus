# Migration notes

This document records what changed between the original Ruqqus source
(2019–2021, written for Flask 1.x and Heroku) and this modernized tree, so you
can upgrade an existing deployment without surprises and understand why the
code no longer looks like it did.

If you are installing from scratch you do not need this file — read
[INSTALL.md](INSTALL.md) instead.

---

## Contents

1. [At a glance](#1-at-a-glance)
2. [Runtime and dependencies](#2-runtime-and-dependencies)
3. [Configuration changes](#3-configuration-changes)
4. [Database changes](#4-database-changes)
5. [Removed and replaced features](#5-removed-and-replaced-features)
6. [Files removed in the cleanup pass](#6-files-removed-in-the-cleanup-pass)
7. [Breaking changes for an existing deployment](#7-breaking-changes-for-an-existing-deployment)
8. [Known defects and deferred work](#8-known-defects-and-deferred-work)
9. [License and attribution](#9-license-and-attribution)

---

## 1. At a glance

| Area | Original | Now |
|---|---|---|
| Python | 3.7 | 3.12+ (tested 3.12 / 3.13) |
| Flask | 1.1.1 | 3.1.3 |
| Werkzeug | 0.15.5 | 3.1.9 |
| SQLAlchemy | 1.3.5 | 2.1.6 |
| PostgreSQL driver | psycopg2-binary 2.8.3 | psycopg 3.3.6 |
| Alembic | unversioned | 1.20.1 |
| Web server | gunicorn 19.9.0 + gevent 1.4.0 | gunicorn 26.2.0, sync workers |
| Redis client | not pinned | redis 8.1.0 |
| Schema source | `schema.txt` dump | Alembic migration `0001_initial` |
| Configuration | hardcoded + Heroku config vars | environment variables + `.env` |
| Deploy | Heroku only | Docker Compose, or bare metal; see [INSTALL.md](INSTALL.md) |
| Tests | `test.py` (contained only `pass`) | 240 pytest cases + GitHub Actions |
| Password hashing | `pbkdf2:sha512` | `pbkdf2:sha512` (unchanged — see §8) |
| Guilds (communities) | schema tables only, no code | **not implemented** — see §5 |

Nothing in the front end was redesigned. Templates, CSS, Bootstrap 4 classes,
the colour scheme, the layout and the copy are the original ones. Markup was
only touched where it was broken.

One caveat on "the original ones": the modernization did not drop any feature
that this source snapshot actually had, but the snapshot itself is missing the
guild/community feature that the product is known for. That gap predates this
work and is documented rather than papered over — see [§5](#5-removed-and-replaced-features).

---

## 2. Runtime and dependencies

### Dropped

| Package | Why |
|---|---|
| `praw`, `prawcore`, `update-checker`, `websocket-client` | Reddit integration was deleted along with `routes/reddit_api.py`. It talked to a third-party service and needed API keys. |
| `python-binary-memcached`, `uhashring` | The memcached cache backend was never used; caching is Redis or NullCache. |
| `gevent` | The app is I/O-light. Gunicorn's default sync workers are simpler and far better supported. Add more workers before reaching for a different worker class. |
| `psycopg2-binary` | Replaced by `psycopg` 3. |
| `Flask-Markdown` | Abandoned in 2014 and incompatible with Flask 3. Replaced by a local Jinja filter, `ruqqus/helpers/markdown_filter.py`, that renders identically. |
| `requests`, `PyYAML` | No longer imported anywhere. |
| `certifi`, `chardet`, `idna`, `urllib3`, `six` | Transitive dependencies of `requests`; dropped along with it. |
| `typing` | Backport. Built into Python 3.12+. |

### Added

| Package | Why |
|---|---|
| `alembic` | Schema is now migrated rather than loaded from a SQL dump. |
| `python-dotenv` | Loads `.env` so a local checkout needs no exported variables. |

### Notable API changes that had to be made

- **`hmac.new()` lost its implicit `digestmod` in Python 3.13.** Both calls in
  `ruqqus/routes/login.py` now spell out `digestmod="md5"`. Token values are
  byte-identical to what Python ≤ 3.12 produced, so existing sessions survive.
- **`limits` 5.x removed `fixed-window-elastic-expiry`.** The strategy string in
  `ruqqus/__main__.py` is now `fixed-window`. See [§8](#8-known-defects-and-deferred-work).
- **SQLAlchemy 2.x resolves a bare `postgresql://` to psycopg2**, which is not
  installed, and rejects `postgres://` outright. `ruqqus/config.py` rewrites
  both to `postgresql+psycopg://` automatically, so a connection string from any
  host can be pasted as-is.

---

## 3. Configuration changes

Everything is now read from the environment. `.env.example` is the complete,
documented reference. The important differences from the original:

### Renamed (old name still works as an alias)

| Old | New |
|---|---|
| `MASTER_KEY` | `SECRET_KEY` |
| `domain` | `SITE_URL` |
| `HEROKU_REDIS_PURPLE_URL` / `HEROKU_REDIS_ORANGE_URL` | `REDIS_URL` |

### Removed — these no longer exist and setting them has no effect

| Variable | Why |
|---|---|
| `MAILGUN_KEY` | The site was hardcoded to Mailgun. Replaced by `MAIL_BACKEND=smtp` plus `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_USE_TLS`. |
| `reddit_id`, `reddit_secret` | Reddit integration deleted. |

### Added

| Variable | Purpose |
|---|---|
| `MAIL_BACKEND` | `console` (default, prints to stdout) or `smtp`. |
| `MAIL_FROM` | From-address for outgoing mail. |
| `CACHE_ENABLED` | Force the response cache on/off. Defaults to off on localhost, on elsewhere. |
| `BEHIND_PROXY` | How many reverse proxies to trust. Set to `false` when exposed directly. |
| `LOG_LEVEL` | `DEBUG` … `CRITICAL`. |
| `UPLOAD_DIR` | Reserved for future upload handling. The original code had none. |
| `POSTGRES_PASSWORD` / `POSTGRES_USER` / `POSTGRES_DB` | Docker Compose only. The app does not read them. |

### Domain-specific hardcoded values that were removed

The original code contained Ruqqus's own domain names, e-mail provider
credentials, image and file hosting URLs, analytics identifiers and Heroku
behaviour. All of it is gone. Anything that needs a site-identity value now
comes from `SITE_URL`.

---

## 4. Database changes

- **The schema is managed by Alembic.** Run `alembic upgrade head` (or
  `scripts/startup.sh`, which does it on every boot). `schema.txt` is kept as a
  read-only reference dump of the original schema; it is not used at runtime.
- **13 tables**, unchanged from the original: `alts`, `badge_defs`, `badges`,
  `commentflags`, `commentvotes`, `comments`, `domains`, `flags`, `images`,
  `notifications`, `submissions`, `users`, `votes`. Plus `alembic_version`.
- **Tables that were removed because nothing reads or writes them:**
  `dms`, `ips`, `userflags`.
- **`boards` and `submissions.board_id` were also dropped — but for a different
  reason.** They are the schema hooks for guilds (communities), which is a core
  feature of the product. This snapshot of the application has **no guild code
  at all** — no model, no routes, no templates, and not one occurrence of the
  word "guild" — so the hooks were orphaned. See
  [§5](#5-removed-and-replaced-features) before deciding to drop them for good.
- **PostgreSQL row-wise functions are part of the schema.** `ups()`, `downs()`,
  `age()`, `comment_count()` and friends are *functions*, not columns. The ORM
  declares them with `server_default=FetchedValue()` so every `SELECT` includes
  them in the column list. `ups()` must have **both** overloads —
  `ups(submissions)` and `ups(comments)` — or post and comment scores will not
  render. Verify with `psql -c '\df ups'`.
- **`users.is_banned` is an integer, not a boolean.** It stores the **user id of
  the admin who issued the ban**, and `0` means not banned. Do not "fix" it to a
  boolean. `User.banned_by` resolves it to a `User`.

### ⚠️ `badge_defs` is empty on a fresh install

`badges.badge_id` has a foreign key to `badge_defs.id`, but the migration seeds
no rows, and `routes/login.py` inserts `badge_id=1` on every signup. The result:

```
POST /signup -> 500
sqlalchemy.exc.IntegrityError: (psycopg.errors.ForeignKeyViolation)
  Key (badge_id)=(1) is not present in table "badge_defs".
```

The user row commits *before* the badge insert fails, so **a partial account is
created and it can actually log in** — the visitor sees a 500, concludes that
signup failed, and is then told the username is taken if they retry.

The original row content is not recoverable from the source tree (the shipped
schema dump is schema-only). The icons that ship in the repository are `beta`,
`mail`, `alpha`, `git`, `prebeta`, `reddit`, `shame` and `whitehat`; the code
comments identify `badge_id=1` as the **beta** badge
(`routes/login.py`) and `badge_id=2` as the **mail** badge
(`helpers/mail.py`, awarded on e-mail verification).

**Workaround until it is seeded:** create the first account with
`scripts/create_admin.py`, which does not award badges. **Suggested fix:** seed
`id=1 -> beta.png` and `id=2 -> mail.png` in a follow-up migration and leave the
rest to the operator. See [§8](#8-known-defects-and-deferred-work).

---

## 5. Removed and replaced features

Nothing was removed silently. Every entry here has a reason and, where
applicable, a replacement.

| Feature | Status | Reason | Replacement |
|---|---|---|---|
| **Guilds (communities)** | **Not present** | This is a core product feature, and it is missing from the source snapshot rather than removed by the modernization. The schema had the hooks (`boards` table, `submissions.board_id`) but there is no `Board` model in `ruqqus/classes/`, no guild route in `ruqqus/routes/`, no guild template, and zero occurrences of "guild" in the code. Posts are flat and unclassified. | **Needs building, not configuring.** Minimum to restore: re-add `boards(id, board_name, is_banned, created_utc)` and `submissions.board_id` to `migrations/versions/`, add a `Board` model, a guild page route, and a board picker on `/submit`. Until then, the schema keeps them out (see §4) so the migration matches the code. |
| Reddit integration (`routes/reddit_api.py`) | **Removed** | Hardcoded dependency on a third-party service plus API keys; the feature was Ruqqus-specific cross-posting. | Re-add behind a config flag if you need it. |
| Reddit account linking, settings page UI | **Replaced** | `settings_profile.html` offered "Link Reddit" / "Unlink Reddit" buttons posting to `/api/get_reddit_auth` and `/api/del_reddit_name`, both of which died with `routes/reddit_api.py` — the buttons would have 404'd. | The two forms and their `{% if v.reddit_username %}` conditional are gone; the section now reads "No third-party account integrations are available in this build." Restore by re-adding the route and swapping that block back. |
| Mailgun e-mail delivery | **Replaced** | Hardcoded provider and credentials. | `MAIL_BACKEND=smtp` with your own SMTP host, or `MAIL_BACKEND=console` to print mail to the log. |
| Memcached cache backend | **Removed** | Never wired up; dead weight. | Redis (default) or NullCache via `CACHE_ENABLED=false`. |
| User IP tracking (`ips` table, `User.update_ip`) | **Removed** | The model and table were already dropped; the method referenced a class that no longer existed and all four call sites were commented out. | If you need it, re-add the model and the `ips` table first. |
| `tags/` templates (`a.html`, `d.html`, `r.html`, `v.html`) | **Removed** | Zero references in code or templates. | None needed. |
| `control_panel_*.html` | **Removed** | Zero references anywhere in the tree. | None needed. |
| "Ruqqus Rules" drafts (`conduct.html`, `terms_conduct.html`) | **Removed** | Unreachable — only `help/*.html` is served — and superseded by `help/terms.html`. | `help/terms.html`, live at `/help/terms`. |
| Travis CI (`.travis.yml`) | **Removed** | Ran `test.py`, which contained only `pass`, on Python 3.7. | `.github/workflows/ci.yml`. |
| Release scripts (`_patch`, `build`) | **Removed** | Called `sass`, `bumpversion` and `git commit` directly; unreferenced and a footgun. | Nothing is lost: `scripts/css.sh` still builds both stylesheets and is the supported way to do it. |
| `CODEOWNERS` | **Removed** | Named the upstream author's personal address as the required reviewer for every file — wrong for this fork and a privacy leak. | Add your own if you publish this. |
| `docs/CNAME` | **Removed** | Hardcoded `www.ruqqus.org`. | Let GitHub Pages use its default `*.github.io` host, or add your own domain. |
| macOS Finder alias masquerading as `templates/userpage.html` | **Not removed** | Earlier audit notes described it as an alias; it is in fact a live 13,993-byte template rendered by `classes/user.py`. | — |

---

## 6. Files removed in the cleanup pass

All fifteen are backed up verbatim to `C:\tmp\ruqqus-phase6-backup\` (outside
the project), so any of them can be restored by copying it back. This tree is
not under version control, which is why the backup exists.

| Path | Size | Why it is dead |
|---|---|---|
| `test.py` | 5 B | Contained only `pass`. |
| `.travis.yml` | 55 B | Travis config for Python 3.7. |
| `_patch` | 133 B | Release script; see §5. |
| `build` | 131 B | Release script; see §5. |
| `CODEOWNERS` | 62 B | Upstream author's address. |
| `docs/CNAME` | 14 B | Hardcoded `www.ruqqus.org`. |
| `ruqqus/routes/activate.py` | 1,012 B | Never imported by `ruqqus/routes/__init__.py`, so its `/activate` route never registered. Superseded by the live handler in `ruqqus/mail/mail.py`, which has a 1-hour token expiry and awards the mail badge. Leaving it in place was a trap: adding it to `__init__.py` would have created a duplicate route. |
| `ruqqus/templates/tags/{a,d,r,v}.html` | 634 B | No `render_template` or template reference anywhere. |
| `ruqqus/templates/control_panel_logged_in.html` | 270 B | Zero references in the whole tree. |
| `ruqqus/templates/control_panel_logged_out.html` | 68 B | Zero references in the whole tree. |
| `ruqqus/templates/conduct.html` | 1,245 B | Unreachable draft; superseded by `help/terms.html`. |
| `ruqqus/templates/terms_conduct.html` | 3,035 B | Unreachable draft; superseded by `help/terms.html`. |

### Dead code removed

- `User.update_ip()` in `ruqqus/classes/user.py`, plus the four commented-out
  `#v.update_ip(...)` call sites in `ruqqus/helpers/wrappers.py`. The method
  referenced an `IP` model and `ips` table that no longer exist.
- The `ruff.toml` per-file suppression that masked that undefined name.

### Bugs fixed during the cleanup

- **Two broken links in the site header** (`ruqqus/templates/header.html`):
  `/help/conduct` → 404 (there is no `help/conduct.html`) now points at
  `/help/terms`, and bare `/about` → 404 (only `/about/<path>` was routed) is
  now forwarded to `/help/about`, matching its sibling route. The bare `/about`
  link appeared in five places across four templates, so fixing the route fixed
  all of them at once.
- **`errors/400.html` and `errors/410.html` existed but no handler rendered
  them**, so 400 and 410 fell back to Flask's unstyled default pages while every
  other error code used the site design. Both handlers are now registered in
  `ruqqus/routes/errors.py`.
- **Three error handlers in `ruqqus/routes/errors.py` were all named
  `error_405`** (a copy-paste slip). It worked — Flask registers at decoration
  time — but the names are now correct.
- **Two `SyntaxWarning: invalid escape sequence`** in `ruqqus/helpers/embed.py`
  and `ruqqus/helpers/markdown.py`. These become `SyntaxError` in a future
  Python. Both regex literals are now raw strings; the compiled patterns and
  match behaviour were verified byte-identical before the change.

---

## 7. Breaking changes for an existing deployment

If you are upgrading a live original-Ruqqus database rather than starting fresh:

1. **Python 3.12+ is required.** 3.7–3.11 will not work.
2. **Install `psycopg` 3 and uninstall `psycopg2`.** Connection strings are
   rewritten automatically, but the driver must be present.
3. **Set `SECRET_KEY`.** It is no longer optional and there is deliberately no
   placeholder value in `.env.example`. Leaving it blank fails loudly rather
   than silently running with a publicly known signing key.
4. **Set `SITE_URL`.** Anything that was previously derived from a hardcoded
   domain now comes from here, including e-mail links and the HTTP→HTTPS
   redirect.
5. **Run `alembic upgrade head`.** The `0001_initial` migration creates the
   schema from scratch; it is not written against a pre-existing database. If
   you have data, you will need to stamp and adapt.
6. **Drop `ips`, `boards`, `dms`, `userflags`** if they are still present and
   you no longer need their contents.
7. **Re-point mail.** `MAILGUN_KEY` no longer does anything.
8. **Rate limiting strategy changed** from `fixed-window-elastic-expiry` (no
   longer exists in `limits`) to `fixed-window`. See §8.

---

## 8. Known defects and deferred work

These are **known and unfixed**. Each is pinned by an `xfail(strict=True)` test
in `tests/`, which turns into a hard failure the moment it is fixed, so none of
them can quietly rot into "looks green".

### Missing core feature

- **Guilds (communities) do not exist in this source snapshot.** The database
  schema had the hooks but the application never had the code. This is the one
  entry on the feature list that cannot be restored by configuration or by
  undoing something this migration did — see
  [§5](#5-removed-and-replaced-features) for the shape of the work.

### Blocking

- **`badge_defs` is empty and account creation 500s.** See
  [§4](#4-database-changes). This is the one that stops a fresh install being
  usable by anyone but an admin.

### Deferred to a security-hardening pass

Not addressed in this migration, and not covered by the phase that produced this
document:

- Password hashing is still `pbkdf2:sha512`. Consider `scrypt` (built into
  Werkzeug 3, no new dependency, migrates old hashes transparently on next
  login) or `argon2id`.
- The signup formkey is bound to a timestamp but its 120-second expiry check is
  commented out, so a captured form stays valid indefinitely.
- CSRF formkeys are missing from `/api/sticky` and four comment-moderation
  routes, and from both `/api/flag/*` routes.
- Session cookies are `HttpOnly` but not `Secure` or `SameSite`.
- Open redirects: `POST /login` accepts `?redirect=`, and `edit_comment`
  redirects to `current_page`, both unvalidated.
- `/health` mints a session cookie, and does so on every health probe.
- Several unvalidated `int()` casts on request parameters return 500 instead of
  400 (`/reset` without `time`, non-numeric `referred_by`, non-base36 post ids).
- `api_sticky_post` dereferences a missing post outside its null check.
- No rate limits on signup, password reset, voting, flagging or search.
- `helpers/sanitize.py` allows any `ruqqus.com`/`ruqq.us` subdomain through a
  `endswith` check with no boundary.
- Dark mode is gated behind a referral count. This reads as deliberate product
  design and was left alone.

### Minor

- `settings_profile.html:101` still labels that section **"Reddit"** even though
  the body now says third-party integrations are unavailable. Cosmetic; the
  heading should probably read "Third-party accounts".
- `users.reddit_username` is still declared on the `User` model and still exists
  as a column. It is written by nothing now. Left in place so an upgraded
  database does not need a destructive migration; drop it once you are sure.
- `scripts/create_admin.py` raises a raw `EOFError` traceback when run without
  `--password` and without a terminal. Pass `--password`.
- `scripts/create_admin.py` also **resets the password** on a re-run, despite
  being described as idempotent.
- `Server: gunicorn` is disclosed in response headers.
- `docs/` is the upstream project's GitHub Pages site and still describes
  Ruqqus.com and links to the original repository.
- `header.html` links "Github" to `https://github.com/ruqqus/ruqqus`.
- `runtime.txt` and `Procfile` are Heroku conventions. Harmless, and
  `scripts/startup.sh` documents the Procfile as one of its entry points.

---

## 9. License and attribution

The project is licensed under the **Mozilla Public License Version 2.0**. See
[LICENSE](LICENSE).

Original Ruqqus source is © the Ruqqus contributors. The MPL-2.0 requires that
recipients of modified files be informed that the code changed and how; this
document is that notice for the modifications described above. The upstream
source carried no per-file license headers, and that convention has been
preserved rather than imposed.

MPL-2.0 is a *file-level* copyleft: if you distribute this, you must keep the
modified files under MPL-2.0, and you must share your changes to them. You may
combine it with code under other licenses under the terms in Section 3.
