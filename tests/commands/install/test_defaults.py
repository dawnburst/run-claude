"""The config folder packaged inside lmi, and adopting it into ~/.lmi."""

import json

import pytest

from lmi.commands.install import config, defaults, statusline, template
from lmi.commands.install.exit_codes import EXIT_CONFIG_WRITE
from lmi.core import config as core_config
from lmi.core.errors import LmiError


class Args:
    def __init__(self, config=None, target="claude"):
        self.config = config
        self.target = target


def said(lines):
    return "\n".join(lines)


@pytest.fixture
def recorder():
    """A `say` that keeps what it was told."""
    lines = []
    return lines, lines.append


def test_both_packaged_files_exist_and_are_a_valid_config_folder(tmp_path):
    """The packaged pair is used as shipped, on a machine with nothing else.

    Every other config folder is copied and edited first, so a bad shape there
    costs somebody a first day. This one is the easy path failing where it is
    supposed to be easiest.
    """
    assert defaults.CONFIG.is_file()
    assert defaults.TEMPLATE.is_file()
    assert defaults.TEMPLATE.parent == defaults.CONFIG.parent, \
        "template.load reads the neighbour of the config file"

    cfg = config.build_config(Args(config=str(defaults.CONFIG)))
    assert cfg.registry
    assert cfg.index
    assert cfg.cafile is None
    assert cfg.strict_ssl is None, "the packaged default touches nobody's TLS"


def test_the_packaged_config_is_the_two_urls_a_site_must_change():
    """Two keys, both a URL, and nothing else to unpick.

    `registry` is the npm source and `index` the PyPI one the SDK comes from -
    the two things that differ between sites and cannot be guessed. Everything
    else stays out: `cafile` is checked to exist, so any value here would be
    exit 2 on a machine that does not have that file, and `strict-ssl` absent
    leaves the machine's npm alone (item 49).
    """
    doc = json.loads(defaults.CONFIG.read_text(encoding="utf-8"))
    assert set(doc["claude"]) == {"registry", "index"}
    assert "cafile" not in doc["claude"]


def test_the_packaged_template_carries_the_placeholder_not_a_token():
    """Item 30: the placeholder is what the blank-answer refusal protects."""
    doc = json.loads(defaults.TEMPLATE.read_text(encoding="utf-8"))
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "<Token from the user input>"


def test_the_packaged_folder_ships_a_statusline_and_declares_it():
    """MANDATORY. Item 32, both directions, for the folder in the wheel.

    The packaged folder is now the only default that ships, and a statusline is
    two files: the `statusLine` block in the template and the script its
    command runs. Either half alone is **silent** - a command pointing at a
    file that is not there, or a script in ~/.claude that nothing runs - and
    both report success. This is the one config folder no operator assembled,
    so nobody else will notice.
    """
    doc = json.loads(defaults.TEMPLATE.read_text(encoding="utf-8"))
    script = defaults.DIR / statusline.NAME
    assert script.is_file(), "%s must ship beside the template" % statusline.NAME
    assert statusline.declares(doc), \
        "the template must declare the statusLine that runs it"


def test_adopt_returns_a_config_the_user_placed_unchanged(tmp_path, recorder):
    lines, say = recorder
    mine = tmp_path / "lmi.json"
    assert defaults.adopt(mine, say) == mine
    assert lines == [], "nothing to announce, nothing to copy"


def test_adopt_copies_the_pair_into_the_home_config_folder(home, recorder):
    """MANDATORY. Silent failure: a mode written where nothing reads it.

    `schedule.mode` must land in the file discovery resolves. The packaged copy
    is not that file: `lmi schedule` searches through find_optional, which has
    no packaged candidate, and site-packages is replaced by the next upgrade
    anyway. Writing the mode there would leave a file with exactly the right
    contents in it that nothing ever reads - item 39, reached from a new
    direction.
    """
    lines, say = recorder
    landed = defaults.adopt(defaults.CONFIG, say)

    assert landed == core_config.expand(core_config.HOME_CONFIG)
    assert landed == home / ".lmi" / "config.json"
    assert json.loads(landed.read_text(encoding="utf-8")) == \
        json.loads(defaults.CONFIG.read_text(encoding="utf-8"))
    assert "packaged with lmi" in said(lines)


