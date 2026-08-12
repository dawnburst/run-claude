from datetime import datetime

import pytest

from lmi.cli import main
from lmi.commands.schedule.config import build_config
from lmi.core.errors import LmiError

from .conftest import FIXTURE_SOURCE


def _args(**kw):
    """A Namespace shaped like argparse produces, with defaults."""
    import argparse
    base = dict(prompt="do a thing", at=None, interval=None, count=None,
                workdir=None, flags="", log=None, state=None, resume=False,
                verbose=False)
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


def test_interval_zero_counts_as_given(cli_mode):
    """-i 0 must not be mistaken for "not supplied"."""
    with pytest.raises(LmiError):
        build_config(_args(interval=0))
    cfg = build_config(_args(interval=0, count=2))
    assert cfg.interval_min == 0 and cfg.max_runs == 2


def test_count_must_be_positive():
    with pytest.raises(LmiError) as exc:
        build_config(_args(interval=1, count=0))
    assert exc.value.code == 2


def test_leading_zero_count_is_decimal_not_octal(cli_mode):
    """argparse type=int already does this; pin it so nobody 'fixes' it."""
    assert build_config(_args(interval=0, count=int("008"))).max_runs == 8


def test_no_interval_or_count_means_a_single_run(cli_mode):
    cfg = build_config(_args())
    assert cfg.max_runs == 1 and cfg.interval_min == 0


def test_malformed_at_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        build_config(_args(at="05/08/2026 22:00"))
    assert exc.value.code == 2
    assert "YYYY-MM-DD HH:MM" in str(exc.value)


def test_well_formed_at_is_parsed(cli_mode):
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


def test_a_long_inline_prompt_is_text_not_a_crash(cli_mode):
    """MANDATORY. Path(prompt).is_dir() raises ENAMETOOLONG once any
    slash-free run reaches 256 bytes - a 143-character Hebrew sentence does
    it. That was an unhandled OSError: a raw traceback and exit 1, the code
    that means "a claude call failed", before the lock and before any log."""
    long_prompt = "א" * 143
    assert len(long_prompt.encode("utf-8")) >= 256
    cfg = build_config(_args(prompt=long_prompt))
    assert cfg.prompt_text == long_prompt and cfg.prompt_file is None

    # And the ASCII boundary, both sides of it.
    for n in (255, 256, 4096):
        assert build_config(_args(prompt="x" * n)).prompt_text == "x" * n


def test_a_prompt_with_a_nul_byte_is_text_not_a_crash(cli_mode):
    """os.stat raises ValueError, not OSError, for an embedded NUL."""
    assert build_config(_args(prompt="a\x00b")).prompt_text == "a\x00b"


def test_an_empty_prompt_reports_a_missing_argument(tmp_path):
    """Path("") is PosixPath('.'), which is a directory, so an empty prompt
    used to be reported as "the prompt argument is a directory"."""
    for value in ("", "   "):
        with pytest.raises(LmiError) as exc:
            build_config(_args(prompt=value))
        assert exc.value.code == 2
        assert "empty" in str(exc.value)
        assert "directory" not in str(exc.value)


def test_a_workdir_that_is_a_file_says_not_a_directory(tmp_path):
    f = tmp_path / "afile.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        build_config(_args(workdir=str(f)))
    assert exc.value.code == 2
    assert "not a directory" in str(exc.value)
    assert "does not exist" not in str(exc.value)


def test_an_over_long_workdir_is_a_usage_error(tmp_path):
    with pytest.raises(LmiError) as exc:
        build_config(_args(workdir=str(tmp_path / ("d" * 300))))
    assert exc.value.code == 2


def test_prompt_file_is_detected(tmp_path, cli_mode):
    p = tmp_path / "task.md"
    p.write_text("from a file\n", encoding="utf-8")
    cfg = build_config(_args(prompt=str(p)))
    assert cfg.prompt_file == p.resolve() and cfg.prompt_text is None


def test_prompt_text_is_used_when_not_a_path(cli_mode):
    cfg = build_config(_args(prompt="just some words"))
    assert cfg.prompt_text == "just some words" and cfg.prompt_file is None


def test_flags_are_split_respecting_quotes(cli_mode):
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
    """A deliberate restriction. Supporting
    it needs nargs="+" on -t, which is greedy and would swallow the prompt in
    `-t "2026-08-05 22:00" "my prompt"`. A silent mis-parse is worse than
    requiring a quote, so the two-token form must fail loudly."""
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "x", "-t", "2026-08-05", "22:00"])
    assert exc.value.code == 2


def test_verbose_is_off_unless_asked_for(cli_mode):
    assert build_config(_args()).verbose is False


def test_v_turns_verbose_on(cli_mode):
    assert build_config(_args(verbose=True)).verbose is True


def test_verbose_with_an_output_format_in_f_is_a_usage_error():
    """MANDATORY. -f is appended after lmi's own flags and claude takes the
    last occurrence of a repeated option, so -f "--output-format json"
    overrides the stream-json that -v relies on. The renderer is then handed
    something it cannot parse. Silent: the activity block goes quiet and the
    iteration still reports exit 0, so nothing distinguishes "claude did
    nothing worth showing" from "lmi could not read what claude said"."""
    for flags in ('--output-format json',
                  '--output-format=json',
                  '--model opus --output-format text'):
        with pytest.raises(LmiError) as exc:
            build_config(_args(verbose=True, flags=flags))
        assert exc.value.code == 2
        assert "--output-format" in str(exc.value)
        assert "-v" in str(exc.value)


