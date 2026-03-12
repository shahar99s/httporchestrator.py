import ast
import re
from typing import Any, Dict
from urllib.parse import urlparse

from httporchestrator import exceptions


def parse_string_value(str_value: str) -> Any:
    """parse string to number if possible
    e.g. "123" => 123
         "12.2" => 12.3
         "abc" => "abc"
    """
    try:
        return ast.literal_eval(str_value)
    except (ValueError, SyntaxError):
        return str_value


def traverse_path(obj: Any, expr: str) -> Any:
    """Traverse a dotted path with optional bracket indexing.

    Examples:
        traverse_path(data, 'body.items[0].name')
        traverse_path(headers, 'Content-Type')
    """
    for segment in expr.split("."):
        if "[" in segment:
            key, _, rest = segment.partition("[")
            idx = int(rest.rstrip("]"))
            if key:
                obj = obj[key] if isinstance(obj, dict) else getattr(obj, key)
            obj = obj[idx]
        elif isinstance(obj, dict):
            obj = obj[segment]
        elif isinstance(obj, list):
            obj = obj[int(segment)]
        else:
            obj = getattr(obj, segment)
    return obj


_EXPR_ACCESS = re.compile(r"""\.([\w]+)|\[(['"])(.+?)\2\]""")


def resolve_expr(expr: str, variables: Dict) -> Any:
    """Resolve a dotted/bracket expression against a variables dict.

    Examples:
        resolve_expr('response.body["key"]', variables)
        resolve_expr('response.json["file"]["name"]', variables)
    """
    m = re.match(r"([a-zA-Z_]\w*)(.*)", expr)
    obj = variables[m.group(1)]
    for tok in _EXPR_ACCESS.finditer(m.group(2)):
        if tok.group(1):
            obj = getattr(obj, tok.group(1))
        else:
            obj = obj[tok.group(3)]
    return obj


def build_url(base_url, step_url):
    """prepend url with base_url unless it's already an absolute URL"""
    o_step_url = urlparse(step_url)
    if o_step_url.netloc != "":
        return step_url

    o_base_url = urlparse(base_url)
    if o_base_url.netloc == "":
        raise exceptions.ParameterError("base url missed!")

    path = o_base_url.path.rstrip("/") + "/" + o_step_url.path.lstrip("/")
    o_step_url = o_step_url._replace(scheme=o_base_url.scheme)._replace(netloc=o_base_url.netloc)._replace(path=path)
    return o_step_url.geturl()