def test_adopt_copies_the_template_too(home, recorder):
    """Both halves or neither.

    An operator who edits the config file lmi just created for them would
    otherwise meet "no settings template found" - from a folder lmi made.
    """
    _, say = recorder
    landed = defaults.adopt(defaults.CONFIG, say)
    beside = landed.parent / template.NAME

    assert beside.is_file()
    doc, source = template.load(landed)
    assert source == beside
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "<Token from the user input>"


def test_what_adopt_wrote_is_what_discovery_then_finds(
        tmp_path, home, recorder, monkeypatch):
    """Item 39's re-check, satisfied by construction rather than a second search.

    Discovery only reaches the packaged folder when $LMI_CONFIG, ./config and
    ~/.lmi are all empty, so the copy cannot be shadowed by something with a
    higher priority. This pins that reasoning: after adopting, the ordinary
    search resolves the file adopt wrote.
    """
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    (tmp_path / "work").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path / "work")

    _, say = recorder
    landed = defaults.adopt(defaults.CONFIG, say)
    found, _ = core_config.find_optional(None)
    assert found == landed


def test_adopting_twice_is_a_no_op_after_the_first(home, recorder):
    """The second install finds ~/.lmi by the ordinary search and never returns.

    Called with the adopted path rather than the packaged one, which is what
    build_config resolves once the folder exists.
    """
    _, say = recorder
    landed = defaults.adopt(defaults.CONFIG, say)
    landed.write_text('{"claude": {"registry": "https://mine/"}}',
                      encoding="utf-8")

    assert defaults.adopt(landed, say) == landed
    assert "mine" in landed.read_text(encoding="utf-8"), \
        "an edited config must never be overwritten by the packaged one"


def test_an_unwritable_home_is_reported_not_swallowed(home, recorder,
                                                      monkeypatch):
    """Better a named failure than a mode silently written into the wheel."""
    _, say = recorder

    def refuse(*a, **kw):
        raise LmiError("nope", 4)

    monkeypatch.setattr(defaults.statusline, "install", refuse)
    with pytest.raises(LmiError):
        defaults.adopt(defaults.CONFIG, say)


# --- adopting the whole folder, and preserving what was there -------------

def packaged_names():
    """Every file in the packaged folder, as adopt should name them in ~/.lmi.

    lmi.json becomes config.json because that is what discovery looks for at
    the home level; everything else keeps the name it shipped with.
    """
    out = set()
    for path in defaults.DIR.iterdir():
        if not path.is_file():
            continue
        out.add("config.json" if path.name == core_config.CWD_CONFIG_NAME
                else path.name)
    return out


def test_adopt_copies_every_file_in_the_packaged_folder(home, recorder):
    """Not just the two it used to name.

    A switch file or a statusline.js placed in the packaged folder is part of
    the default a site ships; copying only lmi.json and settings.json leaves it
    inside site-packages, where `lmi config switch` never looks and the next
    `pip install --upgrade` replaces it.
    """
    _, say = recorder
    landed = defaults.adopt(defaults.CONFIG, say)
    got = set(p.name for p in landed.parent.iterdir() if p.is_file())
    assert got == packaged_names()


def test_the_statusline_script_is_adopted_byte_for_byte(home, recorder):
    """It is somebody's script. Normalising it is lmi editing a file it was
    only asked to move - the same rule as installing it into ~/.claude."""
    _, say = recorder
    landed = defaults.adopt(defaults.CONFIG, say)
    assert (landed.parent / statusline.NAME).read_bytes() == \
        (defaults.DIR / statusline.NAME).read_bytes()


