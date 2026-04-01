import unittest

from fetchers.limewire_fetcher import LimeWireFetcherFactory
from fetchers.utils import Mode


def _step_struct(fetcher, index):
    return fetcher.steps[index].struct()


class TestLimeWireFetcherFactoryUrlParsing(unittest.TestCase):
    """Tests for URL detection and content-ID parsing (no network required)."""

    # ------------------------------------------------------------------
    # is_relevant_url
    # ------------------------------------------------------------------
    def test_valid_share_url(self):
        self.assertTrue(
            LimeWireFetcherFactory.is_relevant_url(
                "https://limewire.com/d/01HVVT4SC5NF0QA0TKMJAPNZE3"
            )
        )

    def test_valid_share_url_http(self):
        # HTTP share links should also be recognised
        self.assertTrue(
            LimeWireFetcherFactory.is_relevant_url(
                "http://limewire.com/d/ABCDEFGHIJ1234567890ABCDEF"
            )
        )

    def test_valid_share_url_with_query_string(self):
        self.assertTrue(
            LimeWireFetcherFactory.is_relevant_url(
                "https://limewire.com/d/01HVVT4SC5NF0QA0TKMJAPNZE3?utm_source=share"
            )
        )

    def test_invalid_url_wrong_domain(self):
        self.assertFalse(
            LimeWireFetcherFactory.is_relevant_url("https://example.com/d/ABCDEF1234")
        )

    def test_invalid_url_no_content_id(self):
        # Path has "/d/" but no content ID segment
        self.assertFalse(
            LimeWireFetcherFactory.is_relevant_url("https://limewire.com/d/")
        )

    def test_invalid_url_short_content_id(self):
        # Content ID that is too short (< 10 chars) should not match
        self.assertFalse(
            LimeWireFetcherFactory.is_relevant_url("https://limewire.com/d/abc")
        )

    def test_invalid_url_wrong_path_prefix(self):
        # /f/ instead of /d/
        self.assertFalse(
            LimeWireFetcherFactory.is_relevant_url(
                "https://limewire.com/f/01HVVT4SC5NF0QA0TKMJAPNZE3"
            )
        )

    def test_invalid_url_root_path(self):
        self.assertFalse(
            LimeWireFetcherFactory.is_relevant_url("https://limewire.com/")
        )

    def test_invalid_url_junk(self):
        self.assertFalse(LimeWireFetcherFactory.is_relevant_url("not-a-url"))

    # ------------------------------------------------------------------
    # Content-ID extraction
    # ------------------------------------------------------------------
    def test_parse_content_id(self):
        url = "https://limewire.com/d/01HVVT4SC5NF0QA0TKMJAPNZE3"
        self.assertEqual(
            LimeWireFetcherFactory._parse_content_id(url),
            "01HVVT4SC5NF0QA0TKMJAPNZE3",
        )

    def test_parse_content_id_query_params_ignored(self):
        url = "https://limewire.com/d/CONTENTID1234ABCD?ref=share&t=1234"
        self.assertEqual(
            LimeWireFetcherFactory._parse_content_id(url),
            "CONTENTID1234ABCD",
        )

    def test_constructor_stores_content_id(self):
        factory = LimeWireFetcherFactory(
            "https://limewire.com/d/01HVVT4SC5NF0QA0TKMJAPNZE3"
        )
        self.assertEqual(factory.content_id, "01HVVT4SC5NF0QA0TKMJAPNZE3")

    def test_constructor_raises_on_invalid_url(self):
        with self.assertRaises(ValueError):
            LimeWireFetcherFactory("https://example.com/some/path")

    def test_constructor_raises_on_junk(self):
        with self.assertRaises(ValueError):
            LimeWireFetcherFactory("@@@invalid@@@")


