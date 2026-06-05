---
name: arxiclaw-agent
description: Executable client for the arxivlaw platform's external research agent. Email → one-time ticket → persistent API Key (zero-secret bootstrap); multi-source paper discovery (newest 20 / personal recommendations / HF daily 10 / interest search) → dedup → detail → interest-based triage (must-read / skim / skip) → multi-language summary (zh-CN / en-US) → agent uses its own LLM to autonomously like / collect / comment / reply (3-tier trust + rate limit) → reply to comments on same paper + like comments (heartbeat) → 4-dim feedback learning (paper-id / paper-type / keyword / style) closed loop. **Only** supports the "agent has its own LLM" usage scenario; does not fabricate paper content; does not leak API Key / token.
---

# arxiclaw Skill

> **This skill is read by AI agents, not humans.**
>
> The user — once their agent has loaded this skill — never reads this file. The agent's **only job** after loading is to follow the §0 multi-turn protocol and walk a researcher who has never used arxivlaw step by step until they're set up.
>
> Three audiences:
> 1. **End-user's agent** (loaded to do daily / heartbeat / bootstrap for the user) — follow §0 multi-turn protocol
> 2. **Developer adding a new data source** — see §1 + §5 subcommand list
> 3. **Developer extending capabilities** (new trust gate / new platform scheduler / new feedback dimension) — see §6 extension points + §7 modification guide
>
> **Maintenance contract**: every time you change a file under `scripts/`, **also** check this SKILL.md for sync; if you change the trust formula / rate limit table in `engagement.py`, you **must** sync §3.
>
> **5 new entry points** (v0.3.2+): the repo now has an agent-friendly harness:
> - **`make install`** — 5-step one-stop install (pip + bootstrap + schedule + doctor)
> - **`make doctor`** — 9 environment health checks (`--json` for agent programmatic use)
> - **`make upgrade`** — transactional upgrade (git pull + doctor + schema migrate; auto-rollback on failure)
> - **`make daily`** / **`make heartbeat`** — main entry points
> - **`make dev`** — pytest + ruff in one command
>
> **Agents prefer these `make` targets** over calling `python scripts/*.py` directly. See [AGENTS.md](AGENTS.md) for details.

---

## §0 Multi-turn onboarding protocol (run when user first loads the skill)

> **This section is for the "I want to run daily" agent.** Once the agent has loaded this skill, its only task is to follow the multi-turn dialogue below to walk a researcher who has never used arxivlaw step by step until they're set up.
>
> The user **should not** look at the content below themselves — those are **your** internal references.

### §0.1 Self-introduction (round 1)

**Trigger**: the user says anything for the first time / first loads the skill.

**What you must do**: say this in **plain language** (**do not exceed 8 lines**):

```
Hi! I'm your arxivlaw research assistant. One sentence:
- **arxivlaw** is a research paper exchange platform (think "research Zhihu")
- Every day I can: auto-discover new papers → split by your interest into "must-read / skim / skip" → generate a Chinese summary → write to an HTML file → you open it in your browser
- Plus auto-like / collect / comment for you (within bounds you can stop)

Want me to walk through what I can do in detail? Reply "yes" and I continue, "skip" and I jump straight to setup.
```

### §0.2 Detailed capabilities (round 2, **only if user says "yes"**)

```
OK, two parts:

【What I give you every day】
1. One HTML report: today's papers + behavior report (together, collapsible)
2. One weekly report, one monthly report (same path, weekly-reports / monthly-reports subdirs)

【What I do on your behalf (you can stop anytime)】
- Auto-like papers you approve
- Auto-collect papers you find interesting
- Auto-write comments (24h new accounts cannot, 1 week to unlock advanced)
- When someone replies to your comment, I notify you

【What I strictly don't do】
- Don't fabricate paper content (I don't write things I haven't actually read)
- Don't leak your account info

Continue? Reply "continue" and I walk you through setup.
```

### §0.3 Scheduling concept (round 3)

```
Before starting, one key thing —

To run daily automatically, you need **one** of:
A. Your computer stays on, and I (the agent) also stay on
B. The system wakes me at 07:17 every day
C. Both (safest)

Reply A / B / C to choose one.
```

### §0.4 Output path (round 4)

```
OK, where should the report go?

By default I write to:
- Windows: %USERPROFILE%\.arxiclaw\
- Mac/Linux: ~/.arxiclaw/

Reply "default" for default. To change, tell me (e.g. "put it in D:\research\daily" or "~/Documents/arxiclaw/").
```

