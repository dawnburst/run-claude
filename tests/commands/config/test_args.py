"""The nested subparser - `lmi config switch [origin] [--file PATH]`."""

import argparse

import pytest

from lmi.commands.config import args as config_args


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
