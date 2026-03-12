import json
from http.cookies import SimpleCookie

import httpx
from loguru import logger

from httporchestrator.http_models import (RequestData, RequestResponseRecord,
                                          ResponseData)
from httporchestrator.utils import (format_response_body_for_log,
                                    lower_dict_keys)


def _log_record(data, label: str):
    """Log a RequestData or ResponseData in debug mode."""
    lines = [f"\n{'=' * 20} {label} details {'=' * 20}"]
    for key, value in data.dict().items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, indent=4, ensure_ascii=False)
        lines.append(f"{key:<8} : {value}")
    logger.debug("\n".join(lines))


def _parse_request_cookies(headers: dict) -> dict:
    """Extract cookies from the raw Cookie header."""
    cookie_header = headers.get("cookie", "")
    if not cookie_header:
        return {}
    parsed = SimpleCookie()
    parsed.load(cookie_header)
    return {k: m.value for k, m in parsed.items()}


def _parse_request_body(resp_obj: httpx.Response, headers: dict):
    """Extract and decode the request body, returning a JSON-friendly value."""
    try:
        raw = resp_obj.request.content
    except httpx.RequestNotRead:
        return None

    content_type = lower_dict_keys(headers).get("content-type", "")
    if "multipart/form-data" in content_type:
        return "upload file stream (OMITTED)"

    try:
        return json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return raw


def get_req_resp_record(resp_obj: httpx.Response, log_details: bool = True) -> RequestResponseRecord:
    """Get request and response info from an httpx.Response object."""
    # --- request ---
    request_headers = dict(resp_obj.request.headers)

    request_data = RequestData(
        method=resp_obj.request.method,
        url=str(resp_obj.request.url),
        headers=request_headers,
        cookies=_parse_request_cookies(request_headers),
        body=_parse_request_body(resp_obj, request_headers),
    )
    if log_details:
        _log_record(request_data, "request")

    # --- response ---
    resp_headers = dict(resp_obj.headers)
    lower_headers = lower_dict_keys(resp_headers)
    content_type = lower_headers.get("content-type", "")
    content_disposition = lower_headers.get("content-disposition", "")

    try:
        response_body = resp_obj.json()
    except ValueError:
        raw = resp_obj.content if ("image" in content_type or "attachment" in content_disposition) else resp_obj.text
        response_body = format_response_body_for_log(raw, content_type, content_disposition)

    response_data = ResponseData(
        status_code=resp_obj.status_code,
        cookies=dict(resp_obj.cookies) if resp_obj.cookies else {},
        encoding=resp_obj.encoding,
        headers=resp_headers,
        content_type=content_type,
        body=response_body,
    )
    if log_details:
        _log_record(response_data, "response")

    return RequestResponseRecord(request=request_data, response=response_data)
