"""Engagement state + trust level + rate limiting for arxiclaw agent.

This is the **client-side** trust system. arxiclaw platform does not (yet)
expose a trust field, so we compute it locally based on:

- Account age: time since firstSeenAt
- Engagement score: weighted count of meaningful actions

Three trust levels:
  - new:         < 24h since firstSeenAt
  - established: 24h <= age < 7d OR score < 5
  - trusted:     age >= 7d AND score >= 5

Rate limit matrix (per action × per trust level) is defined in
`RATE_LIMITS` below. Check `can_act()` before any platform write.

Public API:
  - load_engagement(home) -> dict
  - save_engagement(home, state)
  - trust_level(state) -> str
  - trust_score(state) -> float
  - can_act(state, action) -> (bool, reason, wait_seconds)
  - record_action(state, action, ...) -> None
  - can_perform(policy, capability, trust, user_approved=False) -> (bool, reason)
  - upgrade_trust_if_eligible(state, reason) -> bool
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --- trust level numeric order ---
TRUST_ORDER = {"new": 0, "established": 1, "trusted": 2}
TRUST_NAMES = list(TRUST_ORDER.keys())

# --- score weights (must mirror policy.trustThresholds.scoreWeights) ---
# Keys match lifetime activity counter names exactly.
SCORE_WEIGHTS = {
    "commentsPosted": 1.0,
    "repliesPosted":  1.0,
    "postLikes":      0.1,
    "postCollects":   0.3,
    "commentLikes":   0.05,
}

# --- rate limit per action × trust level ---
# values: (per_minute, per_day)
RATE_LIMITS: dict[str, dict[str, tuple[int, int]]] = {
    "comment":     {"new": (1, 5),    "established": (3, 20),   "trusted": (6, 50)},
    "reply":       {"new": (1, 10),   "established": (30, 50),  "trusted": (60, 100)},
    "commentLike": {"new": (5, 30),   "established": (10, 100), "trusted": (20, 200)},
    "postLike":    {"new": (10, 50),  "established": (20, 200), "trusted": (50, 500)},
    "postCollect": {"new": (5, 20),   "established": (10, 100), "trusted": (20, 200)},
    "discover":    {"new": (60, 500), "established": (60, 500), "trusted": (60, 500)},
}

# --- action -> engagement_state.counter key ---
ACTION_TO_COUNTER = {
    "comment":     "commentsPosted",
    "reply":       "repliesPosted",
    "commentLike": "commentLikes",
    "postLike":    "postLikes",
    "postCollect": "postCollects",
    "discover":    "postsViewed",
}


# ---------- paths ----------

def agent_home() -> Path:
    configured = os.getenv("ARXICLAW_AGENT_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.environ["USERPROFILE"]) / ".arxiclaw"
    return Path.home() / ".arxiclaw"


def _engagement_path(home: Path) -> Path:
    return home / "engagement_state.json"


# ---------- load / save ----------

def default_state(user_id: int | None = None,
                 username: str = "",
                 email: str = "") -> dict[str, Any]:
    """Build a fresh state dict. Called when engagement_state.json is missing."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schemaVersion": 1,
        "userId": user_id,
        "username": username,
        "email": email,
        "firstSeenAt": now,
        "trustLevel": "new",
        "trustUpgradeAt": None,
        "trustHistory": [{"at": now, "level": "new", "reason": "initial"}],
        "activity": {
            "lifetime":  _empty_activity(),
            "rolling7d": _empty_activity(),
            "rolling30d":_empty_activity(),
            "today":     _empty_activity(),
        },
        "rateLimits": _empty_rate_limits(),
        "lastActions": _empty_last_actions(),
    }


def _empty_activity() -> dict[str, int]:
    return {
        "commentsPosted": 0,
        "repliesPosted": 0,
        "commentLikes": 0,
        "postLikes": 0,
        "postCollects": 0,
        "postsViewed": 0,
        "activeDays": 0,
    }


