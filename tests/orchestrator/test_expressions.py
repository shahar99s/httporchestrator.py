import unittest

from httporchestrator import expressions


class TestParserBasic(unittest.TestCase):
    def test_build_url(self):
        url = expressions.build_url("https://postman-echo.com", "/get")
        self.assertEqual(url, "https://postman-echo.com/get")
        url = expressions.build_url("https://postman-echo.com", "get")
        self.assertEqual(url, "https://postman-echo.com/get")
        url = expressions.build_url("https://postman-echo.com/", "/get")
        self.assertEqual(url, "https://postman-echo.com/get")

        url = expressions.build_url("https://postman-echo.com/abc/", "/get?a=1&b=2")
        self.assertEqual(url, "https://postman-echo.com/abc/get?a=1&b=2")
        url = expressions.build_url("https://postman-echo.com/abc/", "get?a=1&b=2")
        self.assertEqual(url, "https://postman-echo.com/abc/get?a=1&b=2")

        # omit query string in base url
        url = expressions.build_url("https://postman-echo.com/abc?x=6&y=9", "/get?a=1&b=2")
        self.assertEqual(url, "https://postman-echo.com/abc/get?a=1&b=2")

        url = expressions.build_url("", "https://postman-echo.com/get")
        self.assertEqual(url, "https://postman-echo.com/get")

        # notice: step request url > config base url
        url = expressions.build_url("https://postman-echo.com", "https://httpbin.org/get")
        self.assertEqual(url, "https://httpbin.org/get")

    def test_parse_string_value(self):
        self.assertEqual(expressions.parse_string_value("123"), 123)
        self.assertEqual(expressions.parse_string_value("12.3"), 12.3)
        self.assertEqual(expressions.parse_string_value("a123"), "a123")
        self.assertEqual(expressions.parse_string_value("$var"), "$var")
        self.assertEqual(expressions.parse_string_value("${func}"), "${func}")


if __name__ == "__main__":
    unittest.main()
