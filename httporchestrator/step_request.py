import json
import time
from typing import Any, Callable, Dict, List

import httpx
from loguru import logger

from httporchestrator import utils
from httporchestrator.client import get_req_resp_record
from httporchestrator.exceptions import ParameterError, ValidationFailure
from httporchestrator.expressions import build_url, resolve_expr
from httporchestrator.http_models import (RequestMetrics, RequestTemplate,
                                          SessionData)
from httporchestrator.models import (Hooks, MethodEnum, StepData, StepProtocol,
                                     StepResult, VariablesMapping)
from httporchestrator.response import ResponseObject
from httporchestrator.runner import ALLURE, HttpRunner


def call_hooks(hooks: Hooks, step_variables: VariablesMapping, hook_msg: str, log_details: bool = True) -> set:
    """call hook actions.

    Args:
        hooks (list): each hook in hooks list maybe in these formats:

            format1 (callable): call with step_variables dict.
                lambda v: do_something(v["response"])
            format2 (dict with callable): assignment with callable.
                {"var": lambda v: extract(v["response"])}

        step_variables: current step variables to call hook, include two special variables

            request: parsed request dict
            response: ResponseObject for current response

        hook_msg: setup/teardown request/workflow
        log_details: if False, suppress verbose debug logging of hook values

    Returns:
        set: variable names assigned by dict-format hooks

    """
    if log_details:
        logger.info(f"call hook actions: {hook_msg}")
    assigned = set()

    if not isinstance(hooks, List):
        logger.error(f"Invalid hooks format: {hooks}")
        return assigned

    for hook in hooks:
        if callable(hook):
            # callable hook
            if log_details:
                logger.debug(f"call hook function: {hook}")
            hook(step_variables)
        elif isinstance(hook, Dict) and len(hook) == 1:
            # {"var": callable}
            var_name, hook_content = list(hook.items())[0]
            if callable(hook_content):
                hook_content_eval = hook_content(step_variables)
            else:
                logger.error(f"Hook value must be callable, got: {type(hook_content)}")
                continue
            if log_details:
                logger.debug(f"call hook function: {hook_content}, got value: {hook_content_eval}")
                logger.debug(f"assign variable: {var_name} = {hook_content_eval}")
            step_variables[var_name] = hook_content_eval
            assigned.add(var_name)
        else:
            logger.error(f"Invalid hook format: {hook}")

    return assigned


def format_value(v) -> str:
    if isinstance(v, dict):
        return json.dumps(v, indent=4, ensure_ascii=False)

    if isinstance(v, httpx.Headers):
        return json.dumps(dict(v.items()), indent=4, ensure_ascii=False)

    return repr(utils.omit_long_data(v))


def _resolve_dict_vars(d: Dict, variables: Dict) -> Dict:
    """Resolve callables and $-prefixed variable references in all values of a dict."""
    resolved = {}
    for k, v in d.items():
        if callable(v):
            resolved[k] = v(variables)
        elif isinstance(v, str) and v.startswith("$") and v[1:] in variables:
            resolved[k] = variables[v[1:]]
        else:
            resolved[k] = v
    return resolved


def _resolve_request(runner: HttpRunner, step: StepData) -> tuple:
    """Resolve step template into concrete request dict with all variables/callables evaluated."""
    step_variables = runner.merge_step_variables(step.variables)
    step_variables["self"] = runner

    # Resolve callable variables.  Callables are evaluated against the
    session_vars = runner.session_variables
    for k in list(step_variables):
        v = step_variables[k]
        if callable(v) and k != "self":
            if k in session_vars and step_variables[k] != v(step_variables):
                raise ParameterError(
                    f"Variable name conflict for callable variable '{k}': "
                    f"step variables has a different value than session variables. "
                    f"Please rename the step variable or session variable to avoid conflict."
                )
            step_variables[k] = session_vars[k]

    # setup hooks — run before request construction so hooks can set
    # variables consumed by URL / JSON / header callables.
    if step.setup_hooks:
        call_hooks(step.setup_hooks, step_variables, "setup request", log_details=runner.get_config().log_details)

    request_dict = step.request.dict()

    # resolve callable or $-prefixed variable-reference URL
    if callable(step.request.url):
        request_dict["url"] = step.request.url(step_variables)
    elif (
        isinstance(step.request.url, str)
        and step.request.url.startswith("$")
        and step.request.url[1:] in step_variables
    ):
        request_dict["url"] = step_variables[step.request.url[1:]]

    # resolve callable JSON body
    if callable(step.request.req_json):
        try:
            request_dict["req_json"] = step.request.req_json(step_variables)
        except TypeError:
            request_dict["req_json"] = step.request.req_json()

    # resolve callables in params
    if request_dict.get("params"):
        request_dict["params"] = _resolve_dict_vars(request_dict["params"], step_variables)

    # prepare headers
    request_headers = request_dict.pop("headers", {})
    request_headers = {key: request_headers[key] for key in request_headers if not key.startswith(":")}
    request_headers = _resolve_dict_vars(request_headers, step_variables)
    if runner.get_config().add_request_id:
        request_headers["HRUN-Request-ID"] = f"HRUN-{runner.case_id}-{str(int(time.time() * 1000))[-6:]}"
    request_dict["headers"] = request_headers

    step_variables["request"] = request_dict

    return step_variables, request_dict