def _empty_rate_limits() -> dict[str, dict[str, Any]]:
    """Per action × {used, limit (per_day or per_min window), resetAt/windowStart}."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        # per-day counters (reset at UTC midnight)
        "commentsPerDay":     {"used": 0, "limit": 0, "resetAt": _next_utc_midnight_iso()},
        "repliesPerDay":      {"used": 0, "limit": 0, "resetAt": _next_utc_midnight_iso()},
        "commentLikesPerDay": {"used": 0, "limit": 0, "resetAt": _next_utc_midnight_iso()},
        "postLikesPerDay":    {"used": 0, "limit": 0, "resetAt": _next_utc_midnight_iso()},
        "postCollectsPerDay": {"used": 0, "limit": 0, "resetAt": _next_utc_midnight_iso()},
        # per-minute rolling windows
        "commentsPerMin":      {"used": 0, "limit": 0, "windowStart": now_iso},
        "repliesPerMin":       {"used": 0, "limit": 0, "windowStart": now_iso},
        "commentLikesPerMin":  {"used": 0, "limit": 0, "windowStart": now_iso},
        "postLikesPerMin":     {"used": 0, "limit": 0, "windowStart": now_iso},
        "postCollectsPerMin":  {"used": 0, "limit": 0, "windowStart": now_iso},
    }


def _empty_last_actions() -> dict[str, str | None]:
    return {
        "lastCommentAt":  None,
        "lastReplyAt":    None,
        "lastLikeAt":     None,
        "lastCollectAt":  None,
        "lastViewAt":     None,
    }


def load_engagement(home: Path) -> dict[str, Any]:
    """Load engagement state; auto-create if missing. Also rolls over
    today/rolling windows if needed and syncs rate-limit bounds to
    the current trust tier."""
    path = _engagement_path(home)
    if not path.exists():
        state = default_state()
    else:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[warn] engagement_state.json unreadable ({exc}); reset",
                  file=__import__("sys").stderr, flush=True)
            state = default_state()
    _rollover_windows(state)
    # sync rate limit bounds to the persisted trust level
    _sync_rate_limit_bounds(state, state.get("trustLevel", "new"))
    return state


def save_engagement(home: Path, state: dict[str, Any]) -> None:
    state["schemaVersion"] = 1
    state.setdefault("trustHistory", [])
    path = _engagement_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    try:
        if os.name != "nt":
            os.chmod(path, 0o600)
    except OSError:
        pass


def _rollover_windows(state: dict[str, Any]) -> None:
    """Reset today counter at local midnight; trim rolling windows.

    Note: state dict is mutated in place.
    """
    now = datetime.now(timezone.utc)
    today_date = now.date().isoformat()
    today_marker = state["activity"].get("todayDate")
    if today_marker != today_date:
        # rollover today
        state["activity"]["today"] = _empty_activity()
        state["activity"]["todayDate"] = today_date
        # reset per-day counters
        next_midnight = _next_utc_midnight_iso()
        for k in ("commentsPerDay", "repliesPerDay", "commentLikesPerDay",
                  "postLikesPerDay", "postCollectsPerDay"):
            if k in state["rateLimits"]:
                state["rateLimits"][k]["used"] = 0
                state["rateLimits"][k]["resetAt"] = next_midnight
    # rolling windows: we keep rolling7d/rolling30d in sync via simple
    # snapshot update on each record_action(); here we just ensure keys exist


def _next_utc_midnight_iso() -> str:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0,
                                                    second=0, microsecond=0)
    return tomorrow.isoformat()


# ---------- trust ----------

def trust_score(state: dict[str, Any]) -> float:
    """Compute engagement score from lifetime counters using SCORE_WEIGHTS."""
    lifetime = state.get("activity", {}).get("lifetime", {})
    score = 0.0
    for action, weight in SCORE_WEIGHTS.items():
        score += lifetime.get(action, 0) * weight
    return round(score, 2)


def trust_level(state: dict[str, Any],
                thresholds: dict[str, Any] | None = None) -> str:
    """Return new/established/trusted based on age + score.

    thresholds dict (optional) mirrors policy.trustThresholds:
      - newAgeDays (default 1)
      - trustedAgeDays (default 7)
      - trustedScoreMin (default 5.0)
    """
    t = thresholds or {}
    new_age = t.get("newAgeDays", 1)
    trusted_age = t.get("trustedAgeDays", 7)
    trusted_score = t.get("trustedScoreMin", 5.0)

    first_seen = state.get("firstSeenAt")
    if not first_seen:
        return "new"
    try:
        first_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "new"
    now = datetime.now(timezone.utc)
    age_days = (now - first_dt).total_seconds() / 86400.0
    score = trust_score(state)

    if age_days < new_age:
        return "new"
    if age_days < trusted_age or score < trusted_score:
        return "established"
    return "trusted"


def sync_state_to_trust(state: dict[str, Any]) -> None:
    """Force `rateLimits[...].limit` to match the **persisted** trustLevel.

    Use this:
      - on every can_act() / record_action() entry to ensure limits are
        always consistent with the current trust tier
      - after load_engagement() (already done there)
      - after set_trust() (already done there)
    """
    _sync_rate_limit_bounds(state, state.get("trustLevel", "new"))


def upgrade_trust_if_eligible(state: dict[str, Any],
                              thresholds: dict[str, Any] | None = None,
                              reason: str = "") -> bool:
    """Re-evaluate trust level from age+score. If the auto-recomputed
    level is HIGHER than the persisted level, upgrade. After upgrade,
    sync rate-limit bounds to the new level.

    NOTE: This function does NOT auto-demote a manually-set level.
    Use set_trust() for explicit downgrades.

    Returns True if upgraded.
    """
    new_level = trust_level(state, thresholds)
    old_level = state.get("trustLevel", "new")
    if TRUST_ORDER[new_level] <= TRUST_ORDER[old_level]:
        return False
    state["trustLevel"] = new_level
    _sync_rate_limit_bounds(state, new_level)
    state["trustUpgradeAt"] = datetime.now(timezone.utc).isoformat()
    if not reason:
        if thresholds:
            reason = (f"age>=7d & score>={thresholds.get('trustedScoreMin', 5.0)}"
                      if new_level == "trusted"
                      else f"age>=24h & score<{thresholds.get('trustedScoreMin', 5.0)}")
        else:
            reason = "auto"
    state.setdefault("trustHistory", []).append({
        "at": state["trustUpgradeAt"],
        "level": new_level,
        "reason": reason,
    })
    return True


def _sync_rate_limit_bounds(state: dict[str, Any], trust: str) -> None:
    """Set `limit` fields in rateLimits to match the trust tier's RATE_LIMITS."""
    if trust not in ("new", "established", "trusted"):
        return
    rate = state.setdefault("rateLimits", {})
    for action, tiers in RATE_LIMITS.items():
        if trust not in tiers:
            continue
        per_min_limit, per_day_limit = tiers[trust]
        day_key = _per_day_key(action)
        if day_key in rate:
            rate[day_key]["limit"] = per_day_limit
        min_key = _per_min_key(action)
        if min_key in rate:
            rate[min_key]["limit"] = per_min_limit


