import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from anchor_client import (
    MAX_RETRIES,
    NVIDIA_BUILD_ENDPOINT_NAME,
    EmptyAssistantText,
    Endpoint,
    Fleet,
    RegistryConflict,
    load_prompt,
    project_root_from,
    resolve_doctrine_path,
    write_endpoint_nick,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "openai_chat"


def make_response(content="ok"):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def make_response_from_fixture(name: str):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


@patch("anchor_client.requests.post")
def test_gemma_system_role_folds_into_first_user_turn(mock_post):
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="gemma3",
                  quirks={"system_role": "fold_into_user"})

    ep.chat([{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}])

    sent = mock_post.call_args.kwargs["json"]["messages"]
    assert all(m["role"] != "system" for m in sent)
    assert sent[0]["role"] == "user"
    assert "SYS" in sent[0]["content"] and "USER" in sent[0]["content"]


@patch("anchor_client.requests.post")
def test_qwen3_think_toggle_appends_suffix(mock_post):
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="executor", base_url="http://x/v1", model="qwen3",
                  quirks={"think_toggle": "qwen3"})

    ep.chat([{"role": "user", "content": "hi"}], thinking=True)
    assert mock_post.call_args.kwargs["json"]["messages"][-1]["content"].endswith("/think")

    ep.chat([{"role": "user", "content": "hi"}], thinking=False)
    assert mock_post.call_args.kwargs["json"]["messages"][-1]["content"].endswith("/no_think")


@patch("anchor_client.requests.post")
def test_nemotron_think_toggle_sets_system_line(mock_post):
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="reasoner", base_url="http://x/v1", model="nemotron",
                  quirks={"think_toggle": "nemotron"})

    ep.chat([{"role": "user", "content": "hi"}], thinking=True)
    sent = mock_post.call_args.kwargs["json"]["messages"]
    assert sent[0] == {"role": "system", "content": "detailed thinking on"}

    ep.chat([{"role": "system", "content": "existing"}, {"role": "user", "content": "hi"}], thinking=False)
    sent = mock_post.call_args.kwargs["json"]["messages"]
    assert sent[0]["content"].startswith("detailed thinking off")
    assert "existing" in sent[0]["content"]


@patch("anchor_client.requests.post")
def test_strip_think_removes_think_blocks(mock_post):
    mock_post.return_value = make_response("<think>reasoning</think>final answer")
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m", quirks={"strip_think": True})

    out = ep.chat([{"role": "user", "content": "hi"}])

    assert out == "final answer"
    assert "<think>" not in out


def test_project_root_from_source_scripts(tmp_path):
    root = tmp_path / "myproj"
    (root / "scripts").mkdir(parents=True)
    f = root / "scripts" / "anchor_client.py"
    f.touch()
    assert project_root_from(f) == root


def test_project_root_from_source_mcp(tmp_path):
    root = tmp_path / "myproj"
    (root / "mcp" / "project-orchestrator").mkdir(parents=True)
    f = root / "mcp" / "project-orchestrator" / "server.py"
    f.touch()
    assert project_root_from(f) == root


def test_project_root_from_dot_anchor_scripts(tmp_path):
    root = tmp_path / "myproj"
    (root / ".anchor" / "scripts").mkdir(parents=True)
    f = root / ".anchor" / "scripts" / "anchor_client.py"
    f.touch()
    assert project_root_from(f) == root


def test_project_root_from_dot_anchor_mcp(tmp_path):
    root = tmp_path / "myproj"
    (root / ".anchor" / "mcp" / "project-orchestrator").mkdir(parents=True)
    f = root / ".anchor" / "mcp" / "project-orchestrator" / "server.py"
    f.touch()
    assert project_root_from(f) == root


def test_resolve_doctrine_path_dual_reads_legacy_anchor_prefix(tmp_path):
    root = tmp_path / "myproj"
    (root / "anchor" / "system-prompts").mkdir(parents=True)
    target = root / "anchor" / "system-prompts" / "mythos-core.md"
    target.write_text("legacy content", encoding="utf-8")

    resolved = resolve_doctrine_path(".anchor/system-prompts/mythos-core.md", root=root)

    assert resolved == target


