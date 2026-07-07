"""arxiclaw daily research runner with i18n support.

Reads credentials, policy, persona from ARXICLAW_AGENT_HOME (default
~/.arxiclaw-agent). Discovers papers from newest + recommendations +
HF daily + per-interest search, dedupes, fetches details, sorts into
must_read / skim / skip (interest-related), generates a multi-language
daily digest, and (when policy allows) executes like / collect /
comment / reply / comment-like actions with toggle-aware idempotency.

Strict contract:
- must_read / skim / skip are interest-related (core_hits >= 1
  or token_hits >= 1 or explicit persona signal). Unrelated candidates
  stay in evidence_pack.json as unrelated_filtered.
- HF daily top 10 is its own section, not merged into the candidate
  pool.
- Summaries are full API-provided text, never first-sentence snippets.
- 4-slot i18n: comment / digest / feedback / stored independent.

Subcommands:
    python daily_runner.py                # full daily
    python daily_runner.py dry-run        # no platform writes
    python daily_runner.py heartbeat      # comment reply + like only
    python daily_runner.py feedback ...   # paper-id/type/keyword/style accept/reject
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


# ---------- Version ----------

__version__ = "0.3.1"


# ---------- Config ----------

BASE_URL = os.getenv("ARXICLAW_BASE_URL", "https://arxiclaw.reduct.cn").rstrip("/")
TIMEOUT = 60
SOURCE_TAG = "external_research_agent:daily_digest"
RECOMMENDATIONS_PAGE_CAP = 10
RECOMMENDATIONS_MAX_PAGES = 10
RECOMMENDATIONS_DEVICE_ID = os.getenv("ARXICLAW_DEVICE_ID", "arxiclaw-daily-runner")
SUPPORTED_LANGS = ("zh-CN", "en-US")
DEFAULT_LANG = "zh-CN"
DEFAULT_MAX_REPLIES_PER_RUN = 3
DEFAULT_MAX_COMMENT_LIKES_PER_RUN = 10
DEFAULT_DRY_RUN_PAGE_SIZE = 10
DEFAULT_DRY_RUN_MAX_DETAILS = 12
DEFAULT_DRY_RUN_HF_TOP_N = 5
DEFAULT_DRY_RUN_COMMENT_SCAN_PAPERS = 5
SUPPORTED_ACTION_TYPES = {
    "like",
    "collect",
    "comment",
    "reply",
    "comment_like",
    "feedback_reject",
    "feedback_accept",
}


# ---------- Core category terms (used for triage) ----------

CORE_CATEGORY_TERMS = [
    "multimodal", "retrieval", "vision-language", "cross-modal",
    "video-text", "image-text", "image retrieval", "video retrieval",
    "visual-semantic", "contrastive", "embedding",
    "image-text matching", "vision encoder", "vision tower",
    "clip", "blip", "rag",
]

FOCUS_STOP = {"the", "and", "for", "with", "from", "augmented",
              "generation", "aware", "unified"}


# ---------- I18N ----------

I18N_ZH: dict[str, str] = {
    # console / fatal
    "fatal_credentials_missing": "[致命] 缺少 credentials.json，无法继续",
    "fatal_api_bootstrap": "[致命] api-bootstrap 失败：{err}",
    "ok_daily_run_finished": "[成功] 每日运行完成，必读={mr} 速览={sk} 跳过={sp} 动作={ac}",
    "stage": "阶段",
    "auth": "认证",
    "discovery": "发现",
    "triage": "分流",
    "actions": "动作",
    # digest
    "digest_title": "arxiclaw 每日论文摘要 {date}",
    "user_label": "用户",
    "summary_label": "摘要",
    "evidence_label": "证据范围",
    "must_read_label": "必读",
    "skim_label": "速览",
    "skip_label": "跳过",
    "skip_count_label": "跳过数",
    "section_must_read": "必读",
    "section_hf_daily_top10": "Hugging Face 日榜 Top 10",
    "section_skim": "速览",
    "section_skip": "跳过",
    "section_actions": "今日智能体动作",
    "label_authors": "作者",
    "label_arxiv": "arXiv",
    "label_published": "发布日期",
    "label_category": "类别",
    "label_code": "代码",
    "label_fig_alt": "论文主图",
    "label_tab_alt": "论文主表",
    "label_fig_missing": "无封面图",
    "label_keywords": "关键词",
    "label_source": "来源",
    "label_type": "类型",
    "label_no_summary": "(无摘要)",
    "label_overview": "今日总览",
    "label_discovery_sources": "发现源",
    "label_footer": "本报告由 arxiclaw 智能体基于平台元数据自动生成；图片与摘要均来自平台 API 返回，未读 PDF 全文。",
    "summary_template": "今日发现 {c} 篇候选；{mr} 篇必读，{sk} 篇速览，{sp} 篇跳过；执行 {ac} 个动作。",
    "skipped_same": "(已是目标状态，跳过)",
    "core_field": "命中核心类别",
    "tokens_field": "命中焦点词",
    "score_field": "评分",
    "no_actions": "_(本次运行未执行任何动作)_",
    "none_label": "_(无)_",
    "action_like": "点赞",
    "action_collect": "收藏",
    "action_comment": "评论",
    "label_no_papers": "(本段无内容)",
}

I18N_EN: dict[str, str] = {
    "fatal_credentials_missing": "[fatal] credentials.json missing, cannot continue",
    "fatal_api_bootstrap": "[fatal] api-bootstrap failed: {err}",
    "ok_daily_run_finished": "[ok] daily run finished, must_read={mr} skim={sk} skip={sp} actions={ac}",
    "stage": "stage",
    "auth": "auth", "discovery": "discovery", "triage": "triage", "actions": "actions",
    "digest_title": "arxiclaw Daily Digest {date}",
    "user_label": "User", "summary_label": "Summary", "evidence_label": "Evidence",
    "must_read_label": "Must Read", "skim_label": "Skim", "skip_label": "Skip",
    "skip_count_label": "Skip (count)",
    "section_must_read": "Must Read",
    "section_hf_daily_top10": "Hugging Face Daily Top 10",
    "section_skim": "Skim",
    "section_skip": "Skip",
    "section_actions": "Today's Agent Actions",
    "label_authors": "Authors", "label_arxiv": "arXiv", "label_published": "Published",
    "label_category": "Category", "label_code": "Code",
    "label_fig_alt": "key figure", "label_tab_alt": "key table",
    "label_fig_missing": "no cover figure",
    "label_keywords": "Keywords", "label_source": "source", "label_type": "type",
    "label_no_summary": "(no summary available)",
    "label_overview": "Today's overview",
    "label_discovery_sources": "Discovery sources",
    "label_footer": "Auto-generated by arxiclaw agent from platform metadata; "
                    "images and summaries are API-supplied. Full PDF not read.",
    "summary_template": "Today found {c} candidates; {mr} must-read; {sk} skim; "
                        "{sp} skip; {ac} actions executed.",
    "skipped_same": "(already in desired state, skipped)",
    "core_field": "core", "tokens_field": "tokens", "score_field": "score",
    "no_actions": "_(no actions executed this run)_",
    "none_label": "_(none)_",
    "action_like": "Like", "action_collect": "Collect", "action_comment": "Comment",
    "label_no_papers": "(no papers in this section)",
}


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Translate key with fallback to zh-CN, then key itself."""
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    table = I18N_ZH if lang == "zh-CN" else I18N_EN
    text = table.get(key) or I18N_ZH.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def resolve_lang(policy: dict[str, Any], slot: str) -> str:
    lang_cfg = policy.get("language") or {}
    val = lang_cfg.get(slot) or DEFAULT_LANG
    return val if val in SUPPORTED_LANGS else DEFAULT_LANG


