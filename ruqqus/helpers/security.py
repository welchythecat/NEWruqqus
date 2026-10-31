"""
Token generation and password hashing helpers.

Tokens are HMACs used for password-reset and e-mail-verification links.  They
are *deterministic* -- the same inputs always produce the same token -- which
is a known weakness (a token is never invalidated after use).  Phase 3
replaces this with random, single-use tokens; the behaviour is preserved here
so Phase 2 changes nothing observable.
"""

import hmac

from werkzeug.security import check_password_hash, generate_password_hash

from ruqqus import config


def generate_hash(string: str) -> str:
    """Sign a string with the application token key and return a hex digest."""
    return hmac.new(
        key=config.TOKEN_SIGNING_KEY.encode("utf-16"),
        msg=string.encode("utf-16"),
        digestmod="md5",
    ).hexdigest()


def validate_hash(string: str, hashstr: str) -> bool:
    """Constant-time check of a token produced by :func:`generate_hash`."""
    return hmac.compare_digest(hashstr, generate_hash(string))


def hash_password(password: str) -> str:
    """
    Hash a password for storage.

    Kept identical to the original ``pbkdf2:sha512`` / 8-byte salt so that
    existing hashes keep verifying.  Phase 3 upgrades to argon2id with a
    transparent rehash-on-login path.
    """
    return generate_password_hash(password, method="pbkdf2:sha512", salt_length=8)


__all__ = ["generate_hash", "validate_hash", "hash_password",
           "generate_password_hash", "check_password_hash"]
