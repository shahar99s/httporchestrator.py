import httpx
import pytest

from httporchestrator import (
    CallFlow,
    ConditionalStep,
    Flow,
    ForEachStep,
    ParameterError,
    RepeatableStep,
    RequestStep,
    ValidationFailure,
)
from httporchestrator.engine.orchestrator import WorkflowEngine


def make_client(responses):
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, str(request.url))
        response = responses[key]
        if callable(response):
            response = response(request)
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_flow_run_returns_workflow_run():
    flow = Flow(
        name="demo",
        base_url="https://example.com",
        steps=(
            RequestStep("load")
            .get("/items")
            .capture("token", lambda response, state: response.json()["token"])
            .check(
                lambda response, state: response.status_code == 200,
                "status should be 200",
            ),
        ),
    ).export(["token"])

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200,
                json={"token": "abc"},
                request=httpx.Request("GET", "https://example.com/items"),
            )
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.summary.name == "demo"
    assert run.success is True
    assert run.exported == {"token": "abc"}
    assert run.session_variables["token"] == "abc"
    assert run.step_results[0].success is True


def test_nested_flow_exports_values():
    child = Flow(
        name="child",
        base_url="https://example.com",
        steps=(
            RequestStep("child request")
            .get("/child")
            .capture("child_token", lambda response, state: response.json()["token"])
            .check(
                lambda response, state: response.status_code == 200,
                "child status should be 200",
            ),
        ),
    ).export(["child_token"])

    parent = Flow(
        name="parent",
        steps=(
            CallFlow("run child")
            .use(child, flow_name="renamed child")
            .export("child_token"),
        ),
    ).export(["child_token"])

    client = make_client(
        {
            ("GET", "https://example.com/child"): httpx.Response(
                200,
                json={"token": "nested"},
                request=httpx.Request("GET", "https://example.com/child"),
            )
        }
    )

    run = WorkflowEngine().run(parent, client=client)

    assert run.exported == {"child_token": "nested"}
    assert run.step_results[0].data[0].name == "child request"


def test_when_can_skip():
    flow = Flow(
        name="optional",
        base_url="https://example.com",
        steps=(
            ConditionalStep(RequestStep("download").get("/file")).run_when(
                lambda state: False
            ),
        ),
    )

    run = WorkflowEngine().run(flow, client=make_client({}))

    assert run.step_results[0].attachment == "skipped(when)"


def test_repeat_repeats_until_condition_is_false():
    flow = Flow(
        name="repeat",
        base_url="https://example.com",
        steps=(
            RepeatableStep(
                RequestStep("load")
                .state(index=lambda state: state.get("index", 0))
                .get(lambda state: f"/items/{state['index']}")
                .after(
                    lambda response, state: {
                        "index": state["index"] + 1,
                        "last_value": response.json()["value"],
                    }
                )
                .check(
                    lambda response, state: response.status_code == 200,
                    "status should be 200",
                )
            ).run_while(lambda state: state.get("index", 0) < 3),
        ),
    ).export(["index", "last_value"])

    client = make_client(
        {
            ("GET", "https://example.com/items/0"): httpx.Response(
                200,
                json={"value": "a"},
                request=httpx.Request("GET", "https://example.com/items/0"),
            ),
            ("GET", "https://example.com/items/1"): httpx.Response(
                200,
                json={"value": "b"},
                request=httpx.Request("GET", "https://example.com/items/1"),
            ),
            ("GET", "https://example.com/items/2"): httpx.Response(
                200,
                json={"value": "c"},
                request=httpx.Request("GET", "https://example.com/items/2"),
            ),
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.success is True
    assert run.exported == {"index": 3, "last_value": "c"}
    assert len(run.step_results[0].data) == 3


class ClosableHeadResponse:
    def __init__(self, request: httpx.Request):
        self.request = request
        self.status_code = 200
        self.headers = {"Content-Length": "0"}
        self.cookies = {}
        self.encoding = None
        self.history = []
        self.is_error = False
        self.is_stream_consumed = False
        self.elapsed = None
        self.close_calls = 0

    def read(self):
        self.is_stream_consumed = True

    def raise_for_status(self):
        return None

    def close(self):
        self.close_calls += 1


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.cookies = {}

    def request(self, method, url, **kwargs):
        return self.response


def test_flow_closes_raw_response_after_step():
    flow = Flow(
        name="close response",
        base_url="https://example.com",
        steps=(
            RequestStep("head metadata")
            .head("/file")
            .check(
                lambda response, state: response.status_code == 200,
                "status should be 200",
            ),
        ),
    )

    request = httpx.Request("HEAD", "https://example.com/file")
    response = ClosableHeadResponse(request)

    run = WorkflowEngine().run(flow, client=FakeClient(response))

    assert run.success is True
    assert response.close_calls == 1


def test_failed_assertion_raises_validation_failure():
    flow = Flow(
        name="invalid",
        base_url="https://example.com",
        steps=(
            RequestStep("load")
            .get("/items")
            .check(lambda response, state: False, "forced failure"),
        ),
    )

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200,
                json={"token": "abc"},
                request=httpx.Request("GET", "https://example.com/items"),
            )
        }
    )

    with pytest.raises(ValidationFailure, match="forced failure"):
        WorkflowEngine().run(flow, client=client)


