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
    """MANDATORY. Silent failure: the origin snapshot written from a mutated dict.

    runner reads settings.json once and passes it here. If deep_merge mutated
    `base`, the snapshot taken from that same object would already carry the
    switch - so `switch origin` would restore the switched state and the user's
    real settings would be gone, with nothing to show it happened.
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
