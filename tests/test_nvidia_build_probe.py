from unittest.mock import MagicMock, patch

import nvidia_build_probe as nbp
import requests


def make_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    return resp


def test_find_api_key_prefers_nvidia_api_key_over_ngc():
    key, source = nbp.find_api_key({"NVIDIA_API_KEY": "nvapi-abc", "NGC_API_KEY": "ngc-xyz"})
    assert key == "nvapi-abc"
    assert source == "NVIDIA_API_KEY"


def test_find_api_key_falls_back_to_ngc_api_key():
    key, source = nbp.find_api_key({"NGC_API_KEY": "ngc-xyz"})
    assert key == "ngc-xyz"
    assert source == "NGC_API_KEY"


def test_find_api_key_absent_returns_none_none():
    assert nbp.find_api_key({}) == (None, None)


def test_probe_build_not_configured_makes_no_network_call():
    with patch("nvidia_build_probe.requests.get") as mock_get:
        probe = nbp.probe_build(env={})
    mock_get.assert_not_called()
    assert probe.configured is False
    assert probe.reachable is False
    assert probe.key_source is None


@patch("nvidia_build_probe.requests.get")
def test_probe_build_configured_and_reachable(mock_get):
    mock_get.return_value = make_response(200)
    probe = nbp.probe_build(env={"NVIDIA_API_KEY": "nvapi-abc"})
    assert probe.configured is True
    assert probe.reachable is True
    assert probe.key_source == "NVIDIA_API_KEY"
    assert probe.error is None
    # Never sends the key anywhere but the Authorization header, never returns it.
    sent_headers = mock_get.call_args.kwargs["headers"]
    assert sent_headers["Authorization"] == "Bearer nvapi-abc"
    assert "nvapi-abc" not in repr(probe)


@patch("nvidia_build_probe.requests.get")
def test_probe_build_configured_but_unauthorized(mock_get):
    mock_get.return_value = make_response(401)
    probe = nbp.probe_build(env={"NVIDIA_API_KEY": "bad-key"})
    assert probe.configured is True
    assert probe.reachable is False
    assert probe.error == "HTTP 401"


@patch("nvidia_build_probe.requests.get")
def test_probe_build_connect_error_is_soft_failure(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")
    probe = nbp.probe_build(env={"NVIDIA_API_KEY": "nvapi-abc"})
    assert probe.configured is True
    assert probe.reachable is False
    assert probe.error == "ConnectionError"


def test_preferred_backend_build_when_configured_and_reachable():
    probe = nbp.BuildProbe(configured=True, reachable=True, key_source="NVIDIA_API_KEY",
                            base_url=nbp.BUILD_BASE_URL)
    assert nbp.preferred_backend(probe) == "build"


def test_preferred_backend_local_when_not_configured():
    probe = nbp.BuildProbe(configured=False, reachable=False, key_source=None,
                            base_url=nbp.BUILD_BASE_URL)
    assert nbp.preferred_backend(probe) == "local"


def test_preferred_backend_local_when_configured_but_unreachable():
    probe = nbp.BuildProbe(configured=True, reachable=False, key_source="NVIDIA_API_KEY",
                            base_url=nbp.BUILD_BASE_URL, error="HTTP 401")
    assert nbp.preferred_backend(probe) == "local"


def test_preferred_backend_operator_override_wins_even_when_reachable():
    # Operator override must never be silently clobbered by a live Build key.
    probe = nbp.BuildProbe(configured=True, reachable=True, key_source="NVIDIA_API_KEY",
                            base_url=nbp.BUILD_BASE_URL)
    assert nbp.preferred_backend(probe, prefer_local=True) == "local"


def test_explain_never_includes_a_key_value():
    probe = nbp.BuildProbe(configured=True, reachable=True, key_source="NVIDIA_API_KEY",
                            base_url=nbp.BUILD_BASE_URL)
    text = nbp.explain(probe, "build")
    assert "NVIDIA Build" in text
    assert "nvapi-" not in text


def test_explain_local_reason_mentions_missing_key():
    probe = nbp.BuildProbe(configured=False, reachable=False, key_source=None,
                            base_url=nbp.BUILD_BASE_URL)
    assert "no NVIDIA_API_KEY" in nbp.explain(probe, "local")


def test_explain_local_reason_mentions_operator_override():
    probe = nbp.BuildProbe(configured=True, reachable=True, key_source="NVIDIA_API_KEY",
                            base_url=nbp.BUILD_BASE_URL)
    text = nbp.explain(probe, "local", prefer_local=True)
    assert "operator preference" in text
