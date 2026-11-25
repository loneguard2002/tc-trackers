"""The feedback settings kept in ``app_settings``: where feedback is emailed, and whether the Feedback link shows.

No address is ever written in the code; the recipients are whatever an administrator saved.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppSetting

ADDRESS_KEY = "feedback_email"
LINK_KEY = "feedback_link"
MAX_ADDRESSES = 10
ADDRESS_ERROR = "Enter valid email addresses, separated by commas."
TOO_MANY_ERROR = "Enter at most 10 addresses."
_ADDRESS = re.compile(r"[^@\s,;<>()\[\]\"]+@[^@\s,;<>()\[\]\"]+\.[^@\s,;<>()\[\]\"]+")


def _value(session: Session, key: str) -> str | None:
    return session.scalar(select(AppSetting.value).where(AppSetting.key == key))


def addresses(session: Session) -> list[str]:
    """The saved feedback addresses; an empty list when none is set."""
    return [part.strip() for part in (_value(session, ADDRESS_KEY) or "").split(",") if part.strip()]


def link_on(session: Session) -> bool:
    """Whether the Feedback link and the form page are on; they are until an administrator switches them off."""
    return _value(session, LINK_KEY) != "0"


def parse_addresses(text: str) -> tuple[list[str], str | None]:
    """``(addresses, error)`` for the text of the box; blank means none. Spaces and empty items are ignored."""
    found = [part.strip() for part in (text or "").split(",") if part.strip()]
    if not all(_ADDRESS.fullmatch(address) for address in found):
        return [], ADDRESS_ERROR
    if len(found) > MAX_ADDRESSES:
        return [], TOO_MANY_ERROR
    return found, None
