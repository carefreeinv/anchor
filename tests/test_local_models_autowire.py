from pathlib import Path

import fit_device
import local_models_autowire as lma


def _model(name="qwen3-8b", family="qwen3", tier="swarm") -> fit_device.Model:
    return fit_device.Model(name, 8, family, tier, "g", "m", "h")


# --- ConfirmedStack.confirmed / reasons -----------------------------------

def test_confirmed_requires_reachable_tag_and_served():
    m = _model()
    stack = lma.ConfirmedStack(
        reachable=True, base_url="http://x:1/v1", model=m, ollama_tag="qwen3:8b",
        model_served=True, aider_present=True, probe={},
    )
    assert stack.confirmed is True
    assert stack.reasons() == []


def test_not_confirmed_when_unreachable():
    stack = lma.ConfirmedStack(
        reachable=False, base_url=None, model=None, ollama_tag=None,
        model_served=False, aider_present=False, probe={},
    )
    assert stack.confirmed is False
    assert "no guest-reachable" in stack.reasons()[0]


def test_not_confirmed_when_model_unmapped():
    m = _model(name="mistral-small-24b", family="mistral", tier="executor")
    stack = lma.ConfirmedStack(
        reachable=True, base_url="http://x:1/v1", model=m, ollama_tag=None,
        model_served=False, aider_present=False, probe={},
    )
    assert stack.confirmed is False
    assert any("no known Ollama tag" in r for r in stack.reasons())


def test_not_confirmed_when_reachable_but_model_not_served():
    m = _model()
    stack = lma.ConfirmedStack(
        reachable=True, base_url="http://x:1/v1", model=m, ollama_tag="qwen3:8b",
        model_served=False, aider_present=False, probe={},
    )
    assert stack.confirmed is False
    assert any("does not list model" in r for r in stack.reasons())


# --- ollama_tag_for --------------------------------------------------------

def test_ollama_tag_for_known_and_unknown_models():
    assert lma.ollama_tag_for(_model("qwen3-4b")) == "qwen3:4b"
    assert lma.ollama_tag_for(_model("mistral-small-24b")) is None
    assert lma.ollama_tag_for(None) is None


# --- detect_confirmed_stack (mocked probe) ---------------------------------

def test_detect_confirmed_stack_wires_from_probe(monkeypatch):
    m = _model("qwen3-4b")
    monkeypatch.setattr(fit_device, "probe_device", lambda: {
        "register_ok": True, "register_base_url": "http://172.26.0.1:11434/v1",
        "usable_memory_gb": 8.0, "free_memory_gb": 2.0, "available_memory_gb": 12.0,
        "profile": "wsl-host-cpu", "total_ram_gb": 15.7, "backend": "metal",
    })
    monkeypatch.setattr(fit_device, "fitting_models", lambda mem, quant, ctx: [m])
    monkeypatch.setattr(fit_device, "default_wire_model", lambda fits, **kw: (m, "high"))
    monkeypatch.setattr(lma, "list_served_model_ids", lambda base, timeout=2.0: ["qwen3:4b", "qwen3:8b"])
    monkeypatch.setattr(lma, "shutil", __import__("shutil"))
    monkeypatch.setattr(lma.shutil, "which", lambda name: "/usr/bin/aider" if name == "aider" else None)

    stack = lma.detect_confirmed_stack()
    assert stack.confirmed is True
    assert stack.ollama_tag == "qwen3:4b"
    assert stack.aider_present is True


def test_detect_confirmed_stack_not_confirmed_when_unreachable(monkeypatch):
    monkeypatch.setattr(fit_device, "probe_device", lambda: {
        "register_ok": False, "register_base_url": None,
        "usable_memory_gb": None, "free_memory_gb": None, "available_memory_gb": None,
        "profile": "wsl-host-cpu", "total_ram_gb": 15.7, "backend": "metal",
    })
    stack = lma.detect_confirmed_stack()
    assert stack.confirmed is False
    assert stack.model is None


# --- write set (C1 refusal, idempotency, gated aider parts) ---------------

def _confirmed_stack(tmp_path: Path, *, aider_present: bool = True) -> lma.ConfirmedStack:
    m = _model("qwen3-8b")
    return lma.ConfirmedStack(
        reachable=True, base_url="http://172.26.0.1:11434/v1", model=m,
        ollama_tag="qwen3:8b", model_served=True, aider_present=aider_present,
        probe={"backend": "metal"},
    )


def test_write_project_stack_refuses_when_not_confirmed(tmp_path):
    unconfirmed = lma.ConfirmedStack(
        reachable=False, base_url=None, model=None, ollama_tag=None,
        model_served=False, aider_present=False, probe={},
    )
    result = lma.write_project_stack(tmp_path, tmp_path, unconfirmed)
    assert "error" in result
    assert not (tmp_path / ".env").exists()


def test_write_project_stack_full_set_and_idempotent_rerun(tmp_path):
    anchor_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "consumer"
    project.mkdir()
    stack = _confirmed_stack(project)

    result1 = lma.write_project_stack(anchor_root, project, stack)
    assert result1["env"] == "created"
    assert result1["endpoints_overlay"] == "created"
    assert result1["aider_conf"] == "created"
    assert result1["launcher"] == "created"
    assert result1["conventions"] == "skipped (no conventions file)"

    assert (project / ".env").read_text().count("OLLAMA_API_BASE=http://172.26.0.1:11434") == 1
    assert "qwen3-8b-local" in (project / "var/endpoints.local.yaml").read_text()
    assert (project / ".aider.conf.yml").read_text().strip() == "model: ollama_chat/qwen3:8b"
    assert (project / "scripts/aider-ollama.sh").is_file()

    result2 = lma.write_project_stack(anchor_root, project, stack)
    assert result2["env"] == "unchanged"
    assert result2["endpoints_overlay"] == "unchanged"
    assert result2["aider_conf"] == "unchanged"
    assert result2["launcher"] == "unchanged"


def test_write_project_stack_skips_aider_parts_when_aider_absent(tmp_path):
    anchor_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "consumer2"
    project.mkdir()
    stack = _confirmed_stack(project, aider_present=False)

    result = lma.write_project_stack(anchor_root, project, stack)
    assert result["aider_conf"].startswith("skipped")
    assert result["launcher"].startswith("skipped")
    assert not (project / ".aider.conf.yml").exists()
    assert not (project / "scripts/aider-ollama.sh").exists()
    # Non-Aider-gated parts still happen.
    assert result["env"] == "created"
    assert result["endpoints_overlay"] == "created"


def test_write_conventions_note_only_when_file_exists(tmp_path):
    stack = _confirmed_stack(tmp_path)
    assert lma.write_conventions_note(tmp_path, stack) == "skipped (no conventions file)"

    conv = tmp_path / ".anchor" / "conventions.md"
    conv.parent.mkdir(parents=True)
    conv.write_text("# Conventions\n")
    assert lma.write_conventions_note(tmp_path, stack) == "updated"
    assert lma.CONVENTIONS_MARKER in conv.read_text()
    # Idempotent
    assert lma.write_conventions_note(tmp_path, stack) == "unchanged"


def test_write_aider_conf_replaces_existing_model_line(tmp_path):
    stack = _confirmed_stack(tmp_path)
    (tmp_path / ".aider.conf.yml").write_text("model: ollama_chat/old-model\nweak-model: foo\n")
    path, action = lma.write_aider_conf(tmp_path, stack)
    assert action == "updated"
    text = path.read_text()
    assert "model: ollama_chat/qwen3:8b" in text
    assert "weak-model: foo" in text
    assert "old-model" not in text
