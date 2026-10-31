# AUDIT.md — Ruqqus codebase audit (Phase 1)

**Scope:** read-only review of the entire repository. No code was changed.
**Date:** 2026-10-29
**Code vintage:** ~2019–2021, version `0.5.0`, targeted at Python 3.7 / Heroku.

---

## 1. Project structure

```
NEWruqqus-master/
├── Procfile                  # Heroku: `web: source scripts/startup.sh`
├── runtime.txt               # python-3.7.5
├── requirements.txt          # 32 pinned deps (2019-era)
├── schema.txt                # pg_dump of the production PostgreSQL schema (30 KB)
├── build / _patch            # shell one-liners: sass + bumpversion + git commit
├── test.py                   # literally `pass` — no tests exist
├── .travis.yml               # runs `python3.7 test.py`
├── .bumpversion.cfg          # version 0.5.0
├── LICENSE                   # MPL-2.0 (no per-file headers anywhere in the source)
├── README.md                 # marketing copy + dead badges/links
├── docs/                     # Jekyll GitHub Pages site (marketing/contribute docs)
├── scripts/
│   ├── startup.sh            # db_prep.py then gunicorn (gevent, 2 workers)
│   └── css.sh                # sass compile main.scss / main_dark.scss
└── ruqqus/
    ├── __main__.py           # app factory-by-import: Flask app, cache, limiter, db session
    ├── classes/              # SQLAlchemy 1.x models (user, submission, comment, votes,
    │                         #   flags, badges, alts, domains, images)
    ├── helpers/              # base36, db_prep (SQL functions), embed, filters, jinja2,
    │                         #   lazy, markdown, sanitize, security, wrappers
    ├── mail/                 # Mailgun HTTP API client + email-verification routes
    ├── routes/               # 15 modules, ~40 routes (login, posts, comments, votes,
    │                         #   admin, admin_api, flagging, front, search, settings,
    │                         #   static, user_pages, activate, errors, reddit_api)
    ├── templates/            # ~60 Jinja2 templates (Bootstrap 4 + custom SCSS)
    └── assets/               # fontawesome, images, js, style (compiled CSS + SCSS)
```

Total Python: **~3,650 lines**. Total templates: **~5,500 lines**.

---

## 2. How the app boots

`Procfile` → `source scripts/startup.sh`:

```sh
python3.7 ruqqus/helpers/db_prep.py          # installs/refreshes Postgres SQL functions
gunicorn ruqqus.__main__:app -w 2 -k gevent --worker-connections 9
```

`ruqqus/__main__.py` is not a factory — importing it **is** the construction of the app:

1. Creates `Flask(__name__, template_folder='./templates', static_folder='./static')`.
2. Wraps WSGI in `werkzeug.contrib.fixers.ProxyFix` (**removed in Werkzeug 1.0**).
3. Reads `DATABASE_URL`, `MASTER_KEY`, `domain`, `REDIS_URL`, `HEROKU_REDIS_*_URL` from env.
4. Picks cache backend by string-matching `"localhost"` into `SERVER_NAME`.
5. Builds a raw `sqlalchemy.create_engine` + `sessionmaker` — **not** Flask-SQLAlchemy.
6. `from ruqqus.classes import *` / `from ruqqus.routes import *` — import-time side effects register every route.
7. Registers `before_request` (HTTPS redirect + `db.rollback()` + session bootstrap) and `after_request` (CORS-ish headers) **only in the `else` branch of `if __name__ == "__main__"`** — meaning they are absent under `flask run` / `app.run()`, present under gunicorn.

`runtime.txt` pins `python-3.7.5`. `docs/`, `build`, `_patch`, `.travis.yml` are all dead or Heroku/local-dev-only artifacts.

---

## 3. Environment variables & configuration

| Variable | Read at | Purpose | Notes |
|---|---|---|---|
| `DATABASE_URL` | `__main__.py`, `helpers/db_prep.py` | PostgreSQL DSN | Required. `db_prep.py` crashes at import if unset. |
| `MASTER_KEY` | `__main__.py`, `helpers/security.py`, `routes/login.py` | Flask `SECRET_KEY` **and** HMAC key for form tokens / reset tokens | Shared secret for two different purposes. Crashes if unset. |
| `domain` | `__main__.py`, `mail/mail.py`, `routes/settings.py` | `SERVER_NAME`, link generation | **Lowercase, non-standard name.** `None` → `app.config["SERVER_NAME"]` becomes `None` and `"localhost" in None` raises `TypeError`. |
| `REDIS_URL` | `__main__.py` | Flask-Caching Redis URL | Only used when `domain` doesn't contain "localhost". |
| `HEROKU_REDIS_PURPLE_URL` | `__main__.py` | Flask-Limiter storage | Heroku-specific name. Falls back to `HEROKU_REDIS_ORANGE_URL` — but the fallback is computed into `limit_url` and then **never used**; the Limiter is always built with `HEROKU_REDIS_PURPLE_URL` (so limiter storage is `None` in dev). |
| `MAILGUN_KEY` | `mail/mail.py` | Mailgun HTTP API auth | Hard dependency for all mail. |
| `reddit_id`, `reddit_secret` | `routes/reddit_api.py` | PRAW OAuth client | Hardcoded redirect to `https://www.ruqqus.com/...`. |

