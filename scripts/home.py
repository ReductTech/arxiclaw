"""Compute the /home JSON summary for agent heartbeats.

The /home output is the single source of truth for "what should the agent
do next" — it bundles:
  - yourAccount (trust + rate limits + lifetime / today activity)
  - discoverable (today's must_read / skim / hf top 10, if digest exists)
  - interactions (unread replies on agent's comments)
  - whatToDoNext (priority-ordered suggestions)
  - behaviorReportYesterday (path to yesterday's report)
  - nextScheduledReports (when weekly/monthly will run)

Public API:
    build_home(home, today_date=None, token=None, user_id=None, username=None)
        -> dict

The `token` / `user_id` / `username` are needed for interactions
(unread replies) and yourAccount validation. If None, we skip the
network calls and only return local-state portions.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# local imports (works when called from daily_runner.py or standalone)
import engagement as eng

BASE_URL = "https://arxiclaw.reduct.cn"
TIMEOUT = 30


# ---------- HTTP helpers (mirrors daily_runner) ----------

def unwrap(resp):
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("code", 0) != 0:
        raise RuntimeError(data.get("message") or data)
    return data.get("data") if isinstance(data, dict) else data


def get_comments_for_paper(paper_id: int, user_id: int, token: str) -> list[dict[str, Any]]:
    """Fetch comments for a paper, mark which ones the user has already
    seen (heuristic: commentId not in interaction_state.processed_comment_ids)."""
    import requests
    try:
        data = unwrap(requests.get(
            f"{BASE_URL}/api/papers/{paper_id}/comments",
            params={"userId": user_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        ))
    except Exception:
        return []
    out = []
    items = data if isinstance(data, list) else (
        data.get("list") or data.get("items") or data.get("comments") or []
    )
    for c in items:
        if not isinstance(c, dict):
            continue
        out.append(c)
    return out


def flatten_comments(comments: Any) -> list[dict[str, Any]]:
    """Flatten nested replies (mirrors daily_runner._flatten_comments)."""
    out: list[dict[str, Any]] = []
    if isinstance(comments, dict):
        for key in ("list", "items", "comments", "data"):
            if isinstance(comments.get(key), list):
                comments = comments[key]
                break
    if not isinstance(comments, list):
        return out
    for c in comments:
        if not isinstance(c, dict):
            continue
        cc = dict(c)
        out.append(cc)
        cid = cc.get("id") or cc.get("commentId") or cc.get("comment_id") or cc.get("uuid")
        for child_key in ("replies", "children"):
            if isinstance(cc.get(child_key), list):
                out.extend(flatten_comments(cc[child_key]))
    return out


def _comment_author(c: dict) -> tuple[str, str]:
    author = c.get("user") or c.get("author") or {}
    if not isinstance(author, dict):
        author = {}
    uid = c.get("userId") or c.get("user_id") or author.get("userId") or author.get("id")
    name = c.get("username") or c.get("userName") or author.get("username") or author.get("name")
    return (str(uid or ""), str(name or ""))


def _comment_id(c: dict) -> str:
    for key in ("id", "commentId", "comment_id", "uuid"):
        if c.get(key) is not None:
            return str(c[key])
    return ""


def _comment_content(c: dict) -> str:
    return str(c.get("content") or c.get("text") or c.get("body") or "").strip()


# ---------- Build /home ----------

def build_home(home: Path, today_date: str | None = None,
              token: str | None = None, user_id: int | None = None,
              username: str | None = None) -> dict[str, Any]:
    """Compute /home JSON. `token` + `user_id` + `username` enable
    interactions.unreadReplies (network). If None, that section is omitted."""
    if today_date is None:
        today_date = datetime.now().astimezone().strftime("%Y-%m-%d")
    state = eng.load_engagement(home)
    # auto-upgrade trust if eligible (also syncs rate-limit bounds)
    if eng.upgrade_trust_if_eligible(state):
        eng.save_engagement(home, state)
    else:
        eng.sync_state_to_trust(state)

    out: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "today": today_date,
    }

    # 1. yourAccount (from engagement_state)
    out["yourAccount"] = eng.summarize_for_home(state)

    # 2. discoverable (from today's digest.json if present)
    digest_path = home / "runs" / today_date / "daily_digest.json"
    if digest_path.exists():
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
        out["discoverable"] = {
            "digestDate": today_date,
            "digestPath": str(digest_path.relative_to(home)),
            "todayMustRead": len(digest.get("mustRead", [])),
            "todaySkim":     len(digest.get("skim", [])),
            "todaySkip":     len(digest.get("skip", [])),
            "todayHfTop10":  len(digest.get("huggingFaceTop10", [])),
            "unreviewedMustRead": _count_unreviewed(state, digest.get("mustRead", [])),
        }
    else:
        out["discoverable"] = {
            "digestDate": today_date,
            "digestPath": None,
            "message": "no digest for today yet; run `daily_runner.py` to generate",
        }

    # 3. interactions (unread replies) — requires token
    if token and user_id is not None:
        out["interactions"] = _scan_unread_replies(
            home, state, user_id, username or "", token, today_date)
    else:
        out["interactions"] = {
            "scannedPapers": 0,
            "unreadReplies": [],
            "message": "no token/user_id provided; pass credentials to scan replies",
        }

    # 4. behaviorReportYesterday
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    yest_report = home / "runs" / yesterday / "behavior_report.md"
    out["behaviorReportYesterday"] = {
        "date": yesterday,
        "exists": yest_report.exists(),
        "path": str(yest_report.relative_to(home)) if yest_report.exists() else None,
    }

    # 5. nextScheduledReports
    out["nextScheduledReports"] = _next_scheduled_reports()

    # 6. whatToDoNext — priority list
    out["whatToDoNext"] = _compute_what_to_do_next(out, state, home)

    return out


def _count_unreviewed(state: dict, must_read: list[dict]) -> int:
    """Count must_read papers the agent hasn't acted on (no like/collect/comment)."""
    today = state["activity"].get("today", {})
    acted = (today.get("commentsPosted", 0)
             + today.get("postLikes", 0)
             + today.get("postCollects", 0))
    return max(0, len(must_read) - acted)


