import pytest

from httporchestrator import (
    CallFlow,
    ConditionalStep,
    Flow,
    ForEachStep,
    RepeatableStep,
    RequestStep,
)
from httporchestrator.exceptions import ParameterError


def test_request_builders_are_immutable_and_accumulate_callbacks():
    def before(state):
        return {"token": "abc"}

    def capture(response, state):
        return {"ok": True}

    def after(response, state):
        return {"saved": True}

    def assertion(response, state):
        return True

    step = (
        RequestStep("load item")
        .get("/items")
        .state(item_id=1)
        .before(before)
        .capture("result", capture)
        .after(after)
        .check(assertion, "should pass")
        .retry(2, 1)
    )

    assert step.name == "load item"
    assert step.method.value == "GET"
    assert step.url == "/items"
    assert step.state_values == {"item_id": 1}
    assert step.before_hooks == (before,)
    assert len(step.captures) == 1
    assert step.after_hooks == (after,)
    assert len(step.assertions) == 1
    assert step.retry_policy.times == 2
    assert step.retry_policy.interval == 1


def test_call_flow_requires_flow_instance():
    child = Flow(name="child")
    step = CallFlow("run child").use(child, flow_name="nested").export("token")

    assert step.flow is child
    assert step.flow_name == "nested"
    assert step.exports == ("token",)


def test_call_flow_rejects_non_flow():
    with pytest.raises(ParameterError):
        CallFlow("bad").use(object())


def test_when_wraps_inner_step():
    wrapped = ConditionalStep(RequestStep("maybe").get("/path")).run_when(
        lambda state: state.get("enabled") is True
    )

    assert wrapped.name == "maybe"
    assert wrapped.step.name == "maybe"


def test_repeat_wraps_inner_step():
    wrapped = RepeatableStep(RequestStep("loop").get("/path")).run_while(
        lambda state: state.get("enabled") is True
    )

    assert wrapped.name == "loop"
    assert wrapped.step.name == "loop"


def test_when_fluent_method_wraps_in_conditional_step():
    predicate = lambda state: state.get("flag") is True
    step = RequestStep("guarded").get("/path")
    conditional = step.when(predicate)

    assert isinstance(conditional, ConditionalStep)
    assert conditional.name == "guarded"
    assert conditional.step is step
    assert conditional.predicate is predicate


def test_when_is_independent_of_run_when():
    step = RequestStep("guarded").get("/path")
    pred_a = lambda state: True
    pred_b = lambda state: False

    via_when = step.when(pred_a)
    via_run_when = ConditionalStep(step).run_when(pred_b)

    assert via_when.predicate is pred_a
    assert via_run_when.predicate is pred_b


def test_for_each_step_builder():
    template = RequestStep("fetch").get(lambda s: f"/items/{s['item']}")
    step = ForEachStep(template, "urls").bind_as("url")

    assert step.name == "fetch"
    assert step.variable == "urls"
    assert step.item_var == "url"
    assert step.step is template


def test_while_fluent_method_wraps_in_repeatable_step():
    predicate = lambda state: state.get("count", 0) < 3
    step = RequestStep("loop").get("/path")
    repeatable = step.while_(predicate)

    assert isinstance(repeatable, RepeatableStep)
    assert repeatable.name == "loop"
    assert repeatable.step is step
    assert repeatable.predicate is predicate


def test_for_each_fluent_method_wraps_in_for_each_step():
    step = RequestStep("fetch").get(lambda s: f"/items/{s['item']}")
    foreach = step.for_each("ids")

    assert isinstance(foreach, ForEachStep)
    assert foreach.name == "fetch"
    assert foreach.step is step
    assert foreach.variable == "ids"


def test_after_docstring_states_contract():
    assert "mapping" in (RequestStep.after.__doc__ or "").lower()
