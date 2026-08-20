"""The repo as a source of versions: its newest tag, and how versions order.

Nothing here reaches a real git. `fake_git` replaces PATH entirely, the way
`fake_claude` and `fake_npm` do, because a real `git ls-remote` in a test is a
network call whose answer changes under it.
"""

import pytest

from lmi.commands.upgrade import repo


# --- version order ---------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("0.2.1", (0, 2, 1)),
    ("v0.2.1", (0, 2, 1)),
    ("V0.2.1", (0, 2, 1)),
    ("1.0", (1, 0)),
    ("2", (2,)),
    ("  v3.4.5  ", (3, 4, 5)),
])
def test_a_version_becomes_a_tuple_of_integers(text, expected):
    assert repo.parse_version(text) == expected


@pytest.mark.parametrize("text", [
    "", "v", "nightly", "release_final", "v1.0-rc1", "0.3.0rc1", "0.3.0.dev2",
    "latest", "v1.2.x", None, "1.2.3-4",
])
def test_anything_that_is_not_a_plain_version_is_not_ordered(text):
    """Ignored rather than ordered, because there is no ordering for these that
    is not a guess - and a guess here means claiming a machine is out of date
    when it is not."""
    assert repo.parse_version(text) is None


def test_versions_compare_as_numbers_not_as_strings():
    """MANDATORY - item 61's second half.

    `"0.10.0" > "0.9.0"` is False as a string, which would tell a machine
    running 0.9.0 that it is current for every release from 0.10.0 onward - the
    exact failure this feature exists to remove, and it looks like nothing.
    """
    assert repo.is_newer("0.10.0", "0.9.0")
    assert not repo.is_newer("0.9.0", "0.10.0")
    assert repo.is_newer("1.0.0", "0.99.99")
    assert not repo.is_newer("0.99.99", "1.0.0")


def test_equal_versions_are_not_newer():
    assert not repo.is_newer("0.2.1", "0.2.1")
    assert not repo.is_newer("v0.2.1", "0.2.1")


def test_a_shorter_version_is_not_newer_than_its_own_prefix():
    """0.2 and 0.2.0 are the same release written two ways; neither is an
    upgrade to the other."""
    assert not repo.is_newer("0.2", "0.2.0")
    assert not repo.is_newer("0.2.0", "0.2")
    assert repo.is_newer("0.2.1", "0.2")


@pytest.mark.parametrize("candidate,running", [
    ("nightly", "0.2.1"), ("0.3.0", "nightly"), (None, "0.2.1"),
    ("0.3.0", None), ("", ""),
])
def test_an_unparseable_side_is_never_newer(candidate, running):
    """MANDATORY - item 61. Silence is the safe direction: a false "a newer lmi
    is available" is indistinguishable from a true one, and after the second
    false alarm the line is noise."""
    assert not repo.is_newer(candidate, running)


# --- the remote ------------------------------------------------------------

URL = "https://example.invalid/lmi.git"


def test_the_newest_tag_is_read_from_ls_remote(fake_git):
    fake_git.tags(["v0.1.0", "v0.9.0", "v0.10.0", "v0.2.1"])
    tag = repo.newest_tag(URL)
    assert tag.name == "v0.10.0"
    assert tag.version == (0, 10, 0)


def test_the_argv_is_a_read_only_ls_remote_of_the_configured_url(fake_git):
    """No clone, no fetch, no write anywhere on the machine: a lookup must not
    be able to change anything, least of all a checkout the operator is in."""
    fake_git.tags(["v0.3.0"])
    repo.newest_tag(URL)
    argv = fake_git.calls()[0]
    assert argv[0] == "ls-remote"
    assert "--tags" in argv
    assert URL in argv
    for forbidden in ("clone", "fetch", "pull", "checkout", "-C"):
        assert forbidden not in argv


def test_tags_that_are_not_versions_are_ignored(fake_git):
    fake_git.tags(["nightly", "v0.2.0", "release_final", "v0.3.0-rc1"])
    tag = repo.newest_tag(URL)
    assert tag.name == "v0.2.0"


def test_a_remote_with_no_version_tags_answers_nothing(fake_git):
    fake_git.tags(["nightly", "release_final"])
    assert repo.newest_tag(URL) is None


def test_an_annotated_tags_dereference_line_is_not_a_second_tag(fake_git):
    """`ls-remote --tags` prints `refs/tags/v1^{}` for an annotated tag as well
    as the tag itself. Read as a name it parses to nothing, which is right, but
    it must not shadow the real one either."""
    fake_git.raw("abc123\trefs/tags/v0.4.0\ndef456\trefs/tags/v0.4.0^{}\n")
    tag = repo.newest_tag(URL)
    assert tag.name == "v0.4.0"


def test_a_failing_git_answers_nothing(fake_git):
    fake_git.rc(128)
    assert repo.newest_tag(URL) is None


def test_no_git_on_path_answers_nothing(monkeypatch, tmp_path):
    """The commonest case on a locked-down machine, and it must be silent: git
    is not a dependency of lmi, it is a thing this one lookup can use if it is
    there."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert repo.newest_tag(URL) is None


def test_a_hanging_git_is_abandoned_rather_than_waited_out(fake_git):
    """MANDATORY - item 62. This is the only network call on `lmi schedule`'s
    startup path; an unreachable git host must not delay an unattended run's
    first iteration."""
    import time
    fake_git.hang(30)
    started = time.time()
    assert repo.newest_tag(URL, timeout=1) is None
    assert time.time() - started < 10


# --- a tag name is not the version it carries ------------------------------

@pytest.mark.parametrize("text,expected", [
    ("v0.3.0", "0.3.0"),
    ("0.3.0", "0.3.0"),
    ("V1.2", "1.2"),
    ("nightly", None),
    ("", None),
    (None, None),
])
def test_the_version_a_tag_name_carries(text, expected):
    """MANDATORY - item 22 in a new place.

    `verify.confirm` compares what it was told to expect against what the
    installed console script reports. Handed a tag name it fails a perfectly
    good upgrade with "expected v0.3.0, got 0.3.0" - which reads exactly like
    the stale-wheel failure that check exists to catch.
    """
    assert repo.version_string(text) == expected
