"""`lmi config schedule` - showing the backend, and writing one.

Two things make this command dangerous out of proportion to its size.

A mode is invisible in the outcome: both backends exit 0 when they work, so a
write that lands in a file `lmi schedule` does not read reports success, leaves
a file with exactly the right contents in it, and changes nothing for ever.
Only the runner's header line would ever reveal it.

And the *showing* half is the debugging tool for every other silent failure in
this area - it is the only thing that answers "which of four discoverable
config files is my `lmi schedule` actually reading, and where would a change
go?" So its third line, the one that is not deducible from the other two, is
pinned as hard as the writes are.
"""

import json

import pytest

from lmi.commands.config import args as config_args
from lmi.commands.config import runner, schedule
from lmi.commands.schedule import backend
from lmi.core.errors import LmiError


class Args:
    """What argparse hands the subcommand, plus the dispatcher's marker."""

    def __init__(self, mode=None, config=None):
        self.mode = mode
        self.config = config
        setattr(self, config_args.RUN_MARKER, schedule.NAME)


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def read_mode(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get("schedule", {}).get("mode")


@pytest.fixture
def nowhere(tmp_path, monkeypatch, home):
    """A world with no config file anywhere discovery looks.

    A throwaway HOME and a working directory with no ./config/ in it. Both are
    needed: discovery reads Path.cwd(), so a test run from the repository root
    would otherwise find the checkout's own config/lmi.json and quietly test
    something else.
    """
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


# --- showing --------------------------------------------------------------

def test_showing_with_no_config_file_names_the_default_and_where_it_would_go(
        nowhere, home, capsys):
    assert schedule.run(Args()) == 0
    out = capsys.readouterr().out
    assert "Backend    : %s" % backend.DEFAULT in out
    assert "Chosen by  : %s" % backend.DEFAULT_SOURCE in out
    assert str(home / ".lmi" / "config.json") in out
    assert "would be created" in out


def test_showing_names_the_file_the_mode_came_from(nowhere, capsys):
    path = write_json(nowhere / "config" / "lmi.json",
                      {"schedule": {"mode": "cli"}})

    assert schedule.run(Args()) == 0
    out = capsys.readouterr().out
    assert "Backend    : cli" in out
    assert str(path) in out


def test_showing_distinguishes_the_default_from_the_file_a_write_goes_to(
        nowhere, capsys):
    """The third line is the one that is not deducible from the other two.

    A config file with no "schedule" section gives the DEFAULT backend from no
    file at all, while a --mode would still land in that file. Collapsing the
    two lines into one would answer the wrong question in exactly the case an
    operator is most likely to be asking it.
    """
    path = write_json(nowhere / "config" / "lmi.json",
                      {"claude": {"registry": "https://r/"}})

    assert schedule.run(Args()) == 0
    out = capsys.readouterr().out
    assert "Chosen by  : %s" % backend.DEFAULT_SOURCE in out
    assert "--mode goes to: %s" % path in out
    assert "would be created" not in out


def test_showing_an_invalid_mode_is_exit_2_not_the_default(nowhere):
    """There is deliberately no fall back to the default when reading, either.

    A run that silently used a backend the operator did not choose is
    indistinguishable from one that used the right one, because both exit 0.
    """
    write_json(nowhere / "config" / "lmi.json", {"schedule": {"mode": "SDK"}})

    with pytest.raises(LmiError) as exc:
        schedule.run(Args())
    assert exc.value.code == 2


# --- setting --------------------------------------------------------------

def test_an_invalid_mode_touches_no_file_and_reads_like_lmi_schedule(nowhere):
    """One message template, in backend.parse, with one list of valid names.

    --mode deliberately has no argparse `choices=`: argparse would reject a bad
    value with its own wording, so the same typo would read one way here and
    another way from `lmi schedule` - and the two are the same mistake.
    """
    path = write_json(nowhere / "config" / "lmi.json",
                      {"schedule": {"mode": "cli"}})
    before = path.read_bytes()

    with pytest.raises(LmiError) as exc:
        schedule.run(Args(mode="claude"))
    assert exc.value.code == 2
    assert ", ".join(backend.MODES) in str(exc.value)
    assert path.read_bytes() == before, "validated before anything is looked up"


def test_a_write_merges_into_the_discovered_file(nowhere):
    path = write_json(nowhere / "config" / "lmi.json", {
        "claude": {"registry": "https://r/", "index": "https://i/"},
        "lmi": {"index": "https://i/"},
    })

    assert schedule.run(Args(mode="cli")) == 0

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schedule"] == {"mode": "cli"}
    assert doc["claude"]["registry"] == "https://r/"
    assert doc["lmi"] == {"index": "https://i/"}


def test_the_write_lands_in_the_file_that_wins(nowhere, home):
    """MANDATORY. Silent failure: the right contents in the wrong file.

    Two discoverable config files, and only one of them is the one
    `lmi schedule` reads. Writing the other reports success and leaves a file
    that looks exactly right, while the machine keeps its old backend for ever.
    """
    winner = write_json(nowhere / "config" / "lmi.json",
                        {"schedule": {"mode": "sdk"}})
    loser = write_json(home / ".lmi" / "config.json",
                       {"schedule": {"mode": "sdk"}})

    assert schedule.run(Args(mode="cli")) == 0

    assert read_mode(winner) == "cli"
    assert read_mode(loser) == "sdk", "the shadowed file must be left alone"


def test_a_write_that_would_be_shadowed_is_exit_2(nowhere, home, monkeypatch):
    """MANDATORY. Silent failure: a mode written where nothing reads it.

    Only reachable for a file this command CREATES - when discovery found one,
    that is the winner by definition. So the case is a higher-priority file
    appearing while this command runs: another operator, a config-management
    tool, a checkout done in the working directory a moment ago. Rare, and the
    only shape of failure here that leaves the command reporting success with
    the file it named sitting there containing exactly what it says.

    Simulated by creating the winner during the write, which is precisely the
    interleaving the re-check exists to catch.
    """
    real_write = schedule.backend.write

    def write(path, mode, code):
        real_write(path, mode, code)
        write_json(nowhere / "config" / "lmi.json", {"schedule": {"mode": "sdk"}})

    monkeypatch.setattr(schedule.backend, "write", write)

    with pytest.raises(LmiError) as exc:
        schedule.run(Args(mode="cli"))

    assert exc.value.code == 2
    message = str(exc.value)
    assert str(home / ".lmi" / "config.json") in message, "the file written"
    assert str(nowhere / "config" / "lmi.json") in message, "and the one that wins"
    assert "--config" in message, "and the way out"


def test_creating_a_config_file_from_nothing_writes_the_home_one(nowhere, home):
    """A backend is a property of the machine, not of a directory.

    ~/.lmi/config.json rather than ./config/lmi.json, which would be committed
    by accident from inside a checkout.
    """
    assert schedule.run(Args(mode="cli")) == 0

    created = home / ".lmi" / "config.json"
    assert read_mode(created) == "cli"
    assert not (nowhere / "config" / "lmi.json").exists()


def test_an_explicit_config_is_written_even_when_another_file_wins(
        nowhere, tmp_path):
    """--config names the file, so there is nothing to be shadowed by."""
    write_json(nowhere / "config" / "lmi.json", {"schedule": {"mode": "sdk"}})
    named = write_json(tmp_path / "elsewhere" / "lmi.json", {"claude": {}})

    assert schedule.run(Args(mode="cli", config=str(named))) == 0

    assert read_mode(named) == "cli"
    assert read_mode(nowhere / "config" / "lmi.json") == "sdk"


def test_an_unparseable_config_file_is_refused_not_overwritten(nowhere):
    """Item 19, reached through backend.write's use of core/jsonfile.py.

    Treating it as {} would discard everything the operator had.
    """
    path = nowhere / "config" / "lmi.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"claude": }', encoding="utf-8")

    with pytest.raises(LmiError) as exc:
        schedule.run(Args(mode="cli"))
    assert exc.value.code == 3
    assert str(path) in str(exc.value)
    assert path.read_text(encoding="utf-8") == '{"claude": }'


# --- through the dispatcher ------------------------------------------------

def test_the_dispatcher_reaches_the_subcommand(nowhere, home, capsys):
    """The registry, not an if/elif: `config` learns nothing about `schedule`."""
    assert runner.run(Args()) == 0
    assert "Backend    :" in capsys.readouterr().out
