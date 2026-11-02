import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


@pytest.fixture(autouse=True)
def _disable_reasoning_logs_by_default(monkeypatch):
    """Keep unit tests from writing ``<cwd>/var/log`` unless they opt in."""
    monkeypatch.setenv("ANCHOR_NO_REASONING_LOG", "1")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A fresh git repo with one committed file (README) on branch main."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README").write_text("hi\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    _git(root, "branch", "-M", "main")
    return root
