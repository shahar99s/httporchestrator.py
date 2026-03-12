import json
import os
import re
from http.cookies import SimpleCookie
from typing import Dict
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, format_size, format_timestamp
from httporchestrator import RunRequest
from httporchestrator.response import ResponseObject
from httporchestrator.step_request import ConditionalStep


class TeraBoxFetcherFactory:
    """
    has download notification: No
    has downloads count: No
    """

    VALID_HOSTS = {
        "www.terabox.com",
        "terabox.com",
        "1024terabox.com",
        "www.terabox.app",
        "terabox.app",
        "1024tera.com",
    }

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc in cls.VALID_HOSTS and parsed.path.startswith("/s/")

    def __init__(
        self,
        link: str,
        headers: Dict[str, str] | None = None,
        cookie: str | None = None,
        ndus: str | None = None,
        login_email: str | None = None,
        login_password: str | None = None,
        gateway_url: str | None = None,
        gateway_api2_url: str | None = None,
        worker_url: str | None = None,
    ):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid TeraBox URL provided")
        self.link = link
        self.headers = headers or {}
        self.cookie = (cookie or "").strip()
        self.ndus = (ndus or "").strip()
        self.login_email = (login_email or "").strip()
        self.login_password = (login_password or "").strip()
        self.gateway_url = (gateway_url or "").strip()
        self.gateway_api2_url = (gateway_api2_url or "").strip()
        self.worker_url = (worker_url or "").strip()

        parsed = urlparse(link)

        self.shorturl = parsed.path.split("/s/")[1].rstrip("/")
        self.surl = self.shorturl[1:] if self.shorturl.startswith("1") else self.shorturl

    def create(self, mode: Mode = Mode.FETCH, **kwargs) -> BaseFetcher:
        surl = self.surl
        shorturl = self.shorturl
        link = self.link
        request_headers = dict(self.headers)
        auth_cookie = (request_headers.get("Cookie") or self.cookie).strip()
        if not auth_cookie:
            ndus = self.ndus.strip()
            if ndus:
                auth_cookie = f"ndus={ndus}"
        if auth_cookie:
            request_headers["Cookie"] = auth_cookie

        login_email = self.login_email.strip()
        login_password = self.login_password.strip()
        gateway_api2_url = self.gateway_api2_url.strip()
        gateway_url = self.gateway_url.strip()
        worker_url = self.worker_url.strip()
        raw_gateway_url = (gateway_api2_url or gateway_url or worker_url).strip()
        proxy_mode = "disabled"
        proxy_request_url = ""
        if raw_gateway_url:
            normalized_gateway_url = raw_gateway_url.rstrip("/")
            if gateway_api2_url:
                proxy_mode = "api2"
                proxy_request_url = normalized_gateway_url
            elif "workers.dev" in normalized_gateway_url or worker_url:
                proxy_mode = "worker"
                proxy_request_url = normalized_gateway_url or raw_gateway_url
            else:
                proxy_mode = "api2"
                proxy_request_url = (
                    normalized_gateway_url
                    if normalized_gateway_url.endswith("/api2")
                    else f"{normalized_gateway_url}/api2"
                )
        share_page_path = f"/sharing/link?surl={surl}"
        sharedownload_headers = dict(request_headers)
        sharedownload_headers.setdefault("Referer", f"https://www.1024tera.com{share_page_path}")
        download_headers = dict(request_headers)
        download_headers.setdefault("Referer", f"https://www.1024tera.com{share_page_path}")
        proxy_headers = dict(request_headers)
        proxy_headers.setdefault("Accept", "application/json")

        class TeraBoxFetcher(BaseFetcher):
            NAME = "TeraBox"
            BASE_URL = "https://www.1024tera.com"

            def __init__(self, **kwargs):
                super().__init__(**kwargs)

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": metadata.get("filename"),
                            "downloads_count": downloads_count,
                            "size": format_size(metadata.get("size")),
                            "md5": metadata.get("md5"),
                            "upload_date": format_timestamp(metadata.get("upload_date")),
                            "share_username": metadata.get("share_username"),
                            "share_id": metadata.get("share_id"),
                            "country": metadata.get("country"),
                            "state": metadata.get("state"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_js_token(self, response: ResponseObject) -> str:
                body = response.text
                patterns = [
                    r'window\.jsToken\s*=\s*"([^"]+)"',
                    r"window\.jsToken\s*=\s*'([^']+)'",
                    r"fn%28%22([A-F0-9]+)%22%29",
                    r"jsToken%22%3A%22([A-Fa-f0-9]+)%22",
                    r'"jsToken"\s*:\s*"([^"]+)"',
                ]
                for pattern in patterns:
                    match = re.search(pattern, body)
                    if match:
                        return match.group(1)
                raise ValueError("Error: TeraBox jsToken not found on share page")

            def extract_cookies_from_response(self, response: ResponseObject) -> str:
                """Extract auth cookies (especially ndus) from Set-Cookie response headers."""
                cookie_jar: dict[str, str] = {}
                # Use multi_items() to properly handle multiple Set-Cookie headers
                # without breaking on commas inside date strings.
                try:
                    raw_items = response.headers.multi_items()
                except AttributeError:
                    raw_items = []
                set_cookie_values = [v for k, v in raw_items if k.lower() == "set-cookie"]
                if not set_cookie_values:
                    # Fallback: try .get() for non-httpx responses
                    single = response.headers.get("Set-Cookie", "")
                    if single:
                        set_cookie_values = [single]
                for line in set_cookie_values:
                    sc = SimpleCookie()
                    try:
                        sc.load(line.strip())
                    except Exception:
                        continue
                    for key, morsel in sc.items():
                        if morsel.value:
                            cookie_jar[key] = morsel.value
                if cookie_jar:
                    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_jar.items())
                    logger.info("[TeraBox] extracted cookies from response: {}", list(cookie_jar.keys()))
                    return cookie_str
                return ""

            def parse_cookie_header(self, cookie_header: str) -> dict[str, str]:
                cookie_map: dict[str, str] = {}
                if not cookie_header:
                    return cookie_map
                for pair in cookie_header.split(";"):
                    part = pair.strip()
                    if "=" not in part:
                        continue
                    key, value = part.split("=", 1)
                    cookie_map[key.strip()] = value.strip()
                return cookie_map

            def has_ndus_cookie(self, cookie_header: str) -> bool:
                return bool(self.parse_cookie_header(cookie_header).get("ndus"))

            def merge_cookies(self, existing_cookie: str, new_cookies: str) -> str:
                """Merge new cookies into existing cookie header, preferring new values."""
                if not new_cookies:
                    return existing_cookie
                if not existing_cookie:
                    return new_cookies
                merged: dict[str, str] = {}
                for pair in existing_cookie.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        merged[k.strip()] = v.strip()
                for pair in new_cookies.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        merged[k.strip()] = v.strip()
                return "; ".join(f"{k}={v}" for k, v in merged.items())

            def update_cookie_headers(self, merged_cookie: str):
                for headers_dict in (request_headers, sharedownload_headers, download_headers, proxy_headers):
                    headers_dict["Cookie"] = merged_cookie

            def _load_cached_ndus(self) -> bool:
                """Load ndus cookie from cache file if available."""
                cache_path = os.path.join(os.getcwd(), ".terabox_cookies.json")
                if not os.path.exists(cache_path):
                    return False
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    cached_ndus = cached.get("ndus", "")
                    if cached_ndus and cached.get("email") == login_email:
                        current = request_headers.get("Cookie", "")
                        self.update_cookie_headers(self.merge_cookies(current, f"ndus={cached_ndus}"))
                        logger.info("[TeraBox] restored ndus cookie from cache")
                        return True
                except Exception:
                    pass
                return False

            def _cache_ndus(self, ndus: str):
                """Cache ndus cookie for future runs."""
                try:
                    path = os.path.join(os.getcwd(), ".terabox_cookies.json")
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump({"ndus": ndus, "email": login_email}, f)
                except Exception:
                    pass

            def auto_login_and_set_cookie(self):
                """Login via Playwright headless browser to obtain ndus cookie."""
                if not (login_email and login_password):
                    return

                logger.info("[TeraBox] attempting headless browser login for {}", login_email)

                try:
                    from playwright.sync_api import sync_playwright
                except ImportError:
                    raise ValueError(
                        "Error: Playwright is required for TeraBox login. "
                        "Install with: pip install playwright && python -m playwright install chromium"
                    )

                current_cookie = request_headers.get("Cookie", "")
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        page.set_default_timeout(60000)

                        page.goto(f"{self.BASE_URL}/login", wait_until="domcontentloaded")
                        page.wait_for_selector('input[type="password"]', state="visible", timeout=30000)
                        page.wait_for_timeout(1000)

                        page.fill('input[type="text"], input[type="email"]', login_email)
                        page.fill('input[type="password"]', login_password)
                        page.wait_for_timeout(500)

                        submit_btn = page.wait_for_selector('div[class*="submit"]', state="visible", timeout=5000)
                        if not submit_btn:
                            raise ValueError("Error: TeraBox login submit button not found")

                        submit_btn.click()
                        page.wait_for_timeout(8000)

                        # Check for rate-limit notification
                        notification = page.query_selector('div.notification, div[class*="Notification"]')
                        if notification:
                            text = notification.inner_text()
                            if "too many times" in text.lower() or "wrong password" in text.lower():
                                raise ValueError(
                                    f"Error: TeraBox account locked: {text.strip()}. "
                                    "Wait 24 minutes before retrying."
                                )

                        cookies = browser.contexts[0].cookies()
                        browser_cookie = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                        merged = self.merge_cookies(current_cookie, browser_cookie)
                        ndus = self.parse_cookie_header(merged).get("ndus")

                        if ndus:
                            self.update_cookie_headers(merged)
                            logger.success("[TeraBox] login succeeded, ndus cookie captured")
                            self._cache_ndus(ndus)
                        else:
                            try:
                                page.screenshot(path=os.path.join(os.getcwd(), "terabox_login_debug.png"))
                            except Exception:
                                pass
                            raise ValueError(
                                "Error: TeraBox login did not produce ndus cookie. "
                                "The account may need verification or a captcha was required."
                            )
                    finally:
                        browser.close()

            def bootstrap_session_cookies(self):
                """Bootstrap session cookies by visiting the TeraBox share page programmatically."""
                current_cookie = request_headers.get("Cookie", "")
                base_headers = {k: v for k, v in request_headers.items() if k.lower() != "cookie"}
                base_headers.setdefault(
                    "Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
                )
                base_headers.setdefault("Accept-Language", "en-US,en;q=0.9")

                with httpx.Client(
                    base_url=self.BASE_URL,
                    headers=base_headers,
                    follow_redirects=True,
                    timeout=20.0,
                ) as client:
                    # Visit the share page — TeraBox sets session cookies
                    # (csrfToken, browserid, lang, __bid_n, ndus, etc.)
                    client.get(f"/sharing/link?surl={surl}")
                    session_cookies = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
                    if session_cookies:
                        merged = self.merge_cookies(current_cookie, session_cookies)
                        self.update_cookie_headers(merged)
                        logger.info(
                            "[TeraBox] bootstrapped session cookies: {}",
                            [name for name, _ in client.cookies.items()],
                        )
                        return merged
                return current_cookie

            def ensure_auth_cookie(self):
                if self.has_ndus_cookie(request_headers.get("Cookie", "")):
                    return request_headers.get("Cookie", "")

                # Try cached cookie from previous login
                if self._load_cached_ndus():
                    return request_headers.get("Cookie", "")

                # Bootstrap session cookies from TeraBox share page
                try:
                    self.bootstrap_session_cookies()
                except Exception as exc:
                    logger.warning("[TeraBox] session cookie bootstrap failed: {}", exc)

                if self.has_ndus_cookie(request_headers.get("Cookie", "")):
                    return request_headers.get("Cookie", "")

                # Try Playwright login if credentials were provided
                if login_email and login_password:
                    try:
                        self.auto_login_and_set_cookie()
                    except Exception as exc:
                        logger.warning("[TeraBox] login auth failed: {}", exc)

                return request_headers.get("Cookie", "")

            def apply_extracted_cookies(self, response: ResponseObject) -> str:
                """Extract cookies from the share page and update request headers for subsequent calls."""
                new_cookies = self.extract_cookies_from_response(response)
                if new_cookies:
                    merged = self.merge_cookies(request_headers.get("Cookie", ""), new_cookies)
                    self.update_cookie_headers(merged)
                    return merged
                return request_headers.get("Cookie", "")

            def extract_file_list(self, response: ResponseObject) -> list:
                data = response.json
                if data.get("errno") != 0:
                    raise ValueError(f"TeraBox API error: errno={data.get('errno')}, msg={data.get('errmsg')}")
                return data.get("list") or []

            def extract_metadata(self, response: ResponseObject, file_list: list) -> dict:
                if not file_list:
                    return {
                        "filename": None,
                        "size": None,
                        "size_bytes": None,
                        "state": "empty",
                    }

                primary = file_list[0]
                data = response.json or {}
                upload_ts = int(primary.get("server_ctime") or 0)
                share_ts = int(data.get("ctime") or 0)
                size_bytes = int(primary.get("size") or 0)
                return {
                    "filename": primary.get("server_filename"),
                    "size": format_size(size_bytes),
                    "size_bytes": size_bytes,
                    "md5": primary.get("md5"),
                    "fs_id": primary.get("fs_id"),
                    "category": primary.get("category"),
                    "is_dir": primary.get("isdir") == "1",
                    "upload_date": format_timestamp(upload_ts * 1000 if upload_ts else None),
                    "file_count": len(file_list),
                    "title": primary.get("server_filename") or data.get("title", "").strip("/"),
                    "country": data.get("country"),
                    "share_username": data.get("share_username"),
                    "share_id": data.get("shareid"),
                    "uk": data.get("uk"),
                    "uk_str": data.get("uk_str"),
                    "head_url": data.get("head_url"),
                    "share_ctime": format_timestamp(share_ts * 1000 if share_ts else None),
                    "expired_type": data.get("expiredtype"),
                    "fcount": data.get("fcount"),
                    "sign": data.get("sign"),
                    "randsk": data.get("randsk"),
                    "download_timestamp": int(data.get("timestamp") or 0),
                    "thumbs": primary.get("thumbs") or {},
                    "cookie_auth": self.has_ndus_cookie(request_headers.get("Cookie", "")),
                    "state": "available",
                    "url": link,
                }

            def extract_filename(self, metadata: dict) -> str:
                return metadata.get("filename") or f"terabox-{surl}.bin"

            def is_proxy_gateway_configured(self) -> bool:
                return bool(proxy_request_url)

            def default_downloads_count(self) -> int | None:
                # TeraBox API does not expose a download counter
                return None

            def is_available(self, file_list: list) -> bool:
                return len(file_list) > 0

            def get_download_sign(self, metadata: dict) -> str:
                return metadata.get("sign") or ""

            def get_download_timestamp(self, metadata: dict) -> int:
                return int(metadata.get("download_timestamp") or 0)

            def get_share_id(self, metadata: dict) -> int:
                return int(metadata.get("share_id") or 0)

            def get_share_uk(self, metadata: dict) -> int:
                return int(metadata.get("uk") or 0)

            def build_fid_list(self, metadata: dict) -> str:
                fs_id = metadata.get("fs_id")
                return json.dumps([int(fs_id)]) if fs_id else "[]"

            def build_download_extra(self, metadata: dict) -> str:
                return json.dumps({"sekey": unquote(metadata.get("randsk") or "")}, separators=(",", ":"))

            def extract_sharedownload_item(self, response: ResponseObject) -> dict:
                data = response.json or {}
                items = data.get("list") or []
                item = items[0] if items else {}
                return {
                    "errno": data.get("errno"),
                    "errmsg": data.get("errmsg"),
                    "server_time": int(data.get("server_time") or 0),
                    "request_id": data.get("request_id"),
                    "dlink": item.get("dlink"),
                    "item": item,
                }

            def extract_proxy_result(self, response: ResponseObject) -> dict:
                payload = response.json if isinstance(response.json, dict) else {}
                files = payload.get("files") or []
                item = files[0] if files else {}
                direct_link = (
                    item.get("direct_link") or item.get("download_link") or item.get("link") or item.get("dlink")
                )
                return {
                    "status_code": response.status_code,
                    "status": payload.get("status"),
                    "error": payload.get("error") or payload.get("message"),
                    "errno": payload.get("errno"),
                    "file": item,
                    "direct_link": direct_link,
                    "payload": payload,
                }

            def extract_worker_proxy_result(self, response: ResponseObject) -> dict:
                payload = response.json if isinstance(response.json, dict) else {}
                data = payload.get("data") or payload.get("upstream") or {}
                items = data.get("list") or []
                item = items[0] if items else {}
                direct_link = (
                    item.get("direct_link")
                    or item.get("download_link")
                    or item.get("link")
                    or item.get("dlink")
                    or data.get("dlink")
                )
                return {
                    "status_code": response.status_code,
                    "status": "success" if response.status_code == 200 and data.get("errno") == 0 else "error",
                    "error": payload.get("error") or payload.get("message") or payload.get("note"),
                    "errno": data.get("errno"),
                    "file": item,
                    "direct_link": direct_link,
                    "payload": payload,
                    "note": payload.get("note"),
                    "data": data,
                }

            def extract_proxy_download_status(self, proxy_result: dict) -> dict:
                base = {
                    "errno": proxy_result.get("errno"),
                    "errmsg": proxy_result.get("error"),
                    "server_time": None,
                    "dstime": None,
                    "source": "gateway",
                }
                if proxy_result.get("status_code") != 200:
                    return {
                        **base,
                        "can_download": False,
                        "reason": f"gateway_http_{proxy_result.get('status_code')}",
                        "direct_link": None,
                    }
                if proxy_result.get("status") != "success":
                    return {**base, "can_download": False, "reason": "gateway_error", "direct_link": None}
                direct_link = proxy_result.get("direct_link")
                if not direct_link:
                    return {**base, "can_download": False, "reason": "gateway_missing_link", "direct_link": None}
                return {**base, "can_download": True, "reason": "gateway_ready", "direct_link": direct_link}

            def extract_proxy_direct_link(self, proxy_result: dict) -> str | None:
                return proxy_result.get("direct_link")

            def extract_direct_link(self, download_item: dict) -> str | None:
                return download_item.get("dlink")

            def extract_download_status(self, download_item: dict) -> dict:
                errno = download_item.get("errno")
                dlink = download_item.get("dlink")
                server_time = int(download_item.get("server_time") or 0)

                if errno != 0:
                    return {
                        "can_download": False,
                        "reason": f"sharedownload_errno_{errno}",
                        "errno": errno,
                        "errmsg": download_item.get("errmsg"),
                        "server_time": server_time,
                        "dstime": None,
                        "direct_link": None,
                    }

                if not dlink:
                    return {
                        "can_download": False,
                        "reason": "missing_dlink",
                        "errno": errno,
                        "errmsg": download_item.get("errmsg"),
                        "server_time": server_time,
                        "dstime": None,
                        "direct_link": None,
                    }

                query = parse_qs(urlparse(dlink).query)
                dstime_raw = (query.get("dstime") or [None])[0]
                try:
                    dstime = int(dstime_raw) if dstime_raw else None
                except (TypeError, ValueError):
                    dstime = None

                is_fresh = bool(dstime and server_time and dstime >= server_time)
                reason = "ready" if is_fresh else "expired_issued_link"
                return {
                    "can_download": is_fresh,
                    "reason": reason,
                    "errno": errno,
                    "errmsg": download_item.get("errmsg"),
                    "server_time": server_time,
                    "dstime": dstime,
                    "direct_link": dlink,
                }

            def extend_metadata_download(self, metadata: dict, download_item: dict, download_status: dict) -> dict:
                updated = dict(metadata)
                updated["download_errno"] = download_item.get("errno")
                updated["download_error"] = download_item.get("errmsg")
                updated["download_server_time"] = download_status.get("server_time")
                updated["download_dstime"] = download_status.get("dstime")
                updated["download_state"] = download_status.get("reason")
                updated["download_url"] = download_status.get("direct_link")
                updated["download_source"] = download_status.get("source") or "native"
                return updated

            def extend_metadata_proxy(self, metadata: dict, proxy_result: dict, download_status: dict) -> dict:
                updated = dict(metadata)
                file_info = proxy_result.get("file") or {}
                payload = proxy_result.get("payload") or {}
                proxy_size_bytes = int(file_info.get("size_bytes") or updated.get("size_bytes") or 0)
                updated["filename"] = file_info.get("filename") or updated.get("filename")
                updated["size_bytes"] = proxy_size_bytes
                updated["size"] = format_size(proxy_size_bytes) if proxy_size_bytes else updated.get("size")
                updated["fs_id"] = file_info.get("fs_id") or updated.get("fs_id")
                updated["thumbs"] = file_info.get("thumbnails") or updated.get("thumbs") or {}
                updated["download_errno"] = proxy_result.get("errno")
                updated["download_error"] = proxy_result.get("error")
                updated["download_server_time"] = None
                updated["download_dstime"] = None
                updated["download_state"] = download_status.get("reason")
                updated["download_url"] = download_status.get("direct_link")
                updated["download_source"] = download_status.get("source")
                updated["proxy_gateway"] = proxy_request_url
                updated["proxy_status"] = payload.get("status")
                if proxy_result.get("note"):
                    updated["proxy_note"] = proxy_result.get("note")
                return updated

            def log_download_negotiation(self, download_item: dict, download_status: dict):
                self.log_json(
                    "download negotiation",
                    {
                        "request": {
                            "shorturl": shorturl,
                            "cookie_auth": self.has_ndus_cookie(request_headers.get("Cookie", "")),
                        },
                        "response": download_item,
                        "status": download_status,
                    },
                )
                if download_status.get("reason") == "expired_issued_link":
                    logger.warning(
                        "[TeraBox] download link expired at issuance (dstime={} < server_time={}). "
                        "Without the ndus auth cookie, TeraBox returns pre-expired download links. "
                        "To fix: provide login credentials (login_email/login_password) "
                        "or pass ndus='<value>' to TeraBoxFetcherFactory.",
                        download_status.get("dstime"),
                        download_status.get("server_time"),
                    )

            def log_proxy_resolution(self, proxy_result: dict, download_status: dict):
                self.log_json(
                    "gateway resolution",
                    {
                        "request": {
                            "url": proxy_request_url,
                            "mode": proxy_mode,
                            "cookie_auth": self.has_ndus_cookie(request_headers.get("Cookie", "")),
                        },
                        "response": proxy_result,
                        "status": download_status,
                    },
                )

            info_steps = [
                RunRequest("load share page")
                .get(share_page_path)
                .setup_hook(lambda v: v["self"].ensure_auth_cookie())
                .headers(**request_headers)
                .teardown_callback("apply_extracted_cookies(response)", assign="auth_cookie")
                .teardown_callback("extract_js_token(response)", assign="js_token")
                .validate()
                .assert_equal("status_code", 200),
                RunRequest("load share metadata")
                .get("/api/shorturlinfo")
                .headers(**request_headers, Cookie="$auth_cookie")
                .params(
                    app_id="250528",
                    web="1",
                    channel="dubox",
                    clienttype="0",
                    jsToken="$js_token",
                    shorturl=shorturl,
                    root="1",
                    scene="",
                )
                .teardown_callback("extract_file_list(response)", assign="file_list")
                .teardown_callback("extract_metadata(response, file_list)", assign="metadata")
                .teardown_callback("extract_filename(metadata)", assign="filename")
                .teardown_callback("default_downloads_count()", assign="downloads_count")
                .teardown_callback("is_available(file_list)", assign="available")
                .teardown_callback("log_fetch_state(metadata, downloads_count)")
                .validate()
                .assert_equal("status_code", 200)
                .assert_equal("available", True),
            ]

            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    ConditionalStep(
                        RunRequest("load gateway direct link")
                        .get(proxy_request_url or "https://invalid.local/api2")
                        .headers(**proxy_headers)
                        .params(url=link)
                        .teardown_callback("extract_proxy_result(response)", assign="proxy_result")
                        .teardown_callback("extract_proxy_direct_link(proxy_result)", assign="direct_link")
                        .teardown_callback("extract_proxy_download_status(proxy_result)", assign="download_status")
                        .teardown_callback(
                            "extend_metadata_proxy(metadata, proxy_result, download_status)", assign="metadata"
                        )
                        .teardown_callback("extract_filename(metadata)", assign="filename")
                        .teardown_callback("log_proxy_resolution(proxy_result, download_status)")
                    ).when(lambda vars: (mode != Mode.INFO and vars.get("available") is True and proxy_mode == "api2")),
                    ConditionalStep(
                        RunRequest("load worker direct link")
                        .get(proxy_request_url or "https://invalid.local/")
                        .headers(**proxy_headers)
                        .params(mode="resolve", surl=surl, raw="1")
                        .teardown_callback("extract_worker_proxy_result(response)", assign="proxy_result")
                        .teardown_callback("extract_proxy_direct_link(proxy_result)", assign="direct_link")
                        .teardown_callback("extract_proxy_download_status(proxy_result)", assign="download_status")
                        .teardown_callback(
                            "extend_metadata_proxy(metadata, proxy_result, download_status)", assign="metadata"
                        )
                        .teardown_callback("extract_filename(metadata)", assign="filename")
                        .teardown_callback("log_proxy_resolution(proxy_result, download_status)")
                    ).when(
                        lambda vars: (mode != Mode.INFO and vars.get("available") is True and proxy_mode == "worker")
                    ),
                    ConditionalStep(
                        RunRequest("load shared download link")
                        .get("/api/sharedownload")
                        .setup_hook(
                            lambda v: v.update(
                                {
                                    "download_sign": v["self"].get_download_sign(v["metadata"]),
                                    "download_timestamp": v["self"].get_download_timestamp(v["metadata"]),
                                    "share_id": v["self"].get_share_id(v["metadata"]),
                                    "share_uk": v["self"].get_share_uk(v["metadata"]),
                                    "fid_list": v["self"].build_fid_list(v["metadata"]),
                                    "download_extra": v["self"].build_download_extra(v["metadata"]),
                                }
                            )
                        )
                        .headers(**sharedownload_headers, Cookie="$auth_cookie")
                        .params(
                            app_id="250528",
                            web="1",
                            channel="dubox",
                            clienttype="0",
                            jsToken="$js_token",
                            shorturl=shorturl,
                            sign="$download_sign",
                            timestamp="$download_timestamp",
                            shareid="$share_id",
                            primaryid="$share_id",
                            uk="$share_uk",
                            fid_list="$fid_list",
                            product="share",
                            type="nolimit",
                            nozip="0",
                            extra="$download_extra",
                        )
                        .teardown_callback("extract_sharedownload_item(response)", assign="download_item")
                        .teardown_callback("extract_direct_link(download_item)", assign="direct_link")
                        .teardown_callback("extract_download_status(download_item)", assign="download_status")
                        .teardown_callback(
                            "extend_metadata_download(metadata, download_item, download_status)", assign="metadata"
                        )
                        .teardown_callback("log_download_negotiation(download_item, download_status)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(
                        lambda vars: (
                            mode != Mode.INFO
                            and vars.get("available") is True
                            and not bool((vars.get("download_status") or {}).get("can_download"))
                        )
                    ),
                    ConditionalStep(
                        RunRequest("download")
                        .get("$direct_link")
                        .headers(**download_headers, Cookie="$auth_cookie")
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(
                        lambda vars: (
                            mode != Mode.INFO
                            and vars.get("available") is True
                            and bool(
                                (vars.get("download_status") or {}).get("can_download") and vars.get("direct_link")
                            )
                        )
                    ),
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return TeraBoxFetcher(**kwargs)
