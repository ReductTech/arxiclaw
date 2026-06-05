"""Unit tests for engagement.py — trust + rate limit logic.

Run: pytest tests/test_engagement.py -v

These tests do NOT call any platform API. They test the pure state-machine
logic of trust level transitions and rate limit bookkeeping.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import engagement as eng


# ---------- fixtures ----------

def _fresh_state(user_id: int = 1, username: str = "alice"):
    s = eng.default_state(user_id=user_id, username=username, email=f"{username}@example.com")
    return s


def _backdate(state: dict, **delta) -> dict:
    """Backdate firstSeenAt by the given timedelta kwargs (days=, hours=)."""
    state["firstSeenAt"] = (
        datetime.now(timezone.utc)
        - timedelta(**delta)
    ).isoformat()
    return state


def _set_trust(state: dict, level: str) -> dict:
    state["trustLevel"] = level
    eng.sync_state_to_trust(state)
    return state


# ---------- default state ----------

def test_default_state_has_new_trust():
    s = _fresh_state()
    assert s["trustLevel"] == "new"
    assert s["activity"]["lifetime"]["commentsPosted"] == 0
    assert s["rateLimits"]["commentsPerDay"]["used"] == 0


def test_default_state_has_required_keys():
    s = _fresh_state()
    for k in ("userId", "username", "firstSeenAt", "trustLevel", "trustHistory",
              "activity", "rateLimits", "lastActions"):
        assert k in s, f"missing key: {k}"


# ---------- trust score ----------

def test_trust_score_zero_on_fresh():
    s = _fresh_state()
    assert eng.trust_score(s) == 0.0


def test_trust_score_uses_only_lifetime_counters():
    s = _fresh_state()
    s["activity"]["today"]["commentsPosted"] = 100  # shouldn't count
    s["activity"]["lifetime"]["commentsPosted"] = 5
    s["activity"]["lifetime"]["repliesPosted"] = 2
    # score = 5*1 + 2*1 = 7
    assert eng.trust_score(s) == 7.0


def test_trust_score_weights_match_constants():
    s = _fresh_state()
    s["activity"]["lifetime"]["commentsPosted"] = 100
    s["activity"]["lifetime"]["repliesPosted"] = 100
    s["activity"]["lifetime"]["postLikes"] = 100
    s["activity"]["lifetime"]["postCollects"] = 100
    s["activity"]["lifetime"]["commentLikes"] = 100
    expected = (
        100 * eng.SCORE_WEIGHTS["commentsPosted"]
        + 100 * eng.SCORE_WEIGHTS["repliesPosted"]
        + 100 * eng.SCORE_WEIGHTS["postLikes"]
        + 100 * eng.SCORE_WEIGHTS["postCollects"]
        + 100 * eng.SCORE_WEIGHTS["commentLikes"]
    )
    assert eng.trust_score(s) == round(expected, 2)


# ---------- trust level transitions ----------

def test_trust_level_stays_new_under_24h():
    s = _backdate(_fresh_state(), hours=23)
    assert eng.trust_level(s) == "new"


def test_trust_level_promotes_at_exactly_24h():
    s = _backdate(_fresh_state(), hours=24)
    assert eng.trust_level(s) == "established"


def test_trust_level_stays_established_at_7d_with_low_score():
    s = _backdate(_fresh_state(), days=8)
    # No score
    assert eng.trust_score(s) < 5
    assert eng.trust_level(s) == "established"


def test_trust_level_becomes_trusted_at_7d_with_score_5():
    s = _backdate(_fresh_state(), days=8)
    s["activity"]["lifetime"]["commentsPosted"] = 10
    # score = 10*1 = 10 >= 5
    assert eng.trust_score(s) >= 5
    assert eng.trust_level(s) == "trusted"


def test_trust_level_custom_thresholds():
    s = _backdate(_fresh_state(), hours=12)
    thresholds = {"newAgeDays": 0.5, "trustedAgeDays": 1, "trustedScoreMin": 3.0}
    # age=0.5 days > newAgeDays=0.5 -> wait, == boundary, < not <=
    # 12h = 0.5d, age < 0.5 is False, so promoted
    assert eng.trust_level(s, thresholds) in ("established", "trusted")


# ---------- upgrade / downgrade ----------

def test_upgrade_trust_from_new_to_established():
    s = _backdate(_fresh_state(), hours=25)
    upgraded = eng.upgrade_trust_if_eligible(s)
    assert upgraded is True
    assert s["trustLevel"] == "established"
    assert s["trustHistory"][-1]["level"] == "established"


def test_upgrade_trust_does_not_demote():
    s = _set_trust(_fresh_state(), "trusted")
    s["trustHistory"]  # ensure exists
    was_level = s["trustLevel"]
    # backdate but keep low score
    s = _backdate(s, days=1)
    s["activity"]["lifetime"]["commentsPosted"] = 0
    upgraded = eng.upgrade_trust_if_eligible(s)
    # trust_score = 0 < 5, age=1 < 7 -> recomputed level would be 'established'
    # but persisted level is 'trusted', which is HIGHER, so no downgrade
    assert upgraded is False
    assert s["trustLevel"] == "trusted"


def test_set_trust_records_history():
    s = _set_trust(_fresh_state(), "established")
    eng.set_trust(s, "trusted", reason="I'm the owner")
    assert s["trustLevel"] == "trusted"
    last = s["trustHistory"][-1]
    assert last["level"] == "trusted"
    assert "manual" in last["reason"]
    assert last.get("fromLevel") == "established"


def test_set_trust_to_same_level_is_noop():
    s = _set_trust(_fresh_state(), "established")
    before = len(s["trustHistory"])
    eng.set_trust(s, "established", reason="redundant")
    assert s["trustLevel"] == "established"
    assert len(s["trustHistory"]) == before


# ---------- rate limit: per-day ----------

def test_can_act_blocks_after_daily_limit_established():
    s = _set_trust(_fresh_state(), "established")
    s["rateLimits"]["commentsPerDay"]["used"] = 20  # new established limit is 20
    ok, reason, _ = eng.can_act(s, "comment")
    assert not ok
    assert "daily_limit" in reason
    assert "20" in reason


def test_can_act_blocks_after_daily_limit_new():
    s = _set_trust(_fresh_state(), "new")
    s["rateLimits"]["commentsPerDay"]["used"] = 5  # new tier limit is 5
    ok, reason, _ = eng.can_act(s, "comment")
    assert not ok
    assert "daily_limit" in reason


def test_can_act_trusted_higher_limit():
    s = _set_trust(_fresh_state(), "trusted")
    s["rateLimits"]["commentsPerDay"]["used"] = 49  # below 50
    ok, _, _ = eng.can_act(s, "comment")
    assert ok


# ---------- rate limit: per-minute ----------

def test_can_act_blocks_after_per_minute_limit():
    s = _set_trust(_fresh_state(), "established")
    s["rateLimits"]["commentsPerMin"]["used"] = 3  # established per-min is 3
    ok, reason, _ = eng.can_act(s, "comment")
    assert not ok
    assert "per_minute_limit" in reason


def test_can_act_resets_per_minute_window_after_60s():
    s = _set_trust(_fresh_state(), "established")
    s["rateLimits"]["commentsPerMin"]["used"] = 3
    # Backdate windowStart to 61s ago
    s["rateLimits"]["commentsPerMin"]["windowStart"] = (
        datetime.now(timezone.utc) - timedelta(seconds=61)
    ).isoformat()
    ok, _, _ = eng.can_act(s, "comment")
    assert ok


# ---------- rate limit: unknown actions / unknown trust ----------

def test_can_act_unknown_action_rejected():
    s = _fresh_state()
    ok, reason, _ = eng.can_act(s, "magic_action")
    assert not ok
    assert "unknown_action" in reason


def test_can_act_correct_action_per_tier():
    # new tier can do postLike (10/h, 50/d)
    s = _set_trust(_fresh_state(), "new")
    s["rateLimits"]["postLikesPerDay"]["used"] = 50
    ok, reason, _ = eng.can_act(s, "postLike")
    assert not ok
    assert "daily_limit" in reason


# ---------- record_action ----------

def test_record_action_increments_counters():
    s = _set_trust(_fresh_state(), "established")
    before = s["activity"]["lifetime"]["commentsPosted"]
    eng.record_action(s, "comment", paper_id=123)
    assert s["activity"]["lifetime"]["commentsPosted"] == before + 1
    assert s["rateLimits"]["commentsPerDay"]["used"] == 1
    assert s["rateLimits"]["commentsPerMin"]["used"] == 1
    assert s["lastActions"]["lastCommentAt"] is not None


def test_record_action_increments_all_rolling_windows():
    s = _set_trust(_fresh_state(), "established")
    for window in ("lifetime", "rolling7d", "rolling30d", "today"):
        before = s["activity"][window]["commentsPosted"]
        eng.record_action(s, "comment", paper_id=1)
        assert s["activity"][window]["commentsPosted"] == before + 1


def test_record_action_increments_active_days():
    s = _set_trust(_fresh_state(), "established")
    eng.record_action(s, "comment", paper_id=1)
    assert s["activity"]["lifetime"]["activeDays"] == 1
    assert "lastActiveDate" in s["activity"]["lifetime"]


def test_record_action_unknown_action_is_noop():
    s = _set_trust(_fresh_state(), "established")
    before = s["rateLimits"]["commentsPerDay"]["used"]
    eng.record_action(s, "magic_action", paper_id=1)
    assert s["rateLimits"]["commentsPerDay"]["used"] == before


# ---------- can_perform (trust gates) ----------

def test_can_perform_blocks_trust_too_low():
    policy = {"trustGates": {"auto_comment": "established"}}
    ok, reason = eng.can_perform(policy, "auto_comment", "new")
    assert not ok
    assert "trust_too_low" in reason


def test_can_perform_allows_at_or_above_required():
    policy = {"trustGates": {"auto_comment": "established"}}
    ok, _ = eng.can_perform(policy, "auto_comment", "established")
    assert ok
    ok, _ = eng.can_perform(policy, "auto_comment", "trusted")
    assert ok


def test_can_perform_user_approval_required():
    policy = {"trustGates": {"hf_publish": "trusted_with_user_approval"}}
    # trusted but no approval
    ok, reason = eng.can_perform(policy, "hf_publish", "trusted", user_approved=False)
    assert not ok
    assert "user_approval_required" in reason
    # trusted + approved
    ok, _ = eng.can_perform(policy, "hf_publish", "trusted", user_approved=True)
    assert ok


def test_can_perform_unknown_capability_rejected():
    policy = {"trustGates": {"auto_comment": "established"}}
    ok, reason = eng.can_perform(policy, "auto_magic", "trusted")
    assert not ok
    assert "unknown_capability" in reason


def test_can_perform_bad_required_trust_rejected():
    policy = {"trustGates": {"auto_comment": "leviathan"}}
    ok, reason = eng.can_perform(policy, "auto_comment", "trusted")
    assert not ok
    assert "bad_required_trust" in reason


# ---------- summarize_for_home ----------

def test_summarize_for_home_includes_lifetime_and_today():
    s = _set_trust(_fresh_state(), "established")
    s["activity"]["lifetime"]["commentsPosted"] = 42
    s["activity"]["today"]["commentsPosted"] = 3
    summary = eng.summarize_for_home(s)
    assert summary["lifetime"]["commentsPosted"] == 42
    assert summary["today"]["commentsPosted"] == 3
    assert summary["trustLevel"] == "established"


def test_summarize_for_home_includes_rate_limits():
    s = _set_trust(_fresh_state(), "established")
    summary = eng.summarize_for_home(s)
    assert "rateLimits" in summary
    for action in ("comment", "reply", "commentLike", "postLike", "postCollect"):
        assert f"{action}PerDay" in summary["rateLimits"]
        assert f"{action}PerMin" in summary["rateLimits"]


# ---------- save / load roundtrip ----------

def test_save_and_load_roundtrip(tmp_path):
    home = tmp_path
    s = _set_trust(_fresh_state(), "established")
    s["activity"]["lifetime"]["commentsPosted"] = 17
    eng.save_engagement(home, s)

    loaded = eng.load_engagement(home)
    assert loaded["trustLevel"] == "established"
    assert loaded["activity"]["lifetime"]["commentsPosted"] == 17


def test_load_engagement_creates_default_if_missing(tmp_path):
    home = tmp_path
    # No file at home/engagement_state.json
    state = eng.load_engagement(home)
    assert state["trustLevel"] == "new"
    assert state["userId"] is None or state["userId"] == 1


# ---------- /home integration ----------

def test_summarize_for_home_includes_last_actions():
    s = _set_trust(_fresh_state(), "established")
    eng.record_action(s, "comment", paper_id=1)
    summary = eng.summarize_for_home(s)
    assert summary["lastActions"]["lastCommentAt"] is not None