class TestLimeWireFetcherStepStructure(unittest.TestCase):
    """Tests for step layout and request parameters (no network required)."""

    _CONTENT_ID = "01HVVT4SC5NF0QA0TKMJAPNZE3"
    _URL = f"https://limewire.com/d/{_CONTENT_ID}"

    def _make_fetcher(self, mode=Mode.FETCH, api_key=None):
        return LimeWireFetcherFactory(self._URL, api_key=api_key).create(mode=mode)

    # ------------------------------------------------------------------
    # INFO mode
    # ------------------------------------------------------------------
    def test_info_mode_has_one_step(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        self.assertEqual(len(fetcher.steps), 1)

    def test_info_mode_step_name(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        step = _step_struct(fetcher, 0)
        self.assertEqual(step.name, "get content metadata")

    def test_info_mode_step_url(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        step = _step_struct(fetcher, 0)
        self.assertEqual(
            step.request.url,
            f"/api/v1/content/{self._CONTENT_ID}",
        )

    def test_info_mode_step_method_is_get(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        step = _step_struct(fetcher, 0)
        self.assertEqual(step.request.method, "GET")

    # ------------------------------------------------------------------
    # FETCH mode
    # ------------------------------------------------------------------
    def test_fetch_mode_has_two_steps(self):
        fetcher = self._make_fetcher(mode=Mode.FETCH)
        self.assertEqual(len(fetcher.steps), 2)

    def test_fetch_mode_first_step_is_metadata(self):
        fetcher = self._make_fetcher(mode=Mode.FETCH)
        step = _step_struct(fetcher, 0)
        self.assertEqual(step.name, "get content metadata")

    def test_fetch_mode_second_step_is_download(self):
        fetcher = self._make_fetcher(mode=Mode.FETCH)
        step = _step_struct(fetcher, 1)
        self.assertEqual(step.name, "download")

    # ------------------------------------------------------------------
    # FORCE_FETCH mode
    # ------------------------------------------------------------------
    def test_force_fetch_mode_has_two_steps(self):
        fetcher = self._make_fetcher(mode=Mode.FORCE_FETCH)
        self.assertEqual(len(fetcher.steps), 2)

    # ------------------------------------------------------------------
    # API key header injection
    # ------------------------------------------------------------------
    def test_no_api_key_omits_header(self):
        fetcher = self._make_fetcher(api_key=None)
        step = _step_struct(fetcher, 0)
        self.assertNotIn("X-Api-Key", step.request.headers)

    def test_api_key_injected_into_headers(self):
        fetcher = self._make_fetcher(api_key="my-secret-key")
        step = _step_struct(fetcher, 0)
        self.assertEqual(step.request.headers.get("X-Api-Key"), "my-secret-key")

    def test_accept_header_always_present(self):
        fetcher = self._make_fetcher()
        step = _step_struct(fetcher, 0)
        self.assertEqual(step.request.headers.get("Accept"), "application/json")

    # ------------------------------------------------------------------
    # extract_metadata helper (unit-test the logic directly)
    # ------------------------------------------------------------------
    def test_extract_metadata_standard_response(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)

        class FakeResponse:
            json = {
                "id": "01HVVT4SC5NF0QA0TKMJAPNZE3",
                "file_name": "hello.png",
                "content_type": "image/png",
                "size": 12345,
                "status": "COMPLETED",
                "asset_url": "https://cdn.limewire.com/hello.png",
                "created_at": "2024-01-01T00:00:00Z",
                "creator": {"id": "uid", "username": "alice"},
            }

        meta = fetcher.extract_metadata(FakeResponse())
        self.assertEqual(meta["filename"], "hello.png")
        self.assertEqual(meta["content_type"], "image/png")
        self.assertEqual(meta["size"], 12345)
        self.assertEqual(meta["asset_url"], "https://cdn.limewire.com/hello.png")
        self.assertEqual(meta["state"], "available")
        self.assertEqual(meta["creator"], "alice")

    def test_extract_metadata_wrapped_data_key(self):
        """API responses that nest payload under a 'data' key are handled."""
        fetcher = self._make_fetcher(mode=Mode.INFO)

        class FakeResponse:
            json = {
                "data": {
                    "id": "SOMEID12345678901234567890",
                    "name": "track.mp3",
                    "content_type": "audio/mpeg",
                    "size": 5000000,
                    "status": "COMPLETED",
                    "download_url": "https://cdn.limewire.com/track.mp3",
                }
            }

        meta = fetcher.extract_metadata(FakeResponse())
        self.assertEqual(meta["filename"], "track.mp3")
        self.assertEqual(meta["asset_url"], "https://cdn.limewire.com/track.mp3")

    def test_extract_metadata_incomplete_response_falls_back(self):
        """Missing optional fields fall back to safe defaults."""
        fetcher = self._make_fetcher(mode=Mode.INFO)

        class FakeResponse:
            json = {
                "id": "SOMEID12345678901234567890",
                "status": "COMPLETED",
                "url": "https://cdn.limewire.com/file.bin",
            }

        meta = fetcher.extract_metadata(FakeResponse())
        self.assertEqual(meta["filename"], f"limewire-{self._CONTENT_ID}")
        self.assertEqual(meta["asset_url"], "https://cdn.limewire.com/file.bin")
        self.assertEqual(meta["content_type"], "application/octet-stream")

    def test_extract_metadata_non_completed_status_is_unavailable(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)

        class FakeResponse:
            json = {
                "id": "SOMEID12345678901234567890",
                "status": "PROCESSING",
                "url": "https://cdn.limewire.com/file.bin",
            }

        meta = fetcher.extract_metadata(FakeResponse())
        self.assertEqual(meta["state"], "unavailable")

    def test_extract_direct_link_raises_when_missing(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        with self.assertRaises(ValueError):
            fetcher.extract_direct_link({"asset_url": None})

    def test_extract_direct_link_returns_asset_url(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        url = "https://cdn.limewire.com/hello.png"
        self.assertEqual(
            fetcher.extract_direct_link({"asset_url": url}),
            url,
        )

    def test_is_available_true_when_completed(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        self.assertTrue(fetcher.is_available({"state": "available"}))

    def test_is_available_false_when_processing(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        self.assertFalse(fetcher.is_available({"state": "unavailable"}))

    def test_default_downloads_count_is_one(self):
        fetcher = self._make_fetcher(mode=Mode.INFO)
        self.assertEqual(fetcher.default_downloads_count(), 1)

    # ------------------------------------------------------------------
    # Registry integration
    # ------------------------------------------------------------------
    def test_registry_detects_limewire_url(self):
        from fetchers.fetcher_registry import find_relevant_fetcher_factory

        factory_cls = find_relevant_fetcher_factory(self._URL)
        self.assertIsNotNone(factory_cls)
        self.assertIs(factory_cls, LimeWireFetcherFactory)

    def test_registry_does_not_detect_other_url(self):
        from fetchers.fetcher_registry import find_relevant_fetcher_factory

        factory_cls = find_relevant_fetcher_factory(
            "https://wetransfer.com/downloads/TID/SEC"
        )
        self.assertIsNotNone(factory_cls)
        self.assertIsNot(factory_cls, LimeWireFetcherFactory)