def agent_home() -> Path:
    configured = os.getenv("ARXICLAW_AGENT_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.environ["USERPROFILE"]) / ".arxiclaw-agent"
    return Path.home() / ".arxiclaw-agent"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_policy(home: Path) -> dict[str, Any]:
    default_path = Path(__file__).with_name("policy.default.json")
    defaults = load_json(default_path, {}) if default_path.exists() else {}
    policy = load_json(home / "policy.json", {})
    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(policy, dict):
        policy = {}
    merged = dict(defaults)
    for key, value in policy.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


# ---------- HTTP helpers ----------

def unwrap(resp: requests.Response) -> Any:
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("code", 0) != 0:
        raise RuntimeError(data.get("message") or data)
    return data.get("data") if isinstance(data, dict) else data


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def exchange_api_key(api_key: str) -> str:
    return unwrap(requests.post(
        f"{BASE_URL}/api/auth/token",
        json={"grantType": "api_key", "apiKey": api_key},
        timeout=TIMEOUT,
    ))["accessToken"]


def get_me(token: str) -> dict[str, Any]:
    return unwrap(requests.get(
        f"{BASE_URL}/api/auth/me", headers=auth_headers(token), timeout=TIMEOUT,
    ))


def get_interests(token: str) -> list[str]:
    try:
        data = unwrap(requests.get(
            f"{BASE_URL}/api/user/interests",
            headers=auth_headers(token),
            timeout=TIMEOUT,
        ))
    except (requests.HTTPError, requests.ConnectionError, requests.Timeout,
            requests.RequestException) as exc:
        print(f"[warn] get_interests failed: {exc}; falling back to "
              f"persona.preferred_concepts", file=sys.stderr, flush=True)
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("eng_interest", "engInterest", "items", "list", "keywords"):
            v = data.get(key)
            if isinstance(v, list):
                return v
    return []


def post_user_behavior(token: str, user_id: int, username: str,
                        behavior_type: str, paper_id: int | None = None,
                        result_state: str | None = None,
                        source: str | None = None,
                        device_id: str = RECOMMENDATIONS_DEVICE_ID) -> None:
    body: dict[str, Any] = {
        "userId": user_id, "username": username,
        "behaviorType": behavior_type,
    }
    if paper_id is not None:
        body["paperId"] = paper_id
    if result_state is not None:
        body["resultState"] = result_state
    if source is not None:
        body["source"] = source
    try:
        unwrap(requests.post(
            f"{BASE_URL}/api/user-behaviors",
            headers={**auth_headers(token), "X-Device-Id": device_id},
            json=body, timeout=TIMEOUT,
        ))
    except Exception as exc:
        print(f"[warn] user-behaviors({behavior_type}) failed: {exc}",
              file=sys.stderr, flush=True)


# ---------- Discovery ----------

def _extract_papers(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("list", "items", "papers"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []


def _tag_sources(papers: list[dict[str, Any]], source_tag: str) -> list[dict[str, Any]]:
    for p in papers:
        tags = p.get("source_tags")
        if not isinstance(tags, list):
            tags = []
        if source_tag not in tags:
            tags.append(source_tag)
        p["source_tags"] = tags
    return papers


def list_papers(sort: str, time_range: str, page_size: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in (1, 2):
        try:
            payload = unwrap(requests.get(
                f"{BASE_URL}/api/papers",
                params={
                    "sort": sort, "timeRange": time_range,
                    "page": page, "pageSize": page_size, "skipTotal": "true",
                },
                timeout=TIMEOUT,
            ))
        except requests.HTTPError as exc:
            print(f"[warn] list_papers({sort},{time_range},page={page}) failed: {exc}",
                  file=sys.stderr, flush=True)
            break
        batch = _extract_papers(payload)
        items.extend(batch)
        if len(items) >= page_size:
            break
        if len(batch) < page_size:
            break
    return items[:page_size]


def search_papers(q: str, page_size: int, search_mode: str = "auto") -> list[dict[str, Any]]:
    base_params = {
        "sort": "newest", "timeRange": "180d",
        "page": 1, "pageSize": page_size, "skipTotal": "true",
    }
    mode = (search_mode or "auto").lower()
    attempts: list[tuple[str, dict[str, Any]]] = []
    if mode in ("keyword", "auto"):
        attempts.append(("keyword", {**base_params, "keyword": q}))
    if mode in ("q", "auto"):
        attempts.append(("q", {**base_params, "q": q, "searchType": "all"}))
    if not attempts:
        attempts.append(("keyword", {**base_params, "keyword": q}))

    for label, params in attempts:
        try:
            payload = unwrap(requests.get(
                f"{BASE_URL}/api/papers", params=params, timeout=TIMEOUT,
            ))
            items = _extract_papers(payload)
            if label != attempts[0][0]:
                print(f"[info] search_papers({q!r}) succeeded via {label}",
                      flush=True)
            return _tag_sources(items, f"interest_search:{q}:{label}")
        except (requests.HTTPError, requests.ConnectionError,
                requests.Timeout, requests.RequestException,
                RuntimeError) as exc:
            print(f"[warn] search_papers({q!r}) via {label} failed: {exc}",
                  file=sys.stderr, flush=True)
    print(f"[warn] search_papers({q!r}) exhausted all modes",
          file=sys.stderr, flush=True)
    return []


def get_recommendations(token: str, page_size: int) -> list[dict[str, Any]]:
    headers = {**auth_headers(token), "X-Device-Id": RECOMMENDATIONS_DEVICE_ID}
    out: list[dict[str, Any]] = []
    for page in range(1, RECOMMENDATIONS_MAX_PAGES + 1):
        try:
            resp = requests.get(
                f"{BASE_URL}/api/papers/recommendations",
                headers=headers,
                params={"page": page, "pageSize": page_size,
                        "uuid": RECOMMENDATIONS_DEVICE_ID},
                timeout=TIMEOUT,
            )
            if 500 <= resp.status_code < 600:
                print(f"[warn] recommendations page {page} transient "
                      f"HTTP {resp.status_code}; skipping", file=sys.stderr,
                      flush=True)
                continue
            resp.raise_for_status()
            payload = resp.json()
        except requests.HTTPError as exc:
            print(f"[warn] recommendations page {page} failed: {exc}",
                  file=sys.stderr, flush=True)
            break
        except (requests.ConnectionError, requests.Timeout) as exc:
            print(f"[warn] recommendations page {page} network error: {exc}",
                  file=sys.stderr, flush=True)
            continue
        if isinstance(payload, dict) and payload.get("code", 0) != 0:
            print(f"[warn] recommendations page {page} non-ok: "
                  f"{payload.get('code')} {payload.get('message')}",
                  file=sys.stderr, flush=True)
            break
        data = payload.get("data") if isinstance(payload, dict) else payload
        batch = _extract_papers(data)
        out.extend(batch)
        if len(out) >= page_size:
            break
        if len(batch) < RECOMMENDATIONS_PAGE_CAP:
            break
    return out


def get_huggingface_papers(period: str, page_size: int) -> list[dict[str, Any]]:
    """`GET /api/huggingface/daily-papers`; response is `items[].paper`."""
    try:
        payload = unwrap(requests.get(
            f"{BASE_URL}/api/huggingface/daily-papers",
            params={
                "page": 1, "pageSize": page_size, "period": period,
                "cacheOnly": "true", "fallbackLatest": "true",
            },
            timeout=TIMEOUT,
        ))
    except (requests.HTTPError, requests.ConnectionError, requests.Timeout,
            requests.RequestException, RuntimeError) as exc:
        print(f"[warn] huggingface {period} papers failed: {exc}",
              file=sys.stderr, flush=True)
        return []
    out: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items") or payload.get("list") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        paper = item.get("paper")
        if not isinstance(paper, dict):
            paper = {
                "id": item.get("paperId"),
                "external_id": item.get("arxivId"),
            }
        cloned = dict(paper)
        cloned.setdefault("id", item.get("paperId") or paper.get("id"))
        cloned["_huggingface_rank"] = item.get("rank")
        cloned["_huggingface_upvotes"] = item.get("upvotes")
        cloned["_huggingface_comments"] = item.get("numComments")
        out.append(cloned)
    return _tag_sources(out, f"huggingface:{period}")


def search_all_interests(interests: list[str], page_size: int,
                          search_mode: str = "auto") -> tuple[list[dict[str, Any]], dict[str, int]]:
    papers: list[dict[str, Any]] = []
    per_query: dict[str, int] = {}
    for term in interests:
        if not term:
            continue
        batch = search_papers(term, page_size, search_mode=search_mode)
        per_query[term] = len(batch)
        _tag_sources(batch, f"interest_search:{term}")
        papers.extend(batch)
    return papers, per_query


# ---------- Persona & seen window ----------

def prune_seen(papers: list[dict[str, Any]], seen_ids: set[int]) -> list[dict[str, Any]]:
    if not seen_ids:
        return papers
    return [p for p in papers if p.get("id") not in seen_ids]


def record_seen(persona: dict[str, Any], paper_ids: list[int], now_iso: str) -> list[int]:
    entries = persona.get("seen_paper_ids") or []
    if not isinstance(entries, list):
        entries = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    kept: list[dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        pid = e.get("paperId")
        ts = e.get("seenAt")
        if pid is None or not ts:
            continue
        try:
            seen_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if seen_dt >= cutoff:
            kept.append(e)
    existing_ids = {e.get("paperId") for e in kept}
    for pid in paper_ids:
        if pid is None or pid in existing_ids:
            continue
        kept.append({"paperId": pid, "seenAt": now_iso})
        existing_ids.add(pid)
    persona["seen_paper_ids"] = kept
    return existing_ids


# ---------- Detail & dedup ----------

def paper_detail(paper_id: int) -> dict[str, Any] | None:
    """Fetch paper detail with retry on transient network errors.

    Returns None on any failure so callers can skip this paper without
    aborting the whole daily run. The previous version only caught
    HTTPError, which let ProxyError / ConnectionError / Timeout crash
    main() and lose the entire run.
    """
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return unwrap(requests.get(
                f"{BASE_URL}/api/papers/{paper_id}", timeout=TIMEOUT,
            ))
        except requests.HTTPError as exc:
            print(f"[warn] detail {paper_id} failed: {exc}",
                  file=sys.stderr, flush=True)
            return None
        except (requests.ConnectionError, requests.Timeout,
                requests.RequestException) as exc:
            last_exc = exc
            wait = 0.5 * (2 ** attempt)
            print(f"[warn] detail {paper_id} transient {type(exc).__name__} "
                  f"(attempt {attempt+1}/3): {exc}; sleep {wait:.1f}s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
    print(f"[warn] detail {paper_id} gave up after 3 retries: {last_exc}",
          file=sys.stderr, flush=True)
    return None


def normalize_title(title: str) -> str:
    nfkd = unicodedata.normalize("NFKD", title or "").lower()
    return re.sub(r"[\s\W_]+", "", nfkd)


def dedupe(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[int] = set()
    seen_ext: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in papers:
        pid = p.get("id")
        ext = p.get("external_id") or ""
        title_key = normalize_title(p.get("title") or "")
        if pid is not None:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
        if ext:
            if ext in seen_ext:
                continue
            seen_ext.add(ext)
        if title_key:
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
        out.append(p)
    return out


# ---------- Triage ----------

def _focus_tokens(focus_terms: list[str]) -> list[str]:
    tokens: list[str] = []
    for term in focus_terms:
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", term):
            if tok.lower() not in FOCUS_STOP:
                tokens.append(tok.lower())
    seen: set[str] = set()
    out: list[str] = []
    for tk in tokens:
        if tk not in seen:
            seen.add(tk)
            out.append(tk)
    return out


def _haystack(detail: dict[str, Any]) -> str:
    return " ".join([
        str(detail.get("title") or ""),
        str(detail.get("abstract") or ""),
        str(detail.get("eng_script") or ""),
        " ".join(detail.get("eng_keywords") or []),
        " ".join(detail.get("cn_keywords") or []),
    ]).lower()


def _core_hits(haystack: str) -> int:
    return sum(1 for term in CORE_CATEGORY_TERMS if term in haystack)


def _token_hits(haystack: str, focus_tokens: list[str]) -> int:
    return sum(1 for tok in focus_tokens if tok in haystack)


def classify_paper_type(detail: dict[str, Any]) -> str:
    hay = _haystack(detail)
    keywords = " ".join(detail.get("eng_keywords") or []).lower()
    type_rules: list[tuple[str, list[str]]] = [
        ("retrieval", ["retrieval", "image-text matching", "matching",
                       "re-ranking", "reranking"]),
        ("vlm", ["vision-language", "vlm", "visual reasoning",
                 "visual question", "vqa", "mllm"]),
        ("embedding", ["embedding", "vector", "contrastive",
                       "representation learning"]),
        ("agent", ["agent", "agentic", "tool use", "planning"]),
        ("generation", ["generation", "rag", "retrieval-augmented",
                        "grounded generation"]),
    ]
    for type_name, needles in type_rules:
        if any(n in hay or n in keywords for n in needles):
            return type_name
    if "multimodal" in hay or "multimodal" in keywords:
        return "multimodal_general"
    return "multimodal_general"


def _term_hits(haystack: str, terms: Any) -> list[str]:
    if not isinstance(terms, list):
        return []
    hits: list[str] = []
    for term in terms:
        text = str(term or "").strip()
        if text and text.lower() in haystack:
            hits.append(text)
    return hits


def _persona_interest_signals(detail: dict[str, Any],
                              persona: dict[str, Any] | None) -> dict[str, Any]:
    persona = persona or {}
    hay = _haystack(detail)
    paper_id = detail.get("id")
    ptype = classify_paper_type(detail)
    accepted_ids = set(persona.get("accepted_paper_ids") or [])
    rejected_ids = set(persona.get("rejected_paper_ids") or [])
    accepted_by_feedback = False
    rejected_by_feedback = False
    for fb in persona.get("feedback_history") or []:
        target = str(fb.get("target") or "")
        if target == f"paper_id={paper_id}":
            action = str(fb.get("action") or "").lower()
            accepted_by_feedback = accepted_by_feedback or action == "accept"
            rejected_by_feedback = rejected_by_feedback or action == "reject"
    return {
        "preferredConceptHits": _term_hits(hay, persona.get("preferred_concepts")),
        "rejectedKeywordHits": _term_hits(hay, persona.get("rejected_keywords")),
        "acceptedKeywordHits": _term_hits(hay, persona.get("accepted_keywords")),
        "acceptedPaperId": paper_id in accepted_ids or accepted_by_feedback,
        "rejectedPaperId": paper_id in rejected_ids or rejected_by_feedback,
        "rejectedPaperType": (
            ptype if ptype in (persona.get("rejected_paper_types") or []) else ""
        ),
    }


def _has_persona_interest_signal(signals: dict[str, Any]) -> bool:
    for value in signals.values():
        if isinstance(value, list) and value:
            return True
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value:
            return True
    return False


def triage(detail: dict[str, Any], focus_tokens: list[str],
           persona: dict[str, Any] | None = None) -> tuple[str, int, int, int]:
    persona = persona or {}
    paper_id = detail.get("id")
    if paper_id in (persona.get("rejected_paper_ids") or []):
        return ("rejected_user", 0, 0, -1)
    ptype = classify_paper_type(detail)
    if ptype in (persona.get("rejected_paper_types") or []):
        return ("rejected_user", 0, 0, -1)
    hay = _haystack(detail)
    if not focus_tokens:
        return ("skip", 0, 0, 0)
    th = _token_hits(hay, focus_tokens)
    ch = _core_hits(hay)
    score = 10 * ch + th
    if ch >= 1 and th >= 2:
        bucket = "must_read"
    elif ch >= 1 and th >= 1:
        bucket = "skim"
    elif ch >= 2:
        bucket = "must_read"
    elif ch == 1:
        bucket = "skim"
    else:
        bucket = "skip"
    return (bucket, th, ch, score)


# ---------- Interaction state ----------

def _get_status(token: str, paper_id: int, kind: str, user_id: int) -> bool:
    path = "likes" if kind == "like" else "collects"
    try:
        data = unwrap(requests.get(
            f"{BASE_URL}/api/papers/{paper_id}/{path}",
            params={"userId": user_id}, timeout=TIMEOUT,
        ))
    except requests.HTTPError as exc:
        print(f"[warn] get {kind} status {paper_id} failed: {exc}",
              file=sys.stderr, flush=True)
        return False
    if isinstance(data, dict):
        for key in ("liked", "collected", "isLiked", "isCollected", "active"):
            if key in data:
                return bool(data[key])
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in ("liked", "collected", "isLiked", "isCollected", "active"):
                if key in inner:
                    return bool(inner[key])
    return False


def _bulk_get_status(token: str, paper_ids: list[int], user_id: int
                      ) -> dict[int, dict[str, bool]]:
    if not paper_ids:
        return {}
    if len(paper_ids) > 200:
        paper_ids = paper_ids[:200]
    try:
        data = unwrap(requests.get(
            f"{BASE_URL}/api/papers/interactions",
            headers=auth_headers(token),
            params={"paperIds": ",".join(str(p) for p in paper_ids),
                    "userId": user_id},
            timeout=TIMEOUT,
        ))
    except (requests.HTTPError, requests.ConnectionError, requests.Timeout,
            requests.RequestException) as exc:
        print(f"[warn] bulk get interactions ({len(paper_ids)} papers) "
              f"failed: {exc}; per-paper _get_status() will fall back",
              file=sys.stderr, flush=True)
        return {}
    out: dict[int, dict[str, bool]] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            pid = item.get("paperId")
            if pid is None:
                continue
            entry: dict[str, bool] = {}
            for src_key, dst_key in (("liked", "liked"), ("isLiked", "liked"),
                                      ("collected", "collected"),
                                      ("isCollected", "collected")):
                if src_key in item:
                    entry[dst_key] = bool(item[src_key])
                    break
            if not entry:
                inner = item.get("data")
                if isinstance(inner, dict):
                    for src_key, dst_key in (("liked", "liked"),
                                              ("collected", "collected")):
                        if src_key in inner:
                            entry[dst_key] = bool(inner[src_key])
            if entry:
                out[int(pid)] = entry
    return out


def _set_state(token: str, paper_id: int, kind: str, user_id: int,
               username: str, desired: bool, feedback_lang: str,
               bulk_status: dict[int, dict[str, bool]] | None = None
               ) -> dict[str, Any]:
    bulk = (bulk_status or {}).get(paper_id) or {}
    if kind == "like":
        current = bool(bulk.get("liked", False))
    else:
        current = bool(bulk.get("collected", False))
    if not bulk:
        current = _get_status(token, paper_id, kind, user_id)
    if current == desired:
        return {"ok": True, "skipped": True, "current": current, "desired": desired}
    path = "like" if kind == "like" else "collect"
    body = {"userId": user_id, "username": username}
    try:
        data = unwrap(requests.post(
            f"{BASE_URL}/api/papers/{paper_id}/{path}",
            headers=auth_headers(token), json=body, timeout=TIMEOUT,
        ))
        return {"ok": True, "skipped": False, "current": current, "desired": desired, "data": data}
    except requests.HTTPError as exc:
        return {"ok": False, "skipped": False, "error": str(exc),
                "status": exc.response.status_code if exc.response else None}


def _do_comment(token: str, paper_id: int, content: str) -> dict[str, Any]:
    body = {"content": content, "parentCommentId": None}
    try:
        data = unwrap(requests.post(
            f"{BASE_URL}/api/papers/{paper_id}/comments",
            headers=auth_headers(token), json=body, timeout=TIMEOUT,
        ))
        return {"ok": True, "data": data}
    except requests.HTTPError as exc:
        return {"ok": False, "error": str(exc),
                "status": exc.response.status_code if exc.response else None}


# ---------- LLM (4-step workflow) ----------























def _build_skim_summary(detail: dict[str, Any], lang: str) -> str:
    if lang == "zh-CN":
        fields = ("cn_script", "cn_abstract", "abstract", "eng_script")
    else:
        fields = ("eng_script", "abstract", "cn_abstract", "cn_script")
    for field in fields:
        text = (detail.get(field) or "").strip()
        if text:
            return text
    return ""






def load_interaction_state(home: Path) -> dict[str, Any]:
    state = load_json(home / "interaction_state.json", {})
    state.setdefault("replied_comment_ids", [])
    state.setdefault("liked_comment_ids", [])
    state.setdefault("processed_comment_ids", [])
    state.setdefault("commented_paper_ids", [])
    state.setdefault("updatedAt", None)
    return state


def save_interaction_state(home: Path, state: dict[str, Any]) -> None:
    for key in ("replied_comment_ids", "liked_comment_ids",
                "processed_comment_ids", "commented_paper_ids"):
        vals = state.get(key) or []
        state[key] = list(dict.fromkeys(str(v) for v in vals))[-1000:]
    state["updatedAt"] = utc_now_iso()
    save_json(home / "interaction_state.json", state)


def _comment_id(c: dict[str, Any]) -> str:
    for key in ("id", "commentId", "comment_id", "uuid"):
        if c.get(key) is not None:
            return str(c.get(key))
    return ""


def _comment_parent_id(c: dict[str, Any]) -> str:
    for key in ("parentCommentId", "parent_id", "parentId"):
        if c.get(key) is not None:
            return str(c.get(key))
    return ""


def _comment_author(c: dict[str, Any]) -> tuple[str, str]:
    author = c.get("user") or c.get("author") or {}
    if not isinstance(author, dict):
        author = {}
    uid = c.get("userId") or c.get("user_id") or author.get("userId") or author.get("id")
    name = c.get("username") or c.get("userName") or author.get("username") or author.get("name")
    return (str(uid or ""), str(name or ""))


def _comment_content(c: dict[str, Any]) -> str:
    return str(c.get("content") or c.get("text") or c.get("body") or "").strip()


def _comment_liked(c: dict[str, Any]) -> bool | None:
    for key in ("liked", "isLiked", "commentLiked", "active"):
        if key in c:
            return bool(c[key])
    return None


def _flatten_comments(comments: Any, parent_id: str = "") -> list[dict[str, Any]]:
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
        cc.setdefault("_parentId", parent_id or _comment_parent_id(cc))
        out.append(cc)
        cid = _comment_id(cc)
        for child_key in ("replies", "children"):
            if isinstance(cc.get(child_key), list):
                out.extend(_flatten_comments(cc[child_key], parent_id=cid))
    return out


def get_comments(paper_id: int, user_id: int) -> list[dict[str, Any]]:
    try:
        data = unwrap(requests.get(
            f"{BASE_URL}/api/papers/{paper_id}/comments",
            params={"userId": user_id}, timeout=TIMEOUT,
        ))
    except (requests.HTTPError, requests.ConnectionError, requests.Timeout,
            requests.RequestException, RuntimeError) as exc:
        print(f"[warn] comments for paper {paper_id} failed: {exc}",
              file=sys.stderr, flush=True)
        return []
    return _flatten_comments(data)


def _do_reply(token: str, paper_id: int, parent_comment_id: str,
              content: str) -> dict[str, Any]:
    try:
        data = unwrap(requests.post(
            f"{BASE_URL}/api/papers/{paper_id}/comments",
            headers=auth_headers(token),
            json={"content": content, "parentCommentId": parent_comment_id},
            timeout=TIMEOUT,
        ))
        return {"ok": True, "data": data}
    except requests.HTTPError as exc:
        return {"ok": False, "error": str(exc),
                "status": exc.response.status_code if exc.response else None}


def _do_comment_like(token: str, comment_id: str, user_id: int,
                     username: str) -> dict[str, Any]:
    try:
        data = unwrap(requests.post(
            f"{BASE_URL}/api/comments/{comment_id}/like",
            headers=auth_headers(token),
            json={"userId": user_id, "username": username},
            timeout=TIMEOUT,
        ))
        return {"ok": True, "data": data}
    except requests.HTTPError as exc:
        return {"ok": False, "error": str(exc),
                "status": exc.response.status_code if exc.response else None}


def _draft_reply(paper: dict[str, Any], comment: dict[str, Any], lang: str) -> str:
    """Template fallback for reply text. v3.1: agent writes the actual
    reply in its own context; this is a placeholder that should not be
    used in production. Kept for backwards compatibility / testing."""
    title = str(paper.get("title") or "")[:180]
    if lang == "zh-CN":
        return (f"我也在看《{title}》。你这个点很有价值；从平台摘要看，"
                f"我会进一步关注它是否把核心假设、评测设置和失败案例讲清楚。"
                f"如果后续有更多实验细节，尤其是和检索或多模态证据相关的消融，"
                f"我也想继续跟进。")
    return (f"I am also reading \"{title}\". Your point is useful; from the "
            f"platform metadata, I would next check whether the paper clearly "
            f"separates its core assumption, evaluation setup, and failure "
            f"cases. If more details appear, especially around retrieval or "
            f"multimodal evidence, I would like to keep following this thread.")


def process_comment_interactions(token: str, user_id: int, username: str,
                                  papers: list[dict[str, Any]], policy: dict[str, Any],
                                  state: dict[str, Any], comment_lang: str,
                                  dry_run: bool = False
                                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    allow_reply = bool(policy.get("allowAutoReply", True))
    allow_comment_like = bool(policy.get("allowAutoCommentLike", True))
    max_replies = int(policy.get("maxRepliesPerDailyRun", DEFAULT_MAX_REPLIES_PER_RUN) or 0)
    max_likes = int(policy.get("maxCommentLikesPerDailyRun", DEFAULT_MAX_COMMENT_LIKES_PER_RUN) or 0)
    max_scan_papers = int(policy.get("maxCommentScanPapersPerRun", 15) or 15)
    if dry_run:
        max_scan_papers = min(
            max_scan_papers,
            int(policy.get("dryRunMaxCommentScanPapers", DEFAULT_DRY_RUN_COMMENT_SCAN_PAPERS)
                or DEFAULT_DRY_RUN_COMMENT_SCAN_PAPERS),
        )
    reply_scope = policy.get("replyScope") or "same_paper_discussion"
    proposals: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    scanned = 0
    reply_proposed = 0
    like_proposed = 0
    seen_papers: set[int] = set()
    replied_ids = set(str(x) for x in state.get("replied_comment_ids", []))
    liked_ids = set(str(x) for x in state.get("liked_comment_ids", []))
    processed_ids = set(str(x) for x in state.get("processed_comment_ids", []))
    for paper in papers:
        if len(seen_papers) >= max_scan_papers:
            break
        paper_id = paper.get("paperId") or paper.get("id")
        if paper_id is None:
            continue
        try:
            pid = int(paper_id)
        except (TypeError, ValueError):
            continue
        if pid in seen_papers:
            continue
        seen_papers.add(pid)
        comments = get_comments(pid, user_id)
        scanned += len(comments)
        for c in comments:
            cid = _comment_id(c)
            if not cid:
                continue
            author_id, author_name = _comment_author(c)
            is_self = author_id == str(user_id) or (
                author_name and author_name == username)
            content = _comment_content(c)
            if not content:
                continue
            evidence_refs = [
                f"paper:{pid}:summary",
                f"paper:{pid}:comment:{cid}",
            ]
            if (allow_comment_like and like_proposed < max_likes
                    and not is_self and cid not in liked_ids):
                liked_field = _comment_liked(c)
                if liked_field is not True:
                    action_id = f"commentlike_{today_stamp()}_{like_proposed + 1:03d}"
                    proposals.append({
                        "actionId": action_id, "actionType": "comment_like",
                        "paperId": pid, "commentId": cid,
                        "title": paper.get("title"),
                        "reason": "same-paper discussion comment is eligible for acknowledgement",
                        "evidenceRefs": evidence_refs,
                        "riskLevel": "external_write",
                        "requiresApproval": False, "status": "proposed",
                    })
                    like_proposed += 1
            if (allow_reply and reply_proposed < max_replies and not is_self
                    and cid not in replied_ids and cid not in processed_ids
                    and reply_scope == "same_paper_discussion"):
                action_id = f"reply_{today_stamp()}_{reply_proposed + 1:03d}"
                proposals.append({
                    "actionId": action_id, "actionType": "reply",
                    "paperId": pid, "commentId": cid,
                    "parentCommentId": cid,
                    "title": paper.get("title"),
                    "contentSlot": "external_agent_required",
                    "contentLanguage": comment_lang,
                    "reason": "external agent may reply if it can add evidence-backed research context",
                    "evidenceRefs": evidence_refs,
                    "needsUserInput": False,
                    "riskLevel": "external_write", "requiresApproval": False,
                    "status": "proposed",
                })
                reply_proposed += 1
    summary = {
        "scannedComments": scanned,
        "scannedPapers": len(seen_papers),
        "scanLimitPapers": max_scan_papers,
        "scanLimited": len(seen_papers) >= max_scan_papers,
        "replyProposals": sum(1 for p in proposals if p.get("actionType") == "reply"),
        "commentLikeProposals": sum(1 for p in proposals if p.get("actionType") == "comment_like"),
        "replyResults": 0,
        "commentLikeResults": 0,
        "dryRun": dry_run,
        "mode": "proposal_only",
    }
    return proposals, results, summary


def _paper_identity(paper: dict[str, Any]) -> int | str | None:
    return paper.get("paperId") or paper.get("id")


def _merge_unique_by_key(existing: list[dict[str, Any]],
                         incoming: list[dict[str, Any]],
                         key: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in [*existing, *incoming]:
        if not isinstance(item, dict):
            continue
        value = item.get(key)
        if value is None and key == "paperId":
            value = item.get("id")
        if value is None:
            value = f"idx:{len(order)}"
        skey = str(value)
        if skey not in merged:
            order.append(skey)
            merged[skey] = dict(item)
        else:
            merged[skey].update({k: v for k, v in item.items() if v not in (None, "", [])})
    return [merged[k] for k in order]


def _cap_recommendations(must_read: list[dict[str, Any]],
                         skim: list[dict[str, Any]],
                         limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if limit <= 0:
        limit = 20
    ordered = [("must_read", p) for p in must_read] + [("skim", p) for p in skim]
    kept = ordered[:limit]
    removed = ordered[limit:]
    capped_must = [p for bucket, p in kept if bucket == "must_read"]
    capped_skim = [p for bucket, p in kept if bucket == "skim"]
    changes = []
    for bucket, paper in removed:
        changes.append({
            "paperId": _paper_identity(paper),
            "title": paper.get("title"),
            "fromBucket": bucket,
            "toBucket": "overflow",
            "reason": "digestPaperLimit",
            "changedAt": utc_now_iso(),
        })
    return capped_must, capped_skim, changes


def _proposal_evidence_refs(paper: dict[str, Any]) -> list[str]:
    pid = _paper_identity(paper)
    refs = [f"paper:{pid}:summary", f"paper:{pid}:recommendation"]
    if paper.get("key_fig_url"):
        refs.append(f"paper:{pid}:key_fig")
    if paper.get("key_tab_url"):
        refs.append(f"paper:{pid}:key_tab")
    return refs


def _build_action_proposals_for_papers(
    ranked_papers: list[dict[str, Any]],
    comment_lang: str,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    seq = 1
    action_policy = {
        "like": bool(policy.get("allowAutoLike", True)),
        "collect": bool(policy.get("allowAutoCollect", True)),
        "comment": bool(policy.get("allowAutoComment", True)),
    }
    for paper in ranked_papers:
        pid = _paper_identity(paper)
        if pid is None:
            continue
        bucket = paper.get("bucket") or (
            "must_read" if paper in ranked_papers else "skim"
        )
        for action_type in ("like", "collect", "comment"):
            if action_type == "comment" and bucket != "must_read":
                continue
            proposal = {
                "actionId": f"{action_type}_{today_stamp()}_{seq:03d}",
                "actionType": action_type,
                "paperId": pid,
                "title": paper.get("title", ""),
                "reason": (
                    f"{bucket}: score={paper.get('score', 0)}; "
                    "external agent must provide content for comments"
                ),
                "evidenceRefs": _proposal_evidence_refs(paper),
                "dryRun": False,
                "status": "proposed" if action_policy[action_type] else "skipped",
                "skipReason": "" if action_policy[action_type] else "policy_disabled",
            }
            if action_type == "comment":
                proposal["contentSlot"] = "external_agent_required"
                proposal["contentLanguage"] = comment_lang
            proposals.append(proposal)
            seq += 1
    return proposals


def _load_today_digest(run_dir: Path) -> dict[str, Any]:
    digest = load_json(run_dir / "daily_digest.json", {})
    return digest if isinstance(digest, dict) else {}


def _merge_digest(existing: dict[str, Any], incoming: dict[str, Any],
                  policy: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        existing = {}
    out = dict(existing)
    for key, value in incoming.items():
        if key not in {
            "mustRead",
            "skim",
            "skip",
            "actionResults",
            "actionProposals",
            "replyProposals",
            "replyResults",
            "selectionChanges",
            "discussionStatus",
            "sourceStatus",
        }:
            out[key] = value
    must = _merge_unique_by_key(existing.get("mustRead") or [],
                                incoming.get("mustRead") or [], "paperId")
    skim = _merge_unique_by_key(existing.get("skim") or [],
                                incoming.get("skim") or [], "paperId")
    limit = int(policy.get("digestPaperLimit", 20) or 20)
    must, skim, limit_changes = _cap_recommendations(must, skim, limit)
    out["mustRead"] = must
    out["skim"] = skim
    out["selectedPapers"] = [
        {"paperId": p.get("paperId"), "title": p.get("title"), "bucket": "must_read"}
        for p in must
    ] + [
        {"paperId": p.get("paperId"), "title": p.get("title"), "bucket": "skim"}
        for p in skim
    ]
    out["selectionChanges"] = [
        *(existing.get("selectionChanges") or []),
        *(incoming.get("selectionChanges") or []),
        *limit_changes,
    ][-500:]
    out["skip"] = _merge_unique_by_key(existing.get("skip") or [],
                                       incoming.get("skip") or [], "paperId")
    out["skip_total"] = len(out["skip"])
    out["skip_displayed"] = min(
        len(out["skip"]), int(policy.get("skipDisplayLimit", 10) or 10)
    )
    out["actionResults"] = [
        *(existing.get("actionResults") or []),
        *(incoming.get("actionResults") or []),
    ][-1000:]
    out["actionProposals"] = incoming.get("actionProposals") or existing.get("actionProposals") or []
    out["replyProposals"] = _merge_unique_by_key(
        existing.get("replyProposals") or [],
        incoming.get("replyProposals") or [],
        "actionId",
    )
    out["replyResults"] = [
        *(existing.get("replyResults") or []),
        *(incoming.get("replyResults") or []),
    ][-1000:]
    out["discussionStatus"] = {
        **(existing.get("discussionStatus") or {}),
        **(incoming.get("discussionStatus") or {}),
    }
    out["sourceStatus"] = {
        **(existing.get("sourceStatus") or {}),
        **(incoming.get("sourceStatus") or {}),
    }
    out["updatedAt"] = utc_now_iso()
    return out


def _rerender_digest_files(run_dir: Path, digest: dict[str, Any],
                           stored_lang: str, digest_lang: str,
                           inline_images: bool) -> None:
    save_json(run_dir / "daily_digest.json", digest)
    (run_dir / f"daily_digest.{stored_lang}.md").write_text(
        render_digest_md(digest, digest_lang), encoding="utf-8",
    )
    html_text = _render_digest_html(digest, stored_lang,
                                    inline_images=inline_images)
    (run_dir / f"daily_digest.{stored_lang}.html").write_text(
        html_text, encoding="utf-8",
    )


def _extract_actions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        actions = payload.get("actions")
        if isinstance(actions, list):
            return [a for a in actions if isinstance(a, dict)]
    return []


def _content_quality_gate(action: dict[str, Any]) -> tuple[bool, str]:
    atype = action.get("actionType")
    if atype not in ("comment", "reply"):
        return (True, "")
    content = str(action.get("content") or "").strip()
    if not content:
        return (False, "missing_content")
    if len(content) < 20 or len(content) > 300:
        return (False, "bad_length")
    lowered = content.lower()
    placeholders = (
        "todo", "tbd", "placeholder", "lorem ipsum", "<content>",
        "待补充", "占位", "这里写", "关键词", "关键字",
    )
    if any(p in lowered for p in placeholders):
        return (False, "placeholder_detected")
    if "???" in content or "\ufffd" in content:
        return (False, "garbled_text_detected")
    words = re.findall(r"[\w\u4e00-\u9fff]+", content)
    unique_words = set(words)
    if len(words) >= 8 and len(unique_words) <= 3:
        return (False, "keyword_string_detected")
    refs = action.get("evidenceRefs")
    if not isinstance(refs, list) or len([r for r in refs if r]) < 2:
        return (False, "insufficient_evidence")
    return (True, "")


def _validate_action_schema(action: dict[str, Any]) -> tuple[bool, str]:
    atype = action.get("actionType")
    if atype not in SUPPORTED_ACTION_TYPES:
        return (False, "unsupported_action")
    if not action.get("reason"):
        return (False, "missing_reason")
    if atype in ("like", "collect", "comment", "reply",
                 "feedback_reject", "feedback_accept"):
        if action.get("paperId") is None:
            return (False, "missing_paperId")
    if atype == "comment_like" and action.get("commentId") is None:
        return (False, "missing_commentId")
    if atype == "reply" and not (
        action.get("parentCommentId") or action.get("commentId")
    ):
        return (False, "missing_parentCommentId")
    return _content_quality_gate(action)


def _result_for_skip(action: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "actionId": action.get("actionId"),
        "actionType": action.get("actionType"),
        "paperId": action.get("paperId"),
        "commentId": action.get("commentId"),
        "parentCommentId": action.get("parentCommentId"),
        "title": action.get("title"),
        "reason": action.get("reason", ""),
        "evidenceRefs": action.get("evidenceRefs") or [],
        "skipped": True,
        "skipReason": reason,
        "platform": {"ok": False, "skipped": True, "reason": reason},
        "executedAt": utc_now_iso(),
    }


def _apply_feedback_action(home: Path, action: dict[str, Any],
                           dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dryRun": True, "localOnly": True}
    persona = load_json(home / "persona.json", {})
    persona.setdefault("rejected_paper_ids", [])
    persona.setdefault("feedback_history", [])
    pid = action.get("paperId")
    atype = action.get("actionType")
    if atype == "feedback_reject":
        if pid not in persona["rejected_paper_ids"]:
            persona["rejected_paper_ids"].append(pid)
        feedback_action = "reject"
    else:
        persona["rejected_paper_ids"] = [
            x for x in persona.get("rejected_paper_ids", []) if x != pid
        ]
        persona.setdefault("accepted_paper_ids", [])
        if pid not in persona["accepted_paper_ids"]:
            persona["accepted_paper_ids"].append(pid)
        feedback_action = "accept"
    persona["feedback_history"].append({
        "timestamp": utc_now_iso(),
        "action": feedback_action,
        "target": f"paper_id={pid}",
        "reason": action.get("reason", ""),
        "source": "execute-actions",
    })
    persona["feedback_history"] = persona["feedback_history"][-200:]
    persona["updatedAt"] = utc_now_iso()
    save_json(home / "persona.json", persona)
    return {"ok": True, "localOnly": True}


def _comment_like_already_active(paper_id: int | None, comment_id: str,
                                 user_id: int) -> bool:
    if paper_id is None:
        return False
    for comment in get_comments(paper_id, user_id):
        if _comment_id(comment) == comment_id:
            return _comment_liked(comment) is True
    return False


def _action_policy_and_rate(
    action: dict[str, Any],
    policy: dict[str, Any],
    engagement_state: dict[str, Any],
) -> tuple[bool, str, str | None]:
    import engagement as _eng
    atype = action.get("actionType")
    mapping = {
        "like": ("autoLike", "postLike"),
        "collect": ("autoCollect", "postCollect"),
        "comment": ("autoComment", "comment"),
        "reply": ("autoReply", "reply"),
        "comment_like": ("autoCommentLike", "commentLike"),
    }
    if atype not in mapping:
        return (True, "", None)
    capability, rate_action = mapping[atype]
    ok, reason = _eng.can_perform(
        policy,
        capability,
        engagement_state.get("trustLevel", "new"),
        user_approved=bool(action.get("userApproved")),
    )
    if not ok:
        return (False, f"policy_or_trust:{reason}", rate_action)
    can, can_reason, _ = _eng.can_act(engagement_state, rate_action)
    if not can:
        return (False, f"rate_limited:{can_reason}", rate_action)
    return (True, "", rate_action)


def _execute_one_action(
    home: Path,
    action: dict[str, Any],
    token: str,
    user_id: int,
    username: str,
    policy: dict[str, Any],
    engagement_state: dict[str, Any],
    interaction_state: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    ok, reason = _validate_action_schema(action)
    if not ok:
        return _result_for_skip(action, reason)
    action_dry_run = dry_run or bool(action.get("dryRun"))
    ok, reason, rate_action = _action_policy_and_rate(action, policy, engagement_state)
    if not ok:
        return _result_for_skip(action, reason)
    atype = action["actionType"]
    pid = action.get("paperId")
    result: dict[str, Any]
    if action_dry_run:
        result = {"ok": True, "dryRun": True}
    elif atype == "like":
        result = _set_state(token, int(pid), "like", user_id, username,
                            desired=True, feedback_lang=DEFAULT_LANG)
    elif atype == "collect":
        result = _set_state(token, int(pid), "collect", user_id, username,
                            desired=True, feedback_lang=DEFAULT_LANG)
    elif atype == "comment":
        result = _do_comment(token, int(pid), str(action["content"]).strip())
    elif atype == "reply":
        parent_id = str(action.get("parentCommentId") or action.get("commentId"))
        result = _do_reply(token, int(pid), parent_id,
                           str(action["content"]).strip())
    elif atype == "comment_like":
        comment_id = str(action["commentId"])
        paper_id_int = int(pid) if pid is not None else None
        if _comment_like_already_active(paper_id_int, comment_id, user_id):
            result = {"ok": True, "skipped": True, "current": True}
        else:
            result = _do_comment_like(token, comment_id, user_id, username)
    elif atype in ("feedback_reject", "feedback_accept"):
        result = _apply_feedback_action(home, action, action_dry_run)
    else:
        result = {"ok": False, "error": "unsupported_action"}

    if result.get("ok") and not action_dry_run:
        import engagement as _eng
        if rate_action:
            _eng.record_action(
                engagement_state,
                rate_action,
                paper_id=int(pid) if pid is not None else None,
                comment_id=str(action.get("commentId")) if action.get("commentId") else None,
                parent_id=str(action.get("parentCommentId")) if action.get("parentCommentId") else None,
            )
        if atype == "comment":
            interaction_state.setdefault("commented_paper_ids", []).append(str(pid))
            post_user_behavior(token, user_id, username, "paper_comment",
                               paper_id=int(pid), result_state="active",
                               source="execute-actions")
        elif atype == "reply":
            cid = str(action.get("parentCommentId") or action.get("commentId"))
            interaction_state.setdefault("replied_comment_ids", []).append(cid)
            interaction_state.setdefault("processed_comment_ids", []).append(cid)
            post_user_behavior(token, user_id, username, "paper_comment_reply",
                               paper_id=int(pid), result_state="active",
                               source="execute-actions")
        elif atype == "comment_like":
            interaction_state.setdefault("liked_comment_ids", []).append(
                str(action.get("commentId"))
            )
            if pid is not None:
                post_user_behavior(token, user_id, username, "comment_like",
                                   paper_id=int(pid), result_state="active",
                                   source="execute-actions")

    content = str(action.get("content") or "")
    return {
        "actionId": action.get("actionId"),
        "actionType": atype,
        "paperId": pid,
        "commentId": action.get("commentId"),
        "parentCommentId": action.get("parentCommentId"),
        "title": action.get("title"),
        "reason": action.get("reason", ""),
        "evidenceRefs": action.get("evidenceRefs") or [],
        "content_full": content,
        "commentContent": content if atype == "comment" else "",
        "replyContent": content if atype == "reply" else "",
        "skipped": bool(result.get("skipped")),
        "dryRun": action_dry_run,
        "platform": result,
        "executedAt": utc_now_iso(),
    }


# ---------- Time ----------

def today_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- Markdown rendering ----------

def _extract_keywords(p: dict[str, Any], lang: str) -> list[str]:
    if lang == "zh-CN":
        kws = p.get("cn_keywords") or p.get("eng_keywords") or []
    else:
        kws = p.get("eng_keywords") or p.get("cn_keywords") or []
    if not isinstance(kws, list):
        return []
    return [str(k) for k in kws if k]


def _fmt_paper_meta_line(p: dict[str, Any], lang: str) -> list[str]:
    out: list[str] = []
    authors = p.get("plain_authors") or ""
    affils_zh = p.get("cn_affiliation_names") or []
    affils_en = p.get("eng_affiliation_names") or []
    if lang == "zh-CN":
        affils = affils_zh or affils_en
    else:
        affils = affils_en or affils_zh
    if authors:
        s = authors
        if len(s) > 180:
            s = s[:177].rstrip() + "..."
        if affils:
            s += f"  _({', '.join(affils[:4])}{'...' if len(affils) > 4 else ''})_"
        out.append(f"- **{t(lang, 'label_authors')}:** {s}")
    ext = p.get("external_id") or ""
    pub = p.get("pub_url") or ""
    if ext and pub:
        out.append(f"- **{t(lang, 'label_arxiv')}:** [{ext}]({pub})")
    elif ext:
        out.append(f"- **{t(lang, 'label_arxiv')}:** {ext}")
    cat = p.get("arxiv_categories")
    if isinstance(cat, list):
        cat_str = ", ".join(cat[:5])
    elif isinstance(cat, str) and cat:
        cat_str = cat
    else:
        cat_str = ""
    if cat_str:
        out.append(f"- **{t(lang, 'label_category')}:** {cat_str}")
    pub_date = (p.get("publication_date") or "")[:10]
    cite = p.get("citation_count") or 0
    stars = p.get("github_stars") or 0
    code = p.get("code_url") or ""
    misc_bits: list[str] = []
    if pub_date:
        misc_bits.append(f"{t(lang, 'label_published')}: {pub_date}")
    if cite:
        misc_bits.append(f"寮曠敤: {cite}" if lang == "zh-CN" else f"citations: {cite}")
    if stars:
        misc_bits.append(f"[github] {stars} stars")
    if misc_bits:
        out.append(f"- {' | '.join(misc_bits)}")
    if code:
        out.append(f"- **{t(lang, 'label_code')}:** [{code}]({code})")
    return out


def _source_tag_label(tag: str, lang: str) -> str:
    if tag.startswith("newest:"):
        return ("最新 " if lang == "zh-CN" else "newest ") + tag[len("newest:"):]
    if tag == "recommendations":
        return "个性推荐" if lang == "zh-CN" else "recommendations"
    if tag.startswith("interest_search:"):
        q = tag[len("interest_search:"):]
        return ("兴趣搜索: " if lang == "zh-CN" else "interest: ") + q
    if tag.startswith("huggingface:"):
        return "Hugging Face"
    return tag


def _fmt_source_tags(tags: list[str], lang: str) -> str:
    if not tags:
        return ""
    return ", ".join(_source_tag_label(t, lang) for t in tags[:6])


def _fmt_escape_md(s: str) -> str:
    return s.replace("|", "\\|")


# ---------- HTML rendering (self-contained, images inlined as data URIs) ----------

def _html_escape(s: str) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _inline_image_as_data_uri(url: str, max_bytes: int = 5_000_000,
                               timeout: int = 8) -> str | None:
    """Download an image and return a data: URI string for inline embedding.

    Returns None on any failure (network/timeout/size/non-image) so the
    caller can fall back to the original URL.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "").lower()
        if not content_type.startswith("image/"):
            return None
        data = b""
        for chunk in resp.iter_content(chunk_size=64_000):
            data += chunk
            if len(data) > max_bytes:
                return None
        if not data:
            return None
        import base64
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception:
        return None


def _render_digest_html(digest: dict[str, Any], lang: str,
                         inline_images: bool = True) -> str:
    """Light-themed, self-contained HTML companion for daily_digest.{lang}.md.

    When inline_images is true, the runner downloads each key figure and
    embeds it as a data: URI so the file renders fully offline in any
    browser. Failed downloads fall back to the original URL.
    """
    css = """
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;max-width:920px;margin:24px auto;padding:0 20px;color:#1a1a1a;line-height:1.55;background:#fafafa}
    h1{font-size:28px;border-bottom:2px solid #2c5282;padding-bottom:8px}
    h3{font-size:17px;margin-top:24px;color:#2c5282}
    h4{font-size:15px;margin-top:18px;color:#2d3748}
    .meta{color:#4a5568;font-size:14px}
    .meta b{color:#1a1a1a}
    .paper{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:14px 18px;margin:14px 0}
    .paper img{max-width:100%;height:auto;border:1px solid #cbd5e0;border-radius:4px;margin:6px 0}
    blockquote{background:#f7fafc;border-left:3px solid #cbd5e0;padding:8px 14px;margin:10px 0;color:#2d3748;font-size:14px}
    code{background:#edf2f7;padding:1px 6px;border-radius:3px;font-size:13px;color:#c53030}
    .footer{color:#718096;font-size:12px;margin-top:40px;padding-top:14px;border-top:1px solid #e2e8f0}
    .action-stats{margin:6px 0 12px;font-size:14px}
    .stat{display:inline-block;margin-right:14px;padding:2px 10px;border-radius:12px;background:#edf2f7}
    .stat.like{background:#fed7d7;color:#c53030}
    .stat.collect{background:#fefcbf;color:#975a16}
    .stat.comment{background:#bee3f8;color:#2a4365}
    .muted{color:#718096}
    .action-card{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:14px 18px;margin:12px 0}
    .action-title{margin-top:0}
    .stance-pill{display:inline-block;padding:2px 8px;border-radius:10px;background:#e2e8f0;font-size:12px;margin-left:6px}
    .stance-critique{background:#fed7d7;color:#c53030}
    .stance-support{background:#c6f6d5;color:#276749}
    .stance-discussion{background:#bee3f8;color:#2a4365}
    .stance-thinking{background:#fefcbf;color:#975a16}
    .paper-id{color:#a0aec0;font-size:12px;font-weight:normal;margin-left:8px}
    .empty{color:#a0aec0;font-style:italic}
    /* Collapsible sections: each <h2> is wrapped in <details open><summary> */
    details.digest-section{margin-top:24px;border:2px solid #a0aec0;border-radius:8px;background:#fff;overflow:hidden}
    details.digest-section>summary{font-size:22px;font-weight:700;color:#1a365d;background:#e2e8f0;padding:14px 18px;cursor:pointer;list-style:none}
    details.digest-section>summary::-webkit-details-marker{display:none}
    details.digest-section>.digest-body{padding:4px 14px 18px}
    .paper-recommendations{border-color:#90cdf4}
    .behavior-summary{border-color:#f6ad55}
    .gate-reason{display:inline-block;background:#fff5f5;color:#9b2c2c;border:1px solid #fed7d7;border-radius:10px;padding:1px 8px;font-size:12px;margin-left:6px}
    details.section{margin-top:18px;border:1px solid #cbd5e0;border-radius:8px;background:#fff;overflow:hidden}
    details.section>summary{font-size:20px;font-weight:600;color:#2c5282;background:#edf2f7;padding:12px 16px;cursor:pointer;list-style:none;display:flex;align-items:center;user-select:none;border-bottom:1px solid #cbd5e0}
    details.section>summary::-webkit-details-marker{display:none}
    details.section>summary::before{content:'鈻?;display:inline-block;margin-right:10px;font-size:13px;color:#718096;transition:transform 0.15s}
    details.section[open]>summary::before{transform:rotate(90deg)}
    details.section>summary:hover{background:#e2e8f0}
    details.section>summary .sec-count{font-size:14px;font-weight:normal;color:#4a5568;margin-left:10px}
    details.section>summary .sec-toggle{font-size:12px;color:#718096;margin-left:auto;padding:2px 8px;border:1px solid #cbd5e0;border-radius:10px;background:#fff}
    details.section>summary .sec-toggle:hover{background:#edf2f7;color:#2c5282}
    details.section>.sec-body{padding:8px 16px 16px}
    /* Toolbar at top */
    .toolbar{position:sticky;top:0;background:#fafafa;padding:10px 0;border-bottom:1px solid #e2e8f0;margin:0 -20px 18px;padding-left:20px;padding-right:20px;z-index:10;display:flex;gap:8px;align-items:center;font-size:13px;color:#4a5568}
    .toolbar button{background:#fff;border:1px solid #cbd5e0;border-radius:4px;padding:4px 12px;cursor:pointer;color:#2c5282;font-size:13px}
    .toolbar button:hover{background:#edf2f7}
    .toolbar .hint{margin-left:auto;color:#718096}
    """
    out: list[str] = [
        f"<!DOCTYPE html><html lang=\"{_html_escape(lang)}\"><head><meta charset=\"UTF-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{_html_escape(t(lang, 'digest_title', date=digest['date']))}</title>",
        f"<style>{css}</style>",
        # Toolbar JS: collapse/expand all + per-summary click prevention on toggle button
        "<script>",
        "function setAll(open){",
        "  document.querySelectorAll('details.section,details.digest-section').forEach(function(d){d.open=open;});",
        "  var c=document.getElementById('btn-collapse');",
        "  var e=document.getElementById('btn-expand');",
        "  if(c)c.style.display=open?'none':'';",
        "  if(e)e.style.display=open?'':'none';",
        "}",
        "document.addEventListener('click',function(ev){",
        "  if(ev.target.classList && ev.target.classList.contains('sec-toggle')){",
        "    ev.preventDefault();ev.stopPropagation();",
        "    var d=ev.target.closest('details.section,details.digest-section');",
        "    if(d){var anyOpen=!!document.querySelector('details.section[open],details.digest-section[open]');setAll(anyOpen);}",
        "  }",
        "});",
        "</script>",
        "</head><body>",
        f"<h1>{_html_escape(t(lang, 'digest_title', date=digest['date']))}</h1>",
        # Sticky toolbar
        "<div class='toolbar'>",
        "<button id='btn-collapse' onclick='setAll(false)'>全部折叠 / Collapse all</button>",
        "<button id='btn-expand' style='display:none' onclick='setAll(true)'>全部展开 / Expand all</button>",
        "<span class='hint'>点击区段标题折叠/展开；工具栏可一键切换</span>",
        "</div>",
        f"<p class='meta'><b>{_html_escape(t(lang, 'user_label'))}:</b> "
        f"{_html_escape(digest['username'])} (id={digest['userId']})<br>",
        f"<b>{_html_escape(t(lang, 'label_overview'))}:</b> "
        f"{_html_escape(digest['summary'])}</p>",
    ]
    src = digest.get("discoverySources") or {}
    if src:
        bits = []
        if "newest" in src:
            bits.append(f"newest={src.get('newest', 0)}")
        if "recommendations" in src:
            bits.append(f"recommendations={src.get('recommendations', 0)}")
        if "huggingface_daily" in src:
            bits.append(f"hf_daily={src.get('huggingface_daily', 0)}")
        if "interest_total" in src:
            bits.append(f"interest_search={src.get('interest_total', 0)}")
        if bits:
            out.append(
                f"<p class='meta'><b>{_html_escape(t(lang, 'label_discovery_sources'))}:</b> "
                + _html_escape(" | ".join(bits)) + "</p>"
            )

    def _keywords_html(p: dict[str, Any]) -> str:
        kws = _extract_keywords(p, lang)
        if not kws:
            return ""
        return (f"<div class='meta'><i>{_html_escape(t(lang, 'label_keywords'))}:</i> "
                + " ".join(f"<code>#{_html_escape(k)}</code>" for k in kws)
                + "</div>")

    def _src_html(p: dict[str, Any]) -> str:
        tags = p.get("source_tags") or []
        if not tags:
            return ""
        label = _fmt_source_tags(tags, lang)
        return f"<div class='meta'><i>{_html_escape(t(lang, 'label_source'))}:</i> {_html_escape(label)}</div>"

    def _img_html(url: str) -> str:
        if not url:
            return ""
        if inline_images:
            data_uri = _inline_image_as_data_uri(url)
            if data_uri:
                return f"<img src='{data_uri}' alt='{_html_escape(t(lang, 'label_fig_alt'))}'>"
        return f"<img src='{_html_escape(url)}' alt='{_html_escape(t(lang, 'label_fig_alt'))}'>"

    def _meta_lines_html(p: dict[str, Any]) -> str:
        lines: list[str] = []
        authors = p.get("plain_authors") or ""
        affils_zh = p.get("cn_affiliation_names") or []
        affils_en = p.get("eng_affiliation_names") or []
        if lang == "zh-CN":
            affils = affils_zh or affils_en
        else:
            affils = affils_en or affils_zh
        if authors:
            s = authors
            if len(s) > 200:
                s = s[:197].rstrip() + "..."
            if affils:
                s += f" <i>({', '.join(affils[:4])}{'...' if len(affils) > 4 else ''})</i>"
            lines.append(f"<div class='meta'><b>{_html_escape(t(lang, 'label_authors'))}:</b> {_html_escape(s)}</div>")
        ext = p.get("external_id") or ""
        pub = p.get("pub_url") or ""
        if ext and pub:
            lines.append(f"<div class='meta'><b>{_html_escape(t(lang, 'label_arxiv'))}:</b> "
                         f"<a href='{_html_escape(pub)}' target='_blank'>{_html_escape(ext)}</a></div>")
        elif ext:
            lines.append(f"<div class='meta'><b>{_html_escape(t(lang, 'label_arxiv'))}:</b> {_html_escape(ext)}</div>")
        cat = p.get("arxiv_categories")
        if isinstance(cat, list):
            cat_str = ", ".join(cat[:5])
        elif isinstance(cat, str) and cat:
            cat_str = cat
        else:
            cat_str = ""
        if cat_str:
            lines.append(f"<div class='meta'><b>{_html_escape(t(lang, 'label_category'))}:</b> {_html_escape(cat_str)}</div>")
        pub_date = (p.get("publication_date") or "")[:10]
        cite = p.get("citation_count") or 0
        stars = p.get("github_stars") or 0
        code = p.get("code_url") or ""
        misc: list[str] = []
        if pub_date:
            misc.append(f"{_html_escape(t(lang, 'label_published'))}: {_html_escape(pub_date)}")
        if cite:
            misc.append(f"引用: {cite}" if lang == "zh-CN" else f"citations: {cite}")
        if stars:
            misc.append(f"github {stars} stars")
        if misc:
            lines.append(f"<div class='meta'>{_html_escape(' | '.join(misc))}</div>")
        if code:
            lines.append(f"<div class='meta'><b>{_html_escape(t(lang, 'label_code'))}:</b> "
                         f"<a href='{_html_escape(code)}' target='_blank'>{_html_escape(code)}</a></div>")
        return "\n".join(lines)

    reco_count = len(digest.get("mustRead") or []) + len(digest.get("skim") or [])
    if lang == "zh-CN":
        reco_title = f"论文推荐 <span class='sec-count'>{reco_count} 篇</span>"
    else:
        reco_title = f"Paper Recommendations <span class='sec-count'>{reco_count}</span>"
    out.append(
        "<details class=\"digest-section paper-recommendations\" open>"
        f"<summary>{reco_title}</summary><div class=\"digest-body\">"
    )
    out.append(
        "<p class='meta'>must_read="
        f"{len(digest.get('mustRead') or [])} | skim={len(digest.get('skim') or [])} | "
        f"skip={len(digest.get('skip') or [])}</p>"
    )

    # HF top 10
    hf_top10 = digest.get("huggingFaceTop10") or []
    if hf_top10:
        out.append(_open_section(_html_escape(t(lang, 'section_hf_daily_top10')),
                                  len(hf_top10)))
        for i, p in enumerate(hf_top10, 1):
            out.append("<div class='paper'>")
            out.append(f"<h3>{i}. {_html_escape(p.get('title', '(no title)'))}</h3>")
            rank = p.get("hfRank") or i
            upvotes = p.get("hfUpvotes")
            comments = p.get("hfComments")
            bits = [f"HF rank={rank}"]
            if upvotes is not None:
                bits.append(f"upvotes={upvotes}")
            if comments is not None:
                bits.append(f"comments={comments}")
            out.append(f"<div class='meta'>{' | '.join(bits)}</div>")
            for fig_key in ("key_fig_url", "key_tab_url"):
                img = _img_html((p.get(fig_key) or "").strip())
                if img:
                    out.append(img)
            out.append(_meta_lines_html(p))
            summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
            out.append(f"<blockquote>{_html_escape(summary)}</blockquote>")
            k = _keywords_html(p)
            s = _src_html(p)
            if k:
                out.append(k)
            if s:
                out.append(s)
            out.append("</div>")
        out.append(_close_section())

    # must_read
    out.append(_open_section(_html_escape(t(lang, 'section_must_read')),
                              len(digest['mustRead'])))
    if not digest["mustRead"]:
        out.append(f"<p class='empty'>{_html_escape(t(lang, 'label_no_papers'))}</p>")
    for i, p in enumerate(digest["mustRead"], 1):
        out.append("<div class='paper'>")
        out.append(f"<h3>{i}. {_html_escape(p.get('title', '(no title)'))}</h3>")
        for fig_key in ("key_fig_url", "key_tab_url"):
            img = _img_html((p.get(fig_key) or "").strip())
            if img:
                out.append(img)
        out.append(_meta_lines_html(p))
        summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
        out.append(f"<blockquote>{_html_escape(summary)}</blockquote>")
        k = _keywords_html(p)
        s = _src_html(p)
        if k:
            out.append(k)
        if s:
            out.append(s)
        out.append("</div>")
    out.append(_close_section())

    # skim
    out.append(_open_section(_html_escape(t(lang, 'section_skim')),
                              len(digest['skim'])))
    if not digest["skim"]:
        out.append(f"<p class='empty'>{_html_escape(t(lang, 'label_no_papers'))}</p>")
    for i, p in enumerate(digest["skim"], 1):
        out.append("<div class='paper'>")
        out.append(f"<h3>{i}. {_html_escape(p.get('title', '(no title)'))}</h3>")
        img = _img_html((p.get("key_fig_url") or "").strip())
        if img:
            out.append(img)
        out.append(_meta_lines_html(p))
        summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
        out.append(f"<blockquote>{_html_escape(summary)}</blockquote>")
        k = _keywords_html(p)
        s = _src_html(p)
        if k:
            out.append(k)
        if s:
            out.append(s)
        out.append("</div>")
    out.append(_close_section())

    # skip
    skip_papers = digest.get("skip") or []
    skip_display_n = int(digest.get("skip_displayed") or len(skip_papers))
    skip_total = int(digest.get("skip_total") or len(skip_papers))
    skip_to_render = skip_papers[:skip_display_n]
    header_suffix = (f" <span class='muted'>({skip_display_n}/{skip_total})</span>"
                     if skip_display_n < skip_total else "")
    out.append(_open_section(
        f"{_html_escape(t(lang, 'section_skip'))}",
        len(skip_papers), extra_suffix=header_suffix))
    if not skip_to_render:
        out.append(f"<p class='empty'>{_html_escape(t(lang, 'label_no_papers'))}</p>")
    for i, p in enumerate(skip_to_render, 1):
        out.append("<div class='paper'>")
        out.append(f"<h3>{i}. {_html_escape(p.get('title', '(no title)'))}</h3>")
        out.append(_meta_lines_html(p))
        summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
        out.append(f"<blockquote>{_html_escape(summary)}</blockquote>")
        k = _keywords_html(p)
        s = _src_html(p)
        if k:
            out.append(k)
        if s:
            out.append(s)
        out.append("</div>")
    out.append(_close_section())

    out.append("</div></details>")

    if lang == "zh-CN":
        behavior_title = (
            f"行为总结 <span class='sec-count'>"
            f"{len(digest.get('actionResults') or [])} 条动作</span>"
        )
    else:
        behavior_title = (
            f"Behavior Summary <span class='sec-count'>"
            f"{len(digest.get('actionResults') or [])} actions</span>"
        )
    out.append(
        "<details class=\"digest-section behavior-summary\" open>"
        f"<summary>{behavior_title}</summary><div class=\"digest-body\">"
    )
    source_status = digest.get("sourceStatus") or {}
    if source_status:
        bad_sources = [
            f"{k}:{v.get('status')}" for k, v in source_status.items()
            if isinstance(v, dict) and v.get("status") not in ("ok", "skipped")
        ]
        if bad_sources:
            out.append(
                "<p class='meta'>Some sources degraded; available sources were used. "
                f"{_html_escape(', '.join(bad_sources))}</p>"
            )

    # actions
    out.append(_format_actions_section_html_v2(digest.get("actionResults") or [],
                                               lang))

    # ----- integrated behavior report section -----
    # Same content as the daily_digest.md trailing section, rendered as a
    # collapsible <details class='section'> in the same HTML file. ONE html
    # per day instead of daily_digest.html + behavior_report.html.
    try:
        from behavior_report import build_behavior_section_html
        _bh = agent_home()
        _behavior_html = build_behavior_section_html(_bh, digest["date"], lang)
        if _behavior_html:
            out.append(_behavior_html)
    except Exception as exc:
        out.append(f"<!-- behavior section failed: {exc} -->")

    out.append("</div></details>")

    out.append(f"<div class='footer'>{_html_escape(t(lang, 'label_footer'))}</div>")
    out.append("</body></html>")
    return "\n".join(out)


def _open_section(title: str, count: int, extra_suffix: str = "") -> str:
    """Open a collapsible <details> section with the given title.

    The section starts expanded (open). The summary shows the count of
    items in this section; click anywhere on the summary to collapse.
    """
    count_html = (f"<span class='sec-count'>{count} 篇</span>" if count is not None
                  else "")
    suffix_html = extra_suffix or ""
    return (f"<details class='section' open>"
            f"<summary>{title} {count_html}{suffix_html}"
            f"<span class='sec-toggle' title='全部展开/折叠'>toggle</span>"
            f"</summary><div class='sec-body'>")


def _close_section() -> str:
    return "</div></details>"


def _format_actions_section_html(results: list, lang: str) -> str:
    by_paper: dict[int, dict] = {}
    for r in results:
        pid = r.get("paperId")
        if pid is None:
            continue
        by_paper.setdefault(pid, {"title": r.get("title", "?"),
                                  "actions": []})["actions"].append(r)
    n_papers = len(by_paper)
    n_like = sum(1 for r in results if r.get("actionType") == "like")
    n_collect = sum(1 for r in results if r.get("actionType") == "collect")
    n_comment = sum(1 for r in results if r.get("actionType") == "comment")
    n_skipped = sum(1 for r in results
                    if r.get("actionType") in ("like", "collect")
                    and r.get("skipped"))
    if not by_paper:
        return (_open_section(
                    _html_escape(t(lang, 'section_actions')), 0)
                + f"<p class='empty'>{_html_escape(t(lang, 'no_actions'))}</p>"
                + _close_section())
    out: list[str] = []
    out.append(_open_section(
        _html_escape(t(lang, 'section_actions')),
        n_papers, extra_suffix=f" <span class='muted'>/ {len(results)} 动作</span>"))
    out.append("<p class='action-stats'>"
               f"<span class='stat like'>{_html_escape(t(lang, 'action_like'))} {n_like}</span> "
               f"<span class='stat collect'>{_html_escape(t(lang, 'action_collect'))} {n_collect}</span> "
               f"<span class='stat comment'>{_html_escape(t(lang, 'action_comment'))} {n_comment}</span>")
    if n_skipped:
        if lang == "zh-CN":
            out.append(f" <span class='muted'>({n_skipped} 已是目标状态，跳过)</span>")
        else:
            out.append(f" <span class='muted'>({n_skipped} already in desired state)</span>")
    out.append("</p>")
    for i, (pid, info) in enumerate(by_paper.items(), 1):
        out.append(f"<article class='action-card' data-paper-id='{_html_escape(str(pid))}'>")
        out.append(f"<h3 class='action-title'>{i}. "
                   f"{_html_escape(info['title'])} "
                   f"<span class='paper-id'>id={_html_escape(str(pid))}</span></h3>")
        for r in info["actions"]:
            atype = r.get("actionType", "?")
            ok = r.get("platform", {}).get("ok")
            skipped = r.get("skipped")
            reason = r.get("llm_reason") or ""
            status = "OK" if ok else "SKIP"
            if atype in ("like", "collect"):
                label = _html_escape(t(lang, "action_like" if atype == "like"
                                        else "action_collect"))
                emoji = "[like]" if atype == "like" else "[collect]"
                skipped_html = (f" <span class='muted'>({_html_escape(t(lang, 'skipped_same'))})</span>"
                                if skipped else "")
                reason_html = f"<div class='muted'>{_html_escape(reason)}</div>" if reason else ""
                out.append(f"<div>{status} {emoji} <b>{label}</b>{skipped_html}</div>{reason_html}")
            elif atype == "comment":
                stance = r.get("stance", "thinking")
                stance_label = _html_escape(t(lang,
                    f"label_action_stance_{stance}", default=stance))
                full = r.get("content_full") or r.get("content_preview") or ""
                full_html = (f"<blockquote>{_html_escape(full)}</blockquote>"
                             if full else "")
                reason_html = f"<div class='muted'>{_html_escape(reason)}</div>" if reason else ""
                out.append(f"<div>{status} [comment] <b>{_html_escape(t(lang, 'action_comment'))}</b>"
                           f" <span class='stance-pill stance-{_html_escape(stance)}'>{stance_label}</span></div>"
                           f"{full_html}{reason_html}")
        out.append("</article>")
    out.append(_close_section())
    return "\n".join(out)


def _format_actions_section_html_v2(results: list, lang: str) -> str:
    by_paper: dict[str, dict[str, Any]] = {}
    for r in results:
        pid = r.get("paperId")
        key = str(pid) if pid is not None else "local"
        by_paper.setdefault(key, {
            "title": r.get("title") or ("Local feedback" if key == "local" else "?"),
            "actions": [],
        })["actions"].append(r)

    title = "Today's Agent Actions" if lang == "en-US" else "今日智能体动作"
    if not results:
        return (
            _open_section(title, 0)
            + "<p class='empty'>no actions passed gate yet: no_eligible_comment / "
            "quality_gate_failed / rate_limited / duplicate_or_seen</p>"
            + _close_section()
        )

    stats = {
        "like": sum(1 for r in results if r.get("actionType") == "like"),
        "collect": sum(1 for r in results if r.get("actionType") == "collect"),
        "comment": sum(1 for r in results if r.get("actionType") == "comment"),
        "reply": sum(1 for r in results if r.get("actionType") == "reply"),
        "comment_like": sum(
            1 for r in results if r.get("actionType") == "comment_like"
        ),
        "skipped": sum(1 for r in results if r.get("skipped")),
    }
    out: list[str] = [
        _open_section(
            title,
            len(by_paper),
            extra_suffix=f" <span class='muted'>/ {len(results)} actions</span>",
        ),
        "<p class='action-stats'>"
        f"<span class='stat like'>like {stats['like']}</span> "
        f"<span class='stat collect'>collect {stats['collect']}</span> "
        f"<span class='stat comment'>comment {stats['comment']}</span> "
        f"<span class='stat comment'>reply {stats['reply']}</span> "
        f"<span class='stat like'>comment_like {stats['comment_like']}</span> "
        f"<span class='muted'>skipped {stats['skipped']}</span></p>",
    ]
    for i, (pid, info) in enumerate(by_paper.items(), 1):
        out.append(f"<article class='action-card' data-paper-id='{_html_escape(pid)}'>")
        out.append(
            f"<h3 class='action-title'>{i}. {_html_escape(info['title'])} "
            f"<span class='paper-id'>id={_html_escape(pid)}</span></h3>"
        )
        for r in info["actions"]:
            atype = str(r.get("actionType") or "?")
            platform = r.get("platform") if isinstance(r.get("platform"), dict) else {}
            ok = bool(platform.get("ok"))
            skipped = bool(r.get("skipped") or platform.get("skipped"))
            status = "OK" if ok and not skipped else "SKIP" if skipped else "FAIL"
            reason = str(r.get("reason") or r.get("llm_reason") or "")
            skip_reason = str(r.get("skipReason") or platform.get("reason") or "")
            gate_html = (
                f"<span class='gate-reason'>{_html_escape(skip_reason)}</span>"
                if skip_reason else ""
            )
            parent = r.get("parentCommentId") or r.get("commentId")
            parent_html = (
                f" <span class='paper-id'>parent={_html_escape(str(parent))}</span>"
                if parent and atype == "reply" else ""
            )
            out.append(
                f"<div><b>{_html_escape(status)}</b> "
                f"<b>{_html_escape(atype)}</b>{parent_html}{gate_html}</div>"
            )
            content = (
                r.get("commentContent")
                or r.get("replyContent")
                or r.get("content_full")
                or r.get("content_preview")
                or ""
            )
            if content:
                out.append(f"<blockquote>{_html_escape(str(content))}</blockquote>")
            if reason:
                out.append(f"<div class='muted'>{_html_escape(reason)}</div>")
        out.append("</article>")
    out.append(_close_section())
    return "\n".join(out)


def render_digest_md(digest: dict[str, Any], lang: str) -> str:
    lines: list[str] = [
        f"# {t(lang, 'digest_title', date=digest['date'])}",
        "",
        f"**{t(lang, 'user_label')}:** {digest['username']} (id={digest['userId']})",
        f"**{t(lang, 'label_overview')}:** {digest['summary']}",
    ]
    src = digest.get("discoverySources") or {}
    if src:
        parts: list[str] = []
        if "newest" in src:
            parts.append(f"newest={src.get('newest', 0)}")
        if "recommendations" in src:
            parts.append(f"recommendations={src.get('recommendations', 0)}")
        if "huggingface_daily" in src:
            parts.append(f"hf_daily={src.get('huggingface_daily', 0)}")
        if "interest_total" in src:
            parts.append(f"interest_search={src.get('interest_total', 0)}")
        if parts:
            lines.append(f"**{t(lang, 'label_discovery_sources')}:** "
                         + " | ".join(parts))
    lines.append("")

    def _kw_block_md(p: dict[str, Any]) -> str:
        kws = _extract_keywords(p, lang)
        if not kws:
            return ""
        return f"_{t(lang, 'label_keywords')}:_ " + " ".join(
            f"`#{_fmt_escape_md(k)}`" for k in kws
        )

    def _src_block_md(p: dict[str, Any]) -> str:
        s = _fmt_source_tags(p.get("source_tags") or [], lang)
        return f"_{t(lang, 'label_source')}:_ {s}" if s else ""

    hf_top10 = digest.get("huggingFaceTop10") or []
    if hf_top10:
        lines += [f"## {t(lang, 'section_hf_daily_top10')} ({len(hf_top10)} 篇)"
                  if lang == "zh-CN" else
                  f"## {t(lang, 'section_hf_daily_top10')} ({len(hf_top10)})", ""]
        for i, p in enumerate(hf_top10, 1):
            rank = p.get("hfRank") or i
            upvotes = p.get("hfUpvotes")
            comments = p.get("hfComments")
            bits = [f"rank={rank}"]
            if upvotes is not None:
                bits.append(f"upvotes={upvotes}")
            if comments is not None:
                bits.append(f"comments={comments}")
            lines.append(f"### {i}. {p['title']}")
            lines.append(f"- **HF:** {' | '.join(bits)}")
            fig_url = (p.get("key_fig_url") or "").strip()
            tab_url = (p.get("key_tab_url") or "").strip()
            if fig_url:
                lines.append(f"![{t(lang, 'label_fig_alt')}]({fig_url})")
                lines.append("")
            if tab_url:
                lines.append(f"![{t(lang, 'label_tab_alt')}]({tab_url})")
                lines.append("")
            lines.extend(_fmt_paper_meta_line(p, lang))
            summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
            lines += ["", f"> {summary}", ""]
            kw = _kw_block_md(p)
            src_line = _src_block_md(p)
            if kw:
                lines.append(kw)
            if src_line:
                lines.append(src_line)
            lines += ["", "---", ""]

    lines += [f"## {t(lang, 'section_must_read')} ({len(digest['mustRead'])} 篇)"
              if lang == "zh-CN" else
              f"## {t(lang, 'section_must_read')} ({len(digest['mustRead'])})", ""]
    for i, p in enumerate(digest["mustRead"], 1):
        lines.append(f"### {i}. {p['title']}")
        fig_url = (p.get("key_fig_url") or "").strip()
        tab_url = (p.get("key_tab_url") or "").strip()
        if fig_url and tab_url:
            lines.append(f"![{t(lang, 'label_fig_alt')}]({fig_url})")
            lines.append("")
            lines.append(f"![{t(lang, 'label_tab_alt')}]({tab_url})")
        elif fig_url:
            lines.append(f"![{t(lang, 'label_fig_alt')}]({fig_url})")
        elif tab_url:
            lines.append(f"![{t(lang, 'label_tab_alt')}]({tab_url})")
        lines.append("")
        lines.extend(_fmt_paper_meta_line(p, lang))
        summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
        lines += ["", f"> {summary}", ""]
        kw = _kw_block_md(p)
        src_line = _src_block_md(p)
        if kw:
            lines.append(kw)
        if src_line:
            lines.append(src_line)
        lines += ["", "---", ""]

    lines += [f"## {t(lang, 'section_skim')} ({len(digest['skim'])} 篇)"
              if lang == "zh-CN" else
              f"## {t(lang, 'section_skim')} ({len(digest['skim'])})", ""]
    for i, p in enumerate(digest["skim"], 1):
        lines.append(f"### {i}. {p['title']}")
        fig_url = (p.get("key_fig_url") or "").strip()
        if fig_url:
            lines.append(f"![{t(lang, 'label_fig_alt')}]({fig_url})")
            lines.append("")
        lines.extend(_fmt_paper_meta_line(p, lang))
        summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
        lines += ["", f"> {summary}", ""]
        kw = _kw_block_md(p)
        src_line = _src_block_md(p)
        if kw:
            lines.append(kw)
        if src_line:
            lines.append(src_line)
        lines += ["", "---", ""]

    skip_papers = digest.get("skip") or []
    skip_display_n = int(digest.get("skip_displayed") or len(skip_papers))
    skip_total = int(digest.get("skip_total") or len(skip_papers))
    skip_to_render = skip_papers[:skip_display_n]
    if lang == "zh-CN":
        header = f"## {t(lang, 'section_skip')} ({len(skip_papers)} 篇)"
        if skip_display_n < skip_total:
            header += f" _({skip_display_n}/{skip_total} 篇)_"
    else:
        header = f"## {t(lang, 'section_skip')} ({len(skip_papers)})"
        if skip_display_n < skip_total:
            header += f" _({skip_display_n}/{skip_total})_"
    lines += [header, ""]
    for i, p in enumerate(skip_to_render, 1):
        lines.append(f"### {i}. {p['title']}")
        lines.extend(_fmt_paper_meta_line(p, lang))
        summary = (p.get("summary") or "").strip() or t(lang, "label_no_summary")
        lines += ["", f"> {summary}", ""]
        kw = _kw_block_md(p)
        src_line = _src_block_md(p)
        if kw:
            lines.append(kw)
        if src_line:
            lines.append(src_line)
        lines += ["", "---", ""]

    # actions summary (grouped by paper)
    lines += _format_actions_section_md(digest.get("actionResults") or [],
                                       digest.get("actionProposals") or [],
                                       lang)

    # ----- integrated behavior report section -----
    # The behavior report used to be a separate behavior_report.{md,html}.
    # It is now a trailing section of the same daily_digest file, so the
    # user has ONE report (md + html) per day. If the run dir is missing
    # (e.g. digest is from memory), skip silently.
    try:
        from behavior_report import build_behavior_section_md
        _bh = agent_home()
        _behavior_md = build_behavior_section_md(_bh, digest["date"], lang)
        if _behavior_md:
            lines += ["", "---", "", _behavior_md.rstrip(), ""]
    except Exception as exc:
        # Behavior section is best-effort; do not break the main digest.
        lines += [f"<!-- behavior section failed: {exc} -->"]

    lines += ["", "---", "", f"_{t(lang, 'label_footer')}_", ""]
    return "\n".join(lines)


def _format_actions_section_md(results: list, proposals: list,
                                lang: str) -> list[str]:
    out: list[str] = []
    by_paper: dict[int, dict] = {}
    for r in results:
        pid = r.get("paperId")
        if pid is None:
            continue
        by_paper.setdefault(pid, {"title": r.get("title", "?"),
                                  "actions": []})["actions"].append(r)
    n_papers = len(by_paper)
    n_like = sum(1 for r in results if r.get("actionType") == "like")
    n_collect = sum(1 for r in results if r.get("actionType") == "collect")
    n_comment = sum(1 for r in results if r.get("actionType") == "comment")
    n_skipped = sum(1 for r in results
                    if r.get("actionType") in ("like", "collect")
                    and r.get("skipped"))
    head = f"## {t(lang, 'section_actions')} ({n_papers} / {len(results)})"
    out.append(head)
    out.append("")
    if lang == "zh-CN":
        stats = f"**统计:** 点赞 {n_like} / 收藏 {n_collect} / 评论 {n_comment}"
        if n_skipped:
            stats += f" _(其中 {n_skipped} 个 like/collect 因已是目标状态而跳过)_"
    else:
        stats = f"**Stats:** likes {n_like} / collects {n_collect} / comments {n_comment}"
        if n_skipped:
            stats += f" _({n_skipped} skipped - already in desired state)_"
    out.append(stats)
    out.append("")
    if not by_paper:
        out.append(t(lang, "no_actions"))
        out.append("")
        return out
    out.append("### Per-paper" if lang == "en-US" else "### 每篇论文的动作")
    out.append("")
    for i, (pid, info) in enumerate(by_paper.items(), 1):
        title = info["title"]
        out.append(f"#### {i}. {title} _(id={pid})_")
        out.append("")
        for r in info["actions"]:
            atype = r.get("actionType", "?")
            ok = r.get("platform", {}).get("ok")
            status = "OK" if ok else "SKIP"
            skipped = r.get("skipped")
            if atype in ("like", "collect"):
                emoji = "[like]" if atype == "like" else "[collect]"
                label = t(lang, "action_like" if atype == "like" else "action_collect")
                line = f"- {status} {emoji} **{label}**"
                if skipped:
                    line += f" _{t(lang, 'skipped_same')}_"
                reason = r.get("llm_reason") or ""
                if reason:
                    line += f"  \n  *{reason}*"
                out.append(line)
            elif atype == "comment":
                stance = r.get("stance", "thinking")
                out.append(f"- {status} [comment] **{t(lang, 'action_comment')}** [{stance}]")
                full = r.get("content_full") or r.get("content_preview") or ""
                if full:
                    out.append("")
                    out.append(f"  > {full}")
                    out.append("")
                reason = r.get("llm_reason") or ""
                if reason:
                    out.append(f"  *{reason}*")
        out.append("")
    return out


# ---------- Feedback handler ----------

def _parse_feedback_args(argv: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"action": None, "undo": True}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--paper-id" and i + 1 < len(argv):
            try:
                out["paper_id"] = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif a == "--paper-type" and i + 1 < len(argv):
            out["paper_type"] = argv[i + 1]
            i += 2
        elif a == "--keyword" and i + 1 < len(argv):
            out["keyword"] = argv[i + 1]
            i += 2
        elif a == "--style" and i + 1 < len(argv):
            out["style"] = argv[i + 1]
            i += 2
        elif a == "--action" and i + 1 < len(argv):
            out["action"] = argv[i + 1]
            i += 2
        elif a == "--reason" and i + 1 < len(argv):
            out["reason"] = argv[i + 1]
            i += 2
        elif a == "--no-undo":
            out["undo"] = False
            i += 1
        else:
            i += 1
    return out


def handle_feedback(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    args = _parse_feedback_args(argv)
    action = args.get("action")
    if action not in ("reject", "accept", "note"):
        print("[fatal] --action must be one of reject|accept|note",
              file=sys.stderr, flush=True)
        return 2
    home = agent_home()
    persona = load_json(home / "persona.json", {})
    creds = load_json(home / "credentials.json", None)
    persona.setdefault("rejected_paper_ids", [])
    persona.setdefault("rejected_titles", [])
    persona.setdefault("rejected_paper_types", [])
    persona.setdefault("rejected_keywords", [])
    persona.setdefault("rejected_styles", [])
    persona.setdefault("feedback_history", [])
    target = "unknown"
    if args.get("paper_id") is not None:
        target = f"paper_id={args['paper_id']}"
    elif args.get("paper_type"):
        target = f"paper_type={args['paper_type']}"
    elif args.get("keyword"):
        target = f"keyword={args['keyword']}"
    elif args.get("style"):
        target = f"style={args['style']}"
    undo_results: list[dict[str, Any]] = []
    undo_warning: str | None = None
    if action == "accept" and args.get("paper_id") is not None:
        persona["rejected_paper_ids"] = [
            x for x in persona.get("rejected_paper_ids", []) if x != args["paper_id"]
        ]
    if action == "accept" and args.get("paper_type"):
        persona["rejected_paper_types"] = [
            x for x in persona.get("rejected_paper_types", []) if x != args["paper_type"]
        ]
    if action == "accept" and args.get("keyword"):
        persona["rejected_keywords"] = [
            x for x in persona.get("rejected_keywords", []) if x != args["keyword"]
        ]
    if action == "reject" and args.get("paper_id") is not None:
        if args["paper_id"] not in persona["rejected_paper_ids"]:
            persona["rejected_paper_ids"].append(args["paper_id"])
    if action == "reject" and args.get("paper_type"):
        if args["paper_type"] not in persona["rejected_paper_types"]:
            persona["rejected_paper_types"].append(args["paper_type"])
    if action == "reject" and args.get("keyword"):
        if args["keyword"] not in persona["rejected_keywords"]:
            persona["rejected_keywords"].append(args["keyword"])
    if action == "reject" and args.get("style"):
        if args["style"] not in persona["rejected_styles"]:
            persona["rejected_styles"].append(args["style"])
    if action == "reject" and args.get("undo", True) and creds and args.get("paper_id") is not None:
        try:
            token = exchange_api_key(creds["apiKey"])
            me = get_me(token)
            user_id = me.get("userId")
            username = me.get("username") or creds.get("username") or ""
            for kind in ("like", "collect"):
                res = _set_state(token, args["paper_id"], kind, user_id,
                                  username, desired=False, feedback_lang=DEFAULT_LANG)
                undo_results.append({"kind": kind, "ok": res.get("ok"),
                                      "skipped": res.get("skipped"),
                                      "error": res.get("error")})
        except Exception as exc:
            undo_warning = f"undo failed: {exc}"
    persona["feedback_history"].append({
        "timestamp": utc_now_iso(),
        "action": action,
        "target": target,
        "reason": args.get("reason", ""),
        "undo": args.get("undo", True),
        "undoResults": undo_results,
        "undoWarning": undo_warning,
    })
    persona["feedback_history"] = persona["feedback_history"][-200:]
    persona["updatedAt"] = utc_now_iso()
    save_json(home / "persona.json", persona)
    print(f"[ok] feedback {action} {target} reason={args.get('reason','')!r}")
    if undo_results:
        for u in undo_results:
            mark = "OK" if u.get("ok") else "SKIP"
            skipped = " (skipped)" if u.get("skipped") else ""
            print(f"  {mark} undo {u['kind']}{skipped}")
    if undo_warning:
        print(f"  ! {undo_warning}")
    return 0


# ---------- Batch action executor ----------

def handle_execute_actions(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    if any(a in ("-h", "--help", "help") for a in argv):
        print("usage: execute-actions [--file <path>] [--dry-run] "
              "[--date YYYY-MM-DD]", flush=True)
        print("       if --file is omitted, looks for "
              "runs/<today>/agent_actions.json", flush=True)
        return 0
    action_file = _parse_flag(argv, "file")
    if not action_file:
        action_file = "agent_actions.json"
    dry_run = "dry-run" in argv or "--dry-run" in argv
    date_str = _parse_flag(argv, "date")
    if not date_str:
        date_str = datetime.now().astimezone().strftime("%Y-%m-%d")
    home = agent_home()
    path = Path(action_file).expanduser()
    if not path.is_absolute():
        candidate = home / "runs" / date_str / action_file
        path = candidate if candidate.exists() else Path.cwd() / action_file
    if not path.exists():
        print(f"[fatal] action file not found: {path}",
              file=sys.stderr, flush=True)
        return 2
    try:
        payload = load_json(path, None)
    except json.JSONDecodeError as exc:
        print(f"[fatal] invalid action JSON: {exc}", file=sys.stderr, flush=True)
        return 2
    actions = _extract_actions(payload)
    if not actions:
        print("[fatal] no actions found; expected a list or {\"actions\": [...]}.",
              file=sys.stderr, flush=True)
        return 2
    creds = load_json(home / "credentials.json", None)
    if not creds:
        if dry_run:
            creds = {}
            token = ""
            user_id = 0
            username = ""
        else:
            print(t(DEFAULT_LANG, "fatal_credentials_missing"),
                  file=sys.stderr, flush=True)
            return 2
    else:
        token = exchange_api_key(creds["apiKey"])
        me = get_me(token)
        user_id = me.get("userId")
        username = me.get("username") or creds.get("username") or ""
    if user_id is None:
        print("[fatal] /api/auth/me did not return userId",
              file=sys.stderr, flush=True)
        return 1
    policy = load_policy(home)
    import engagement as _eng
    engagement_state = _eng.load_engagement(home)
    _eng.sync_state_to_trust(engagement_state)
    interaction_state = load_interaction_state(home)
    results = [
        _execute_one_action(
            home, action, token, int(user_id), username, policy, engagement_state,
            interaction_state, dry_run,
        )
        for action in actions
    ]
    if not dry_run:
        _eng.save_engagement(home, engagement_state)
        save_interaction_state(home, interaction_state)
    run_dir = home / "runs" / date_str
    run_dir.mkdir(parents=True, exist_ok=True)
    save_json(run_dir / "agent_action_results.json", results)
    existing_digest = _load_today_digest(run_dir)
    stored_lang = (
        existing_digest.get("language", {}).get("stored")
        if isinstance(existing_digest.get("language"), dict) else None
    ) or resolve_lang(policy, "stored")
    digest_lang = (
        existing_digest.get("language", {}).get("digest")
        if isinstance(existing_digest.get("language"), dict) else None
    ) or resolve_lang(policy, "digest")
    if existing_digest:
        merged = _merge_digest(existing_digest, {
            "date": date_str,
            "actionResults": results,
            "heartbeatSummary": {
                **(existing_digest.get("heartbeatSummary") or {}),
                "lastExecuteActionsAt": utc_now_iso(),
                "lastExecuteActionsDryRun": dry_run,
                "lastExecuteActionsCount": len(actions),
            },
        }, policy)
        _rerender_digest_files(run_dir, merged, stored_lang, digest_lang,
                               inline_images=not dry_run)
    save_json(run_dir / "heartbeat_summary.json", {
        **(load_json(run_dir / "heartbeat_summary.json", {}) or {}),
        "lastExecuteActionsAt": utc_now_iso(),
        "lastExecuteActionsCount": len(actions),
        "lastExecuteActionsDryRun": dry_run,
        "actionResultsOk": sum(1 for r in results if r.get("platform", {}).get("ok")),
        "actionResultsSkipped": sum(1 for r in results if r.get("skipped")),
    })
    ok_count = sum(1 for r in results if r.get("platform", {}).get("ok"))
    skipped = sum(1 for r in results if r.get("skipped"))
    print(json.dumps({
        "ok": True,
        "dryRun": dry_run,
        "actions": len(actions),
        "okCount": ok_count,
        "skipped": skipped,
        "resultsPath": str(run_dir / "agent_action_results.json"),
    }, ensure_ascii=False))
    return 0


# ---------- HTML-only renderer (post-hoc backfill) ----------

def handle_render_html(argv: list[str]) -> int:
    """Re-render the HTML companion for an existing run.

    Useful when the runner was upgraded with HTML support after a run
    already produced daily_digest.json. Skips platform calls entirely.

    Usage:
        python daily_runner.py render-html                  # today
        python daily_runner.py render-html --date 2026-06-04
        python daily_runner.py render-html --date 2026-06-04 --no-inline
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    date = None
    no_inline = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--date" and i + 1 < len(argv):
            date = argv[i + 1]
            i += 2
        elif a == "--no-inline":
            no_inline = True
            i += 1
        else:
            i += 1
    if not date:
        date = datetime.now().astimezone().strftime("%Y-%m-%d")
    home = agent_home()
    run_dir = home / "runs" / date
    if not run_dir.exists():
        print(f"[fatal] run directory not found: {run_dir}", file=sys.stderr,
              flush=True)
        return 2
    digest_path = run_dir / "daily_digest.json"
    if not digest_path.exists():
        print(f"[fatal] daily_digest.json missing: {digest_path}",
              file=sys.stderr, flush=True)
        return 2
    digest = load_json(digest_path, None)
    if not isinstance(digest, dict):
        print(f"[fatal] invalid daily_digest.json: {digest_path}",
              file=sys.stderr, flush=True)
        return 2
    lang = digest.get("language", {}).get("stored") or \
        digest.get("language", {}).get("digest") or DEFAULT_LANG
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    inline = not no_inline
    try:
        html_text = _render_digest_html(digest, lang, inline_images=inline)
        out_path = run_dir / f"daily_digest.{lang}.html"
        out_path.write_text(html_text, encoding="utf-8")
        size = out_path.stat().st_size
        print(f"[ok] rendered {out_path} ({size:,} bytes, "
              f"inline_images={inline})", flush=True)
        return 0
    except Exception as exc:
        print(f"[fatal] render failed: {exc}", file=sys.stderr, flush=True)
        return 1


# ---------- Home (agent heartbeat entry point) ----------

def handle_home(argv: list[str]) -> int:
    """Compute /home JSON for agent heartbeats.

    Usage:
        python daily_runner.py home
        python daily_runner.py home --json
        python daily_runner.py home --quiet
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    as_json = "json" in argv or "--json" in argv
    quiet = "quiet" in argv or "--quiet" in argv
    today_date = None
    skip_network = "no-network" in argv or "--no-network" in argv
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--date" and i + 1 < len(argv):
            today_date = argv[i + 1]
            i += 2
        else:
            i += 1

    home = agent_home()
    creds = load_json(home / "credentials.json", None)

    token = None
    user_id = None
    username = None
    if creds and not skip_network:
        try:
            token = exchange_api_key(creds["apiKey"])
            me = get_me(token)
            user_id = me.get("userId")
            username = me.get("username") or creds.get("username", "")
        except Exception as exc:
            print(f"[warn] /home network init failed: {exc}; "
                  f"returning local-only summary", file=sys.stderr, flush=True)
            token = None

    # late import to avoid circular
    from home import build_home, render_home_text

    home_data = build_home(
        home, today_date=today_date,
        token=token, user_id=user_id, username=username,
    )
    if as_json:
        print(json.dumps(home_data, ensure_ascii=False, indent=2))
    elif quiet:
        acct = home_data.get("yourAccount", {})
        interactions = home_data.get("interactions") or {}
        unread = interactions.get("unreadReplies") or []
        print(f"trust={acct.get('trustLevel')} score={acct.get('trustScore')} "
              f"today(评论/点赞/收藏)={acct.get('today',{}).get('commentsPosted',0)}/"
              f"{acct.get('today',{}).get('postLikes',0)}/"
              f"{acct.get('today',{}).get('postCollects',0)} "
              f"whatToDoNext={len(home_data.get('whatToDoNext',[]))} "
              f"unreadReplies={len(unread) if isinstance(unread, list) else 0}")
    else:
        print(render_home_text(home_data))
    return 0


# ---------- Heartbeat ----------

def _latest_evidence_papers(home: Path) -> list[dict[str, Any]]:
    runs_dir = home / "runs"
    if not runs_dir.exists():
        return []
    dated = [p for p in runs_dir.iterdir() if p.is_dir()]
    dated.sort(key=lambda p: p.name, reverse=True)
    for run in dated:
        evidence = load_json(run / "evidence_pack.json", None)
        if isinstance(evidence, list) and evidence:
            return evidence
    return []


# ---------- Read-paper subcommands (read-only, no rate limit) ----------

def _parse_flag(argv, name, default=None, cast=str):
    """Tiny helper: pull `--name value` from argv (or `--name=value`)."""
    for i, a in enumerate(argv):
        if a == f"--{name}" and i + 1 < len(argv):
            return cast(argv[i + 1])
        if a.startswith(f"--{name}="):
            return cast(a.split("=", 1)[1])
    return default


def _ensure_token(home: Path) -> tuple[str | None, int | None, str]:
    """Load creds + exchange for access token. Returns (token, user_id, username)."""
    creds = load_json(home / "credentials.json", None)
    if not creds:
        return (None, None, "")
    try:
        token = exchange_api_key(creds["apiKey"])
        me = get_me(token)
        return (token, me.get("userId"), me.get("username") or creds.get("username", ""))
    except Exception as exc:
        print(f"[warn] exchange_api_key failed: {exc}", file=sys.stderr, flush=True)
        return (None, None, "")


def _output(data, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        # human-friendly: print title / paperId / first 200 chars of summary
        if isinstance(data, list):
            for p in data[:30]:
                pid = p.get("id") or p.get("paperId")
                title = (p.get("title") or "")[:100]
                print(f"  [{pid}] {title}")
        elif isinstance(data, dict):
            pid = data.get("id") or data.get("paperId") or ""
            title = data.get("title", "")
            summary = (data.get("summary") or data.get("abstract") or
                       data.get("eng_script") or "")[:200]
            print(f"[{pid}] {title}")
            if summary:
                print(f"  {summary}")


def handle_search_papers(argv: list[str]) -> int:
    q = _parse_flag(argv, "q")
    if not q:
        print("[fatal] --q required", file=sys.stderr, flush=True)
        return 2
    time_range = _parse_flag(argv, "time-range", "180d")
    sort = _parse_flag(argv, "sort", "newest")
    page_size = int(_parse_flag(argv, "page-size", "20", int))
    search_mode = _parse_flag(argv, "mode", "auto")
    search_type = _parse_flag(argv, "search-type", "all")
    as_json = "json" in argv or "--json" in argv
    try:
        # use existing search_papers() which has auto mode
        if search_type and search_type != "all":
            url = f"{BASE_URL}/api/papers"
            params = {"q": q, "searchType": search_type, "timeRange": time_range,
                      "sort": sort, "page": 1, "pageSize": page_size, "skipTotal": "true"}
            data = unwrap(requests.get(url, params=params, timeout=TIMEOUT))
        else:
            data = search_papers(q, page_size, search_mode=search_mode)
    except Exception as exc:
        print(f"[fatal] search failed: {exc}", file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_trending(argv: list[str]) -> int:
    time_range = _parse_flag(argv, "time-range", "30d")
    page_size = int(_parse_flag(argv, "page-size", "20", int))
    as_json = "json" in argv or "--json" in argv
    try:
        data = list_papers("trending", time_range, page_size)
    except Exception as exc:
        print(f"[fatal] trending failed: {exc}", file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_hot(argv: list[str]) -> int:
    time_range = _parse_flag(argv, "time-range", "7d")
    page_size = int(_parse_flag(argv, "page-size", "20", int))
    as_json = "json" in argv or "--json" in argv
    try:
        data = list_papers("hot", time_range, page_size)
    except Exception as exc:
        print(f"[fatal] hot failed: {exc}", file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_paper_detail(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    as_json = "json" in argv or "--json" in argv
    lang = _parse_flag(argv, "lang")
    try:
        url = f"{BASE_URL}/api/papers/{pid}"
        params = {"lang": lang} if lang else {}
        data = unwrap(requests.get(url, params=params, timeout=TIMEOUT))
    except Exception as exc:
        print(f"[fatal] paper-detail failed: {exc}", file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def _handle_paper_reaction_state(argv: list[str], endpoint: str,
                                 command_name: str) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    home = agent_home()
    token, user_id, _ = _ensure_token(home)
    if not token or user_id is None:
        print("[fatal] credentials required for this command", file=sys.stderr, flush=True)
        return 2
    as_json = "json" in argv or "--json" in argv
    try:
        url = f"{BASE_URL}/api/papers/{pid}/{endpoint}"
        data = unwrap(requests.get(url, params={"userId": user_id},
                                     headers=auth_headers(token), timeout=TIMEOUT))
    except Exception as exc:
        print(f"[fatal] {command_name} failed: {exc}", file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_paper_likes(argv: list[str]) -> int:
    return _handle_paper_reaction_state(argv, "likes", "paper-likes")


def handle_paper_collects(argv: list[str]) -> int:
    return _handle_paper_reaction_state(argv, "collects", "paper-collects")


def handle_paper_comments(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    sort = _parse_flag(argv, "sort")
    as_json = "json" in argv or "--json" in argv
    home = agent_home()
    token, user_id, _ = _ensure_token(home)
    if not token or user_id is None:
        print("[fatal] credentials required (need userId)",
              file=sys.stderr, flush=True)
        return 2
    try:
        url = f"{BASE_URL}/api/papers/{pid}/comments"
        data = unwrap(requests.get(
            url, params={"userId": user_id, "sort": sort or "best"},
            headers=auth_headers(token), timeout=TIMEOUT,
        ))
    except Exception as exc:
        print(f"[fatal] paper-comments failed: {exc}",
              file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_paper_interactions(argv: list[str]) -> int:
    ids_str = _parse_flag(argv, "ids")
    if not ids_str:
        print("[fatal] --ids required (comma-separated)", file=sys.stderr, flush=True)
        return 2
    try:
        ids = [int(x) for x in ids_str.split(",") if x.strip()]
    except ValueError:
        print("[fatal] --ids must be int, comma-separated", file=sys.stderr, flush=True)
        return 2
    if not ids:
        print("[fatal] --ids must be non-empty", file=sys.stderr, flush=True)
        return 2
    home = agent_home()
    token, user_id, _ = _ensure_token(home)
    if not token or user_id is None:
        print("[fatal] credentials required", file=sys.stderr, flush=True)
        return 2
    as_json = "json" in argv or "--json" in argv
    try:
        data = unwrap(requests.get(
            f"{BASE_URL}/api/papers/interactions",
            params={"paperIds": ",".join(str(x) for x in ids), "userId": user_id},
            headers=auth_headers(token), timeout=TIMEOUT,
        ))
    except Exception as exc:
        print(f"[fatal] paper-interactions failed: {exc}", file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_paper_download(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    out_path = _parse_flag(argv, "out")
    home = agent_home()
    policy = load_policy(home)
    if not policy.get("allowPdfDownload", False):
        print("[fatal] policy.allowPdfDownload=false; set it to true first",
              file=sys.stderr, flush=True)
        return 2
    if not out_path:
        out_path = str(home / "downloads" / f"paper-{pid}.pdf")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(f"{BASE_URL}/api/papers/{pid}/download",
                           stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64_000):
                    f.write(chunk)
        size = Path(out_path).stat().st_size
        print(f"[ok] saved {size:,} bytes to {out_path}")
    except Exception as exc:
        print(f"[fatal] paper-download failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


def handle_paper_core_knowledge(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    out_path = _parse_flag(argv, "out")
    home = agent_home()
    if not out_path:
        out_path = str(home / "downloads" / f"paper-{pid}-core.json")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(f"{BASE_URL}/api/papers/{pid}/core-knowledge/download",
                           stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64_000):
                    f.write(chunk)
        size = Path(out_path).stat().st_size
        print(f"[ok] saved {size:,} bytes to {out_path}")
    except Exception as exc:
        print(f"[fatal] paper-core-knowledge failed: {exc}",
              file=sys.stderr, flush=True)
        return 1
    return 0


def handle_paper_related_papers(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    out_path = _parse_flag(argv, "out")
    home = agent_home()
    if not out_path:
        out_path = str(home / "downloads" / f"paper-{pid}-related.json")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(f"{BASE_URL}/api/papers/{pid}/related-paper/download",
                           stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64_000):
                    f.write(chunk)
        size = Path(out_path).stat().st_size
        print(f"[ok] saved {size:,} bytes to {out_path}")
    except Exception as exc:
        print(f"[fatal] paper-related-papers failed: {exc}",
              file=sys.stderr, flush=True)
        return 1
    return 0


def handle_my_latest_papers(argv: list[str]) -> int:
    home = agent_home()
    token, _, _ = _ensure_token(home)
    if not token:
        print("[fatal] credentials required", file=sys.stderr, flush=True)
        return 2
    as_json = "json" in argv or "--json" in argv
    try:
        data = unwrap(requests.get(f"{BASE_URL}/api/papers/my/latest-papers",
                                     headers=auth_headers(token), timeout=TIMEOUT))
    except Exception as exc:
        print(f"[fatal] my-latest-papers failed: {exc}",
              file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_hf_token_status(argv: list[str]) -> int:
    home = agent_home()
    token, _, _ = _ensure_token(home)
    if not token:
        print("[fatal] credentials required", file=sys.stderr, flush=True)
        return 2
    as_json = "json" in argv or "--json" in argv
    try:
        data = unwrap(requests.get(f"{BASE_URL}/api/huggingface/token",
                                     headers=auth_headers(token), timeout=TIMEOUT))
    except Exception as exc:
        print(f"[fatal] hf-token-status failed: {exc}",
              file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


def handle_keywords_suggest(argv: list[str]) -> int:
    q = _parse_flag(argv, "q")
    if not q:
        print("[fatal] --q required", file=sys.stderr, flush=True)
        return 2
    limit = int(_parse_flag(argv, "limit", "10", int))
    as_json = "json" in argv or "--json" in argv
    try:
        data = unwrap(requests.get(
            f"{BASE_URL}/api/keywords/suggest",
            params={"q": q, "limit": limit}, timeout=TIMEOUT))
    except Exception as exc:
        print(f"[fatal] keywords-suggest failed: {exc}",
              file=sys.stderr, flush=True)
        return 1
    _output(data, as_json)
    return 0


# ---------- Write-action subcommands (rate-limit + trust gated) ----------

def handle_set_like(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    desired_raw = _parse_flag(argv, "desired", "true").lower()
    desired = desired_raw in ("true", "1", "yes")
    home = agent_home()
    token, user_id, username = _ensure_token(home)
    if not token:
        print("[fatal] credentials required", file=sys.stderr, flush=True)
        return 2
    import engagement as _eng
    state = _eng.load_engagement(home)
    _eng.sync_state_to_trust(state)
    policy = load_policy(home)
    capability = "autoLike"
    user_approved = "user-approved" in argv
    ok, reason = _eng.can_perform(policy, capability, state["trustLevel"],
                                   user_approved=user_approved)
    if not ok:
        print(f"[skip] set-like {pid} ->{desired}: {reason}",
              file=sys.stderr, flush=True)
        return 0
    can, can_reason, _ = _eng.can_act(state, "postLike")
    if not can:
        print(f"[skip] set-like {pid} ->{desired}: {can_reason}",
              file=sys.stderr, flush=True)
        return 0
    res = _set_state(token, pid, "like", user_id, username,
                      desired=desired, feedback_lang=DEFAULT_LANG)
    if res.get("ok"):
        _eng.record_action(state, "postLike", paper_id=pid)
        _eng.save_engagement(home, state)
    print(json.dumps({"ok": res.get("ok"), "skipped": res.get("skipped", False),
                      "current": res.get("current"), "data": res.get("data")},
                     ensure_ascii=False, default=str))
    return 0 if res.get("ok") else 1


def handle_set_collect(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    if not pid:
        print("[fatal] --id required", file=sys.stderr, flush=True)
        return 2
    desired_raw = _parse_flag(argv, "desired", "true").lower()
    desired = desired_raw in ("true", "1", "yes")
    home = agent_home()
    token, user_id, username = _ensure_token(home)
    if not token:
        print("[fatal] credentials required", file=sys.stderr, flush=True)
        return 2
    import engagement as _eng
    state = _eng.load_engagement(home)
    _eng.sync_state_to_trust(state)
    policy = load_policy(home)
    ok, reason = _eng.can_perform(policy, "autoCollect", state["trustLevel"])
    if not ok:
        print(f"[skip] set-collect {pid} ->{desired}: {reason}",
              file=sys.stderr, flush=True)
        return 0
    can, can_reason, _ = _eng.can_act(state, "postCollect")
    if not can:
        print(f"[skip] set-collect {pid} ->{desired}: {can_reason}",
              file=sys.stderr, flush=True)
        return 0
    res = _set_state(token, pid, "collect", user_id, username,
                      desired=desired, feedback_lang=DEFAULT_LANG)
    if res.get("ok"):
        _eng.record_action(state, "postCollect", paper_id=pid)
        _eng.save_engagement(home, state)
    print(json.dumps({"ok": res.get("ok"), "skipped": res.get("skipped", False),
                      "current": res.get("current"), "data": res.get("data")},
                     ensure_ascii=False, default=str))
    return 0 if res.get("ok") else 1


def handle_post_comment(argv: list[str]) -> int:
    pid = _parse_flag(argv, "id", cast=int)
    content = _parse_flag(argv, "content")
    if not pid or not content:
        print("[fatal] --id and --content required", file=sys.stderr, flush=True)
        return 2
    parent_id = _parse_flag(argv, "parent-id")
    home = agent_home()
    token, user_id, _ = _ensure_token(home)
    if not token:
        print("[fatal] credentials required", file=sys.stderr, flush=True)
        return 2
    import engagement as _eng
    state = _eng.load_engagement(home)
    _eng.sync_state_to_trust(state)
    policy = load_policy(home)
    capability = "autoReply" if parent_id else "autoComment"
    user_approved = "user-approved" in argv
    ok, reason = _eng.can_perform(policy, capability, state["trustLevel"],
                                   user_approved=user_approved)
    if not ok:
        print(f"[skip] post-{capability} {pid}: {reason}", file=sys.stderr, flush=True)
        return 0
    action = "reply" if parent_id else "comment"
    can, can_reason, _ = _eng.can_act(state, action)
    if not can:
        print(f"[skip] post-{action} {pid}: {can_reason}", file=sys.stderr, flush=True)
        return 0
    if parent_id:
        res = _do_reply(token, pid, parent_id, content)
    else:
        res = _do_comment(token, pid, content)
    if res.get("ok"):
        _eng.record_action(state, action, paper_id=pid, parent_id=parent_id)
        _eng.save_engagement(home, state)
    print(json.dumps(res, ensure_ascii=False, default=str))
    return 0 if res.get("ok") else 1


def handle_post_reply(argv: list[str]) -> int:
    """Convenience wrapper: same as post-comment but defaults to reply mode."""
    return handle_post_comment(argv)


def handle_like_comment(argv: list[str]) -> int:
    cid = _parse_flag(argv, "comment-id")
    if not cid:
        print("[fatal] --comment-id required", file=sys.stderr, flush=True)
        return 2
    home = agent_home()
    token, user_id, username = _ensure_token(home)
    if not token:
        print("[fatal] credentials required", file=sys.stderr, flush=True)
        return 2
    import engagement as _eng
    state = _eng.load_engagement(home)
    _eng.sync_state_to_trust(state)
    policy = load_policy(home)
    ok, reason = _eng.can_perform(policy, "autoCommentLike", state["trustLevel"])
    if not ok:
        print(f"[skip] like-comment {cid}: {reason}", file=sys.stderr, flush=True)
        return 0
    can, can_reason, _ = _eng.can_act(state, "commentLike")
    if not can:
        print(f"[skip] like-comment {cid}: {can_reason}", file=sys.stderr, flush=True)
        return 0
    res = _do_comment_like(token, cid, user_id, username)
    if res.get("ok"):
        _eng.record_action(state, "commentLike", comment_id=cid)
        _eng.save_engagement(home, state)
    print(json.dumps(res, ensure_ascii=False, default=str))
    return 0 if res.get("ok") else 1


def handle_record_action(argv: list[str]) -> int:
    """Explicitly record a user action (agent calls this AFTER successful
    platform write to keep engagement_state in sync).

    Examples:
      record-action --action comment --paper-id 123
      record-action --action like --paper-id 123
      record-action --action discover --paper-id 123
    """
    action = _parse_flag(argv, "action")
    if not action:
        print("[fatal] --action required", file=sys.stderr, flush=True)
        return 2
    paper_id = _parse_flag(argv, "id", cast=int) or _parse_flag(argv, "paper-id", cast=int)
    comment_id = _parse_flag(argv, "comment-id")
    parent_id = _parse_flag(argv, "parent-id")
    home = agent_home()
    import engagement as _eng
    state = _eng.load_engagement(home)
    _eng.sync_state_to_trust(state)
    if action not in _eng.RATE_LIMITS:
        print(f"[fatal] unknown action: {action}", file=sys.stderr, flush=True)
        return 2
    _eng.record_action(state, action, paper_id=paper_id, comment_id=comment_id,
                        parent_id=parent_id)
    _eng.save_engagement(home, state)
    print(json.dumps({"ok": True, "action": action,
                      "lifetime": state["activity"]["lifetime"]},
                     ensure_ascii=False, default=str))
    return 0


# ---------- Behavior report subcommands ----------
#
# v2026-06-04: behavior reports are embedded in daily digest files.
#   daily_digest.{lang}.{md,html} appends a behavior report section.
#
# Subcommands:
#   report-yesterday  -> re-render the selected daily digest.
#   report-week       -> aggregate to runs/weekly-reports/YYYY-Www.{md,html}.
#   report-month      -> aggregate to runs/monthly-reports/YYYY-MM.{md,html}.

def handle_report_yesterday(argv: list[str]) -> int:
    """Re-render yesterday's integrated daily digest."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    home = agent_home()
    date_str = _parse_flag(argv, "date")
    if not date_str:
        date_str = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    run_dir = home / "runs" / date_str
    if not run_dir.exists():
        print(json.dumps({"ok": False,
                          "error": f"no run for {date_str}",
                          "md_path": None, "html_path": None},
                         ensure_ascii=False))
        return 1
    # Re-render the unified HTML; the behavior section is embedded automatically.
    rc = handle_render_html(["--date", date_str])
    md_path = None
    html_path = None
    digest = load_json(run_dir / "daily_digest.json", {})
    if isinstance(digest, dict):
        lang = (digest.get("language", {}) or {}).get("stored") or \
               (digest.get("language", {}) or {}).get("digest") or "zh-CN"
        if lang not in SUPPORTED_LANGS:
            lang = "zh-CN"
        md_path = f"runs/{date_str}/daily_digest.{lang}.md"
        html_path = f"runs/{date_str}/daily_digest.{lang}.html"
    out = {
        "ok": rc == 0,
        "date": date_str,
        "md_path": md_path,
        "html_path": html_path,
        "note": "行为报告已嵌入 daily_digest.{lang}.{md,html} 末尾",
    }
    print(json.dumps(out, ensure_ascii=False, default=str))
    return rc


def handle_report_week(argv: list[str]) -> int:
    """Generate weekly rollup reports."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    home = agent_home()
    week_of = _parse_flag(argv, "week-of")
    import behavior_report as br
    dates, title, wkey = br.week_dates(week_of)

    # MD
    md_lines: list[str] = []
    md_lines.append(br.build_aggregated_behavior_md(home, dates, title))
    # Append per-day behavior sections (Markdown)
    md_lines.append("\n---\n\n## 每日行为区段\n")
    for d in dates:
        sub = br.build_behavior_section_md(home, d, "zh-CN")
        if sub:
            md_lines.append("\n---\n")
            md_lines.append(sub)
    md_text = "\n".join(md_lines).rstrip() + "\n"
    out_dir = home / "runs" / "weekly-reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{wkey}.md"
    md_path.write_text(md_text, encoding="utf-8")

    # HTML
    html_body = br.build_aggregated_behavior_html(home, dates, title)
    # Append per-day behavior sections (HTML); strip <html><head> wrapper
    # from subsequent fragments and inline.
    extra = []
    for d in dates:
        sub = br.build_behavior_section_html(home, d, "zh-CN")
        if sub:
            extra.append(sub)
    # Insert before </body></html>
    if "</body></html>" in html_body:
        idx = html_body.rfind("</body></html>")
        html_body = html_body[:idx] + "\n<hr>\n<h1>每日行为区段</h1>\n" + \
                    "\n".join(extra) + "\n" + html_body[idx:]
    else:
        html_body += "\n" + "\n".join(extra)
    html_path = out_dir / f"{wkey}.html"
    html_path.write_text(html_body, encoding="utf-8")

    out = {
        "ok": True,
        "week": wkey,
        "dates": dates,
        "md_path": str(md_path.relative_to(home)),
        "html_path": str(html_path.relative_to(home)),
        "summary": f"{title}: 覆盖 {len(dates)} 天",
    }
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


def handle_report_month(argv: list[str]) -> int:
    """Generate monthly rollup reports."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    home = agent_home()
    month_of = _parse_flag(argv, "month-of")
    import behavior_report as br
    dates, title, mkey = br.month_dates(month_of)

    # MD
    md_lines: list[str] = []
    md_lines.append(br.build_aggregated_behavior_md(home, dates, title))
    md_lines.append("\n---\n\n## 每日行为区段\n")
    for d in dates:
        sub = br.build_behavior_section_md(home, d, "zh-CN")
        if sub:
            md_lines.append("\n---\n")
            md_lines.append(sub)
    md_text = "\n".join(md_lines).rstrip() + "\n"
    out_dir = home / "runs" / "monthly-reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{mkey}.md"
    md_path.write_text(md_text, encoding="utf-8")

    # HTML
    html_body = br.build_aggregated_behavior_html(home, dates, title)
    extra = []
    for d in dates:
        sub = br.build_behavior_section_html(home, d, "zh-CN")
        if sub:
            extra.append(sub)
    if "</body></html>" in html_body:
        idx = html_body.rfind("</body></html>")
        html_body = html_body[:idx] + "\n<hr>\n<h1>每日行为区段</h1>\n" + \
                    "\n".join(extra) + "\n" + html_body[idx:]
    else:
        html_body += "\n" + "\n".join(extra)
    html_path = out_dir / f"{mkey}.html"
    html_path.write_text(html_body, encoding="utf-8")

    out = {
        "ok": True,
        "month": mkey,
        "dates_count": len(dates),
        "md_path": str(md_path.relative_to(home)),
        "html_path": str(html_path.relative_to(home)),
        "summary": f"{title}: 覆盖 {len(dates)} 天",
    }
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


# ---------- Trust subcommands ----------

def handle_trust(argv: list[str]) -> int:
    """trust show | score | set <level> [--reason "..."] | reset."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    if not argv:
        argv = ["show"]
    sub = argv[0]
    rest = argv[1:]
    home = agent_home()
    import engagement as _eng
    state = _eng.load_engagement(home)

    if sub == "show":
        _eng.sync_state_to_trust(state)
        score = _eng.trust_score(state)
        first = state.get("firstSeenAt", "")
        age_days = 0.0
        if first:
            try:
                first_dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - first_dt).total_seconds() / 86400.0
            except (ValueError, AttributeError):
                pass
        out = {
            "userId":           state.get("userId"),
            "trustLevel":       state.get("trustLevel"),
            "trustScore":       score,
            "ageDays":          round(age_days, 2),
            "firstSeenAt":      first,
            "lifetime":         state["activity"]["lifetime"],
            "today":            state["activity"]["today"],
            "rateLimits":       {k: {"used": v.get("used", 0),
                                       "limit": v.get("limit", 0)}
                                  for k, v in state.get("rateLimits", {}).items()
                                  if isinstance(v, dict) and "limit" in v},
            "trustHistory":     state.get("trustHistory", []),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    if sub == "score":
        print(json.dumps({
            "trustLevel": state.get("trustLevel"),
            "score": _eng.trust_score(state),
            "weights": _eng.SCORE_WEIGHTS,
        }, ensure_ascii=False, indent=2, default=str))
        return 0
    if sub == "set":
        if not rest:
            print("[fatal] trust set <new|established|trusted> [--reason '...']",
                  file=sys.stderr, flush=True)
            return 2
        level = rest[0]
        reason = ""
        if "--reason" in rest:
            i = rest.index("--reason")
            if i + 1 < len(rest):
                reason = rest[i + 1]
        if _eng.set_trust(state, level, reason):
            _eng.save_engagement(home, state)
            print(f"[ok] trust set to {level} (reason={reason!r})")
        else:
            print(f"[info] trust already {level}, no change")
        return 0
    if sub == "reset":
        # delete engagement_state.json (destructive)
        path = home / "engagement_state.json"
        if path.exists():
            path.unlink()
            print(f"[ok] removed {path} (next run will re-create)")
        return 0
    print(f"[fatal] unknown trust subcommand: {sub}", file=sys.stderr, flush=True)
    return 2


def handle_heartbeat(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    dry_run = "dry-run" in argv or "--dry-run" in argv
    home = agent_home()
    creds = load_json(home / "credentials.json", None)
    if not creds:
        print(t(DEFAULT_LANG, "fatal_credentials_missing"),
              file=sys.stderr, flush=True)
        return 2
    policy = load_policy(home)
    comment_lang = resolve_lang(policy, "comment")
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    run_dir = home / "runs" / (f"{today}-dry-run" if dry_run else today)
    run_dir.mkdir(parents=True, exist_ok=True)
    existing_digest = _load_today_digest(run_dir)
    token = exchange_api_key(creds["apiKey"])
    me = get_me(token)
    user_id = me.get("userId")
    username = me.get("username") or creds.get("username") or ""
    papers = _latest_evidence_papers(home)
    state = load_interaction_state(home)
    reply_proposals, reply_results, heartbeat_summary = process_comment_interactions(
        token, user_id, username, papers, policy, state, comment_lang,
        dry_run=dry_run,
    )
    save_json(run_dir / "reply_proposals.json", reply_proposals)
    save_json(run_dir / "reply_results.json", reply_results)
    save_json(run_dir / "heartbeat_summary.json", {
        **heartbeat_summary, "mode": "heartbeat",
        "paperCount": len(papers), "generatedAt": utc_now_iso(),
    })
    if existing_digest:
        stored_lang = (
            existing_digest.get("language", {}).get("stored")
            if isinstance(existing_digest.get("language"), dict) else None
        ) or resolve_lang(policy, "stored")
        digest_lang = (
            existing_digest.get("language", {}).get("digest")
            if isinstance(existing_digest.get("language"), dict) else None
        ) or resolve_lang(policy, "digest")
        merged = _merge_digest(existing_digest, {
            "date": today,
            "replyProposals": reply_proposals,
            "replyResults": reply_results,
            "heartbeatSummary": {
                **(existing_digest.get("heartbeatSummary") or {}),
                **heartbeat_summary,
                "mode": "heartbeat",
                "lastHeartbeatAt": utc_now_iso(),
            },
            "discussionStatus": {
                "scannedComments": heartbeat_summary.get("scannedComments", 0),
                "replyProposals": heartbeat_summary.get("replyProposals", 0),
                "commentLikeProposals": heartbeat_summary.get("commentLikeProposals", 0),
            },
        }, policy)
        _rerender_digest_files(run_dir, merged, stored_lang, digest_lang,
                               inline_images=not dry_run)
    if not dry_run:
        save_interaction_state(home, state)
    print(f"HEARTBEAT_OK papers={len(papers)} comments={heartbeat_summary['scannedComments']} "
          f"replies={heartbeat_summary['replyResults']} "
          f"commentLikes={heartbeat_summary['commentLikeResults']} "
          f"dryRun={dry_run}", flush=True)
    return 0


# ---------- Main entry ----------

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    if len(sys.argv) > 1 and sys.argv[1] == "feedback":
        return handle_feedback(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "heartbeat":
        return handle_heartbeat(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "execute-actions":
        return handle_execute_actions(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "render-html":
        return handle_render_html(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "home":
        return handle_home(sys.argv[2:])
    # read-paper subcommands
    if len(sys.argv) > 1 and sys.argv[1] == "search-papers":
        return handle_search_papers(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "trending":
        return handle_trending(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "hot":
        return handle_hot(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-detail":
        return handle_paper_detail(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-likes":
        return handle_paper_likes(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-collects":
        return handle_paper_collects(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-comments":
        return handle_paper_comments(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-interactions":
        return handle_paper_interactions(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-download":
        return handle_paper_download(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-core-knowledge":
        return handle_paper_core_knowledge(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "paper-related-papers":
        return handle_paper_related_papers(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "my-latest-papers":
        return handle_my_latest_papers(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "hf-token-status":
        return handle_hf_token_status(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "keywords-suggest":
        return handle_keywords_suggest(sys.argv[2:])
    # write-action subcommands
    if len(sys.argv) > 1 and sys.argv[1] == "set-like":
        return handle_set_like(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "set-collect":
        return handle_set_collect(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "post-comment":
        return handle_post_comment(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "post-reply":
        return handle_post_reply(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "like-comment":
        return handle_like_comment(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "record-action":
        return handle_record_action(sys.argv[2:])
    # trust subcommands
    if len(sys.argv) > 1 and sys.argv[1] == "trust":
        return handle_trust(sys.argv[2:])
    # behavior reports
    if len(sys.argv) > 1 and sys.argv[1] == "report-yesterday":
        return handle_report_yesterday(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "report-week":
        return handle_report_week(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "report-month":
        return handle_report_month(sys.argv[2:])
    dry_run = any(a in ("dry-run", "--dry-run") for a in sys.argv[1:])
    if any(a in ("--help", "-h", "help") for a in sys.argv[1:]):
        print("usage: python daily_runner.py [home|search-papers|trending|hot|"
              "paper-detail|paper-likes|paper-collects|paper-comments|paper-interactions|"
              "paper-download|paper-core-knowledge|paper-related-papers|my-latest-papers|"
              "hf-token-status|keywords-suggest|set-like|set-collect|post-comment|post-reply|"
              "like-comment|record-action|execute-actions|heartbeat|feedback|render-html|"
              "dry-run|--dry-run|home]",
              flush=True)
        return 0

    home = agent_home()
    creds = load_json(home / "credentials.json", None)
    if not creds:
        print(t(DEFAULT_LANG, "fatal_credentials_missing"),
              file=sys.stderr, flush=True)
        return 2
    policy = load_policy(home)
    persona = load_json(home / "persona.json", {})

    feedback_lang = resolve_lang(policy, "feedback")
    comment_lang = resolve_lang(policy, "comment")
    digest_lang = resolve_lang(policy, "digest")
    stored_lang = resolve_lang(policy, "stored")

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    run_dir = home / "runs" / (f"{today}-dry-run" if dry_run else today)
    existing_digest = _load_today_digest(run_dir)
    # Backup any existing run for today so a partial-failure run doesn't
    # silently leave stale files that the next successful run would
    # overwrite piecemeal.
    if run_dir.exists():
        ts = datetime.now().astimezone().strftime("%H%M%S")
        backup = run_dir.with_name(f"{run_dir.name}-failed-{ts}")
        run_dir.rename(backup)
        print(f"[info] backed up previous run to {backup.name}",
              flush=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    print(t(feedback_lang, "stage"), "->", t(feedback_lang, "auth"), flush=True)
    try:
        token = exchange_api_key(creds["apiKey"])
    except Exception as exc:
        print(t(feedback_lang, "fatal_api_bootstrap", err=str(exc)),
              file=sys.stderr, flush=True)
        save_json(run_dir / "failure.json",
                  {"ok": False, "stage": "auth", "error": str(exc)})
        return 1
    me = get_me(token)
    user_id = me.get("userId")
    username = me.get("username")
    interaction_state = load_interaction_state(home)
    source_status: dict[str, dict[str, Any]] = {}
    source_status["auth_me"] = {
        "status": "ok",
        "userId": user_id,
        "username": username,
    }
    source_status["local_interaction_state"] = {
        "status": "ok",
        "lastHeartbeatAt": interaction_state.get("lastHeartbeatAt"),
    }
    interests = get_interests(token)
    focus_terms = interests or persona.get("preferred_concepts") or []
    focus_tokens = _focus_tokens(focus_terms)

    print(t(feedback_lang, "stage"), "->", t(feedback_lang, "discovery"),
          flush=True)

    page_size = int(policy.get("dailyPageSize", 20) or 20)
    dry_run_limits: dict[str, int] = {}
    if dry_run:
        requested_page_size = page_size
        page_size = min(
            page_size,
            int(policy.get("dryRunPageSize", DEFAULT_DRY_RUN_PAGE_SIZE)
                or DEFAULT_DRY_RUN_PAGE_SIZE),
        )
        dry_run_limits["requestedPageSize"] = requested_page_size
        dry_run_limits["pageSize"] = page_size
    newest_window = policy.get("newestTimeRange", "1d")
    enable_newest = bool(policy.get("enableNewestSource", True))
    search_mode = policy.get("searchMode", "auto")
    enable_hf_daily = bool(policy.get("enableHuggingFaceDailySource", True))
    enable_hf_weekly = bool(policy.get("enableHuggingFaceWeeklySource", False))
    hf_top_n = int(policy.get("hfTopN", 10))
    if dry_run:
        requested_hf_top_n = hf_top_n
        hf_top_n = min(
            hf_top_n,
            int(policy.get("dryRunHfTopN", DEFAULT_DRY_RUN_HF_TOP_N)
                or DEFAULT_DRY_RUN_HF_TOP_N),
        )
        dry_run_limits["requestedHfTopN"] = requested_hf_top_n
        dry_run_limits["hfTopN"] = hf_top_n

    src_newest: list[dict[str, Any]] = []
    if enable_newest:
        src_newest = list_papers("newest", newest_window, page_size)
        _tag_sources(src_newest, f"newest:{newest_window}")
    else:
        print("[info] newest source disabled by policy.enableNewestSource=false",
              flush=True)
    src_recommendations = get_recommendations(token, page_size)
    _tag_sources(src_recommendations, "recommendations")
    src_hf_daily: list[dict[str, Any]] = []
    if enable_hf_daily:
        src_hf_daily = get_huggingface_papers("daily", page_size)
    src_hf_weekly: list[dict[str, Any]] = []
    if enable_hf_weekly:
        src_hf_weekly = get_huggingface_papers("weekly", page_size)
    interest_terms = persona.get("preferred_concepts") or []
    if not interest_terms:
        interest_terms = ["multimodal retrieval"]
    src_interest, interest_per_query = search_all_interests(
        interest_terms, page_size, search_mode=search_mode)

    source_report = {
        "newest": len(src_newest), "newest_window": newest_window,
        "newest_enabled": enable_newest,
        "recommendations": len(src_recommendations),
        "huggingface_daily": len(src_hf_daily),
        "huggingface_weekly": len(src_hf_weekly),
        "interest_total": len(src_interest),
        "interest_per_query": interest_per_query,
        "interest_queries": list(interest_terms),
        "search_mode": search_mode,
    }
    source_status.update({
        "newest": {
            "status": "ok" if (not enable_newest or src_newest) else "empty",
            "count": len(src_newest),
        },
        "recommendations": {
            "status": "ok" if src_recommendations else "empty",
            "count": len(src_recommendations),
        },
        "huggingface_daily": {
            "status": "ok" if (not enable_hf_daily or src_hf_daily) else "empty",
            "count": len(src_hf_daily),
        },
        "interest_search": {
            "status": "ok" if src_interest else "empty",
            "count": len(src_interest),
        },
    })
    if dry_run:
        source_status["dry_run_limits"] = {
            "status": "limited",
            "reason": "dry_run_keeps_network_and_rendering_bounded",
            **dry_run_limits,
        }
    print(f"[info] discovery: newest={source_report['newest']} "
          f"recommendations={source_report['recommendations']} "
          f"hf_daily={source_report['huggingface_daily']} "
          f"hf_weekly={source_report['huggingface_weekly']} "
          f"interest_total={source_report['interest_total']} "
          f"(per_query={interest_per_query})", flush=True)
    if enable_newest and len(src_newest) < page_size:
        print(f"[warn] source 'newest' returned {len(src_newest)} < {page_size}",
              flush=True)
    if len(src_recommendations) < page_size:
        print(f"[warn] source 'recommendations' returned "
              f"{len(src_recommendations)} < {page_size}", flush=True)

    raw: list[dict[str, Any]] = []
    raw += src_newest
    raw += src_recommendations
    raw += src_hf_daily
    raw += src_hf_weekly
    raw += src_interest

    now_iso = utc_now_iso()
    seen_ids = record_seen(persona, [], now_iso)
    raw_after_seen = prune_seen(raw, seen_ids)
    pruned_count = len(raw) - len(raw_after_seen)
    if pruned_count:
        print(f"[info] seen-dedup: dropped {pruned_count} papers seen in last 7d",
              flush=True)

    candidates = dedupe(raw_after_seen)
    max_details = int(policy.get("dailyMaxDetails", 30) or 30)
    if dry_run:
        requested_max_details = max_details
        max_details = min(
            max_details,
            int(policy.get("dryRunMaxDetails", DEFAULT_DRY_RUN_MAX_DETAILS)
                or DEFAULT_DRY_RUN_MAX_DETAILS),
        )
        dry_run_limits["requestedMaxDetails"] = requested_max_details
        dry_run_limits["maxDetails"] = max_details
    candidates = candidates[:max_details]
    if len(candidates) < max_details:
        print(f"[warn] post-dedup candidates={len(candidates)} < "
              f"dailyMaxDetails={max_details}", flush=True)

    print(t(feedback_lang, "stage"), "->", "detail", flush=True)
    detailed: list[dict[str, Any]] = []
    for c in candidates:
        d = paper_detail(c["id"])
        if d:
            detailed.append(d)
        else:
            # paper_detail transient failed (e.g. ProxyError). The candidate
            # dict from discovery already has title/abstract/category; keep it
            # as a degraded entry. triage() will still classify by
            # core_hits/token_hits from whatever fields the candidate has.
            print(f"[warn] paper_detail {c.get('id')} failed after retries; "
                  f"using discovery metadata as fallback", file=sys.stderr,
                  flush=True)
            detailed.append(c)
        time.sleep(0.05)

    # Build HF top N (interest-agnostic ranking by HF upvotes, separate section)
    hf_top10: list[dict[str, Any]] = []
    hf_seen: set[int] = set()
    for hp in src_hf_daily[:hf_top_n]:
        pid = hp.get("id")
        if pid is None:
            continue
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_int in hf_seen:
            continue
        hf_seen.add(pid_int)
        d = paper_detail(pid_int) or (hp if hp.get("title") else None)
        if not d:
            # paper_detail failed AND hf metadata has no title (matched=false
            # in HF upstream). Skip; never include a paper with no
            # title/abstract in the digest (would be a garbage row).
            print(f"[warn] HF paper {pid_int} skipped: detail failed + "
                  f"no title in HF metadata", file=sys.stderr, flush=True)
            continue
        merged = {**hp, **d}
        tags = list(dict.fromkeys((hp.get("source_tags") or []) +
                                   (d.get("source_tags") or [])))
        merged["source_tags"] = tags or ["huggingface:daily"]
        hf_top10.append({
            "paperId": merged.get("id"),
            "title": merged.get("title"),
            "hfRank": hp.get("_huggingface_rank"),
            "hfUpvotes": hp.get("_huggingface_upvotes"),
            "hfComments": hp.get("_huggingface_comments"),
            "abstract": merged.get("abstract") or "",
            "eng_script": merged.get("eng_script") or "",
            "cn_abstract": merged.get("cn_abstract") or "",
            "cn_script": merged.get("cn_script") or "",
            "external_id": merged.get("external_id") or "",
            "pub_url": merged.get("pub_url") or "",
            "key_fig_url": merged.get("key_fig_url") or "",
            "key_tab_url": merged.get("key_tab_url") or "",
            "plain_authors": merged.get("plain_authors") or "",
            "eng_affiliation_names": merged.get("eng_affiliation_names") or [],
            "cn_affiliation_names": merged.get("cn_affiliation_names") or [],
            "arxiv_categories": merged.get("arxiv_categories") or [],
            "eng_keywords": merged.get("eng_keywords") or [],
            "cn_keywords": merged.get("cn_keywords") or [],
            "gpt_kwds": merged.get("gpt_kwds") or [],
            "venue_name": merged.get("venue_name") or "",
            "venue_names": merged.get("venue_names") or [],
            "publication_date": merged.get("publication_date") or "",
            "code_url": merged.get("code_url") or "",
            "github_stars": merged.get("github_stars") or 0,
            "citation_count": merged.get("citation_count") or 0,
            "summary": _build_skim_summary(merged, digest_lang),
            "paperType": classify_paper_type(merged),
            "source_tags": merged.get("source_tags", []),
        })
        time.sleep(0.03)

    print(t(feedback_lang, "stage"), "->", t(feedback_lang, "triage"), flush=True)
    evidence_pack = []
    unrelated_filtered = []
    interest_related_count = 0
    must_read, skim, skip = [], [], []
    must_read_ranked: list[dict[str, Any]] = []
    skim_ranked: list[dict[str, Any]] = []
    for d in detailed:
        bucket, th, ch, score = triage(d, focus_tokens, persona)
        persona_signals = _persona_interest_signals(d, persona)
        interest_related = (
            ch >= 1 or th >= 1
            or _has_persona_interest_signal(persona_signals)
        )
        rich = {
            "abstract": d.get("abstract") or "",
            "eng_script": d.get("eng_script") or "",
            "cn_abstract": d.get("cn_abstract") or "",
            "cn_script": d.get("cn_script") or "",
            "external_id": d.get("external_id") or "",
            "pub_url": d.get("pub_url") or "",
            "key_fig_url": d.get("key_fig_url") or "",
            "key_tab_url": d.get("key_tab_url") or "",
            "plain_authors": d.get("plain_authors") or "",
            "eng_affiliation_names": d.get("eng_affiliation_names") or [],
            "cn_affiliation_names": d.get("cn_affiliation_names") or [],
            "arxiv_categories": d.get("arxiv_categories") or [],
            "eng_keywords": d.get("eng_keywords") or [],
            "cn_keywords": d.get("cn_keywords") or [],
            "gpt_kwds": d.get("gpt_kwds") or [],
            "venue_name": d.get("venue_name") or "",
            "venue_names": d.get("venue_names") or [],
            "publication_date": d.get("publication_date") or "",
            "code_url": d.get("code_url") or "",
            "github_stars": d.get("github_stars") or 0,
            "citation_count": d.get("citation_count") or 0,
            "summary": _build_skim_summary(d, digest_lang),
        }
        record = {
            "paperId": d.get("id"), "title": d.get("title"),
            "evidence_scope": "metadata_only",
            "sources_used": ["title", "abstract", "eng_keywords"],
            "missing_sources": ["core_knowledge", "pdf_text"],
            "score": score, "token_hits": th, "core_hits": ch,
            "bucket": bucket, "interest_related": interest_related,
            "personaSignals": persona_signals,
            "paperType": classify_paper_type(d),
            "source_tags": d.get("source_tags", []),
        }
        record.update(rich)
        if not interest_related:
            record["bucket"] = "unrelated_filtered"
            record["filtered_reason"] = "no_core_hit_no_focus_token_no_persona_signal"
            evidence_pack.append(record)
            unrelated_filtered.append({
                "paperId": d.get("id"), "title": d.get("title"),
                "score": score, "core_hits": ch, "token_hits": th,
                "bucket": "unrelated_filtered",
                "paperType": classify_paper_type(d),
                "source_tags": d.get("source_tags", []),
                "filtered_reason": record["filtered_reason"],
            })
            continue
        interest_related_count += 1
        evidence_pack.append(record)
        if bucket == "must_read":
            entry = {"detail": d, "token_hits": th, "core_hits": ch,
                     "score": score, "bucket": bucket}
            must_read_ranked.append(entry)
            must_read.append({
                "paperId": d.get("id"), "title": d.get("title"),
                "reason": f"{t(feedback_lang,'core_field')}={ch} "
                          f"{t(feedback_lang,'tokens_field')}={th} "
                          f"{t(feedback_lang,'score_field')}={score}",
                "evidence_scope": "metadata_only",
                "score": score, "core_hits": ch, "token_hits": th,
                "interest_related": interest_related,
                "personaSignals": persona_signals,
                "paperType": classify_paper_type(d),
                "source_tags": d.get("source_tags", []),
                **rich,
            })
        elif bucket == "skim":
            skim_ranked.append({"detail": d, "token_hits": th, "core_hits": ch,
                                "score": score, "bucket": bucket})
            skim.append({
                "paperId": d.get("id"), "title": d.get("title"),
                "core_hits": ch, "token_hits": th, "score": score,
                "interest_related": interest_related,
                "personaSignals": persona_signals,
                "paperType": classify_paper_type(d),
                "source_tags": d.get("source_tags", []),
                **rich,
            })
        else:
            skip.append({
                "paperId": d.get("id"), "title": d.get("title"),
                "core_hits": ch, "token_hits": th, "score": score,
                "bucket": bucket,
                "interest_related": interest_related,
                "personaSignals": persona_signals,
                "paperType": classify_paper_type(d),
                "source_tags": d.get("source_tags", []),
                **rich,
            })

    must_read_ranked.sort(key=lambda e: e["score"], reverse=True)
    skim_ranked.sort(key=lambda e: e["score"], reverse=True)

    triaged_ids = [d.get("id") for d in detailed if d.get("id") is not None]
    if dry_run:
        print(f"[info] dry-run: not recording {len(triaged_ids)} seen-paper ids",
              flush=True)
    else:
        record_seen(persona, triaged_ids, now_iso)
        save_json(home / "persona.json", persona)
        print(f"[info] recorded {len(triaged_ids)} seen-paper ids "
              f"(7d window now holds {len(persona.get('seen_paper_ids', []))})",
              flush=True)

    print(t(feedback_lang, "stage"), "->", t(feedback_lang, "actions"), flush=True)
    ranked_for_actions: list[dict[str, Any]] = []
    for e in must_read_ranked:
        ranked_for_actions.append({**e, "bucket": "must_read"})
    for e in skim_ranked:
        ranked_for_actions.append({**e, "bucket": "skim"})

    # Main does not execute platform writes. It emits action proposals;
    # the external agent writes agent_actions.json and execute-actions gates it.
    results: list[dict[str, Any]] = []
    proposal_papers: list[dict[str, Any]] = []
    for entry in ranked_for_actions:
        detail = dict(entry.get("detail", {}))
        detail["bucket"] = entry.get("bucket", "must_read")
        detail["score"] = entry.get("score", 0)
        proposal_papers.append(detail)
    proposals = _build_action_proposals_for_papers(
        proposal_papers, comment_lang, policy,
    )
    save_json(run_dir / "action_proposals.json", proposals)
    print(f"[info] wrote {len(proposals)} action proposals to "
          f"action_proposals.json (agent will decide in heartbeat)",
          flush=True)

    reply_proposals, reply_results, heartbeat_summary = process_comment_interactions(
        token, user_id, username,
        [e["detail"] for e in ranked_for_actions],
        policy, interaction_state, comment_lang, dry_run=dry_run,
    )
    if not dry_run:
        interaction_state["lastHeartbeatAt"] = utc_now_iso()
        save_interaction_state(home, interaction_state)

    digest = {
        "date": today,
        "userId": user_id,
        "username": username,
        "summary": t(digest_lang, "summary_template",
                     c=len(candidates), mr=len(must_read),
                     sk=len(skim), sp=len(skip), ac=len(results)),
        "evidenceSummary": {
            "metadataOnly": len(detailed),
            "coreKnowledge": 0, "relatedPaper": 0, "pdfParsed": 0,
        },
        "discoverySources": source_report,
        "huggingFaceTop10": hf_top10,
        "mustRead": must_read,
        "skim": skim,
        "interestRelatedCount": interest_related_count,
        "unrelatedFilteredCount": len(unrelated_filtered),
        "unrelatedFiltered": unrelated_filtered,
        "skip": skip,
        "skip_total": len(skip),
        "skip_displayed": min(len(skip), int(policy.get("skipDisplayLimit", 10))),
        "actionProposals": proposals,
        "actionResults": results,
        "replyProposals": reply_proposals,
        "replyResults": reply_results,
        "heartbeatSummary": heartbeat_summary,
        "language": {
            "comment": comment_lang, "digest": digest_lang,
            "feedback": feedback_lang, "stored": stored_lang,
        },
    }

    digest["sourceStatus"] = source_status
    digest["discussionStatus"] = {
        "scannedComments": heartbeat_summary.get("scannedComments", 0),
        "replyProposals": heartbeat_summary.get("replyProposals", 0),
        "commentLikeProposals": heartbeat_summary.get("commentLikeProposals", 0),
    }
    digest = _merge_digest(existing_digest, digest, policy)
    save_json(run_dir / "evidence_pack.json", evidence_pack)
    try:
        _rerender_digest_files(run_dir, digest, stored_lang, digest_lang,
                               inline_images=not dry_run)
        if dry_run:
            print("[info] dry-run: wrote lightweight html (no image inlining)",
                  flush=True)
    except Exception as exc:
        print(f"[warn] html digest render failed: {exc}",
              file=sys.stderr, flush=True)
    save_json(run_dir / "action_proposals.json", proposals)
    save_json(run_dir / "action_results.json", results)
    save_json(run_dir / "reply_proposals.json", reply_proposals)
    save_json(run_dir / "reply_results.json", reply_results)
    save_json(run_dir / "heartbeat_summary.json", {
        **heartbeat_summary, "mode": "daily",
        "paperCount": len(ranked_for_actions),
        "sourceStatus": source_status,
        "generatedAt": utc_now_iso(),
    })
    save_json(run_dir / "persona_update.json", {
        "userId": str(user_id), "eventType": "daily_run",
        "source": "daily_runner", "language": feedback_lang,
        "metadata": {
            "interest_count": len(interests),
            "candidate_count": len(candidates),
            "interest_related_count": interest_related_count,
            "unrelated_filtered_count": len(unrelated_filtered),
            "must_read_count": len(must_read),
            "actions_executed": len(results),
            "reply_actions_executed": len(reply_results),
            "dry_run": dry_run,
        },
        "personaPatch": {
            "trajectory": [{
                "period": today,
                "focus": "multimodal retrieval",
                "must_read_titles": [m["title"] for m in must_read[:5]],
                "actions": [{"type": r["actionType"], "paperId": r["paperId"]}
                            for r in results],
            }],
        },
    })
    print(t(feedback_lang, "ok_daily_run_finished",
            mr=len(must_read), sk=len(skim), sp=len(skip), ac=len(results)),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
