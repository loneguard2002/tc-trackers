"""The domains report emails may go to (audit 2026-11-25, Medium 1), kept in ``app_settings`` and changed by an
administrator on Email settings. A tracker's recipient must have an address at one of them: one outside the list cannot
be added, and one added before (or whose domain was taken off since) stays on the list but is not sent to."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppSetting

KEY = "recipient_domains"
# Until an administrator saves a list: the organisation's own domains.
DEFAULT_DOMAINS = ("tradition.com", "tradition.ch", "traditiondata.com", "traditionasia.com")
MAX_DOMAINS = 50
EMPTY_ERROR = "Keep at least one domain: report emails can only go to addresses at a domain on this list."
DOMAIN_ERROR = "Enter each domain as it appears after the @, for example example.com."
TOO_MANY_ERROR = f"Enter at most {MAX_DOMAINS} domains."
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")


def allowed_domains(session: Session) -> list[str]:
    """The saved domains, or the organisation's own until a list is saved."""
    stored = session.scalar(select(AppSetting.value).where(AppSetting.key == KEY))
    if stored is None:
        return list(DEFAULT_DOMAINS)
    return [part for part in stored.split() if part]


def parse_domains(text: str) -> tuple[list[str], str | None]:
    """``(domains, error)`` for the posted list: one per line (commas and spaces also separate), a leading @ is dropped,
    lower case, each once, in the order given."""
    found: list[str] = []
    for part in re.split(r"[\s,;]+", (text or "").lower()):
        domain = part.strip().lstrip("@")
        if not domain:
            continue
        if not _DOMAIN.fullmatch(domain):
            return [], DOMAIN_ERROR
        if domain not in found:
            found.append(domain)
    if not found:
        return [], EMPTY_ERROR
    if len(found) > MAX_DOMAINS:
        return [], TOO_MANY_ERROR
    return found, None


def domain_of(email: str) -> str:
    return email.rpartition("@")[2].strip().lower()


def is_allowed(email: str, domains: list[str]) -> bool:
    """Whether the address is at one of ``domains`` exactly (a sub-domain needs its own entry)."""
    return domain_of(email) in domains


def split_recipients(emails: list[str], domains: list[str]) -> tuple[list[str], list[str]]:
    """``(allowed, not_allowed)``, each in the order given."""
    allowed = [email for email in emails if is_allowed(email, domains)]
    return allowed, [email for email in emails if not is_allowed(email, domains)]


def listed(domains: list[str]) -> str:
    """The domains as a sentence: "a, b or c"."""
    if len(domains) <= 1:
        return "".join(domains)
    return ", ".join(domains[:-1]) + " or " + domains[-1]


def not_allowed_message(email: str, domains: list[str]) -> str:
    return (
        f"{domain_of(email)} is not an allowed domain. Use an address at {listed(domains)}, or ask an administrator "
        "to allow it in Email settings."
    )