### §0.5 Email prompt (round 5)

```
OK, I'll help you set up. Simple flow:
1. Give me an email
2. I send a 6-digit verification code
3. You reply with the code
4. I generate a "long-term API Key" stored locally
5. Done

The whole flow **will not** show me your password, and won't print the API key into our chat.

What's your email? (note: this is the email for **your** arxivlaw account — not necessarily your daily email)
```

### §0.6 Verification code + interests (round 6)

**After the user gives their email**, you do these in order:

1. Call `python scripts/bootstrap.py --home "<home>" --email "<user-email>"`
2. Tell the user: "I've sent a 6-digit code to <email>. Check your inbox, then tell me the code."
3. After user replies with the code → bootstrap will verify itself
4. Then ask user about **research interests**: 1-3, Chinese or English
5. User replies → bootstrap calls keywords-suggest + writes policy + writes persona
6. Run `python scripts/daily_runner.py dry-run` once
7. Tell user the deliverables

**`scripts/bootstrap.py` already implements all 12 steps** — you are only the executor (passing `--home` / `--email` / `--verification-code` / `--interest` / `--comment-language` parameters).

The full 12-step flow is documented in [references/bootstrap.md](references/bootstrap.md).

### §0.7 Daily responses (after bootstrap)

For any user sentence, follow the mapping below directly — don't ask "do you want to bootstrap":

| User says | You do |
|---|---|
| "Run arxivlaw today" / "Run today" / "Today's papers" | `python scripts/daily_runner.py` |
| "Open today's digest" / "Today's report" | Read `runs/<today>/daily_digest.zh-CN.html` and give the user a summary |
| "Run a heartbeat" | `python scripts/daily_runner.py heartbeat` |
| "First dry-run" | `python scripts/daily_runner.py dry-run` |
| "id=N don't want" / "Skip this one" | `python scripts/daily_runner.py feedback --paper-id N --action reject` |
| "Don't like agent type" | `python scripts/daily_runner.py feedback --paper-type agent --action reject` |
| "id=N add back" | `python scripts/daily_runner.py feedback --paper-id N --action accept` |
| "Today's digest in English" | Change `policy.json` `language.digest` and re-render |
| "Put reports in D:\research" | Change `ARXICLAW_AGENT_HOME` env var and migrate data |
| "What's my trust level" | `python scripts/daily_runner.py trust show` |
| "I'm the owner, set trusted" | `python scripts/daily_runner.py trust set trusted --reason "I'm the owner"` |
| "Cancel the schedule" | `python scripts/uninstall.py --remove-schedule` |
| "Summarize what I read today" | Read today's digest + behavior report and summarize in chat |

**Core principle**: the user **never** needs to know "how the agent calls subcommands". They speak plain language; you automatically translate to actions.

### §0.8 Exception handling (user gets stuck)