def test_an_output_format_in_f_is_fine_without_verbose(cli_mode):
    """Without -v lmi sets no output format, so there is nothing to collide
    with and the flag is the user's business."""
    cfg = build_config(_args(flags="--output-format json"))
    assert cfg.user_flags == ["--output-format", "json"]


def test_a_duplicate_verbose_in_f_is_allowed(cli_mode):
    """--verbose is a boolean, so a second occurrence is idempotent - unlike
    --output-format, which is last-wins. Deduplicating it would mean lmi
    learning claude's flag grammar, and risk silently dropping a user flag."""
    cfg = build_config(_args(verbose=True, flags="--verbose"))
    assert cfg.verbose is True and cfg.user_flags == ["--verbose"]


# --- -f is forwarded in BOTH backends ------------------------------------

def test_flags_are_accepted_under_the_sdk_backend(sdk_mode):
    """-f works in both modes. In SDK mode the flags are handed to the SDK as
    `extra_args`, which it renders onto the argv of the `claude` it spawns - so
    they reach the same command line they would have in CLI mode.

    lmi does not learn what any of them mean. It converts token shape into the
    mapping the SDK wants and knows only the four names it must refuse."""
    cfg = build_config(_args(flags="--model opus --max-turns 3 --dangerously-x"))
    assert cfg.user_flags == ["--model", "opus", "--max-turns", "3",
                              "--dangerously-x"]
    from lmi.commands.schedule import sdk
    assert sdk.parse_flags(cfg.user_flags) == {
        "model": "opus", "max-turns": "3", "dangerously-x": None,
    }


def test_the_equals_form_and_dash_leading_values(sdk_mode):
    """`--flag=value` always binds; a bare value beginning with `-` cannot be
    told apart from the next flag, so the equals form is how those are written."""
    from lmi.commands.schedule import sdk
    assert sdk.parse_flags(["--append-system-prompt=-x"]) == {
        "append-system-prompt": "-x"}
    assert sdk.parse_flags(["--a", "--b"]) == {"a": None, "b": None}


def test_a_flag_the_sdk_cannot_forward_is_a_usage_error(sdk_mode):
    """MANDATORY. `extra_args` is appended AFTER the flags the SDK builds for
    itself and the CLI takes the last occurrence, so forwarding one of these
    does not add anything - it overrides the SDK's own and breaks the protocol
    the two of them speak.

    Refused rather than dropped: -f is where a site puts what it cannot say any
    other way, so silently ignoring one is the failure worth avoiding. The
    message names the flag, the reason, and the way out."""
    for flag in ("--output-format json", "--input-format stream-json",
                 "--permission-mode plan", "--print"):
        with pytest.raises(LmiError) as exc:
            build_config(_args(flags=flag))
        assert exc.value.code == 2, flag
        assert flag.split()[0] in str(exc.value), flag
        assert "lmi config schedule --mode cli" in str(exc.value), flag


def test_a_short_option_in_f_is_refused_under_the_sdk_backend(sdk_mode):
    """The SDK forwards flags as a name/value mapping, which cannot spell a
    single-dash option - so it is refused rather than mangled into `---p`."""
    with pytest.raises(LmiError) as exc:
        build_config(_args(flags="-p"))
    assert exc.value.code == 2
    assert "long options" in str(exc.value)


def test_the_same_flags_are_untouched_under_the_cli_backend(cli_mode):
    """CLI mode appends -f to the argv verbatim, so nothing here may filter it -
    including the four SDK mode refuses, which mean nothing to a plain argv."""
    cfg = build_config(_args(flags="--print --permission-mode plan"))
    assert cfg.user_flags == ["--print", "--permission-mode", "plan"]


def test_the_sdk_backend_is_fine_without_f(sdk_mode):
    """The mirror: only a non-empty -f is refused. An SDK-mode run with no
    flags at all must build a Config like any other."""
    cfg = build_config(_args())
    assert cfg.user_flags == []
    assert cfg.mode == "sdk"


def test_f_still_works_under_the_cli_backend(cli_mode):
    """Task 37's other half: nothing about -f changes for the backend that
    still has a command line to put it on."""
    cfg = build_config(_args(flags="--model opus --max-turns 3"))
    assert cfg.user_flags == ["--model", "opus", "--max-turns", "3"]


def test_the_output_format_refusal_survives_under_the_cli_backend(cli_mode):
    """MANDATORY. Item 26 must keep its exit 2 now that a second refusal sits
    beside it. The two are independent: this one is about -v and -f colliding,
    task 37's is about -f having no destination at all."""
    with pytest.raises(LmiError) as exc:
        build_config(_args(verbose=True, flags="--output-format json"))
    assert exc.value.code == 2
    assert "--output-format" in str(exc.value)


# --- the mode reaches the Config -----------------------------------------

def test_the_config_carries_the_mode_and_its_source(cli_mode):
    """The header line (item 33) is built from these two fields, so a Config
    that carried the mode without its source would leave the log unable to say
    whether a config file chose the backend or nothing did."""
    cfg = build_config(_args())
    assert cfg.mode == "cli"
    assert cfg.mode_source == FIXTURE_SOURCE
