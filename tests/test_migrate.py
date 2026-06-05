"""Unit tests for migrate.py — schema migration engine.

Tests verify:
  - detect_version returns 0 when schemaVersion is missing
  - pending_migrations is empty for current version
  - apply_all is idempotent (running twice has no effect)
  - main() handles missing file gracefully (rc=0, nothing to do)
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migrate as mig


def test_detect_version_zero_when_missing():
    assert mig.detect_version({}) == 0
    assert mig.detect_version({"schemaVersion": 3}) == 3


def test_pending_migrations_empty_at_current():
    state = {"schemaVersion": mig.CURRENT_VERSION}
    assert mig.pending_migrations(state) == []


def test_pending_migrations_finds_lower_versions():
    state = {"schemaVersion": 0}
    pending = mig.pending_migrations(state)
    assert (0, 1, mig.MIGRATIONS[0][2]) in [(frm, to, fn) for frm, to, fn in pending]


def test_apply_all_idempotent():
    state = {"schemaVersion": 0}
    applied1 = mig.apply_all(state, dry_run=False)
    after_version = mig.detect_version(state)
    applied2 = mig.apply_all(state, dry_run=False)
    # Second run applies nothing
    assert applied1 and not applied2
    assert after_version == mig.CURRENT_VERSION


def test_apply_all_dry_run_does_not_mutate():
    state = {"schemaVersion": 0}
    snapshot = dict(state)
    mig.apply_all(state, dry_run=True)
    # state unchanged
    assert state == snapshot


def test_migration_adds_schema_version():
    state = {"trustLevel": "new"}
    mig.apply_all(state, dry_run=False)
    assert state["schemaVersion"] == mig.CURRENT_VERSION


def test_main_missing_file(tmp_path, monkeypatch, capsys):
    """No engagement_state.json → exit 0 (not an error)."""
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(mig, "HOME", tmp_path)
    monkeypatch.setattr(mig, "ENGAGEMENT", tmp_path / "engagement_state.json")
    rc = mig.main([])
    assert rc == 0


def test_main_nothing_to_migrate(tmp_path, monkeypatch, capsys):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "engagement_state.json").write_text(json.dumps({
        "schemaVersion": mig.CURRENT_VERSION, "trustLevel": "new"
    }))
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    monkeypatch.setattr(mig, "HOME", home)
    monkeypatch.setattr(mig, "ENGAGEMENT", home / "engagement_state.json")
    rc = mig.main([])
    assert rc == 0
    captured = capsys.readouterr()
    assert "nothing to do" in captured.out


def test_main_migrates_and_updates_file(tmp_path, monkeypatch, capsys):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "engagement_state.json").write_text(json.dumps({
        "trustLevel": "new"
    }))
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    monkeypatch.setattr(mig, "HOME", home)
    monkeypatch.setattr(mig, "ENGAGEMENT", home / "engagement_state.json")
    rc = mig.main([])
    assert rc == 0
    # File should now have schemaVersion
    after = json.loads((home / "engagement_state.json").read_text())
    assert after["schemaVersion"] == mig.CURRENT_VERSION


def test_main_dry_run_does_not_write(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    p = home / "engagement_state.json"
    p.write_text(json.dumps({"trustLevel": "new"}))
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    monkeypatch.setattr(mig, "HOME", home)
    monkeypatch.setattr(mig, "ENGAGEMENT", p)
    before = p.read_text()
    mig.main(["--dry-run"])
    after = p.read_text()
    assert before == after


def test_main_rejects_future_state_version(tmp_path, monkeypatch, capsys):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    p = home / "engagement_state.json"
    p.write_text(json.dumps({"schemaVersion": mig.CURRENT_VERSION + 5}))
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    monkeypatch.setattr(mig, "HOME", home)
    monkeypatch.setattr(mig, "ENGAGEMENT", p)
    rc = mig.main([])
    assert rc == 2
