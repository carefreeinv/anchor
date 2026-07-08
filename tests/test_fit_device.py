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
    assert fit_device.quirks_for(qwen, 8192) == {"think_toggle": "qwen3", "strip_think": True, "max_context": 8192}
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
