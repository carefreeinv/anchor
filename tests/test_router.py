from anchor_client import Fleet
from router import endpoint_detail, fleet_summary_block, route, summarize_endpoints


class FakeEndpoint:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, max_tokens=8, **kwargs):
        return self.reply


class FakeFleet:
    def __init__(self, reply=None, raise_on_pick=False):
        self.reply = reply
        self.raise_on_pick = raise_on_pick

    def pick(self, role):
        if self.raise_on_pick:
            raise LookupError("no endpoint")
        return FakeEndpoint(self.reply)


def test_architecture_task_routes_to_planner():
    assert route("what's the right architecture for this migration?", FakeFleet()) == "planner"


def test_review_task_routes_to_critic():
    assert route("please review this diff before merge", FakeFleet()) == "critic"


def test_race_condition_task_routes_to_critic():
    assert route("investigate this race condition in the worker pool", FakeFleet()) == "critic"


def test_rename_task_routes_to_tuner():
    assert route("rename this variable across the file", FakeFleet()) == "tuner"


def test_boilerplate_catchall_routes_to_executor_without_model_classify():
    assert route("implement dark mode toggle", FakeFleet(), use_model=False) == "executor"


def test_catchall_uses_model_classify_when_enabled():
    fleet = FakeFleet(reply="planner")
    assert route("implement dark mode toggle", fleet, use_model=True) == "planner"


def test_model_classify_ignores_invalid_reply():
    fleet = FakeFleet(reply="not-a-real-role")
    assert route("implement dark mode toggle", fleet, use_model=True) == "executor"


def test_model_classify_failure_falls_back_to_executor():
    fleet = FakeFleet(raise_on_pick=True)
    assert route("implement dark mode toggle", fleet, use_model=True) == "executor"


def test_specific_rule_wins_even_with_model_classify_enabled():
    # A non-executor rule match should short-circuit before ever touching the fleet.
    fleet = FakeFleet(raise_on_pick=True)
    assert route("audit this module for bugs", fleet, use_model=True) == "critic"


def _registry(tmp_path, body):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(body)
    return Fleet(registry)


def test_summarize_endpoints_includes_name_tier_and_capability(tmp_path):
    fleet = _registry(
        tmp_path,
        "endpoints:\n"
        "  - name: h100-nemotron\n    tier: reasoner\n"
        "    base_url: http://10.0.1.11:8000/v1\n    model: nvidia/nemotron\n"
        "    quirks: {think_toggle: nemotron, max_context: 65536}\n"
        "roles: {}\n",
    )
    lines = summarize_endpoints(fleet)
    assert len(lines) == 1
    assert "h100-nemotron" in lines[0]
    assert "reasoner" in lines[0]
    assert "ctx=65536" in lines[0]
    assert "hybrid-reasoning (nemotron)" in lines[0]


def test_summarize_endpoints_omits_context_when_unset(tmp_path):
    fleet = _registry(
        tmp_path,
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "roles: {}\n",
    )
    assert "ctx=unspecified" in summarize_endpoints(fleet)[0]


def test_summarize_endpoints_never_leaks_url_or_model(tmp_path):
    fleet = _registry(
        tmp_path,
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://10.0.1.99:8000/v1\n"
        "    model: secret-internal-model-name\n"
        "roles: {}\n",
    )
    line = summarize_endpoints(fleet)[0]
    assert "10.0.1.99" not in line
    assert "http" not in line
    assert "secret-internal-model-name" not in line


def test_summarize_endpoints_respects_line_cap(tmp_path):
    fleet = _registry(
        tmp_path,
        "endpoints:\n"
        "  - name: an-endpoint-with-a-very-long-name-that-keeps-going-and-going\n"
        "    tier: executor-heavy\n    base_url: http://a/v1\n    model: m\n"
        "    quirks: {reasoning_effort: high}\n"
        "roles: {}\n",
    )
    line = summarize_endpoints(fleet)[0]
    assert len(line) <= 100


def test_summarize_endpoints_empty_fleet_returns_empty_list():
    class NoEndpoints:
        pass

    assert summarize_endpoints(NoEndpoints()) == []


def test_fleet_summary_block_empty_when_no_endpoints():
    class NoEndpoints:
        pass

    assert fleet_summary_block(NoEndpoints()) == ""


def test_fleet_summary_block_has_header_and_lines(tmp_path):
    fleet = _registry(
        tmp_path,
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "roles: {}\n",
    )
    block = fleet_summary_block(fleet)
    assert block.startswith("FLEET SUMMARY")
    assert "lookup_endpoint" in block
    assert "a · swarm" in block


def test_endpoint_detail_returns_full_non_secret_fields(tmp_path):
    fleet = _registry(
        tmp_path,
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "    quirks: {strip_think: true}\n"
        "roles: {}\n",
    )
    detail = endpoint_detail(fleet, "a")
    assert "http://a/v1" in detail
    assert "m" in detail
    assert "strip_think=True" in detail


def test_endpoint_detail_unknown_name_lists_known_names(tmp_path):
    fleet = _registry(
        tmp_path,
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "roles: {}\n",
    )
    detail = endpoint_detail(fleet, "nope")
    assert "nope" in detail
    assert "a" in detail
