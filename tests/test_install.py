"""Unit tests for install.py — pipeline orchestration.

Tests verify that:
  - Each step function returns True/False correctly
  - main() returns the right exit code per step
  - --skip-* flags bypass the corresponding step
"""

import sys
from collections import namedtuple
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import install as inst


# Use namedtuple (NOT a plain class) so it supports the comparison
# protocols Python 3.10+ expects on sys.version_info.
FakeVersion = namedtuple("FakeVersion", ["major", "minor", "micro", "releaselevel", "serial"])


# ---------- step functions ----------

def test_step_check_python_passes(monkeypatch):
    monkeypatch.setattr(inst.sys, "version_info", FakeVersion(3, 11, 4, "final", 0))
    assert inst.step_check_python() is True


def test_step_check_python_fails_below_3_10(monkeypatch):
    monkeypatch.setattr(inst.sys, "version_info", FakeVersion(3, 9, 0, "final", 0))
    assert inst.step_check_python() is False


def test_step_install_deps_ok(monkeypatch):
    class FakeCompleted:
        returncode = 0
    monkeypatch.setattr(inst.subprocess, "run", lambda *a, **kw: FakeCompleted())
    assert inst.step_install_deps(non_interactive=False, upgrade=False) is True


def test_step_install_deps_fail(monkeypatch):
    class FakeCompleted:
        returncode = 1
    monkeypatch.setattr(inst.subprocess, "run", lambda *a, **kw: FakeCompleted())
    assert inst.step_install_deps(non_interactive=False, upgrade=False) is False


def test_step_bootstrap_skips_when_credentials_exist(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "credentials.json").write_text("{}")
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    monkeypatch.setattr(inst, "HOME", home)
    assert inst.step_bootstrap(non_interactive=True) is True


def test_step_register_schedule_skipped():
    assert inst.step_register_schedule(skip=True, non_interactive=True) is True


# ---------- main() ----------

def test_main_returns_2_on_old_python(monkeypatch, capsys):
    monkeypatch.setattr(inst.sys, "version_info", FakeVersion(3, 9, 0, "final", 0))
    rc = inst.main([])
    assert rc == 2


def test_main_returns_0_with_skip_all(monkeypatch, capsys):
    """With all steps short-circuited, main returns 0."""
    monkeypatch.setattr(inst.sys, "version_info", FakeVersion(3, 11, 4, "final", 0))

    class FakeCompleted:
        returncode = 0
    monkeypatch.setattr(inst.subprocess, "run", lambda *a, **kw: FakeCompleted())
    rc = inst.main(["--skip-schedule", "--skip-doctor"])
    assert rc == 0
