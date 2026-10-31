"""
Replacement for the abandoned ``flaskext.markdown`` (Flask-Markdown 0.3).

Flask-Markdown registered a Jinja filter named ``markdown`` used by the help
templates as ``{% filter markdown %}...{% endfilter %}``.  It wrapped
``markdown.Markdown()`` and marked the output safe.

We reproduce that exactly -- including the *no extensions* default, which is
what ``Markdown(app)`` used.  The help pages rely only on core syntax
(headings, paragraphs, links, blockquotes), so adding extensions such as
``extra`` would change how those pages render.
"""

from __future__ import annotations

import markdown as _markdown
from markupsafe import Markup


def render_markdown(text: str) -> Markup:
    """Convert a markdown fragment to safe HTML, exactly as Flask-Markdown did."""
    if not text:
        return Markup("")
    html = _markdown.markdown(text, output_format="html")
    return Markup(html)


def attach_markdown_filter(app) -> None:
    """Register the ``markdown`` Jinja filter on a Flask app."""
    app.jinja_env.filters["markdown"] = render_markdown