**No `.env.example` exists. No secrets in the repo** (verified), but there is also **no documentation** of what to set. `security.py` will throw `TypeError: encoding without a string argument` if `MASTER_KEY` is unset rather than a clean config error.

---

## 4. External services & hardcoded infrastructure

| Dependency | Where | Problem |
|---|---|---|
| **Mailgun** | `mail/mail.py` | Hardcoded `https://api.mailgun.net/v3/mail.ruqqus.com/messages`, from-address `noreply@mail.ruqqus.com`. |
| **Reddit / PRAW** | `routes/reddit_api.py` | Module-level `praw.Reddit(...)` with `redirect_uri="https://www.ruqqus.com/api/redditredirect"`. Dead: Reddit username verification badge. |
| **ruqqus.com / ruqq.us** | ~15 templates + `helpers/sanitize.py`, `routes/comments.py`, `mail/mail.py`, `assets/js/signup.js`, `docs/` | Referral links, share links, shortlinks, email footers, `nofollow` domain allowlist, Atom feed URLs, username-availability API in JS. |
| **Heroku** | `__main__.py`, `Procfile`, `runtime.txt`, `scripts/startup.sh` | Redis addon names, `python3.7`, gevent worker model. |
| **CDNs (no versioning/SRI)** | `templates/*.html` | Bootstrap 4.0.0 & 4.3.1, jQuery 3.1.1 & 3.2.1-slim (two different versions!), Popper 1.12.9 & 1.14.7, clipboard.js, AOS, code-prettify, Google Fonts. **Visual style depends on these; must be preserved.** |
| **`/app/` path assumption** | `helpers/jinja2.py` | `open("/app/"+file_name)` — Heroku slug layout. Will crash anywhere else. |

---

## 5. Database schema

Source of truth is `schema.txt` (pg_dump from **PostgreSQL 11.5**). Tables:

| Table | Purpose | Notes |
|---|---|---|
| `users` | Accounts | Has `ban_state` in the dump but the model uses `is_banned`/`ban_reason` — **schema and models have drifted**. |
| `submissions` | Posts (link or text) | `board_id` in dump (unused "guild" remnant). `over_18` in dump but not in model. |
| `comments` | Threaded comments | `parent_fullname` is a *string* like `t2_x1y` in the model but a `varchar` FK-less column. |
| `votes`, `commentvotes` | 1 / 0 / -1 votes | |
| `flags`, `commentflags`, `userflags` | Reports | `userflags` has no model — dead table. |
| `notifications` | Comment replies | No model for "read" timestamps etc. |
| `badges`, `badge_defs` | Profile badges | Seeded with beta/mail/reddit/git etc. |
| `alts` | Admin multi-account tracking | Written by `check_for_alts()`. |
| `domains` | Per-domain submit/comment rules | `reason` is an **int index** into a Python list. |
| `images` | Splash art by US state | `random_image()`. |
| `boards` | **"Guilds" table, never used in code** | Orphan. |
| `dms` | **DMs table, never used in code** | Orphan. |
| `ips` | **IP log table; `User.update_ip()` references `self.ips` / `IP(...)` but there is no `IP` model and `update_ip` is never called** | Orphan + broken. |

**Server-side computed columns** — a large set of PostgreSQL functions (`ups`, `downs`, `age`, `score`, `rank_hot`, `rank_fiery`, `rank_activity`, `comment_count`, `flag_count`, `energy`, `referral_count`, `splash`, `created_utc`/`is_banned`/`is_deleted` on notifications) declared in SQLAlchemy as `Column(..., server_default=FetchedValue())`. These are **not** ordinary columns: they are functions taking a row. This is the single most important architectural constraint — any migration must reproduce them, and they are what makes ranking queries fast.

**Critical inconsistency:** `schema.txt` declares these as `IMMUTABLE STRICT` and keys bans off `users.ban_state > -1`, while `helpers/db_prep.py` (which is what actually runs at deploy) declares them `IMMUTABLE RETURNS NULL ON NULL INPUT` and keys bans off `users.is_banned=0`. The two definitions of the same functions **disagree**. `db_prep.py` is authoritative at runtime.

Also: the functions are declared `IMMUTABLE` while `age()` depends on `CURRENT_TIMESTAMP`. This is a correctness bug (Postgres may cache results past their real lifetime) but is load-bearing for the ranking indexes.

---

## 6. Features list (as implemented)

