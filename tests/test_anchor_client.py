from unittest.mock import MagicMock, patch

import pytest
import requests
from anchor_client import MAX_RETRIES, Endpoint, Fleet


def make_response(content="ok"):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
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


def test_fleet_pick_round_robins_within_tier(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "  - name: b\n    tier: swarm\n    base_url: http://b/v1\n    model: m\n"
        "roles:\n  executor: [swarm]\n"
    )
    fleet = Fleet(registry)

    picks = [fleet.pick("executor").name for _ in range(4)]

    assert picks == ["a", "b", "a", "b"]


def test_fleet_pick_raises_when_no_endpoint_available_for_role(tmp_path):
    registry = tmp_path / "endpoints.yaml"
    registry.write_text(
        "endpoints:\n"
        "  - name: a\n    tier: swarm\n    base_url: http://a/v1\n    model: m\n"
        "roles:\n  planner: [frontier]\n"
    )
    fleet = Fleet(registry)

    with pytest.raises(LookupError):
        fleet.pick("planner")


@patch("anchor_client.requests.post")
def test_no_auth_header_sent_when_api_key_unset(mock_post, monkeypatch):
    monkeypatch.delenv("ANCHOR_API_KEY", raising=False)
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m")

    ep.chat([{"role": "user", "content": "hi"}])

    assert "Authorization" not in mock_post.call_args.kwargs["headers"]


@patch("anchor_client.requests.post")
def test_auth_header_sent_when_api_key_set(mock_post, monkeypatch):
    monkeypatch.setenv("ANCHOR_API_KEY", "secret")
    mock_post.return_value = make_response()
    ep = Endpoint(name="n", tier="swarm", base_url="http://x/v1", model="m")

    ep.chat([{"role": "user", "content": "hi"}])

    assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"


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
