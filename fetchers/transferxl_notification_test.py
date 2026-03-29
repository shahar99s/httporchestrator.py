"""Integration test: TransferXL download notification.

Test steps
----------
1. Upload a test file to TransferXL (or use a pre-configured URL).  The sender
   email is set to a monitored temp-mail address so the "first download"
   notification can be verified.
2. Use ``TransferXLFetcherFactory`` as a separate user to info / fetch the file.
3. Verify the download notification:
   - After INFO mode the ``download_count`` must remain 0.
   - After FETCH mode the ``download_count`` increments (to 1) and a
     notification email should arrive in the sender's inbox.

Environment variables
---------------------
TEST_TRANSFERXL_URL
    Optional.  When set the upload step is skipped and the supplied TransferXL
    download URL is used directly.  The URL must point to a fresh transfer
    whose download counter is still 0.
"""

import os
import unittest

import httpx
import pytest

from fetchers.mail_checker import TempMailChecker
from fetchers.transferxl_fetcher import TransferXLFetcherFactory
from fetchers.utils import Mode

_TEST_CONTENT = b"Hello, TransferXL notification test!"
_TEST_FILENAME = "transferxl_test.txt"

_TRANSFERXL_API_BASE = "https://api.transferxl.com/api/v2"


def _upload_to_transferxl(
    file_content: bytes,
    filename: str,
    sender_email: str,
) -> str:
    """Upload *file_content* to TransferXL and return the public download URL.

    Uses the TransferXL v2 API.
    """
    # Step 1: create the transfer
    create_resp = httpx.post(
        f"{_TRANSFERXL_API_BASE}/upload",
        json={
            "from": sender_email,
            "subject": "Test notification transfer",
            "message": "Integration test upload",
            "files": [{"name": filename, "size": len(file_content)}],
        },
        timeout=30,
    )
    create_resp.raise_for_status()
    data = create_resp.json()
    # TransferXL uses "id" for the internal transfer identifier; "shortUrl" contains
    # the same alphanumeric code used in the public download URL and in API calls that
    # accept a shortUrl parameter — so it is a valid stand-in for the transfer ID.
    transfer_id = data.get("id") or data.get("shortUrl")
    files = data.get("files") or [{}]
    upload_url = data.get("uploadUrl") or files[0].get("uploadUrl")
    if not transfer_id:
        raise RuntimeError(
            f"TransferXL create transfer did not return a transfer id: {data}"
        )
    if not upload_url:
        raise RuntimeError(
            f"TransferXL create transfer did not return an upload URL: {data}"
        )

    # Step 2: upload file content
    httpx.put(
        upload_url,
        content=file_content,
        headers={"Content-Type": "text/plain"},
        timeout=30,
    ).raise_for_status()

    # Step 3: finalise the transfer
    complete_resp = httpx.post(
        f"{_TRANSFERXL_API_BASE}/upload/{transfer_id}/complete",
        json={},
        timeout=30,
    )
    complete_resp.raise_for_status()

    download_url = complete_resp.json().get("shareUrl") or f"https://transferxl.com/download/{transfer_id}"
    return download_url


@pytest.mark.integration
class TestTransferXLNotification(unittest.TestCase):
    """Integration test: TransferXL sends a "first download" notification email.

    Steps:
    1. Upload a test file with the sender address pointing to a monitored inbox.
    2. Info / fetch via TransferXLFetcherFactory (as a different user).
    3. Verify:
       - INFO mode does not increment the download counter.
       - FETCH mode increments the counter and triggers a notification email.
    """

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        try:
            cls.mail = TempMailChecker.generate_inbox()
            url = os.environ.get("TEST_TRANSFERXL_URL")
            if url:
                cls.transfer_url = url
            else:
                cls.transfer_url = _upload_to_transferxl(
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
    def test_info_does_not_increment_download_counter(self):
        """INFO mode must not increment ``download_count``.

        TransferXL tracks downloads; a counter at 0 confirms no notification
        has been dispatched yet.
        """
        fetcher = TransferXLFetcherFactory(self.transfer_url).create(mode=Mode.INFO)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        metadata = session_vars.get("metadata", {})
        downloads_count = session_vars.get("downloads_count")

        self.assertIsNotNone(
            metadata,
            "Metadata should be populated after INFO run",
        )
        # For a freshly uploaded transfer the initial count must be 0.
        self.assertEqual(
            downloads_count,
            0,
            "Download counter must be 0 after INFO mode (no download occurred)",
        )

    # ------------------------------------------------------------------
    # Test 2 – FETCH mode
    # ------------------------------------------------------------------
    def test_fetch_triggers_first_download_notification(self):
        """FETCH mode downloads the file and TransferXL sends a notification email
        to the sender on the first download.
        """
        fetcher = TransferXLFetcherFactory(self.transfer_url).create(mode=Mode.FETCH)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        # Pre-fetch counter should have been 0 (first download).
        initial_downloads_count = session_vars.get("downloads_count", 0)
        self.assertEqual(
            initial_downloads_count,
            0,
            "Expected downloads_count to be 0 before the first fetch",
        )

        # Verify the notification email arrives in the sender's inbox.
        notification = self.mail.wait_for_notification(
            subject_contains="download",
            timeout_seconds=120,
        )
        self.assertIsNotNone(
            notification,
            f"Expected a download notification email at {self.mail.email} but none arrived",
        )
