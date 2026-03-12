from typing import Callable, Union

from httporchestrator import HttpRunner
from httporchestrator.http_models import RequestTemplate
from httporchestrator.models import StepData, StepResult, Workflow
from httporchestrator.step_request import RunRequest
from httporchestrator.step_workflow import RunWorkflow


class Step(object):
    def __init__(
        self,
        step: Union[
            RunRequest,
            RunWorkflow,
        ],
    ):
        self.__step = step

    @property
    def request(self) -> RequestTemplate:
        return self.__step.struct().request

    @property
    def workflow(self) -> Workflow:
        return self.__step.struct().workflow

    @property
    def retry_times(self) -> int:
        return self.__step.struct().retry_times

    @property
    def retry_interval(self) -> int:
        return self.__step.struct().retry_interval

    def struct(self) -> StepData:
        return self.__step.struct()

    def name(self) -> str:
        return self.__step.name()

    def type(self) -> str:
        return self.__step.type()

    def run(self, runner: HttpRunner) -> StepResult:
        return self.__step.run(runner)


class OptionalStep(Step):
    """
    Wrap a step and only execute it when a condition is met.
    """

    def __init__(self, step: Step):
        super().__init__(step)
        self.__step = step
        self.__predicate: Callable[[dict], bool] = lambda _vars: True

    def when(self, predicate: Callable[[dict], bool]) -> "OptionalStep":
        self.__predicate = predicate
        return self

    def run(self, runner: HttpRunner) -> StepResult:
        step_variables = runner.merge_step_variables(self.__step.struct().variables)
        should_run = bool(self.__predicate(step_variables))
        if should_run:
            return self.__step.run(runner)
        step = self.__step.struct()
        result = StepResult(name=step.name, step_type=self.__step.type(), success=True)
        result.attachment = "skipped(optional)"
        return result
