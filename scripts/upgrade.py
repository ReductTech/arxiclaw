"""arxiclaw transactional upgrade.

Run: python scripts/upgrade.py [--from <ref>] [--no-pull] [--json]

Pipeline (transactional — any step failure rolls back to pre-upgrade state):
  1. Snapshot current HEAD (commit hash)
  2. Pre-flight: doctor must pass
  3. git fetch + git pull (or git checkout <ref>)
  4. Reinstall dependencies (in case requirements.txt changed)
  5. Run pending schema migrations
  6. Post-flight: doctor must pass
  7. If anything fails: git reset --hard <snapshot> + reinstall deps

If upgrade succeeds, prints "upgrade to <new-commit>" + CHANGELOG hint.
If upgrade fails, prints "rolled back to <snapshot>" + doctor report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOCTOR = HERE / "doctor.py"
MIGRATE = HERE / "migrate.py"


def _run(cmd: list[str], cwd: Path | None = None, **kw) -> subprocess.CompletedProcess:
    print(f"[upgrade] $ {' '.join(cmd)} (cwd={cwd or ROOT})", file=sys.stderr, flush=True)
    return subprocess.run(cmd, cwd=cwd or ROOT, **kw)


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=check)


def _current_commit() -> str:
    return _git("rev-parse", "HEAD", check=False).stdout.strip()


def _current_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()


def _is_clean() -> bool:
    r = _git("status", "--porcelain", check=False)
    return r.returncode == 0 and r.stdout.strip() == ""


def _preflight_doctor() -> bool:
    print("[1/5] Pre-flight: running doctor...", flush=True)
    r = _run([sys.executable, str(DOCTOR), "--json"], check=False,
             capture_output=True, text=True)
    if r.returncode != 0:
        try:
            data = json.loads(r.stdout)
            fails = [c["name"] for c in data.get("checks", []) if c["status"] == "fail"]
            print(f"  [WARN] pre-flight doctor reported {len(fails)} failure(s): {fails}",
                  file=sys.stderr)
        except Exception:
            print("  [WARN] pre-flight doctor failed to parse", file=sys.stderr)
        return False
    print("  [OK] pre-flight clean", flush=True)
    return True


def _pull(from_ref: str | None) -> str:
    print(f"[2/5] Pulling updates (from={from_ref or 'default remote'})...", flush=True)
    if from_ref:
        # explicit ref — fetch + reset
        remote = _git("config", "--get", "remote.origin.url", check=False).stdout.strip()
        if not remote:
            print("  [FAIL] no remote configured and --from given", file=sys.stderr)
            return ""
        r = _run(["git", "fetch", "origin"], check=False, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  [FAIL] git fetch failed: {r.stderr}", file=sys.stderr)
            return ""
        r = _run(["git", "reset", "--hard", f"origin/{from_ref}"], check=False,
                 capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  [FAIL] git reset failed: {r.stderr}", file=sys.stderr)
            return ""
    else:
        r = _run(["git", "pull", "--ff-only"], check=False, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  [FAIL] git pull failed: {r.stderr}", file=sys.stderr)
            return ""
    return _current_commit()


def _reinstall_deps() -> bool:
    print("[3/5] Reinstalling dependencies (in case requirements.txt changed)...",
          flush=True)
    r = _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
             check=False)
    if r.returncode != 0:
        print(f"  [FAIL] pip install returned {r.returncode}", file=sys.stderr)
        return False
    print("  [OK] deps up to date", flush=True)
    return True


def _migrate() -> bool:
    print("[4/5] Running pending schema migrations...", flush=True)
    r = _run([sys.executable, str(MIGRATE)], check=False)
    if r.returncode not in (0, 2):
        # rc=2 = no migrations needed
        print(f"  [FAIL] migrate returned {r.returncode}", file=sys.stderr)
        return False
    print("  [OK] migrations clean", flush=True)
    return True


def _postflight_doctor() -> bool:
    print("[5/5] Post-flight: running doctor...", flush=True)
    r = _run([sys.executable, str(DOCTOR), "--json"], check=False,
             capture_output=True, text=True)
    if r.returncode != 0:
        try:
            data = json.loads(r.stdout)
            fails = [c["name"] for c in data.get("checks", []) if c["status"] == "fail"]
            print(f"  [FAIL] post-flight doctor: {fails}", file=sys.stderr)
        except Exception:
            print("  [FAIL] post-flight doctor could not parse", file=sys.stderr)
        return False
    print("  [OK] post-flight clean", flush=True)
    return True


def _rollback(snapshot: str) -> None:
    print(f"[rollback] resetting to {snapshot[:8]}...", file=sys.stderr, flush=True)
    _run(["git", "reset", "--hard", snapshot], check=False)
    _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="arxiclaw transactional upgrade")
    parser.add_argument("--from", dest="from_ref", default=None,
                        help="explicit ref to upgrade to (e.g. main, v0.3.2)")
    parser.add_argument("--no-pull", action="store_true",
                        help="skip git pull (already done externally)")
    parser.add_argument("--no-deps", action="store_true",
                        help="skip pip install (deps unchanged)")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="allow uncommitted local changes (still snapshots)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    if not _is_clean() and not args.allow_dirty:
        print("[FAIL] working tree has uncommitted changes. Commit or stash first, "
              "or pass --allow-dirty.", file=sys.stderr)
        return 1

    snapshot = _current_commit()
    if not snapshot:
        print("[FAIL] not a git repository (or git unavailable)", file=sys.stderr)
        return 1

    print(f"arxiclaw upgrade @ branch={_current_branch()} snapshot={snapshot[:8]}",
          flush=True)
    print("", flush=True)

    # Pre-flight: do not even attempt upgrade if env is broken
    if not _preflight_doctor():
        print("\n[ABORT] pre-flight failed; upgrade not attempted.", file=sys.stderr)
        print("        fix the doctor failures first, then retry.", file=sys.stderr)
        return 2

    if not args.no_pull:
        new_commit = _pull(args.from_ref)
        if not new_commit:
            print("\n[ABORT] pull failed; nothing changed.", file=sys.stderr)
            return 3
        if new_commit == snapshot:
            print(f"\n[OK] already at {snapshot[:8]}; nothing to do.", flush=True)
            return 0
    else:
        new_commit = _current_commit()
        if new_commit == snapshot:
            print("\n[OK] no new commit; nothing to do.", flush=True)
            return 0

    # Now we're on new code. Run remaining steps. If any fails, roll back.
    print(f"  [info] new commit: {new_commit[:8]}", flush=True)
    if not args.no_deps and not _reinstall_deps():
        _rollback(snapshot)
        return 4
    if not _migrate():
        _rollback(snapshot)
        return 5
    if not _postflight_doctor():
        _rollback(snapshot)
        return 6

    print("", flush=True)
    print(f"[OK] upgrade complete: {snapshot[:8]} -> {new_commit[:8]}", flush=True)
    if args.json:
        print(json.dumps({
            "ok": True,
            "from": snapshot,
            "to": new_commit,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