**Accounts & auth**
- Signup (username `\w{5,25}`, password ≥8 chars, optional email, referral code)
- Login (username **or** email, case-insensitive), logout
- Email verification via signed link (`/activate`), mail badge
- Password reset via signed time-limited link (`/forgot`, `/reset`, 10-minute window)
- Session-based auth (Flask signed cookie), `session["history"]` for alt-account detection
- Settings: profile (bio, over-18), security (change password, change email)

**Content**
- Submit link posts and/or text posts (mistletoe markdown + `@username` mentions)
- Edit / delete own posts and comments
- YouTube embed detection
- Per-domain submit/comment bans
- Banned URL reasons (shorteners, porn, copyright)

**Voting & ranking**
- Post and comment votes (1 / 0 / -1), auto-upvote on create
- Score fuzzing (±1%)
- Sorts: hot, new, top, disputed ("fiery"), activity, random (comments only)
- Front page with sticky post support, pagination (25/page)

**Moderation**
- `admin_level` 0–3 gate
- Ban/unban users (records `ban_reason`, banner id)
- Ban/unban posts & comments, distinguish, sticky
- Flag posts/comments → `/flagged/posts`, `/flagged/comments` queues with approve state
- Alt-account tracking graph

**Other**
- Search (case-insensitive substring on title)
- Notifications (comment replies + username mentions)
- Atom feeds `/feeds/<hot|fiery|top>`
- User pages with paginated posts and comments
- Dark mode (gated behind `referral_count > 0` — see bugs)
- Username-availability JSON API
- Badges, bio, karma ("energy"), referral counts
- Help pages rendered from markdown in templates
- Error pages 400/401/403/404/405/410/422/429/500

---

## 7. Dead / broken code

| Item | File | Finding |
|---|---|---|
| `test.py` | root | Contains `pass`. No test suite at all. |
| `ruqqus/templates/userpage.html alias` | templates | **Binary macOS Finder alias** accidentally committed. Points at a developer's local `~/Documents/GitHub/ruqqus/templates/userpage.html`. Must be deleted. |
| `boards`, `dms`, `userflags` tables | schema.txt | No model, no code path. |
| `IP` / `User.update_ip()` | `classes/user.py:104-113` | References `self.ips` relationship and `IP(...)` class that **do not exist**. All call sites are commented out. Would `NameError` if enabled. |
| `limit_url` | `__main__.py:41` | Computed, never used. |
| `Comment.children` | `classes/comment.py` | Filters `parent_comment=`, a column that doesn't exist. Dead. |
| `Comment.rank_hot` | `classes/comment.py:67` | `self.down` — **typo for `self.downs`** → `AttributeError` if ever called. Shadows the SQL function. |
| `helpers/security.py:hash_password` | | Duplicates `User.hash_password`, differing only in being unused-from-there. |
| `Comment.__init__` | `classes/comment.py:36-39` | Hand-rolls `__dict__` assignment to skip virtual columns, but the loop's allowlist doesn't match the virtual column set (`rank_hot`, `rank_fiery`, `score`, `flag_count`, `is_banned`, `is_deleted` are not all covered). Fragile. |
| `_allowed_tags_with_links` | `helpers/sanitize.py:24` | Assigned but never used. |
| `BAN_REASONS` | `routes/user_pages.py:11` | Duplicate of the one in `posts.py`, unused. |
| `.travis.yml`, `build`, `_patch` | root | Travis is dead; build scripts are Heroku-dev scratch. |
| `docs/` | | Points at live `ruqqus.com`, references the upstream GitHub org. |
| `praw` stack | `routes/reddit_api.py` | Depends on a dead third-party integration and a hardcoded redirect URI. |
| **Duplicate `/activate` route** | `routes/activate.py` **and** `mail/mail.py` | Both register `GET /activate`. **Silently shadowed** — whichever is imported last wins. `routes/activate.py` is orphaned (not in `routes/__init__.py`). |
| `help_path` | `routes/static.py:66` | `safe_join` is used but **never imported** → `NameError` at request time. |
| `routes/comments.py:15` | | `from werkzeug.contrib.atom import AtomFeed` — **`werkzeug.contrib` was removed in Werkzeug 1.0**. Import-time crash on any modern install. |
| `__main__.py:13` | | `from werkzeug.contrib.fixers import ProxyFix` — same, removed. |
| `flaskext.markdown` | `__main__.py` | Flask-Markdown is abandoned (last release 2014), depends on `flaskext` namespace pkg. |
| `Python 2 regex warnings` | `routes/login.py:15`, `posts.py`, `user_pages.py` | `re.compile("^\w{5,25}$")` etc. — invalid escape sequences, `SyntaxWarning` on 3.12+. |

### Login/signup logic bugs (functional, not just legacy)

