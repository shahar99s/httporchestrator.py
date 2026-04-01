"""Integration test: SendGB download notification.

Test steps
----------
1. Upload a test file to SendGB (or use a pre-configured URL).  The recipient
   for the "first-download" notification email is a temp-mail address generated
   specifically for this test run.
2. Use ``SendgbFetcherFactory`` as a separate user to info / fetch the file.
3. Verify the download notification:
   - After INFO mode the file is **not** downloaded, so no notification email
     should arrive.
   - After FETCH mode the file is downloaded and a notification email should
     land in the sender's inbox.

Environment variables
---------------------
TEST_SENDGB_URL
    Optional.  When set the upload step is skipped and the supplied SendGB
    download URL is used directly.  The URL must point to a fresh transfer
    whose download counter is still 0.
"""

import os
import re
import unittest

import httpx
import pytest

from fetchers.mail_checker import TempMailChecker
from fetchers.sendgb_fetcher import SendgbFetcherFactory
from fetchers.utils import Mode

_TEST_CONTENT = b"Hello, SendGB notification test!"
_TEST_FILENAME = "sendgb_test.txt"


def _upload_to_sendgb(file_content: bytes, filename: str, sender_email: str) -> str:
    """Upload *file_content* to SendGB and return the public download URL.

    Uses the SendGB multipart upload endpoint.
    """
    upload_url = "https://www.sendgb.com/upload"

    resp = httpx.post(
        upload_url,
        data={"email": sender_email, "lang": "en"},
        files={"file[]": (filename, file_content, "text/plain")},
        follow_redirects=True,
        timeout=60,
    )
    resp.raise_for_status()

    # SendGB returns the transfer URL in the response JSON or as a redirect.
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    transfer_url = data.get("url") or data.get("link")
    if not transfer_url:
        # Try to extract from HTML response (SendGB sometimes returns HTML).
        match = re.search(r'sendgb\.com/([0-9a-zA-Z]+)', resp.text)
        if match:
            transfer_url = f"https://www.sendgb.com/{match.group(1)}"
    if not transfer_url:
        raise RuntimeError(f"SendGB upload did not return a transfer URL. Response: {resp.text[:500]}")
    return transfer_url


@pytest.mark.integration
class TestSendGBNotification(unittest.TestCase):
    """Integration test: SendGB sends a "first download" notification email.

    Steps:
    1. Upload a test file with sender_email pointing to a monitored temp inbox.
    2. Info / fetch via SendgbFetcherFactory (as a different user).
    3. After FETCH, verify the notification email arrives in the sender's inbox.
    """

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        try:
            cls.mail = TempMailChecker.generate_inbox()
            url = os.environ.get("TEST_SENDGB_URL")
            if url:
                cls.transfer_url = url
            else:
                cls.transfer_url = _upload_to_sendgb(
                    _TEST_CONTENT, _TEST_FILENAME, cls.mail.email
                )
        except Exception as exc:
            cls.skip_reason = f"Upload/setup failed: {exc}"

    def setUp(self):
        if self.skip_reason:
            self.skipTest(self.skip_reason)

    def _session_vars(self, fetcher):
        return fetcher._HttpRunner__final_session_variables

    # ------------------------------------------------------------------
    # Test 1 – INFO mode
    # ------------------------------------------------------------------
    def test_info_does_not_trigger_notification(self):
        """INFO mode retrieves file metadata without downloading.

        SendGB only sends a notification on the *first actual download*, so INFO
        mode (which does not download) must not produce a notification email.
        """
        fetcher = SendgbFetcherFactory(self.transfer_url).create(mode=Mode.INFO)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        self.assertIn(
            "metadata",
            session_vars,
            "Metadata should be populated after INFO run",
        )

        # No notification should arrive — download did not happen.
        no_notification = self.mail.wait_for_notification(
            subject_contains="download",
            timeout_seconds=30,
        )
        self.assertIsNone(
            no_notification,
            "Did not expect a notification email after INFO mode (no download occurred)",
        )

    # ------------------------------------------------------------------
    # Test 2 – FETCH mode
    # ------------------------------------------------------------------
    def test_fetch_triggers_first_download_notification(self):
        """FETCH mode downloads the file and SendGB dispatches a "first download"
        notification email to the sender's address.
        """
        fetcher = SendgbFetcherFactory(self.transfer_url).create(mode=Mode.FETCH)
        fetcher.run()

        # Check the sender's inbox for the notification email.
        notification = self.mail.wait_for_notification(
            subject_contains="download",
            timeout_seconds=120,
        )
        self.assertIsNotNone(
            notification,
            f"Expected a download notification email at {self.mail.email} but none arrived",
        )
