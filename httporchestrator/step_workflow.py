from typing import Callable

from loguru import logger

from httporchestrator import exceptions
from httporchestrator.models import StepData, StepResult, WorkflowSummary
from httporchestrator.runner import HttpRunner
from httporchestrator.step_request import BaseStep, call_hooks


def run_step_workflow(runner: HttpRunner, step: StepData) -> StepResult:
    """run step: referenced workflow"""
    step_result = StepResult(name=step.name, step_type="workflow")
    step_variables = runner.merge_step_variables(step.variables)
    step_export = step.export

    # setup hooks
    if step.setup_hooks:
        call_hooks(step.setup_hooks, step_variables, "setup workflow", log_details=runner.get_config().log_details)

    # step.workflow is a referenced workflow, e.g. RequestWithFunctions
    ref_case_runner = step.workflow()
    ref_case_runner.config._Config__name = step.name
    ref_case_runner.set_referenced().set_client(runner.client).set_case_id(runner.case_id).variables(
        step_variables
    ).export(step_export).run()

    # teardown hooks
    if step.teardown_hooks:
        call_hooks(
            step.teardown_hooks, step_variables, "teardown workflow", log_details=runner.get_config().log_details
        )

    summary: WorkflowSummary = ref_case_runner.get_summary()
    step_result.data = summary.step_results  # list of step data
    step_result.export_vars = summary.in_out.export_vars
    step_result.success = summary.success

    if step_result.export_vars:
        logger.info(f"export variables: {step_result.export_vars}")

    return step_result


class RunWorkflow(BaseStep):
    def __init__(self, name: str):
        super().__init__(name)

    # --- StepProtocol overrides ---

    def type(self) -> str:
        if self._step.request:
            return f"request-{self._step.request.method}"
        return "workflow"

    def run(self, runner: HttpRunner):
        return run_step_workflow(runner, self._step)

    # --- Workflow-specific builder methods ---

    def call(self, workflow: Callable) -> "RunWorkflow":
        if issubclass(workflow, HttpRunner):
            self._step.workflow = workflow
        else:
            raise exceptions.ParameterError(f"Invalid step referenced workflow: {workflow}")
        return self

    def export(self, *var_name: str) -> "RunWorkflow":
        self._step.export.extend(var_name)
        return self
