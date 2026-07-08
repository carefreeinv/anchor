from unittest.mock import patch

import check_docs_sync


def test_read_recorded_hash_parses_sync_comment(tmp_path):
    docs_file = tmp_path / "page.md"
    docs_file.write_text("---\nsidebar_position: 1\n---\n\n"
                          "<!-- synced-from: some/source.md @ " + "a" * 40 + " -->\n\n# Title\n")

    assert check_docs_sync.read_recorded_hash(docs_file) == ("some/source.md", "a" * 40)


def test_read_recorded_hash_none_when_comment_missing(tmp_path):
    docs_file = tmp_path / "page.md"
    docs_file.write_text("---\nsidebar_position: 1\n---\n\n# Title\n")

    assert check_docs_sync.read_recorded_hash(docs_file) is None


@patch("check_docs_sync.git_blob_hash")
def test_check_flags_stale_hash(mock_hash, tmp_path, monkeypatch):
    docs_path = tmp_path / "doc.md"
    docs_path.write_text(f"<!-- synced-from: src.md @ {'a' * 40} -->\n# Title\n")
    monkeypatch.setattr(check_docs_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_docs_sync, "SYNC_MAP", {"src.md": "doc.md"})
    mock_hash.return_value = "b" * 40  # current source hash differs from the recorded one

    problems = check_docs_sync.check()

    assert len(problems) == 1
    assert "stale" in problems[0]


@patch("check_docs_sync.git_blob_hash")
def test_check_passes_when_hash_matches(mock_hash, tmp_path, monkeypatch):
    docs_path = tmp_path / "doc.md"
    docs_path.write_text(f"<!-- synced-from: src.md @ {'a' * 40} -->\n# Title\n")
    monkeypatch.setattr(check_docs_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_docs_sync, "SYNC_MAP", {"src.md": "doc.md"})
    mock_hash.return_value = "a" * 40

    assert check_docs_sync.check() == []


def test_check_flags_missing_comment(tmp_path, monkeypatch):
    docs_path = tmp_path / "doc.md"
    docs_path.write_text("# Title, no sync comment\n")
    monkeypatch.setattr(check_docs_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_docs_sync, "SYNC_MAP", {"src.md": "doc.md"})

    problems = check_docs_sync.check()

    assert len(problems) == 1
    assert "missing 'synced-from'" in problems[0]
