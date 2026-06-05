"""Unit tests for home.py — /home output builder.

Run: pytest tests/test_home.py -v

These tests use the `state_override` parameter to build_home() to avoid
filesystem dependencies. Each test constructs a synthetic state, calls
build_home(), and asserts on the returned dict structure.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import engagement as eng
import home as home_mod


def _sample_state(user_id: int = 19, username: str = "alice", trust: str = "established"):
    s = eng.default_state(user_id=user_id, username=username,
                          email=f"{username}@example.com")
    s["trustLevel"] = trust
    s["firstSeenAt"] = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()
    s["activity"]["lifetime"]["commentsPosted"] = 5
    s["activity"]["lifetime"]["postLikes"] = 12
    s["activity"]["today"]["commentsPosted"] = 1
    s["activity"]["today"]["postLikes"] = 3
    eng.sync_state_to_trust(s)
    return s


def _build(state, today_date="2026-06-04", tmp_path=None):
    """Helper: call build_home with state_override, return the dict.

    Pass tmp_path if any test wants filesystem-side-effects (none currently do).
    """
    return home_mod.build_home(
        home=tmp_path or Path("/tmp"),
        today_date=today_date,
        token=None, user_id=None, username=None,
        state_override=state,
    )


# ---------- yourAccount block ----------

def test_your_account_block_includes_trust():
    home_data = _build(_sample_state())
    acct = home_data["yourAccount"]
    assert acct["trustLevel"] == "established"
    assert acct["userId"] == 19
    assert acct["username"] == "alice"
    assert acct["lifetime"]["commentsPosted"] == 5
    assert acct["today"]["commentsPosted"] == 1


def test_your_account_includes_last_actions():
    s = _sample_state()
    s["lastActions"]["lastCommentAt"] = "2026-06-04T10:00:00Z"
    home_data = _build(s)
    assert home_data["yourAccount"]["lastActions"]["lastCommentAt"] == "2026-06-04T10:00:00Z"


def test_your_account_includes_rate_limits():
    home_data = _build(_sample_state())
    assert "rateLimits" in home_data["yourAccount"]
    for action in ("comment", "reply", "commentLike", "postLike", "postCollect"):
        assert f"{action}PerDay" in home_data["yourAccount"]["rateLimits"]


def test_your_account_trust_new():
    s = _sample_state(trust="new")
    home_data = _build(s)
    assert home_data["yourAccount"]["trustLevel"] == "new"


def test_your_account_trust_trusted():
    s = _sample_state(trust="trusted")
    home_data = _build(s)
    assert home_data["yourAccount"]["trustLevel"] == "trusted"


# ---------- top-level shape ----------

def test_home_data_top_level_keys():
    home_data = _build(_sample_state())
    assert "yourAccount" in home_data
    assert "whatToDoNext" in home_data
    assert "today" in home_data
    assert "generatedAt" in home_data


def test_today_field_matches_input():
    home_data = _build(_sample_state(), today_date="2026-12-25")
    assert home_data["today"] == "2026-12-25"


def test_what_to_do_next_is_list():
    home_data = _build(_sample_state())
    assert isinstance(home_data["whatToDoNext"], list)


# ---------- filesystem integration ----------

def test_build_home_loads_from_disk_when_no_override(tmp_path):
    """Without state_override, build_home reads engagement_state.json from disk."""
    home = tmp_path / "arxiclaw"
    home.mkdir()
    s = _sample_state()
    s["activity"]["lifetime"]["commentsPosted"] = 99
    eng.save_engagement(home, s)

    home_data = home_mod.build_home(
        home=home, today_date="2026-06-04",
        token=None, user_id=None, username=None,
    )
    assert home_data["yourAccount"]["lifetime"]["commentsPosted"] == 99


def test_build_home_handles_missing_engagement_state(tmp_path):
    """If engagement_state.json doesn't exist, build_home creates it via
    eng.load_engagement (which auto-creates defaults)."""
    home = tmp_path / "arxiclaw"
    home.mkdir()
    home_data = home_mod.build_home(
        home=home, today_date="2026-06-04",
        token=None, user_id=None, username=None,
    )
    # Should succeed and return default state
    assert home_data["yourAccount"]["trustLevel"] == "new"
    # the freshly-created state should now exist on disk
    assert (home / "engagement_state.json").exists()


# ---------- render_home_text ----------

def test_render_home_text_includes_trust_label():
    s = _sample_state()
    home_data = _build(s)
    text = home_mod.render_home_text(home_data)
    assert "established" in text or "trust" in text.lower()


def test_render_home_text_contains_account_block():
    s = _sample_state()
    s["username"] = "test_alice"
    home_data = _build(s)
    text = home_mod.render_home_text(home_data)
    assert "test_alice" in text
