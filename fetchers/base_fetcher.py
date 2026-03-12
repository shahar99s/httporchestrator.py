import json
import os
from urllib.parse import unquote

from loguru import logger

from httprunner import Config, HttpRunner
from httprunner.parser import Parser


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

    def save_file(self, response: object, fallback_filename: str) -> str:
        disposition = response.headers.get("Content-Disposition", "")
        resolved_name = fallback_filename
        if disposition:
            for item in disposition.split(";"):
                part = item.strip()
                if part.startswith("filename*="):
                    encoded_name = part.split("=", 1)[1].strip('"')
                    if "''" in encoded_name:
                        encoded_name = encoded_name.split("''", 1)[1]
                    resolved_name = unquote(encoded_name)
                    break
                if part.startswith("filename="):
                    resolved_name = unquote(part.split("=", 1)[1].strip('"'))

        resolved_name = os.path.basename(resolved_name)

        path = os.path.join(os.getcwd(), resolved_name)
        with open(path, "wb") as file_handle:
            file_handle.write(response.body)

        logger.success(
            "[{}] downloaded file saved to {} ({} bytes)",
            self.NAME,
            path,
            len(response.body),
        )
        return path

    def _init_parser_functions(self):
        # Automatically grab required functions from the subclass
        parser_functions = {}
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and not attr_name.startswith("__") and attr_name not in dir(HttpRunner):
                parser_functions[attr_name] = attr
        if parser_functions:
            self.parser = Parser(parser_functions)

    def __init__(self, parser_functions=None):
        super().__init__()
        self.config = Config(name=self.NAME)
        self.config.base_url(self.BASE_URL)
        self.config.add_request_id(False)
        self.parser_functions = parser_functions
        if not self.parser_functions:
            self._init_parser_functions()
        # Ensure teststeps is set if present in subclass
        if hasattr(self, "teststeps"):
            self.teststeps = getattr(self, "teststeps")
