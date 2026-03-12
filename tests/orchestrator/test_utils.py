import unittest
from pathlib import Path

try:
    import tomllib

    def _toml_loads(content):
        return tomllib.loads(content)

except ModuleNotFoundError:
    import toml

    def _toml_loads(content):
        return toml.loads(content)


from httporchestrator import __version__, utils
from httporchestrator.utils import merge_variables


class TestUtils(unittest.TestCase):
    def test_validators(self):
        from httporchestrator.comparators import COMPARATORS

        functions_mapping = COMPARATORS

        functions_mapping["equal"](None, None)
        functions_mapping["equal"](1, 1)
        functions_mapping["equal"]("abc", "abc")
        with self.assertRaises(AssertionError):
            functions_mapping["equal"]("123", 123)

        functions_mapping["less_than"](1, 2)
        functions_mapping["less_or_equals"](2, 2)

        functions_mapping["greater_than"](2, 1)
        functions_mapping["greater_or_equals"](2, 2)

        functions_mapping["not_equal"](123, "123")

        functions_mapping["length_equal"]("123", 3)
        with self.assertRaises(AssertionError):
            functions_mapping["length_equal"]("123", "3")
        with self.assertRaises(AssertionError):
            functions_mapping["length_equal"]("123", "abc")
        functions_mapping["length_greater_than"]("123", 2)
        functions_mapping["length_greater_or_equals"]("123", 3)

        functions_mapping["contains"]("123abc456", "3ab")
        functions_mapping["contains"](["1", "2"], "1")
        functions_mapping["contains"]({"a": 1, "b": 2}, "a")
        functions_mapping["contained_by"]("3ab", "123abc456")
        functions_mapping["contained_by"](0, [0, 200])

        functions_mapping["regex_match"]("123abc456", "^123\w+456$")
        with self.assertRaises(AssertionError):
            functions_mapping["regex_match"]("123abc456", "^12b.*456$")

        functions_mapping["startswith"]("abc123", "ab")
        functions_mapping["startswith"]("123abc", 12)
        functions_mapping["startswith"](12345, 123)

        functions_mapping["endswith"]("abc123", 23)
        functions_mapping["endswith"]("123abc", "abc")
        functions_mapping["endswith"](12345, 45)

        functions_mapping["type_match"](580509390, int)
        functions_mapping["type_match"](580509390, "int")
        functions_mapping["type_match"]([], list)
        functions_mapping["type_match"]([], "list")
        functions_mapping["type_match"]([1], "list")
        functions_mapping["type_match"]({}, "dict")
        functions_mapping["type_match"]({"a": 1}, "dict")
        functions_mapping["type_match"](None, "None")
        functions_mapping["type_match"](None, "NoneType")
        functions_mapping["type_match"](None, None)

    def test_lower_dict_keys(self):
        request_dict = {
            "url": "http://127.0.0.1:5000",
            "METHOD": "POST",
            "Headers": {"Accept": "application/json", "User-Agent": "ios/9.3"},
        }
        new_request_dict = utils.lower_dict_keys(request_dict)
        self.assertIn("method", new_request_dict)
        self.assertIn("headers", new_request_dict)
        self.assertIn("Accept", new_request_dict["headers"])
        self.assertIn("User-Agent", new_request_dict["headers"])

        request_dict = "$default_request"
        new_request_dict = utils.lower_dict_keys(request_dict)
        self.assertEqual("$default_request", request_dict)

        request_dict = None
        new_request_dict = utils.lower_dict_keys(request_dict)
        self.assertEqual(None, request_dict)

    def test_override_config_variables(self):
        step_variables = {"base_url": "$base_url", "foo1": "bar1"}
        config_variables = {"base_url": "https://postman-echo.com", "foo1": "bar111"}
        self.assertEqual(
            merge_variables(step_variables, config_variables),
            {"base_url": "https://postman-echo.com", "foo1": "bar1"},
        )

    def test_versions_are_in_sync(self):
        """Checks if the pyproject.toml and __version__ in __init__.py are in sync."""

        path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        pyproject = _toml_loads(path.read_text(encoding="utf-8"))
        pyproject_version = pyproject["tool"]["poetry"]["version"]
        self.assertEqual(pyproject_version, __version__)
