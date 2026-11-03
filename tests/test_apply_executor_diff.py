from pathlib import Path

import pytest

from apply_executor_diff import (
    EDIT_FORMAT,
    ApplyError,
    NoApplyableHunks,
    apply_reply,
    extract_file_blocks,
    extract_patches,
    reply_has_applyable,
)


def test_extract_rejects_garbage():
    with pytest.raises(NoApplyableHunks):
        apply_reply("## Result\nok\n", Path("/tmp"))
    assert extract_patches("--- a/foo\nthis is not a plusplus\n") == []
    with pytest.raises(NoApplyableHunks):
        apply_reply("--- notes\nstill prose\n", Path("/tmp"))


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


def test_orphan_dash_with_fence_still_writes(tmp_path: Path):
    reply = (
        "```foo.py\n"
        "x = 1\n"
        "```\n"
        "--- notes\n"
        "prose separator\n"
        "## Result\nwrote foo.py\n"
        "## How to verify\ncat foo.py\n"
        "## Deferred / concerns\nnone\n"
    )
    written = apply_reply(reply, tmp_path)
    assert written == ["foo.py"]
    assert (tmp_path / "foo.py").read_text(encoding="utf-8") == "x = 1\n"


def test_apply_fenced_path_whole_file(tmp_path: Path):
    reply = (
        "here is the file\n"
        "```foo.py\n"
        "x = 1\n"
        "```\n"
        "## Result\nwrote foo.py\n"
        "## How to verify\ncat foo.py\n"
        "## Deferred / concerns\nnone\n"
    )
    apply_reply(reply, tmp_path)
    assert (tmp_path / "foo.py").read_text(encoding="utf-8") == "x = 1\n"


def test_apply_file_header_then_python_fence(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text("old\n", encoding="utf-8")
    reply = (
        "File: src/mod.py\n"
        "```python\n"
        "new = True\n"
        "```\n"
    )
    apply_reply(reply, tmp_path)
    assert (tmp_path / "src" / "mod.py").read_text(encoding="utf-8") == "new = True\n"


def test_edit_format_shows_fence_example():
    assert "```path/to/file.py" in EDIT_FORMAT
    assert "--- a/path/to/file" in EDIT_FORMAT


def test_fenced_body_with_nested_diff_writes_only_that_file(tmp_path: Path):
    reply = (
        "```notes.md\n"
        "see this example:\n"
        "--- a/other\n"
        "+++ b/other\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "```\n"
    )
    apply_reply(reply, tmp_path)
    assert (tmp_path / "notes.md").read_text(encoding="utf-8").startswith("see this")
    assert not (tmp_path / "other").exists()


def test_overlapping_file_blocks_error():
    reply = "```a.py\n1\n```\n```a.py\n2\n```\n"
    with pytest.raises(ApplyError, match="overlapping"):
        extract_file_blocks(reply)


def test_empty_fence_is_no_hunks(tmp_path: Path):
    with pytest.raises(NoApplyableHunks):
        apply_reply("```foo.py\n```\n", tmp_path)
    assert not (tmp_path / "foo.py").exists()


def test_file_header_blank_line_then_fence(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text("old\n", encoding="utf-8")
    reply = "File: src/mod.py\n\n```python\nnew = True\n```\n"
    apply_reply(reply, tmp_path)
    assert (tmp_path / "src" / "mod.py").read_text(encoding="utf-8") == "new = True\n"


def test_fenced_plans_denied(tmp_path: Path):
    with pytest.raises(ApplyError, match="may not write"):
        apply_reply("```.plans/bugs/x.md\nhi\n```\n", tmp_path)


def test_fenced_path_escape(tmp_path: Path):
    with pytest.raises(ApplyError, match="escapes"):
        apply_reply("```../../etc/passwd\nhacked\n```\n", tmp_path)


def test_apply_fenced_scripts_x_py(tmp_path: Path):
    reply = "```scripts/x.py\nprint(1)\n```\n"
    apply_reply(reply, tmp_path)
    assert (tmp_path / "scripts" / "x.py").read_text(encoding="utf-8") == "print(1)\n"


OVERLAP = (
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1 @@\n"
    "-a\n"
    "+b\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1 @@\n"
    "-a\n"
    "+c\n"
)


def test_extract_patches_raises_on_overlap():
    with pytest.raises(ApplyError, match="overlapping patches"):
        extract_patches(OVERLAP)


def test_reply_has_applyable_true_on_overlap():
    assert reply_has_applyable(OVERLAP) is True
