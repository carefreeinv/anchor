from unittest.mock import patch

import check_docs_sync


def test_read_recorded_hashes_parses_sync_comment(tmp_path):
    docs_file = tmp_path / "page.md"
    docs_file.write_text("---\nsidebar_position: 1\n---\n\n"
                          "<!-- synced-from: some/source.md @ " + "a" * 40 + " -->\n\n# Title\n")

    assert check_docs_sync.read_recorded_hashes(docs_file) == [("some/source.md", "a" * 40)]


def test_read_recorded_hashes_empty_when_comment_missing(tmp_path):
    docs_file = tmp_path / "page.md"
    docs_file.write_text("---\nsidebar_position: 1\n---\n\n# Title\n")

    assert check_docs_sync.read_recorded_hashes(docs_file) == []


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


# -- many sources -> one page ----------------------------------------------

def test_sources_normalizes_both_key_shapes():
    from check_docs_sync import _sources

    assert _sources("a/b.md") == ("a/b.md",)
    assert _sources(("a/b.md", "c/d.md")) == ("a/b.md", "c/d.md")


def test_every_sync_map_source_exists():
    # A key naming a file that no longer exists would make its page silently
    # unguarded — git hash-object would fail rather than report drift.
    from check_docs_sync import REPO_ROOT, SYNC_MAP, _sources

    missing = [
        src for key in SYNC_MAP for src in _sources(key)
        if not (REPO_ROOT / src).is_file()
    ]
    assert not missing, f"SYNC_MAP names sources that do not exist: {missing}"


def test_multi_source_page_records_one_comment_per_source():
    from check_docs_sync import REPO_ROOT, SYNC_MAP, _sources, read_recorded_hashes

    multi = [(k, v) for k, v in SYNC_MAP.items() if len(_sources(k)) > 1]
    assert multi, "expected at least one multi-source page (mcp-servers)"
    for key, docs_rel in multi:
        recorded = dict(read_recorded_hashes(REPO_ROOT / docs_rel))
        assert set(recorded) == set(_sources(key)), (
            f"{docs_rel} records {sorted(recorded)}, expected {sorted(_sources(key))}"
        )


def test_the_mcp_servers_page_is_guarded():
    # The bug this page was corrected for was an unbounded `pip install "mcp[cli]"`
    # in the docs. Leaving the page unregistered meant nothing would catch it
    # drifting back.
    from check_docs_sync import SYNC_MAP, _sources

    guarded = {v: _sources(k) for k, v in SYNC_MAP.items()}
    page = "docs/docs/tooling/mcp-servers.md"
    assert page in guarded, f"{page} is not in SYNC_MAP"
    assert len(guarded[page]) == 3, "all three server READMEs should be sources"


def test_read_recorded_hashes_parses_several_comments(tmp_path):
    docs_file = tmp_path / "page.md"
    docs_file.write_text(
        "<!-- synced-from: a/one.md @ " + "a" * 40 + " -->\n"
        "<!-- synced-from: b/two.md @ " + "b" * 40 + " -->\n"
        "---\nsidebar_position: 1\n---\n\n# Title\n"
    )
    assert check_docs_sync.read_recorded_hashes(docs_file) == [
        ("a/one.md", "a" * 40),
        ("b/two.md", "b" * 40),
    ]
