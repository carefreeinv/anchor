from pathlib import Path

import pytest
from handoff import (
    Handoff,
    HandoffError,
    accumulate,
    build_continuation,
    check_scope_shrinks,
    looks_like_handoff,
    parse_handoff,
)

TEMPLATE = Path(__file__).resolve().parent.parent / "anchor" / "templates" / "handoff.md"

HANDOFF_TEXT = """# Handoff: add CSV export

## Done
- [x] Added the export button — verified by `pytest tests/test_ui.py -q` → pass
- [x] Wired the route — verified by `pytest -q` → unverified

## Remaining

### 1. Serialize the rows

- Goal: stream report rows as CSV
- Files in scope: app/export.py
- Verify by: `pytest tests/test_export.py -q`
- Notes: the header row is already written by the route

### 2. Document the endpoint

- Goal: document the new endpoint
- Files in scope: docs/api.md
- Verify by: `npm run docs:build`

## Decisions made
- Streamed rather than buffered — reports can exceed memory

## Files touched
- `app/routes.py` — added the /export route

## Open concerns
- Large exports are untested above 100k rows
"""


def _handoff(**overrides) -> Handoff:
    base = parse_handoff(HANDOFF_TEXT)
    return Handoff(**{**base.__dict__, **overrides})


# --- template round-trip (the artifact and the parser must agree) -------------


def test_template_round_trips_through_the_parser():
    """The shipped template is itself a valid handoff.

    If the template drifts from the parser, every executor that follows it
    faithfully gets rejected — so the template is the fixture.
    """
    text = TEMPLATE.read_text(encoding="utf-8")

    assert looks_like_handoff(text)
    parsed = parse_handoff(text)

    assert parsed.done
    assert parsed.decisions
    assert parsed.files_touched
    assert parsed.concerns
    assert len(parsed.remaining) == 2
    assert all(item.verify_by for item in parsed.remaining)


def test_template_guidance_comments_are_not_parsed_as_content():
    """HTML comments in the template are instructions, not handoff data."""
    parsed = parse_handoff(TEMPLATE.read_text(encoding="utf-8"))

    assert not any("REQUIRED" in line for line in parsed.done)
    assert not any("dispatchable" in line for line in parsed.concerns)


# --- parsing ------------------------------------------------------------------


def test_parses_all_five_sections():
    parsed = parse_handoff(HANDOFF_TEXT)

    assert len(parsed.done) == 2
    assert "export button" in parsed.done[0]
    assert [item.title for item in parsed.remaining] == ["1. Serialize the rows",
                                                         "2. Document the endpoint"]
    assert parsed.remaining[0].verify_by == "pytest tests/test_export.py -q"
    assert parsed.remaining[0].files == ("app/export.py",)
    assert parsed.remaining[0].notes.startswith("the header row")
    assert parsed.decisions == ("Streamed rather than buffered — reports can exceed memory",)
    assert parsed.files_touched[0].startswith("`app/routes.py`")
    assert parsed.concerns == ("Large exports are untested above 100k rows",)
    assert parsed.scope == ("app/export.py", "docs/api.md")


def test_looks_like_handoff_is_false_for_a_normal_task_result():
    assert not looks_like_handoff("did the thing\n## Result\nok\n## How to verify\npytest -q\n")


def test_missing_section_names_what_is_missing():
    text = HANDOFF_TEXT.replace("## Decisions made\n", "## Choices\n")

    assert not looks_like_handoff(text)
    with pytest.raises(HandoffError, match="Decisions made"):
        parse_handoff(text)


def test_remaining_item_without_verify_by_is_rejected():
    """Undispatchable remaining work is the failure this parser exists to catch."""
    text = HANDOFF_TEXT.replace("- Verify by: `npm run docs:build`\n", "")

    with pytest.raises(HandoffError, match="Verify by"):
        parse_handoff(text)


def test_handoff_with_no_remaining_items_is_rejected():
    """A handoff with nothing left is a finished task pretending to be a handoff."""
    head, tail = HANDOFF_TEXT.split("## Remaining", 1)
    rest = "## Decisions made" + tail.split("## Decisions made", 1)[1]
    text = f"{head}## Remaining\n\nall finished\n\n{rest}"

    with pytest.raises(HandoffError, match="sub-specs"):
        parse_handoff(text)


