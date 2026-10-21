"""Password hashing (passlib bcrypt)."""

from __future__ import annotations

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 72  # bcrypt ignores or rejects anything longer

# Verified against when the account does not exist, so response time does not reveal which emails are registered.
_DUMMY_HASH = pwd_context.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(password, hashed)
    except (ValueError, TypeError):
        return False


def verify_against_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def validate_new_password(password: str) -> str | None:
    """Return an error message for an unacceptable new password, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"The password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return f"The password must be at most {MAX_PASSWORD_BYTES} bytes long."
    return None
