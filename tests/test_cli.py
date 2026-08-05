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


def test_schedule_is_registered():
    from lmi.commands import COMMANDS
    assert [c.NAME for c in COMMANDS] == ["schedule"]


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
