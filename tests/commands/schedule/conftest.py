"""Shared helpers for the `lmi schedule` tests.

`Config` has ten fields and several test modules need one; building it in each
of them meant two copies that had already drifted apart.
"""

import pytest

from lmi.commands.schedule.config import Config


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
