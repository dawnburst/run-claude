"""The mode: one definition, one parser, one writer.

`backend.py` is imported by three commands - `schedule` reads the mode,
`lmi config schedule` writes it, `lmi install claude` writes it too - so a bug
here is a bug in all three at once, and the shape of it is always the same: one
command writes a value another refuses, or accepts a value it should not.
"""

import json
from pathlib import Path

import pytest

from lmi.commands.schedule import backend
from lmi.core import config as core_config
from lmi.core.errors import LmiError

from .conftest import _REAL_RESOLVE

CODE = 3            # a command's own code, passed in as backend.write requires


@pytest.fixture
def nowhere(tmp_path, monkeypatch):
    """A world with no config file anywhere discovery looks.

    A throwaway HOME and a working directory with no ./config/ in it, because
    discovery reads `Path.cwd()` and `~/.lmi/config.json` - a suite run from the
    repository root would otherwise find the checkout's own config/lmi.json, and
    a mode set on the developer's machine would change what the suite tests.

    Returns the working directory; `home` below is the other half.
    """
    monkeypatch.delenv(core_config.CONFIG_ENV_VAR, raising=False)
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


@pytest.fixture
def home(nowhere, tmp_path):
    """The throwaway HOME `nowhere` installed."""
    return tmp_path / "home"


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def resolve(explicit_config=None):
    """The real backend.resolve, past the autouse guard that replaces it.

    The guard in conftest.py patches `backend.resolve` so that a schedule test
    which resolves a backend without declaring one fails loudly. That would
    otherwise make the one function whose job is resolving a mode the one
    function in this package that cannot be tested - hence _REAL_RESOLVE,
    captured at import time.
    """
    return _REAL_RESOLVE(explicit_config)


# --- task 5: the parser ---------------------------------------------------

def test_both_valid_names_are_accepted():
    assert backend.parse("sdk", "a test") == "sdk"
    assert backend.parse("cli", "a test") == "cli"


@pytest.mark.parametrize("raw", [None, "", "SDK", "Cli", "claude", "sdk\n",
                                 " cli", 0, True, [], {}])
def test_every_other_value_is_exit_2(raw):
    """Never a silent fall back to the default.

    Case-sensitive on purpose, and `"SDK"` is in this list to pin that: folding
    it would mean this module deciding that a value the operator did not write
    is what they meant. The names are two words long - there is nothing to gain
    by guessing and a whole class of near-misses to get wrong quietly.

    `True` is here because `isinstance(True, int)` is a classic way for a
    non-string to slip through a laxer check; the parser tests `isinstance(raw,
    str)` first."""
    with pytest.raises(LmiError) as exc:
        backend.parse(raw, "a test")
    assert exc.value.code == 2


def test_the_message_names_both_valid_names_and_where_the_value_came_from():
    """"cli or sdk" without "in this file" leaves the operator hunting through
    four discoverable config files for which one said it."""
    with pytest.raises(LmiError) as exc:
        backend.parse("claude", "/etc/lmi/lmi.json")
    text = str(exc.value)
    assert "sdk" in text and "cli" in text
    assert "/etc/lmi/lmi.json" in text
    assert "claude" in text                      # the offending value itself


def test_a_null_mode_is_reported_as_null_not_as_none():
    """The operator wrote JSON, so the message has to speak JSON back."""
    with pytest.raises(LmiError) as exc:
        backend.parse(None, "a test")
    assert "null" in str(exc.value)
    assert "None" not in str(exc.value)


# --- task 5: absent is not null -------------------------------------------

def test_an_absent_section_means_the_default():
    mode, source = backend.of_document({}, "lmi.json")
    assert mode == backend.DEFAULT == "sdk"
    assert source == backend.DEFAULT_SOURCE == "default"


def test_an_absent_key_means_the_default():
    mode, source = backend.of_document({"schedule": {}}, "lmi.json")
    assert mode == "sdk" and source == "default"


