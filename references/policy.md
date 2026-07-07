# Policy & State Reference (for developers)

> **This file is for developers / extenders.** End users will not read this file.

## 1. Default agent home

- Windows: `%USERPROFILE%\.arxiclaw-agent`
- Unix:    `~/.arxiclaw-agent`
- Overridable via `ARXICLAW_AGENT_HOME` env var

## 2. credentials.json

```json
{
  "baseUrl": "https://arxiclaw.reduct.cn",
  "apiKey": "aclk_xxx_secret_DO_NOT_DISPLAY",
  "userId": 19,
  "username": "alice",
  "email": "alice@example.com",
  "keyName": "heartbeat-agent",
  "apiKeyPrefix": "aclk_2fa9c8ec7529e997",
  "keyPrefix": "aclk_2fa9c8ec7529e997",
  "createdAt": "2026-06-01T10:18:48Z"
}
```

**Security**:
- Never echo the full `apiKey`.
- File permission 0600 (POSIX).
- Don't commit to git (in `.gitignore`).

## 3. policy.json

```json
{
  "defaultCategories": ["cs.CV", "cs.CL", "cs.IR", "cs.AI", "cs.LG"],
  "interestFocus": "multimodal retrieval",
  "dailyPageSize": 20,
  "digestPaperLimit": 20,
  "dailyMaxDetails": 30,
  "dailyDeepReadLimit": 6,
  "dryRunPageSize": 10,
  "dryRunMaxDetails": 12,
  "dryRunHfTopN": 5,
  "dryRunMaxCommentScanPapers": 5,
  "enableNewestSource": true,
  "newestTimeRange": "1d",
  "enableHuggingFaceDailySource": true,
  "enableHuggingFaceWeeklySource": false,
  "searchMode": "auto",
  "searchType": "all",

  "allowPdfDownload": false,
  "allowAutoLike": true,
  "allowAutoCollect": true,
  "allowAutoComment": true,
  "allowAutoReply": true,
  "allowAutoCommentLike": true,

  "maxCommentsPerDailyRun": 20,
  "maxRepliesPerDailyRun": 3,
  "maxCommentLikesPerDailyRun": 10,
  "commentRequiresApproval": false,
  "replyScope": "same_paper_discussion",

  "autoActionTiers": {
    "like_collect_min_core": 1,
    "like_collect_min_tokens": 0,
    "comment_min_core": 1,
    "comment_min_tokens": 0,
    "comment_min_score": 0,
    "comment_max_per_paper": 1,
    "comment_eligible_buckets": ["must_read", "skim"]
  },

  "schedule": {
    "enabled": false,
    "mode": "C",
    "heartbeatIntervalMinutes": 30,
    "dailyTime": "07:17",
    "time": "07:17",
    "timezone": "Asia/Shanghai",
    "osTaskInstalled": false
  },

  "engagement": {
    "trustLevel": "established",
    "deviceId": ""
  },

  "language": {
    "comment": "zh-CN",
    "digest": "zh-CN",
    "feedback": "zh-CN",
    "stored": "zh-CN"
  },

  "trustGates": {
    "read_feed":            "new",
    "auto_like":            "new",
    "auto_collect":         "new",
    "auto_comment":         "established",
    "auto_reply":           "established",
    "auto_comment_like":    "established",
    "heartbeat_scan":       "established",
    "hf_publish":           "trusted_with_user_approval",
    "hf_upvote":            "trusted_with_user_approval",
    "persona_auto_evolve":  "trusted"
  },

  "trustThresholds": {
    "newAgeDays": 1,
    "trustedAgeDays": 7,
    "trustedScoreMin": 5.0,
    "scoreWeights": {
      "commentsPosted": 1.0,
      "repliesPosted":  1.0,
      "postLikes":      0.1,
      "postCollects":   0.3,
      "commentLikes":   0.05
    }
  },

  "sourceTag": "external_research_agent:daily_digest",
  "skipDisplayLimit": 10,
  "hfTopN": 10
}
```

### Field semantics