| Bug | Location | Effect |
|---|---|---|
| **Commented-out `if` leaves unreachable code** | `routes/login.py:208-211` | `return new_signup(...)` at line 211 is indented *inside* `new_signup`'s body scope per AST? No — it parses as **dead code after the function def**, never executed. Net effect: **the 120-second token expiry check is gone.** |
| `form_timestamp` default `0` | `routes/login.py:177` | `request.form.get("now", 0)` returns `0` (int) if missing; then `form_timestamp+submitted_token` does `int + str` → `TypeError` → 500. |
| `formkey` uses `hmac` + `md5` + `utf-16` | `helpers/security.py` | MD5 as digest, `utf-16` (with BOM) key encoding. Functionally works but is a red flag and non-standard. |
| Missing User-Agent → 403 | `routes/login.py:143` | Legitimate clients (some bots, curl without UA) blocked; also a trivially bypassed signal. |
| `session["signup_token"]` unguarded | `routes/login.py:180` | Direct POST to `/signup` without visiting GET first → `KeyError` → 500. |

---

## 8. Security issues

Ranked by severity. **This is a 2019 app with none of the modern baseline.**

### CRITICAL

1. **No CSRF protection on 8+ state-changing endpoints.**
   `validate_formkey` is a custom HMAC and is applied to some routes but **not** to:
   - `POST /api/flag/post/<pid>` and `POST /api/flag/comment/<cid>` (`routes/flagging.py`)
   - `POST /api/sticky/<post_id>` (`routes/admin_api.py:106`)
   - `POST /api/ban_comment/<c_id>`, `/api/unban_comment`, `/api/distinguish_comment`, `/api/undistinguish_comment` (`admin_api.py`)
   - `POST /settings/dark_mode/<x>`
   - `POST /login`, `POST /signup`, `POST /forgot`, `POST /reset`
   An attacker's page can drive all of these if the victim is logged in. **Ban/unban of comments and stickying posts are admin actions with zero CSRF protection.**

2. **Open redirect on login/signup.**
   `routes/login.py:32, 91, 289` — `redir = request.form.get("redirect", "/")` / `request.args.get("redirect","/")` is passed straight to `redirect()`. `https://evil.com` works. Classic phishing vector post-login.

3. **Unescaped user content — stored XSS.**
   - `{{ p.title | safe }}` in `submission.html`, `submission_listing.html`, `single_comment.html` — the title is passed through `sanitize()`, but `sanitize(title, linkgen=False)` still allows the full tag set including `<a href>`; combined with `|safe` and the `nofollow` filter rewriting hrefs this is *narrowly* OK, but see #4.
   - `{{ u.bio_html | safe }}` in `userpage.html` — bio is sanitized with `sanitize(bio)` **without `linkgen=True`**, so raw `<a>` survives and the `nofollow`/https-upgrade filter is **not applied**.
   - `{{ c.post.title | safe }}` — same as above.
   - Critically: **`bleach` is pinned at 3.1.0** and the code relies on `bleach.linkifier.LinkifyFilter` with `skip_tags`, a callback that mutates `attrs[(None,"href")]`. In bleach ≥5/6 (and the new `nh3`/`bleach` API surface) this changed. Any upgrade must re-verify this filter, or titles/bios become XSS.
   - `Message.html` is rendered from `render_template(...)` output in the mail path — safe, but the `|safe` pattern is used everywhere as the default, which is the wrong default.

4. **`nofollow` filter forces `https://` on external links but keeps the *netloc* unvalidated.**
   `helpers/sanitize.py:38-50` — `urlparse(attrs[(None,"href")])` will `KeyError` on an `<a>` with no href; and `domain.endswith(("ruqqus.com","ruqq.us"))` uses `endswith` on a tuple of **strings with dots** — `evil-ruqqus.com` **does** match `.com` suffix logic? No: `endswith("ruqqus.com")` is literal, so `evilruqqus.com` fails but `notruqqus.com` does not end with `ruqqus.com` — this is correct. However `endswith` is being used where a proper domain-boundary check is intended; `sub.ruqqus.com.evil.com` is correctly excluded, but `ruqqus.com.evil.com` is also excluded. Low risk, still worth tightening.

5. **`source_code` Jinja filter is a local file disclosure primitive.**
   `helpers/jinja2.py:19-21` — `open("/app/"+file_name).read()`. Used by `help/about.html` with hardcoded paths. If the route ever takes user input this reads arbitrary files. Currently the paths are template literals, so it's "only" a DoS/fragility issue, but the filter itself is unsafe-by-construction and must be replaced.

6. **Password hashing is `pbkdf2:sha512` with `salt_length=8`.**
   8-byte salt, PBKDF2 with default iteration count of the pinned Werkzeug 0.15.5. Below current guidance (OWASP 2023+: argon2id, or PBKDF2 ≥600k iterations). **Needs migration path**, since existing hashes must keep verifying.

7. **No security headers.** No `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Strict-Transport-Security`. Clickjacking of the vote/comment/ban forms is trivial.

8. **Session cookie has no `Secure`/`HttpOnly`/`SameSite` configuration.** Flask defaults are `HttpOnly=True`, `SameSite=None` (in old Flask) / `Lax` (new). No `SESSION_COOKIE_SECURE`, so the session cookie can leak over plain HTTP (the app *does* try to redirect to HTTPS in `before_request`, but only under gunicorn).

