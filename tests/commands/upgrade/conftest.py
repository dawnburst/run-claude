"""Fixtures for the `lmi upgrade` suite.

`fake_pip` used to live here. It moved to tests/conftest.py when
`lmi install claude` became the second command that runs pip: one seam faked
twice is two descriptions of pip that drift apart, and the two commands then
disagree about what pip looks like rather than about what it does. Nothing else
in this suite needs a fixture of its own, so this file is a pointer.

Everything that made it worth having is unchanged: pip is never found on PATH -
it is always `<interpreter> -m pip` - so the seam is the interpreter, and no
test may reach a real pip or a real index, because a real one would install a
real package over the developer's own lmi.
"""
