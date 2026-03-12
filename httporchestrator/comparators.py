"""Assertion comparators for response validation."""

import re
from typing import Any


def _assert(condition: bool, message: str = ""):
    if not condition:
        raise AssertionError(message)


def equal(check_value: Any, expect_value: Any, message: str = ""):
    _assert(check_value == expect_value, message)


def not_equal(check_value: Any, expect_value: Any, message: str = ""):
    _assert(check_value != expect_value, message)


def string_equals(check_value: Any, expect_value: Any, message: str = ""):
    _assert(str(check_value) == str(expect_value), message)


def greater_than(check_value, expect_value, message: str = ""):
    _assert(check_value > expect_value, message)


def less_than(check_value, expect_value, message: str = ""):
    _assert(check_value < expect_value, message)


def greater_or_equals(check_value, expect_value, message: str = ""):
    _assert(check_value >= expect_value, message)


def less_or_equals(check_value, expect_value, message: str = ""):
    _assert(check_value <= expect_value, message)


def length_equal(check_value, expect_value: int, message: str = ""):
    _assert(isinstance(expect_value, int), "expect_value should be int type")
    _assert(len(check_value) == expect_value, message)


def length_greater_than(check_value, expect_value, message: str = ""):
    _assert(isinstance(expect_value, (int, float)), "expect_value should be int/float type")
    _assert(len(check_value) > expect_value, message)


def length_greater_or_equals(check_value, expect_value, message: str = ""):
    _assert(isinstance(expect_value, (int, float)), "expect_value should be int/float type")
    _assert(len(check_value) >= expect_value, message)


def length_less_than(check_value, expect_value, message: str = ""):
    _assert(isinstance(expect_value, (int, float)), "expect_value should be int/float type")
    _assert(len(check_value) < expect_value, message)


def length_less_or_equals(check_value, expect_value, message: str = ""):
    _assert(isinstance(expect_value, (int, float)), "expect_value should be int/float type")
    _assert(len(check_value) <= expect_value, message)


def contains(check_value, expect_value: Any, message: str = ""):
    _assert(
        isinstance(check_value, (list, tuple, dict, str, bytes)),
        "check_value should be list/tuple/dict/str/bytes type",
    )
    _assert(expect_value in check_value, message)


def contained_by(check_value: Any, expect_value, message: str = ""):
    _assert(
        isinstance(expect_value, (list, tuple, dict, str, bytes)),
        "expect_value should be list/tuple/dict/str/bytes type",
    )
    _assert(check_value in expect_value, message)


def type_match(check_value: Any, expect_value, message: str = ""):
    if expect_value in ("None", "NoneType", None):
        _assert(check_value is None, message)
    else:
        if isinstance(expect_value, type):
            target_type = expect_value
        elif isinstance(expect_value, str):
            import builtins

            target_type = getattr(builtins, expect_value, None)
            if target_type is None:
                raise ValueError(expect_value)
        else:
            raise ValueError(expect_value)
        _assert(type(check_value) == target_type, message)


def regex_match(check_value: Any, expect_value: str, message: str = ""):
    _assert(isinstance(expect_value, str), "expect_value should be str type")
    _assert(isinstance(check_value, str), "check_value should be str type")
    _assert(re.match(expect_value, check_value) is not None, message)


def startswith(check_value: Any, expect_value: Any, message: str = ""):
    _assert(str(check_value).startswith(str(expect_value)), message)


def endswith(check_value: Any, expect_value: Any, message: str = ""):
    _assert(str(check_value).endswith(str(expect_value)), message)


# Registry: comparator name → function
COMPARATORS = {
    "equal": equal,
    "not_equal": not_equal,
    "string_equals": string_equals,
    "greater_than": greater_than,
    "less_than": less_than,
    "greater_or_equals": greater_or_equals,
    "less_or_equals": less_or_equals,
    "length_equal": length_equal,
    "length_greater_than": length_greater_than,
    "length_greater_or_equals": length_greater_or_equals,
    "length_less_than": length_less_than,
    "length_less_or_equals": length_less_or_equals,
    "contains": contains,
    "contained_by": contained_by,
    "type_match": type_match,
    "regex_match": regex_match,
    "startswith": startswith,
    "endswith": endswith,
}


def run_comparator(name: str, check_value: Any, expect_value: Any, message: str = ""):
    comparator_fn = COMPARATORS.get(name)
    if comparator_fn is None:
        raise ValueError(f"unknown comparator: {name}")
    comparator_fn(check_value, expect_value, message)
