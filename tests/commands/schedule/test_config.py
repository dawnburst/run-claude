from datetime import datetime
from pathlib import Path

import pytest

from lmi.cli import main
from lmi.commands.schedule.config import build_config
from lmi.core.errors import LmiError


def _args(**kw):
    """A Namespace shaped like argparse produces, with defaults."""
    import argparse
    base = dict(prompt="do a thing", at=None, interval=None, count=None,
                workdir=None, flags="", log=None, state=None, resume=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_interval_without_count_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        build_config(_args(interval=5))
    assert exc.value.code == 2
    assert "-c" in str(exc.value)


def test_count_without_interval_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        build_config(_args(count=3))
    assert exc.value.code == 2
    assert "-i" in str(exc.value)


def test_interval_zero_counts_as_given():
    """-i 0 must not be mistaken for "not supplied"."""
    with pytest.raises(LmiError):
        build_config(_args(interval=0))
    cfg = build_config(_args(interval=0, count=2))
    assert cfg.interval_min == 0 and cfg.max_runs == 2


def test_count_must_be_positive():
    with pytest.raises(LmiError) as exc:
        build_config(_args(interval=1, count=0))
    assert exc.value.code == 2


def test_leading_zero_count_is_decimal_not_octal():
    """argparse type=int already does this; pin it so nobody 'fixes' it."""
    assert build_config(_args(interval=0, count=int("008"))).max_runs == 8


def test_no_interval_or_count_means_a_single_run():
    cfg = build_config(_args())
    assert cfg.max_runs == 1 and cfg.interval_min == 0


def test_malformed_at_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        build_config(_args(at="05/08/2026 22:00"))
    assert exc.value.code == 2
    assert "YYYY-MM-DD HH:MM" in str(exc.value)


def test_well_formed_at_is_parsed():
    cfg = build_config(_args(at="2026-08-05 22:00"))
    assert cfg.at == datetime(2026, 8, 5, 22, 0)


def test_missing_workdir_is_a_usage_error(tmp_path):
    with pytest.raises(LmiError) as exc:
        build_config(_args(workdir=str(tmp_path / "nope")))
    assert exc.value.code == 2


def test_prompt_that_is_a_directory_is_a_usage_error(tmp_path):
    with pytest.raises(LmiError) as exc:
        build_config(_args(prompt=str(tmp_path)))
    assert exc.value.code == 2
    assert "directory" in str(exc.value)


def test_prompt_file_is_detected(tmp_path):
    p = tmp_path / "task.md"
    p.write_text("from a file\n", encoding="utf-8")
    cfg = build_config(_args(prompt=str(p)))
    assert cfg.prompt_file == p.resolve() and cfg.prompt_text is None


def test_prompt_text_is_used_when_not_a_path():
    cfg = build_config(_args(prompt="just some words"))
    assert cfg.prompt_text == "just some words" and cfg.prompt_file is None


def test_flags_are_split_respecting_quotes():
    cfg = build_config(_args(flags='--verbose --model "sonnet 5"'))
    assert cfg.user_flags == ["--verbose", "--model", "sonnet 5"]


def test_non_numeric_interval_exits_2_via_argparse():
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "x", "-i", "abc", "-c", "2"])
    assert exc.value.code == 2


def test_two_positional_prompts_exits_2_via_argparse():
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "one", "two"])
    assert exc.value.code == 2


def test_unquoted_two_token_at_is_rejected():
    """A deliberate deviation from the .bat, which tolerates this. Supporting
    it needs nargs="+" on -t, which is greedy and would swallow the prompt in
    `-t "2026-08-05 22:00" "my prompt"`. A silent mis-parse is worse than
    requiring a quote, so the two-token form must fail loudly."""
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "x", "-t", "2026-08-05", "22:00"])
    assert exc.value.code == 2