def set_trust(state: dict[str, Any], level: str, reason: str) -> bool:
    """Manually set trust level (user override). Returns True if changed."""
    if level not in TRUST_ORDER:
        return False
    old = state.get("trustLevel", "new")
    if old == level:
        return False
    state["trustLevel"] = level
    state["trustUpgradeAt"] = datetime.now(timezone.utc).isoformat()
    state.setdefault("trustHistory", []).append({
        "at": state["trustUpgradeAt"],
        "level": level,
        "reason": f"manual:{reason}" if reason else "manual",
        "fromLevel": old,
    })
    return True


# ---------- rate limit ----------

def _per_day_key(action: str) -> str:
    return {
        "comment":     "commentsPerDay",
        "reply":       "repliesPerDay",
        "commentLike": "commentLikesPerDay",
        "postLike":    "postLikesPerDay",
        "postCollect": "postCollectsPerDay",
    }.get(action, f"{action}PerDay")


def _per_min_key(action: str) -> str:
    return {
        "comment":     "commentsPerMin",
        "reply":       "repliesPerMin",
        "commentLike": "commentLikesPerMin",
        "postLike":    "postLikesPerMin",
        "postCollect": "postCollectsPerMin",
    }.get(action, f"{action}PerMin")


def _summary_day_key(action: str) -> str:
    """User-facing key in /home rateLimits output (e.g. 'commentPerDay')."""
    return action + "PerDay"


