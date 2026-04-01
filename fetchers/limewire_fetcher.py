import re
from typing import Dict
from urllib.parse import urlparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class LimeWireFetcherFactory:
    """
    has download notification: Yes (creators are notified on each download)
    has downloads count: No (not exposed publicly without authentication)
    note: Requires an optional API key (X-Api-Key) for private/paid content.
          Public content is accessible without authentication.
          Share URL format: https://limewire.com/d/{content_id}
    """

    # Content IDs are ULID-style: 26 uppercase alphanumeric characters
    CONTENT_ID_PATTERN = re.compile(r"^[0-9A-Za-z]{10,}$")

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        if "limewire.com" not in parsed.netloc:
            return False
        path_parts = [p for p in parsed.path.split("/") if p]
        # Accepts: /d/{content_id}
        if len(path_parts) >= 2 and path_parts[0] == "d":
            return bool(cls.CONTENT_ID_PATTERN.match(path_parts[1]))
        return False

    @staticmethod
    def _parse_content_id(url: str) -> str:
        """Extract the content ID from a LimeWire share URL."""
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2 and path_parts[0] == "d":
            return path_parts[1]
        raise ValueError(f"Error: Unable to parse LimeWire content ID from URL: {url}")

    def __init__(
        self,
        link: str,
        api_key: str | None = None,
        headers: Dict[str, str] | None = None,
    ):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid LimeWire URL provided")
        self.link = link
        self.api_key = api_key
        self.headers = headers or {}
        self.content_id = self._parse_content_id(link)

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        content_id = self.content_id
        api_key = self.api_key
        link = self.link
        request_headers = {
            **self.headers,
            "Accept": "application/json",
            **({"X-Api-Key": api_key} if api_key else {}),
        }

        class LimeWireFetcher(BaseFetcher):
            NAME = "LimeWire"
            BASE_URL = "https://api.limewire.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "content_id": content_id,
                            "filename": metadata.get("filename"),
                            "content_type": metadata.get("content_type"),
                            "size": metadata.get("size"),
                            "status": metadata.get("status"),
                            "creator": metadata.get("creator"),
                            "downloads_count": downloads_count,
                            "state": metadata.get("state"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def default_downloads_count(self) -> int:
                # LimeWire does not expose a public download counter; default
                # to 1 so should_download() proceeds normally in FETCH mode.
                return 1

            def extract_metadata(self, response: ResponseObject) -> dict:
                data = response.json or {}
                # The API may wrap the payload under a "data" key
                if "data" in data and isinstance(data["data"], dict):
                    data = data["data"]

                # Derive the download URL from common field names
                asset_url = (
                    data.get("asset_url")
                    or data.get("download_url")
                    or data.get("url")
                    or data.get("file_url")
                )

                filename = (
                    data.get("file_name")
                    or data.get("filename")
                    or data.get("name")
                    or f"limewire-{content_id}"
                )
                # Strip any path prefix that may come from the API
                if "/" in filename:
                    filename = filename.rsplit("/", 1)[-1]

                content_type = (
                    data.get("content_type")
                    or data.get("mime_type")
                    or data.get("type")
                    or "application/octet-stream"
                )

                status = data.get("status", "UNKNOWN")

                return {
                    "id": data.get("id", content_id),
                    "filename": filename,
                    "content_type": content_type,
                    "size": data.get("size"),
                    "status": status,
                    "creator": (data.get("creator") or {}).get("username"),
                    "created_at": data.get("created_at"),
                    "asset_url": asset_url,
                    "state": "available" if status == "COMPLETED" else "unavailable",
                    "url": link,
                }

            def extract_filename(self, metadata: dict) -> str:
                return metadata.get("filename") or f"limewire-{content_id}"

            def extract_direct_link(self, metadata: dict) -> str:
                asset_url = metadata.get("asset_url")
                if not asset_url:
                    raise ValueError(
                        "Error: LimeWire metadata did not include a download URL"
                    )
                return asset_url

            def is_available(self, metadata: dict) -> bool:
                return metadata.get("state") == "available"

            info_steps = [
                Step(
                    RunRequest("get content metadata")
                    .get(f"/api/v1/content/{content_id}")
                    .headers(**request_headers)
                    .teardown_callback("extract_metadata(response)", assign="metadata")
                    .teardown_callback("extract_filename(metadata)", assign="filename")
                    .teardown_callback("extract_direct_link(metadata)", assign="direct_link")
                    .teardown_callback("default_downloads_count()", assign="downloads_count")
                    .teardown_callback("is_available(metadata)", assign="available")
                    .teardown_callback("log_fetch_state(metadata, downloads_count)")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("available", True)
                )
            ]

            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    OptionalStep(
                        RunRequest("download")
                        .get("$direct_link")
                        .headers(**self.headers)
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(
                        lambda step, vars: (
                            vars.get("available") is True
                            and should_download(mode, vars.get("downloads_count"))
                        )
                    )
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return LimeWireFetcher()
