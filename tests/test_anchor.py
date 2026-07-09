import json

import pytest

import anchor


def test_resolve_selection_returns_platform_files():
    pairs = anchor.resolve_selection(["claude"])
    assert pairs == anchor.PLATFORMS["claude"]["files"]


def test_resolve_selection_unknown_platform_raises():
    with pytest.raises(SystemExit):
        anchor.resolve_selection(["not-a-platform"])


def test_resolve_selection_local_without_submodel_raises():
    with pytest.raises(SystemExit):
        anchor.resolve_selection(["local"])


def test_resolve_selection_local_with_unknown_submodel_raises():
    with pytest.raises(SystemExit):
        anchor.resolve_selection(["local:not-a-model"])


def test_resolve_selection_local_with_valid_submodel():
    pairs = anchor.resolve_selection(["local:qwen3"])
    srcs = {src for src, _ in pairs}
    assert "platforms/local-models/README.md" in srcs
    assert anchor.LOCAL_MODEL_FILES["qwen3"] in srcs


def test_plan_copy_dedupes_same_destination(tmp_path):
    # claude + chat share the CORE_FILES; the same dest must not appear twice.
    plan = anchor.plan_copy(tmp_path, ["claude", "chat"], want_fleet=False)
    dests = [dest for _, dest in plan]
    assert len(dests) == len(set(dests))


def test_plan_copy_includes_plans_tree_and_work_commands(tmp_path):
    plan = anchor.plan_copy(tmp_path, ["claude", "grok"], want_fleet=False)
    dests = {str(dest.relative_to(tmp_path)) for _, dest in plan}
    assert ".plans/README.md" in dests
    assert ".plans/.gitignore" in dests
    assert ".plans/bugs/.gitkeep" in dests
    assert ".plans/features/.gitkeep" in dests
    assert ".plans/drafts/.gitkeep" in dests
    assert ".plans/completed/.gitkeep" in dests
    assert ".claude/commands/work.md" in dests
    assert ".claude/commands/draft.md" in dests
    assert ".grok/skills/work/SKILL.md" in dests
    assert ".grok/skills/draft/SKILL.md" in dests


def test_ensure_project_var_creates_dir_and_gitignore(tmp_path):
    info = anchor.ensure_project_var(tmp_path)
    assert (tmp_path / "var").is_dir()
    assert (tmp_path / "var" / "worktrees").is_dir()
    assert (tmp_path / "var" / ".gitkeep").is_file()
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "var/" in gi
    assert info["gitignore"] == "created"
    # idempotent
    info2 = anchor.ensure_project_var(tmp_path)
    assert info2["gitignore"] == "unchanged"


def test_ensure_project_var_appends_existing_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    info = anchor.ensure_project_var(tmp_path)
    assert info["gitignore"] == "updated"
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "node_modules/" in text
    assert "var/" in text
    # does not duplicate
    assert text.count("var/") == 1


def test_check_conflicts_flags_existing_destination(tmp_path):
    plan = anchor.plan_copy(tmp_path, ["chat"], want_fleet=False)
    existing_dest = plan[0][1]
    existing_dest.parent.mkdir(parents=True, exist_ok=True)
    existing_dest.write_text("already here")

    conflicts = anchor.check_conflicts(plan)

    assert existing_dest in conflicts


def test_detect_framework_node(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert anchor.detect_framework(tmp_path) == "node"


def test_detect_framework_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]")
    assert anchor.detect_framework(tmp_path) == "rust"


def test_detect_framework_blank_dir_returns_none(tmp_path):
    assert anchor.detect_framework(tmp_path) is None


