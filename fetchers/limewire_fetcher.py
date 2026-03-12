import base64
import json
import re
from typing import Dict
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap
from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, format_size, format_timestamp, should_download
from httporchestrator import RunRequest
from httporchestrator.response import ResponseObject
from httporchestrator.step_request import ConditionalStep

_STREAM_RE = re.compile(r'streamController\.enqueue\("((?:[^"\\]|\\.)*)"\)')

# These constants are embedded in LimeWire frontend bundles.
_SHARING_PASSPHRASE_SALT_B64 = "wvsoOvbI854RHQMiSiPmnw=="
_CONTENT_MAIN_FILE_IV_B64 = "C8aZG384/qPpBzg="


def decode_turbo_stream(flat: list):
    cache: dict = {}

    def resolve(idx):
        if idx < 0:
            return None
        if idx in cache:
            return cache[idx]
        val = flat[idx]
        if isinstance(val, dict):
            result: dict = {}
            cache[idx] = result
            for k, v_idx in val.items():
                key_idx = int(k.lstrip("_"))
                actual_key = resolve(key_idx)
                actual_val = resolve(v_idx)
                if actual_key is not None:
                    result[actual_key] = actual_val
            return result
        if isinstance(val, list):
            if len(val) == 2 and val[0] == "D":
                return val[1]
            result_list: list = []
            cache[idx] = result_list
            result_list.extend(resolve(item) for item in val)
            return result_list
        return val

    return resolve(0)


def extract_turbo_data(html: str) -> tuple[dict, dict] | None:
    if not isinstance(html, str):
        return None

    match = _STREAM_RE.search(html)
    if not match:
        return None

    raw = match.group(1)
    try:
        decoded_str = json.loads('"' + raw + '"')
        flat = json.loads(decoded_str)
    except (json.JSONDecodeError, ValueError):
        return None

    decoded = decode_turbo_stream(flat)
    if not isinstance(decoded, dict):
        return None

    loader = decoded.get("loaderData", {})
    route_data = loader.get("routes/__root/d/$id", {})
    root_data = loader.get("routes/__root", {})
    return route_data, root_data


def parse_sharing_url_info(url: str) -> dict:
    parsed = urlparse(url)
    sharing_id = (parsed.path.rstrip("/").split("/")[-1]) or ""
    decryption_info = parsed.fragment or ""
    return {
        "sharing_id": sharing_id,
        "decryption_info": decryption_info,
    }


def select_primary_file_key(file_keys: list, primary_key_id: str | None) -> dict:
    if not file_keys:
        return {}
    if primary_key_id:
        return next((entry for entry in file_keys if entry.get("id") == primary_key_id), file_keys[0])
    return file_keys[0]


def build_turbo_metadata(route_data: dict, root_data: dict, content_id: str, link: str) -> dict:
    bucket_wrap = route_data.get("sharingBucketContentData", {})
    bucket_val = bucket_wrap.get("value", {}) if bucket_wrap.get("ok") else {}
    bucket = bucket_val.get("sharingBucket", {})
    content_items = bucket_val.get("contentItemList", [])
    first_item = content_items[0] if content_items else {}

    file_keys = bucket_val.get("fileEncryptionKeys", [])
    primary_key_id = bucket.get("primaryEncryptionKeyId")
    file_key = select_primary_file_key(file_keys, primary_key_id)

    status = bucket.get("sharingStatus", "")

    return {
        "id": bucket.get("id") or content_id,
        "filename": bucket.get("name") or f"limewire-{content_id}",
        "size": format_size(bucket.get("totalFileSize")),
        "file_type": first_item.get("mediaType"),
        "downloads_count": bucket.get("downloadCounter"),
        "creator_id": bucket.get("ownerId"),
        "created_at": format_timestamp(bucket.get("createdDate")),
        "expires_at": format_timestamp(bucket.get("expiresAt")),
        "state": "available" if status == "SHARED" else "unavailable",
        "url": link,
        "item_type": first_item.get("itemType"),
        "sharing_id": route_data.get("sharingId"),
        "file_url": None,
        "self_csrf": root_data.get("selfCsrf", ""),
        "content_item": first_item,
        "file_encryption_key": file_key,
        "sharing_url_info": parse_sharing_url_info(link),
    }


def urlsafe_b64decode(data: str) -> bytes:
    normalized = (data or "").replace("-", "+").replace("_", "/")
    pad = len(normalized) % 4
    if pad:
        normalized += "=" * (4 - pad)
    return base64.b64decode(normalized)


