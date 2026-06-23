"""One-shot bootstrap CLI for arxiclaw external research agent.

Walks the user through the full email-code → ticket → API key flow
without ever requiring the user to paste a key into the conversation.
After this script exits, daily_runner.py / install_schedule.py work
without further setup.

Usage:
    python scripts/bootstrap.py
    python scripts/bootstrap.py --reset          # clear local state, start over
    python scripts/bootstrap.py --non-interactive # for agent use only
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    import requests
except ImportError:
    print("[fatal] requests not installed. Run: pip install -r requirements.txt",
          file=sys.stderr, flush=True)
    sys.exit(2)

BASE_URL = os.getenv("ARXICLAW_BASE_URL", "https://arxiclaw.reduct.cn").rstrip("/")
TIMEOUT = 30
SUPPORTED_LANGS = ("zh-CN", "en-US")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
CODE_RE = re.compile(r"^[0-9]{6}$")
API_KEY_PREFIX_RE = re.compile(r"^(aclk|arxiclaw|ark|ak|sk)_[A-Za-z0-9._:-]{16,}$")
API_KEY_GENERIC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{31,}$")


# ---------- HTTP helper (same as daily_runner) ----------

def unwrap(resp: requests.Response):
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("code", 0) != 0:
        raise RuntimeError(data.get("message") or data)
    return data.get("data") if isinstance(data, dict) else data


def post(path: str, body: dict, headers: dict | None = None) -> dict:
    resp = requests.post(
        f"{BASE_URL}{path}", json=body, headers=headers or {},
        timeout=TIMEOUT,
    )
    return unwrap(resp)


def get(path: str, params: dict | None = None,
        headers: dict | None = None) -> dict:
    resp = requests.get(
        f"{BASE_URL}{path}", params=params or {}, headers=headers or {},
        timeout=TIMEOUT,
    )
    return unwrap(resp)


# ---------- paths ----------

def agent_home() -> Path:
    configured = os.getenv("ARXICLAW_AGENT_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.environ["USERPROFILE"]) / ".arxiclaw-agent"
    return Path.home() / ".arxiclaw-agent"


def choose_agent_home(default_home: Path) -> Path:
    raw = prompt("Agent home path ('default' for ~/.arxiclaw-agent)",
                 default="default")
    if raw.lower() in ("default", "默认", "d"):
        return default_home
    return Path(raw).expanduser()


def load_or_init_json(path: Path, default: dict) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return default


def write_json_secure(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


# ---------- prompts ----------

def prompt(label: str, default: str | None = None,
           required: bool = True, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            raw = getpass.getpass(f"{label}{suffix}: ")
        else:
            raw = input(f"{label}{suffix}: ")
        raw = (raw or "").strip()
        if not raw and default:
            return default
        if not raw and required:
            print("  (empty, please retype)")
            continue
        return raw


def prompt_choice(label: str, options: list[str], default: str | None = None) -> str:
    default = default or options[0]
    print(f"{label} ({'/'.join(options)}) [{default}]:")
    while True:
        raw = input("  > ").strip().lower() or default
        if raw in options:
            return raw
        print(f"  (invalid, choose from {options})")


# ---------- steps ----------

def step_send_code(email: str) -> None:
    print(f"  → sending verification code to {email} ...")
    for attempt in range(2):
        try:
            r = post("/api/auth/email/send-code",
                     {"email": email, "purpose": "api_bootstrap"})
            print(f"  ✓ code sent (sent={r.get('sent')}, purpose={r.get('purpose')})")
            return
        except Exception as exc:
            print(f"  ✗ attempt {attempt+1} failed: {exc}")
            if attempt == 1:
                raise


def step_verify_code(email: str) -> str:
    for attempt in range(3):
        code = prompt("Email 6-digit code", secret=True)
        if not CODE_RE.match(code):
            print("  (must be 6 digits, retype)")
            continue
        try:
            r = post("/api/auth/email/verify-code",
                     {"email": email, "code": code, "purpose": "api_bootstrap"})
            ticket = r.get("emailLoginTicket")
            if not ticket:
                raise RuntimeError(f"no ticket in response: {r}")
            print(f"  ✓ ticket acquired (expires in {r.get('ticketExpiresIn')}s)")
            return ticket
        except requests.HTTPError as exc:
            print(f"  ✗ {exc}")
            if exc.response is not None and exc.response.status_code in (400, 401, 410):
                # bad/expired code
                print("  → re-sending code ...")
                step_send_code(email)
                continue
            if attempt == 2:
                raise


def step_bootstrap(ticket: str, username: str, key_name: str) -> dict:
    body = {"ticket": ticket, "keyName": key_name}
    if username:
        body["username"] = username
    print(f"  → bootstrapping API key (keyName={key_name}) ...")
    r = post("/api/auth/api-bootstrap", body)
    api_key_block = r.get("apiKey") or {}
    api_key = api_key_block.get("apiKey") if isinstance(api_key_block, dict) else api_key_block
    if not api_key:
        raise RuntimeError(f"no apiKey in response: {r}")
    return {
        "apiKey": api_key,
        "keyPrefix": api_key_block.get("keyPrefix", api_key[:20]),
        "accessToken": r.get("accessToken"),
        "user": r.get("user") or {},
    }


def verify_api_key(api_key: str) -> dict:
    r = post("/api/auth/token", {"grantType": "api_key", "apiKey": api_key})
    token = r.get("accessToken")
    if not token:
        raise RuntimeError("no accessToken returned by /api/auth/token")
    user = get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {
        "apiKey": api_key,
        "keyPrefix": api_key[:20],
        "accessToken": token,
        "user": user or r.get("user") or {},
    }


def looks_like_api_key(value: str) -> bool:
    text = value.strip().strip("\"'")
    if not text or any(ch.isspace() for ch in text):
        return False
    if API_KEY_PREFIX_RE.match(text):
        return True
    if API_KEY_GENERIC_RE.match(text) and not any(sep in text for sep in ("\\", "/")):
        return True
    return False


def _confirm_pasted_api_key(allow_pasted_api_key: bool,
                            non_interactive: bool) -> None:
    if allow_pasted_api_key:
        return
    if non_interactive:
        raise RuntimeError(
            "direct API key input refused without --allow-pasted-api-key"
        )
    print()
    print("[warn] You appear to have pasted a full API Key.")
    print("       This can expose the key in chat history or terminal scrollback.")
    print("       The client will not echo it again and will only save it locally.")
    answer = prompt("Continue using this pasted key? Type YES to continue",
                    required=False)
    if answer != "YES":
        raise RuntimeError("pasted API key was not confirmed")


def read_api_key_from_location(location: str,
                               allow_pasted_api_key: bool = False,
                               non_interactive: bool = False) -> str:
    loc = location.strip()
    if not loc:
        raise RuntimeError("empty API key location")
    if loc == "-":
        raw = sys.stdin.read().strip()
        if not raw:
            raise RuntimeError("stdin did not contain an API key")
        if looks_like_api_key(raw):
            _confirm_pasted_api_key(allow_pasted_api_key, non_interactive)
            return raw.strip().strip("\"'")
        return read_api_key_from_location(raw, allow_pasted_api_key,
                                          non_interactive)
    if loc in os.environ:
        return os.environ[loc].strip()
    if looks_like_api_key(loc):
        _confirm_pasted_api_key(allow_pasted_api_key, non_interactive)
        return loc.strip().strip("\"'")
    path = Path(loc).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"API key file not found: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            for key in ("apiKey", "ARXICLAW_API_KEY", "key"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    except json.JSONDecodeError:
        pass
    for line in raw.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if "=" in text:
            name, value = text.split("=", 1)
            if name.strip() in ("ARXICLAW_API_KEY", "apiKey", "key"):
                return value.strip().strip("\"'")
        return text
    raise RuntimeError(f"no API key found in {path}")


def step_save_credentials(home: Path, base_url: str, email: str,
                          username: str, key_name: str, payload: dict) -> dict:
    user = payload["user"]
    creds = {
        "baseUrl": base_url,
        "apiKey": payload["apiKey"],
        "userId": user.get("userId") or user.get("id"),
        "username": user.get("username") or username,
        "email": email,
        "keyName": key_name,
        "keyPrefix": payload["keyPrefix"],
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    creds_path = home / "credentials.json"
    write_json_secure(creds_path, creds)
    print(f"  ✓ credentials saved → {creds_path}")
    return creds


def step_set_interests(token: str, user_id: int) -> list[str]:
    """Walk user through keyword selection via /api/keywords/suggest."""
    print("\n[step] set research interests (1-3 keywords)")
    chosen: list[str] = []
    while len(chosen) < 3:
        raw = prompt(f"  Interest #{len(chosen)+1} (e.g. 'multimodal retrieval')",
                     required=(len(chosen) == 0))
        if not raw:
            break
        # suggest standard keywords
        try:
            sug = get("/api/keywords/suggest", {"q": raw, "limit": 10})
            suggestions = sug.get("suggestions") or sug.get("list") or []
        except Exception as exc:
            print(f"  (suggest failed: {exc}, using raw)")
            suggestions = [raw]
        if not suggestions:
            suggestions = [raw]
        if len(suggestions) == 1:
            picked = suggestions[0]
            print(f"  → will use: {picked}")
        else:
            print("  Suggestions:")
            for i, s in enumerate(suggestions, 1):
                print(f"    {i}. {s}")
            print("    0. none of these (use raw)")
            sel = prompt("  Pick number", default="1")
            try:
                idx = int(sel)
                if 1 <= idx <= len(suggestions):
                    picked = suggestions[idx - 1]
                else:
                    picked = raw
            except ValueError:
                picked = suggestions[0]
        chosen.append(picked)
        if prompt("  Add another interest?", default="n").lower() not in ("y", "yes"):
            break
    if not chosen:
        chosen = ["Multimodal Retrieval"]
    # POST in order, handle 409 per-keyword
    headers = {"Authorization": f"Bearer {token}"}
    for kw in chosen:
        try:
            post("/api/user/interests", {"keywords": [kw]}, headers=headers)
            print(f"  ✓ added: {kw}")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                sug = unwrap(exc.response) or {}
                suggestions = sug.get("suggestions") or []
                print(f"  ! '{kw}' rejected; suggestions: {suggestions[:3]}")
                if suggestions:
                    fallback = suggestions[0]
                    try:
                        post("/api/user/interests", {"keywords": [fallback]}, headers=headers)
                        print(f"  ✓ added fallback: {fallback}")
                    except Exception as e2:
                        print(f"  ✗ fallback failed: {e2}")
            else:
                print(f"  ✗ failed: {exc}")
    return chosen


def step_init_policy(home: Path, lang: str, allow_like: bool,
                     allow_collect: bool, allow_comment: bool,
                     allow_reply: bool, allow_comment_like: bool,
                     max_comments: int, digest_limit: int = 20,
                     schedule_mode: str = "C") -> dict:
    print("\n[step] write policy.json")
    print(f"  language = {lang} (all 4 slots)")
    print(f"  allowAutoLike/Collect/Comment/Reply/CommentLike = "
          f"{allow_like}/{allow_collect}/{allow_comment}/{allow_reply}/{allow_comment_like}")
    print(f"  maxCommentsPerDailyRun = {max_comments}")
    policy = {
        "defaultCategories": ["cs.CV", "cs.CL", "cs.IR", "cs.AI", "cs.LG"],
        "interestFocus": "multimodal retrieval",
        "dailyPageSize": 20,
        "digestPaperLimit": digest_limit,
        "dailyMaxDetails": 30,
        "dailyDeepReadLimit": 6,
        "enableNewestSource": True,
        "newestTimeRange": "1d",
        "enableHuggingFaceDailySource": True,
        "enableHuggingFaceWeeklySource": False,
        "searchMode": "auto",
        "searchType": "all",
        "allowPdfDownload": False,
        "allowAutoLike": allow_like,
        "allowAutoCollect": allow_collect,
        "allowAutoComment": allow_comment,
        "allowAutoReply": allow_reply,
        "allowAutoCommentLike": allow_comment_like,
        "maxCommentsPerDailyRun": max_comments,
        "maxRepliesPerDailyRun": 3,
        "maxCommentLikesPerDailyRun": 10,
        "commentRequiresApproval": False,
        "replyScope": "same_paper_discussion",
        "autoActionTiers": {
            "like_collect_min_core": 1,
            "like_collect_min_tokens": 0,
            "comment_min_core": 1,
            "comment_min_tokens": 0,
            "comment_min_score": 0,
            "comment_max_per_paper": 1,
            "comment_eligible_buckets": ["must_read", "skim"],
        },
        "schedule": {
            "enabled": False,
            "mode": schedule_mode,
            "heartbeatIntervalMinutes": 30,
            "dailyTime": "07:17",
            "time": "07:17",
            "timezone": _local_tz(),
            "osTaskInstalled": False,
        },
        "engagement": {
            "trustLevel": "established",
            "deviceId": str(uuid4()),
        },
        "language": {
            "comment": lang, "digest": lang, "feedback": lang, "stored": lang,
        },
        "trustGates": {
            "read_feed": "new",
            "auto_like": "new",
            "auto_collect": "new",
            "auto_comment": "established",
            "auto_reply": "established",
            "auto_comment_like": "established",
            "heartbeat_scan": "established",
            "hf_publish": "trusted_with_user_approval",
            "hf_upvote": "trusted_with_user_approval",
            "persona_auto_evolve": "trusted",
        },
        "trustThresholds": {
            "newAgeDays": 1,
            "trustedAgeDays": 7,
            "trustedScoreMin": 5.0,
            "scoreWeights": {
                "commentsPosted": 1.0,
                "repliesPosted": 1.0,
                "postLikes": 0.1,
                "postCollects": 0.3,
                "commentLikes": 0.05,
            },
        },
        "sourceTag": "external_research_agent:daily_digest",
        "skipDisplayLimit": 10,
        "hfTopN": 10,
    }
    write_json_secure(home / "policy.json", policy)
    print(f"  ✓ policy saved → {home / 'policy.json'}")
    return policy


def step_init_persona(home: Path, user_id: int | str, username: str,
                      email: str) -> None:
    print("\n[step] init persona.json")
    persona = {
        "userId": str(user_id),
        "username": username,
        "email": email,
        "preferred_concepts": [],
        "accepted_paper_ids": [],
        "rejected_paper_ids": [],
        "rejected_titles": [],
        "rejected_paper_types": [],
        "rejected_keywords": [],
        "rejected_styles": [],
        "research_values": ["evidence-grounding", "reproducibility", "mechanism"],
        "open_questions": [],
        "trajectory": [],
        "feedback_history": [],
        "seen_paper_ids": [],
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_json_secure(home / "persona.json", persona)
    print(f"  ✓ persona saved → {home / 'persona.json'}")


def step_init_states(home: Path, user_id: int | str, username: str,
                     email: str, trust_level: str = "established") -> None:
    now = datetime.now(timezone.utc).isoformat()
    engagement = {
        "schemaVersion": 1,
        "userId": user_id,
        "username": username,
        "email": email,
        "firstSeenAt": now,
        "trustLevel": trust_level,
        "trustScore": 0,
        "trustUpgradeAt": now if trust_level != "new" else None,
        "trustHistory": [{"at": now, "level": trust_level, "reason": "bootstrap"}],
        "activity": {
            "lifetime": {},
            "rolling7d": {},
            "rolling30d": {},
            "today": {},
            "todayDate": datetime.now(timezone.utc).date().isoformat(),
        },
        "rateLimits": {},
        "lastActions": {},
    }
    interaction = {
        "schemaVersion": 1,
        "replied_comment_ids": [],
        "liked_comment_ids": [],
        "processed_comment_ids": [],
        "commented_paper_ids": [],
        "updatedAt": now,
    }
    write_json_secure(home / "engagement_state.json", engagement)
    write_json_secure(home / "interaction_state.json", interaction)
    (home / "runs").mkdir(parents=True, exist_ok=True)


def step_offer_dry_run(home: Path) -> None:
    print("\n[step] run a dry-run to verify setup")
    if prompt("  Run daily_runner.py dry-run now?", default="y").lower() not in ("y", "yes"):
        print("  (skipped; run it later with: python scripts/daily_runner.py dry-run)")
        return
    try:
        __import__("requests")
    except ImportError:
        print("  [fail] missing dependency: requests")
        print("         run: python -m pip install -r requirements.txt")
        return
    runner = Path(__file__).parent / "daily_runner.py"
    if not runner.exists():
        print(f"  ✗ daily_runner.py not found at {runner}")
        return
    print(f"  → running {runner} dry-run ...")
    rc = subprocess.run([sys.executable, str(runner), "dry-run"],
                        env={**os.environ, "ARXICLAW_AGENT_HOME": str(home)}).returncode
    if rc == 0:
        from datetime import datetime
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        digest = home / "runs" / f"{today}-dry-run" / "daily_digest.zh-CN.md"
        if not digest.exists():
            digest_en = home / "runs" / f"{today}-dry-run" / "daily_digest.en-US.md"
            if digest_en.exists():
                digest = digest_en
        print(f"  ✓ digest: {digest}")
    else:
        print(f"  ✗ dry-run exited with code {rc}")


def step_offer_schedule(home: Path) -> None:
    print("\n[step] register scheduled task")
    if prompt("  Register daily 07:17 auto-run?", default="y").lower() not in ("y", "yes"):
        print("  (skipped; run later: python scripts/install_schedule.py)")
        return
    installer = Path(__file__).parent / "install_schedule.py"
    if not installer.exists():
        print(f"  ✗ install_schedule.py not found at {installer}")
        return
    rc = subprocess.run([sys.executable, str(installer)],
                        env={**os.environ, "ARXICLAW_AGENT_HOME": str(home)}).returncode
    if rc == 0:
        # mark enabled in policy
        policy_path = home / "policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy.setdefault("schedule", {})["enabled"] = True
        write_json_secure(policy_path, policy)
        print("  ✓ schedule registered, policy.schedule.enabled = true")


def _local_tz() -> str:
    try:
        import time as _t
        name = _t.tzname[0] or "UTC"
        # common Windows TZ names → IANA
        mapping = {
            "中国标准时间": "Asia/Shanghai",
            "China Standard Time": "Asia/Shanghai",
            "Pacific Standard Time": "America/Los_Angeles",
        }
        return mapping.get(name, name)
    except Exception:
        return "UTC"


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="arxiclaw one-shot bootstrap")
    ap.add_argument("--reset", action="store_true",
                    help="delete local credentials before starting")
    ap.add_argument("--non-interactive", action="store_true",
                    help="for agent use; reads from env vars / stdin")
    ap.add_argument("--allow-pasted-api-key", action="store_true",
                    help="allow direct API key input after caller has accepted the risk")
    ap.add_argument("--api-key-source",
                    help="API key source for non-interactive mode: env var, file path, '-' stdin, or direct key")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    home = agent_home()

    print("=" * 60)
    print("  arxiclaw external research agent — bootstrap")
    print("=" * 60)
    print(f"  base URL: {BASE_URL}")
    print(f"  default agent home: {home}")
    print()

    method = prompt_choice(
        "Connect account: A=email code, B=import website API key",
        ["a", "b"], default="a",
    )

    email = ""
    username = ""
    key_name = "heartbeat-agent"
    payload: dict
    if method == "a":
        email = prompt("Your email (for API key bootstrap)")
        if not EMAIL_RE.match(email):
            print(f"  ✗ invalid email: {email}")
            return 2
        step_send_code(email)
        ticket = step_verify_code(email)
        username = prompt("Username (optional, can be empty)", required=False)
        key_name = prompt("API key name", default="heartbeat-agent")
        payload = step_bootstrap(ticket, username, key_name)
    else:
        location = args.api_key_source
        if not location:
            location = prompt(
                "API key file path, environment variable name, '-' for stdin, or pasted key"
            )
        api_key = read_api_key_from_location(
            location,
            allow_pasted_api_key=args.allow_pasted_api_key,
            non_interactive=args.non_interactive,
        )
        payload = verify_api_key(api_key)
        user = payload.get("user") or {}
        username = user.get("username") or ""
        email = user.get("email") or ""

    home = choose_agent_home(home)
    if args.reset and home.exists():
        for name in ("credentials.json", "policy.json", "persona.json",
                     "engagement_state.json", "interaction_state.json"):
            p = home / name
            if p.exists():
                p.unlink()
                print(f"[reset] removed {p}")
    home.mkdir(parents=True, exist_ok=True)

    if (home / "credentials.json").exists():
        creds = json.loads((home / "credentials.json").read_text(encoding="utf-8"))
        print("[info] credentials.json already exists.")
        print(f"  user: {creds.get('username')} (id={creds.get('userId')})")
        print(f"  key prefix: {creds.get('keyPrefix')}")
        if prompt("  Re-bootstrap (this will overwrite)?", default="n").lower() not in ("y", "yes"):
            print("[exit] existing credentials preserved")
            return 0
        (home / "credentials.json").unlink()

    creds = step_save_credentials(home, BASE_URL, email, username, key_name, payload)
    user = payload.get("user") or {}
    step_init_persona(home, creds.get("userId"), creds.get("username") or username, email)
    step_init_states(home, creds.get("userId"), creds.get("username") or username, email)

    # 7. set interests
    access_token = payload.get("accessToken")
    if not access_token:
        # exchange apiKey for access token
        r = post("/api/auth/token", {"grantType": "api_key", "apiKey": creds["apiKey"]})
        access_token = r.get("accessToken")
    interests = step_set_interests(access_token, creds["userId"])

    # 8. update persona.preferred_concepts from chosen interests
    persona = json.loads((home / "persona.json").read_text(encoding="utf-8"))
    persona["preferred_concepts"] = [i.lower() for i in interests]
    write_json_secure(home / "persona.json", persona)

    digest_limit_raw = prompt("Daily digest paper limit", default="20")
    try:
        digest_limit = max(1, int(digest_limit_raw))
    except ValueError:
        digest_limit = 20

    schedule_mode = prompt_choice(
        "Heartbeat schedule mode A=resident B=daily C=both D=manual",
        ["a", "b", "c", "d"], default="c",
    ).upper()

    # 9. language
    lang = prompt_choice("Comment / digest language", list(SUPPORTED_LANGS),
                         default="zh-CN")

    # 10. auto actions
    allow_like = prompt("Enable auto-like? (y/n)", default="y").lower().startswith("y")
    allow_collect = prompt("Enable auto-collect? (y/n)", default="y").lower().startswith("y")
    allow_comment = prompt("Enable auto-comment? (y/n)", default="y").lower().startswith("y")
    allow_reply = prompt("Enable auto-reply in discussions? (y/n)",
                         default="y").lower().startswith("y")
    allow_comment_like = prompt("Enable auto-like on others' comments? (y/n)",
                                default="y").lower().startswith("y")
    max_comments_raw = prompt("Max comments per daily run", default="20")
    try:
        max_comments = int(max_comments_raw)
    except ValueError:
        max_comments = 20

    # 11. write policy
    step_init_policy(home, lang, allow_like, allow_collect, allow_comment,
                     allow_reply, allow_comment_like, max_comments,
                     digest_limit=digest_limit, schedule_mode=schedule_mode)

    # 12. offer dry-run
    step_offer_dry_run(home)

    # 13. offer schedule
    step_offer_schedule(home)

    # final summary
    print()
    print("=" * 60)
    print("  ✅ Bootstrap complete")
    print("=" * 60)
    print(f"  📁 Agent home: {home}")
    print(f"  🔑 API Key prefix: {creds['keyPrefix']}    (do not share)")
    print(f"  👤 User: {creds['username']} (id={creds['userId']}) {creds['email']}")
    print(f"  🎯 Interests: {', '.join(interests)}")
    print(f"  🌐 Language: comment={lang} digest={lang} feedback={lang} stored={lang}")
    print("  📜 Files:")
    print(f"     {home / 'credentials.json'}")
    print(f"     {home / 'policy.json'}")
    print(f"     {home / 'persona.json'}")
    print()
    print("  Next: re-run with `python scripts/daily_runner.py`, or")
    print("        just say '用 arxiclaw 跑今日论文' to your agent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
