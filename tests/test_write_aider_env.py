from pathlib import Path

import write_aider_env as wae


def test_strip_v1_suffix():
    assert wae.strip_v1_suffix("http://172.26.0.1:11434/v1") == "http://172.26.0.1:11434"
    assert wae.strip_v1_suffix("http://172.26.0.1:11434/v1/") == "http://172.26.0.1:11434"
    assert wae.strip_v1_suffix("http://127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_resolve_ollama_api_base_reuses_fit_device_discovery(monkeypatch):
    monkeypatch.setattr(
        wae,
        "resolve_register_base_url",
        lambda proposed, wsl=None, backend="cuda": {
            "base_url": "http://172.26.0.1:11434/v1",
            "ok": True,
            "reason": "discovered:default-gateway",
            "discovery": {"host": "172.26.0.1"},
        },
    )
    result = wae.resolve_ollama_api_base()
    assert result["base_url"] == "http://172.26.0.1:11434"
    assert result["ok"] is True
    assert result["reason"] == "discovered:default-gateway"


def test_resolve_ollama_api_base_falls_back_when_unreachable(monkeypatch):
    monkeypatch.setattr(
        wae,
        "resolve_register_base_url",
        lambda proposed, wsl=None, backend="cuda": {
            "base_url": "http://127.0.0.1:11434/v1",
            "ok": False,
            "reason": "no-reachable-api; loopback-fallback",
            "discovery": None,
        },
    )
    result = wae.resolve_ollama_api_base()
    assert result["ok"] is False
    assert result["base_url"] == "http://127.0.0.1:11434"


# --- _upsert_env_var -----------------------------------------------------

def test_upsert_env_var_appends_to_empty_text():
    text, changed = wae._upsert_env_var("", "OLLAMA_API_BASE", "http://x:1/")
    assert changed is True
    assert text.strip() == "OLLAMA_API_BASE=http://x:1/"


def test_upsert_env_var_replaces_existing_bare_assignment():
    text, changed = wae._upsert_env_var(
        "FOO=bar\nOLLAMA_API_BASE=http://old:1\nBAZ=qux\n",
        "OLLAMA_API_BASE", "http://new:2",
    )
    assert changed is True
    lines = text.splitlines()
    assert "FOO=bar" in lines
    assert "BAZ=qux" in lines
    assert "OLLAMA_API_BASE=http://new:2" in lines
    assert "OLLAMA_API_BASE=http://old:1" not in lines


def test_upsert_env_var_noop_when_already_correct():
    text, changed = wae._upsert_env_var("OLLAMA_API_BASE=http://x:1\n", "OLLAMA_API_BASE", "http://x:1")
    assert changed is False


# --- write_env_file -------------------------------------------------------

def test_write_env_file_creates_new_file(tmp_path: Path):
    env_path, changed, action = wae.write_env_file(tmp_path, "http://172.26.0.1:11434")
    assert changed is True
    assert action == "created"
    text = env_path.read_text()
    assert "OLLAMA_API_BASE=http://172.26.0.1:11434" in text
    assert "OPENAI_API_KEY=ollama" in text


def test_write_env_file_preserves_unrelated_lines_and_is_idempotent(tmp_path: Path):
    (tmp_path / ".env").write_text("MY_SECRET=abc123\nOLLAMA_API_BASE=http://old:1\n")
    env_path, changed, action = wae.write_env_file(tmp_path, "http://172.26.0.1:11434", ensure_openai_key=False)
    assert changed is True
    assert action == "updated"
    text = env_path.read_text()
    assert "MY_SECRET=abc123" in text
    assert "OLLAMA_API_BASE=http://172.26.0.1:11434" in text
    assert "OLLAMA_API_BASE=http://old:1" not in text

    # Re-run: nothing should change.
    _, changed2, action2 = wae.write_env_file(tmp_path, "http://172.26.0.1:11434", ensure_openai_key=False)
    assert changed2 is False
    assert action2 == "unchanged"


def test_write_env_file_dry_run_writes_nothing(tmp_path: Path):
    env_path, changed, action = wae.write_env_file(tmp_path, "http://x:1", dry_run=True)
    assert changed is True
    assert action == "would-write"
    assert not env_path.exists()


# --- gitignore -------------------------------------------------------------

def test_ensure_env_gitignored_creates_when_missing(tmp_path: Path):
    action = wae.ensure_env_gitignored(tmp_path)
    assert action == "created"
    text = (tmp_path / ".gitignore").read_text()
    assert ".env" in text.splitlines()


def test_ensure_env_gitignored_unchanged_when_already_covered(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
    action = wae.ensure_env_gitignored(tmp_path)
    assert action == "unchanged"


def test_ensure_env_gitignored_appends_when_missing_entry(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    action = wae.ensure_env_gitignored(tmp_path)
    assert action == "updated"
    text = (tmp_path / ".gitignore").read_text()
    assert "node_modules/" in text
    assert ".env" in text.splitlines()


def test_ensure_env_gitignored_dry_run_writes_nothing(tmp_path: Path):
    action = wae.ensure_env_gitignored(tmp_path, dry_run=True)
    assert action == "would-create"
    assert not (tmp_path / ".gitignore").exists()


# --- gitignore: Aider's own machine-local files -----------------------------

def test_ensure_aider_gitignored_creates_when_missing(tmp_path: Path):
    action = wae.ensure_aider_gitignored(tmp_path)
    assert action == "created"
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert "/.aider.conf.yml" in lines
    assert "/.aider.model.settings.yml" in lines
    assert ".aider.chat.history.md" in lines
    assert ".aider.input.history" in lines
    assert ".aider.tags.cache.v*/" in lines


def test_ensure_aider_gitignored_appends_to_existing(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
    action = wae.ensure_aider_gitignored(tmp_path)
    assert action == "updated"
    text = (tmp_path / ".gitignore").read_text()
    assert "node_modules/" in text and ".env" in text.splitlines()
    assert "/.aider.conf.yml" in text.splitlines()


def test_ensure_aider_gitignored_unchanged_when_covered(tmp_path: Path):
    (tmp_path / ".gitignore").write_text(
        "\n".join(wae.AIDER_GITIGNORE_ENTRIES) + "\n")
    assert wae.ensure_aider_gitignored(tmp_path) == "unchanged"


def test_ensure_aider_gitignored_accepts_unanchored_hand_written_entries(tmp_path: Path):
    """A project that wrote `.aider.conf.yml` itself is already covered — the
    root-anchored form must not be appended on top of it."""
    (tmp_path / ".gitignore").write_text(".aider.conf.yml\n")
    action = wae.ensure_aider_gitignored(tmp_path)
    assert action == "updated"  # the other entries are still missing
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines.count(".aider.conf.yml") == 1
    assert "/.aider.conf.yml" not in lines
    assert "/.aider.model.settings.yml" in lines


def test_ensure_aider_gitignored_dry_run_writes_nothing(tmp_path: Path):
    assert wae.ensure_aider_gitignored(tmp_path, dry_run=True) == "would-create"
    assert not (tmp_path / ".gitignore").exists()


def test_aider_entries_do_not_shadow_scaffolded_examples(tmp_path: Path):
    """The scaffold ships `.aider.conf.yml.example` (root) and
    `platforms/aider/.aider.conf.*.example` — the ignore block must leave both
    trackable."""
    ignored = {e.lstrip("/") for e in wae.AIDER_GITIGNORE_ENTRIES}
    assert ".aider.conf.yml.example" not in ignored
    assert all(not e.endswith(".example") for e in wae.AIDER_GITIGNORE_ENTRIES)


def test_ensure_aider_gitignored_respects_aiders_own_catchall(tmp_path: Path):
    """Aider appends `.aider*` itself on first run in a repo; that already
    covers every entry, so Anchor must not stack a redundant block under it."""
    (tmp_path / ".gitignore").write_text("node_modules/\n.aider*\n")
    assert wae.ensure_aider_gitignored(tmp_path) == "unchanged"
    assert (tmp_path / ".gitignore").read_text() == "node_modules/\n.aider*\n"
