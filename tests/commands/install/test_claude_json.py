"""What goes into ~/.claude.json."""

from pathlib import Path

from lmi.commands.install import claude_json


def test_path_is_the_dotfile_in_home(home):
    assert claude_json.path() == Path(str(home)) / ".claude.json"


def test_the_onboarding_key_has_a_lowercase_b():
    """MANDATORY. Silent failure: onboarding still runs.

    Verified in the Claude Code 2.1.222 key list and in a live ~/.claude.json.
    'hasCompletedOnBoarding' writes cleanly, parses cleanly, and does nothing -
    the user is greeted by the onboarding flow the command promised to skip.
    """
    assert claude_json.ONBOARDING_KEY == "hasCompletedOnboarding"


def test_absent_key_needs_an_update():
    assert claude_json.needs_update({}) is True


def test_false_needs_an_update():
    """A machine image shipping false must be corrected, not left alone."""
    assert claude_json.needs_update({"hasCompletedOnboarding": False}) is True


def test_already_true_needs_nothing():
    assert claude_json.needs_update({"hasCompletedOnboarding": True}) is False


def test_a_truthy_non_true_value_still_needs_an_update():
    assert claude_json.needs_update({"hasCompletedOnboarding": "yes"}) is True


def test_mark_complete_sets_exactly_one_key():
    doc = {"projects": {"/a": {"history": [1, 2]}}, "firstStartTime": "x"}
    marked = claude_json.mark_complete(doc)
    assert marked["hasCompletedOnboarding"] is True
    assert marked["projects"] == {"/a": {"history": [1, 2]}}
    assert marked["firstStartTime"] == "x"
    assert len(marked) == 3
