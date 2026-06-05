"""arxiclaw state-file schema migration.

Run: python scripts/migrate.py [--dry-run] [--json]

Detects schema version in `engagement_state.json` and runs pending
migrations in order. Each migration is a pure function
`v<N>_to_v<N+1>(state) -> state`. Idempotent: re-running on an
already-migrated state is a no-op.

Currently supported migrations:
  - v0 -> v1  (initial schema; renames keys for forward-compat)
  - (more added per release)

State file: ~/.arxiclaw/engagement_state.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ---------- paths ----------

if os.environ.get("ARXICLAW_AGENT_HOME"):
    HOME = Path(os.environ["ARXICLAW_AGENT_HOME"]).expanduser()
elif os.name == "nt":
    HOME = Path(os.environ.get("USERPROFILE", "~")) / ".arxiclaw"
else:
    HOME = Path.home() / ".arxiclaw"

ENGAGEMENT = HOME / "engagement_state.json"

# ---------- migration registry ----------
#
# Add new migrations here. Each entry: (from_version, to_version, fn).
# The fn takes the engagement_state dict, mutates + returns it.

CURRENT_VERSION = 1

MIGRATIONS: list[tuple[int, int, Callable[[dict[str, Any]], dict[str, Any]]]] = [
    # v0 -> v1: initial schema (adds schemaVersion field if missing)
    (0, 1, lambda s: {**s, "schemaVersion": 1, "v0_migrated_at": datetime.now(timezone.utc).isoformat()}),
]


# ---------- core ----------

def detect_version(state: dict[str, Any]) -> int:
    """Return the schema version embedded in the state, or 0 if missing."""
    return int(state.get("schemaVersion", 0))


def pending_migrations(state: dict[str, Any]) -> list[tuple[int, int, Callable]]:
    current = detect_version(state)
    return [(frm, to, fn) for (frm, to, fn) in MIGRATIONS if frm >= current]


def apply_all(state: dict[str, Any], dry_run: bool) -> list[tuple[int, int]]:
    """Apply pending migrations. Returns list of (from, to) pairs that ran."""
    applied: list[tuple[int, int]] = []
    for frm, to, fn in pending_migrations(state):
        if not dry_run:
            state = fn(state)
        applied.append((frm, to))
    if not dry_run and applied:
        state["schemaVersion"] = applied[-1][1]
    return applied


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="arxiclaw schema migration")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview migrations without modifying state")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    if not ENGAGEMENT.exists():
        if args.json:
            print(json.dumps({
                "ok": False, "reason": "engagement_state.json missing",
                "ran_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
        else:
            print(f"[migrate] no engagement_state.json at {ENGAGEMENT}", file=sys.stderr)
            print("         (run `make install` first)", file=sys.stderr)
        return 0  # not an error; nothing to migrate

    try:
        state = json.loads(ENGAGEMENT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[migrate] invalid JSON in {ENGAGEMENT}: {exc}", file=sys.stderr)
        return 1

    before_version = detect_version(state)
    if before_version > CURRENT_VERSION:
        print(f"[migrate] state is at schemaVersion={before_version}, "
              f"but this client only supports up to {CURRENT_VERSION}.", file=sys.stderr)
        print("         upgrade the arxiclaw client to a newer version.", file=sys.stderr)
        return 2

    pending = pending_migrations(state)
    if not pending:
        if args.json:
            print(json.dumps({
                "ok": True, "applied": [],
                "current_version": before_version,
                "ran_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
        else:
            print(f"[migrate] schemaVersion={before_version}; nothing to do.", flush=True)
        return 0

    applied = apply_all(state, dry_run=args.dry_run)

    if not args.dry_run:
        ENGAGEMENT.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if os.name != "nt":
            try:
                os.chmod(ENGAGEMENT, 0o600)
            except OSError:
                pass

    if args.json:
        print(json.dumps({
            "ok": True,
            "dry_run": args.dry_run,
            "applied": [{"from": frm, "to": to} for (frm, to) in applied],
            "current_version": applied[-1][1] if applied else before_version,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2))
    else:
        verb = "would apply" if args.dry_run else "applied"
        for frm, to in applied:
            print(f"  {verb} v{frm} -> v{to}", flush=True)
        if not args.dry_run:
            print(f"[migrate] state is now schemaVersion={applied[-1][1]}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