### HIGH

9. **`before_request`/`after_request` are registered only when not `__main__`.** Under `flask run` there is **no** `db.rollback()` per request and **no** HTTPS redirect. Easy to deploy insecurely by accident.

10. **`db.rollback()` in `before_request`, not `teardown_request`.** If a request raises, the session may stay dirty across requests. With a **global `Session` shared by all gevent-greenlet workers** (`sessionmaker()()` at module import, 2 gevent workers × 9 connections), this is a **data-corruption / cross-request bleed risk**. Any modernization must replace this with scoped sessions (Flask-SQLAlchemy or `scoped_session`).

11. **Rate limiting is nearly absent.** Only `POST /login` (6/min), `POST /submit` (6/min), `POST /api/comment` (10/min), and static assets are exempt. **No limit on `/signup`, `/forgot`, `/reset`, voting, flagging.** And the limiter's `storage_uri` is `None` in dev (falls back to in-memory), which is per-process and therefore useless under gunicorn's 2 workers.

12. **Password reset token is deterministic and not single-use.**
    `generate_hash(f"{user.id}+{now}+forgot")` — same inputs give the same token. The token is accepted for 600 s. It is not invalidated after use; the "reset" token is a second deterministic hash of the same tuple. Replaying within the window works. Also **no rate limit** on `/forgot` → email enumeration + spam.

13. **Email verification token is deterministic and not single-use**, `generate_hash(f"{email}+{user.id}+{now}")`, 3600 s window. Combined with #12 this means token = `HMAC(MASTER_KEY, known_string)` and **MASTER_KEY is doing double duty as both the Flask `SECRET_KEY` and the HMAC key** — a leak of one is a leak of both.

14. **`reset` and `activate` tokens are compared with `validate_hash` but no expiry is checked on the *reset* POST path's `user_id` binding** — actually `now-timestamp>600` is checked, OK. But `user_id` comes from the form and is only protected by the token; the token binds `user_id`, so this is fine. (Listing for completeness.)

15. **`api_is_available` is unauthenticated and unthrottled** (`routes/user_pages.py:14`) — username enumeration.

16. **`db_prep.py` runs `prep_database()` at import time** and opens a raw psycopg2 connection. Under `scripts/startup.sh` this is a separate process, fine; but any accidental `import ruqqus.helpers.db_prep` opens a DB connection and mutates schema.

### MEDIUM

17. **`hmac` with `digestmod='md5'`** — MD5 is not a security break in HMAC, but it's a lint/audit failure and there's no reason for it.

18. **`utf-16` encoding of HMAC message and key** — introduces a BOM and makes tokens non-portable across languages. Non-standard.

19. **`front.py:76` builds raw SQL with an f-string of a Python list literal** (`text(f"select ... join (values {tups}) ...")`). The values are server-side integers from a previous query, so **not injectable**, but the pattern is dangerous and must be replaced with a bound parameter list.

20. **`search` has no query length cap and no rate limit** — `func.lower(Submission.title).contains(query)` is an unindexed ILIKE `%q%` on every search. DoS vector.

21. **`Comment.parent_fullname` is not validated** in `api_comment` before `int(parent_fullname.split("_")[1], 36)` — a crafted value raises `ValueError`/`IndexError` → 500.

22. **`base36decode` raises on non-base36 input** (`int(str(number), 36)`) — every route taking `<base36id>` 500s on bad input instead of 404.

23. **`votes.py` `change_to()` calls `abort(400)` but `abort` is not imported** in `classes/votes.py` — `NameError` on the invalid-argument path (which is unreachable because the routes validate first, but it is a latent crash).

24. **`comments.py:102` `if not comment_id:`** — checks the decoded *int* variable instead of `if not comment` → a missing comment raises `AttributeError` on the next line instead of a 404.

25. **`admin_api.py` `ban_user`/`unban_user`/`ban_post`/`unban_post` return `(redirect(...), obj)`** — a tuple where the second element is a SQLAlchemy object. `admin_level_required`'s wrapper strips it (`return response[0]`), so it works by accident. Fragile.

26. **`admin_api.py` `api_sticky_post`**: `if post:` guards the unsticky branch but the stickied branch below dereferences `post` unconditionally — `NameError`/`AttributeError` if the post is missing.

27. **`settings.py:38`** — `if request.form.get("over18") != v.over_18` compares a string-or-`None` against a bool. Always true-ish → `over_18` toggles unpredictably.

28. **`settings_dark_mode`** requires `referral_count > 0` to enable dark mode — an obvious accidental feature gate. Users with no referrals are **forced into light mode and get a 403**.

29. **`mail/mail.py` `send_mail` returns the `requests.Response` and ignores it.** Mail failures are silent. Also `requests.post` with `auth=("api", MAILGUN_KEY)` — no timeout, so a hung Mailgun hangs the request.