def test_resolve_doctrine_path_prefers_dot_anchor_when_both_exist(tmp_path):
    root = tmp_path / "myproj"
    (root / "anchor" / "system-prompts").mkdir(parents=True)
    (root / ".anchor" / "system-prompts").mkdir(parents=True)
    (root / "anchor" / "system-prompts" / "mythos-core.md").write_text("legacy", encoding="utf-8")
    scaffold = root / ".anchor" / "system-prompts" / "mythos-core.md"
    scaffold.write_text("scaffolded", encoding="utf-8")

    resolved = resolve_doctrine_path(".anchor/system-prompts/mythos-core.md", root=root)

    assert resolved == scaffold


def test_resolve_doctrine_path_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_doctrine_path("anchor/does-not-exist.md", root=tmp_path)


def test_fleet_pick_round_robins_within_tier(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "  - name: b\n    tier: swarm\n    base_url: http://b/v1\n    model: m\n"
        "roles:\n  executor: [swarm]\n"
    )
    fleet = Fleet(registry, probe_health=False)

    picks = [fleet.pick("executor").name for _ in range(4)]

    assert picks == ["a", "b", "a", "b"]


def test_fleet_pick_raises_when_no_endpoint_available_for_role(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "roles:\n  planner: [frontier]\n"
    )
    fleet = Fleet(registry, probe_health=False, prefer_local=True)

    with pytest.raises(LookupError):
        fleet.pick("planner")


def _clear_api_keys(monkeypatch):
    for name in ("ANCHOR_API_KEY", "NVIDIA_API_KEY", "NGC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@patch("anchor_client.requests.post")
def test_no_auth_header_sent_when_api_key_unset(mock_post, monkeypatch):
    _clear_api_keys(monkeypatch)
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m")

    ep.chat([{"role": "user", "content": "hi"}])

    assert "Authorization" not in mock_post.call_args.kwargs["headers"]


@patch("anchor_client.requests.post")
def test_auth_header_sent_when_api_key_set(mock_post, monkeypatch):
    _clear_api_keys(monkeypatch)
    monkeypatch.setenv("ANCHOR_API_KEY", "secret")
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m")

    ep.chat([{"role": "user", "content": "hi"}])

    assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"


@patch("anchor_client.requests.post")
def test_auth_header_falls_back_to_nvidia_api_key(mock_post, monkeypatch):
    _clear_api_keys(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="reasoner", base_url="http://x/v1", model="m")

    ep.chat([{"role": "user", "content": "hi"}])

    assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer nvapi-test"


def test_load_dotenv_setdefault_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("NVIDIA_API_KEY=from-file\nALREADY=file\n", encoding="utf-8")
    monkeypatch.setenv("ALREADY", "exported")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    loaded = __import__("anchor_client").load_dotenv(env_file)
    assert loaded == env_file.resolve()
    assert os.environ["NVIDIA_API_KEY"] == "from-file"
    assert os.environ["ALREADY"] == "exported"


def test_load_dotenv_reads_primary_checkout_from_worktree(tmp_path, monkeypatch):
    import subprocess

    import anchor_client

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True,
    )
    (repo / "README").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True,
    )
    (repo / ".env").write_text("NVIDIA_API_KEY=from-primary\n", encoding="utf-8")
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat", str(wt)],
        cwd=repo, check=True, capture_output=True,
    )
    assert not (wt / ".env").exists()
    monkeypatch.chdir(wt)
    monkeypatch.setattr(anchor_client, "REPO_ROOT", wt)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    loaded = anchor_client.load_dotenv()
    assert loaded == (repo / ".env").resolve()
    assert os.environ["NVIDIA_API_KEY"] == "from-primary"


@patch("anchor_client.time.sleep")
@patch("anchor_client.requests.post")
def test_chat_retries_on_connection_error_then_succeeds(mock_post, mock_sleep):
    mock_post.side_effect = [requests.exceptions.ConnectionError("down"), make_response("recovered")]
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m")

    out = ep.chat([{"role": "user", "content": "hi"}])

    assert out == "recovered"
    assert mock_post.call_count == 2
    assert mock_sleep.call_count == 1


@patch("anchor_client.time.sleep")
@patch("anchor_client.requests.post")
def test_chat_raises_after_exhausting_retries(mock_post, mock_sleep):
    mock_post.side_effect = requests.exceptions.ConnectionError("down")
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m")

    with pytest.raises(requests.exceptions.ConnectionError):
        ep.chat([{"role": "user", "content": "hi"}])

    assert mock_post.call_count == MAX_RETRIES + 1


