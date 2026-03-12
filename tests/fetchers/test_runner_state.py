from fetchers.base_fetcher import BaseFetcher


class DummyFetcher(BaseFetcher):
    NAME = "Dummy"
    BASE_URL = ""
    steps = []

    def build_marker(self):
        return "marker-value"


def test_runner_preserves_fetcher_parser_functions_across_run():
    fetcher = DummyFetcher()

    assert fetcher.build_marker() == "marker-value"

    fetcher.run()

    assert fetcher.build_marker() == "marker-value"


def test_runner_instances_keep_independent_variable_state():
    first = DummyFetcher().variables({"shared_var": "first"})
    second = DummyFetcher()

    first.run()
    second.run()

    assert first.get_summary().in_out.config_vars["shared_var"] == "first"
    assert "shared_var" not in second.get_summary().in_out.config_vars
