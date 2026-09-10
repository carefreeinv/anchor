import fit_device


def test_estimate_grows_with_params_quant_and_context():
    small = fit_device.estimate_memory_gb(8, "q4", 8192)
    big = fit_device.estimate_memory_gb(32, "q4", 8192)
    assert big > small
    assert fit_device.estimate_memory_gb(8, "q8", 8192) > fit_device.estimate_memory_gb(8, "q4", 8192)
    assert fit_device.estimate_memory_gb(8, "q4", 32768) > fit_device.estimate_memory_gb(8, "q4", 8192)


def test_fitting_models_ranks_largest_first_and_respects_budget():
    fits = fit_device.fitting_models(16, "q4", 8192)
    assert fits, "expected at least one model to fit 16GB"
    params = [m.params_b for m in fits]
    assert params == sorted(params, reverse=True)
    # A 16GB device must not be handed the 70B model.
    assert all(m.name != "llama33-70b" for m in fits)


def test_tiny_budget_fits_nothing():
    assert fit_device.fitting_models(2, "q4", 8192) == []


def test_max_context_for_is_monotonic_in_memory():
    lo = fit_device.max_context_for(14, "q4", 12)
    hi = fit_device.max_context_for(14, "q4", 48)
    assert hi >= lo
    # Result is a power of two within the cap, or 0.
    assert hi == 0 or (hi & (hi - 1)) == 0


def test_quirks_track_model_family():
    qwen = next(m for m in fit_device.CATALOG if m.family == "qwen3")
    gemma = next(m for m in fit_device.CATALOG if m.family == "gemma3")
    mistral = next(m for m in fit_device.CATALOG if m.family == "mistral")
    deepseek = next(m for m in fit_device.CATALOG if m.family == "deepseek-r1-distill")
    qwen_q = fit_device.quirks_for(qwen, 8192)
    assert qwen_q["think_toggle"] == "qwen3"
    assert qwen_q["strip_think"] is True
    assert qwen_q["min_completion_tokens"] == 256
    # openai_think is Ollama-only opt-in; key presence would tax non-Ollama backends.
    assert "openai_think" not in qwen_q
    assert qwen_q["sampling_thinking"] == {"top_p": 0.95, "top_k": 20}
    assert qwen_q["sampling"] == {"top_p": 0.8}
    assert qwen_q["max_context"] == 8192
    gemma_q = fit_device.quirks_for(gemma, 32768)
    assert gemma_q["system_role"] == "fold_into_user"
    assert "BLOCKED" in gemma_q["system_suffix"]  # agreeableness guardrail rides along
    assert fit_device.quirks_for(mistral, 32768)["temperature"] == 0.15
    deepseek_q = fit_device.quirks_for(deepseek, 32768)
    # R1 official guidance: no system prompt — must fold, strip <think>, and carry
    # the LOW-CONFIDENCE budget rule.
    assert deepseek_q["system_role"] == "fold_into_user"
    assert deepseek_q["strip_think"] is True
    assert "LOW-CONFIDENCE" in deepseek_q["system_suffix"]


def test_full_context_omits_max_context_quirk():
    qwen = next(m for m in fit_device.CATALOG if m.family == "qwen3")
    assert "max_context" not in fit_device.quirks_for(qwen, 32768)


def test_launch_command_matches_backend():
    m = next(x for x in fit_device.CATALOG if x.name == "qwen3-14b")
    assert "llama-server" in fit_device.launch_command(m, "metal", "q4", 8192)
    assert "mlx_lm.server" in fit_device.launch_command(m, "mlx", "q4", 8192)
    assert "vllm serve" in fit_device.launch_command(m, "cuda", "q4", 8192)


def test_endpoint_stanza_uses_cuda_port_and_hf_model():
    m = next(x for x in fit_device.CATALOG if x.name == "qwen3-14b")
    cuda = fit_device.endpoint_stanza(m, "cuda", 8192)
    assert "localhost:8000" in cuda and m.hf in cuda
    metal = fit_device.endpoint_stanza(m, "metal", 8192)
    assert "localhost:8080" in metal and "model: qwen3-14b" in metal


def test_endpoint_stanza_with_guardrail_is_valid_yaml():
    import yaml

    gemma = next(x for x in fit_device.CATALOG if x.name == "gemma3-27b")
    stanza = fit_device.endpoint_stanza(gemma, "metal", 8192)
    parsed = yaml.safe_load("endpoints:\n" + stanza)["endpoints"][0]
    assert parsed["quirks"]["system_role"] == "fold_into_user"
    assert "BLOCKED" in parsed["quirks"]["system_suffix"]
    assert parsed["quirks"]["max_context"] == 8192


def test_probe_device_returns_expected_keys():
    probe = fit_device.probe_device()
    for key in (
        "system", "machine", "wsl", "apple_silicon", "total_ram_gb",
        "cuda_vram_gb", "usable_memory_gb", "free_memory_gb", "available_memory_gb",
        "backend", "profile", "tools",
        "recommend_bare_metal", "executor_placement",
    ):
        assert key in probe
    assert probe["backend"] in {"metal", "mlx", "cuda"}
    assert isinstance(probe["tools"], dict)


