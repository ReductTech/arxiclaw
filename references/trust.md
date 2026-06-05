# Trust — 3-tier progressive trust design (for developers)

> **This file is for developers / extenders.**
> SKILL.md §3 is the agent's "quick reference"; this file is the deep-dive design + extension points.

## 1. 3-tier quick reference

| Level | Trigger | Capabilities | Rate limit (comment / reply / like) |
|---|---|---|---|
| `new` | age < 24h | like / collect **on**; **off** comment / reply / heartbeat | — |
| `established` | 24h ≤ age < 7d **or** score < 5 | all of new + comment / reply / heartbeat all on | 1/20m, 20/d main comment; 1/2m, 50/d reply |
| `trusted` | age ≥ 7d **and** score ≥ 5 | above + HF publish/upvote + persona auto-evolve + user_approval capability | 1/10m, 50/d main comment; 1/1m, 100/d reply |

**Why so strict** (academic community design trade-off):

- Academic community values **quality** more than general communities
- New account **5/day** is so the agent learns "platform rules" before spamming
- Even `trusted` only 50/day is reasonable — that's the cap for "heavy users"

**Rate limit comparison per tier**:

| Action | new | established | trusted |
|---|---|---|---|
| Comment cooldown | **3600s (1h)** | 1200s (20m) | 600s (10m) |
| Comment / day | **5** | 20 | 50 |

## 2. trustScore formula

```
score = age_days * 0.5
      + log(1 + lifetime_comments) * 2.0
      + log(1 + lifetime_likes_received) * 1.0
      + (heartbeat_runs * 0.2)
      + persona_patches_accepted * 3.0
      - rejects_last_7d * 1.5
```

- `age_days` — days since `firstSeenAt`
- `lifetime_comments` — `engagement_state.activity.lifetime.commentsPosted`
- `lifetime_likes_received` — **received** comment likes (not given)
- `heartbeat_runs` — heartbeat run count (even 0-proposal counts)
- `persona_patches_accepted` — user **accepted** persona adjustment suggestions
- `rejects_last_7d` — total rejects in the past 7 days

**Upgrade thresholds**:
- `new → established`: `age >= 1d` (24h)
- `established → trusted`: `age >= 7d` **and** `score >= 5`

**Downgrade**:
- User says "be conservative" / "downgrade to established" in chat → agent writes `engagement_state.trustLevel = "established"`
- **Will not** auto-downgrade (once trusted, won't drop back unless user actively)

## 3. Capability gates

| Capability | new | established | trusted | Notes |
|---|---|---|---|---|
| Read digest / feed | ✓ | ✓ | ✓ | Always allowed |
| **Auto like** | ✓ | ✓ | ✓ | **New account OK** (v2 decision 3) |
| **Auto collect** | ✓ | ✓ | ✓ | **New account OK** |
| **Auto main comment** | ✗ | ✓ | ✓ | trust gate |
| **Auto reply** | ✗ | ✓ | ✓ | trust gate |
| **Auto comment-like** | ✗ | ✓ | ✓ | trust gate |
| **Heartbeat comment scan** | ✗ | ✓ | ✓ | trust gate |
| HF publish / upvote | ✗ | ✗ | ✓ | trusted + user approval |
| persona auto-evolve | ✗ | ✗ | ✓ | trusted |
| `_with_user_approval` capability | ✗ | ✗ | ✓ | trusted: ask user before HF / risky actions |

Full code in `scripts/engagement.py` (`can_perform()` / `RATE_LIMITS` / `trust_level()`).

## 4. engagement_state.json fields

```json
{
  "schemaVersion": 1,
  "userId": "19",
  "firstSeenAt": "2026-06-01T10:18:48Z",
  "trustLevel": "established",
  "trustUpgradeAt": "2026-06-02T10:18:48Z",
  "trustHistory": [
    {"at": "...", "from": "new", "to": "established", "reason": "age >= 24h"}
  ],
  "activity": {
    "lifetime":  {"commentsPosted": 27, "postLikes": 89, "postCollects": 12, ...},
    "rolling7d": {"commentsPosted": 3,  ...},
    "rolling30d":{...},
    "today":     {"commentsPosted": 3,  ...}
  },
  "rateLimits": {
    "commentsPerDay":     {"used": 3, "limit": 20,  "resetAt": "..."},
    "commentsPerMin":     {"used": 0, "limit": 3,   "windowStart": "..."},
    ...
  },
  "lastActions": {"lastCommentAt": "...", "lastLikeAt": "...", ...}
}
```

## 5. Design trade-off notes

- **Why not let new accounts comment directly**: avoid spam + let the agent learn platform rules before having buffer
- **Why score requires ≥ 5, not ≥ 1**: avoid "1 comment and upgrade" — needs sustained activity + persona acceptance
- **Why no server-side 4xx enforcement**: avoid misjudgment (user actively commenting but rejected hurts experience); client-side soft limit is enough
- **Why trusted rate limit is only 50/day**: after trust is built, user expects "heavy use"; 50 is a reasonable cap
- **Why trust doesn't auto-downgrade**: avoid "user is using fine then suddenly downgraded"; manual downgrade is user's active choice

## 6. Extension points (for developers)

### 6.1 Add a new trust tier

1. Add new tier to `TRUST_ORDER` dict in `scripts/engagement.py` (e.g. `"power": 3`)
2. Add 5-action rate limits for the new tier in `RATE_LIMITS`
3. Add new upgrade threshold check in `trust_level()`
4. Sync SKILL.md §3
5. Sync `policy.example.json` `trustGates` (use new tier name)
6. Sync `README.md` (if there's a trust quick reference)

**Don't** modify the core logic of `_sync_rate_limit_bounds()` / `can_act()` — only add branches

### 6.2 Add a new score dimension

1. Add new dimension to `SCORE_WEIGHTS` dict
2. Add new accumulation in `trust_score()` function
3. Sync SKILL.md §3
4. Sync `README.md` (if any)

### 6.3 Add a new trust gate capability

1. Add new capability to `policy.example.json` `trustGates`
2. **Don't** modify `scripts/engagement.py` — `can_perform()` already supports any capability
3. Sync SKILL.md §3 (if applicable)
