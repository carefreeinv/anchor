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


# -- behavioural: many sources actually drive check() and stamp() ------------
#
# The tests above assert *structure* (normalisation, existence, comment count).
# None of them ran check() or stamp() against a key with more than one source,
# so these mutations all survived a full green suite:
#
#   check(): `for source_rel in sources:` -> `sources[:1]`   (2nd/3rd source ignored)
#   stamp(): writes one comment            -> `sources[:1]`   (page under-stamped)
#   SYNC_MAP: drop a 1:1 entry                                (page silently unguarded)
#
# Each test below fails against exactly one of those.


def _two_source_map(monkeypatch, tmp_path, docs_text: str):
    monkeypatch.setattr(check_docs_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_docs_sync, "SYNC_MAP",
                        {("one.md", "two.md"): "doc.md"})
    (tmp_path / "doc.md").write_text(docs_text, encoding="utf-8")


@patch("check_docs_sync.git_blob_hash")
def test_check_reports_a_change_to_the_SECOND_source(mock_hash, tmp_path, monkeypatch):
    # Kills `sources[:1]` in check(): the first source is unchanged, so a
    # checker that only ever looks at sources[0] reports nothing.
    _two_source_map(monkeypatch, tmp_path,
                    f"<!-- synced-from: one.md @ {'a' * 40} -->\n"
                    f"<!-- synced-from: two.md @ {'b' * 40} -->\n# Title\n")
    mock_hash.side_effect = lambda src: {"one.md": "a" * 40, "two.md": "c" * 40}[src]

    problems = check_docs_sync.check()

    assert len(problems) == 1, problems
    assert "two.md" in problems[0] and "stale" in problems[0]


@patch("check_docs_sync.git_blob_hash")
def test_check_passes_when_every_source_matches(mock_hash, tmp_path, monkeypatch):
    _two_source_map(monkeypatch, tmp_path,
                    f"<!-- synced-from: one.md @ {'a' * 40} -->\n"
                    f"<!-- synced-from: two.md @ {'b' * 40} -->\n# Title\n")
    mock_hash.side_effect = lambda src: {"one.md": "a" * 40, "two.md": "b" * 40}[src]

    assert check_docs_sync.check() == []


@patch("check_docs_sync.git_blob_hash")
def test_stamp_writes_a_comment_for_every_source(mock_hash, tmp_path, monkeypatch):
    # Kills `sources[:1]` in stamp(): an under-stamped page then reads back as
    # "no synced-from line for 'two.md'" forever, or silently loses the guard.
    _two_source_map(monkeypatch, tmp_path, "---\nsidebar_position: 1\n---\n\n# Title\n")
    mock_hash.side_effect = lambda src: {"one.md": "a" * 40, "two.md": "b" * 40}[src]

    check_docs_sync.stamp()

    assert check_docs_sync.read_recorded_hashes(tmp_path / "doc.md") == [
        ("one.md", "a" * 40),
        ("two.md", "b" * 40),
    ]
    # And the round trip is clean: stamping then checking reports nothing.
    assert check_docs_sync.check() == []


def test_the_eight_one_to_one_pairs_are_still_registered():
    # Kills "delete an entry from SYNC_MAP": dropping a page leaves it unguarded
    # while the checker still reports OK, one page quieter than before. The plan
    # constraint is that the pre-existing 1:1 entries survive the many-source
    # change untouched.
    from check_docs_sync import SYNC_MAP, _sources

    one_to_one = {
        next(iter(_sources(k))): v for k, v in SYNC_MAP.items() if len(_sources(k)) == 1
    }
    expected = {
        "anchor/ANCHOR.md": "docs/docs/doctrine.md",
        "anchor/model-fitness.md": "docs/docs/model-fitness.md",
        "anchor/capacity-routing.md": "docs/docs/capacity-routing.md",
        "platforms/claude-code/CLAUDE.md": "docs/docs/platforms/claude-code.md",
        "platforms/grok-build/GROK.md": "docs/docs/platforms/grok-build.md",
        "platforms/nvidia-nim/NEMOTRON.md": "docs/docs/platforms/nvidia-nim.md",
        "platforms/local-models/README.md": "docs/docs/platforms/local-models.md",
        "platforms/chat/CHAT.md": "docs/docs/platforms/chat.md",
    }
    assert one_to_one == expected