30. **No input length caps** beyond DB column sizes. `body` is `String(2000)` but the form accepts anything; a 10 MB body is rendered through mistletoe + bleach before the DB rejects it.

31. **`over_18` content gate is not enforced** anywhere in the post listing/feed paths.

32. **`robots.txt`, `favicon.ico`, `/assets/<path>` are served from `./assets` relative to CWD** — depends on the process working directory. Fragile.

### LOW / hygiene

33. Every SQL function is marked `IMMUTABLE` while `age()` uses `CURRENT_TIMESTAMP`. Postgres may memoize across a transaction.
34. `Comment.parent_fullname` is a `BigInteger` column in the model but a `varchar(255)` holding `t2_...` strings in the dump. Model/schema mismatch.
35. `Submission.url` is `String(500)` in the model, `varchar(255)` in the dump.
36. `math.floor(real*(1-k))` for score fuzzing can produce `a > b` on negative scores → `random.randint` raises.
37. `random.seed(f"{self.id}+{self.username}")` in `User.color` seeds the **global** RNG — side effects on every other `random` call in the process.
38. No `.env.example`, no config docs, no health endpoint, no structured logging.
39. `from flask import *`, `from sqlalchemy import *`, `from ruqqus.classes import *` — namespace pollution, and `db` is a plain `Session` shadowing what people expect from Flask-SQLAlchemy.
40. MPL-2.0 `LICENSE` is present but **no source file carries an MPL header**, and there is no "modified files" marker convention in place.

---

## 9. Dependency audit

`requirements.txt` (32 entries, all 2019). Notable problems:

| Package | Pinned | Status |
|---|---|---|
| `Flask` | 1.1.1 | 2 major versions behind. `flask.json` API changed; `flaskext.markdown` incompatible. |
| `Werkzeug` | 0.15.5 | **`werkzeug.contrib` removed in 1.0** → app cannot import. Known CVEs. |
| `SQLAlchemy` | 1.3.5 | 2.x is current; 1.4→2.0 migration required (`Query` legacy API, `declarative_base` moved). |
| `Jinja2` | 2.10.1 | 3.x; `MarkupSafe` 2.x removed `soft_unicode`, Jinja2 2.10 incompatible. |
| `MarkupSafe` | 1.1.1 | CVE-2022-?; must move to 2.x. |
| `itsdangerous` | 1.1.0 | 2.x. |
| `psycopg2-binary` | 2.8.3 | Prefer `psycopg[binary]` 3.x (or `psycopg2` 2.9.x). |
| `redis` | 3.3.6 | 4.x/5.x. |
| `gevent` | 1.4.0 | Old; **only needed because of gevent worker**. `gunicorn` + `gthread`/`gunicorn` default sync is simpler. |
| `gunicorn` | 19.9.0 | 22.x+ (several CVEs in <20). |
| `bleach` | 3.1.0 | **Now deprecated** (the maintainers recommend `nh3`). API changed in 5.x/6.x. |
| `Markdown` | 3.1.1 | OK-ish, but unused? (`flaskext.markdown` uses it for the `markdown` filter in help templates.) |
| `mistletoe` | 0.7.2 | 1.x; `SpanToken`/`HTMLRenderer` constructor API changed (`__init__(self, *args)` → different). |
| `beautifulsoup4` | 4.8.1 | Fine; needs `html.parser` explicit (it is, in one place; the other uses default which warns). |
| `praw` | 6.3.1 | Dead integration; **remove**. |
| `prawcore`, `update-checker`, `websocket-client`, `uhashring`, `python-binary-memcached`, `typing`, `six`, `certifi`, `chardet`, `idna`, `urllib3`, `webencodings`, `PyYAML`, `Click` | various | Mostly **transitive deps that shouldn't be pinned directly**; `python-binary-memcached`, `uhashring`, `typing`, `six`, `websocket-client`, `update-checker`, `prawcore` are **unused** → remove. |
| `Flask-Limiter` | 1.1.0 | 3.x; API changed substantially. |
| `Flask-Caching` | 1.7.2 | 2.x. |

**`Flask-Markdown` (`flaskext.markdown`) is abandoned and must be removed** — it is used only for the `markdown` Jinja filter in `templates/help/{faq,privacy,rules,terms}.html`. Replace with a tiny local filter over `markdown` or `mistletoe`.

I could not run `pip-audit` in Phase 1 (no code changes / no install). Phase 2 will run it against the new pinned set and report.

---

## 10. Prioritized plan for remaining phases

> Estimate is lines-of-code churn + files touched, not wall-clock.