@patch("anchor_client.requests.post")
def test_system_suffix_appends_guardrail_to_system_message(mock_post):
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="executor", base_url="http://x/v1", model="m",
                  quirks={"system_suffix": "GUARDRAIL LINE"})

    ep.chat([{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}])

    sent = mock_post.call_args.kwargs["json"]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[0]["content"] == "SYS\nGUARDRAIL LINE"


@patch("anchor_client.requests.post")
def test_system_suffix_survives_gemma_fold(mock_post):
    # R1/Gemma-style endpoints: guardrail must ride into the folded user turn.
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="reasoner", base_url="http://x/v1", model="r1",
                  quirks={"system_role": "fold_into_user", "system_suffix": "LOW-CONFIDENCE rule"})

    ep.chat([{"role": "system", "content": "SYS"}, {"role": "user", "content": "task"}])

    sent = mock_post.call_args.kwargs["json"]["messages"]
    assert all(m["role"] != "system" for m in sent)
    assert "LOW-CONFIDENCE rule" in sent[0]["content"] and "task" in sent[0]["content"]


@patch("anchor_client.requests.post")
def test_temperature_quirk_overrides_default_but_not_caller(mock_post):
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="executor", base_url="http://x/v1", model="mistral",
                  quirks={"temperature": 0.15})

    ep.chat([{"role": "user", "content": "hi"}])
    assert mock_post.call_args.kwargs["json"]["temperature"] == 0.15

    ep.chat([{"role": "user", "content": "hi"}], temperature=0.9)
    assert mock_post.call_args.kwargs["json"]["temperature"] == 0.9


@patch("anchor_client.requests.post")
def test_thinking_never_greedy(mock_post):
    # Qwen3/R1 loop under greedy decoding in reasoning mode — temp 0 must be clamped.
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="reasoner", base_url="http://x/v1", model="qwen3",
                  quirks={"think_toggle": "qwen3"})

    ep.chat([{"role": "user", "content": "hi"}], thinking=True, temperature=0)

    assert mock_post.call_args.kwargs["json"]["temperature"] == 0.6


@patch("anchor_client.requests.post")
def test_sampling_quirk_merged_but_temperature_wins(mock_post):
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="executor", base_url="http://x/v1", model="qwen3",
                  quirks={"sampling_thinking": {"top_p": 0.95, "top_k": 20, "temperature": 0.99}})

    ep.chat([{"role": "user", "content": "hi"}], thinking=True)

    payload = mock_post.call_args.kwargs["json"]
    assert payload["top_p"] == 0.95 and payload["top_k"] == 20
    assert payload["temperature"] == 0.6  # resolved temperature beats the sampling dict


@patch("anchor_client.requests.post")
def test_max_context_caps_completion_tokens(mock_post):
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m",
                  quirks={"max_context": 8192})

    ep.chat([{"role": "user", "content": "hi"}], max_tokens=16384)

    assert mock_post.call_args.kwargs["json"]["max_tokens"] == 8192


def test_resolve_doctrine_path_prefers_given_then_dot_anchor(tmp_path):
    # Scaffolded-style: only .anchor/ exists
    dest = tmp_path / ".anchor" / "templates"
    dest.mkdir(parents=True)
    (dest / "plan.md").write_text("PLAN", encoding="utf-8")
    path = resolve_doctrine_path("anchor/templates/plan.md", root=tmp_path)
    assert path == dest / "plan.md"
    assert path.read_text(encoding="utf-8") == "PLAN"

    # Explicit .anchor/ form
    assert resolve_doctrine_path(".anchor/templates/plan.md", root=tmp_path) == dest / "plan.md"

    # Source-style: only anchor/ exists
    src_root = tmp_path / "src"
    src = src_root / "anchor" / "system-prompts"
    src.mkdir(parents=True)
    (src / "mythos-core.md").write_text("CORE", encoding="utf-8")
    assert resolve_doctrine_path(
        "anchor/system-prompts/mythos-core.md", root=src_root
    ).read_text(encoding="utf-8") == "CORE"


def test_load_prompt_reads_source_tree():
    text = load_prompt("anchor/system-prompts/mythos-core.md")
    assert "FIT CHECK" in text or "fit check" in text.lower() or "Mythos" in text or len(text) > 100


