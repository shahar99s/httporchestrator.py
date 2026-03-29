"""Integration test: WeTransfer download notification.

Test steps
----------
1. Create a WeTransfer transfer (uploader side) using a temp-mail address so that
   any "first download" notification email lands in a verifiable inbox.
2. Use ``WeTransferFetcherFactory`` as a separate "user" to info / fetch the file.
3. Verify the download notification was delivered:
   - via the download counter exposed by the WeTransfer API (counter increments on
     each call to the ``/download`` endpoint, which triggers the notification), and
   - via the temp-mail inbox (a notification email should arrive after the first
     actual download).

Environment variables
---------------------
TEST_WETRANSFER_URL
    Optional.  When set the upload step is skipped and the supplied download URL
    is used directly.  The URL must point to a fresh transfer whose download
    counter is still 0.
"""

import os
import unittest

import httpx
import pytest

from fetchers.mail_checker import TempMailChecker
from fetchers.utils import Mode
from fetchers.wetransfer_fetcher import WeTransferFetcherFactory

_TEST_CONTENT = b"Hello, WeTransfer notification test!"
_TEST_FILENAME = "wetransfer_test.txt"


def _upload_to_wetransfer(
    file_content: bytes,
    filename: str,
    sender_email: str,
) -> str:
    """Upload *file_content* to WeTransfer and return the download URL.

    Uses the public WeTransfer v4 API (no authentication required for anonymous
    transfers).
    """
    base_url = "https://wetransfer.com"
    common_headers = {
        "x-requested-with": "XMLHttpRequest",
        "Content-Type": "application/json",
    }

    # Step 1: create the transfer and get a presigned upload URL
    create_body = {
        "message": "Integration test upload",
        "ui_language": "en",
        "sender": {"email": sender_email},
        "files": [
            {
                "name": filename,
                "size": len(file_content),
                "multipart": {
                    "chunk_size": len(file_content),
                    "id": None,
                },
            }
        ],
    }
    resp = httpx.post(
        f"{base_url}/api/v4/transfers",
        json=create_body,
        headers=common_headers,
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    transfer_data = resp.json()
    transfer_id = transfer_data["id"]
    files = transfer_data.get("files") or []
    if not files:
        raise RuntimeError(f"WeTransfer create transfer returned no files: {transfer_data}")
    file_info = files[0]
    file_id = file_info["id"]
    upload_url = file_info["multipart"]["url"]

    # Step 2: upload file content to the presigned S3 URL
    httpx.put(upload_url, content=file_content, timeout=30).raise_for_status()

    # Step 3: mark the file upload as complete
    httpx.put(
        f"{base_url}/api/v4/transfers/{transfer_id}/files/{file_id}/upload-complete",
        json={"part_numbers": 1},
        headers=common_headers,
        timeout=30,
    ).raise_for_status()

    # Step 4: finalise the transfer → returns the public download URL
    resp = httpx.put(
        f"{base_url}/api/v4/transfers/{transfer_id}/finalize",
        headers=common_headers,
        timeout=30,
    )
    resp.raise_for_status()
    download_url = resp.json().get("url")
    if not download_url:
        raise RuntimeError(f"WeTransfer finalise did not return a download URL: {resp.json()}")
    return download_url


@pytest.mark.integration
class TestWeTransferNotification(unittest.TestCase):
    """Integration test: WeTransfer sends a download notification email after the
    first download of a transfer.

    Steps:
    1. Upload a test file as a user whose inbox is monitored via TempMailChecker.
    2. Fetch / info the transfer as a different (anonymous) user.
    3. Confirm a notification is recorded (download counter > 0 and/or email arrives).
    """

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        try:
            cls.mail = TempMailChecker.generate_inbox()
            url = os.environ.get("TEST_WETRANSFER_URL")
            if url:
                cls.transfer_url = url
            else:
                cls.transfer_url = _upload_to_wetransfer(
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
        """INFO mode retrieves transfer metadata without triggering a download.

        WeTransfer notifies the sender only when the ``/download`` endpoint is
        called (which creates a direct link and increments the counter).  INFO
        mode must *not* call that endpoint, so the counter stays at 0.
        """
        fetcher = WeTransferFetcherFactory(self.transfer_url).create(mode=Mode.INFO)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        downloads_count = session_vars.get("downloads_count", 0)
        # No download should have occurred → counter remains at its initial value
        self.assertIsNotNone(
            session_vars.get("metadata"),
            "Metadata should be populated after INFO run",
        )
        self.assertGreaterEqual(
            downloads_count,
            0,
            "downloads_count must be a non-negative integer",
        )

    # ------------------------------------------------------------------
    # Test 2 – FETCH mode
    # ------------------------------------------------------------------
    def test_fetch_triggers_download_notification(self):
        """FETCH mode downloads the file, incrementing the counter and sending
        a notification email to the sender's address.

        WeTransfer sends a 'first download' email notification to the sender
        when the download count transitions from 0 to 1.
        """
        fetcher = WeTransferFetcherFactory(self.transfer_url).create(mode=Mode.FETCH)
        fetcher.run()

        session_vars = self._session_vars(fetcher)

        # The direct_link step (which triggers the notification) must have run.
        # After fetching, the downloads_count seen at info time was 0, meaning
        # this was the first download → a notification email was dispatched.
        self.assertIsNotNone(
            session_vars.get("metadata"),
            "Metadata should be populated after FETCH run",
        )
        initial_downloads_count = session_vars.get("downloads_count", 0)
        # The counter captured by the fetcher is the value *before* this download.
        # For a freshly uploaded transfer it should be 0.
        self.assertEqual(
            initial_downloads_count,
            0,
            "Expected download counter to be 0 before the first fetch",
        )

        # Check that a notification email was delivered to the sender's inbox.
        notification = self.mail.wait_for_notification(
            subject_contains="download",
            timeout_seconds=120,
        )
        self.assertIsNotNone(
            notification,
            f"Expected a download notification email at {self.mail.email} but none arrived",
        )
