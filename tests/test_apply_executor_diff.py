from pathlib import Path

import pytest

from apply_executor_diff import (
    ApplyError,
    NoApplyableHunks,
    apply_reply,
    extract_patches,
)


def test_extract_rejects_garbage():
    with pytest.raises(NoApplyableHunks):
        apply_reply("## Result\nok\n", Path("/tmp"))
    with pytest.raises(ApplyError, match="not followed"):
        extract_patches("--- a/foo\nthis is not a plusplus\n")


def test_apply_unified_diff_tmp_path(tmp_path: Path):
    (tmp_path / "hello.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    reply = (
        "did it\n"
        "--- a/hello.txt\n"
        "+++ b/hello.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " one\n"
        "-two\n"
        "+TWO\n"
        " three\n"
        "## Result\nedited hello.txt\n"
        "## How to verify\ncat hello.txt\n"
        "## Deferred / concerns\nnone\n"
    )
    written = apply_reply(reply, tmp_path)
    assert written == ["hello.txt"]
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"


def test_apply_fenced_diff_new_file(tmp_path: Path):
    reply = (
        "```diff\n"
        "--- /dev/null\n"
        "+++ b/src/new.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+x = 1\n"
        "+y = 2\n"
        "```\n"
    )
    apply_reply(reply, tmp_path)
    assert (tmp_path / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\ny = 2\n"


def test_apply_rejects_plans_and_escape(tmp_path: Path):
    with pytest.raises(ApplyError, match="may not write"):
        apply_reply(
            "--- /dev/null\n+++ b/.plans/bugs/x.md\n@@ -0,0 +1 @@\n+hi\n",
            tmp_path,
        )
    with pytest.raises(ApplyError, match="escapes"):
        extract_patches("--- a/foo\n+++ b/../../etc/passwd\n@@ -1 +1 @@\n-a\n+b\n")
        apply_reply(
            "--- a/foo\n+++ b/../../etc/passwd\n@@ -1 +1 @@\n-a\n+b\n",
            tmp_path,
        )


def test_apply_rejects_context_mismatch(tmp_path: Path):
    (tmp_path / "f.txt").write_text("aaa\n", encoding="utf-8")
    with pytest.raises(ApplyError, match="context mismatch"):
        apply_reply(
            "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-bbb\n+ccc\n",
            tmp_path,
        )