def test_endpoint_sends_reasoning_effort_quirk(monkeypatch):
    """Grok endpoint quirk injects reasoning_effort into the OpenAI body."""
    import anchor_client as ac
    from anchor_client import Endpoint

    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content": "ok\n## Result\nx\n## How to verify\ny"}}]}

    def fake_post(url, *, json, headers, timeout):
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(ac, "_post_with_retry", fake_post)
    ep = Endpoint(
        name="grok",
        tier="mid",
        base_url="http://example/v1",
        model="grok-4.6",
        quirks={"reasoning_effort": "xhigh"},
    )
    ep.chat([{"role": "user", "content": "hi"}], max_tokens=16)
    assert captured["json"].get("reasoning_effort") == "xhigh"


def test_endpoint_overlay_effort_fills_chat_when_quirk_absent(monkeypatch):
    import anchor_client as ac
    from anchor_client import Endpoint

    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, *, json, headers, timeout):
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(ac, "_post_with_retry", fake_post)
    ep = Endpoint(
        name="grok",
        tier="mid",
        base_url="http://example/v1",
        model="grok-4.6",
        effort="low",
    )
    ep.chat([{"role": "user", "content": "hi"}], max_tokens=16)
    assert captured["json"].get("reasoning_effort") == "low"


def test_fixtures_load():
    for name in (
        "empty_content_reasoning_length.json",
        "content_after_reasoning.json",
        "inline_think_tags.json",
        "empty_content_no_reasoning.json",
    ):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert data["choices"][0]["message"] is not None


@patch("anchor_client.requests.post")
def test_empty_content_with_reasoning_retries_then_returns(mock_post):
    mock_post.side_effect = [
        make_response_from_fixture("empty_content_reasoning_length.json"),
        make_response_from_fixture("content_after_reasoning.json"),
    ]
    ep = Endpoint(
        name="qwen-local",
        tier="swarm",
        base_url="http://x/v1",
        model="qwen3:4b",
        quirks={"think_toggle": "qwen3", "min_completion_tokens": 256},
    )

    out = ep.chat([{"role": "user", "content": "ping"}], thinking=False, max_tokens=32)

    assert out == "pong"
    assert mock_post.call_count == 2
    first = mock_post.call_args_list[0].kwargs["json"]
    second = mock_post.call_args_list[1].kwargs["json"]
    assert first["max_tokens"] == 256  # floor applied
    assert second["max_tokens"] >= 256
    assert second["messages"][-1]["content"].endswith("/no_think")


@patch("anchor_client.requests.post")
def test_empty_content_after_retry_raises(mock_post):
    empty = make_response_from_fixture("empty_content_reasoning_length.json")
    mock_post.side_effect = [empty, empty]
    ep = Endpoint(
        name="qwen-local",
        tier="swarm",
        base_url="http://x/v1",
        model="qwen3:4b",
        quirks={"think_toggle": "qwen3", "min_completion_tokens": 256},
    )

    with pytest.raises(EmptyAssistantText, match="empty assistant content"):
        ep.chat([{"role": "user", "content": "ping"}], max_tokens=64)


@patch("anchor_client.requests.post")
def test_blank_content_without_reasoning_raises(mock_post):
    mock_post.side_effect = [
        make_response_from_fixture("empty_content_no_reasoning.json"),
        make_response_from_fixture("empty_content_no_reasoning.json"),
    ]
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m")

    with pytest.raises(EmptyAssistantText):
        ep.chat([{"role": "user", "content": "hi"}], max_tokens=16)


@patch("anchor_client.requests.post")
def test_inline_think_tags_stripped_to_answer(mock_post):
    mock_post.return_value = make_response_from_fixture("inline_think_tags.json")
    ep = Endpoint(
        name="n",
        tier="swarm",
        base_url="http://x/v1",
        model="qwen3",
        quirks={"think_toggle": "qwen3"},
    )

    assert ep.chat([{"role": "user", "content": "hi"}]) == "pong"


@patch("anchor_client.requests.post")
def test_openai_think_quirk_sent_and_dropped_on_400(mock_post):
    bad = MagicMock()
    bad.status_code = 400
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("400")
    good = make_response("pong")
    mock_post.side_effect = [bad, good]
    ep = Endpoint(
        name="ollama",
        tier="swarm",
        base_url="http://x/v1",
        model="qwen3:4b",
        quirks={"openai_think": False, "think_toggle": "qwen3"},
    )

    out = ep.chat([{"role": "user", "content": "hi"}], thinking=False)

    assert out == "pong"
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[0].kwargs["json"]["think"] is False
    assert "think" not in mock_post.call_args_list[1].kwargs["json"]
    assert ep._think_unsupported is True


