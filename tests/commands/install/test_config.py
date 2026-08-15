"""Discovery and validation of the lmi install config file."""

import json

import pytest

from lmi.commands.install import config, defaults
from lmi.core.errors import LmiError


class Args:
    """argparse.Namespace stand-in: only the two attributes build_config reads."""

    def __init__(self, config=None, target="claude"):
        self.config = config
        self.target = target


TEMPLATE = {"env": {"ANTHROPIC_BASE_URL": "https://gw.corp/"}}


def write(path, doc, template=TEMPLATE):
    """An lmi.json, plus the settings.json every valid config folder now has.

    build_config loads the template as part of the Config, so a config file with
    no neighbour is exit 2 - which is its own test below, not a trap for the
    twenty tests here that are about something else.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    if template is not None:
        with open(str(path.parent / "settings.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(template, fh)
    return path


MINIMAL = {"claude": {"registry": "https://artifactory.corp.local/api/npm/npm/"}}

# The working-directory default: ./config/lmi.json, not ./lmi.json.
CWD = ("config", "lmi.json")


@pytest.fixture
def no_packaged_config(tmp_path, monkeypatch):
    """Hide the config folder packaged with lmi.

    It always exists in a working install, so this is the only way left to
    reach "no config file found" - which still has to be right, because a
    broken install is exactly when it gets read.
    """
    monkeypatch.setattr(defaults, "CONFIG",
                        tmp_path / "absent" / "lmi.json")


@pytest.fixture
def bare_search(tmp_path, monkeypatch):
    """An empty search: no $LMI_CONFIG, no ./config/lmi.json, no ~/.lmi."""
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "work").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path / "work")


def test_explicit_config_wins(tmp_path, monkeypatch):
    chosen = write(tmp_path / "chosen.json", MINIMAL)
    write(tmp_path.joinpath(*CWD), {"claude": {"registry": "https://wrong/"}})
    monkeypatch.chdir(tmp_path)
    cfg = config.build_config(Args(config=str(chosen)))
    assert cfg.registry == "https://artifactory.corp.local/api/npm/npm/"
    assert cfg.source == chosen


def test_missing_explicit_config_does_not_fall_through(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: provisioning against the wrong registry.

    A --config the user named and that does not exist must be an error, never
    a quiet fall-through to ./config/lmi.json - which would install from a
    different registry than the one asked for and report success.
    """
    write(tmp_path.joinpath(*CWD), MINIMAL)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(tmp_path / "nope.json")))
    assert exc.value.code == 2


def test_env_var_beats_cwd(tmp_path, monkeypatch):
    from_env = write(tmp_path / "env.json", MINIMAL)
    write(tmp_path.joinpath(*CWD), {"claude": {"registry": "https://wrong/"}})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LMI_CONFIG", str(from_env))
    assert config.build_config(Args()).source == from_env


def test_cwd_beats_home(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    write(tmp_path / "home" / ".lmi" / "config.json",
          {"claude": {"registry": "https://wrong/"}})
    here = write(tmp_path.joinpath("work", *CWD), MINIMAL)
    monkeypatch.chdir(tmp_path / "work")
    assert config.build_config(Args()).source == here


def test_a_config_left_at_the_old_path_is_refused_not_skipped(
        tmp_path, monkeypatch):
    """MANDATORY. Silent failure: provisioning against the wrong registry.

    The working-directory default moved from ./lmi.json into ./config/. A file
    left at the old path must not be passed over in silence, because the next
    candidate is ~/.lmi/config.json - a different registry - and installing
    from that while an lmi.json sits in view in the working directory reports
    success having provisioned the machine against the wrong source.
    """
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    write(tmp_path / "home" / ".lmi" / "config.json",
          {"claude": {"registry": "https://wrong/"}})
    (tmp_path / "work").mkdir()
    legacy = write(tmp_path / "work" / "lmi.json", MINIMAL)
    monkeypatch.chdir(tmp_path / "work")

    with pytest.raises(LmiError) as exc:
        config.build_config(Args())
    assert exc.value.code == 2
    message = str(exc.value)
    assert str(legacy) in message         # which file it means
    assert "config" in message            # and where it belongs now


def test_the_old_path_does_not_override_an_explicit_config(tmp_path, monkeypatch):
    """The refusal is for the search, not for a file the user named.

    --config and $LMI_CONFIG are answers to the question the refusal asks, so
    neither may trip over it - including --config pointing at the old path
    itself, which is the escape hatch the message offers.
    """
    legacy = write(tmp_path / "lmi.json", MINIMAL)
    monkeypatch.chdir(tmp_path)
    assert config.build_config(Args(config=str(legacy))).source == legacy
    monkeypatch.setenv("LMI_CONFIG", str(legacy))
    assert config.build_config(Args()).source == legacy


def test_home_beats_the_packaged_default(tmp_path, bare_search):
    fallback = write(tmp_path / "home" / ".lmi" / "config.json", MINIMAL)
    assert config.build_config(Args()).source == fallback


def test_the_packaged_default_is_the_last_resort(bare_search):
    """`pip install lmi` is the whole installation: no config file to write.

    Nothing in the search exists, and the command still gets a registry and a
    settings template - from the folder shipped inside the package. The
    template comes along for free: template.load reads the neighbour of
    whatever discovery resolved, and the packaged folder is laid out like any
    other config folder for exactly that reason.
    """
    cfg = config.build_config(Args())
    assert cfg.source == defaults.CONFIG
    assert cfg.registry
    assert cfg.settings_source == defaults.TEMPLATE
    assert cfg.settings["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"


def test_the_packaged_default_carries_no_statusline(bare_search):
    """MANDATORY. Item 32's two warnings must stay quiet on the packaged pair.

    No statusline.js ships inside the package - statusline.py says why - so the
    packaged template must not declare a `statusLine` either. Declaring one
    would install a command pointing at a file that is never written, on every
    machine that falls through to the default, and say so in a [WARN] nobody
    can act on.
    """
    from lmi.commands.install import statusline
    cfg = config.build_config(Args())
    assert cfg.statusline is None
    assert not statusline.declares(cfg.settings)


def test_the_packaged_default_does_not_mask_the_old_path(tmp_path, bare_search):
    """MANDATORY. Silent failure: provisioning against the wrong registry.

    A last-resort default changed what falling through *reaches*: an lmi.json
    left at the pre-move path used to fall through to ~/.lmi and would now
    reach the packaged registry instead. Either way it is a machine provisioned
    from a source the operator can see in the working directory and did not
    get. The refusal fires first, as before.
    """
    legacy = write(tmp_path / "work" / "lmi.json", MINIMAL)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args())
    assert exc.value.code == 2
    assert str(legacy) in str(exc.value)


def test_no_config_anywhere_is_usage_with_an_example(
        bare_search, no_packaged_config):
    with pytest.raises(LmiError) as exc:
        config.build_config(Args())
    assert exc.value.code == 2
    message = str(exc.value)
    assert "registry" in message          # the paste-ready example
    assert "lmi.json" in message          # the paths searched


@pytest.mark.parametrize("doc", [
    [1, 2, 3],                                        # top level not an object
    {},                                               # no "claude"
    {"claude": "nope"},                               # "claude" not an object
    {"claude": {}},                                   # no registry
    {"claude": {"registry": ""}},                     # empty registry
    {"claude": {"registry": 5}},                      # registry not a string
])
def test_rejected_shapes_are_usage_errors(tmp_path, monkeypatch, doc):
    path = write(tmp_path / "lmi.json", doc)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2


def test_invalid_json_names_the_file_and_the_position(tmp_path, monkeypatch):
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"claude": }')
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "lmi.json" in str(exc.value)