def test_an_explicit_null_mode_is_refused_not_defaulted():
    """MANDATORY. Item 18's rule in its fourth home. `.get(KEY)` alone cannot
    tell an absent key from `"mode": null`, and null is a value the operator
    wrote - refusing it is the only way to say so. Collapsing the two is
    **silent**: a machine deliberately set to something the operator got wrong
    runs on the default instead, and both backends exit 0 on success."""
    with pytest.raises(LmiError) as exc:
        backend.of_document({"schedule": {"mode": None}}, "lmi.json")
    assert exc.value.code == 2


def test_a_valid_mode_reports_the_file_it_came_from():
    """The source is what item 33's header line prints, so it must be the path
    rather than a generic "a config file"."""
    mode, source = backend.of_document({"schedule": {"mode": "cli"}},
                                       "/tmp/lmi.json")
    assert mode == "cli"
    assert source == "/tmp/lmi.json"


def test_a_non_object_schedule_section_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        backend.of_document({"schedule": "cli"}, "lmi.json")
    assert exc.value.code == 2


def test_a_non_object_document_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        backend.of_document([1, 2, 3], "lmi.json")
    assert exc.value.code == 2


# --- task 8: the one writer -----------------------------------------------

def test_the_writer_creates_the_section_when_it_is_absent(tmp_path):
    path = tmp_path / "lmi.json"
    path.write_text(json.dumps({"claude": {"registry": "x"}}), encoding="utf-8")

    backend.write(path, "cli", CODE)

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schedule"]["mode"] == "cli"


def test_the_writer_merges_and_never_replaces_the_document(tmp_path):
    """MANDATORY. An lmi.json carries the `claude` and `lmi` sections two other
    commands depend on. Writing only what this command knows about would
    **silently unprovision the machine**: the next `lmi install claude` would
    find no registry, and the file would look deliberate."""
    original = {
        "claude": {"registry": "https://artifactory/api/npm/npm",
                   "cafile": "/etc/ssl/ca.pem",
                   "index": "https://artifactory/api/pypi/pypi/simple"},
        "lmi": {"index": "https://artifactory/api/pypi/pypi/simple"},
        "schedule": {"mode": "sdk", "something_else": 1},
    }
    path = tmp_path / "lmi.json"
    path.write_text(json.dumps(original), encoding="utf-8")

    backend.write(path, "cli", CODE)

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["claude"] == original["claude"]
    assert doc["lmi"] == original["lmi"]
    assert doc["schedule"]["mode"] == "cli"
    # And the rest of the section survives too - only the one key changes.
    assert doc["schedule"]["something_else"] == 1


