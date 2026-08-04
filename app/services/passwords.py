from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16
DERIVED_KEY_BYTES = 32
MAX_PASSWORD_BYTES = 1024


class PasswordHashError(ValueError):
    """Raised when a password or stored hash cannot be processed safely."""


def _password_bytes(password: str) -> bytes:
    if not isinstance(password, str):
        raise PasswordHashError("Password must be text.")

    encoded = password.encode("utf-8")
    if not encoded:
        raise PasswordHashError("Password cannot be empty.")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise PasswordHashError(
            f"Password cannot exceed {MAX_PASSWORD_BYTES} UTF-8 bytes."
        )
    return encoded


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise PasswordHashError("Stored password hash is malformed.") from exc


def hash_password(
    password: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
) -> str:
    """Return a versioned PBKDF2-SHA256 password hash."""
    if iterations < 100_000:
        raise PasswordHashError("Password hash iterations are too low.")

    password_bytes = _password_bytes(password)
    salt = secrets.token_bytes(SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password_bytes,
        salt,
        iterations,
        dklen=DERIVED_KEY_BYTES,
    )
    return "$".join(
        (
            ALGORITHM,
            str(iterations),
            _encode(salt),
            _encode(derived_key),
        )
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password using a constant-time digest comparison."""
    try:
        algorithm, raw_iterations, raw_salt, raw_expected = stored_hash.split(
            "$",
            3,
        )
        if algorithm != ALGORITHM:
            return False

        iterations = int(raw_iterations)
        if iterations < 100_000:
            return False

        password_bytes = _password_bytes(password)
        salt = _decode(raw_salt)
        expected = _decode(raw_expected)
        if len(salt) < 16 or len(expected) < 16:
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password_bytes,
            salt,
            iterations,
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, PasswordHashError, TypeError, ValueError):
        return False


def needs_rehash(
    stored_hash: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
) -> bool:
    """Return True when the stored format or work factor should be upgraded."""
    try:
        algorithm, raw_iterations, _, _ = stored_hash.split("$", 3)
        return algorithm != ALGORITHM or int(raw_iterations) < iterations
    except (AttributeError, TypeError, ValueError):
        return True
