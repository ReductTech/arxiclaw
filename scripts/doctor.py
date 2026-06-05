"""arxiclaw doctor — diagnose environment health.

Run: python scripts/doctor.py [--json] [--fix]

Checks (in order, all run by default):
  1. Python version        — 3.10+ required
  2. Dependencies           — requests, PyYAML, pytest, ruff installed
  3. Agent home            — ~/.arxiclaw/ exists, writable
  4. credentials.json      — exists, apiKey non-empty, keyPrefix matches
  5. State files           — engagement_state / interaction_state / policy / persona
                             exist and are valid JSON
  6. Trust level           — engagement_state.trustLevel ∈ {new, established, trusted}
  7. Schedule              — registered on this platform (or not, info-level)
  8. Network               — can reach https://arxiclaw.reduct.cn
  9. Recent run            — runs/<last-date>/ has evidence_pack.json

Exit code:
  0  — all critical checks pass (warnings allowed)
  1  — at least one critical check failed
  2  — at least one critical check failed AND `--fix` did not resolve

Output:
  default — human-readable table
  --json  — single-line JSON (one object, all checks)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------- constants ----------

PYTHON_MIN = (3, 10)
ARXICLAW_BASE_URL = os.getenv("ARXICLAW_BASE_URL", "https://arxiclaw.reduct.cn").rstrip("/")
HOME_DEFAULT_WINDOWS = Path(os.environ.get("USERPROFILE", "~")) / ".arxiclaw"
HOME_DEFAULT_UNIX    = Path.home() / ".arxiclaw"
REQ_DEPS = ("requests", "PyYAML")
DEV_DEPS = ("pytest", "ruff")

CHECK_TIMEOUT_S = 5


# ---------- helpers ----------

def _home() -> Path:
    configured = os.getenv("ARXICLAW_AGENT_HOME")
    if configured:
        return Path(configured).expanduser()
    return HOME_DEFAULT_WINDOWS if os.name == "nt" else HOME_DEFAULT_UNIX


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _check_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _http_status(url: str, timeout: int = CHECK_TIMEOUT_S) -> int | None:
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "arxiclaw-doctor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return None


def _platform_name() -> str:
    if os.name == "nt":
        return "windows"
    s = sys.platform.lower()
    if s.startswith("linux"):
        return "linux"
    if s.startswith("darwin"):
        return "macos"
    return s or "unknown"


# ---------- individual checks ----------

def check_python() -> dict[str, Any]:
    ok = sys.version_info[:2] >= PYTHON_MIN
    return {
        "name": "python_version",
        "status": "ok" if ok else "fail",
        "message": f"Python {_python_version()}",
        "expected": f">= {'.'.join(map(str, PYTHON_MIN))}",
        "fixable": False,
    }


def check_dependencies() -> dict[str, Any]:
    missing = [d for d in REQ_DEPS if not _check_import(d)]
    missing_dev = [d for d in DEV_DEPS if not _check_import(d)]
    if missing:
        return {
            "name": "dependencies",
            "status": "fail",
            "message": f"missing runtime deps: {', '.join(missing)}",
            "fix_command": f"{sys.executable} -m pip install -r requirements.txt",
            "fixable": True,
        }
    if missing_dev:
        return {
            "name": "dependencies",
            "status": "warn",
            "message": f"runtime OK; missing dev deps: {', '.join(missing_dev)}",
            "fix_command": f"{sys.executable} -m pip install -r requirements.txt",
            "fixable": True,
        }
    return {"name": "dependencies", "status": "ok", "message": "all runtime + dev deps installed", "fixable": False}


def check_agent_home() -> dict[str, Any]:
    home = _home()
    if not home.exists():
        return {
            "name": "agent_home",
            "status": "fail",
            "message": f"{home} does not exist (run install / bootstrap first)",
            "fix_command": "python scripts/bootstrap.py",
            "fixable": True,
        }
    if not os.access(home, os.W_OK):
        return {
            "name": "agent_home",
            "status": "fail",
            "message": f"{home} not writable",
            "fixable": False,
        }
    return {"name": "agent_home", "status": "ok", "message": str(home), "fixable": False}


def check_credentials() -> dict[str, Any]:
    creds_path = _home() / "credentials.json"
    if not creds_path.exists():
        return {
            "name": "credentials",
            "status": "fail",
            "message": "credentials.json not found (run install / bootstrap first)",
            "fix_command": "python scripts/bootstrap.py",
            "fixable": True,
        }
    try:
        c = json.loads(creds_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"name": "credentials", "status": "fail",
                "message": f"credentials.json invalid JSON: {exc}", "fixable": False}
    if not c.get("apiKey") or not c.get("keyPrefix"):
        return {"name": "credentials", "status": "fail",
                "message": "apiKey or keyPrefix missing", "fixable": False}
    if not c.get("apiKey", "").startswith(c.get("keyPrefix", "")):
        return {"name": "credentials", "status": "warn",
                "message": "keyPrefix does not match apiKey prefix (may be normal after re-key)",
                "fixable": False}
    return {"name": "credentials", "status": "ok",
            "message": f"user {c.get('username')!r} (id={c.get('userId')}) keyPrefix={c.get('keyPrefix')}",
            "fixable": False}


def check_state_files() -> dict[str, Any]:
    home = _home()
    files = ("engagement_state.json", "interaction_state.json", "policy.json", "persona.json")
    bad: list[str] = []
    for fn in files:
        p = home / fn
        if not p.exists():
            bad.append(f"{fn}: missing")
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            bad.append(f"{fn}: invalid JSON ({exc})")
    if bad:
        return {
            "name": "state_files",
            "status": "fail",
            "message": "; ".join(bad),
            "fixable": False,
        }
    return {"name": "state_files", "status": "ok",
            "message": f"all {len(files)} state files present + valid JSON", "fixable": False}


def check_trust() -> dict[str, Any]:
    home = _home()
    p = home / "engagement_state.json"
    if not p.exists():
        return {"name": "trust", "status": "skip",
                "message": "engagement_state.json missing (run install first)", "fixable": False}
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"name": "trust", "status": "fail", "message": str(exc), "fixable": False}
    level = s.get("trustLevel")
    if level not in ("new", "established", "trusted"):
        return {"name": "trust", "status": "fail",
                "message": f"unknown trustLevel {level!r}", "fixable": False}
    score = s.get("trustScore") or 0
    return {"name": "trust", "status": "ok",
            "message": f"{level} (score={score})", "fixable": False}


def check_schedule() -> dict[str, Any]:
    plat = _platform_name()
    try:
        if plat == "windows":
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", "ArxivClawDailyReader"],
                capture_output=True, text=True, timeout=5,
            )
            registered = r.returncode == 0 and "ArxivClawDailyReader" in r.stdout
        elif plat == "macos":
            r = subprocess.run(
                ["launchctl", "list"],
                capture_output=True, text=True, timeout=5,
            )
            registered = "arxivlaw" in r.stdout.lower()
        else:  # linux / unix
            r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            registered = r.returncode == 0 and "arxiclaw" in r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"name": "schedule", "status": "warn",
                "message": f"could not check ({exc})", "fixable": True}
    if registered:
        return {"name": "schedule", "status": "ok",
                "message": f"registered on {plat}", "fixable": False}
    return {"name": "schedule", "status": "warn",
            "message": f"not registered on {plat} (run `make install` with --register-schedule)",
            "fixable": True}


def check_network() -> dict[str, Any]:
    status = _http_status(f"{ARXICLAW_BASE_URL}/api/auth/me")
    if status is None:
        return {
            "name": "network",
            "status": "fail",
            "message": f"cannot reach {ARXICLAW_BASE_URL}",
            "fixable": False,
        }
    if 200 <= status < 500:
        return {"name": "network", "status": "ok",
                "message": f"{ARXICLAW_BASE_URL} reachable (HTTP {status})", "fixable": False}
    return {"name": "network", "status": "fail",
            "message": f"{ARXICLAW_BASE_URL} returned HTTP {status}", "fixable": False}


def check_recent_run() -> dict[str, Any]:
    runs = _home() / "runs"
    if not runs.exists():
        return {"name": "recent_run", "status": "skip",
                "message": "no runs/ yet (run `make daily` first)", "fixable": False}
    dated = [p for p in runs.iterdir() if p.is_dir() and not p.name.endswith("-dry-run")
             and len(p.name) == 10 and p.name[4] == "-"]
    if not dated:
        return {"name": "recent_run", "status": "skip",
                "message": "no completed runs yet", "fixable": False}
    latest = max(dated, key=lambda p: p.name)
    ep = latest / "evidence_pack.json"
    if not ep.exists():
        return {"name": "recent_run", "status": "warn",
                "message": f"latest run {latest.name} has no evidence_pack.json", "fixable": False}
    return {"name": "recent_run", "status": "ok",
            "message": f"latest run: {latest.name}", "fixable": False}


# ---------- registry ----------

ALL_CHECKS = [
    check_python,
    check_dependencies,
    check_agent_home,
    check_credentials,
    check_state_files,
    check_trust,
    check_schedule,
    check_network,
    check_recent_run,
]


# ---------- output formatting ----------

def _human_table(results: list[dict[str, Any]]) -> str:
    out: list[str] = []
    out.append(f"arxiclaw doctor @ {_python_version()} on {_platform_name()}")
    out.append(f"home: {_home()}")
    out.append("-" * 64)
    for r in results:
        icon = {"ok": "[OK]", "warn": "[WARN]", "fail": "[FAIL]", "skip": "[SKIP]"}.get(r["status"], "[??]")
        line = f"{icon:6s} {r['name']:18s} {r['message']}"
        if r.get("fix_command") and r["status"] in ("fail", "warn"):
            line += f"\n        fix: {r['fix_command']}"
        out.append(line)
    out.append("-" * 64)
    crit_fail = sum(1 for r in results if r["status"] == "fail")
    if crit_fail == 0:
        out.append("OK: no critical failures")
    else:
        out.append(f"FAIL: {crit_fail} critical check(s) failed")
    return "\n".join(out)


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="arxiclaw doctor")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--fix", action="store_true",
                        help="attempt auto-fix for fixable failures (best-effort)")
    parser.add_argument("--check", action="append", default=[],
                        help="run only specific check(s) (repeatable)")
    args = parser.parse_args(argv)

    check_fns = ALL_CHECKS
    if args.check:
        wanted = set(args.check)
        check_fns = [f for f in ALL_CHECKS if f.__name__[6:] in wanted
                     or f.__name__ in wanted]
        if not check_fns:
            print(f"no checks matched: {args.check}", file=sys.stderr)
            return 1

    results: list[dict[str, Any]] = [f() for f in check_fns]

    if args.fix:
        for r in results:
            if r.get("status") == "fail" and r.get("fix_command"):
                cmd = r["fix_command"]
                print(f"[fix] {r['name']}: running {cmd}", file=sys.stderr)
                try:
                    subprocess.run(cmd, shell=True, check=False, timeout=120)
                except subprocess.TimeoutExpired:
                    pass

    if args.json:
        print(json.dumps({
            "doctor_version": "1.0",
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "platform": _platform_name(),
            "python": _python_version(),
            "home": str(_home()),
            "checks": results,
        }, ensure_ascii=False, indent=2))
    else:
        print(_human_table(results))

    return 0 if not any(r["status"] == "fail" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
