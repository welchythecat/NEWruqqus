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
| Schema source | `schema.txt` dump | Alembic migrations `0001`–`0003` |
| Configuration | hardcoded + Heroku config vars | environment variables + `.env` |
| Deploy | Heroku only | Docker Compose, or bare metal; see [INSTALL.md](INSTALL.md) |
| Tests | `test.py` (contained only `pass`) | 411 pytest cases, 19 xfailed (strict) + GitHub Actions |
| Password hashing | `pbkdf2:sha512` | `scrypt`, with transparent upgrade of old hashes (see §8) |
| Guilds (communities) | schema tables only, no code | **built** — creation, membership, per-guild moderation, guild pins, "my guilds" feed; see §5 |

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
- **15 tables**: `alts`, `badge_defs`, `badges`, `board_members`, `boards`,
  `commentflags`, `commentvotes`, `comments`, `domains`, `flags`, `images`,
  `notifications`, `submissions`, `users`, `votes`. Plus `alembic_version`.
- **Tables that were removed because nothing reads or writes them:**
  `dms`, `ips`, `userflags`.
- **`boards` and `submissions.board_id` are the schema hooks for guilds
  (communities).** They were dropped in the first release because the source
  snapshot had no guild code at all; they are now **restored under their
  original names** by the `0002_guilds` migration, along with a new
  `board_members` table. Keeping the historical table name is what lets a
  database that still carries the original `boards` table keep its guilds
  across an upgrade. See [§5](#5-removed-and-replaced-features).
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
| **Guilds (communities)** | **Built** | This was a core product feature missing from the source snapshot rather than removed by the modernization. The schema had the hooks (`boards` table, `submissions.board_id`) but there was no `Guild` model in `ruqqus/classes/`, no guild route in `ruqqus/routes/`, no guild template, and zero occurrences of "guild" in the code. Posts were flat and unclassified. | **Built, not configured.** The `0002_guilds` migration restores `boards` and `submissions.board_id` under their historical names and adds `board_members`. See [§5.1](#51-guilds-what-is-historical-and-what-is-new) for exactly what was restored and what was newly added. |
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

### 5.1 Guilds: what is historical and what is new

Guilds are the communities that posts are filed under. The `0002_guilds`
migration builds them. Two things are worth separating, because one is a
restoration and the other is a design decision made for this build.

**Restored, under the original names** — so a database that still carries the
original `boards` table keeps its guilds across an upgrade:

| Object | Columns | Note |
|---|---|---|
| `boards` | `id`, `board_name`, `is_banned`, `created_utc` | Exactly the columns in `schema.txt`. `id` stays `Integer`, matching `submissions.board_id`. |
| `submissions.board_id` | — | Nullable. Posts made before guilds existed, and posts filed nowhere, both stay valid. |

**New in this build** — these have no counterpart in `schema.txt` and are an
addition, not a restoration. Nothing was removed to make room for them:

| Object | Purpose |
|---|---|
| `boards.created_by` | The founder. Nullable: the column allows a guild with no owner, though no route builds one. |
| `boards.description`, `boards.description_html` | The guild's blurb, Markdown in and sanitized HTML out — the same pipeline posts use. |
| `board_members` | The guild's roster: one row per member, with an `is_mod` flag. **This is the membership and per-guild moderator table.** The original schema had no such table. |
| `Guild` model in `ruqqus/classes/guild.py` | `__tablename__` is `"boards"` deliberately, not `"guilds"`. |
| `GuildMember` model in the same file | Maps `board_members`. |

**Design decisions**, all chosen for this build rather than recovered from the
original:

- **Anyone may create a guild.** No application, no approval step, no
  privilege required.
- **Membership is open.** Joining and leaving is a click; there is no
  membership request or approval queue. A guild page shows a member count.
- **Guilds have their own moderators**, separate from the site's. A guild
  moderator can change that guild's description and appoint or remove other
  moderators *of that guild*, and has no power anywhere else. Appointing
  someone who is not a member of the guild is refused — the roster would
  otherwise list people who cannot see what they moderate.
- **The founder cannot be removed as a moderator.** `Guild.is_moderator`
  returns true for the founder regardless of any membership row, so
  "removing" them would be a silent no-op; the route returns 403 instead.
  This is the one tie that cannot be broken by kicking everyone out.
- **Site admins outrank every guild moderator** and may moderate any guild.
- **URLs are `/guilds` for the directory and `/+<name>` for one guild.** The
  `+` prefix means the guild route cannot shadow any other route, which is
  checked by `tests/test_guilds.py::TestGuildRoutes`.
- **Guild names** are 3-32 characters of letters, numbers and underscore.
  They go straight into the URL, so they are validated strictly and a bad one
  is reported rather than silently normalized.

**Moderation and the personal feed**, built after the list above and equally an
addition:

| Behaviour | Where |
|---|---|
| Guild moderators may **remove and approve the posts filed in their own guild**, and the comments under them. | `Submission.can_moderate(user)`, `Comment.can_moderate(user)` |
| `/` has a **"my guilds" feed**. `/?feed=mine` narrows the front page to the guilds the signed-in user has joined. `/?feed=all`, or no parameter at all, is the historical global listing and is unchanged. | `frontlist(..., user_id=...)`, `home()` |

Both the endpoints and the moderation menus consult the *same* predicate, so a
button that is drawn is a button that works. The feed's personalisation
argument is a parameter of `frontlist` rather than something read from
`session`, because that function is `@cache.memoize`'d and the cache key is
built from its arguments — a user read inside the body would have had one
user's feed cached under a key every visitor shares.

**What did not move.** Guild moderators are an addition to the site-staff
rules, not a widening of them:

| Action | Site staff | Guild moderator |
|---|---|---|
| Remove / approve a post | `admin_level >= 3` | their own guild, only |
| Remove / approve a comment | `admin_level >= 1` | their own guild, only |

**Two pre-existing disagreements this resolved.** Before this change the menus
and the routes did not agree, in opposite directions:

| | The menu was drawn at | The route allowed | Consequence |
|---|---|---|---|
| Posts | `admin_level >= 1` | `admin_level >= 3` | Levels 1–2 saw a Remove button that always 403'd. |
| Comments | `admin_level >= 3` | `admin_level >= 1` | Level 1 could remove comments but was never shown the control. |

Both now use the route's own historical threshold. The visible consequence is
that site moderators of level 1 and 2 no longer see *post* Remove/Approve
controls — those never worked, clicking one always returned 403 — and they now
do see the *comment* controls they have always been allowed to use. **No
permission was granted or taken away; only the menus moved.**

**Guild pins.** A guild moderator can now **pin** a post in their own guild
(`/api/guild_pin`), and it heads that guild's page. This is deliberately a
*different* power from the site-wide sticky, and the separation is the whole
point:

| | `submissions.stickied` | `submissions.guild_pinned` |
|---|---|---|
| Scope | One slot, the whole site | One slot **per guild** |
| Who can set it | `admin_level >= 3` only | A guild moderator, in their own guild |
| Where it shows | Heads the front page | Heads the guild's page (`/+name`) |
| Can it displace the other? | Never touches `guild_pinned` | Never touches `stickied` |

Widening `/api/sticky` instead would have let any guild moderator knock the
site announcement off the front page, so that route is untouched. `Submission
.can_guild_pin` is the single source of truth and the Pin control is shown
under exactly the same condition — a button you can see is always a button
that works. The column is added by `0003_guild_pins`.

**Still not built** (so not claimed):

- A guild moderator still cannot **distinguish** a post in their own guild.
  `/api/distinguish` remains `admin_level >= 1` and is the author's own call
  ("speaking officially"), not a moderation tool. It is a deliberate default
  rather than an oversight. Say if you want it widened.
- No per-guild feed URL (an RSS/Atom equivalent of `/?feed=mine`), and no
  combined feed across guilds with different sorts per guild.

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
   schema from scratch, `0002_guilds` adds the guild tables on top, and
   `0003_guild_pins` adds the per-guild pin column; it is not written against
   a pre-existing database. If you have data, you will need to stamp and
   adapt.
6. **Drop `ips`, `dms`, `userflags`** if they are still present and you no
   longer need their contents. Keep `boards` — guilds use it now.
7. **Re-point mail.** `MAILGUN_KEY` no longer does anything.
8. **Rate limiting strategy changed** from `fixed-window-elastic-expiry` (no
   longer exists in `limits`) to `fixed-window`. See §8.

---

## 8. Known defects and deferred work

This section is in two parts: what has been **fixed** since the first release,
and what is still **known and unfixed**. Each remaining defect is pinned by an
`xfail(strict=True)` test in `tests/`, which turns into a hard failure the
moment it is fixed, so none of them can quietly rot into "looks green".

### Fixed since the first release

Recorded here because the v1.0.0 release notes and earlier revisions of this
document said otherwise.

- **Password hashing is now `scrypt`** — Werkzeug's default, `scrypt:32768:8:1`
  (N=2^15, r=8, p=1), backed by `hashlib.scrypt` in the standard library, so
  this adds no dependency. Existing `pbkdf2:sha512` hashes are deliberately
  **not** invalidated: `check_password_hash` dispatches on the algorithm name
  stored in the hash string, and `User._upgrade_hash_if_needed` re-hashes to
  `scrypt` on the next *successful* login. No migration script, no mass
  re-hash, no forced password resets, and the common path (already on `scrypt`)
  is untouched.
- **`referred_by` no longer 500s.** Both call sites in `routes/login.py` now
  coerce through `int()` inside a `try/except` and ignore junk input.
- **Non-numeric user ids in moderation routes no longer 500.** `/api/ban_user`
  and `/api/unban_user` compared a URL path string against the integer
  `users.id`; they now coerce, and a non-numeric id is a 400.
- **`204` responses were being returned as `200`.** `admin_level_required`
  unwrapped every tuple response to `response[0]`, which turned `("", 204)` into
  an empty 200 body. It now only unwraps the `(response, model)` pairs that
  actually need it.
- **Duplicate submissions were not detected.** `POST /submit` forced `https`
  onto the submitted URL *after* the duplicate check, so the raw input never
  matched the stored row and the same link could be posted repeatedly. The
  rewrite now happens first.
- **A repeated comment now lands where the first one did.** The duplicate
  redirect used the comment's own permalink while the create path used
  `#comment-N` on the post page; both now use the latter.
- **A post with no URL no longer crashes every listing it appears on.**
  `submission_listing.html` and `submission.html` called `p.url.endswith(...)`
  unguarded; `submissions.url` is nullable and defaults to NULL, so any such
  row raised `UndefinedError: 'None' has no attribute 'endswith'` on the front
  page and on the post page. `POST /submit` always writes `""` rather than
  NULL, which is why this stayed latent — but the column allows it, and an ORM
  insert or a hand-edited row was enough to take the front page down. All four
  call sites now test `p.url` first. Found by the guild work's HTTP smoke test,
  not by the suite, because the test factory also writes `""`.
- **Guilds are now built.** The one feature the source snapshot never had. See
  [§5.1](#51-guilds-what-is-historical-and-what-is-new) for what is a
  restoration of the historical schema and what is an addition made here.
- **Guild moderators can now moderate their own guild, and the moderation
  menus match the moderation routes.** The two disagreed before, in opposite
  directions: the *post* menu was drawn at `admin_level >= 1` while
  `/api/ban_post` required 3, so a level 1 moderator saw a Remove button that
  403'd; the *comment* menu was drawn at `admin_level >= 3` while
  `/api/ban_comment` allowed 1, so a level 1 moderator could remove comments
  but was never shown the control. Both are now gated on
  `Submission.can_moderate` / `Comment.can_moderate`, which is the same
  predicate the routes check. Site-staff thresholds are unchanged. Full table
  in [§5.1](#51-guilds-what-is-historical-and-what-is-new).
- **The front page has a "my guilds" feed.** `/?feed=mine` shows only posts
  filed under guilds the signed-in user has joined. The 30-second response
  cache was the hazard here: `frontlist` is `@cache.memoize`'d and the cache
  key comes from its arguments, so the user id is an argument, and the
  unfiltered front page is a separate cache entry.
- **`/api/ban_comment` and `/api/unban_comment` now require a CSRF formkey.**
  They were among the routes listed as unguarded below. The shared `post()`
  helper in `default.html` has always sent the formkey, so the UI is
  unaffected.
- **Guild moderators can now pin a post in their own guild.** A guild pin is a
  new column, `submissions.guild_pinned`, with one slot per guild — deliberately
  separate from `submissions.stickied`, which is a single site-wide slot that
  heads the front page and is still `admin_level >= 3`. Widening `/api/sticky`
  would have let a guild moderator knock the site announcement off the front
  page. The two never touch each other. See
  [§5.1](#51-guilds-what-is-historical-and-what-is-new).

### Missing core feature

- **None outstanding.** Guilds (communities) were the one feature the source
  snapshot never had — the database had the hooks but the application had no
  code for it. They are now built, including per-guild moderation, guild pins,
  and the "my guilds" feed; see
  [§5.1](#51-guilds-what-is-historical-and-what-is-new) for exactly what that
  includes and the smaller thing still open.

### Blocking

- **`badge_defs` is empty and account creation 500s.** See
  [§4](#4-database-changes). This is the one that stops a fresh install being
  usable by anyone but an admin.

### Deferred to a security-hardening pass

Not addressed in this migration, and not covered by the phase that produced this
document:

- The signup formkey is bound to a timestamp but its 120-second expiry check is
  commented out, so a captured form stays valid indefinitely.
- CSRF formkeys are missing from `/api/sticky` and the two
  comment-distinguishing routes, and from both `/api/flag/*` routes.
  (`/api/ban_comment` and `/api/unban_comment` had the same gap and now carry
  the check.)
- Session cookies are `HttpOnly` but not `Secure` or `SameSite`.
- Open redirects: `POST /login` accepts `?redirect=`, and `edit_comment`
  redirects to `current_page`, both unvalidated.
- `/health` mints a session cookie, and does so on every health probe.
- Unvalidated `int()` casts on request parameters return 500 instead of 400
  (`/reset` without `time`, non-base36 post ids).
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
