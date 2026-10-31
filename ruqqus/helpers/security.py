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
    Hash a password for storage using ``scrypt``.

    ``scrypt`` is memory-hard, which is the point: ``pbkdf2:sha512`` is fast
    enough to brute-force on a GPU.  It is Werkzeug's own default and is backed
    by :func:`hashlib.scrypt` in the standard library, so this adds no
    dependency.

    Parameters are Werkzeug's default, ``scrypt:32768:8:1`` (N=2^15, r=8, p=1),
    which is the RFC 7914 / OWASP-recommended starting point and takes roughly
    50-100ms per hash on typical hardware.

    Existing ``pbkdf2:sha512`` hashes are deliberately NOT invalidated.
    :func:`check_password_hash` dispatches on the algorithm name stored in the
    hash string itself, so accounts created before this change keep logging in
    and are silently upgraded to ``scrypt`` on their next successful login --
    see :meth:`User._upgrade_hash_if_needed`.  No migration script, no mass
    re-hash, no forced password resets.
    """
    return generate_password_hash(password, method="scrypt")


__all__ = ["generate_hash", "validate_hash", "hash_password",
           "generate_password_hash", "check_password_hash"]
