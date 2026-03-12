import json
import os
import re
from typing import Dict
from urllib.parse import parse_qs, urlparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, format_size, format_timestamp, should_download
from httporchestrator.response import ResponseObject
from httporchestrator.step import Step
from httporchestrator.step_request import ConditionalStep, RunRequest

"""
NOTE: transfernow saves logs for each download and the IP they came from
Also the first download for each user sends a notification
"""


class TransferNowFetcherFactory:
    """
    has download notification: Yes
    has downloads count: Yes
    note: Also save source IP for each download
    """

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        try:
            cls._parse_link(url)
            return True
        except ValueError:
            return False

    def __init__(
        self,
        link: str,
        sender_secret: str | None = None,
        headers: Dict[str, str] | None = None,
    ):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid TransferNow URL provided")
        self.link = link
        self.sender_secret = sender_secret
        self.headers = headers or {}

        transfer_id, secret = self._parse_link(link)
        self.transfer_id = transfer_id
        self.secret = secret

    @staticmethod
    def _parse_link(link: str) -> tuple[str, str]:
        parsed = urlparse(link)
        host = (parsed.hostname or "").lower()
        is_transfernow_host = host == "transfernow.net" or host.endswith(".transfernow.net")

        if not is_transfernow_host:
            raise ValueError(f"Error: No valid TransferNow URL provided. Got: {link}")

        path_parts = [part for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query)

        # /dl/{transfer_id}/{secret}
        if len(path_parts) >= 3 and path_parts[-3] == "dl":
            return path_parts[-2], path_parts[-1]

        # /dl/{transfer_id}  (short link, no secret)
        if len(path_parts) == 2 and path_parts[-2] == "dl":
            return path_parts[-1], ""

        if path_parts and path_parts[-1] == "cld":
            transfer_id = query.get("utm_source", [None])[0]
            secret = query.get("utm_medium", [""])[0] or ""
            if transfer_id:
                return transfer_id, secret

        if len(path_parts) >= 2 and path_parts[-2:] == ["d", "start"]:
            transfer_id = query.get("utm_source", [None])[0]
            secret = query.get("utm_medium", [""])[0] or ""
            if transfer_id:
                return transfer_id, secret

        raise ValueError("Error: Unable to parse TransferNow URL")

    def create(self, mode: Mode = Mode.FETCH, **kwargs) -> BaseFetcher:
        transfer_id = self.transfer_id
        secret = self.secret
        sender_secret = self.sender_secret

        class TransferNowFetcher(BaseFetcher):
            NAME = "TransferNow"
            BASE_URL = "https://www.transfernow.net"

            def log_fetch_state(
                self,
                metadata: dict,
                downloads_count=None,
                views_count=None,
                filename=None,
                primary_file=None,
                download_events=None,
            ):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": filename or (primary_file or {}).get("name"),
                            "downloads_count": downloads_count,
                            "views_count": views_count,
                            "uploader_email": (metadata.get("owner") or {}).get("email")
                            or (metadata.get("sender") or {}).get("email"),
                            "upload_date": format_timestamp((metadata.get("validity") or {}).get("from")),
                            "expires_at": format_timestamp((metadata.get("validity") or {}).get("to")),
                            "size": format_size(metadata.get("size") or (primary_file or {}).get("size")),
                        },
                        "details": {
                            "metadata": metadata,
                            "primary_file": primary_file,
                            "download_events": download_events,
                        },
                    },
                )

            def default_downloads_count(self) -> int | None:
                return None

            def extract_next_data(self, response: ResponseObject) -> dict:
                content = response.body.decode("utf-8")
                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
                    content,
                    re.DOTALL,
                )
                if not match:
                    raise ValueError("Error: TransferNow metadata payload not found")
                return json.loads(match.group(1))

            def extract_transfer_data(self, response: ResponseObject) -> dict | None:
                payload = self.extract_next_data(response)
                page_props = payload.get("props", {}).get("pageProps", {})
                return page_props.get("transferData")

            def extract_metadata(self, response: ResponseObject) -> dict | None:
                transfer_data = self.extract_transfer_data(response)
                if not transfer_data:
                    return None
                return transfer_data.get("metadata")

            def is_available(self, response: ResponseObject) -> bool:
                transfer_data = self.extract_transfer_data(response)
                if not transfer_data:
                    return False
                metadata = transfer_data.get("metadata", {})
                return (
                    transfer_data.get("available") is True
                    and transfer_data.get("locked") is False
                    and transfer_data.get("shouldBuy") is False
                    and metadata.get("status") == "ENABLED"
                )

            def extract_primary_file(self, response: ResponseObject) -> dict | None:
                metadata = self.extract_metadata(response)
                if not metadata:
                    return None
                files = metadata.get("files") or []
                if not files:
                    raise ValueError("Error: TransferNow files metadata not found")
                return files[0]

            def extract_download_start_path(self, response: ResponseObject) -> str:
                file_data = self.extract_primary_file(response)
                file_id = file_data.get("id")
                if not file_id:
                    raise ValueError("Error: TransferNow file id not found")
                return f"/d/start?utm_source={transfer_id}" f"&utm_medium={secret}&utm_term={file_id}"

            def extract_filename(self, file_data: dict) -> str:
                return file_data.get("name") or f"{transfer_id}.bin"

            def extract_file_id(self, file_data: dict) -> str:
                file_id = file_data.get("id")
                if not file_id:
                    raise ValueError("Error: TransferNow file id not found")
                return file_id

            def extract_stats_downloads_count(self, response: ResponseObject) -> int:
                return response.json.get("downloadsCount") or 0

            def extract_stats_views_count(self, response: ResponseObject) -> int:
                return response.json.get("viewsCount") or 0

            def extract_download_events(self, response: ResponseObject) -> list:
                return response.json.get("downloadEvents") or []

            info_steps = [
                Step(
                    RunRequest("load transfer page")
                    .get(f"/en/cld?utm_source={transfer_id}" + (f"&utm_medium={secret}" if secret else ""))
                    .headers(**self.headers)
                    .teardown_callback("default_downloads_count()", assign="downloads_count")
                    .teardown_callback("extract_metadata(response)", assign="metadata")
                    .teardown_callback("extract_primary_file(response)", assign="primary_file")
                    .teardown_callback("extract_file_id(primary_file)", assign="file_id")
                    .teardown_callback("extract_filename(primary_file)", assign="filename")
                    .teardown_callback("extract_download_start_path(response)", assign="download_start_path")
                    .teardown_callback("is_available(response)", assign="available")
                    .teardown_callback("log_fetch_state(metadata, downloads_count, None, filename, primary_file, None)")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("available", True)
                )
            ]

            if sender_secret:
                info_steps.append(
                    Step(
                        RunRequest("load transfer stats")
                        .get(f"/api/transfer/v2/transfers/{transfer_id}")
                        .headers(**self.headers)
                        .params(senderSecret=sender_secret)
                        .teardown_callback("extract_stats_downloads_count(response)", assign="downloads_count")
                        .teardown_callback("extract_stats_views_count(response)", assign="views_count")
                        .teardown_callback("extract_download_events(response)", assign="download_events")
                        .teardown_callback(
                            "log_fetch_state(metadata, downloads_count, views_count, filename, primary_file, download_events)"
                        )
                        .validate()
                        .assert_equal("status_code", 200)
                    )
                )

            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    ConditionalStep(
                        RunRequest("create direct link")
                        .get("/api/transfer/downloads/link")
                        .headers(**self.headers)
                        .params(
                            transferId=transfer_id,
                            userSecret=secret,
                            fileId="$file_id",
                        )
                        .teardown_callback("response.body['url']", assign="direct_link")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda vars: should_download(mode, vars.get("downloads_count"))),
                    ConditionalStep(
                        RunRequest("download")
                        .get("$direct_link")
                        .headers(**self.headers)
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda vars: should_download(mode, vars.get("downloads_count"))),
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return TransferNowFetcher(**kwargs)