@patch("anchor_client.requests.post")
def test_openai_think_cached_skip_after_400(mock_post):
    """After a think 400, later calls must not re-probe the field."""
    bad = MagicMock()
    bad.status_code = 400
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("400")
    good = make_response("pong")
    mock_post.side_effect = [bad, good, good]
    ep = Endpoint(
        name="ollama",
        tier="swarm",
        base_url="http://x/v1",
        model="qwen3:4b",
        quirks={"openai_think": False},
    )

    assert ep.chat([{"role": "user", "content": "a"}]) == "pong"
    assert ep.chat([{"role": "user", "content": "b"}]) == "pong"
    assert mock_post.call_count == 3  # 400+retry, then one clean call
    assert "think" not in mock_post.call_args_list[2].kwargs["json"]


@patch("anchor_client.requests.post")
def test_min_completion_tokens_floors_max_tokens(mock_post):
    mock_post.return_value = make_response("pong")
    ep = Endpoint(
        name="n",
        tier="swarm",
        base_url="http://x/v1",
        model="qwen3",
        quirks={"min_completion_tokens": 256},
    )

    ep.chat([{"role": "user", "content": "hi"}], max_tokens=32)

    assert mock_post.call_args.kwargs["json"]["max_tokens"] == 256


def test_endpoint_locality_inferred_from_base_url():
    private = Endpoint(name="n", tier="executor", base_url="http://10.0.1.10:8000/v1", model="m")
    cloud = Endpoint(name="n", tier="frontier", base_url="https://api.example.com/v1", model="m")
    assert private.is_local
    assert not cloud.is_local


def test_endpoint_explicit_local_flag_wins():
    # A tunnelled public URL that really is your hardware, and a private-range
    # address that is someone else's problem to power.
    assert Endpoint(name="n", tier="executor", base_url="https://tunnel.example.com/v1",
                    model="m", local=True).is_local
    assert not Endpoint(name="n", tier="executor", base_url="http://10.0.1.10:8000/v1",
                        model="m", local=False).is_local


def test_overlay_aliases_load_and_lookup(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: nemotron-build\n    tier: executor\n"
        "    base_url: https://integrate.api.nvidia.com/v1\n"
        "    model: nvidia/nemotron-3.5-lightning-30b-a3b\n"
        "roles:\n  executor: [executor]\n",
        encoding="utf-8",
    )
    overlay = tmp_path / "var" / "endpoints.local.yaml"
    overlay.parent.mkdir()
    overlay.write_text(
        "endpoints:\n"
        "  - name: nemotron-build\n    aliases: [lightning]\n"
        "    machine: flippy\n    effort: low\n",
        encoding="utf-8",
    )
    fleet = Fleet(registry, overlays=[overlay], probe_health=False)
    by_name = fleet.lookup("nemotron-build")
    by_nick = fleet.lookup("lightning")
    assert by_name is by_nick
    assert by_nick.machine == "flippy"
    assert by_nick.effort == "low"
    assert "lightning" in by_nick.aliases


