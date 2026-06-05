"""Unregister arxiclaw daily scheduled task and optionally clear state.

Usage:
    python scripts/uninstall.py
    python scripts/uninstall.py --purge-runs      # also delete runs/ except last 7
    python scripts/uninstall.py --keep-credentials
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


LINUX_TIMER = "arxiclaw-daily.timer"
LINUX_SERVICE = "arxiclaw-daily.service"
TASK_NAME = "ArxivClawDailyReader"


def uninstall_windows(home: Path, task_name: str) -> None:
    cmd = ["schtasks", "/Delete", "/TN", task_name, "/F"]
    print(f"  → {subprocess.list2cmdline(cmd)}")
    rc = subprocess.run(cmd, capture_output=True, text=True).returncode
    if rc == 0:
        print("  ✓ Windows task deleted")
    else:
        print(f"  (rc={rc}; task may not exist)")


def uninstall_linux(home: Path, task_name: str, timer: str) -> None:
    # systemd --user
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", timer], check=False)
        subprocess.run(["systemctl", "--user", "stop", timer], check=False)
        for f in (timer, LINUX_SERVICE):
            path = Path.home() / ".config" / "systemd" / "user" / f
            if path.exists():
                path.unlink()
                print(f"  ✓ removed {path}")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    # crontab
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True,
                                  text=True, check=False).stdout
    except FileNotFoundError:
        existing = ""
    if "arxiclaw" in existing:
        new = "\n".join(
            line for line in existing.splitlines()
            if "arxiclaw" not in line
        )
        subprocess.run(["crontab", "-"], input=new, capture_output=True, text=True)
        print("  ✓ crontab entry removed")
    else:
        print("  (no crontab entry found)")


def uninstall_macos(home: Path, task_name: str, timer: str) -> None:
    uninstall_linux(home, task_name, timer)


def uninstall_all(plat: str, home: Path, task_name: str, timer: str) -> int:
    if plat == "windows":
        uninstall_windows(home, task_name)
    elif plat in ("linux", "macos"):
        uninstall_linux(home, task_name, timer)
    else:
        print(f"  ✗ unsupported platform: {plat}")
        return 2
    # mark disabled
    policy_path = home / "policy.json"
    if policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy.setdefault("schedule", {})["enabled"] = False
        policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Uninstall arxiclaw scheduler")
    ap.add_argument("--purge-runs", action="store_true",
                    help="delete runs/ except last 7 days")
    ap.add_argument("--keep-credentials", action="store_true",
                    help="do not delete credentials.json")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    home = Path(os.getenv("ARXICLAW_AGENT_HOME") or (
        Path(os.environ["USERPROFILE"]) / ".arxiclaw"
        if os.name == "nt" else Path.home() / ".arxiclaw"
    ))
    plat = "windows" if sys.platform.startswith("win") else (
        "darwin" if sys.platform == "darwin" else "linux"
    )

    print("=" * 60)
    print("  arxiclaw scheduler uninstaller")
    print("=" * 60)
    print(f"  platform: {plat}")
    print(f"  agent home: {home}")

    rc = uninstall_all(plat, home, TASK_NAME, LINUX_TIMER)

    if args.purge_runs:
        runs = home / "runs"
        if runs.exists():
            keep = sorted([p for p in runs.iterdir() if p.is_dir()],
                          reverse=True)[:7]
            keep_names = {p.name for p in keep}
            for p in runs.iterdir():
                if p.is_dir() and p.name not in keep_names:
                    shutil.rmtree(p)
                    print(f"  ✓ removed {p}")

    if not args.keep_credentials:
        creds = home / "credentials.json"
        if creds.exists() and input("  Delete credentials.json? (y/n) [n]: ").lower().startswith("y"):
            creds.unlink()
            print(f"  ✓ removed {creds}")

    print("  Done.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