def test_a_utf8_bom_is_tolerated(tmp_path):
    """Notepad and PowerShell's Set-Content both write one; json.loads rejects it."""
    path = tmp_path / "lmi.json"
    with open(str(path), "wb") as fh:
        fh.write(b"\xef\xbb\xbf" + json.dumps(MINIMAL).encode("utf-8"))
    write(tmp_path / "other.json", MINIMAL)     # for the settings.json beside it
    assert config.build_config(Args(config=str(path))).registry.startswith("https://")


# --- the settings template ------------------------------------------------

def test_the_template_is_loaded_as_part_of_the_config(tmp_path):
    path = write(tmp_path / "lmi.json", MINIMAL)
    cfg = config.build_config(Args(config=str(path)))
    assert cfg.settings == TEMPLATE
    assert cfg.settings_source == tmp_path / "settings.json"


def test_the_template_is_taken_from_the_config_file_that_won(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: a machine configured from another site.

    --config names one site's lmi.json. Pairing it with the working directory's
    template instead would install a different site's gateway and marketplaces
    and report success.
    """
    chosen = write(tmp_path / "site" / "lmi.json", MINIMAL,
                   template={"env": {"ANTHROPIC_BASE_URL": "https://right/"}})
    write(tmp_path.joinpath(*CWD), MINIMAL,
          template={"env": {"ANTHROPIC_BASE_URL": "https://WRONG/"}})
    monkeypatch.chdir(tmp_path)
    cfg = config.build_config(Args(config=str(chosen)))
    assert cfg.settings["env"]["ANTHROPIC_BASE_URL"] == "https://right/"


def test_a_config_folder_with_no_template_is_a_usage_error(tmp_path):
    """MANDATORY. Silent failure: a binary with no configuration at all."""
    path = write(tmp_path / "lmi.json", MINIMAL, template=None)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "settings.json" in str(exc.value)


def test_a_broken_template_fails_the_whole_config(tmp_path):
    """Never a partial Config: every config error surfaces before npm runs."""
    path = write(tmp_path / "lmi.json", MINIMAL,
                 template={"env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": 64000}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "string" in str(exc.value)


def test_cafile_must_exist(tmp_path):
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "cafile": str(tmp_path / "absent.pem")}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2


def test_cafile_that_exists_is_resolved(tmp_path):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "cafile": str(pem)}})
    assert config.build_config(Args(config=str(path))).cafile == pem


def test_tilde_user_that_cannot_resolve_is_usage_not_a_traceback():
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config="~nosuchuser-lmi/lmi.json"))
    assert exc.value.code == 2


def test_the_claude_section_carries_nothing_but_registry_and_cafile(tmp_path):
    """The keys that duplicated the template are gone, and stay gone.

    `marketplaces` and `env` were copied verbatim into settings.json, which is
    two spellings for one thing and the reason the two drifted. Re-adding either
    here would give a site somewhere to write a setting that the template then
    silently overwrites.
    """
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "marketplaces": {"corp": {}},
        "env": {"A": "1"}}})
    cfg = config.build_config(Args(config=str(path)))
    assert not hasattr(cfg, "marketplaces")
    assert not hasattr(cfg, "env")
    assert "marketplaces" not in config.EXAMPLE
    assert '"env"' not in config.EXAMPLE
