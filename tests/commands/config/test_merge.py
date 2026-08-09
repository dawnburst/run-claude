"""The recursive merge that makes a switch touch only what it names."""

from lmi.commands.config.merge import deep_merge


def test_an_unnamed_sibling_survives():
    base = {"env": {"A": "1", "B": "2"}, "model": "sonnet"}
    assert deep_merge(base, {"env": {"A": "9"}}) == {
        "env": {"A": "9", "B": "2"},
        "model": "sonnet",
    }


def test_siblings_survive_three_levels_down():
    base = {"a": {"b": {"c": {"keep": 1, "change": 1}}}}
    result = deep_merge(base, {"a": {"b": {"c": {"change": 2}}}})
    assert result == {"a": {"b": {"c": {"keep": 1, "change": 2}}}}


def test_a_scalar_replaces_a_scalar():
    assert deep_merge({"model": "sonnet"}, {"model": "opus"}) == {"model": "opus"}


def test_a_new_key_is_added():
    assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_a_list_replaces_rather_than_merging():
    """Merging lists has no single right answer - append? union? by index?

    Guessing produces a settings.json nobody wrote, so a list replaces whole.
    """
    assert deep_merge({"x": [1, 2, 3]}, {"x": [9]}) == {"x": [9]}


def test_an_object_replaces_a_scalar():
    assert deep_merge({"x": 5}, {"x": {"a": 1}}) == {"x": {"a": 1}}


def test_a_scalar_replaces_an_object():
    assert deep_merge({"x": {"a": 1}}, {"x": 5}) == {"x": 5}


def test_null_sets_and_does_not_delete():
    """MANDATORY. Silent failure: a key the user meant to blank disappears.

    `null` is a value. Treating it as a tombstone would make it impossible to
    ever set a key to null deliberately, and would quietly remove settings a
    fragment merely mentioned.
    """
    assert deep_merge({"a": 1, "b": 2}, {"a": None}) == {"a": None, "b": 2}


def test_neither_argument_is_mutated():
    """MANDATORY. deep_merge must never edit what it is handed.

    Not, as this docstring used to claim, because the origin snapshot comes from
    the same object: runner._switch calls origin.capture, which writes the
    snapshot to disk, BEFORE deep_merge runs, so a mutating merge could not
    reach it. The real reason is plainer and outlives that ordering. The runner
    goes on using `current` after the merge, and a helper that quietly edits its
    argument is a trap for whatever reads it next - here today, and at whatever
    call site is added later without re-reading this function.

    The test below pins the other half: the copy is deep, so no nested dict ends
    up shared between an input and the result.
    """
    base = {"env": {"A": "1"}}
    overlay = {"env": {"A": "9"}}
    deep_merge(base, overlay)
    assert base == {"env": {"A": "1"}}
    assert overlay == {"env": {"A": "9"}}


def test_nested_results_are_not_shared_with_the_inputs():
    base = {"env": {"A": "1"}}
    result = deep_merge(base, {"model": "opus"})
    result["env"]["A"] = "mutated"
    assert base["env"]["A"] == "1"


def test_an_empty_overlay_changes_nothing():
    assert deep_merge({"a": 1}, {}) == {"a": 1}


def test_an_empty_base_takes_the_overlay():
    assert deep_merge({}, {"a": 1}) == {"a": 1}
