"""The config folder packaged inside lmi, and adopting it into ~/.lmi."""

import json

import pytest

from lmi.commands.install import config, defaults, statusline, template
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
    assert not statusline.declares(doc), \
        "no statusline.js ships in the package, so nothing may declare one"


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
