from anchor_client import Endpoint
from prompt_tuner import find_endpoint, inject_budget, render_budget, tune

SPEC_WITH_BUDGET = (
    "# Task: <title>\n\n"
    "## Budget\n"
    "- Context window: <n tokens>\n"
    "- Output ceiling: <n tokens>\n"
    "- Spec + provided context exceeding this budget means the task is decomposed wrong "
    "— reject back to the planner, never truncate silently.\n\n"
    "## Goal\nfix the thing\n"
)


class FakeEndpoint:
    def __init__(self, reply):
        self.reply = reply
        self.name = "fake-tuner"
        self.model = "fake-model"
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.reply


class FakeFleet:
    def __init__(self, reply, endpoints=()):
        self.ep = FakeEndpoint(reply)
        self.endpoints = list(endpoints)

    def pick(self, role):
        return self.ep


def test_find_endpoint_matches_by_name():
    registered = Endpoint(name="h100-executor", tier="executor-heavy",
                          base_url="http://x", model="m", quirks={"max_context": 32768})
    fleet = FakeFleet("spec", endpoints=[registered])
    assert find_endpoint(fleet, "h100-executor") is registered
    assert find_endpoint(fleet, "does-not-exist") is None


def test_render_budget_unspecified_when_target_unknown():
    assert render_budget(None, "template text", "rough text") == ("unspecified", "unspecified")


def test_render_budget_unspecified_when_endpoint_has_no_max_context():
    ep = Endpoint(name="no-ceiling", tier="executor", base_url="http://x", model="m", quirks={})
    assert render_budget(ep, "template text", "rough text") == ("unspecified", "unspecified")


def test_render_budget_computes_numeric_ceiling_for_registered_endpoint():
    ep = Endpoint(name="h100-executor", tier="executor-heavy", base_url="http://x",
                  model="m", quirks={"max_context": 32768})
    context_window, output_ceiling = render_budget(ep, "template text", "rough text")
    assert context_window == "32768"
    assert output_ceiling.isdigit()
    assert int(output_ceiling) < 32768


def test_inject_budget_overwrites_existing_section():
    out = inject_budget(SPEC_WITH_BUDGET, "32768", "32000")
    assert "Context window: 32768" in out
    assert "Output ceiling: 32000" in out
    assert "<n tokens>" not in out
    assert "## Goal\nfix the thing" in out  # rest of the spec untouched


def test_inject_budget_appends_section_when_model_dropped_it():
    spec = "# Task: <title>\n\n## Goal\ndo the thing\n"
    out = inject_budget(spec, "unspecified", "unspecified")
    assert "## Budget" in out
    assert "Context window: unspecified" in out
    assert "## Goal\ndo the thing" in out


def test_tune_injects_numeric_budget_for_registered_endpoint():
    registered = Endpoint(name="h100-executor", tier="executor-heavy", base_url="http://x",
                          model="m", quirks={"max_context": 32768})
    fleet = FakeFleet(SPEC_WITH_BUDGET, endpoints=[registered])
    spec = tune("fix the login bug", fleet, target="h100-executor")
    assert "Context window: 32768" in spec
    assert "unspecified" not in spec


def test_tune_leaves_budget_unspecified_when_no_target_given():
    fleet = FakeFleet(SPEC_WITH_BUDGET, endpoints=[])
    spec = tune("fix the login bug", fleet, target=None)
    assert "Context window: unspecified" in spec
    assert "Output ceiling: unspecified" in spec


def test_tune_leaves_budget_unspecified_when_target_not_registered():
    fleet = FakeFleet(SPEC_WITH_BUDGET, endpoints=[])
    spec = tune("fix the login bug", fleet, target="ghost-endpoint")
    assert "Context window: unspecified" in spec
