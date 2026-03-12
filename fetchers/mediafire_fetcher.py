import re
from typing import Dict

from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class MediaFireFetcherFactory:
    """
    has download notification: No
    has downloads count: Yes
    note: Downloads count can be bypassed by copying the file into our user account
    """

    def __init__(
        self,
        link: str,
        headers: Dict[str, str] | None = None,
        email: str = "",
        password: str = "",
        app_id: str = "42511",
    ):
        self.link = link
        self.headers = headers or {}
        result = re.search(r"mediafire\.com\/file\/(\w+)\/", self.link)
        if result is not None and len(result.groups()) > 0:
            self.file_key = result.group(1)
        elif "mediafire.com" not in self.link:
            raise ValueError("Error: No valid MediaFire URL provided")
        else:
            raise ValueError("Error: No valid MediaFire URL provided")

        self.email = email.strip()
        self.password = password.strip()
        self.app_id = app_id.strip()
        self.has_credentials = bool(self.email and self.password)

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        """
        mode: Mode.INFO (only info_steps), Mode.FETCH (full fetch_steps)

        If email and password are provided, the fetcher will log in, copy the
        file to the authenticated user's account, and then download from the
        user's own copy. This bypasses the public download counter.
        """
        file_key = self.file_key
        has_credentials = self.has_credentials
        email = self.email
        password = self.password
        app_id = self.app_id

        class MediaFireFetcher(BaseFetcher):
            NAME = "MediaFire"
            BASE_URL = "https://mediafire.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": metadata.get("filename"),
                            "downloads_count": downloads_count,
                            "views_count": metadata.get("views") or metadata.get("view"),
                            "upload_date": metadata.get("created"),
                            "size": metadata.get("size"),
                            "auth_mode": "user_copy" if has_credentials else "public",
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_metadata(self, response: ResponseObject) -> dict:
                return response.json["response"]["file_info"]

            def default_downloads_count(self) -> int:
                return 1

            def extract_direct_download_link(self, response: ResponseObject) -> str:
                for line in response.body.decode("utf-8").splitlines():
                    m = re.search(r'href="((http|https)://download[^\"]+)', line)
                    if m:
                        direct_download_link = m.groups()[0]
                        return direct_download_link
                raise ValueError("Error: No valid direct download link found")

            def extract_session_token(self, response: ResponseObject) -> str:
                token = response.json.get("response", {}).get("session_token")
                if not token:
                    raise ValueError("Error: MediaFire login failed - no session token")
                logger.info("[MediaFire] authenticated session obtained")
                return token

            def extract_copy_quick_key(self, response: ResponseObject) -> str:
                new_keys = response.json.get("response", {}).get("new_key") or []
                if isinstance(new_keys, list) and new_keys:
                    return new_keys[0]
                if isinstance(new_keys, str):
                    return new_keys
                raise ValueError("Error: MediaFire file copy failed - no new quick_key")

            def extract_copy_direct_link(self, response: ResponseObject) -> str:
                links = response.json.get("response", {}).get("links") or []
                if links:
                    return links[0].get("direct_download") or links[0].get("normal_download")
                return response.json.get("response", {}).get("link", "")

            info_steps = [
                Step(
                    RunRequest("info")
                    .post("/api/1.5/file/get_info.php")
                    .with_headers(**self.headers)
                    .with_params(
                        **{
                            "recursive": "yes",
                            "quick_key": self.file_key,
                            "response_format": "json",
                        }
                    )
                    .teardown_hook("${extract_metadata($response)}", "metadata")
                    .teardown_hook("${default_downloads_count()}", "downloads_count")
                    .teardown_hook("${log_fetch_state($metadata, $downloads_count)}")
                    .extract()
                    .with_jmespath("$metadata", "metadata")
                    .with_jmespath("body.response.file_info.filename", "filename")
                    .with_jmespath("$downloads_count", "downloads_count")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("body.response.file_info.password_protected", "no")
                    .assert_equal("body.response.file_info.permissions.read", "1")
                    .assert_equal("body.response.result", "Success")
                ),
            ]

            # Authenticated flow: login → copy file → get link for copy → download
            auth_fetch_steps = info_steps.copy()
            auth_fetch_steps.extend(
                [
                    OptionalStep(
                        RunRequest("login")
                        .post("/api/1.5/user/get_session_token.php")
                        .with_headers(**self.headers)
                        .with_params(
                            **{
                                "email": email,
                                "password": password,
                                "application_id": app_id,
                                "token_version": "2",
                                "response_format": "json",
                            }
                        )
                        .teardown_hook("${extract_session_token($response)}", "session_token")
                        .extract()
                        .with_jmespath("$session_token", "session_token")
                        .validate()
                        .assert_equal("status_code", 200)
                        .assert_equal("body.response.result", "Success")
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                    OptionalStep(
                        RunRequest("copy file to user account")
                        .post("/api/1.5/file/copy.php")
                        .with_headers(**self.headers)
                        .with_params(
                            **{
                                "session_token": "$session_token",
                                "quick_key": file_key,
                                "folder_key": "myfiles",
                                "response_format": "json",
                            }
                        )
                        .teardown_hook("${extract_copy_quick_key($response)}", "copy_quick_key")
                        .extract()
                        .with_jmespath("$copy_quick_key", "copy_quick_key")
                        .validate()
                        .assert_equal("status_code", 200)
                        .assert_equal("body.response.result", "Success")
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                    OptionalStep(
                        RunRequest("get copy direct link")
                        .post("/api/1.5/file/get_links.php")
                        .with_headers(**self.headers)
                        .with_params(
                            **{
                                "session_token": "$session_token",
                                "quick_key": "$copy_quick_key",
                                "link_type": "direct_download",
                                "response_format": "json",
                            }
                        )
                        .teardown_hook(
                            "${extract_copy_direct_link($response)}",
                            "direct_download_link",
                        )
                        .extract()
                        .with_jmespath("$direct_download_link", "direct_download_link")
                        .validate()
                        .assert_equal("status_code", 200)
                        .assert_equal("body.response.result", "Success")
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                    OptionalStep(
                        RunRequest("download (user copy)")
                        .get("$direct_download_link")
                        .with_headers(**self.headers)
                        .teardown_hook("${save_file($response, $filename)}")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                ]
            )

            # Public flow (original): scrape direct link → download
            public_fetch_steps = info_steps.copy()
            public_fetch_steps.extend(
                [
                    OptionalStep(
                        RunRequest("get direct link")
                        .get("/file/{}".format(self.file_key))
                        .with_headers(**self.headers)
                        .teardown_hook(
                            "${extract_direct_download_link($response)}",
                            "direct_download_link",
                        )
                        .extract()
                        .with_jmespath("$direct_download_link", "direct_download_link")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                    OptionalStep(
                        RunRequest("download link")
                        .get("$direct_download_link")
                        .with_headers(**self.headers)
                        .teardown_hook("${save_file($response, $filename)}")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                ]
            )

            if mode == Mode.INFO:
                teststeps = info_steps
            elif has_credentials:
                teststeps = auth_fetch_steps
            else:
                teststeps = public_fetch_steps

        return MediaFireFetcher()
