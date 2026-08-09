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

    Returning a copy is not politeness. The runner reads settings.json once and
    uses the same object for the origin snapshot; mutating `base` here would put
    the switched state into the snapshot, so `switch origin` would restore the
    switch instead of undoing it.
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
