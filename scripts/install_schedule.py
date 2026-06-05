"""Register arxiclaw daily runner as a scheduled task.

Supports:
- Windows (Task Scheduler via `schtasks`)
- Linux (cron or systemd timer)
- macOS (cron or launchd plist)

Reads `policy.schedule.{enabled, time, timezone}` and registers a single
daily run at the configured local time (default 07:17 to avoid the
:00 / :30 API peak). Logs go to `<agent_home>/runs/runner.log`.

Usage:
    python scripts/install_schedule.py
    python scripts/install_schedule.py --time 06:30
    python scripts/install_schedule.py --uninstall   # pass-through to uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TASK_NAME = "ArxivClawDailyReader"
LINUX_SERVICE = "arxiclaw-daily.service"
LINUX_TIMER = "arxiclaw-daily.timer"


def agent_home() -> Path:
    configured = os.getenv("ARXICLAW_AGENT_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.environ["USERPROFILE"]) / ".arxiclaw"
    return Path.home() / ".arxiclaw"


def detect_platform() -> str:
    s = sys.platform
    if s.startswith("win"):
        return "windows"
    if s.startswith("linux"):
        return "linux"
    if s == "darwin":
        return "macos"
    return s


# ---------- Windows ----------

def write_run_daily_bat(home: Path, action: str = "daily") -> Path:
    """Write the .bat wrapper if missing. `action` is one of:
    daily | report-yesterday | report-week | report-month"""
    bat = home / "run_daily.bat"
    pyexe_default = r"%USERPROFILE%\anaconda3\python.exe"
    # Map action -> runner subcommand + optional date arg
    if action == "report-yesterday":
        runner_args = "report-yesterday"
    elif action == "report-week":
        runner_args = "report-week"
    elif action == "report-month":
        runner_args = "report-month"
    else:
        runner_args = ""   # default: full daily (dry-run is opt-in)
    content = f"""@echo off
chcp 65001 >nul
setlocal
set AGENT_HOME={home}
set ARXICLAW_AGENT_HOME=%AGENT_HOME%
set ARXICLAW_BASE_URL=https://arxiclaw.reduct.cn
set PYTHONIOENCODING=utf-8
set PYEXE={pyexe_default}
if not exist "%PYEXE%" (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    set PYEXE=%%P
    goto :have_py
  )
  echo [fatal] python not found >> "%AGENT_HOME%\\runs\\runner.log"
  exit /b 2
)
:have_py
REM v3.1: only requests needed (no LLM deps)
"%PYEXE%" -m pip show requests >nul 2>nul
if errorlevel 1 (
  echo [warn] installing requests... >> "%AGENT_HOME%\\runs\\runner.log"
  "%PYEXE%" -m pip install --quiet requests >> "%AGENT_HOME%\\runs\\runner.log" 2>&1
)
"%PYEXE%" "%AGENT_HOME%\\daily_runner.py" {runner_args} >> "%AGENT_HOME%\\runs\\runner.log" 2>&1
exit /b %errorlevel%
"""
    home.mkdir(parents=True, exist_ok=True)
    bat.write_text(content, encoding="utf-8")
    return bat


def install_windows(home: Path, time_hhmm: str,
                    action: str = "daily") -> None:
    bat = write_run_daily_bat(home, action=action)
    tr = f'cmd.exe /c "{bat}"'
    # Different schedule cadences for different actions
    if action == "report-week":
        # Sunday
        sc = "WEEKLY"
        dow = "SUN"
        extra = ["/D", dow]
        label = f"weekly (Sunday) {time_hhmm}"
    elif action == "report-month":
        # 1st of month
        sc = "MONTHLY"
        dow = "1"
        extra = ["/D", dow]
        label = f"monthly (1st) {time_hhmm}"
    else:
        sc = "DAILY"
        extra = []
        label = f"daily {time_hhmm}"
    cmd = [
        "schtasks", "/Create", "/SC", sc,
        "/TN", TASK_NAME,
        "/TR", tr,
        "/ST", time_hhmm,
        "/F", "/RL", "HIGHEST",
    ] + extra
    print(f"  → {subprocess.list2cmdline(cmd)}")
    rc = subprocess.run(cmd, capture_output=True, text=True).returncode
    if rc == 0:
        print(f"  ✓ registered: {TASK_NAME} @ {label} (action={action})")
        print(f"  ✓ log: {home / 'runs' / 'runner.log'}")
        print(f"  ✓ test now: schtasks /Run /TN {TASK_NAME}")
    else:
        print(f"  ✗ schtasks failed with rc={rc}")
        print("    try:  schtasks /Create /SC DAILY /TN ArxivClawDailyReader "
              f"/TR 'cmd.exe /c \"{bat}\"' /ST {time_hhmm} /F /RL HIGHEST")


# ---------- Linux (cron + systemd) ----------

CRON_LINE_TEMPLATE = (
    "{minute} {hour} * * * PYTHONIOENCODING=utf-8 "
    "ARXICLAW_AGENT_HOME={home} {home}/daily_runner.py "
    ">> {home}/runs/runner.log 2>&1"
)


def install_linux_cron(home: Path, time_hhmm: str,
                      action: str = "daily") -> None:
    hh, mm = time_hhmm.split(":")
    # Build subcommand tail
    if action == "report-yesterday":
        sub_tail = "report-yesterday"
    elif action == "report-week":
        sub_tail = "report-week"
    elif action == "report-month":
        sub_tail = "report-month"
    else:
        sub_tail = ""
    line = (f"{int(mm)} {int(hh)} * * * PYTHONIOENCODING=utf-8 "
            f"ARXICLAW_AGENT_HOME={home} {home}/daily_runner.py {sub_tail} "
            f">> {home}/runs/runner.log 2>&1")
    # append to crontab
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True,
                                  text=True, check=False).stdout
    except FileNotFoundError:
        print("  ✗ crontab not installed; falling back to systemd timer")
        install_linux_systemd(home, time_hhmm)
        return
    if line in existing:
        print(f"  ✓ crontab entry already present")
        return
    new = existing.rstrip("\n") + "\n" + line + "\n"
    p = subprocess.run(["crontab", "-"], input=new, capture_output=True,
                       text=True)
    if p.returncode == 0:
        print(f"  ✓ crontab registered: {line}")
    else:
        print(f"  ✗ crontab failed: {p.stderr}")


def install_linux_systemd(home: Path, time_hhmm: str,
                       action: str = "daily") -> None:
    """Write user-level systemd service+timer (no sudo)."""
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    python_path = shutil.which("python3") or sys.executable
    # Subcommand tail
    if action == "report-yesterday":
        sub_tail = "report-yesterday"
    elif action == "report-week":
        sub_tail = "report-week"
    elif action == "report-month":
        sub_tail = "report-month"
    else:
        sub_tail = ""
    service = systemd_dir / LINUX_SERVICE
    service.write_text(f"""[Unit]