def derive_wrapping_key_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def build_p256_private_key_from_scalar(raw_scalar: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw_scalar, "big"), ec.SECP256R1())


def derive_aes_key_from_ecdh(private_key: ec.EllipticCurvePrivateKey, peer_public_key_bytes: bytes) -> bytes:
    peer_public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), peer_public_key_bytes)
    return private_key.exchange(ec.ECDH(), peer_public_key)


def decrypt_aes_ctr_11byte_iv(ciphertext: bytes, aes_key: bytes, iv_11: bytes) -> bytes:
    if len(iv_11) != 11:
        raise ValueError("Invalid CTR IV length")
    counter_block = iv_11 + b"\x00" * 5
    decryptor = Cipher(algorithms.AES(aes_key), modes.CTR(counter_block)).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def unwrap_file_private_key_raw(sharing_url_info: dict, file_key: dict) -> bytes | None:
    decryption_info = sharing_url_info.get("decryption_info")
    sharing_id = sharing_url_info.get("sharing_id")
    if not isinstance(decryption_info, str) or not decryption_info:
        return None

    wrapped_private_key = file_key.get("passphraseWrappedPrivateKey")
    if len(sharing_id or "") != 36 and wrapped_private_key:
        salt = urlsafe_b64decode(_SHARING_PASSPHRASE_SALT_B64)
        wrapping_key = derive_wrapping_key_from_passphrase(decryption_info, salt)
        return aes_key_unwrap(wrapping_key, urlsafe_b64decode(wrapped_private_key))

    return urlsafe_b64decode(decryption_info)


def decrypt_limewire_file_bytes(encrypted_bytes: bytes, metadata: dict) -> bytes:
    content_item = metadata.get("content_item") or {}
    file_key = metadata.get("file_encryption_key") or {}
    sharing_url_info = metadata.get("sharing_url_info") or {}

    private_key_raw = unwrap_file_private_key_raw(sharing_url_info, file_key)
    if not private_key_raw:
        raise ValueError("Could not resolve file private key")

    base_private_key = build_p256_private_key_from_scalar(private_key_raw)
    ephemeral_public_key = urlsafe_b64decode(content_item.get("ephemeralPublicKey", ""))
    aes_ctr_key = derive_aes_key_from_ecdh(base_private_key, ephemeral_public_key)

    file_iv = urlsafe_b64decode(_CONTENT_MAIN_FILE_IV_B64)
    return decrypt_aes_ctr_11byte_iv(encrypted_bytes, aes_ctr_key, file_iv)