### Phase 2 — Foundation (blocking)
| # | Task | Files |
|---|---|---|
| 2.1 | Create `ruqqus/config.py`: env-driven config, `.env` support (`python-dotenv`), typed getters, clean errors for missing secrets | **new** `ruqqus/config.py`, `ruqqus/__init__.py` |
| 2.2 | Replace `werkzeug.contrib.fixers.ProxyFix` → `werkzeug.middleware.proxy_fix.ProxyFix`; fix `if __name__` gate so hooks always register | `ruqqus/__main__.py` |
| 2.3 | Remove `flaskext.markdown`; add local `markdown` Jinja filter | `ruqqus/__main__.py`, **new** `ruqqus/helpers/markdown_filter.py`, 4 help templates (no visual change) |
| 2.4 | Remove `werkzeug.contrib.atom.AtomFeed` → vendored or `werkzeug.contrib` replacement (use `feedgen` or hand-rolled Atom) | `ruqqus/routes/comments.py` |
| 2.5 | SQLAlchemy 1.3 → 2.x: `declarative_base` from `sqlalchemy.orm`, `Session` lifecycle, `Query` → `select()`, `text()` bindings, `FetchedValue` review | `ruqqus/classes/*.py`, `ruqqus/__main__.py`, all `routes/*.py` |
| 2.6 | Introduce proper session scope (`scoped_session` or Flask-SQLAlchemy) — fixes the shared-Session bleed | `ruqqus/__main__.py` + every `db.*` call site (mechanical) |
| 2.7 | Fix imports that break on modern libs (`safe_join`, `re` escapes, `BeautifulSoup` parser arg) | `routes/static.py`, `routes/login.py`, `routes/posts.py`, `routes/user_pages.py`, `helpers/filters.py` |
| 2.8 | Replace hardcoded env names (`domain`→`SERVER_NAME`/`SITE_URL`, `HEROKU_REDIS_*`→`REDIS_URL`, `MAILGUN_KEY`→`MAIL_*`) and Mailgun/Reddit with config-driven + console/SMTP defaults | `__main__.py`, `mail/mail.py`, `routes/reddit_api.py` (delete), `routes/settings.py`, `helpers/security.py` |
| 2.9 | Migrations: Alembic autogenerate from models **plus** an init migration that also installs the SQL functions from `db_prep.py` (single source of truth) | **new** `migrations/`, `alembic.ini`, `ruqqus/helpers/db_prep.py` (converted to a migration) |
| 2.10 | `scripts/migrate_old_db.py` — load a legacy `schema.txt`/pg_dump into the new schema | **new** |
| 2.11 | `GET /health` (db + redis ping) | **new** `ruqqus/routes/health.py` |
| 2.12 | `requirements.txt` regenerated and pinned; `pip-audit` run | `requirements.txt` |
| 2.13 | `.env.example` documenting every variable | **new** |

**Estimated churn:** ~2,500 LOC touched. **Bottleneck:** SQLAlchemy 2.x migration is the big one.

### Phase 3 — Bugs & security
| # | Task | Priority |
|---|---|---|
| 3.1 | Global CSRF (Flask-WTF or hand-rolled double-submit) on every state-changing route; keep `formkey` name in templates so markup doesn't change | **Critical** |
| 3.2 | Kill open redirects (allowlist of local paths) | **Critical** |
| 3.3 | Re-verify `sanitize`/`nofollow` under new bleach or `nh3`; escape titles/bios; add CSP + security headers | **Critical** |
| 3.4 | Password hashing → argon2id with pbkdf2 fallback verify + transparent rehash on login | **Critical** |
| 3.5 | Replace `source_code` filter with a safe allowlisted file map | **Critical** |
| 3.6 | Secure cookies, `SESSION_COOKIE_SECURE/SAMESITE`, always-on `before_request`/`teardown_request` | **Critical** |
| 3.7 | Rate limits on signup/forgot/reset/vote/flag/search; shared Redis store | High |
| 3.8 | Single-use, random (not deterministic) reset & verify tokens with server-side invalidation | High |
| 3.9 | Fix all the functional bugs in §7 (signup expiry, `comment_id` check, `sticky` None, `over18`, dark-mode gate, `base36decode` 404s, `abort` import, `Comment.rank_hot` typo, etc.) | High |
| 3.10 | Input length caps; `parent_fullname` validation | Medium |
| 3.11 | `CHANGELOG.md` entries per fix | — |

**Estimated churn:** ~1,200 LOC.

### Phase 4 — Tests
pytest suite (registration/login, post, comment, vote, moderation perms, API auth, CSRF, token flows), `ruff` lint + format, GitHub Actions workflow. **~800 LOC new.**

