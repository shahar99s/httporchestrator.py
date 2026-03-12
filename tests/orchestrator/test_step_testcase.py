import unittest

from httporchestrator import Config
from httporchestrator.runner import HttpRunner
from httporchestrator.step_workflow import RunWorkflow
from tests.orchestrator.test_step_request import WorkflowRequestWithFunctions


class InspectReferencedCase(HttpRunner):
    last_summary_name = None

    config = Config("original referenced workflow")
    steps = []

    def run(self, param=None):
        result = super().run(param)
        type(self).last_summary_name = self.get_summary().name
        return result


class TestRunWorkflow(unittest.TestCase):
    def setUp(self):
        self.runner = WorkflowRequestWithFunctions()
        self.runner.run()

    def test_run_workflow_by_path(self):

        step_result = RunWorkflow("run referenced workflow").call(WorkflowRequestWithFunctions).run(self.runner)
        self.assertTrue(step_result.success)
        self.assertEqual(step_result.name, "run referenced workflow")
        self.assertEqual(len(step_result.data), 3)
        self.assertEqual(step_result.data[0].name, "get with params")
        self.assertEqual(step_result.data[1].name, "post raw text")
        self.assertEqual(step_result.data[2].name, "post form data")

    def test_run_workflow_overrides_referenced_case_name(self):
        InspectReferencedCase.last_summary_name = None

        step_result = RunWorkflow("override referenced workflow name").call(InspectReferencedCase).run(self.runner)

        self.assertTrue(step_result.success)
        self.assertEqual(
            InspectReferencedCase.last_summary_name,
            "override referenced workflow name",
        )
