"""Harness budget ratchet — no model, no verb behavior change."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_harness_budget as hb  # noqa: E402


def test_budgets_hold_on_this_tree():
    root = Path(__file__).resolve().parents[1]
    code, failed, got = hb.evaluate(root)
    assert code == 0, failed
    assert got["generated_tokens_default_path"] == 0
    assert got["declared_install_deps"] == 0
    assert got["banned_modules_on_import_anchor"] == 0


def test_low_ceiling_names_the_budget(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    budget = (root / "anchor" / "harness-budget.toml").read_text(encoding="utf-8")
    budget = budget.replace(
        "sys_modules_added_on_import_anchor = 80",
        "sys_modules_added_on_import_anchor = 0",
    )
    (tmp_path / "anchor").mkdir()
    (tmp_path / "anchor" / "harness-budget.toml").write_text(budget, encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        (root / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8",
    )
    # Point measurements at the real tree; only ceilings come from tmp.
    orig = hb.load_budget
    monkeypatch.setattr(hb, "load_budget", lambda _r: orig(tmp_path))
    code, failed, _ = hb.evaluate(root)
    assert code == 1
    assert any("sys_modules_added_on_import_anchor" in f for f in failed)