# --- scope may only shrink ----------------------------------------------------


def test_scope_shrink_allows_a_subset_of_the_original_scope():
    check_scope_shrinks(parse_handoff(HANDOFF_TEXT), ("app/", "docs/"))  # no raise


def test_scope_shrink_rejects_a_path_the_original_spec_never_allowed():
    with pytest.raises(HandoffError, match="docs/api.md"):
        check_scope_shrinks(parse_handoff(HANDOFF_TEXT), ("app/",))


def test_scope_check_is_skipped_when_no_scope_was_declared():
    check_scope_shrinks(parse_handoff(HANDOFF_TEXT), ())  # no raise


# --- continuation building ----------------------------------------------------


def test_continuation_carries_done_decisions_and_only_remaining_work():
    text = build_continuation("Add CSV export to reports", parse_handoff(HANDOFF_TEXT),
                              window=2)

    assert "CONTINUATION (window 2)" in text
    assert "Add CSV export to reports" in text          # original task still stated
    assert "do NOT redo" in text and "export button" in text
    assert "do NOT reverse" in text and "Streamed rather than buffered" in text
    assert "Serialize the rows" in text                  # remaining work dispatched
    assert "pytest tests/test_export.py -q" in text      # ...with its verify command
    assert "only shrink" in text


def test_continuation_refuses_to_widen_scope():
    with pytest.raises(HandoffError, match="only shrink"):
        build_continuation("task", parse_handoff(HANDOFF_TEXT), window=2, in_scope=("app/",))


def test_accumulate_keeps_earlier_history_and_latest_remaining():
    first = parse_handoff(HANDOFF_TEXT)
    second = _handoff(done=("[x] Serialized the rows — verified by `pytest -q` → pass",),
                      decisions=("Used the csv module — stdlib beats a dependency",),
                      remaining=first.remaining[1:])

    merged = accumulate(first, second)

    assert "export button" in merged.done[0]        # window 1 history survives
    assert "Serialized the rows" in merged.done[-1]  # window 2 appended
    assert len(merged.decisions) == 2
    assert [item.title for item in merged.remaining] == ["2. Document the endpoint"]


def test_accumulate_deduplicates_repeated_history():
    first = parse_handoff(HANDOFF_TEXT)

    merged = accumulate(first, first)

    assert len(merged.done) == len(first.done)


# --- an empty field must not swallow the next line -----------------------------
# `\s` crosses newlines. With it, `- Goal:\n- Files in scope: deploy/prod.yaml`
# parsed as goal="- Files in scope: deploy/prod.yaml" with NO files — so the
# shrink check saw an empty scope and passed, while build_continuation still
# emitted that path into the fresh continuation.


EMPTY_FIELD_HANDOFF = """# Handoff: sneaky

## Done
- [x] something — verified by `pytest -q` → pass

## Remaining

### 1. Finish it

- Goal:
- Files in scope: deploy/prod.yaml
- Verify by: `pytest -q`

## Decisions made
- none

## Files touched
- `app/x.py` — edited

## Open concerns
- none
"""


def test_empty_field_does_not_absorb_the_following_line():
    parsed = parse_handoff(EMPTY_FIELD_HANDOFF)

    assert parsed.remaining[0].goal == ""
    assert parsed.remaining[0].files == ("deploy/prod.yaml",)   # seen, not swallowed
    assert parsed.scope == ("deploy/prod.yaml",)


def test_scope_smuggled_via_an_empty_field_is_still_refused():
    with pytest.raises(HandoffError, match="deploy/prod.yaml"):
        check_scope_shrinks(parse_handoff(EMPTY_FIELD_HANDOFF), ("app/",))


def test_empty_files_in_scope_does_not_eat_the_verify_line():
    """The same bug false-rejected honest handoffs, burning the one retry."""
    text = EMPTY_FIELD_HANDOFF.replace("- Files in scope: deploy/prod.yaml",
                                       "- Files in scope:")

    parsed = parse_handoff(text)  # must not raise "no Verify by"

    assert parsed.remaining[0].verify_by == "pytest -q"
    assert parsed.remaining[0].files == ()