def test_the_writer_validates_through_the_same_parser(tmp_path):
    """One parser, so `lmi install` can never write a value `lmi schedule`
    refuses. The check happens BEFORE the file is read, so a bad mode leaves
    the document untouched."""
    path = tmp_path / "lmi.json"
    path.write_text('{"claude": {}}', encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(LmiError) as exc:
        backend.write(path, "SDK", CODE)
    assert exc.value.code == 2
    assert path.read_bytes() == before


def test_an_unparseable_config_file_is_refused_not_overwritten(tmp_path):
    """MANDATORY. Item 19, inherited free from core/jsonfile.py and not to be
    re-implemented here. Treating an unparseable file as `{}` would discard
    everything the operator had - and this file carries the registry, the CA
    file and the index."""
    path = tmp_path / "lmi.json"
    path.write_text('{"claude": {"registry": "x",,,', encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(LmiError) as exc:
        backend.write(path, "cli", CODE)
    assert exc.value.code == CODE
    assert str(path) in str(exc.value)
    assert path.read_bytes() == before            # byte for byte


def test_a_non_object_schedule_section_is_refused_by_the_writer(tmp_path):
    """Replacing it would discard whatever the operator put there."""
    path = tmp_path / "lmi.json"
    path.write_text('{"schedule": "cli"}', encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(LmiError) as exc:
        backend.write(path, "cli", CODE)
    assert exc.value.code == CODE
    assert path.read_bytes() == before


def test_a_written_mode_reads_back_through_the_reader(tmp_path):
    """The round trip is the point: the writer and the reader are the two ends
    of one contract, and a test of either alone can pass while they disagree."""
    path = tmp_path / "lmi.json"
    path.write_text("{}", encoding="utf-8")

    for mode in (backend.CLI, backend.SDK):
        backend.write(path, mode, CODE)
        doc = json.loads(path.read_text(encoding="utf-8"))
        got, source = backend.of_document(doc, path)
        assert got == mode
        assert source == str(path)


# --- task 6: resolve, which is discovery plus of_document ------------------
#
# of_document is tested above from a dict; these are the other half - that the
# mode is read from the file `lmi schedule` would actually read, through
# core/config.py's discovery unchanged. A resolve() that read a different file
# from the one `lmi config schedule` writes is the silent failure item 39 names,
# from the reading end.

def _source_is(source, path):
    """The reported source names that file.

    Compared resolved rather than as strings: discovery builds its candidates
    with .absolute(), which does not follow the symlink some platforms put in
    front of the temporary directory, so a string comparison would fail for a
    reason that has nothing to do with the mode.
    """
    return Path(source).resolve() == Path(path).resolve()


def test_no_config_file_anywhere_means_the_default(nowhere):
    assert resolve() == (backend.DEFAULT, backend.DEFAULT_SOURCE)


def test_the_working_directory_config_file_is_read(nowhere):
    path = write_json(nowhere / "config" / "lmi.json",
                      {"schedule": {"mode": "cli"}})
    mode, source = resolve()
    assert mode == "cli"
    assert _source_is(source, path)


def test_the_home_config_file_is_read(nowhere, home):
    path = write_json(home / ".lmi" / "config.json",
                      {"schedule": {"mode": "cli"}})
    mode, source = resolve()
    assert mode == "cli"
    assert _source_is(source, path)


def test_the_env_var_config_file_is_read(nowhere, monkeypatch, tmp_path):
    path = write_json(tmp_path / "env" / "lmi.json",
                      {"schedule": {"mode": "cli"}})
    monkeypatch.setenv(core_config.CONFIG_ENV_VAR, str(path))
    mode, source = resolve()
    assert mode == "cli"
    assert _source_is(source, path)


def test_the_discovery_order_is_unchanged(nowhere, home, monkeypatch, tmp_path):
    """--config, then $LMI_CONFIG, then ./config/lmi.json, then ~/.lmi.

    No new search path and no new precedence rule: the mode is read from the
    file every other command already reads. A backend that resolved its own
    order would mean `lmi install claude` provisioning one file while
    `lmi schedule` read another - and both exit 0.
    """
    env = write_json(tmp_path / "env" / "lmi.json", {"schedule": {"mode": "cli"}})
    named = write_json(tmp_path / "named" / "lmi.json",
                       {"schedule": {"mode": "sdk"}})
    write_json(nowhere / "config" / "lmi.json", {"schedule": {"mode": "sdk"}})
    write_json(home / ".lmi" / "config.json", {"schedule": {"mode": "sdk"}})

    monkeypatch.setenv(core_config.CONFIG_ENV_VAR, str(env))

    # --config beats everything, including the env var.
    mode, source = resolve(str(named))
    assert mode == "sdk" and _source_is(source, named)

    # and the env var beats both defaults.
    mode, source = resolve()
    assert mode == "cli" and _source_is(source, env)


def test_the_working_directory_file_beats_the_home_one(nowhere, home):
    winner = write_json(nowhere / "config" / "lmi.json",
                        {"schedule": {"mode": "cli"}})
    write_json(home / ".lmi" / "config.json", {"schedule": {"mode": "sdk"}})
    mode, source = resolve()
    assert mode == "cli"
    assert _source_is(source, winner)


def test_a_config_file_with_no_schedule_section_gives_the_default(nowhere):
    """And reports "default" rather than the path, which is item 33's other
    half: "this file chose it" and "nothing chose it" are different facts and
    the header must not make them confusable."""
    write_json(nowhere / "config" / "lmi.json", {"claude": {"registry": "x"}})
    assert resolve() == (backend.DEFAULT, backend.DEFAULT_SOURCE)


def test_an_invalid_mode_in_the_discovered_file_is_exit_2(nowhere):
    write_json(nowhere / "config" / "lmi.json", {"schedule": {"mode": "claude"}})
    with pytest.raises(LmiError) as exc:
        resolve()
    assert exc.value.code == 2
    # Spelled from Path.cwd() rather than from the fixture, because that is what
    # discovery builds its candidate from - and on a platform whose temporary
    # directory sits behind a symlink the two strings differ for a reason that
    # has nothing to do with the mode.
    assert str(Path.cwd() / "config" / "lmi.json") in str(exc.value)


def test_a_config_given_with_config_that_does_not_exist_is_exit_2(nowhere):
    """Inherited from core/config.py and worth pinning here too: a named file
    that quietly resolves to a different one is how a machine ends up on a
    backend nobody chose."""
    with pytest.raises(LmiError) as exc:
        resolve(str(nowhere / "nope.json"))
    assert exc.value.code == 2


def test_a_file_left_at_the_pre_move_path_is_refused(nowhere):
    """Item 21, reached through resolve. **Silent** if skipped: the next
    candidate is ~/.lmi/config.json - possibly a different site - so the run
    would read its mode from there while an lmi.json sat in plain view in the
    working directory."""
    write_json(nowhere / "lmi.json", {"schedule": {"mode": "cli"}})
    with pytest.raises(LmiError) as exc:
        resolve()
    assert exc.value.code == 2
    assert str(Path.cwd() / "lmi.json") in str(exc.value), "the file it found"
    assert str(Path.cwd() / "config" / "lmi.json") in str(exc.value), \
        "and where it belongs"


def test_the_pre_move_path_never_trips_up_an_explicit_config(nowhere):
    """--config ./lmi.json is the escape hatch the refusal itself offers."""
    legacy = write_json(nowhere / "lmi.json", {"schedule": {"mode": "cli"}})
    mode, source = resolve(str(legacy))
    assert mode == "cli"
    assert _source_is(source, legacy)


def test_an_unparseable_config_file_is_exit_2_rather_than_the_default(nowhere):
    """Not a missing file: a file that is there and cannot be read. Falling back
    to the default here would silently run the wrong backend on a machine whose
    operator had deliberately configured one."""
    path = nowhere / "config" / "lmi.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schedule": }', encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        resolve()
    assert exc.value.code == 2


def test_what_the_writer_writes_is_what_resolve_reads(nowhere, home):
    """The two ends of item 39, in one test: `lmi config schedule` writes
    through backend.write and `lmi schedule` reads through backend.resolve, and
    a test of either alone can pass while they disagree about which file."""
    path = write_json(home / ".lmi" / "config.json", {"claude": {}})
    backend.write(path, "cli", CODE)
    mode, source = resolve()
    assert mode == "cli"
    assert _source_is(source, path)


def test_the_written_file_ends_in_lf_only(tmp_path):
    """Section 4 rule 4. The CRLF half can only be caught by a real Windows
    run - `jsonfile.write`'s O_BINARY is what carries it - but the POSIX half
    is worth pinning here, beside the writer that depends on it."""
    path = tmp_path / "lmi.json"
    path.write_text("{}", encoding="utf-8")
    backend.write(path, "cli", CODE)
    assert b"\r\n" not in path.read_bytes()
