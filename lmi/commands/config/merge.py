"""The recursive merge that makes a switch touch only what it names.

Pure and total: no I/O, no error paths, one function. That is why it is its own
module - it is the piece most worth testing exhaustively, and it is easier to
be exhaustive about something with no dependencies.
"""

import copy


def deep_merge(base, overlay):
    """`base` with `overlay` applied. A new dict; neither argument is touched.

    Two dicts merge key by key, recursing. Anything else replaces whole - a list
    replaces a list rather than being appended to or unioned, because merging
    lists has no single right answer and guessing produces settings nobody wrote.

    Returning a copy is not politeness, though it is not the origin snapshot
    either: runner._switch calls origin.capture, which writes to disk, BEFORE
    this runs, so a mutating merge could not reach the snapshot. Two other
    reasons hold it. The runner still holds `current` after the merge and every
    caller is entitled to find its argument unchanged - a function that edits
    what it is handed is a trap whether or not today's caller notices. And the
    copy has to be deep: a shallow one would alias the nested dicts, so editing
    result["env"] would reach into base["env"] as well.
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