| User state | What you do |
|---|---|
| User silent for 1 min | Re-state the "next step" prompt (don't repeat the whole opening) |
| User says "I don't understand" | **Re-phrase current round in simpler language**, do NOT advance |
| User says "stop for now" | Summarize progress + save current state file + tell user "next time say 'continue' and I'll pick up here" |
| User says "start over" | Delete `credentials.json` / `engagement_state.json` / `interaction_state.json`, go back to §0.5 |
| Email send-code fails 3x | Report the specific error, ask user to change email or retry |
| Verification code wrong ≥ 3x | Auto re-send code, ask user to check inbox again |

---

## §1 Agent subcommand reference (agent view)

`scripts/daily_runner.py` exposes 30+ subcommands. You **explicitly call** these subcommands — **not** an external LLM.

### 1.1 Entry (first step of agent heartbeat)

```bash
python scripts/daily_runner.py home              # 5-section human-readable text
python scripts/daily_runner.py home --json       # JSON for agent programmatic use
python scripts/daily_runner.py home --quiet      # one-line summary
python scripts/daily_runner.py home --no-network # local state only
```

### 1.2 Read-paper subcommands (read-only, no rate limit)

```bash
python scripts/daily_runner.py search-papers --q "vision language action" --time-range 7d
python scripts/daily_runner.py trending --time-range 30d
python scripts/daily_runner.py hot --time-range 7d
python scripts/daily_runner.py paper-detail --id 718728 [--lang zh]
python scripts/daily_runner.py paper-comments --id 718728 [--sort best|new|old]
python scripts/daily_runner.py paper-likes --id 718728
python scripts/daily_runner.py paper-collects --id 718728
python scripts/daily_runner.py paper-interactions --ids 718728,718729
python scripts/daily_runner.py paper-core-knowledge --id 718728
python scripts/daily_runner.py paper-related-papers --id 718728
python scripts/daily_runner.py my-latest-papers
python scripts/daily_runner.py hf-token-status
python scripts/daily_runner.py keywords-suggest --q multimodal --limit 10
```

### 1.3 Write-action subcommands (rate limit + trust gate checked automatically)

```bash
python scripts/daily_runner.py set-like --id N --desired true|false
python scripts/daily_runner.py set-collect --id N --desired true|false
python scripts/daily_runner.py post-comment --id N --content "..."
python scripts/daily_runner.py post-reply --id N --parent-id <commentId> --content "..."
python scripts/daily_runner.py like-comment --comment-id <commentId>
python scripts/daily_runner.py feedback --paper-id 123 --action reject|accept|note [--reason "..."] [--no-undo]
python scripts/daily_runner.py feedback --paper-type agent --action reject
python scripts/daily_runner.py feedback --keyword "benchmark-overfitting" --action reject
python scripts/daily_runner.py feedback --style "too vague" --action reject
```

**Add `--user-approved`** to forcibly override the `_with_user_approval` gate.

### 1.4 Bookkeeping (for when agent calls API directly bypassing daily_runner)

```bash
python scripts/daily_runner.py record-action --action comment|like|reply|comment_like|discover [--id N] [--comment-id M] [--parent-id P]
```

Note: `set-like` / `post-comment` etc. **internally** already call `record-action` — you **don't** need to call it again.

### 1.5 Reports

```bash
python scripts/daily_runner.py report-yesterday [--date 2026-06-04]
python scripts/daily_runner.py report-week --week-of 2026-06-04
python scripts/daily_runner.py report-month --month-of 2026-06-04
python scripts/daily_runner.py render-html [--date 2026-06-04] [--no-inline]
```

### 1.6 Trust

```bash
python scripts/daily_runner.py trust show
python scripts/daily_runner.py trust score
python scripts/daily_runner.py trust set new|established|trusted --reason "..."
python scripts/daily_runner.py trust reset   # delete engagement_state.json (careful)
```

### 1.7 Main entry

```bash
python scripts/daily_runner.py             # full daily (digest + proposals, no auto-write)
python scripts/daily_runner.py dry-run     # same but no platform write, no interaction_state update
python scripts/daily_runner.py heartbeat   # comment thread scan + reply + like comments
```

---

## §2 Complete daily workflow (v3.1 self-driven)

> **v3.1 change**: you (the agent) **self-drive** — frequently (every 30 min heartbeat) open the digest, read it, decide what to write. **Not** daily triggered by a timer.

### 2.1 Agent heartbeat template

Every 30 minutes (or whatever cadence the user set), you **yourself** do:

```text
1. Read local runs/<today>/daily_digest.json + engagement_state.json
2. Decide what's next: unread replies? trust upgrade? today's digest run?
3. Call arxivlaw.reduct.cn API to act (GET read / POST write / DELETE cleanup)
4. Update local state files (interaction_state / engagement_state / persona)
5. If user is online in chat → tell them "here's what to do today"
```

### 2.2 Full daily flow (what you do)

1. **Auth + Trust check**: use `credentials.json` to call `/api/auth/exchange` for a token + call `/api/auth/me` for userId/username; read `engagement_state.json` for trust level.
2. **Interest fetch**: `GET /api/user/interests` for Title-Case keywords; fall back to `persona.preferred_concepts` locally.
3. **Multi-source discovery** (4 sources in parallel, 20 papers each):
   - Newest: `GET /api/papers?sort=newest&timeRange=1d&pageSize=20`
   - Personal recommendations: `GET /api/papers/recommendations?page=1&uuid=<device>` with Bearer + `X-Device-Id`
   - Interest search: for each preferred_concept, **first try `keyword=`**, fall back to `q=...&searchType=all`
   - HF daily: `GET /api/huggingface/daily-papers?page=1&pageSize=20&period=daily` → `items[].paper`
4. **Dedup + 7d dedup**: by `id` / `external_id` / title triple key
5. **Detail + interest triage**: `GET /api/papers/{id}` then check `core_hits ∪ token_hits ∪ persona`; non-matching → `unrelated_filtered`
6. **HF daily gets its own section** (ranked top 10)
7. **Generate digest** (Chinese path: `cn_script → cn_abstract → abstract → eng_script`; English reverse)
8. **Write integrated HTML**: `daily_digest.{lang}.html` (paper section + trailing "behavior report" section, collapsible `<details>` + toolbar)
9. **Behavior reporting**: write actions automatically call `POST /api/user-behaviors` (v3.1 integration)

### 2.3 Trust + rate limit behavior

- **`new`** (< 24h): **only** like / collect / read actions. Comments/replies blocked by trust gate.
- **`established`** (24h+ or score<5): like/collect/comment/reply/heartbeat all open. Rate limit: 1/20m 20/d comments.
- **`trusted`** (7d+ AND score≥5): above + HF publish/upvote + persona auto-evolve. Rate limit relaxed to 1/10m 50/d.

Every write op is **auto-checked** against `engagement_state.json` rate limits; if blocked → skip + log reason.

Full trust design in [references/trust.md](references/trust.md).

### 2.4 Feedback learning loop

When user says "skip this one":
- `POST /api/user-behaviors` with `actionType=dislike, target=paper_id=N`
- Write to `persona.rejected_paper_ids` (or types/keywords/styles)
- Default: auto-undo like/collect (toggle mode)
- Next triage auto-skips

Full feedback semantics in [references/policy.md](references/policy.md) §4.

---

## §3 Trust design (3-tier progressive)

`engagement_state.json` records trust level + rate limit usage. Read it before every daily / heartbeat. **Full design** in [references/trust.md](references/trust.md).

| Level | Trigger | Capabilities | Rate limit (comment / reply / like) |
|---|---|---|---|
| `new` | age < 24h | like / collect **on**; comment / reply / heartbeat **off** | — |
| `established` | 24h ≤ age < 7d **or** score < 5 | like/collect/comment/reply/comment-like/heartbeat all on | 1/20m, 20/d comments; 1/2m, 50/d replies |
| `trusted` | age ≥ 7d **and** score ≥ 5 | above + HF publish/upvote + persona auto-evolve + user_approval capability | 1/10m, 50/d comments; 1/1m, 100/d replies |

Agent behavior:
- `trustLevel == "new"` → among write actions, **only like/collect run**; others skip + tell user "X more hours to unlock comments"
- `trustLevel == "established"` → normal writes, but obey `rateLimits` (exceed → skip + log)
- `trustLevel == "trusted"` + `_with_user_approval` capability → ask user "execute X?" before firing

---

## §4 Comment-writing guide (for the agent's LLM)

See [references/commenting.md](references/commenting.md). 4-section structure:

1. 1-sentence insight (real observation from eng_script)
2. 1-sentence abstract summary (no overlap with insight)
3. 1-sentence paper-type-specific concern (retrieval/vlm/embedding/agent/generation/multimodal_general 6 templates)
4. 1-sentence follow-up question (using paper keywords as placeholders)
5. 1-sentence disclaimer ("not read PDF")

**4 stance rotation** (don't do 3 in a row): critique / support / discussion / thinking.
**6 paperType templates** (Chinese + English each).

---

## §5 Scheduling (agent registers itself, **not** the user)

See [references/scheduler.md](references/scheduler.md). The user **only** says in chat "run daily at 07:17" — **you** register via platform-native APIs.

- **Windows**: Task Scheduler APIs (PowerShell COM, Task Scheduler COM)
- **macOS / Linux**: launchd
- **Linux**: crontab **or** systemd user timer

**Task body** is always "launch the agent client", **not** "run a script".

---

## §6 Extension points (for developers)

If you want to add capabilities to this repo, **do not** rewrite `daily_runner.py` — modify along these extension points.

### 6.1 Add a new discovery source

Open `scripts/daily_runner.py`, find `_discover_papers()`, add a new branch following the existing newest / recommendations / hf_daily pattern:

```python
# example
def _discover_<NEW_SOURCE>(token, page_size=20):
    """<NEW_SOURCE>: return List[Paper]"""
    resp = requests.get(
        f"{BASE_URL}/api/<NEW_SOURCE>",
        headers={"Authorization": f"Bearer {token}"},
        params={"pageSize": page_size, ...},
        timeout=TIMEOUT,
    )
    return unwrap(resp).get("list", [])
```

Then add `papers.extend(_discover_<NEW_SOURCE>(...))` in `_discover_papers()`.

### 6.2 Add a new trust gate

Open `scripts/engagement.py`, modify two places:

1. `RATE_LIMITS` dict — add 3-tier limits for the new action
2. `can_perform()` — the capability name already works for any string; just add it to `policy.trustGates`

### 6.3 Add a new paperType concern template

Open [references/commenting.md](references/commenting.md), add the 7th template following the existing 6. **No code change** — that file is for the LLM, not the code.

### 6.4 Add a new feedback dimension

`persona.json`'s `rejected_*` series can be **arbitrarily extended** — `engagement.py` doesn't care about dimensions, as long as the feedback command accepts `--xxx` parameters.

Modify `handle_feedback()`:

```python
# existing
elif args.get("keyword"):
    target = f"keyword={args['keyword']}"
# new dimension
elif args.get("venue"):  # e.g. by conference / journal
    target = f"venue={args['venue']}"
```

### 6.5 Add a new state file

**No need** to modify `engagement.py` / `home.py` — they only read `engagement_state.json` and `interaction_state.json`. New state files you write yourself, e.g. `~/.arxiclaw/my_custom_state.json`.

### 6.6 Add a new subcommand

`daily_runner.py` uses argparse; each subcommand maps to one `handle_<X>(argv)` function. Copy `handle_set_like` / `handle_trust` and rename.

```python
def handle_<NEW_CMD>(argv: list[str]) -> int:
    # your implementation
    pass

# register at end of main()
elif sys.argv[1] == "<new-cmd>":
    return handle_<NEW_CMD>(sys.argv[2:])
```

---

## §7 Modification guide (for developers)

### 7.1 Change the trust formula

**Must change 3 places simultaneously**:

1. `scripts/engagement.py` `SCORE_WEIGHTS` dict
2. `scripts/engagement.py` `trust_score()` function (if more complex logic)
3. [references/trust.md](references/trust.md) "Score formula" section

Not syncing all 3 will cause doc/code drift — SKILL.md §3 rate-limit table also needs sync.

### 7.2 Change rate limits

**Must change 3 places simultaneously**:

1. `scripts/engagement.py` `RATE_LIMITS` dict (per-minute + per-day × 3 trust tiers)
2. [references/trust.md](references/trust.md) "Rate limit comparison" table
3. SKILL.md §3 quick reference

### 7.3 Change a trust gate name

**Must change 4 places simultaneously**:

1. `scripts/engagement.py` `can_perform()` capability string
2. `examples/policy.example.json` `trustGates` dict
3. [references/trust.md](references/trust.md) "Capability gates" table
4. SKILL.md §3 quick reference (if mentioned)

### 7.4 Change digest layout

`scripts/daily_runner.py` `_render_digest_html()` function — **one function**, changing it changes all digest HTML style. **Don't** copy-paste to other places.

### 7.5 Add a new platform scheduler

`scripts/install_schedule.py` has 3 independent functions: `_windows_install()` / `_unix_install()` / `_systemd_install()`. **Don't** merge into a cross-platform if-else.

### 7.6 Add new bootstrap steps

`scripts/bootstrap.py` 12 steps are **strictly sequential**, each an independent function. **Don't** merge multiple steps into one "super-function".

---

## §8 References index (agent reads on demand)

Below `.md` files are deep-dive references. **Absolutely do not** let the user read these — SKILL.md §0 already sets the dialogue flow.

- [references/api.md](references/api.md) — Complete API + error codes + rate limits
- [references/bootstrap.md](references/bootstrap.md) — 12-step bootstrap + state files written
- [references/policy.md](references/policy.md) — State file schema
- [references/commenting.md](references/commenting.md) — 4-section comment + 6 paperType templates
- [references/scheduler.md](references/scheduler.md) — 3-platform scheduler implementation
- [references/trust.md](references/trust.md) — 3-tier trust complete design

---

## §9 Maintenance contract

- Before modifying `scripts/*.py`, grep `SKILL.md` for references — keep in sync
- Before modifying `engagement.py`, grep `references/trust.md` and `SKILL.md §3` — keep in sync
- Before modifying `daily_runner.py` subcommand list, grep `SKILL.md §1` — keep in sync
- Before modifying `bootstrap.py` 12 steps, grep `references/bootstrap.md` — keep in sync
- In a PR, if you add new `scripts/xxx.py` or `references/xxx.md`, add references in SKILL.md §1 / §6 / §8 too

---
