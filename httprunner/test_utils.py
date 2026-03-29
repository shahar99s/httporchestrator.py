"""Shared test helpers for httprunner unit/integration tests."""

from httprunner.client import HttpSession


def postman_echo_available() -> bool:
    """Return True only if postman-echo.com responds with HTTP 200.

    Used as a lightweight connectivity guard before tests that make live
    requests to the postman-echo service.
    """
    session = HttpSession()
    session.request("get", "https://postman-echo.com/get", timeout=10)
    return bool(
        session.data.req_resps
        and session.data.req_resps[-1].response.status_code == 200
    )