class LimewireFetcherFactory:
    """
    has download notification: No
    has downloads count: Yes
    """

    URL_PATTERN = re.compile(r"limewire\.com/d/([0-9A-Za-z_-]+)")

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        # Use removeprefix, not lstrip: lstrip("www.") strips the individual characters
        # {'w', '.'} from the left, incorrectly matching hosts like "wwwlimewire.com".
        netloc = parsed.netloc.removeprefix("www.")
        return (netloc == "limewire.com" or netloc.endswith(".limewire.com")) and bool(cls.URL_PATTERN.search(url))

    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid Limewire URL provided")
        self.link = link
        self.headers = headers or {}

        match = self.URL_PATTERN.search(link)
        self.content_id = match.group(1)

    def create(self, mode: Mode = Mode.FETCH, **kwargs) -> BaseFetcher:
        content_id = self.content_id
        link = self.link
        request_headers = self.headers

        class LimewireFetcher(BaseFetcher):
            NAME = "Limewire"
            BASE_URL = "https://limewire.com"

            def __init__(self, **kwargs):
                super().__init__(**kwargs)

            def _resolve_access_token(self, response: ResponseObject) -> str:
                # The access token cookie is often set on redirect responses.
                for hist in getattr(response.resp_obj, "history", []):
                    token = dict(hist.cookies).get("production_access_token", "")
                    if token:
                        return token

                token = response.cookies.get("production_access_token", "")
                if token:
                    return token

                if self.client:
                    return str(self.client.cookies.get("production_access_token", ""))

                return ""

            def transform_body(self, body: bytes) -> bytes:
                try:
                    metadata = getattr(self, "_last_metadata", {})
                    return decrypt_limewire_file_bytes(body, metadata)
                except Exception as exc:
                    logger.warning(
                        "[{}] limewire decrypt failed, saving raw payload: {}",
                        self.NAME,
                        exc,
                    )
                    return body

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "content_id": content_id,
                            "filename": metadata.get("filename"),
                            "size": format_size(metadata.get("size")),
                            "downloads_count": downloads_count,
                            "state": metadata.get("state"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def _build_turbo_metadata(self, response: ResponseObject) -> dict | None:
                turbo = extract_turbo_data(response.text)
                if not turbo:
                    return None

                route_data, root_data = turbo
                return build_turbo_metadata(route_data, root_data, content_id, link)

            def extract_metadata(self, response: ResponseObject) -> dict:
                metadata = self._build_turbo_metadata(response)
                if metadata is None:
                    raise ValueError("Unable to parse LimeWire turbo metadata")
                self._last_metadata = metadata
                return metadata

            def extract_bucket_id(self, metadata: dict) -> str | None:
                return metadata.get("id")

            def extract_item_id(self, metadata: dict) -> str | None:
                return (metadata.get("content_item") or {}).get("id")

            def extract_self_csrf(self, metadata: dict) -> str | None:
                return metadata.get("self_csrf")

            def extract_access_token(self, response: ResponseObject) -> str | None:
                return self._resolve_access_token(response) or None

            def extract_download_url(self, response: ResponseObject) -> str | None:
                data = response.json if isinstance(response.json, dict) else {}
                items = data.get("contentItems") or []
                if not items:
                    return None
                return items[0].get("downloadUrl")

            def attach_download_url(self, metadata: dict, download_url: str | None) -> dict:
                metadata["file_url"] = download_url
                self._last_metadata = metadata
                return metadata

            def extract_downloads_count(self, metadata: dict) -> int | None:
                return metadata.get("downloads_count")

            def extract_filename(self, metadata: dict) -> str:
                return metadata.get("filename") or f"limewire-{content_id}"

            def extract_file_url(self, metadata: dict) -> str | None:
                return metadata.get("file_url")

            def is_available(self, metadata: dict) -> bool:
                return metadata.get("state") == "available"

            info_steps = [
                RunRequest("get content metadata")
                .get(f"/d/{content_id}")
                .headers(**request_headers)
                .headers(Accept="text/html")
                .teardown_callback("extract_metadata(response)", assign="metadata")
                .teardown_callback("extract_filename(metadata)", assign="filename")
                .teardown_callback("extract_downloads_count(metadata)", assign="downloads_count")
                .teardown_callback("extract_bucket_id(metadata)", assign="bucket_id")
                .teardown_callback("extract_item_id(metadata)", assign="item_id")
                .teardown_callback("extract_self_csrf(metadata)", assign="self_csrf")
                .teardown_callback("extract_access_token(response)", assign="access_token")
                .teardown_callback("is_available(metadata)", assign="available")
                .teardown_callback("log_fetch_state(metadata, downloads_count)")
                .validate()
                .assert_equal("status_code", 200)
                .assert_equal("available", True),
            ]

            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    ConditionalStep(
                        RunRequest("get download url")
                        .post(lambda v: f"https://api.limewire.com/sharing/download/{v['bucket_id']}")
                        .headers(
                            Authorization=lambda v: f"Bearer {v['access_token']}",
                            **{
                                "x-csrf-token": lambda v: v["self_csrf"],
                                "Content-Type": "application/json",
                                "Cookie": lambda v: f"production_access_token={v['access_token']}",
                            },
                            Origin="https://limewire.com",
                            Referer="https://limewire.com/",
                            Accept="application/json",
                        )
                        .json(lambda v: {"contentItems": [{"id": v["item_id"]}]})
                        .teardown_callback("extract_download_url(response)", assign="download_url")
                        .teardown_callback("attach_download_url(metadata, download_url)", assign="metadata")
                        .teardown_callback("extract_file_url(metadata)", assign="file_url")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(
                        lambda vars: (
                            should_download(mode, vars.get("downloads_count"))
                            and vars.get("available") is True
                            and vars.get("bucket_id") is not None
                            and vars.get("item_id") is not None
                            and vars.get("self_csrf")
                            and vars.get("access_token")
                        )
                    ),
                    ConditionalStep(
                        RunRequest("download")
                        .get("$file_url")
                        .headers(**request_headers)
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(
                        lambda vars: (
                            should_download(mode, vars.get("downloads_count"))
                            and vars.get("available") is True
                            and vars.get("file_url") is not None
                        )
                    ),
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return LimewireFetcher(**kwargs)
