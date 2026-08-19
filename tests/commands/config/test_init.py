"""`lmi config init` - putting the packaged config folder into ~/.lmi.

The command exists because `lmi install claude` was the only thing that ever
created ~/.lmi, so a machine whose folder had been deleted got it back only by
provisioning Claude Code again. Its whole behaviour is one sentence: copy every
file lmi ships to ~/.lmi, and **never overwrite one that is already there**.

That second half is what these tests are mostly about. `defaults.adopt` may
replace what it finds because it backs the folder up first (item 31's rule,
applied to a folder); this command backs up nothing, so the only thing standing
between an operator's own settings.json or switch file and a routine re-run of
the installer script is the skip. There is no copy behind it.
"""

import pytest

from lmi.commands.config import args as config_args
from lmi.commands.config import init
from lmi.commands.install import defaults
from lmi.core.errors import LmiError

from tests.conftest import skip_as_root


class Args:
    """What argparse hands the subcommand, plus the dispatcher's marker."""

    def __init__(self):
        setattr(self, config_args.RUN_MARKER, init.NAME)


# Every name that must land in ~/.lmi, under the name it lands as. lmi.json is
# deliberately absent: it becomes config.json, which is the name discovery
# looks for at the home level.
EXPECTED = (
    "config.json",
    "settings.json",
    "statusline.js",
    "settings_switch_gateway.json",
    "settings_switch_direct.json",
)


@pytest.fixture
def folder(home):
    """~/.lmi, in a throwaway home. Not created - that is the command's job."""
    return home / ".lmi"


def test_a_fresh_folder_gets_every_packaged_file(folder, capsys):
    assert init.run(Args()) == 0
    landed = sorted(p.name for p in folder.iterdir())
    assert landed == sorted(EXPECTED)
    out = capsys.readouterr().out
    assert str(folder) in out


def test_the_config_lands_under_the_name_discovery_looks_for(folder):
    """lmi.json -> config.json.

    MANDATORY. Adopting it under its packaged name produces a folder the next
    search walks straight past: ~/.lmi is searched for config.json and nothing
    else, so an ~/.lmi/lmi.json is a file with exactly the right contents in it
    that no command ever reads - item 39's shape, reached from a new direction.
    """
    assert init.run(Args()) == 0
    assert (folder / "config.json").is_file()
    assert not (folder / "lmi.json").exists()


def test_the_packaged_files_are_copied_byte_for_byte(folder):
    """No line-ending normalisation, no re-encoding.

    The same rule as statusline.install, which is what does the copying: these
    are the operator's files from the moment they land, and a settings.json
    whose CRLF became LF is lmi editing a document it was asked to place.
    """
    assert init.run(Args()) == 0
    for src in defaults.packaged_files(3):
        dest = defaults.destination(src, folder)
        assert dest.read_bytes() == src.read_bytes()


def test_an_existing_file_is_kept_byte_for_byte(folder):
    """MANDATORY. The never-overwrite rule, which is the whole command.

    Silent both ways if it goes: the installer scripts run this on every
    install, so an overwriting init replaces a site's edited settings.json or
    switch file with the packaged example on a routine re-install - reporting
    success, with no backup anywhere, and nothing afterwards to say the
    operator's version ever existed.
    """
    folder.mkdir(parents=True)
    mine = folder / "settings.json"
    mine.write_bytes(b'{"env": {"ANTHROPIC_AUTH_TOKEN": "mine"}}')
    switch = folder / "settings_switch_gateway.json"
    switch.write_bytes(b'{"env": {"ANTHROPIC_BASE_URL": "https://mine/"}}')

    assert init.run(Args()) == 0

    assert mine.read_bytes() == b'{"env": {"ANTHROPIC_AUTH_TOKEN": "mine"}}'
    assert switch.read_bytes() == \
        b'{"env": {"ANTHROPIC_BASE_URL": "https://mine/"}}'
    # ... and the ones that were missing are there.
    assert (folder / "config.json").is_file()
    assert (folder / "statusline.js").is_file()
    assert (folder / "settings_switch_direct.json").is_file()


def test_a_kept_file_is_reported_as_kept(folder, capsys):
    folder.mkdir(parents=True)
    (folder / "settings.json").write_bytes(b"{}")
    assert init.run(Args()) == 0
    out = capsys.readouterr().out
    assert "kept" in out
    assert "settings.json" in out


def test_a_second_run_changes_nothing_and_exits_zero(folder):
    """Idempotent by construction, because the installer scripts re-run it.

    Every install of the wheel calls this command, so "everything is already
    there" is the normal case and cannot be an error - and must not be a write
    either, or a re-install silently reverts the folder it was told to fill.
    """
    assert init.run(Args()) == 0
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    edited = folder / "config.json"
    edited.write_bytes(b'{"claude": {"registry": "https://mine/"}}')

    assert init.run(Args()) == 0

    after = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert sorted(after) == sorted(before)
    assert after["config.json"] == b'{"claude": {"registry": "https://mine/"}}'


def test_a_directory_in_the_way_is_kept_not_written_through(folder):
    """Anything already at the destination is left alone, file or not.

    A ~/.lmi/statusline.js that is a directory is somebody's mistake, but it is
    not this command's to correct: removing it to make room is a delete nobody
    asked for, and it is the one operation with no backup behind it.
    """
    (folder / "statusline.js").mkdir(parents=True)
    assert init.run(Args()) == 0
    assert (folder / "statusline.js").is_dir()
    assert (folder / "config.json").is_file()


@skip_as_root
def test_an_unwritable_folder_is_a_config_write_error(folder):
    folder.mkdir(parents=True)
    folder.chmod(0o500)
    try:
        with pytest.raises(LmiError) as caught:
            init.run(Args())
        assert caught.value.code == init.EXIT_CONFIG_WRITE
    finally:
        folder.chmod(0o700)


def test_a_broken_packaged_folder_is_refused_before_anything_is_copied(
        folder, tmp_path, monkeypatch):
    """MANDATORY. Item 48's refusal, from the second entry point.

    A folder missing either required half is a broken lmi rather than a
    misconfiguration. Copying whatever is left produces a config folder that
    fails at the *next* command with a message pointing at the operator, so the
    check has to happen before the first write - and it is the same check
    `adopt` makes, not a second one.
    """
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "lmi.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(defaults, "DIR", broken)
    monkeypatch.setattr(defaults, "CONFIG", broken / "lmi.json")
    monkeypatch.setattr(defaults, "TEMPLATE", broken / "settings.json")

    with pytest.raises(LmiError) as caught:
        init.run(Args())

    assert caught.value.code == init.EXIT_CONFIG_WRITE
    assert "settings.json" in str(caught.value)
    assert not folder.exists()


def test_the_shipped_switch_files_are_selectable_by_name(folder):
    """The names the operator types are the reason the pair ships at all.

    `settings_switch_<name>.json`, read through the catalog rather than by
    string surgery here: a file whose name the catalog cannot resolve is a
    switch that ships and cannot be applied, which is item 51's shape.
    """
    from lmi.commands.config import catalog

    assert init.run(Args()) == 0
    names, reserved = catalog.scan(folder)
    assert [name for name, _ in names] == ["direct", "gateway"]
    assert reserved == []
