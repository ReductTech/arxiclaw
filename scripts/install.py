"""arxiclaw one-stop install.

Run: python scripts/install.py [--non-interactive] [--skip-schedule] [--upgrade]

Pipeline:
  1. Verify Python 3.10+
  2. pip install -r requirements.txt
  3. Call bootstrap.py (zero-secret bootstrap via email)
  4. Optionally register schedule
  5. Run doctor to confirm

Designed for AI agents: every step is non-interactive when --non-interactive
is passed. By default it asks the user once per step (via bootstrap.py).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------- paths ----------

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REQUIREMENTS = ROOT / "requirements.txt"
BOOTSTRAP = HERE / "bootstrap.py"
DOCTOR = HERE / "doctor.py"
INSTALL_SCHEDULE = HERE / "install_schedule.py"

ARXICLAW_AGENT_HOME = os.environ.get("ARXICLAW_AGENT_HOME")
if ARXICLAW_AGENT_HOME:
    HOME = Path(ARXICLAW_AGENT_HOME).expanduser()
elif os.name == "nt":
    HOME = Path(os.environ.get("USERPROFILE", "~")) / ".arxiclaw"
else:
    HOME = Path.home() / ".arxiclaw"


# ---------- helpers ----------

def _run(cmd: list[str], **kw) -> int:
    print(f"[install] $ {' '.join(cmd)}", file=sys.stderr, flush=True)
    return subprocess.run(cmd, **kw).returncode


def _python() -> str:
    return sys.executable


# ---------- pipeline steps ----------

def step_check_python() -> bool:
    print("[1/5] Checking Python version...", flush=True)
    if sys.version_info < (3, 10):
        print(f"  [FAIL] Python {sys.version_info.major}.{sys.version_info.minor} detected; need >= 3.10",
              file=sys.stderr)
        return False
    print(f"  [OK] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", flush=True)
    return True


def step_install_deps(non_interactive: bool, upgrade: bool) -> bool:
    print(f"[2/5] {'Upgrading' if upgrade else 'Installing'} dependencies...", flush=True)
    cmd = [_python(), "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd += ["-r", str(REQUIREMENTS)]
    rc = _run(cmd, check=False)
    if rc != 0:
        print(f"  [FAIL] pip install returned {rc}", file=sys.stderr)
        return False
    print("  [OK] dependencies installed", flush=True)
    return True


def step_bootstrap(non_interactive: bool) -> bool:
    print(f"[3/5] Bootstrapping arxiclaw at {HOME} ...", flush=True)
    if (HOME / "credentials.json").exists():
        print(f"  [SKIP] credentials.json already exists at {HOME / 'credentials.json'}", flush=True)
        print("         (delete it manually if you want to re-bootstrap)", flush=True)
        return True
    cmd = [_python(), str(BOOTSTRAP)]
    if non_interactive:
        cmd.append("--non-interactive")
    rc = _run(cmd, check=False)
    if rc != 0 and rc != 2:
        # rc=2 is bootstrap's "missing required arg" exit code;
        # in non-interactive mode this is expected (we ran out of input)
        print(f"  [WARN] bootstrap exited with code {rc}", file=sys.stderr)
        return False
    print("  [OK] bootstrap complete", flush=True)
    return True


def step_register_schedule(skip: bool, non_interactive: bool) -> bool:
    if skip:
        print("[4/5] Skipping schedule registration (--skip-schedule)", flush=True)
        return True
    print("[4/5] Registering daily schedule (07:17 local)...", flush=True)
    if non_interactive:
        print("  [SKIP] non-interactive mode (re-run without --non-interactive to register)",
              flush=True)
        return True
    cmd = [_python(), str(INSTALL_SCHEDULE)]
    rc = _run(cmd, check=False)
    if rc != 0:
        print(f"  [WARN] schedule registration returned {rc}", file=sys.stderr)
        return False
    print("  [OK] schedule registered", flush=True)
    return True


def step_doctor() -> bool:
    print("[5/5] Running doctor to confirm install...", flush=True)
    rc = _run([_python(), str(DOCTOR), "--json"], check=False)
    if rc == 0:
        print("  [OK] doctor: no critical failures", flush=True)
        return True
    print("  [WARN] doctor reported warnings/failures (run `make doctor` for details)",
          file=sys.stderr)
    return False


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="arxiclaw one-stop install")
    parser.add_argument("--non-interactive", action="store_true",
                        help="don't prompt; skip schedule registration")
    parser.add_argument("--skip-schedule", action="store_true",
                        help="don't register the daily schedule task")
    parser.add_argument("--upgrade", action="store_true",
                        help="pip install --upgrade the dependencies")
    parser.add_argument("--skip-doctor", action="store_true",
                        help="skip final doctor check")
    args = parser.parse_args(argv)

    print(f"arxiclaw install @ {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", flush=True)
    print(f"target home: {HOME}", flush=True)
    print("", flush=True)

    if not step_check_python():
        return 2
    if not step_install_deps(args.non_interactive, args.upgrade):
        return 3
    if not step_bootstrap(args.non_interactive):
        return 4
    if not step_register_schedule(args.skip_schedule, args.non_interactive):
        return 5
    if not args.skip_doctor and not step_doctor():
        return 6

    print("", flush=True)
    print("[OK] arxiclaw install complete", flush=True)
    print(f"     home: {HOME}", flush=True)
    print("     next: try `make daily` or read AGENTS.md §5", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
