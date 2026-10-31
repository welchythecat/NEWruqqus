"""
Jinja2 template filters.

``total_users`` renders the user count shown in the sidebar.  ``source_code``
renders snippets of Ruqqus source on the /help/about page.

``source_code`` used to open ``"/app/" + file_name`` in ``r+`` mode -- a
Heroku-slug path that also demanded write permission on the file.  It now
reads from the project root read-only, and refuses any path that resolves
outside it.
"""

from __future__ import annotations

from pathlib import Path

from ruqqus import config
from ruqqus.classes.user import User
from ruqqus.__main__ import app, cache, db

#: Only these files may be shown on /help/about.  Anything else is refused.
SOURCE_CODE_ALLOWED = (
    "ruqqus/classes/votes.py",
    "ruqqus/classes/submission.py",
    "ruqqus/classes/user.py",
    "ruqqus/classes/comment.py",
)


@app.template_filter("total_users")
@cache.memoize(timeout=60)
def total_users(x):
    return db.query(User).filter_by(is_banned=0).count()


@app.template_filter("source_code")
@cache.memoize(timeout=60 * 60 * 24)
def source_code(file_name):
    if file_name not in SOURCE_CODE_ALLOWED:
        return f"# {file_name} is not available for display"

    root = config.PROJECT_ROOT.resolve()
    target = (root / file_name).resolve()

    # Belt and braces: even with an allowlist, refuse anything outside root.
    if not target.is_relative_to(root) or not target.is_file():
        return f"# {file_name} could not be read"

    return target.read_text(encoding="utf-8")
