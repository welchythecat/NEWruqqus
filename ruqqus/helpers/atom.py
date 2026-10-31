"""
Minimal Atom 1.0 feed generator.

Replaces ``werkzeug.contrib.atom.AtomFeed``, which was removed from Werkzeug
in 1.0.  Only the surface used by ``ruqqus/routes/comments.py`` is
implemented: ``AtomFeed(title=..., feed_url=..., url=...)``, ``.add(...)`` and
``.get_response()``.

Produces RFC 4287 output.  Text and attribute values are XML-escaped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

from werkzeug.wrappers import Response

ATOM_NS = "http://www.w3.org/2005/Atom"


def _iso(value: datetime | None) -> str:
    """Render a datetime as an RFC 3339 / ISO 8601 timestamp."""
    if value is None:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AtomFeed:
    """A very small Atom feed builder."""

    def __init__(self, title=None, entries=None, **kwargs):
        self.title = title
        self.feed_url = kwargs.pop("feed_url", None)
        self.url = kwargs.pop("url", None)
        self.id = kwargs.pop("id", None) or self.url or self.feed_url or "urn:ruqqus"
        self.subtitle = kwargs.pop("subtitle", None)
        self.updated = kwargs.pop("updated", None)
        self.author = kwargs.pop("author", None)
        self.generator = kwargs.pop("generator", ("Ruqqus", None, None))
        # Anything else is ignored, matching the permissive Werkzeug API.
        self.entries = list(entries) if entries else []

    # -- building ---------------------------------------------------------
    def add(self, title, content, content_type="html", summary=None,
            summary_type=None, updated=None, published=None, author=None,
            id=None, url=None, **kwargs):
        self.entries.append({
            "title": title,
            "content": content,
            "content_type": content_type or "html",
            "summary": summary,
            "summary_type": summary_type,
            "updated": updated,
            "published": published,
            "author": author,
            "id": id or url,
            "url": url,
        })

    def __len__(self):
        return len(self.entries)

    # -- rendering --------------------------------------------------------
    def to_string(self) -> str:
        out = [f'<?xml version="1.0" encoding="utf-8"?>']
        out.append(f'<feed xmlns="{ATOM_NS}">')

        out.append(f"  <title>{escape(str(self.title or ''))}</title>")
        out.append(f"  <id>{escape(str(self.id))}</id>")

        feed_updated = self.updated
        if feed_updated is None and self.entries:
            feed_updated = self.entries[0].get("updated")
        out.append(f"  <updated>{_iso(feed_updated)}</updated>")

        if self.url:
            out.append(f"  <link rel='alternate' type='text/html' href={quoteattr(str(self.url))} />")
        if self.feed_url:
            out.append(f"  <link rel='self' type='application/atom+xml' href={quoteattr(str(self.feed_url))} />")
        if self.subtitle:
            out.append(f"  <subtitle>{escape(str(self.subtitle))}</subtitle>")

        if self.generator:
            name, version, uri = (tuple(self.generator) + (None, None, None))[:3]
            attrs = ""
            if version:
                attrs += f" version={quoteattr(str(version))}"
            if uri:
                attrs += f" uri={quoteattr(str(uri))}"
            out.append(f"  <generator{attrs}>{escape(str(name or ''))}</generator>")

        if self.author:
            out.append(f"  <author><name>{escape(str(self.author))}</name></author>")

        for entry in self.entries:
            out.append("  <entry>")
            out.append(f"    <title>{escape(str(entry['title'] or ''))}</title>")
            if entry.get("id"):
                out.append(f"    <id>{escape(str(entry['id']))}</id>")
            if entry.get("url"):
                out.append(f"    <link rel='alternate' type='text/html' href={quoteattr(str(entry['url']))} />")
            out.append(f"    <updated>{_iso(entry.get('updated'))}</updated>")
            if entry.get("published"):
                out.append(f"    <published>{_iso(entry.get('published'))}</published>")

            author = entry.get("author") or self.author
            if author:
                out.append(f"    <author><name>{escape(str(author))}</name></author>")

            if entry.get("summary") is not None:
                stype = entry.get("summary_type") or "text"
                out.append(f"    <summary type={quoteattr(str(stype))}>{escape(str(entry['summary']))}</summary>")

            ctype = entry.get("content_type") or "html"
            out.append(f"    <content type={quoteattr(str(ctype))}>{escape(str(entry['content'] or ''))}</content>")
            out.append("  </entry>")

        out.append("</feed>")
        return "\n".join(out)

    def get_response(self) -> Response:
        return Response(
            self.to_string(),
            mimetype="application/atom+xml",
            headers={"Content-Type": "application/atom+xml; charset=utf-8"},
        )
