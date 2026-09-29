"""
No-key regression guarantee for the story/caption pipeline.

With GEMINI_API_KEY unset, generated books must be identical to the output the
code produced before the story-content rework (captured in
tests/fixtures/golden_story_nokey.json). The rework's cache, validation, chapter
captions and display boundary are all supposed to be invisible offline; this is
the test that holds them to it.
"""

import json

import pytest

from tests.fixtures.golden_story import GOLDEN_PATH, build, golden_payload


@pytest.fixture
def offline(monkeypatch):
    import app.engine.story_ai as story_ai

    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "")
    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", False)


def test_offline_output_matches_golden(offline):
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    actual = golden_payload(build())

    # Projection first: when it differs, pytest prints which book, variation and
    # spread moved, which a bare digest mismatch cannot tell you.
    for key in expected["projection"]:
        assert actual["projection"][key] == expected["projection"][key], f"offline output changed for {key}"
    assert set(actual["projection"]) == set(expected["projection"])
    assert actual["full_sha256"] == expected["full_sha256"], (
        "Projection matches but the full output differs: a field outside the "
        "text/structure projection changed."
    )
