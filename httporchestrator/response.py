from __future__ import annotations

from typing import Any, Generic, TypeVar

RawResponseT = TypeVar("RawResponseT")


class Response(Generic[RawResponseT]):
    def __init__(self, raw_response: RawResponseT):
        self.raw = raw_response

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    @property
    def body(self) -> Any:
        try:
            return self.raw.json()
        except ValueError:
            return self.raw.content

    def json(self) -> Any:
        return self.raw.json()