def _send_request(runner: HttpRunner, method: str, url: str, request_dict: Dict) -> tuple:
    """Map request dict to httpx kwargs, send the request, return (response, elapsed_ms)."""
    kwargs = dict(request_dict)
    kwargs.setdefault("timeout", 120)
    if "allow_redirects" in kwargs:
        kwargs["follow_redirects"] = kwargs.pop("allow_redirects")
    kwargs.setdefault("follow_redirects", True)
    kwargs.pop("stream", None)
    kwargs.pop("verify", None)

    cookies = kwargs.pop("cookies", None)
    if cookies:
        runner.client.cookies.update(cookies)

    data = kwargs.pop("data", None)
    if data is not None:
        if isinstance(data, (bytes, str)):
            kwargs["content"] = data
        else:
            kwargs["data"] = data

    params = kwargs.get("params")
    if not params and params is not None:
        kwargs.pop("params")

    request_start = time.time()
    try:
        resp = runner.client.request(method, url, **kwargs)
    except (httpx.UnsupportedProtocol, httpx.InvalidURL):
        raise
    except httpx.HTTPError as ex:
        resp = httpx.Response(status_code=0, request=httpx.Request(method, url))
        resp._error = ex

    if not resp.is_stream_consumed:
        try:
            resp.read()
        except Exception:
            pass

    response_time_ms = round((time.time() - request_start) * 1000, 2)
    return resp, response_time_ms