def test_probe_device_free_memory_sources_host_free_on_wsl_host(monkeypatch):
    """WSL + reachable Windows host: free_memory_gb must come from the HOST
    (constrained-guest reality is exactly what recommend_bare_metal exists to
    surface), never silently fall back to the guest's own MemAvailable."""
    monkeypatch.setattr(fit_device, "detect_wsl", lambda: True)
    monkeypatch.setattr(fit_device, "detect_apple_silicon", lambda: False)
    monkeypatch.setattr(fit_device, "detect_total_ram_gb", lambda: 13.8)
    monkeypatch.setattr(fit_device, "detect_cuda_vram_gb", lambda: None)
    monkeypatch.setattr(fit_device, "detect_available_memory_gb", lambda: 0.3)
    monkeypatch.setattr(
        fit_device, "probe_windows_host",
        lambda: {"total_ram_gb": 15.7, "free_ram_gb": 6.5, "has_nvidia": False},
    )
    probe = fit_device.probe_device()
    assert probe["recommend_bare_metal"] is True
    assert probe["free_memory_gb"] == 6.5
    assert probe["available_memory_gb"] == 0.3


def test_probe_device_free_memory_falls_back_to_guest_available_without_host(monkeypatch):
    """No Windows host reachable (plain WSL guest or bare Linux): free_memory_gb
    must come from the guest's own MemAvailable, not a stale/absent host value."""
    monkeypatch.setattr(fit_device, "detect_wsl", lambda: True)
    monkeypatch.setattr(fit_device, "detect_apple_silicon", lambda: False)
    monkeypatch.setattr(fit_device, "detect_total_ram_gb", lambda: 13.8)
    monkeypatch.setattr(fit_device, "detect_cuda_vram_gb", lambda: None)
    monkeypatch.setattr(fit_device, "detect_available_memory_gb", lambda: 0.7)
    monkeypatch.setattr(fit_device, "probe_windows_host", lambda: None)
    probe = fit_device.probe_device()
    assert probe["recommend_bare_metal"] is True  # wsl-cpu still prefers host if reachable later
    assert probe["free_memory_gb"] == 0.7
    assert probe["available_memory_gb"] == 0.7


def test_default_wire_prefers_smallest_when_free_unknown_on_wsl_host_cpu():
    fits = fit_device.fitting_models(8.6, "q4", 8192)
    assert fits and fits[0].name == "qwen3-8b"
    wire, pressure = fit_device.default_wire_model(
        fits, quant="q4", context=8192, profile="wsl-host-cpu", total_ram_gb=16,
    )
    assert wire.name == "qwen3-4b"
    assert pressure == "high"


def test_default_wire_uses_max_fit_when_free_ram_healthy():
    fits = fit_device.fitting_models(48, "q4", 8192)
    assert fits[0].params_b >= 30
    wire, pressure = fit_device.default_wire_model(
        fits,
        quant="q4",
        context=8192,
        free_gb=40.0,
        profile="apple-silicon",
        total_ram_gb=64,
    )
    assert wire.name == fits[0].name
    assert pressure == "low"


def test_default_wire_high_pressure_when_free_ram_tiny():
    """LENOVO-class: catalog max is 8B on ~8.6GB usable, but free RAM is <1GB."""
    fits = fit_device.fitting_models(8.6, "q4", 8192)
    wire, pressure = fit_device.default_wire_model(
        fits,
        quant="q4",
        context=8192,
        free_gb=0.8,
        profile="wsl-host-cpu",
        total_ram_gb=16,
    )
    assert wire.name == "qwen3-4b"
    assert pressure == "high"


def test_print_recommendation_shows_both_answers(capsys):
    fit_device.print_recommendation_report(
        {
            "profile": "wsl-host-cpu",
            "executor_placement": "windows-host",
            "recommend_bare_metal": True,
            "free_memory_gb": 0.8,
            "available_memory_gb": 0.5,
            "total_ram_gb": 16,
        },
        8.6,
        "metal",
        "q4",
        8192,
    )
    out = capsys.readouterr().out
    assert "Max fit" in out and "qwen3-8b" in out
    assert "Default for wire" in out and "qwen3-4b" in out
    assert "memory_pressure=`high`" in out
    assert "opt-up" in out.lower()


def test_official_links_include_https():
    m = next(x for x in fit_device.CATALOG if x.name == "qwen3-8b")
    links = fit_device.official_links(m)
    assert links
    assert all(url.startswith("https://") for _, url in links)


def test_print_install_guidance_wsl_prefers_windows_host(capsys):
    fit_device.print_install_guidance({
        "profile": "wsl-host-cpu",
        "recommend_bare_metal": True,
        "tools": {"ollama": False, "llama-server": False, "host_ollama_windows": False},
    })
    out = capsys.readouterr().out
    assert "bare metal" in out.lower() or "Windows bare-metal" in out or "Windows host" in out
    assert "ollama.com/download" in out
    assert "Fallback" in out or "fallback" in out


def test_probe_windows_host_returns_dict_or_none():
    # On non-WSL CI this is None; on WSL with powershell it should be a dict.
    result = fit_device.probe_windows_host()
    assert result is None or isinstance(result, dict)
    if isinstance(result, dict):
        assert "total_ram_gb" in result or result.get("source") == "powershell.exe"