def test_prepare_updates_request_using_returned_mapping():
    flow = Flow(
        name="prepare hook",
        base_url="https://example.com",
        steps=(
            RequestStep("load")
            .state(path="items", token="old")
            .before(lambda state: {"path": "files", "token": "new-token"})
            .get(lambda state: f"/{state['path']}")
            .headers(Authorization=lambda state: f"Bearer {state['token']}")
            .check(
                lambda response, state: response.status_code == 200,
                "status should be 200",
            ),
        ),
    )

    client = make_client(
        {
            ("GET", "https://example.com/files"): lambda request: httpx.Response(
                200,
                json={"authorization": request.headers["Authorization"]},
                request=request,
            )
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.success is True
    assert run.step_results[0].success is True


def test_handle_exports_returned_updates():
    flow = Flow(
        name="after hook",
        base_url="https://example.com",
        steps=(
            RequestStep("load")
            .get("/items")
            .after(lambda response, state: {"saved_token": response.json()["token"]})
            .check(
                lambda response, state: response.status_code == 200,
                "status should be 200",
            ),
        ),
    ).export(["saved_token"])

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200,
                json={"token": "after-abc"},
                request=httpx.Request("GET", "https://example.com/items"),
            )
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.exported == {"saved_token": "after-abc"}


def test_none_from_prepare_and_handle_means_no_updates():
    flow = Flow(
        name="none hooks",
        base_url="https://example.com",
        steps=(
            RequestStep("load")
            .before(lambda state: None)
            .get("/items")
            .capture("token", lambda response, state: response.json()["token"])
            .after(lambda response, state: None)
            .check(
                lambda response, state: response.status_code == 200,
                "status should be 200",
            ),
        ),
    ).export(["token"])

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200,
                json={"token": "kept"},
                request=httpx.Request("GET", "https://example.com/items"),
            )
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.exported == {"token": "kept"}
    assert "response" not in run.exported


@pytest.mark.parametrize(
    ("builder", "message"),
    [
        (
            lambda: (
                RequestStep("bad prepare").before(lambda state: "bad").get("/items")
            ),
            "prepare must return a mapping or None",
        ),
        (
            lambda: (
                RequestStep("bad after")
                .get("/items")
                .after(lambda response, state: "bad")
            ),
            "after must return a mapping or None",
        ),
    ],
)
def test_prepare_and_handle_must_return_mapping_or_none(builder, message):
    flow = Flow(
        name="invalid hooks",
        base_url="https://example.com",
        steps=(
            builder().check(
                lambda response, state: response.status_code == 200,
                "status should be 200",
            ),
        ),
    )

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200,
                json={"token": "abc"},
                request=httpx.Request("GET", "https://example.com/items"),
            )
        }
    )

    with pytest.raises(ParameterError, match=message):
        WorkflowEngine().run(flow, client=client)


def test_retry_does_not_retry_validation_failures_by_default():
    attempts = {"count": 0}
    flow = Flow(
        name="no retry validation",
        base_url="https://example.com",
        steps=(
            RequestStep("load")
            .get("/items")
            .check(
                lambda response, state: (
                    attempts.__setitem__("count", attempts["count"] + 1) or False
                ),
                "forced failure",
            )
            .retry(1, 0),
        ),
    )

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200,
                json={"token": "abc"},
                request=httpx.Request("GET", "https://example.com/items"),
            )
        }
    )

    with pytest.raises(ValidationFailure, match="forced failure"):
        WorkflowEngine().run(flow, client=client)

    assert attempts["count"] == 1


# --- ForEachStep integration ---