def _log_response(resp, response_time_ms: float, log_details: bool = True):
    """Log response status, headers, and body."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as ex:
        logger.error(f"{str(ex)}")

    if not log_details:
        return

    if not resp.is_error:
        content_size = int(dict(resp.headers).get("content-length") or 0)
        logger.info(
            f"status_code: {resp.status_code}, "
            f"response_time(ms): {response_time_ms} ms, "
            f"response_length: {content_size} bytes"
        )

    response_print = "====== response details ======\n"
    response_print += f"status_code: {resp.status_code}\n"
    response_print += f"headers: {format_value(resp.headers)}\n"

    response_headers = dict(resp.headers)
    content_type = response_headers.get("Content-Type", "")
    content_disposition = response_headers.get("Content-Disposition", "")

    try:
        resp_body = resp.json()
    except (json.JSONDecodeError, ValueError):
        if "attachment" in content_disposition.lower():
            resp_body = utils.format_response_body_for_log(resp.content, content_type, content_disposition)
        else:
            resp_body = utils.format_response_body_for_log(resp.text, content_type, content_disposition)

    response_print += f"body: {format_value(resp_body)}\n"
    logger.debug(response_print)
    if ALLURE is not None:
        ALLURE.attach(
            response_print,
            name="response details",
            attachment_type=ALLURE.attachment_type.TEXT,
        )


def run_step_request(runner: HttpRunner, step: StepData) -> StepResult:
    """run step: request"""
    step_result = StepResult(name=step.name, step_type="request", success=False)
    start_time = time.time()

    step_variables, request_dict = _resolve_request(runner, step)

    # prepare final arguments
    config = runner.get_config()
    method = request_dict.pop("method")
    url_path = request_dict.pop("url")
    url = build_url(config.base_url, url_path)
    request_dict["verify"] = config.verify
    request_dict["json"] = request_dict.pop("req_json", {})
    request_dict.pop("upload", None)

    # log request
    if config.log_details:
        request_print = "====== request details ======\n"
        request_print += f"url: {url}\n"
        request_print += f"method: {method}\n"
        for k, v in request_dict.items():
            request_print += f"{k}: {format_value(v)}\n"
        logger.debug(request_print)
        if ALLURE is not None:
            ALLURE.attach(
                request_print,
                name="request details",
                attachment_type=ALLURE.attachment_type.TEXT,
            )

    resp, response_time_ms = _send_request(runner, method, url, request_dict)
    _log_response(resp, response_time_ms, log_details=config.log_details)

    resp_obj = ResponseObject(resp)
    step_variables["response"] = resp_obj

    # teardown hooks
    teardown_assigned = set()
    if step.teardown_hooks:
        teardown_assigned = call_hooks(
            step.teardown_hooks, step_variables, "teardown request", log_details=config.log_details
        )

    # extract
    extract_mapping = resp_obj.extract(step.extract, step_variables)
    for var_name in teardown_assigned:
        if var_name not in extract_mapping:
            extract_mapping[var_name] = step_variables[var_name]
    step_result.export_vars = extract_mapping

    # validate
    try:
        resp_obj.validate(step.validators, {**step_variables, **extract_mapping})
        step_result.success = True
    except ValidationFailure:
        raise
    finally:
        response_list = resp.history + [resp]
        step_result.data = SessionData(
            success=step_result.success,
            req_resps=[get_req_resp_record(r, log_details=config.log_details) for r in response_list],
            stat=RequestMetrics(
                response_time_ms=response_time_ms,
                elapsed_ms=(
                    resp.elapsed.total_seconds() * 1000.0
                    if hasattr(resp, "elapsed") and resp.elapsed
                    else response_time_ms
                ),
                content_size=int(dict(resp.headers).get("content-length") or 0),
            ),
            validators=resp_obj.validation_results,
        )
        step_result.elapsed = time.time() - start_time

    return step_result


class BaseStep(StepProtocol):
    """Base class for step builders with shared hook/variable/retry methods."""

    def __init__(self, name: str):
        self._step = StepData(name=name)

    # --- StepProtocol interface ---

    def struct(self) -> StepData:
        return self._step

    def name(self) -> str:
        return self._step.name

    def type(self) -> str:
        raise NotImplementedError

    def run(self, runner: HttpRunner):
        raise NotImplementedError

    @property
    def retry_times(self) -> int:
        return self._step.retry_times

    @property
    def retry_interval(self) -> int:
        return self._step.retry_interval

    # --- Common builder methods ---

    def variables(self, **variables) -> "BaseStep":
        self._step.variables.update(variables)
        return self

    def retry(self, times: int, interval: int) -> "BaseStep":
        self._step.retry_times = times
        self._step.retry_interval = interval
        return self

    def setup_hook(self, hook, assign_var_name: str = None) -> "BaseStep":
        if assign_var_name:
            self._step.setup_hooks.append({assign_var_name: hook})
        else:
            self._step.setup_hooks.append(hook)
        return self

    def teardown_hook(self, hook, assign_var_name: str = None) -> "BaseStep":
        if assign_var_name:
            self._step.teardown_hooks.append({assign_var_name: hook})
        else:
            self._step.teardown_hooks.append(hook)
        return self

    def teardown_callback(self, method_name: str, *var_names: str, assign: str = None) -> "BaseStep":
        """Post-step hook: call self.<method_name>(var1, var2, ...) or resolve an expression.

        Supports three formats:
            .teardown_callback("method(arg1, arg2)", assign="result")   # method call
            .teardown_callback("method", "arg1", "arg2", assign="result")  # legacy
            .teardown_callback("response.body['key']", assign="result")  # expression
        """
        if "(" in method_name:
            name, _, args_str = method_name.partition("(")
            args_str = args_str.rstrip(")")
            parsed_args = tuple(a.strip() for a in args_str.split(",") if a.strip()) if args_str.strip() else ()
            method_name = name
            var_names = parsed_args

            _LITERALS = {"None": None, "True": True, "False": False}

            def hook(v):
                return getattr(v["self"], method_name)(*[_LITERALS[n] if n in _LITERALS else v[n] for n in var_names])

        elif "." in method_name or "[" in method_name:
            expr = method_name

            def hook(v):
                return resolve_expr(expr, v)

        else:

            def hook(v):
                return getattr(v["self"], method_name)(*[v[n] for n in var_names])

        return self.teardown_hook(hook, assign)


class RunRequest(BaseStep):
    def __init__(self, name: str):
        super().__init__(name)

    # --- StepProtocol overrides ---

    def type(self) -> str:
        if self._step.request:
            return f"request-{self._step.request.method}"
        return "request"

    def run(self, runner: HttpRunner):
        return run_step_request(runner, self._step)

    # --- HTTP methods ---

    def get(self, url) -> "RunRequest":
        self._step.request = RequestTemplate(method=MethodEnum.GET, url=url)
        return self

    def post(self, url) -> "RunRequest":
        self._step.request = RequestTemplate(method=MethodEnum.POST, url=url)
        return self

    def put(self, url) -> "RunRequest":
        self._step.request = RequestTemplate(method=MethodEnum.PUT, url=url)
        return self

    def head(self, url) -> "RunRequest":
        self._step.request = RequestTemplate(method=MethodEnum.HEAD, url=url)
        return self

    def delete(self, url) -> "RunRequest":
        self._step.request = RequestTemplate(method=MethodEnum.DELETE, url=url)
        return self

    def options(self, url) -> "RunRequest":
        self._step.request = RequestTemplate(method=MethodEnum.OPTIONS, url=url)
        return self

    def patch(self, url) -> "RunRequest":
        self._step.request = RequestTemplate(method=MethodEnum.PATCH, url=url)
        return self

    # --- Request options ---

    def params(self, **params) -> "RunRequest":
        self._step.request.params.update(params)
        return self

    def headers(self, **headers) -> "RunRequest":
        self._step.request.headers.update(headers)
        return self

    def cookies(self, **cookies) -> "RunRequest":
        self._step.request.cookies.update(cookies)
        return self

    def data(self, data) -> "RunRequest":
        self._step.request.data = data
        return self

    def body(self, data) -> "RunRequest":
        return self.data(data)

    def json(self, req_json) -> "RunRequest":
        self._step.request.req_json = req_json
        return self

    def timeout(self, timeout: float) -> "RunRequest":
        self._step.request.timeout = timeout
        return self

    def verify(self, verify: bool) -> "RunRequest":
        self._step.request.verify = verify
        return self

    def allow_redirects(self, allow_redirects: bool) -> "RunRequest":
        self._step.request.allow_redirects = allow_redirects
        return self

    # --- Extraction ---

    def extract(self) -> "RunRequest":
        return self

    def extractor(self, path_or_fn, var_name: str) -> "RunRequest":
        """Register an extractor: path_or_fn is a dotted string path or a Python callable."""
        self._step.extract[var_name] = path_or_fn
        return self

    def capture(self, var_name: str, path_or_fn) -> "RunRequest":
        return self.extractor(path_or_fn, var_name)

    jmespath = extractor

    # --- Validation ---

    def validate(self) -> "RunRequest":
        return self

    def expect(
        self,
        comparator: str,
        check_item,
        expected_value: Any,
        message: str = "",
    ) -> "RunRequest":
        self._step.validators.append({comparator: [check_item, expected_value, message]})
        return self

    def __getattr__(self, name: str):
        if name.startswith("assert_"):
            comparator = name[len("assert_") :]

            def _validator(check_item, expected_value: Any, message: str = "") -> "RunRequest":
                self._step.validators.append({comparator: [check_item, expected_value, message]})
                return self

            return _validator
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")


class ConditionalStep(BaseStep):
    """Wrap a step and only execute it when a predicate is met."""

    def __init__(self, step: BaseStep):
        super().__init__(step.name())
        self.__inner = step
        self.__predicate: Callable[[dict], bool] = lambda _vars: True

    def when(self, predicate: Callable[[dict], bool]) -> "ConditionalStep":
        self.__predicate = predicate
        return self

    def type(self) -> str:
        return self.__inner.type()

    def struct(self) -> StepData:
        return self.__inner.struct()

    def run(self, runner: HttpRunner) -> StepResult:
        step_variables = runner.merge_step_variables(self.__inner.struct().variables)
        if bool(self.__predicate(step_variables)):
            return self.__inner.run(runner)
        step = self.__inner.struct()
        result = StepResult(name=step.name, step_type=self.__inner.type(), success=True)
        result.attachment = "skipped(optional)"
        return result