### Phase 5 — Install & deploy
Multi-stage Dockerfile (non-root), `docker-compose.yml` (app + Postgres 16 + Redis 7, volumes, healthchecks), `Makefile`, `INSTALL.md` (Windows/WSL2, Linux, macOS, VPS with Caddy/Nginx + Let's Encrypt + ufw + backups). **~600 LOC new.**

### Phase 6 — Docs & cleanup
README rewrite, `MIGRATION_NOTES.md`, delete `userpage.html alias`, `boards`/`dms`/`userflags` orphans, `reddit_api.py`, `test.py`, `build`, `_patch`, dead helpers; fix `.gitignore`; MPL-2.0 file headers. **~500 LOC.**

---

## 11. Constraints to respect

- **Visual style is load-bearing.** The CDN pins (Bootstrap 4.0/4.3, jQuery 3.1/3.2, Popper, clipboard.js, AOS, Google Fonts) and the compiled `main.css`/`main_dark.css` must be preserved byte-for-byte unless a page is broken. Front-end lib bumps are out of scope for the modernization and should not be attempted without visual diffing.
- **The SQL functions are the ranking engine.** Do not "simplify" `rank_hot`/`rank_fiery`/`energy` into ORM expressions without benchmarking; they are what makes the front page fast.
- **`schema.txt` and `db_prep.py` disagree.** `db_prep.py` wins (it runs at deploy), but the discrepancy must be resolved deliberately in Phase 2.
- **MPL-2.0**: keep `LICENSE`; add Exhibit-A headers to modified files in Phase 6.

---

## 12. Verification commands for Phase 1

```bash
# from the project root
find . -type f -not -path "./.git/*" | sort          # matches §1 tree
grep -rn "environ.get\|environ\[" --include="*.py" .  # matches §3 table (9 call sites)
grep -rn "werkzeug.contrib\|flaskext" --include="*.py" .
python -c "import ast; [ast.parse(open(f,encoding='utf-8').read()) for f in
  ['ruqqus/routes/login.py','ruqqus/routes/static.py','ruqqus/__main__.py']]; print('parsed ok')"
file "ruqqus/templates/userpage.html alias"            # -> Macintosh HFS alias data
```

Expected: no syntax errors (confirmed), `werkzeug.contrib` in `__main__.py:13` and `comments.py:15`, `flaskext.markdown` in `__main__.py:6`, 9 `environ.get` sites.

---

## Open questions & assumptions

1. **Target Python.** You said "3.12 or newer". gevent on 3.13 is fine but I'd like to **drop gevent entirely** and use `gunicorn -k gthread` (or `sync`), since the app is I/O-bound on Postgres/Redis and gevent's monkey-patching is what makes the shared `Session` dangerous. **Confirm?**

2. **`schema.txt` vs `db_prep.py` disagreement** (§5). I plan to treat `db_prep.py` as authoritative and regenerate the functions from it in the Alembic init migration, then write a migration that renames `ban_state` → `is_banned`/`ban_reason` and drops `board_id`/`over_18` on `submissions` to match the models. **OK to change the schema to match the code, or should old dumps keep the old column names?**

3. **Reddit integration.** I plan to **delete** `routes/reddit_api.py` and the `reddit_username`/reddit-badge path entirely (dead third-party, hardcoded redirect, and the badge template `tags/v.html` still points at reddit.com). It would be listed in `MIGRATION_NOTES.md` with a "bring your own OAuth" replacement suggestion. **Confirm deletion vs. stub behind config?**

4. **`boards` (guilds) and `dms`.** Your brief says "Keep the project's core features: … 'guilds' (communities)". In *this* codebase the guild feature is a **schema orphan** (`boards` table + `submissions.board_id`) with **zero** model, route, or template. There is no guild UI to preserve. **Should I (a) drop them and note it in MIGRATION_NOTES.md, or (b) implement a minimal guilds feature?** (b) is a feature build, not a modernization — I'd recommend (a) unless you say otherwise.

5. **Password hashing.** Plan: argon2id for new hashes, transparent verify-and-rehash for existing `pbkdf2:sha512` hashes. Requires `argon2-cffi`. **OK?**

6. **CSRF.** Plan: Flask-WTF's `CSRFProtect` with the hidden field named `formkey` so existing templates keep working with a one-line macro change. **OK?**

7. **`MASTER_KEY` doing double duty** (Flask `SECRET_KEY` + HMAC key). Plan: split into `SECRET_KEY` (sessions) and `TOKEN_SIGNING_KEY` (emails/reset), with `SECRET_KEY` accepted as a fallback for backwards compat. **OK?**

8. **Email.** Plan: `MAIL_BACKEND=console|smtp`, defaulting to `console` (prints to stdout) so a fresh install works with no third party. SMTP configured via `SMTP_HOST/PORT/USER/PASSWORD/FROM`. **OK?**

9. **File uploads.** There is **no upload code** in this codebase (grep for `request.files`/`FileStorage` returns nothing) — images are remote URLs and static assets. So the "safe file uploads" requirement is currently moot; I'll note it in MIGRATION_NOTES.md and add a pluggable local-disk upload helper only if you want user avatars/uploads added. **OK to defer?**

10. **Front-end library versions.** I plan to leave all CDN `<link>`/`<script>` tags untouched (§11). That keeps the look identical but leaves jQuery 3.1.1 / Bootstrap 4.0.0 with known CVEs. **Confirm we accept that trade-off for the look-and-feel requirement**, or do you want the CDN bumps with a visual regression pass?

11. **Naming.** `SERVER_NAME` from `domain` env var — I'll accept `SITE_URL` as the new primary name and keep `domain` as a deprecated alias for one release. **OK?**