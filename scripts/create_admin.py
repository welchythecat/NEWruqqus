#!/usr/bin/env python3
"""Create or promote an administrator account.

Run this once after installing, to get an account that can moderate the site
(admin_level >= 1) and manage other admins (admin_level >= 3).

    # Interactive - prompts for the password, does not echo it:
    python scripts/create_admin.py --username admin --email admin@example.com

    # Non-interactive (CI, Docker):
    python scripts/create_admin.py --username admin --email admin@example.com \
        --password 'a-long-random-passphrase'

    # Raise an existing account to admin without touching its password:
    python scripts/create_admin.py --username existinguser --promote-only

The script is idempotent: running it twice is safe.  A second run promotes the
account to the requested level and (unless --promote-only) resets its password.

Inside Docker:
    docker compose exec app python scripts/create_admin.py --username admin \
        --email admin@example.com
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

# Make the project root importable.  We add the *project root*, never this
# script's own directory, so a stray file in scripts/ cannot shadow a
# standard-library module.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ruqqus import config  # noqa: E402
from ruqqus.__main__ import db  # noqa: E402
from ruqqus.classes import User  # noqa: E402

# Matches the rules enforced by the signup form (routes/login.py).
VALID_USERNAME = re.compile(r"^\w{5,25}$")
MIN_PASSWORD_LENGTH = 8

# admin_level meanings used by the codebase:
#   0 = ordinary user
#   1 = can distinguish / remove individual comments
#   3 = full moderation: ban users, ban/undelete posts, sticky, manage admins
DEFAULT_LEVEL = 3
MAX_LEVEL = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or promote a Ruqqus administrator account.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--username", required=True, help="5-25 word characters")
    parser.add_argument(
        "--email", default=None, help="e-mail address (optional but recommended)"
    )
    parser.add_argument(
        "--password",
        default=None,
        help=f"at least {MIN_PASSWORD_LENGTH} characters; prompted for if omitted",
    )
    parser.add_argument(
        "--level",
        type=int,
        default=DEFAULT_LEVEL,
        choices=range(1, MAX_LEVEL + 1),
        metavar="1-3",
        help=f"admin level to grant (default {DEFAULT_LEVEL})",
    )
    parser.add_argument(
        "--promote-only",
        action="store_true",
        help="never create or change the password; only raise admin_level",
    )
    return parser.parse_args()


def read_password() -> str:
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords did not match.")
    return first


def main() -> int:
    args = parse_args()

    if not VALID_USERNAME.match(args.username):
        raise SystemExit(
            f"Invalid username {args.username!r}: must be 5-25 characters of "
            "letters, digits and underscores."
        )

    existing = db.query(User).filter(User.username.ilike(args.username)).first()

    # ---- promote an existing account -----------------------------------
    if existing:
        if existing.email != args.email and args.email:
            raise SystemExit(
                f"User {existing.username!r} already exists with e-mail "
                f"{existing.email!r}; refusing to change it. "
                "Re-run without --email to keep it."
            )

        if not args.promote_only:
            password = args.password or read_password()
            if len(password) < MIN_PASSWORD_LENGTH:
                raise SystemExit(
                    f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
                )
            existing.passhash = existing.hash_password(password)
            print(f"Password reset for {existing.username!r}.")

        changed_level = existing.admin_level != args.level
        existing.admin_level = args.level
        existing.is_activated = True

        db.add(existing)
        db.commit()

        print(
            f"Account {existing.username!r} (id={existing.id}) is now "
            f"admin_level={args.level}."
            if changed_level
            else f"Account {existing.username!r} (id={existing.id}) already at "
                 f"admin_level={args.level}."
        )
        print(f"Log in at {config.SITE_URL}/login")
        return 0

    # ---- create a new account ------------------------------------------
    if args.promote_only:
        raise SystemExit(
            f"--promote-only was given but {args.username!r} does not exist."
        )

    password = args.password or read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )

    if args.email:
        clash = db.query(User).filter(User.email.ilike(args.email)).first()
        if clash:
            raise SystemExit(
                f"E-mail {args.email!r} already belongs to {clash.username!r}."
            )

    new_user = User(
        username=args.username,
        password=password,
        email=args.email,
        admin_level=args.level,
        # An activated account can use the password-reset flow immediately.
        is_activated=True,
    )
    db.add(new_user)
    db.commit()

    print(f"Created {new_user.username!r} (id={new_user.id}) with admin_level={args.level}.")
    print(
        f"Log in at {config.SITE_URL}/login"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
