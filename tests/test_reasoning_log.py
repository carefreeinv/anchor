"""Per-call reasoning logs under var/log (ANCHOR_LOG_DIR)."""
from pathlib import Path
from unittest.mock import patch

import pytest
from anchor_client import (
    Endpoint,
    append_reasoning_log,
    extract_think_blocks,
    reasoning_log_dir,
)
from orchestrate import execute_task, relay_text

from test_anchor_client import make_response, make_response_from_fixture
from test_footer_relay import VERBOSE_OUTPUT, RecordingFleet


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    dest = tmp_path / "var" / "log"
    monkeypatch.delenv("ANCHOR_NO_REASONING_LOG", raising=False)
    monkeypatch.setenv("ANCHOR_LOG_DIR", str(dest))
    return dest


def _ep(**quirks):
    return Endpoint(
        name="n",
        tier="executor",
        base_url="http://x/v1",
        model="qwen3:4b",
        quirks=quirks,
    )


def test_reasoning_log_dir_default_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("ANCHOR_NO_REASONING_LOG", raising=False)
    monkeypatch.delenv("ANCHOR_LOG_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert reasoning_log_dir() == tmp_path / "var" / "log"


def test_reasoning_log_dir_empty_env_disables(monkeypatch):
    monkeypatch.delenv("ANCHOR_NO_REASONING_LOG", raising=False)
    monkeypatch.setenv("ANCHOR_LOG_DIR", "  ")
    assert reasoning_log_dir() is None


def test_no_reasoning_log_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_NO_REASONING_LOG", "1")
    monkeypatch.setenv("ANCHOR_LOG_DIR", str(tmp_path / "log"))
    assert reasoning_log_dir() is None


def test_extract_think_blocks():
    assert "internal" in extract_think_blocks("<think>internal</think>\npong")
    assert extract_think_blocks("pong") == ""


@patch("anchor_client.requests.post")
def test_chat_logs_message_reasoning_not_in_return(mock_post, log_dir):
    mock_post.return_value = make_response_from_fixture("content_after_reasoning.json")
    out = _ep().chat([{"role": "user", "content": "ping"}])
    assert out == "pong"
    files = list(log_dir.glob("reasoning-*.log"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Simple ping-pong probe" in text
    assert "endpoint=n" in text
    assert "model=qwen3:4b" in text
    assert "last_user_sha256=" in text
    assert "Authorization" not in text


@patch("anchor_client.requests.post")
def test_chat_logs_think_blocks_and_strips_return(mock_post, log_dir):
    mock_post.return_value = make_response_from_fixture("inline_think_tags.json")
    out = _ep(strip_think=True).chat([{"role": "user", "content": "hi"}])
    assert out == "pong"
    assert "<think>" not in out
    text = next(log_dir.glob("reasoning-*.log")).read_text(encoding="utf-8")
    assert "internal monologue" in text
    assert "think:" in text


@patch("anchor_client.requests.post")
def test_opt_out_writes_nothing(mock_post, tmp_path, monkeypatch):
    dest = tmp_path / "log"
    monkeypatch.setenv("ANCHOR_NO_REASONING_LOG", "1")
    monkeypatch.setenv("ANCHOR_LOG_DIR", str(dest))
    mock_post.return_value = make_response_from_fixture("content_after_reasoning.json")
    assert _ep().chat([{"role": "user", "content": "ping"}]) == "pong"
    assert not dest.exists() or not list(dest.glob("*"))


@patch("anchor_client.requests.post")
def test_empty_content_logs_both_attempts(mock_post, log_dir):
    first = make_response_from_fixture("empty_content_reasoning_length.json")
    second = make_response("recovered")
    mock_post.side_effect = [first, second]
    out = _ep(min_completion_tokens=16).chat([{"role": "user", "content": "hi"}])
    assert out == "recovered"
    text = next(log_dir.glob("reasoning-*.log")).read_text(encoding="utf-8")
    assert text.count("--- ") == 2


@patch("anchor_client.requests.post")
def test_no_reasoning_field_still_records(mock_post, log_dir):
    mock_post.return_value = make_response("ok")
    assert _ep().chat([{"role": "user", "content": "hi"}]) == "ok"
    text = next(log_dir.glob("reasoning-*.log")).read_text(encoding="utf-8")
    assert "no reasoning field" in text


def test_fail_open_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.delenv("ANCHOR_NO_REASONING_LOG", raising=False)
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("file", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_LOG_DIR", str(blocked / "nested"))
    assert append_reasoning_log("hello\n") is None


@patch("anchor_client.requests.post")
def test_prompts_flag_includes_user_body(mock_post, log_dir, monkeypatch):
    monkeypatch.setenv("ANCHOR_LOG_PROMPTS", "1")
    mock_post.return_value = make_response("ok")
    _ep().chat([{"role": "user", "content": "secret-prompt-body"}])
    text = next(log_dir.glob("reasoning-*.log")).read_text(encoding="utf-8")
    assert "secret-prompt-body" in text


@patch("anchor_client.requests.post")
def test_prompts_off_omits_user_body(mock_post, log_dir):
    mock_post.return_value = make_response("ok")
    _ep().chat([{"role": "user", "content": "secret-prompt-body"}])
    text = next(log_dir.glob("reasoning-*.log")).read_text(encoding="utf-8")
    assert "secret-prompt-body" not in text


def test_relay_text_unchanged_by_reasoning_logs(log_dir):
    footer = (
        "## Result\nImplemented the widget.\n\n"
        "## How to verify\npytest -q\n\n"
        "## Deferred / concerns\nnone\n"
    )
    out = relay_text("scratch CoT\n\n" + footer)
    assert "Implemented the widget." in out
    assert "scratch CoT" not in out
    assert not list(log_dir.glob("*"))  # relay is not a chat call


def test_transcripts_still_separate_from_reasoning_log(tmp_path, log_dir):
    fleet = RecordingFleet([VERBOSE_OUTPUT])
    execute_task(
        "do the thing",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
        transcript_root=tmp_path,
        task_slug="fixture-run",
    )
    tdir = tmp_path / "var" / "task-transcripts"
    assert list(tdir.glob("*.log"))
    # RecordingFleet does not go through Endpoint.chat — no reasoning file.
    assert not list(log_dir.glob("reasoning-*.log"))
