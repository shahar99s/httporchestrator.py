from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from httporchestrator.exceptions import ParameterError
from httporchestrator.models import (
    Assertion,
    CaptureAction,
    HandleHook,
    HttpMethod,
    PredicateHook,
    PrepareHook,
    RetryPolicy,
    VariablesMapping,
)


def _merge_mapping(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    merged.update(updates)
    return merged


@dataclass(frozen=True)
class RequestStep:
    name: str
    method: HttpMethod | None = None
    url: Any = ""
    params_values: VariablesMapping = field(default_factory=dict)
    header_values: VariablesMapping = field(default_factory=dict)
    cookie_values: VariablesMapping = field(default_factory=dict)
    body_value: Any = None
    json_value: Any = None
    timeout_seconds: float = 120.0
    follow_redirects: bool = True
    state_values: VariablesMapping = field(default_factory=dict)
    before_hooks: tuple[PrepareHook, ...] = ()
    captures: tuple[CaptureAction, ...] = ()
    after_hooks: tuple[HandleHook, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    def _with_method(self, method: HttpMethod, url: Any) -> "RequestStep":
        return replace(self, method=method, url=url)

    def get(self, url: Any) -> "RequestStep":
        return self._with_method(HttpMethod.GET, url)

    def post(self, url: Any) -> "RequestStep":
        return self._with_method(HttpMethod.POST, url)

    def put(self, url: Any) -> "RequestStep":
        return self._with_method(HttpMethod.PUT, url)

    def head(self, url: Any) -> "RequestStep":
        return self._with_method(HttpMethod.HEAD, url)

    def delete(self, url: Any) -> "RequestStep":
        return self._with_method(HttpMethod.DELETE, url)

    def options(self, url: Any) -> "RequestStep":
        return self._with_method(HttpMethod.OPTIONS, url)

    def patch(self, url: Any) -> "RequestStep":
        return self._with_method(HttpMethod.PATCH, url)

    def state(
        self, values: VariablesMapping | None = None, /, **kwargs
    ) -> "RequestStep":
        updates = dict(values or {})
        updates.update(kwargs)
        return replace(self, state_values=_merge_mapping(self.state_values, updates))

    def params(self, **params) -> "RequestStep":
        return replace(self, params_values=_merge_mapping(self.params_values, params))

    def headers(self, **headers) -> "RequestStep":
        return replace(self, header_values=_merge_mapping(self.header_values, headers))

    def cookies(self, **cookies) -> "RequestStep":
        return replace(self, cookie_values=_merge_mapping(self.cookie_values, cookies))

    def data(self, data: Any) -> "RequestStep":
        return replace(self, body_value=data)

    def body(self, data: Any) -> "RequestStep":
        return self.data(data)

    def json(self, req_json: Any) -> "RequestStep":
        return replace(self, json_value=req_json)

    def timeout(self, timeout: float) -> "RequestStep":
        return replace(self, timeout_seconds=timeout)

    def allow_redirects(self, allow_redirects: bool) -> "RequestStep":
        return replace(self, follow_redirects=allow_redirects)

    def before(self, fn: PrepareHook) -> "RequestStep":
        return replace(self, before_hooks=self.before_hooks + (fn,))

    def capture(self, name: str, fn) -> "RequestStep":
        return replace(
            self, captures=self.captures + (CaptureAction(name=name, fn=fn),)
        )

    def check(self, fn, message: str = "") -> "RequestStep":
        return replace(
            self, assertions=self.assertions + (Assertion(fn=fn, message=message),)
        )

    def retry(
        self,
        times: int,
        interval: float,
        retry_on: tuple[type[BaseException], ...] = (),
    ) -> "RequestStep":
        return replace(
            self,
            retry_policy=RetryPolicy(times=times, interval=interval, retry_on=retry_on),
        )

    def after(self, fn: HandleHook) -> "RequestStep":
        """Register a callback invoked after the response is received.

        fn(response, state) must return a mapping (merged into flow variables) or None.
        Returning anything else raises ParameterError at runtime.
        """
        return replace(self, after_hooks=self.after_hooks + (fn,))

    def when(self, predicate: PredicateHook) -> "ConditionalStep":
        """Wrap this step in a ConditionalStep that only runs when predicate returns True."""
        return ConditionalStep(step=self, predicate=predicate)

    def while_(self, predicate: PredicateHook) -> "RepeatableStep":
        """Wrap this step in a RepeatableStep that loops while predicate returns True."""
        return RepeatableStep(step=self, predicate=predicate)

    def for_each(self, variable: str) -> "ForEachStep":
        """Wrap this step in a ForEachStep that runs once per item in a list variable."""
        return ForEachStep(step=self, variable=variable)

    def require_method(self) -> HttpMethod:
        if self.method is None:
            raise ParameterError(f"request '{self.name}' has no HTTP method configured")
        return self.method


@dataclass(frozen=True)
class ConditionalStep:
    step: object
    predicate: PredicateHook = lambda _state: True

    @property
    def name(self) -> str:
        return getattr(self.step, "name", "when")

    def run_when(self, predicate: PredicateHook) -> "ConditionalStep":
        return replace(self, predicate=predicate)


@dataclass(frozen=True)
class RepeatableStep:
    step: object
    predicate: PredicateHook = lambda _state: True

    @property
    def name(self) -> str:
        return getattr(self.step, "name", "repeat")

    def run_while(self, predicate: PredicateHook) -> "RepeatableStep":
        return replace(self, predicate=predicate)


@dataclass(frozen=True)
class ForEachStep:
    """Execute a step once for each item in a list-valued state variable.

    The current item is bound to `item_var` (default: "item") in state before
    each iteration, making it available to callable fields on the inner step.

    Example::

        ForEachStep(
            RequestStep("download").get(lambda s: s["item"]),
            "urls",
        )
    """

    step: object
    variable: str
    item_var: str = "item"

    @property
    def name(self) -> str:
        return getattr(self.step, "name", "for_each")

    def bind_as(self, item_var: str) -> "ForEachStep":
        """Override the state key the current item is bound to (default: 'item')."""
        return replace(self, item_var=item_var)
