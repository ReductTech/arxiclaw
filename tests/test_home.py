"""Unit tests for home.py — /home output builder.

Run: pytest tests/test_home.py -v
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import engagement as eng
import home as home_mod


def _sample_state():
    s = eng.default_state(user_id=19, username="alice", email="a@b.c")
    s["trustLevel"] = "established"
    s["firstSeenAt"] = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()
    s["activity"]["lifetime"]["commentsPosted"] = 5
    s["activity"]["lifetime"]["postLikes"] = 12
    s["activity"]["today"]["commentsPosted"] = 1
    s["activity"]["today"]["postLikes"] = 3
    eng.sync_state_to_trust(s)
    return s


def test_build_home_your_account_block():
    state = _sample_state()
    home_data = home_mod.build_home(
        home=Path("/tmp"),
        today_date="2026-06-04",
        token=None, user_id=None, username=None,
        state_override=state,
    )
    acct = home_data["yourAccount"]
    assert acct["trustLevel"] == "established"
    assert acct["userId"] == 19
    assert acct["lifetime"]["commentsPosted"] == 5
    assert acct["today"]["commentsPosted"] == 1


def test_build_home_includes_what_to_do_next():
    state = _sample_state()
    home_data = home_mod.build_home(
        home=Path("/tmp"),
        today_date="2026-06-04",
        token=None, user_id=None, username=None,
        state_override=state,
    )
    assert "whatToDoNext" in home_data
    assert isinstance(home_data["whatToDoNext"], list)


def test_render_home_text_includes_trust():
    state = _sample_state()
    home_data = home_mod.build_home(
        home=Path("/tmp"),
        today_date="2026-06-04",
        token=None, user_id=None, username=None,
        state_override=state,
    )
    text = home_mod.render_home_text(home_data)
    assert "established" in text or "trust" in text.lower()
