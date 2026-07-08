from router import route


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