def test_existing_files_are_backed_up_before_being_overwritten(home, recorder):
    """MANDATORY. The copy is the only surviving version of what was there.

    adopt runs when discovery found no config *file*, which does not mean the
    folder is empty: a ~/.lmi holding only a settings.json, or only switch
    files, or last month's leftovers, still falls through to the packaged
    default and is copied into. Overwriting those without a backup destroys
    work the operator cannot get back, at exit 0.
    """
    folder = home / ".lmi"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text('{"mine": true}', encoding="utf-8")
    (folder / "settings_switch_mine.json").write_text('{"model": "opus"}',
                                                      encoding="utf-8")

    _, say = recorder
    defaults.adopt(defaults.CONFIG, say)

    backups = [p for p in folder.iterdir()
               if p.is_dir() and p.name.startswith("backup_")]
    assert len(backups) == 1, "one backup folder per adoption"
    saved = set(p.name for p in backups[0].iterdir())
    assert saved == {"settings.json", "settings_switch_mine.json"}
    assert json.loads((backups[0] / "settings.json").read_text(
        encoding="utf-8")) == {"mine": True}


def test_the_backup_is_announced(home, recorder):
    """A file moved without being mentioned is a file the operator loses.

    Asserted against the real folder name - a timestamp - and a phrase with a
    capital and a space in it. A bare `"backup_" in output` passes for the
    wrong reason: pytest names its tmp directory after the test, so the paths
    this command prints contain the test's own name.
    """
    folder = home / ".lmi"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text("{}", encoding="utf-8")
    lines, say = recorder
    defaults.adopt(defaults.CONFIG, say)

    made = [p for p in folder.iterdir()
            if p.is_dir() and p.name.startswith("backup_")]
    assert len(made) == 1
    assert made[0].name in said(lines)
    assert "Backed up" in said(lines)


def test_an_earlier_backup_is_not_backed_up_again(home, recorder):
    """MANDATORY-adjacent: the backup folder lives INSIDE ~/.lmi.

    Copying it into the next backup nests every generation inside the one after
    it - the folder doubles on each adoption and the oldest copy sinks deeper
    each time.
    """
    folder = home / ".lmi"
    (folder / "backup_20200101-000000").mkdir(parents=True)
    (folder / "backup_20200101-000000" / "settings.json").write_text(
        "{}", encoding="utf-8")
    (folder / "settings.json").write_text("{}", encoding="utf-8")

    _, say = recorder
    defaults.adopt(defaults.CONFIG, say)

    fresh = [p for p in folder.iterdir()
             if p.is_dir() and p.name.startswith("backup_")
             and p.name != "backup_20200101-000000"]
    assert len(fresh) == 1
    assert not any(p.is_dir() for p in fresh[0].iterdir()), \
        "the previous backup must not be copied into the new one"


def test_no_backup_folder_appears_when_there_was_nothing_to_save(home, recorder):
    """A fresh machine must not grow an empty backup_ folder."""
    _, say = recorder
    landed = defaults.adopt(defaults.CONFIG, say)
    assert not any(p.name.startswith("backup_")
                   for p in landed.parent.iterdir())


def test_a_failed_backup_stops_the_adoption(home, recorder, monkeypatch):
    """Fatal, like jsonfile.backup (item 31). Copying over a file we could not
    preserve is not worth the risk, and the packaged default is recoverable by
    simply running the command again."""
    folder = home / ".lmi"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text('{"mine": true}', encoding="utf-8")

    def refuse(*a, **kw):
        raise OSError("no room")

    monkeypatch.setattr(defaults.shutil, "copy2", refuse)
    _, say = recorder
    with pytest.raises(LmiError) as exc:
        defaults.adopt(defaults.CONFIG, say)
    assert exc.value.code == EXIT_CONFIG_WRITE
    assert json.loads((folder / "settings.json").read_text(
        encoding="utf-8")) == {"mine": True}, "the original is untouched"
