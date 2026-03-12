import json
import os

from loguru import logger

from fetchers.utils import resolve_filename
from httporchestrator import Config, HttpRunner


class BaseFetcher(HttpRunner):
    NAME = None
    BASE_URL = None

    def log_json(self, label: str, payload: dict):
        logger.info(
            "[{}] {}\n{}",
            self.NAME,
            label,
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    def transform_body(self, body: bytes) -> bytes:
        return body

    def save_file(self, response: object, fallback_filename: str) -> str:
        if response.status_code != 200:
            logger.warning(
                "[{}] download failed with HTTP {} — skipping save",
                self.NAME,
                response.status_code,
            )
            return ""

        resolved_name = os.path.basename(resolve_filename(response.headers, fallback_filename))
        payload = self.transform_body(response.body)

        path = os.path.join(os.getcwd(), resolved_name)
        with open(path, "wb") as file_handle:
            file_handle.write(payload)

        logger.success(
            "[{}] downloaded file saved to {} ({} bytes)",
            self.NAME,
            path,
            len(payload),
        )
        return path

    def __init__(self, log_details: bool = False):
        super().__init__()
        self.config = Config(name=self.NAME)
        self.config.base_url(self.BASE_URL)
        self.config.add_request_id(False)
        self.config.log_details(log_details)
