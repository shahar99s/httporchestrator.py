import unittest

from httporchestrator import Config, HttpRunner, RunRequest


class WorkflowRequestWithFunctions(HttpRunner):
    config = (
        Config("request methods workflow with functions")
        .variables(
            **{
                "foo1": "config_bar1",
                "foo2": "config_bar2",
                "expect_foo1": "config_bar1",
                "expect_foo2": "config_bar2",
            }
        )
        .base_url("https://postman-echo.com")
        .verify(False)
        .export(*("foo3",))
    )

    steps = [
        RunRequest("get with params")
        .variables(**{"foo1": "bar11", "foo2": "bar21", "sum_v": "3"})
        .get("/get")
        .params(**{"foo1": "bar11", "foo2": "bar21", "sum_v": "3"})
        .headers(**{"User-Agent": "HttpRunner/v4.3.5"})
        .extract()
        .extractor("body.args.foo2", "foo3")
        .validate()
        .assert_equal("status_code", 200)
        .assert_equal("body.args.foo1", "bar11")
        .assert_equal("body.args.sum_v", "3")
        .assert_equal("body.args.foo2", "bar21"),
        RunRequest("post raw text")
        .variables(**{"foo1": "bar12", "foo3": "bar32"})
        .post("/post")
        .headers(
            **{
                "User-Agent": "HttpRunner/v4.3.5",
                "Content-Type": "text/plain",
            }
        )
        .data("This is expected to be sent back as part of response body: bar12-config_bar2-bar32.")
        .validate()
        .assert_equal("status_code", 200)
        .assert_equal(
            "body.data",
            "This is expected to be sent back as part of response body: bar12-config_bar2-bar32.",
        )
        .assert_type_match("body.json", "None")
        .assert_type_match("body.json", "NoneType")
        .assert_type_match("body.json", None),
        RunRequest("post form data")
        .variables(**{"foo2": "bar23"})
        .post("/post")
        .headers(
            **{
                "User-Agent": "HttpRunner/v4.3.5",
                "Content-Type": "application/x-www-form-urlencoded",
            }
        )
        .data("foo1=config_bar1&foo2=bar23&foo3=bar21")
        .validate()
        .assert_equal("status_code", 200, "response status code should be 200")
        .assert_equal("body.form.foo1", "config_bar1")
        .assert_equal("body.form.foo2", "bar23")
        .assert_equal("body.form.foo3", "bar21"),
    ]


class TestRunRequest(unittest.TestCase):
    def test_run_request(self):
        runner = WorkflowRequestWithFunctions().run()
        summary = runner.get_summary()
        self.assertTrue(summary.success)
        self.assertEqual(summary.name, "request methods workflow with functions")
        self.assertEqual(len(summary.step_results), 3)
        self.assertEqual(summary.step_results[0].name, "get with params")
        self.assertEqual(summary.step_results[1].name, "post raw text")
        self.assertEqual(summary.step_results[2].name, "post form data")