def test_duplicate_alias_raises_registry_conflict(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "    aliases: [shared]\n"
        "  - name: b\n    tier: swarm\n    base_url: http://b/v1\n    model: m\n"
        "    aliases: [shared]\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryConflict, match="shared"):
        Fleet(registry, probe_health=False)


def test_write_endpoint_nick_only_touches_overlay(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: pin\n    tier: executor\n    base_url: http://x/v1\n    model: m\n",
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay.yaml"
    before = registry.read_text(encoding="utf-8")
    ep = write_endpoint_nick(
        overlay,
        alias="lightning",
        endpoint="pin",
        machine="flippy",
        effort="low",
        registry_path=registry,
        overlays=[],
    )
    assert ep.name == "pin"
    assert "lightning" in ep.aliases
    assert overlay.is_file()
    assert registry.read_text(encoding="utf-8") == before
    again = Fleet(registry, overlays=[overlay], probe_health=False)
    assert again.lookup("lightning").name == "pin"


def test_write_endpoint_nick_refuses_stolen_alias(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "  - name: b\n    tier: swarm\n    base_url: http://b/v1\n    model: m\n",
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay.yaml"
    write_endpoint_nick(
        overlay, alias="x", endpoint="a", registry_path=registry, overlays=[],
    )
    with pytest.raises(RegistryConflict, match="already maps"):
        write_endpoint_nick(
            overlay, alias="x", endpoint="b", registry_path=registry, overlays=[overlay],
        )


def test_registry_parses_the_local_field(tmp_path):
    reg = tmp_path / "endpoints.yaml"
    reg.write_text(
        "endpoints:\n"
        "  - name: box\n    tier: swarm\n    base_url: http://127.0.0.1:11434/v1\n"
        "    model: qwen3\n    local: true\n"
        "  - name: cloud\n    tier: frontier\n    base_url: https://api.example.com/v1\n"
        "    model: big\n",
        encoding="utf-8",
    )
    fleet = Fleet(reg)
    by_name = {e.name: e for e in fleet.endpoints}
    assert by_name["box"].is_local
    assert not by_name["cloud"].is_local


def test_endpoint_locality_agrees_with_the_shared_helper():
    # The two used to disagree on string values: `local: "false"` was falsy to
    # one and truthy to the other, so a project could be governed differently
    # by work_once and by the MCP.
    import inference_load as il

    for raw in ("true", "false", "yes", "no", "on", "off", "1", "0", "bogus", None):
        entry = {"local": raw, "base_url": "http://10.0.1.10:8000/v1"}
        ep = Endpoint(name="n", tier="swarm", base_url=entry["base_url"], model="m",
                      local=raw)
        assert ep.is_local == il.endpoint_is_local(entry), f"disagreement for {raw!r}"


def _lan_registry(tmp_path: Path) -> Path:
    reg = tmp_path / "endpoints.yaml"
    reg.write_text(
        "endpoints:\n"
        "  - name: h100-executor\n    tier: executor-heavy\n"
        "    base_url: http://10.0.1.10:8000/v1\n    model: qwen\n"
        "  - name: h100-nemotron\n    tier: reasoner\n"
        "    base_url: http://10.0.1.11:8000/v1\n    model: nemo\n"
        "roles:\n  executor: [executor-heavy, swarm]\n  critic: [reasoner]\n",
        encoding="utf-8",
    )
    return reg


@patch("anchor_client.endpoint_reachable", return_value=True)
def test_fleet_pick_keeps_healthy_lan(_mock_ok, tmp_path):
    fleet = Fleet(_lan_registry(tmp_path), prefer_local=False)
    assert fleet.pick("executor").name == "h100-executor"


@patch("anchor_client.endpoint_reachable", return_value=False)
@patch("nvidia_build_probe.list_build_model_ids", return_value=[
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
])
@patch("nvidia_build_probe.probe_build")
def test_fleet_pick_falls_back_to_build_when_lan_down(
    mock_probe, _mock_ids, _mock_down, tmp_path, monkeypatch, capsys,
):
    import nvidia_build_probe as nbp

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    mock_probe.return_value = nbp.BuildProbe(
        configured=True, reachable=True, key_source="NVIDIA_API_KEY",
        base_url=nbp.BUILD_BASE_URL,
    )
    fleet = Fleet(_lan_registry(tmp_path), prefer_local=False)
    ep = fleet.pick("executor")
    assert ep.name == NVIDIA_BUILD_ENDPOINT_NAME
    assert ep.model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert ep.local is False
    assert "llama-3.3-nemotron-super-49b" not in ep.model
    err = capsys.readouterr().err
    assert "NVIDIA Build" in err
    assert "nvapi-test" not in err


@patch("anchor_client.endpoint_reachable", return_value=False)
@patch("nvidia_build_probe.probe_build")
def test_fleet_pick_prefer_local_skips_build(mock_probe, _mock_down, tmp_path, monkeypatch):
    import nvidia_build_probe as nbp

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    mock_probe.return_value = nbp.BuildProbe(
        configured=True, reachable=True, key_source="NVIDIA_API_KEY",
        base_url=nbp.BUILD_BASE_URL,
    )
    fleet = Fleet(_lan_registry(tmp_path), prefer_local=True)
    with pytest.raises(LookupError, match="prefer_local"):
        fleet.pick("executor")
    mock_probe.assert_not_called()


@patch("anchor_client.endpoint_reachable", return_value=False)
def test_fleet_pick_fails_fast_when_lan_and_build_down(_mock_down, tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NGC_API_KEY", raising=False)
    monkeypatch.delenv("ANCHOR_API_KEY", raising=False)
    fleet = Fleet(_lan_registry(tmp_path), prefer_local=False)
    with pytest.raises(LookupError, match="No healthy endpoint"):
        fleet.pick("executor")
