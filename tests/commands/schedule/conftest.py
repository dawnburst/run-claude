"""Shared helpers for the `lmi schedule` tests.

`Config` has ten fields and several test modules need one; building it in each
of them meant two copies that had already drifted apart.
"""

import pytest

from lmi.commands.schedule import paths
from lmi.commands.schedule.config import Config

# A fixed run timestamp, so a resolved log file name is predictable.
TS = "20260803-101500"


@pytest.fixture
def on_windows(monkeypatch):
    """Take the Windows branch of paths.py.

    paths._on_windows is patched rather than os.name, which cannot be patched:
    pathlib picks its concrete class from os.name at instantiation, so forcing
    it to "nt" here makes every Path() raise NotImplementedError.
    """
    monkeypatch.setattr(paths, "_on_windows", lambda: True)


@pytest.fixture
def deny_touch(monkeypatch):
    """Make the writability probe fail the way C:\\Windows does."""
    def _throw(self, *a, **k):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(paths.Path, "touch", _throw)


@pytest.fixture
def make_cfg():
    """Return a factory: make_cfg(tmp_path, **overrides) -> Config."""

    def _make(work_dir, **overrides):
        fields = dict(
            prompt_text="write a haiku",
            prompt_file=None,
            at=None,
            interval_min=0,
            max_runs=1,
            work_dir=work_dir,
            user_flags=[],
            log_arg=None,
            state_arg=None,
            resume=False,
        )
        fields.update(overrides)
        return Config(**fields)

    return _make
