import unittest

import httpx

from httporchestrator.client import get_req_resp_record

ECHO_URL = "https://postman-echo.com"


class TestGetReqRespRecord(unittest.TestCase):
    def test_record_from_get(self):
        with httpx.Client(verify=False) as client:
            resp = client.get(f"{ECHO_URL}/get")
        record = get_req_resp_record(resp)
        self.assertEqual(record.response.status_code, 200)
        self.assertEqual(record.request.method, "GET")
        self.assertIn("postman-echo.com", record.request.url)

    def test_record_from_post_json(self):
        with httpx.Client(verify=False) as client:
            resp = client.post(f"{ECHO_URL}/post", json={"key": "value"})
        record = get_req_resp_record(resp)
        self.assertEqual(record.response.status_code, 200)
        self.assertEqual(record.request.method, "POST")
        self.assertEqual(record.request.body, {"key": "value"})

    def test_record_redirect(self):
        with httpx.Client(verify=False, follow_redirects=False) as client:
            resp = client.get(
                f"{ECHO_URL}/redirect-to?url=https%3A%2F%2Fgithub.com",
            )
        record = get_req_resp_record(resp)
        self.assertEqual(record.response.status_code, 302)
