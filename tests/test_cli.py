import pytest
from lmi.cli import main


def test_no_command_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "schedule" in capsys.readouterr().err


def test_version_flag_exits_0():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc:
        main(["nosuchcommand"])
    assert exc.value.code == 2


def test_the_registry_lists_every_command_in_help_order():
    """The intended tripwire: adding a command must update this list.

    Registry order is --help order, and `install` comes first because that is
    the order a user meets the commands - install the tool, then schedule it.
    """
    from lmi.commands import COMMANDS
    assert [c.NAME for c in COMMANDS] == ["install", "schedule"]


def test_every_command_satisfies_the_contract():
    from lmi.commands import COMMANDS
    for c in COMMANDS:
        assert isinstance(c.NAME, str) and c.NAME
        assert isinstance(c.HELP, str) and c.HELP
        assert callable(c.add_arguments)
        assert callable(c.run)


def test_lmi_error_carries_its_exit_code():
    from lmi.core.errors import LmiError, EXIT_USAGE
    assert LmiError("boom").code == EXIT_USAGE
    assert LmiError("boom", 3).code == 3
