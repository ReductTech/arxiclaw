"""Re-onboard a partially-set-up installation.

Detects missing pieces (credentials, policy, persona, schedule) and
walks the user through filling them in. Safe to run multiple times.

Usage:
    python scripts/onboard.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bootstrap import (
    BASE_URL, agent_home, prompt, prompt_choice, SUPPORTED_LANGS,
    load_or_init_json, write_json_secure, step_send_code, step_verify_code,
    step_bootstrap, step_save_credentials, step_set_interests,
    step_init_policy, step_init_persona, _local_tz,
)
import bootstrap as _b


def check(name: str, predicate: bool, fix_hint: str = "") -> None:
    mark = "✓" if predicate else "✗"
    print(f"  {mark} {name}")
    if not predicate and fix_hint:
        print(f"      → {fix_hint}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    home = agent_home()
    home.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  arxiclaw onboard (re-check / re-fill missing pieces)")
    print("=" * 60)
    print(f"  base URL: {BASE_URL}")
    print(f"  agent home: {home}\n")

    creds = (home / "credentials.json")
    policy = (home / "policy.json")
    persona = (home / "persona.json")
    schedule = _detect_schedule()

    print("[status]")
    check("credentials.json exists", creds.exists(),
          "run bootstrap.py")
    check("policy.json exists", policy.exists(),
          "run bootstrap.py")
    check("persona.json exists", persona.exists(),
          "run bootstrap.py")
    check("schedule registered", schedule,
          "run install_schedule.py")
    print()

    if not creds.exists():
        print("[fix] credentials.json missing — running bootstrap flow\n")
        return _b.main()  # delegate full bootstrap

    if not policy.exists():
        print("[fix] policy.json missing — recreating from defaults\n")
        lang = prompt_choice("Comment language", list(SUPPORTED_LANGS),
                             default="zh-CN")
        step_init_policy(home, lang, True, True, True, True, True, 20)

    if not persona.exists():
        print("[fix] persona.json missing — recreating skeleton\n")
        c = json.loads(creds.read_text(encoding="utf-8"))
        step_init_persona(home, c.get("userId"), c.get("username"),
                          c.get("email"))

    if not schedule:
        print("[fix] no schedule detected — install?")
        if prompt("  Run install_schedule.py now?", default="y").lower().startswith("y"):
            import subprocess
            subprocess.run([sys.executable, str(THIS_DIR / "install_schedule.py")])

    print("\n[ok] onboard complete.")
    return 0


def _detect_schedule() -> bool:
    """Best-effort: did the user register a scheduled task?"""
    if sys.platform.startswith("win"):
        try:
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", "ArxivClawDailyReader"],
                capture_output=True, text=True,
            )
            return r.returncode == 0
        except Exception:
            return False
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return "arxiclaw" in r.stdout
    except Exception:
        return False


if __name__ == "__main__":
    import subprocess  # late import for status detection
    sys.exit(main())