def _summary_min_key(action: str) -> str:
    return action + "PerMin"


def can_act(state: dict[str, Any], action: str,
            trust: str | None = None) -> tuple[bool, str, int]:
    """Check if `action` is allowed under current rate limits.

    Returns (ok, reason, wait_seconds).
    - ok=True means "go ahead and call platform API"
    - ok=False means "skip, log reason"
    - wait_seconds: 0 if ok, else seconds until limit resets
    """
    if action not in RATE_LIMITS:
        return (False, f"unknown_action:{action}", 0)
    if trust is None:
        trust = state.get("trustLevel", "new")
    if trust not in RATE_LIMITS[action]:
        return (False, f"unknown_trust:{trust}", 0)
    sync_state_to_trust(state)  # ensure limits match current trust
    per_min_limit, per_day_limit = RATE_LIMITS[action][trust]
    rate = state["rateLimits"]

    # per-day check
    day_key = _per_day_key(action)
    day = rate.get(day_key, {"used": 0, "limit": per_day_limit, "resetAt": _next_utc_midnight_iso()})
    if day["limit"] != per_day_limit:
        day["limit"] = per_day_limit
    if day["used"] >= per_day_limit:
        # compute wait
        try:
            reset_dt = datetime.fromisoformat(day["resetAt"].replace("Z", "+00:00"))
            wait = max(0, int((reset_dt - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, AttributeError):
            wait = 3600
        return (False, f"daily_limit:{action}:{per_day_limit}", wait)

    # per-minute check (rolling window)
    min_key = _per_min_key(action)
    minute = rate.get(min_key, {"used": 0, "limit": per_min_limit, "windowStart": datetime.now(timezone.utc).isoformat()})
    if minute["limit"] != per_min_limit:
        minute["limit"] = per_min_limit
    # if window expired, reset
    try:
        win_start_dt = datetime.fromisoformat(minute["windowStart"].replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - win_start_dt).total_seconds()
        if elapsed >= 60:
            minute["used"] = 0
            minute["windowStart"] = datetime.now(timezone.utc).isoformat()
    except (ValueError, AttributeError):
        minute["used"] = 0
        minute["windowStart"] = datetime.now(timezone.utc).isoformat()
    if minute["used"] >= per_min_limit:
        try:
            win_start_dt = datetime.fromisoformat(minute["windowStart"].replace("Z", "+00:00"))
            wait = max(0, 60 - int((datetime.now(timezone.utc) - win_start_dt).total_seconds()))
        except (ValueError, AttributeError):
            wait = 60
        return (False, f"per_minute_limit:{action}:{per_min_limit}", wait)
    return (True, "", 0)


def record_action(state: dict[str, Any], action: str,
                  paper_id: int | None = None,
                  comment_id: str | None = None,
                  parent_id: str | None = None,
                  iso_now: str | None = None) -> None:
    """Record an action: bump rate-limit counters, lifetime/7d/30d/today
    activity, and lastActions timestamp. Mutates state in place."""
    if action not in RATE_LIMITS:
        return
    sync_state_to_trust(state)
    now_iso = iso_now or datetime.now(timezone.utc).isoformat()
    rate = state["rateLimits"]

    # rate limit counters
    day_key = _per_day_key(action)
    if day_key in rate:
        rate[day_key]["used"] = rate[day_key].get("used", 0) + 1
    min_key = _per_min_key(action)
    if min_key in rate:
        rate[min_key]["used"] = rate[min_key].get("used", 0) + 1

    # activity counters
    counter = ACTION_TO_COUNTER.get(action)
    if counter:
        for window in ("lifetime", "rolling7d", "rolling30d", "today"):
            bucket = state["activity"].get(window, {})
            bucket[counter] = bucket.get(counter, 0) + 1
        # activeDays: track unique days in lifetime (approximate)
        today = datetime.now(timezone.utc).date().isoformat()
        active_days = state["activity"]["lifetime"].get("activeDays", 0)
        if state["activity"]["lifetime"].get("lastActiveDate") != today:
            state["activity"]["lifetime"]["activeDays"] = active_days + 1
            state["activity"]["lifetime"]["lastActiveDate"] = today

    # lastActions
    last = state.setdefault("lastActions", _empty_last_actions())
    action_to_last = {
        "comment":     "lastCommentAt",
        "reply":       "lastReplyAt",
        "postLike":    "lastLikeAt",
        "postCollect": "lastCollectAt",
        "discover":    "lastViewAt",
    }
    last_key = action_to_last.get(action)
    if last_key:
        last[last_key] = now_iso


# ---------- trust gates (capability -> required trust) ----------

def can_perform(policy: dict[str, Any], capability: str,
                trust: str, user_approved: bool = False
                ) -> tuple[bool, str]:
    """Check if `capability` is allowed under current trust level.

    Reads policy.trustGates which maps capability -> required trust
    (optionally with "_with_user_approval" suffix).

    Returns (ok, reason).
    """
    gates = policy.get("trustGates", {}) or {}
    required = gates.get(capability)
    if required is None:
        return (False, f"unknown_capability:{capability}")
    needs_approval = False
    if "_with_user_approval" in required:
        needs_approval = True
        required_clean = required.replace("_with_user_approval", "").strip()
    else:
        required_clean = required
    if required_clean not in TRUST_ORDER:
        return (False, f"bad_required_trust:{required}")
    if needs_approval and not user_approved:
        return (False, "user_approval_required")
    if TRUST_ORDER[trust] < TRUST_ORDER[required_clean]:
        return (False, f"trust_too_low:{required_clean}")
    return (True, "")


# ---------- /home integration ----------

def summarize_for_home(state: dict[str, Any],
                      policy: dict[str, Any] | None = None
                      ) -> dict[str, Any]:
    """Return the 'yourAccount' + 'rateLimits' blocks for /home JSON output."""
    trust = state.get("trustLevel", "new")
    lifetime = state["activity"].get("lifetime", {})
    today = state["activity"].get("today", {})
    rate = state["rateLimits"]
    out = {
        "userId": state.get("userId"),
        "username": state.get("username", ""),
        "trustLevel": trust,
        "trustScore": trust_score(state),
        "firstSeenAt": state.get("firstSeenAt"),
        "lifetime": {
            "commentsPosted":  lifetime.get("commentsPosted", 0),
            "repliesPosted":   lifetime.get("repliesPosted", 0),
            "postLikes":       lifetime.get("postLikes", 0),
            "postCollects":    lifetime.get("postCollects", 0),
            "commentLikes":    lifetime.get("commentLikes", 0),
            "postsViewed":     lifetime.get("postsViewed", 0),
            "activeDays":      lifetime.get("activeDays", 0),
        },
        "today": {
            "commentsPosted":  today.get("commentsPosted", 0),
            "repliesPosted":   today.get("repliesPosted", 0),
            "postLikes":       today.get("postLikes", 0),
            "postCollects":    today.get("postCollects", 0),
        },
        "rateLimits": {},
        "lastActions": state.get("lastActions", {}),
    }
    # compact rate limit view
    for action in ("comment", "reply", "commentLike", "postLike", "postCollect"):
        day_key = _per_day_key(action)
        rl = rate.get(day_key, {})
        min_key = _per_min_key(action)
        per_min = rate.get(min_key, {})
        if trust in RATE_LIMITS.get(action, {}):
            per_min_limit, per_day_limit = RATE_LIMITS[action][trust]
        else:
            per_min_limit, per_day_limit = 0, 0
        out["rateLimits"][_summary_day_key(action)] = {
            "used":  rl.get("used", 0),
            "limit": per_day_limit,
            "resetAt": rl.get("resetAt"),
        }
        out["rateLimits"][_summary_min_key(action)] = {
            "used":  per_min.get("used", 0),
            "limit": per_min_limit,
        }
    return out
