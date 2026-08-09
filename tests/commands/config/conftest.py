"""Fixtures for the `lmi config` suite."""

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME, so no test can touch the developer's real ~/.claude."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    return h