def test_for_each_step_runs_template_for_every_item():
    flow = Flow(
        name="batch",
        base_url="https://example.com",
        steps=(
            ForEachStep(
                RequestStep("fetch-item")
                .get(lambda s: f"/items/{s['item']}")
                .capture("last_id", lambda response, state: response.json()["id"]),
                "ids",
            ),
        ),
    ).state(ids=[1, 2, 3]).export(["last_id"])

    client = make_client(
        {
            ("GET", "https://example.com/items/1"): httpx.Response(
                200, json={"id": 1}, request=httpx.Request("GET", "https://example.com/items/1")
            ),
            ("GET", "https://example.com/items/2"): httpx.Response(
                200, json={"id": 2}, request=httpx.Request("GET", "https://example.com/items/2")
            ),
            ("GET", "https://example.com/items/3"): httpx.Response(
                200, json={"id": 3}, request=httpx.Request("GET", "https://example.com/items/3")
            ),
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.success is True
    assert len(run.step_results[0].data) == 3
    assert run.exported["last_id"] == 3


def test_for_each_step_empty_list_succeeds_with_no_child_results():
    flow = Flow(
        name="empty-batch",
        base_url="https://example.com",
        steps=(
            ForEachStep(RequestStep("fetch-item").get(lambda s: f"/items/{s['item']}"), "ids"),
        ),
    ).state(ids=[])

    run = WorkflowEngine().run(flow, client=make_client({}))

    assert run.success is True
    assert run.step_results[0].data == []


def test_for_each_step_raises_when_variable_missing():
    flow = Flow(
        name="missing-var",
        base_url="https://example.com",
        steps=(
            ForEachStep(RequestStep("fetch-item").get("/items"), "no_such_var"),
        ),
    )

    with pytest.raises(ParameterError, match="no_such_var"):
        WorkflowEngine().run(flow, client=make_client({}))


def test_for_each_step_bind_as_changes_item_key():
    flow = Flow(
        name="custom-bind",
        base_url="https://example.com",
        steps=(
            ForEachStep(
                RequestStep("fetch-item")
                .get(lambda s: s["url"])
                .capture("last_url", lambda response, state: response.json()["url"]),
                "urls",
            ).bind_as("url"),
        ),
    ).state(urls=["https://example.com/a"]).export(["last_url"])

    client = make_client(
        {
            ("GET", "https://example.com/a"): httpx.Response(
                200,
                json={"url": "https://example.com/a"},
                request=httpx.Request("GET", "https://example.com/a"),
            )
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.exported["last_url"] == "https://example.com/a"
    assert "url" not in run.session_variables


# --- WorkflowRun introspection ---


def test_workflow_run_variables_aliases_session_variables():
    flow = Flow(
        name="alias",
        base_url="https://example.com",
        steps=(
            RequestStep("load")
            .get("/items")
            .capture("token", lambda response, state: response.json()["token"]),
        ),
    )

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200,
                json={"token": "xyz"},
                request=httpx.Request("GET", "https://example.com/items"),
            )
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.variables is run.session_variables
    assert run.variables["token"] == "xyz"


def test_workflow_run_find_step_returns_result_by_name():
    flow = Flow(
        name="find",
        base_url="https://example.com",
        steps=(
            RequestStep("load").get("/items"),
            RequestStep("save").get("/other"),
        ),
    )

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200, json={}, request=httpx.Request("GET", "https://example.com/items")
            ),
            ("GET", "https://example.com/other"): httpx.Response(
                200, json={}, request=httpx.Request("GET", "https://example.com/other")
            ),
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.find_step("load") is run.step_results[0]
    assert run.find_step("save") is run.step_results[1]
    assert run.find_step("nonexistent") is None


def test_step_result_skipped_property():
    flow = Flow(
        name="skip-check",
        base_url="https://example.com",
        steps=(
            RequestStep("always-skip").get("/file").when(lambda state: False),
        ),
    )

    run = WorkflowEngine().run(flow, client=make_client({}))

    result = run.find_step("always-skip")
    assert result is not None
    assert result.skipped is True
    assert run.step_results[0].skipped is True


def test_step_result_skipped_false_for_executed_steps():
    flow = Flow(
        name="ran",
        base_url="https://example.com",
        steps=(RequestStep("load").get("/items"),),
    )

    client = make_client(
        {
            ("GET", "https://example.com/items"): httpx.Response(
                200, json={}, request=httpx.Request("GET", "https://example.com/items")
            )
        }
    )

    run = WorkflowEngine().run(flow, client=client)

    assert run.step_results[0].skipped is False
