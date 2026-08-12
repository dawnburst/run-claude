"""The nested subparser - `lmi config switch [origin] [--file PATH]`,
and `lmi config schedule [--mode MODE]`."""

import argparse

import pytest

from lmi.commands.config import args as config_args
from lmi.commands.config.subcommands import SUBCOMMANDS


def parser():
    p = argparse.ArgumentParser(prog="lmi config")
    config_args.add_arguments(p)
    return p


def test_switch_with_no_arguments_parses():
    ns = parser().parse_args(["switch"])
    assert ns.target is None
    assert ns.file is None


def test_origin_is_accepted_as_the_target():
    assert parser().parse_args(["switch", "origin"]).target == "origin"


def test_a_path_is_rejected_as_the_target():
    """MANDATORY. Silent failure: a filename read as the restore keyword.

    Paths only ever arrive behind --file. If the positional accepted arbitrary
    text, `lmi config switch prod.json` would look reasonable and would have to
    guess whether the word is a keyword or a file - the ambiguity the --file
    flag exists to remove.
    """
    with pytest.raises(SystemExit):
        parser().parse_args(["switch", "prod.json"])


def test_file_takes_a_path():
    assert parser().parse_args(["switch", "--file", "p.json"]).file == "p.json"


def test_f_is_the_short_form():
    assert parser().parse_args(["switch", "-f", "p.json"]).file == "p.json"


def test_origin_and_file_can_be_given_together_and_parse():
    """Parsing accepts it; the runner decides what it means (origin wins)."""
    ns = parser().parse_args(["switch", "origin", "--file", "p.json"])
    assert ns.target == "origin" and ns.file == "p.json"


def test_an_unknown_verb_is_rejected():
    with pytest.raises(SystemExit):
        parser().parse_args(["nosuchverb"])


def test_no_verb_leaves_the_marker_unset():
    """`lmi config` alone must be a usage error, which runner turns into exit 2."""
    assert getattr(parser().parse_args([]), "_config_run", None) is None


# --- the second subcommand, and the registry that made room for it --------

def test_schedule_with_no_arguments_parses_as_show():
    ns = parser().parse_args(["schedule"])
    assert ns.mode is None
    assert getattr(ns, config_args.RUN_MARKER) == "schedule"


def test_schedule_takes_a_mode_and_a_config():
    ns = parser().parse_args(["schedule", "--mode", "cli", "--config", "p.json"])
    assert ns.mode == "cli" and ns.config == "p.json"


def test_an_unknown_mode_reaches_the_command_rather_than_argparse():
    """MANDATORY. Silent failure: two spellings of the same mistake.

    --mode deliberately carries no `choices=`. With one, argparse would reject
    a bad value with its own wording and its own exit path, so the same typo
    would read one way here and another way from `lmi schedule` - which is the
    seam where a wrong mode actually costs something. One template, in
    backend.parse, with one list of valid names in it.
    """
    assert parser().parse_args(["schedule", "--mode", "claude"]).mode == "claude"


def test_each_subcommand_sets_its_own_marker():
    """The dispatch is the registry's, not a branch in args.py."""
    for command in SUBCOMMANDS:
        ns = parser().parse_args([command.NAME])
        assert getattr(ns, config_args.RUN_MARKER) == command.NAME


def test_the_help_order_is_the_registry_order():
    """Deterministic, which is why the registry is a list and not discovery."""
    text = parser().format_help()
    positions = [text.index(command.NAME) for command in SUBCOMMANDS]
    assert positions == sorted(positions)
    assert [c.NAME for c in SUBCOMMANDS] == sorted(c.NAME for c in SUBCOMMANDS)