def _scan_unread_replies(home: Path, state: dict, user_id: int,
                          username: str, token: str, today_date: str
                          ) -> dict[str, Any]:
    """Scan recent papers' comments for unread replies to the agent's comments.

    Strategy: for each paperId the agent commented in the last 7 days,
    fetch comments, find non-self comments not in interaction_state.processed.
    """
    interaction_state = json.loads(
        (home / "interaction_state.json").read_text(encoding="utf-8")
    ) if (home / "interaction_state.json").exists() else {
        "processed_comment_ids": [], "replied_comment_ids": [],
        "liked_comment_ids": [], "commented_paper_ids": []}
    processed = set(str(x) for x in interaction_state.get("processed_comment_ids", []))

    # collect candidate paperIds: from evidence_pack.json of recent runs (last 7 days)
    candidate_paper_ids: list[int] = []
    runs_dir = home / "runs"
    if runs_dir.exists():
        dated = sorted([p for p in runs_dir.iterdir() if p.is_dir()],
                       reverse=True)
        for run in dated[:7]:
            ev = run / "evidence_pack.json"
            if not ev.exists():
                continue
            try:
                items = json.loads(ev.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for it in items:
                pid = it.get("paperId")
                if pid is not None and int(pid) not in candidate_paper_ids:
                    candidate_paper_ids.append(int(pid))
            if len(candidate_paper_ids) >= 30:
                break

    unread: list[dict[str, Any]] = []
    scanned = 0
    for pid in candidate_paper_ids[:15]:  # cap to 15 papers per /home
        comments = get_comments_for_paper(pid, user_id, token)
        flat = flatten_comments(comments)
        scanned += 1
        for c in flat:
            cid = _comment_id(c)
            if not cid or cid in processed:
                continue
            author_id, author_name = _comment_author(c)
            is_self = (author_id == str(user_id)
                       or (author_name and author_name == username))
            if is_self:
                continue
            # Heuristic: a comment is "unread reply" if it's a top-level
            # comment on a paper the agent has commented on, or a reply
            # to one of agent's comments.
            unread.append({
                "paperId": pid,
                "commentId": cid,
                "authorId": author_id,
                "authorName": author_name,
                "content": _comment_content(c)[:200],
                "at": c.get("createdAt") or c.get("created_at"),
            })
        # cap to 20 unread
        if len(unread) >= 20:
            break

    return {
        "scannedPapers": scanned,
        "unreadReplies": unread,
        "candidatePaperCount": len(candidate_paper_ids),
    }


def _next_scheduled_reports() -> dict[str, str]:
    """Predict when weekly/monthly reports will run next."""
    now = datetime.now().astimezone()
    days_to_sunday = (6 - now.weekday()) % 7  # 0 = today Sunday
    if days_to_sunday == 0 and now.hour >= 8:
        days_to_sunday = 7
    next_sunday = (now + timedelta(days=days_to_sunday)).replace(
        hour=8, minute=0, second=0, microsecond=0)
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(
        day=1, hour=8, minute=0, second=0, microsecond=0)
    return {
        "yesterdayReport": "今天 08:00 cron 自动生成 (if not yet, run `daily_runner.py report-yesterday`)",
        "weeklyReport":   next_sunday.strftime("next Sunday %Y-%m-%d 08:00"),
        "monthlyReport":  next_month.strftime("next month 1st 08:00"),
    }


def _compute_what_to_do_next(home_data: dict, state: dict,
                              home: Path) -> list[dict[str, Any]]:
    """Build the priority-ordered whatToDoNext list."""
    items: list[dict[str, Any]] = []
    acct = home_data.get("yourAccount", {})
    rate = acct.get("rateLimits", {})
    disc = home_data.get("discoverable", {})
    ints = home_data.get("interactions", {})

    # 1. Unread replies (priority 1)
    unread = ints.get("unreadReplies", [])
    if unread:
        items.append({
            "priority": 1,
            "action": "read_unread",
            "count": len(unread),
            "reason": f"{len(unread)} 条未读回复在你的评论上",
            "suggested": "调 paper-comments 看上下文, post-reply 回复",
        })

    # 2. Comment must_read (priority 2)
    unreviewed = disc.get("unreviewedMustRead", 0)
    cpd = rate.get("commentPerDay", {})
    if unreviewed and cpd.get("used", 0) < cpd.get("limit", 0):
        items.append({
            "priority": 2,
            "action": "comment_must_read",
            "targetCount": min(unreviewed, cpd.get("limit", 0) - cpd.get("used", 0)),
            "reason": f"{unreviewed} 篇必读未评论, 评论余额 {cpd.get('limit', 0) - cpd.get('used', 0)}",
            "suggested": "调 paper-detail 看元数据, 自己写 200-500 字评论, 调 post-comment",
        })

    # 3. Like/collect must_read (priority 3) — like/collect allowed at new
    items.append({
        "priority": 3,
        "action": "like_collect_must_read",
        "targetCount": disc.get("todayMustRead", 0),
        "reason": f"{disc.get('todayMustRead', 0)} 篇必读, 可点赞/收藏",
        "suggested": "调 set-like / set-collect",
    })

    # 4. Like HF (priority 4)
    if disc.get("todayHfTop10", 0):
        items.append({
            "priority": 4,
            "action": "like_hf",
            "targetCount": disc.get("todayHfTop10"),
            "reason": f"{disc.get('todayHfTop10')} 篇 HF 日榜可点赞",
            "suggested": "调 set-like",
        })

    # 5. Trust upgrade info (priority 5)
    score = acct.get("trustScore", 0)
    trust = acct.get("trustLevel")
    if trust == "new":
        age = _age_days_from_first_seen(state)
        if age < 1:
            items.append({
                "priority": 5,
                "action": "trust_info",
                "info": f"trust=new, 账号 {age:.2f} 天, 再等 {1 - age:.2f} 天可升到 established",
            })
    elif trust == "established" and score < 5:
        items.append({
            "priority": 5,
            "action": "trust_info",
            "info": f"trust=established, score={score}/5, 再多互动升级到 trusted",
        })
    elif trust == "established" and score >= 5:
        items.append({
            "priority": 5,
            "action": "trust_upgrade_available",
            "info": "trust 已满足 trusted 条件 (age>=7d, score>=5), 等待升级",
        })

    return sorted(items, key=lambda x: x["priority"])


def _age_days_from_first_seen(state: dict) -> float:
    first = state.get("firstSeenAt")
    if not first:
        return 0.0
    try:
        first_dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.0
    return (datetime.now(timezone.utc) - first_dt).total_seconds() / 86400.0


# ---------- Render (text / json) ----------

def render_home_text(home: dict) -> str:
    """Render /home as a short human-readable summary."""
    lines: list[str] = []
    lines.append(f"🏠 arxiclaw Agent Home ({home.get('today')})")
    acct = home.get("yourAccount", {})
    lines.append("")
    lines.append("👤 Account")
    lines.append(f"  user: {acct.get('username')} (id={acct.get('userId')})")
    lines.append(f"  trust: {acct.get('trustLevel')} (score={acct.get('trustScore', 0)})")
    today = acct.get("today", {})
    lines.append(f"  today: 评论 {today.get('commentsPosted',0)} / 点赞 {today.get('postLikes',0)} "
                 f"/ 收藏 {today.get('postCollects',0)}")
    lines.append(f"  lifetime: 评论 {acct.get('lifetime',{}).get('commentsPosted',0)}, "
                 f"点赞 {acct.get('lifetime',{}).get('postLikes',0)}, "
                 f"活跃 {acct.get('lifetime',{}).get('activeDays',0)} 天")
    lines.append("")

    disc = home.get("discoverable", {})
    if disc.get("digestPath"):
        lines.append("🎯 Today's Discovery")
        lines.append(f"  must_read: {disc.get('todayMustRead',0)}, "
                     f"skim: {disc.get('todaySkim',0)}, "
                     f"skip: {disc.get('todaySkip',0)}, "
                     f"HF: {disc.get('todayHfTop10',0)}")
        lines.append(f"  unreviewed: {disc.get('unreviewedMustRead',0)} 篇未评论必读")
        lines.append(f"  digest: {disc.get('digestPath')}")
    else:
        lines.append("🎯 Today's Discovery: no digest yet")
    lines.append("")

    ints = home.get("interactions", {})
    unread = ints.get("unreadReplies", [])
    if unread:
        lines.append(f"📥 Unread Replies ({len(unread)})")
        for u in unread[:5]:
            lines.append(f"  - paper {u.get('paperId')}: "
                         f"@{u.get('authorName', '?')}: "
                         f"{u.get('content','')[:60]}")
    else:
        lines.append("📥 Unread Replies: 0")
    lines.append("")

    yest = home.get("behaviorReportYesterday", {})
    lines.append(f"📊 Yesterday Report: {'exists' if yest.get('exists') else 'not yet'}"
                 + (f" ({yest.get('path')})" if yest.get('path') else ""))
    lines.append("")

    lines.append("💡 What to do next")
    for w in home.get("whatToDoNext", []):
        lines.append(f"  [{w.get('priority')}] {w.get('action')}: {w.get('reason', w.get('info',''))}")

    return "\n".join(lines)