def test_detect_framework_unrecognized_files_returns_none(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    assert anchor.detect_framework(tmp_path) is None


def test_load_defaults_reads_saved_platforms_and_fleet(tmp_path, monkeypatch):
    defaults_file = tmp_path / "defaults"
    defaults_file.write_text("PLATFORMS=claude,local:qwen3\nFLEET=1\n")
    monkeypatch.setattr(anchor, "DEFAULTS_FILE", defaults_file)

    result = anchor.load_defaults()

    assert result == (["claude", "local:qwen3"], True)


def test_load_defaults_returns_none_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(anchor, "DEFAULTS_FILE", tmp_path / "defaults")
    assert anchor.load_defaults() is None


def test_load_saved_language_reads_value(tmp_path, monkeypatch):
    defaults_file = tmp_path / "defaults"
    defaults_file.write_text("PLATFORMS=chat\nFLEET=0\nLANGUAGE=Node\n")
    monkeypatch.setattr(anchor, "DEFAULTS_FILE", defaults_file)

    assert anchor.load_saved_language() == "node"


def test_load_model_priority_reads_ordered_list(tmp_path, monkeypatch):
    defaults_file = tmp_path / "defaults"
    defaults_file.write_text("PLATFORMS=chat\nMODEL_PRIORITY=nim, Grok, openai:gpt-5, claude:sonnet\n")
    monkeypatch.setattr(anchor, "DEFAULTS_FILE", defaults_file)

    assert anchor.load_model_priority() == ["nim", "grok", "openai:gpt-5", "claude:sonnet"]


def test_load_model_priority_empty_when_unset(tmp_path, monkeypatch):
    defaults_file = tmp_path / "defaults"
    defaults_file.write_text("PLATFORMS=chat\nFLEET=0\n")
    monkeypatch.setattr(anchor, "DEFAULTS_FILE", defaults_file)

    assert anchor.load_model_priority() == []


def test_resolve_framework_cli_override_wins(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert anchor.resolve_framework(tmp_path, "Rust", None) == "rust"


def test_resolve_framework_detection_wins_over_saved_default(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]")
    assert anchor.resolve_framework(tmp_path, None, "node") == "rust"


def test_resolve_framework_falls_back_to_saved_default_when_non_interactive(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert anchor.resolve_framework(tmp_path, None, "node") == "node"


def test_resolve_framework_returns_none_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert anchor.resolve_framework(tmp_path, None, None) is None


def test_build_manifest_records_commit_platforms_and_file_hashes(tmp_path):
    plan = anchor.plan_copy(tmp_path, ["chat"], want_fleet=False)
    conventions = anchor.plan_conventions(tmp_path, "node")

    manifest = anchor.build_manifest(tmp_path, plan, conventions, ["chat"], False, "node",
                                     ["nim", "claude:sonnet"], "claude:sonnet")

    assert manifest["platforms"] == ["chat"]
    assert manifest["fleet"] is False
    assert manifest["framework"] == "node"
    assert manifest["model_priority"] == ["nim", "claude:sonnet"]
    assert manifest["preferred_orchestrator"] == "claude:sonnet"
    assert "anchor_commit" in manifest and "generated_at" in manifest

    dest_rel = str(plan[0][1].relative_to(tmp_path))
    assert manifest["files"][dest_rel]["hash"] == anchor._sha256(plan[0][0])

    conv_dest_rel = str(conventions[0].relative_to(tmp_path))
    assert manifest["files"][conv_dest_rel]["src"] is None
    assert manifest["files"][conv_dest_rel]["hash"] == anchor._sha256_text(conventions[1])


def test_check_project_missing_manifest_raises(tmp_path):
    with pytest.raises(SystemExit):
        anchor.check_project(tmp_path)


def test_check_project_reports_all_four_states(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "unchanged.md").write_text("stable content")
    (repo / "upstream.md").write_text("new upstream content")
    monkeypatch.setattr(anchor, "REPO_ROOT", repo)

    (project / "unchanged.md").write_text("stable content")
    (project / "modified.md").write_text("hand-edited by the user")
    (project / "upstream.md").write_text("content as of scaffold time")
    # "missing.md" is intentionally never written to the project.

    manifest = {
        "anchor_commit": "abc123",
        "generated_at": "2026-01-01T00:00:00Z",
        "platforms": ["chat"],
        "fleet": False,
        "framework": None,
        "files": {
            "unchanged.md": {"src": "unchanged.md", "hash": anchor._sha256_text("stable content")},
            "modified.md": {"src": "unchanged.md", "hash": anchor._sha256_text("original content")},
            "upstream.md": {"src": "upstream.md", "hash": anchor._sha256_text("content as of scaffold time")},
            "missing.md": {"src": "unchanged.md", "hash": anchor._sha256_text("whatever")},
        },
    }
    (project / anchor.MANIFEST_NAME).write_text(json.dumps(manifest))

    anchor.check_project(project)
    out = capsys.readouterr().out

    assert "unchanged.md: unchanged" in out
    assert "modified.md: locally modified" in out
    assert "upstream.md: upstream updated" in out
    assert "missing.md: MISSING" in out


def test_plan_conventions_includes_model_routing_with_priority(tmp_path):
    result = anchor.plan_conventions(tmp_path, "node", ["nim", "grok", "claude:sonnet"], "claude:sonnet")

    assert result is not None
    _, content = result
    assert "SUGGEST-ESCALATE" in content
    assert "anchor/model-fitness.md" in content
    assert "1. `nim`" in content and "3. `claude:sonnet`" in content
    assert "**Preferred orchestrator:** `claude:sonnet`" in content
    assert "lesser / executor / local / small model" in content
    assert "Temporary coordinator" in content
    assert "TEMPORARY-COORDINATOR" in content


def test_plan_conventions_generated_from_priority_alone(tmp_path):
    result = anchor.plan_conventions(tmp_path, None, ["claude:sonnet"], "claude:sonnet")

    assert result is not None
    _, content = result
    assert "Model routing" in content
    assert "framework" not in content.split("## Preferred orchestrator")[0]


def test_plan_conventions_from_orchestrator_alone(tmp_path):
    result = anchor.plan_conventions(tmp_path, None, None, "claude:opus")
    assert result is not None
    assert "**Preferred orchestrator:** `claude:opus`" in result[1]


def test_plan_conventions_unset_orchestrator_still_describes_temp_role(tmp_path):
    result = anchor.plan_conventions(tmp_path, "python", ["mid"], None)
    assert result is not None
    content = result[1]
    assert "unset" in content.lower() or "_(unset" in content
    assert "Temporary coordinator" in content
    assert "frontier or near-frontier" in content


def test_plan_conventions_none_when_nothing_to_say(tmp_path):
    assert anchor.plan_conventions(tmp_path, None, None, None) is None


def test_resolve_orchestrator_prefers_explicit_then_saved_then_priority_tail():
    assert anchor.resolve_orchestrator("claude:opus", ["nim", "claude:fable"], "grok") == "claude:opus"
    assert anchor.resolve_orchestrator(None, ["nim", "claude:fable"], "grok") == "grok"
    assert anchor.resolve_orchestrator(None, ["nim", "claude:fable"], None) == "claude:fable"
    assert anchor.resolve_orchestrator(None, None, None) is None


def test_set_project_orchestrator_writes_conventions(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "ANCHOR-CONVENTIONS.md").write_text(
        "# Anchor conventions for this project\n\n## Model routing (fit check)\n\nnotes\n"
    )
    (project / ".anchor-manifest.json").write_text(
        json.dumps({
            "files": {"ANCHOR-CONVENTIONS.md": {"src": None, "hash": "x"}},
            "model_priority": [],
        })
    )
    anchor.set_project_orchestrator(project, "Claude:Opus")
    text = (project / "ANCHOR-CONVENTIONS.md").read_text()
    assert "**Preferred orchestrator:** `claude:opus`" in text
    assert "SUGGEST-ESCALATE" in text or "lesser" in text
    manifest = json.loads((project / ".anchor-manifest.json").read_text())
    assert manifest["preferred_orchestrator"] == "claude:opus"


def test_load_orchestrator_from_defaults(tmp_path, monkeypatch):
    defaults_file = tmp_path / "defaults"
    defaults_file.write_text("PLATFORMS=chat\nORCHESTRATOR=Claude:Fable\n")
    monkeypatch.setattr(anchor, "DEFAULTS_FILE", defaults_file)
    assert anchor.load_orchestrator() == "claude:fable"
