"""Unit tests for doctor.py — environment health checks.

Run: pytest tests/test_doctor.py -v

Tests do NOT call any platform API. They test the pure logic of each
check function and the main() entrypoint.
"""

import json
import sys
from pathlib import Path

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import doctor as doc


# ---------- individual checks ----------

def test_check_python_ok():
    r = doc.check_python()
    assert r["status"] == "ok"
    assert r["name"] == "python_version"


def test_check_dependencies_ok_when_all_installed():
    r = doc.check_dependencies()
    assert r["status"] in ("ok", "warn")
    assert r["name"] == "dependencies"


def test_check_agent_home_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(tmp_path / "does-not-exist"))
    r = doc.check_agent_home()
    assert r["status"] == "fail"
    assert "does not exist" in r["message"]


def test_check_agent_home_writable(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_agent_home()
    assert r["status"] == "ok"


def test_check_credentials_missing(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_credentials()
    assert r["status"] == "fail"
    assert "credentials.json not found" in r["message"]


def test_check_credentials_ok(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "credentials.json").write_text(json.dumps({
        "apiKey": "aclk_2fa9c8ec7529e997_real_key_xxxxxxxxxxxxx",
        "keyPrefix": "aclk_2fa9c8ec7529e997",
        "userId": 19,
        "username": "alice",
    }))
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_credentials()
    assert r["status"] == "ok"
    assert "alice" in r["message"]


def test_check_credentials_invalid_json(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "credentials.json").write_text("{not json")
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_credentials()
    assert r["status"] == "fail"
    assert "invalid JSON" in r["message"]


def test_check_state_files_all_ok(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    for fn in ("engagement_state.json", "interaction_state.json", "policy.json", "persona.json"):
        (home / fn).write_text("{}")
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_state_files()
    assert r["status"] == "ok"


def test_check_state_files_missing(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "engagement_state.json").write_text("{}")
    # the other 3 missing
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_state_files()
    assert r["status"] == "fail"


def test_check_state_files_invalid_json(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "engagement_state.json").write_text("not json")
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_state_files()
    assert r["status"] == "fail"
    assert "invalid JSON" in r["message"]


def test_check_trust_missing(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_trust()
    assert r["status"] == "skip"


def test_check_trust_ok(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "engagement_state.json").write_text(json.dumps({
        "trustLevel": "established", "trustScore": 3.2,
    }))
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_trust()
    assert r["status"] == "ok"
    assert "established" in r["message"]


def test_check_trust_unknown_level(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    (home / "engagement_state.json").write_text(json.dumps({"trustLevel": "omega"}))
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_trust()
    assert r["status"] == "fail"


def test_check_recent_run_skip(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_recent_run()
    assert r["status"] == "skip"


def test_check_recent_run_ok(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    run = home / "runs" / "2026-06-04"
    run.mkdir(parents=True)
    (run / "evidence_pack.json").write_text("[]")
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_recent_run()
    assert r["status"] == "ok"
    assert "2026-06-04" in r["message"]


def test_check_recent_run_warn_no_evidence(tmp_path, monkeypatch):
    home = tmp_path / "arxiclaw"
    home.mkdir()
    run = home / "runs" / "2026-06-04"
    run.mkdir(parents=True)
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    r = doc.check_recent_run()
    assert r["status"] == "warn"


# ---------- main() ----------

def test_main_human_output(capsys):
    """Default: human-readable table."""
    rc = doc.main([])
    captured = capsys.readouterr()
    assert rc in (0, 1)
    assert "arxiclaw doctor" in captured.out


def test_main_json_output(capsys):
    rc = doc.main(["--json"])
    captured = capsys.readouterr()
    assert rc in (0, 1)
    data = json.loads(captured.out)
    assert "checks" in data
    assert "doctor_version" in data
    assert "platform" in data
    assert "home" in data


def test_main_specific_check(capsys):
    """--check python_version should run only one check."""
    rc = doc.main(["--check", "python_version"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "python_version" in captured.out
    assert "credentials" not in captured.out


def test_main_unknown_check_exits_1(capsys):
    rc = doc.main(["--check", "nonexistent"])
    assert rc == 1


def test_main_returns_nonzero_on_failure(capsys, monkeypatch, tmp_path):
    """Force credentials failure to confirm exit code 1."""
    home = tmp_path / "arxiclaw"
    home.mkdir()
    monkeypatch.setenv("ARXICLAW_AGENT_HOME", str(home))
    # patch _home so doctor uses our temp
    monkeypatch.setattr(doc, "_home", lambda: home)
    rc = doc.main(["--check", "credentials"])
    assert rc == 1
