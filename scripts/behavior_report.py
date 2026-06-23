"""Behavior report helpers — reused by daily_digest as a trailing section.

Pure local: reads engagement_state.json + runs/{date}/* and returns MD / HTML
fragments. No platform writes. No standalone files.

Public API:
  build_behavior_section_md(home, date_str) -> str       # Markdown fragment
  build_behavior_section_html(home, date_str) -> str     # HTML fragment
  build_aggregated_behavior_md(home, dates, title) -> str
  build_aggregated_behavior_html(home, dates, title) -> str

The returned fragments are meant to be appended to / embedded inside the
unified daily_digest.{lang}.{md,html} (or weekly / monthly aggregate).
The legacy standalone behavior_report.{md,html} files are no longer produced;
they are kept only as a compatibility shim that re-renders the digest's
behavior section and writes the same content to those paths.

NOTE: This module deliberately does NOT call any platform API and does NOT
import daily_runner (to avoid circular imports). The behavior sections read
only local files.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import engagement as eng

# ---------- i18n strings (small, enough for one section) ----------

_BEHAVIOR_T = {
    "zh-CN": {
        "section_title": "行为报告",
        "account_state": "账户状态",
        "received": "收到的互动",
        "received_none": "今日无回复动作",
        "my_actions": "我主动做了什么",
        "my_actions_none": "今日无平台写动作 (或 dry-run)",
        "my_actions_total": "今日总计 {n} 个动作",
        "stat_like": "点赞",
        "stat_collect": "收藏",
        "stat_comment": "评论",
        "stat_reply": "回复",
        "stat_comment_like": "评论点赞",
        "topic_trend": "主题趋势",
        "topic_empty": "无主题数据",
        "persona": "Persona 变化",
        "persona_empty": "本周无 reject 记录",
        "persona_obs": "taste observation",
        "persona_patch": "persona patch suggested",
        "tomorrow": "明日建议",
        "generated_at": "模板生成于",
    },
    "en-US": {
        "section_title": "Behavior Report",
        "account_state": "Account State",
        "received": "Received Interactions",
        "received_none": "No reply actions today",
        "my_actions": "What I Did",
        "my_actions_none": "No platform write actions today (or dry-run)",
        "my_actions_total": "Today total: {n} actions",
        "stat_like": "likes",
        "stat_collect": "collects",
        "stat_comment": "comments",
        "stat_reply": "replies",
        "stat_comment_like": "comment-likes",
        "topic_trend": "Topic Trends",
        "topic_empty": "No topic data",
        "persona": "Persona Changes",
        "persona_empty": "No reject records this week",
        "persona_obs": "taste observation",
        "persona_patch": "persona patch suggested",
        "tomorrow": "Tomorrow's Suggestions",
        "generated_at": "Generated at",
    },
}


def _t(lang: str, key: str, **fmt: Any) -> str:
    table = _BEHAVIOR_T.get(lang, _BEHAVIOR_T["zh-CN"])
    s = table.get(key, _BEHAVIOR_T["zh-CN"].get(key, key))
    if fmt:
        try:
            return s.format(**fmt)
        except (KeyError, IndexError):
            return s
    return s


def _html_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace('"', "&quot;"))


# ---------- shared data loader ----------

def _load_behavior_data(home: Path, date_str: str) -> dict[str, Any] | None:
    """Load all artifacts needed to render a behavior section.

    Returns None if the run_dir does not exist (caller decides how to render
    the "no data" case).
    """
    run_dir = home / "runs" / date_str
    if not run_dir.exists():
        return None
    state = eng.load_engagement(home)
    eng.sync_state_to_trust(state)
    digest = json.loads((run_dir / "daily_digest.json").read_text(encoding="utf-8")) \
        if (run_dir / "daily_digest.json").exists() else {}
    proposals = json.loads((run_dir / "action_proposals.json").read_text(encoding="utf-8")) \
        if (run_dir / "action_proposals.json").exists() else []
    results = json.loads((run_dir / "action_results.json").read_text(encoding="utf-8")) \
        if (run_dir / "action_results.json").exists() else []
    reply_results = json.loads((run_dir / "reply_results.json").read_text(encoding="utf-8")) \
        if (run_dir / "reply_results.json").exists() else []
    interaction_state = {"processed_comment_ids": []}
    p = home / "interaction_state.json"
    if p.exists():
        try:
            interaction_state = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    persona = {}
    pp = home / "persona.json"
    if pp.exists():
        try:
            persona = json.loads(pp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    taste_evolution = None
    tp = run_dir / "taste_evolution.json"
    if tp.exists():
        try:
            taste_evolution = json.loads(tp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "run_dir": run_dir,
        "state": state,
        "digest": digest,
        "proposals": proposals,
        "results": results,
        "reply_results": reply_results,
        "interaction_state": interaction_state,
        "persona": persona,
        "taste_evolution": taste_evolution,
    }


# ---------- per-day behavior section: MD ----------

def build_behavior_section_md(home: Path, date_str: str,
                              lang: str = "zh-CN") -> str:
    """Return a Markdown fragment for the behavior section of date_str.

    If the run dir is missing, returns an empty string (digest's caller
    can decide to skip the section or show a placeholder).
    """
    data = _load_behavior_data(home, date_str)
    if data is None:
        return ""
    state = data["state"]
    digest = data["digest"]
    reply_results = data["reply_results"]
    today_act = state["activity"]["today"]
    lifetime = state["activity"]["lifetime"]

    lines: list[str] = []
    lines.append(f"## 📊 {_t(lang, 'section_title')} — {date_str}")
    lines.append("")
    lines.append(f"> _{_t(lang, 'generated_at')} "
                 f"{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}_")
    lines.append("")

    # 1. account state
    lines.append(f"### {_t(lang, 'account_state')}")
    lines.append(f"- trust: **{state.get('trustLevel')}** "
                 f"(since {(state.get('firstSeenAt') or '')[:10]}, "
                 f"score={eng.trust_score(state)})")
    lines.append(
        f"- lifetime: {lifetime.get('commentsPosted', 0)} 评论, "
        f"{lifetime.get('postLikes', 0)} 点赞, "
        f"{lifetime.get('postCollects', 0)} 收藏"
    )
    lines.append(
        f"- today: {today_act.get('commentsPosted', 0)} 评论, "
        f"{today_act.get('postLikes', 0)} 点赞, "
        f"{today_act.get('postCollects', 0)} 收藏, "
        f"{today_act.get('repliesPosted', 0)} 回复"
    )
    lines.append("")

    # 2. received interactions
    lines.append(f"### {_t(lang, 'received')}")
    processed = len(data["interaction_state"].get("processed_comment_ids", []))
    lines.append(f"- 累计已处理评论: {processed}")
    replies_today = [r for r in reply_results if r.get("actionType") == "reply"]
    if replies_today:
        lines.append(f"- 今日回复: {len(replies_today)} 条")
        for r in replies_today:
            lines.append(f"  - paper {r.get('paperId')}: "
                         f"`{(r.get('content_preview') or '')[:80]}`")
    else:
        lines.append(f"- {_t(lang, 'received_none')}")
    lines.append("")

    # 3. my actions
    lines.append(f"### {_t(lang, 'my_actions')}")
    n_likes = today_act.get("postLikes", 0)
    n_collects = today_act.get("postCollects", 0)
    n_comments = today_act.get("commentsPosted", 0)
    n_replies = today_act.get("repliesPosted", 0)
    n_comment_likes = today_act.get("commentLikes", 0)
    total_today = n_likes + n_collects + n_comments + n_replies + n_comment_likes
    if total_today == 0:
        lines.append(f"- {_t(lang, 'my_actions_none')}")
    else:
        lines.append(f"- {_t(lang, 'my_actions_total', n=total_today)}:")
        if n_likes:
            lines.append(f"  - 👍 {_t(lang, 'stat_like')}: {n_likes} 篇")
        if n_collects:
            lines.append(f"  - ⭐ {_t(lang, 'stat_collect')}: {n_collects} 篇")
        if n_comments:
            lines.append(f"  - 💬 {_t(lang, 'stat_comment')}: {n_comments} 条")
        if n_replies:
            lines.append(f"  - ↩️ {_t(lang, 'stat_reply')}: {n_replies} 条")
        if n_comment_likes:
            lines.append(f"  - 👍💬 {_t(lang, 'stat_comment_like')}: {n_comment_likes} 条")
        if data["proposals"]:
            lines.append(f"- proposals 中: {len(data['proposals'])} 篇 "
                         f"(agent 已选 {total_today} 篇执行)")
    lines.append("")

    # 4. topic trends
    lines.append(f"### {_t(lang, 'topic_trend')}")
    must_read = digest.get("mustRead", []) or []
    topic_counter: Counter = Counter()
    for p in must_read:
        for kw in (p.get("eng_keywords") or [])[:3]:
            topic_counter[kw.upper()] += 1
    if topic_counter:
        for topic, n in topic_counter.most_common(5):
            lines.append(f"- `{topic}`: {n} 篇必读")
    else:
        lines.append(f"- {_t(lang, 'topic_empty')}")
    lines.append("")

    # 5. persona changes
    lines.append(f"### {_t(lang, 'persona')}")
    persona = data["persona"]
    rejected_types = persona.get("rejected_paper_types", []) or []
    rejected_keywords = persona.get("rejected_keywords", []) or []
    if rejected_types:
        lines.append(f"- rejected_paper_types: {rejected_types}")
    if rejected_keywords:
        lines.append(f"- rejected_keywords: {rejected_keywords}")
    if not rejected_types and not rejected_keywords:
        lines.append(f"- {_t(lang, 'persona_empty')}")
    if data["taste_evolution"]:
        te = data["taste_evolution"]
        for obs in (te.get("taste_observations") or [])[:3]:
            lines.append(f"- {_t(lang, 'persona_obs')}: {obs}")
        for patch in (te.get("persona_patches_suggested") or [])[:3]:
            lines.append(f"- {_t(lang, 'persona_patch')}: "
                         f"{patch.get('op')} {patch.get('key')} = {patch.get('value')}")
    lines.append("")

    # 6. tomorrow suggestions
    lines.append(f"### {_t(lang, 'tomorrow')}")
    lines.append(f"- 继续读 {date_str} digest 里建议的论文")
    lines.append("- 处理今日新收到的回复")
    lines.append(f"- 关注 trust 升级: {state.get('trustLevel')} "
                 f"(score={eng.trust_score(state)})")
    lines.append("")
    return "\n".join(lines)


# ---------- per-day behavior section: HTML ----------

def build_behavior_section_html(home: Path, date_str: str,
                                lang: str = "zh-CN") -> str:
    """Return an HTML fragment (one collapsible <details> section) for date_str.

    Uses the same CSS class names as the main digest renderer
    (`details.section` / `summary` / `sec-body` / `stat` / `action-card` /
    `muted` / `paper` / `stance-*`) so it can be embedded directly.
    """
    data = _load_behavior_data(home, date_str)
    if data is None:
        return ""
    state = data["state"]
    digest = data["digest"]
    reply_results = data["reply_results"]
    today_act = state["activity"]["today"]
    lifetime = state["activity"]["lifetime"]

    n_likes = today_act.get("postLikes", 0)
    n_collects = today_act.get("postCollects", 0)
    n_comments = today_act.get("commentsPosted", 0)
    n_replies = today_act.get("repliesPosted", 0)
    n_comment_likes = today_act.get("commentLikes", 0)
    total_today = n_likes + n_collects + n_comments + n_replies + n_comment_likes

    out: list[str] = []
    out.append(
        "<details class='section'>"
        f"<summary>📊 {_html_escape(_t(lang, 'section_title'))} — "
        f"{_html_escape(date_str)}"
        f"<span class='sec-count'>{_html_escape(date_str)}</span>"
        "<span class='sec-toggle' title='全部展开/折叠'>↕</span>"
        "</summary>"
        "<div class='sec-body'>"
    )
    out.append(
        f"<blockquote class='muted'>{_html_escape(_t(lang, 'generated_at'))} "
        f"{_html_escape(datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z'))}"
        "</blockquote>"
    )

    # 1. account state
    out.append(
        f"<h3>{_html_escape(_t(lang, 'account_state'))}</h3>"
        "<ul>"
        f"<li>trust: <b>{_html_escape(str(state.get('trustLevel')))}</b> "
        f"(since {_html_escape((state.get('firstSeenAt') or '')[:10])}, "
        f"score={_html_escape(str(eng.trust_score(state)))})</li>"
        f"<li>lifetime: {_html_escape(str(lifetime.get('commentsPosted', 0)))} 评论, "
        f"{_html_escape(str(lifetime.get('postLikes', 0)))} 点赞, "
        f"{_html_escape(str(lifetime.get('postCollects', 0)))} 收藏</li>"
        f"<li>today: {_html_escape(str(today_act.get('commentsPosted', 0)))} 评论, "
        f"{_html_escape(str(today_act.get('postLikes', 0)))} 点赞, "
        f"{_html_escape(str(today_act.get('postCollects', 0)))} 收藏, "
        f"{_html_escape(str(today_act.get('repliesPosted', 0)))} 回复</li>"
        "</ul>"
    )

    # 2. received interactions
    out.append(f"<h3>{_html_escape(_t(lang, 'received'))}</h3>")
    processed = len(data["interaction_state"].get("processed_comment_ids", []))
    out.append(
        "<ul>"
        f"<li>累计已处理评论: {_html_escape(str(processed))}</li>"
    )
    replies_today = [r for r in reply_results if r.get("actionType") == "reply"]
    if replies_today:
        out.append(f"<li>今日回复: {_html_escape(str(len(replies_today)))} 条<ul>")
        for r in replies_today:
            preview = (r.get("content_preview") or "")[:80]
            out.append(
                f"<li>paper {_html_escape(str(r.get('paperId')))}: "
                f"<code>{_html_escape(preview)}</code></li>"
            )
        out.append("</ul></li>")
    else:
        out.append(f"<li class='muted'>{_html_escape(_t(lang, 'received_none'))}</li>")
    out.append("</ul>")

    # 3. my actions
    out.append(f"<h3>{_html_escape(_t(lang, 'my_actions'))}</h3>")
    if total_today == 0:
        out.append(
            f"<p class='empty'>{_html_escape(_t(lang, 'my_actions_none'))}</p>"
        )
    else:
        out.append("<p class='action-stats'>")
        out.append(
            f"<span class='stat like'>👍 {_html_escape(_t(lang, 'stat_like'))} {n_likes}</span> "
            f"<span class='stat collect'>⭐ {_html_escape(_t(lang, 'stat_collect'))} {n_collects}</span> "
            f"<span class='stat comment'>💬 {_html_escape(_t(lang, 'stat_comment'))} {n_comments}</span> "
            f"<span class='stat'>↩️ {_html_escape(_t(lang, 'stat_reply'))} {n_replies}</span> "
            f"<span class='stat'>👍💬 {_html_escape(_t(lang, 'stat_comment_like'))} {n_comment_likes}</span>"
        )
        out.append("</p>")
        if data["proposals"]:
            out.append(
                f"<p class='muted'>proposals 中: {_html_escape(str(len(data['proposals'])))} 篇 "
                f"(agent 已选 {total_today} 篇执行)</p>"
            )

    # 4. topic trends
    out.append(f"<h3>{_html_escape(_t(lang, 'topic_trend'))}</h3>")
    must_read = digest.get("mustRead", []) or []
    topic_counter: Counter = Counter()
    for p in must_read:
        for kw in (p.get("eng_keywords") or [])[:3]:
            topic_counter[kw.upper()] += 1
    if topic_counter:
        out.append("<ul>")
        for topic, n in topic_counter.most_common(5):
            out.append(
                f"<li><code>{_html_escape(topic)}</code>: "
                f"{_html_escape(str(n))} 篇必读</li>"
            )
        out.append("</ul>")
    else:
        out.append(f"<p class='empty'>{_html_escape(_t(lang, 'topic_empty'))}</p>")

    # 5. persona changes
    out.append(f"<h3>{_html_escape(_t(lang, 'persona'))}</h3><ul>")
    persona = data["persona"]
    rejected_types = persona.get("rejected_paper_types", []) or []
    rejected_keywords = persona.get("rejected_keywords", []) or []
    if rejected_types:
        out.append(f"<li>rejected_paper_types: "
                   f"{_html_escape(str(rejected_types))}</li>")
    if rejected_keywords:
        out.append(f"<li>rejected_keywords: "
                   f"{_html_escape(str(rejected_keywords))}</li>")
    if not rejected_types and not rejected_keywords:
        out.append(f"<li class='muted'>{_html_escape(_t(lang, 'persona_empty'))}</li>")
    if data["taste_evolution"]:
        te = data["taste_evolution"]
        for obs in (te.get("taste_observations") or [])[:3]:
            out.append(
                f"<li>{_html_escape(_t(lang, 'persona_obs'))}: "
                f"{_html_escape(str(obs))}</li>"
            )
        for patch in (te.get("persona_patches_suggested") or [])[:3]:
            out.append(
                f"<li>{_html_escape(_t(lang, 'persona_patch'))}: "
                f"{_html_escape(str(patch.get('op')))} "
                f"{_html_escape(str(patch.get('key')))} = "
                f"{_html_escape(str(patch.get('value')))}</li>"
            )
    out.append("</ul>")

    # 6. tomorrow suggestions
    out.append(f"<h3>{_html_escape(_t(lang, 'tomorrow'))}</h3><ul>")
    out.append(f"<li>继续读 {date_str} digest 里建议的论文</li>")
    out.append("<li>处理今日新收到的回复</li>")
    out.append(
        f"<li>关注 trust 升级: {_html_escape(str(state.get('trustLevel')))} "
        f"(score={_html_escape(str(eng.trust_score(state)))})</li>"
    )
    out.append("</ul>")

    out.append("</div></details>")
    return "\n".join(out)


# ---------- aggregated (week / month) ----------

def _collect_runs(home: Path, dates: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in dates:
        run_dir = home / "runs" / d
        if not run_dir.exists():
            continue
        for fname in ("action_results.json", "reply_results.json"):
            p = run_dir / fname
            if p.exists():
                try:
                    items = json.loads(p.read_text(encoding="utf-8"))
                    for it in items:
                        out.append({**it, "date": d, "sourceFile": fname})
                except (json.JSONDecodeError, OSError):
                    pass
    return out


def build_aggregated_behavior_md(home: Path, dates: list[str],
                                 title: str) -> str:
    items = _collect_runs(home, dates)
    state = eng.load_engagement(home)
    eng.sync_state_to_trust(state)

    n_comments = sum(1 for it in items if it.get("actionType") == "comment")
    n_replies = sum(1 for it in items if it.get("actionType") == "reply")
    n_likes = sum(1 for it in items if it.get("actionType") == "like")
    n_collects = sum(1 for it in items if it.get("actionType") == "collect")
    n_comment_likes = sum(1 for it in items if it.get("actionType") == "comment_like")
    paper_counter: Counter = Counter()
    for it in items:
        pid = it.get("paperId")
        if pid is not None:
            paper_counter[pid] += 1
    top_papers = paper_counter.most_common(5)

    lines: list[str] = [
        f"# 📊 {title}",
        "",
        f"> 模板生成于 {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        f"> 覆盖 {len(dates)} 天 ({dates[0]} → {dates[-1]})",
        "",
        "## 累计",
        f"- 评论: {n_comments}",
        f"- 回复: {n_replies}",
        f"- 点赞: {n_likes}",
        f"- 收藏: {n_collects}",
        f"- 评论点赞: {n_comment_likes}",
        "",
        "## Top 互动论文",
    ]
    if top_papers:
        for pid, n in top_papers:
            lines.append(f"- paper {pid}: {n} 次互动")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## Trust 演进")
    lines.append(f"- 当前: {state.get('trustLevel')} (score={eng.trust_score(state)})")
    lines.append("")
    return "\n".join(lines)


def build_aggregated_behavior_html(home: Path, dates: list[str],
                                   title: str) -> str:
    items = _collect_runs(home, dates)
    state = eng.load_engagement(home)
    eng.sync_state_to_trust(state)

    n_comments = sum(1 for it in items if it.get("actionType") == "comment")
    n_replies = sum(1 for it in items if it.get("actionType") == "reply")
    n_likes = sum(1 for it in items if it.get("actionType") == "like")
    n_collects = sum(1 for it in items if it.get("actionType") == "collect")
    n_comment_likes = sum(1 for it in items if it.get("actionType") == "comment_like")
    paper_counter: Counter = Counter()
    for it in items:
        pid = it.get("paperId")
        if pid is not None:
            paper_counter[pid] += 1
    top_papers = paper_counter.most_common(5)

    out: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{_html_escape(title)}</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:840px;"
        "margin:24px auto;padding:0 16px;background:#fafafa}",
        "h1{font-size:24px;border-bottom:2px solid #2c5282;padding-bottom:6px}",
        "h2{font-size:18px;margin-top:24px;background:#edf2f7;padding:6px 12px}",
        "ul{background:#fff;padding:12px 24px;border:1px solid #e2e8f0;"
        "border-radius:6px}",
        "blockquote{color:#718096;font-style:italic;border-left:3px solid "
        "#cbd5e0;padding-left:12px}",
        "</style></head><body>",
        f"<h1>📊 {_html_escape(title)}</h1>",
        f"<blockquote>覆盖 {dates[0]} → {dates[-1]} ({len(dates)} 天)</blockquote>",
        "<h2>累计</h2><ul>",
        f"<li>评论: {n_comments}</li>",
        f"<li>回复: {n_replies}</li>",
        f"<li>点赞: {n_likes}</li>",
        f"<li>收藏: {n_collects}</li>",
        f"<li>评论点赞: {n_comment_likes}</li>",
        "</ul>",
        "<h2>Top 互动论文</h2>",
    ]
    if top_papers:
        out.append("<ul>")
        for pid, n in top_papers:
            out.append(f"<li>paper {pid}: {n} 次互动</li>")
        out.append("</ul>")
    else:
        out.append("<p class='muted'>无</p>")
    out.append("<h2>Trust 演进</h2>")
    out.append(
        f"<p>当前: <b>{_html_escape(str(state.get('trustLevel')))}</b> "
        f"(score={_html_escape(str(eng.trust_score(state)))})</p>"
    )
    out.append("</body></html>")
    return "\n".join(out)


# ---------- date range helpers (week / month) ----------

def week_dates(week_of: str | None) -> tuple[list[str], str, str]:
    if week_of is None:
        today = datetime.now().astimezone()
        monday = today - timedelta(days=today.weekday())
    else:
        d = datetime.fromisoformat(week_of)
        monday = d - timedelta(days=d.weekday())
    dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    title = f"周报 {monday.strftime('%Y-%m-%d')} - {(monday + timedelta(days=6)).strftime('%Y-%m-%d')}"
    return dates, title, monday.strftime('%Y-W%W')


def month_dates(month_of: str | None) -> tuple[list[str], str, str]:
    if month_of is None:
        today = datetime.now().astimezone()
        first = today.replace(day=1)
    else:
        first = datetime.fromisoformat(month_of).replace(day=1)
    if first.month == 12:
        next_first = first.replace(year=first.year + 1, month=1)
    else:
        next_first = first.replace(month=first.month + 1)
    dates: list[str] = []
    cur = first
    while cur < next_first:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    title = f"月报 {first.strftime('%Y-%m')}"
    return dates, title, first.strftime('%Y-%m')