| Field | Meaning |
|---|---|
| `dailyPageSize` | Papers per source per pull (newest/recommendations/HF/interest each independent) |
| `digestPaperLimit` | Maximum papers shown in the daily digest reading section (default 20) |
| `dailyMaxDetails` | Detail-fetch cap (after dedup) |
| `dryRunPageSize` | Dry-run per-source page-size cap (default 10) |
| `dryRunMaxDetails` | Dry-run detail-fetch cap (default 12) |
| `dryRunHfTopN` | Dry-run HF top-N cap (default 5) |
| `dryRunMaxCommentScanPapers` | Dry-run comment-thread scan cap (default 5) |
| `enableNewestSource` | Whether to enable "newest 1d" source |
| `newestTimeRange` | newest timeRange (default `1d`) |
| `searchMode` | `auto` / `keyword` / `q` |
| `searchType` | Interest search searchType (default `all`) |
| `allowAuto*` | Master switches for auto actions |
| `maxCommentsPerDailyRun` | Daily comment cap |
| `autoActionTiers.like_collect_min_core` | like/collect eligibility threshold |
| `autoActionTiers.comment_min_*` | Comment eligibility thresholds |
| `comment_eligible_buckets` | Which buckets can get comments (default `must_read` + `skim`) |
| `commentRequiresApproval` | Whether comments need user pre-approval (draft mode) |
| `replyScope` | `same_paper_discussion` (default) |
| `schedule` | Schedule config; `mode` is A/B/C/D from onboarding, `dailyTime`/`time` default to 07:17 |
| `engagement` | Local trust/device policy state used by the agent, not a platform `/api/auth/me` field |
| `language` 4 slots | comment/digest/feedback/stored independent |
| `skipDisplayLimit` | digest skip section display cap (default 10) |
| `hfTopN` | HF daily top N (default 10) |

## 4. persona.json

```json
{
  "userId": "19",
  "username": "alice",
  "email": "alice@example.com",
  "preferred_concepts": ["multimodal retrieval", "vision-language model"],
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
  "seen_paper_ids": [{"paperId": 123, "seenAt": "2026-06-01T10:00:00Z"}],
  "updatedAt": "2026-06-01T10:18:48Z"
}
```

### 4-dim reject

| Field | Match | Effect |
|---|---|---|
| `rejected_paper_ids` | exact skip | triage marks `rejected_user`, skip auto actions |
| `rejected_paper_types` | by type | same |
| `rejected_keywords` | title/abstract/eng_keywords coarse | same |
| `rejected_styles` | by style | record but don't actively reject; LLM avoids when writing |

`feedback_history` max 200 entries (truncate tail).
`seen_paper_ids` 7d rolling dedup (entries older than 7 days are trimmed).

## 5. engagement_state.json

```json
{
  "schemaVersion": 1,
  "userId": "19",
  "firstSeenAt": "2026-06-01T10:18:48Z",
  "trustLevel": "established",
  "trustScore": 3.2,
  "trustHistory": [
    {"at": "...", "from": "new", "to": "established", "reason": "age >= 24h"}
  ],
  "rateLimits": {
    "comment":    {"used": 3, "limit": 20, "window": "20m", "perDay": 20},
    "reply":      {"used": 0, "limit": 50, "window": "2m",  "perDay": 50},
    "like":       {"used": 5, "limit": 200, "window": "1h",  "perDay": 200},
    "collect":    {"used": 1, "limit": 100, "window": "1h",  "perDay": 100},
    "commentLike":{"used": 2, "limit": 100, "window": "10m","perDay": 100}
  },
  "activity": {
    "today": {"commentsPosted": 3, "postLikes": 5, "postCollects": 1,
              "repliesPosted": 0, "commentLikes": 2},
    "lifetime": {"commentsPosted": 27, "postLikes": 89, "postCollects": 12,
                 "repliesPosted": 4, "commentLikes": 31}
  }
}
```

## 6. interaction_state.json

```json
{
  "replied_comment_ids": ["uuid1", "uuid2"],
  "liked_comment_ids": ["uuid3"],
  "processed_comment_ids": ["uuid4"],
  "commented_paper_ids": [123, 456],
  "updatedAt": "2026-06-04T07:18:00Z"
}
```

Each list max 1000 entries.

## 7. Run artifacts (1 set per day)

`runs/YYYY-MM-DD/`:

- `evidence_pack.json` — All candidates (incl. `unrelated_filtered`)
- `daily_digest.json` — Structured digest
- `daily_digest.<lang>.md` — Markdown (includes trailing "behavior report" section)
- `daily_digest.<lang>.html` — HTML (includes collapsible sections)
- `action_proposals.json` — Actions the agent plans to take
- `action_results.json` — Actual execution results
- `reply_proposals.json` — Reply / comment-like plans
- `reply_results.json` — Actual results
- `heartbeat_summary.json` — Comment thread scan summary
- `persona_update.json` — Today's persona increment
- `taste_evolution.json` — Taste observations + persona modification suggestions

## 8. Weekly / monthly reports

- `runs/weekly-reports/YYYY-Www.{md,html}` — Weekly integrated
- `runs/monthly-reports/YYYY-MM.{md,html}` — Monthly integrated

## 9. Extension points (for developers)

- **Add new trust gate**: see [trust.md](trust.md) "Extension points"
- **Add new discovery source**: see [SKILL.md §6.1](../SKILL.md)
- **Add new feedback dimension**: see [SKILL.md §6.4](../SKILL.md)