Description=arxiclaw {action} runner
After=network-online.target

[Service]
Type=oneshot
Environment="ARXICLAW_AGENT_HOME={home}"
Environment="PYTHONIOENCODING=utf-8"
WorkingDirectory={home}
ExecStart={python_path} {home}/daily_runner.py {sub_tail}
StandardOutput=append:{home}/runs/runner.log
StandardError=append:{home}/runs/runner.log

[Install]
WantedBy=default.target
""", encoding="utf-8")
    timer = systemd_dir / LINUX_TIMER
    hh, mm = time_hhmm.split(":")
    # Different OnCalendar for different actions
    if action == "report-week":
        # Sunday at HH:MM
        on_cal = f"Sun *-*-* {int(hh):02d}:{int(mm):02d}:00"
    elif action == "report-month":
        # 1st of month at HH:MM
        on_cal = f"*-*-01 {int(hh):02d}:{int(mm):02d}:00"
    else:
        on_cal = f"*-*-* {int(hh):02d}:{int(mm):02d}:00"
    timer.write_text(f"""[Unit]
Description=arxiclaw {action} timer

[Timer]
OnCalendar={on_cal}
Persistent=true

[Install]
WantedBy=timers.target
""", encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", LINUX_TIMER], check=False)
    subprocess.run(["systemctl", "--user", "start", LINUX_TIMER], check=False)
    print(f"  ✓ systemd --user timer enabled: {LINUX_TIMER} "
          f"({action} @ {on_cal})")


def install_linux(home: Path, time_hhmm: str, action: str = "daily") -> None:
    if shutil.which("systemctl") and "XDG_RUNTIME_DIR" in os.environ:
        try:
            subprocess.run(["systemctl", "--user", "status"],
                           capture_output=True, check=True, timeout=5)
            install_linux_systemd(home, time_hhmm, action=action)
            return
        except Exception:
            pass
    install_linux_cron(home, time_hhmm, action=action)


# ---------- macOS ----------

def install_macos(home: Path, time_hhmm: str, action: str = "daily") -> None:
    # Cron is the simplest path on macOS. launchd is also supported but
    # needs plist file. For now default to cron.
    install_linux_cron(home, time_hhmm, action=action)


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Register arxiclaw scheduled task (v3.1: support multiple actions)")
    ap.add_argument("--time", default="07:17",
                    help="HH:MM in local time (default: 07:17, overrides policy)")
    ap.add_argument("--action", default="daily",
                    choices=["daily", "report-yesterday", "report-week", "report-month"],
                    help="what to run: daily (default) / report-yesterday / "
                         "report-week (Sunday) / report-month (1st of month)")
    ap.add_argument("--day-of-week", default=None,
                    choices=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                    help="for report-week: which day to run (default: sun)")
    ap.add_argument("--day-of-month", type=int, default=None,
                    help="for report-month: which day (default: 1)")
    ap.add_argument("--uninstall", action="store_true",
                    help="uninstall instead of install")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    home = agent_home()
    plat = detect_platform()
    print("=" * 60)
    print("  arxiclaw scheduler installer")
    print("=" * 60)
    print(f"  platform: {plat}")
    print(f"  agent home: {home}")

    if args.uninstall:
        from uninstall import uninstall_all
        return uninstall_all(plat, home, TASK_NAME, LINUX_TIMER)

    # Determine time
    policy_path = home / "policy.json"
    time_hhmm = args.time
    if not time_hhmm and policy_path.exists():
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            time_hhmm = policy.get("schedule", {}).get("time", "07:17")
        except Exception:
            time_hhmm = "07:17"
    time_hhmm = time_hhmm or "07:17"
    print(f"  scheduled time: {time_hhmm} (local)")
    print(f"  action: {args.action}")

    if plat == "windows":
        install_windows(home, time_hhmm, action=args.action)
    elif plat == "linux":
        install_linux(home, time_hhmm, action=args.action)
    elif plat == "macos":
        install_macos(home, time_hhmm, action=args.action)
    else:
        print(f"  ✗ unsupported platform: {plat}")
        return 2

    # mark enabled
    if policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy.setdefault("schedule", {})["enabled"] = True
        policy["schedule"]["time"] = time_hhmm
        policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2),
                               encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
