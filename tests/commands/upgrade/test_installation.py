"""Which installation `lmi upgrade` is running from, and what it refuses.

A wrong answer here is silent in this project's sense: pip reports success, the
command still runs, and it is either the old code or a second copy that nothing
on PATH reaches.
"""

import os
from pathlib import Path

import pytest

from lmi.commands.upgrade import installation
from lmi.core.errors import LmiError


@pytest.fixture
def venv(tmp_path, monkeypatch):
    """A convincing virtual environment with lmi installed into it."""
    prefix = tmp_path / "venv"
    scripts = prefix / ("Scripts" if os.name == "nt" else "bin")
    site_packages = prefix / "site-packages"
    (site_packages / "lmi").mkdir(parents=True)
    scripts.mkdir(parents=True)
    (scripts / ("lmi.exe" if os.name == "nt" else "lmi")).write_text("x")

    monkeypatch.setattr(installation, "_editable", lambda: False)
    monkeypatch.setattr(installation, "_prefix", lambda: prefix)
    monkeypatch.setattr(installation, "_base_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_package_dir", lambda: site_packages / "lmi")
    monkeypatch.setattr(installation, "_executable", lambda: scripts / "python")
    monkeypatch.setattr(installation, "_scripts_dir", lambda: scripts)
    monkeypatch.setattr(installation, "_user_site_dir", lambda: tmp_path / "usersite")
    monkeypatch.setattr(installation, "_has_pip", lambda python: True)
    return prefix


def test_a_venv_install_is_upgraded_with_its_own_python(venv):
    inst = installation.detect()
    assert inst.kind == installation.VENV
    assert inst.user_flag is False
    assert inst.pip_prefix[1:] == ["-m", "pip"]
    assert Path(inst.pip_prefix[0]).name.startswith("python")
    assert inst.script.name.startswith("lmi")
    assert inst.where == venv


def test_a_venv_without_pip_borrows_the_base_python(venv, monkeypatch, tmp_path):
    """Debian and Ubuntu force `venv --without-pip`; install-linux.sh has the
    same fallback and this must not be the one place that forgets it."""
    monkeypatch.setattr(installation, "_has_pip", lambda python: False)
    monkeypatch.setattr(installation, "_base_python", lambda: tmp_path / "usr" / "bin" / "python3")

    inst = installation.detect()
    assert inst.pip_prefix[1:3] == ["-m", "pip"]
    assert inst.pip_prefix[3] == "--python"
    assert inst.pip_prefix[4].endswith("python")


def test_no_pip_anywhere_is_a_usage_error_naming_the_package(venv, monkeypatch):
    monkeypatch.setattr(installation, "_has_pip", lambda python: False)
    monkeypatch.setattr(installation, "_base_python", lambda: None)
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert "python3-venv" in str(exc.value)


def test_an_editable_checkout_is_refused(venv, monkeypatch):
    """MANDATORY. Silent: a released wheel installed over a developer's working
    tree looks exactly like a successful upgrade, and their uncommitted work is
    gone. Checked before the venv rule because a dev checkout is usually inside
    one, so the venv rule would otherwise claim it."""
    monkeypatch.setattr(installation, "_editable", lambda: True)
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert "editable" in str(exc.value)
    assert "pip install -e" in str(exc.value)


def test_a_pipx_installation_is_refused(venv, monkeypatch, tmp_path):
    """MANDATORY. Silent: pipx's metadata goes on describing a version that is
    no longer installed, and `pipx list` reports the old one forever."""
    (tmp_path / "venv" / "pipx_metadata.json").write_text("{}")
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert "pipx upgrade lmi" in str(exc.value)


def test_a_user_site_install_gets_the_user_flag(tmp_path, monkeypatch):
    usersite = tmp_path / "usersite"
    (usersite / "lmi").mkdir(parents=True)
    scripts = tmp_path / "userscripts"
    scripts.mkdir()

    monkeypatch.setattr(installation, "_editable", lambda: False)
    monkeypatch.setattr(installation, "_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_base_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_package_dir", lambda: usersite / "lmi")
    monkeypatch.setattr(installation, "_executable", lambda: tmp_path / "usr" / "python")
    monkeypatch.setattr(installation, "_user_site_dir", lambda: usersite)
    monkeypatch.setattr(installation, "_user_scripts_dir", lambda: scripts)

    inst = installation.detect()
    assert inst.kind == installation.USER_SITE
    assert inst.user_flag is True
    assert inst.script.parent == scripts


def test_a_system_install_is_refused(tmp_path, monkeypatch):
    """Neither a venv nor user site: a system site-packages, a checkout on
    PYTHONPATH, something unpacked by hand. Guessing --user here writes a
    second copy that the PATH entry never reaches, and reports success."""
    monkeypatch.setattr(installation, "_editable", lambda: False)
    monkeypatch.setattr(installation, "_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_base_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_package_dir", lambda: tmp_path / "src" / "lmi")
    monkeypatch.setattr(installation, "_executable", lambda: tmp_path / "usr" / "python")
    monkeypatch.setattr(installation, "_user_site_dir", lambda: tmp_path / "usersite")

    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert str(tmp_path / "src" / "lmi") in str(exc.value)


def test_a_venv_whose_lmi_is_somewhere_else_is_refused(venv, monkeypatch, tmp_path):
    """Inside a venv, but lmi is being imported from a checkout on PYTHONPATH.
    Upgrading the venv would leave the checkout still shadowing it."""
    monkeypatch.setattr(installation, "_package_dir", lambda: tmp_path / "src" / "lmi")
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2


def test_the_console_script_is_named_per_platform(monkeypatch):
    monkeypatch.setattr(installation, "_on_windows", lambda: True)
    assert installation._script_name() == "lmi.exe"

    monkeypatch.setattr(installation, "_on_windows", lambda: False)
    assert installation._script_name() == "lmi"


def test_user_scripts_dir_falls_back_to_the_39_scheme_names(monkeypatch):
    """sysconfig.get_preferred_scheme is 3.10+; on the 3.9 floor this fallback
    is the path every user-site install actually takes, not a corner case."""
    monkeypatch.delattr(installation.sysconfig, "get_preferred_scheme", raising=False)

    calls = []
    monkeypatch.setattr(
        installation.sysconfig, "get_path",
        lambda name, scheme=None: calls.append((name, scheme)) or "/x",
    )

    monkeypatch.setattr(installation, "_on_windows", lambda: True)
    installation._user_scripts_dir()
    assert calls[-1] == ("scripts", "nt_user")

    monkeypatch.setattr(installation, "_on_windows", lambda: False)
    installation._user_scripts_dir()
    assert calls[-1] == ("scripts", "posix_user")
