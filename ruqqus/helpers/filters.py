"""
Per-domain content rules.

A comment is rejected when it links to a domain whose ``can_comment`` flag is
false in the ``domains`` table.  The set of candidate domains is every
subdomain suffix of each link, so a rule on ``example.com`` also covers
``www.example.com``.
"""

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ruqqus.__main__ import db
from ruqqus.classes import Domain


def filter_comment_html(html_text):
    soup = BeautifulSoup(html_text, features="html.parser")

    links = soup.find_all("a")

    domain_list = set()

    for link in links:
        # bleach strips a disallowed href (e.g. javascript:) and leaves <a>
        # with no href at all, so this must not assume the attribute exists.
        href = link.get("href")
        if not href:
            continue

        domain = urlparse(href).netloc

        # parse domain into all possible subdomains
        parts = domain.split(".")
        for i in range(len(parts)):
            new_domain = parts[i]
            for j in range(i + 1, len(parts)):
                new_domain += "." + parts[j]

                domain_list.add(new_domain)

    if not domain_list:
        return []

    # search db for domain rules that prohibit commenting
    bans = (
        db.query(Domain)
        .filter_by(can_comment=False)
        .filter(Domain.domain.in_(list(domain_list)))
        .all()
    )

    return bans if bans else []
