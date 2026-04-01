"""Temporary email inbox helper used by notification tests.

Uses the free 1secmail.com API — no API key required.

    inbox = TempMailChecker.generate_inbox()
    print(inbox.email)                   # e.g. "abc123@1secmail.com"
    msg  = inbox.wait_for_notification(  # blocks until email arrives
        subject_contains="download",
        timeout_seconds=120,
    )
"""

import time
from typing import Optional

import httpx


class TempMailChecker:
    """Check for email notifications using the 1secmail.com free API."""

    API_URL = "https://www.1secmail.com/api/v1/"

    def __init__(self, login: str, domain: str):
        self.login = login
        self.domain = domain
        self.email = f"{login}@{domain}"

    @classmethod
    def generate_inbox(cls) -> "TempMailChecker":
        """Generate a fresh random inbox address."""
        response = httpx.get(
            cls.API_URL,
            params={"action": "genRandomMailbox", "count": 1},
            timeout=15,
        )
        response.raise_for_status()
        email = response.json()[0]
        login, domain = email.split("@", 1)
        return cls(login, domain)

    def get_messages(self) -> list:
        """Return the list of message summaries currently in the inbox."""
        response = httpx.get(
            self.API_URL,
            params={
                "action": "getMessages",
                "login": self.login,
                "domain": self.domain,
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def read_message(self, message_id: int) -> dict:
        """Return the full content of a message by its id."""
        response = httpx.get(
            self.API_URL,
            params={
                "action": "readMessage",
                "login": self.login,
                "domain": self.domain,
                "id": message_id,
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def wait_for_notification(
        self,
        subject_contains: Optional[str] = None,
        from_contains: Optional[str] = None,
        timeout_seconds: int = 120,
        poll_interval: int = 5,
    ) -> Optional[dict]:
        """Poll the inbox until a matching message arrives or the timeout expires.

        Returns the full message dict if found, or ``None`` on timeout.
        Matching is case-insensitive substring search.
        """
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            for summary in self.get_messages():
                subject = summary.get("subject") or ""
                sender = summary.get("from") or ""
                matches_subject = subject_contains is None or subject_contains.lower() in subject.lower()
                matches_from = from_contains is None or from_contains.lower() in sender.lower()
                if matches_subject and matches_from:
                    return self.read_message(summary["id"])
            time.sleep(poll_interval)
        return None
