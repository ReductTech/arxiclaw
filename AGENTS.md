# AGENTS.md — for AI agents

> **This file is for AI agents that want to USE, MODIFY, or CONTRIBUTE to the
> arxiclaw codebase.** Humans should read [README.md](README.md) and
> [CONTRIBUTING.md](CONTRIBUTING.md) instead.
>
> **The full agent contract** is in [SKILL.md](SKILL.md) — multi-turn bootstrap
> protocol, all 30+ subcommands, extension points, modification guide.
> This file is the **30-second quickstart** + **project map**.

---

## 1. 30-second quickstart

```bash
# Clone the repo
git clone https://github.com/ReductTech/arxiclaw.git
cd arxiclaw

# Install dependencies + bootstrap a fresh user (if needed)
pip install -r requirements.txt
make install          # or: python scripts/install.py

# Diagnose environment
make doctor           # or: python scripts/doctor.py

# Run today's digest
make daily            # or: python scripts/daily_runner.py

# Dev loop (run after every code change)
make dev              # = pytest + ruff
```

**If you are helping an existing user** (someone with `~/.arxiclaw/credentials.json`):

```bash
# Just diagnose, then act
make doctor --json    # read the JSON, decide what to do
# then: make daily / make heartbeat / make upgrade, etc.
```

**If you want to contribute** (modify the codebase):

```bash
# 1. Make your change
$EDITOR scripts/some_file.py

# 2. Validate
make dev              # pytest + ruff

# 3. Sync docs (if you changed trust/rate-limit/scheduling/commenting/api)
#    → see [SKILL.md §9 Maintenance](SKILL.md)

# 4. Commit + push
git add -A
git commit -m "..."
git push origin main
```

---

## 2. Project map

```
arxiclaw/
├── SKILL.md              ← agent contract (read this)
├── AGENTS.md             ← you are here
├── README.md             ← project facade (humans)
├── CONTRIBUTING.md       ← contribution guide (humans)
├── CHANGELOG.md          ← release notes
├── Makefile               ← one-stop command list (install / doctor / dev / release)
│
├── scripts/              ← actual code
│   ├── daily_runner.py    ← main entrypoint: 30+ subcommands
│   ├── bootstrap.py       ← zero-secret bootstrap (12 steps)
│   ├── engagement.py      ← trust + rate limit state machine
│   ├── home.py            ← /home entrypoint
│   ├── behavior_report.py ← integrated report helpers
│   ├── install_schedule.py← 3-platform scheduler
│   ├── uninstall.py
│   ├── onboard.py         ← fix broken environments
│   ├── install.py         ← ★ one-stop install for new users
│   ├── upgrade.py         ← ★ transactional upgrade (git pull + doctor + migrate)
│   ├── doctor.py          ← ★ environment health check
│   ├── migrate.py         ← ★ state-file schema migration
│   ├── run_daily.bat      ← Windows wrapper
│   ├── policy.default.json
│   └── persona.default.json
│
├── references/           ← deep-dive docs (agent reads on demand)
│   ├── api.md             ← arxivlaw API + error codes + rate limits
│   ├── bootstrap.md       ← 12-step flow + extension points
│   ├── policy.md          ← state-file schemas
│   ├── commenting.md      ← 4-section structure + 6 paperType templates
│   ├── scheduler.md       ← 3-platform scheduling implementation
│   └── trust.md           ← 3-tier trust design + extension points
│
├── tests/                ← pytest
│   ├── test_engagement.py
│   ├── test_home.py
│   ├── test_doctor.py     ← doctor
│   ├── test_install.py    ← install
│   └── test_migrate.py    ← migrate
│
├── examples/             ← templates copied on first bootstrap
│   ├── credentials.example.json
│   ├── policy.example.json
│   └── persona.example.json
│
├── .github/              ← community health + CI
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│       ├── ci.yml         ← pytest + ruff + brand-drift check
│       └── release.yml    ← ★ auto-release on tag push (optional)
│
└── docs/                 ← multi-language READMEs + logo
    ├── README.en-US.md
    ├── README.zh-CN.md
    ├── README.ja-JP.md
    ├── README.ko-KR.md
    └── logo.png
```

---

## 3. Decision flow for agents

```
USER SAYS SOMETHING
       │
       ▼
[Has user been bootstrapped?]
   │  check ~/.arxiclaw/credentials.json
   │
   ├─ NO  → load SKILL.md §0  →  multi-turn bootstrap
   │
   └─ YES → load SKILL.md §0.7 → 13 user-phrase → action mapping
            │
            ▼
       [Is this a code modification?]
            │
            ├─ NO  → use existing scripts/daily_runner.py subcommands
            │
            └─ YES → see §4 below
```

---

## 4. Modifying the codebase

### 4.1 Where to make changes

| You want to add... | Edit | Also update |
|---|---|---|
| New subcommand | `scripts/daily_runner.py` (copy `handle_set_like`) | SKILL.md §1 |
| New discovery source | `scripts/daily_runner.py` `_discover_<NEW>()` | (no doc change) |
| New trust tier | `scripts/engagement.py` (TRUST_ORDER / RATE_LIMITS) | references/trust.md + SKILL.md §3 |
| New rate limit | `scripts/engagement.py` (RATE_LIMITS) | references/trust.md + SKILL.md §3 |
| New trust gate | `examples/policy.example.json` (trustGates) | SKILL.md §3 |
| New paperType comment template | `references/commenting.md` (§3) | (no code change) |
| New feedback dimension | `scripts/daily_runner.py` (handle_feedback) | (no doc change) |
| New scheduled platform | `scripts/install_schedule.py` | references/scheduler.md + SKILL.md §5 |
| New diagnostic check | `scripts/doctor.py` (add `check_<X>()`) | (no doc change) |
| New state-file schema | `scripts/migrate.py` (add `v0_X_to_v0_Y()`) | CHANGELOG.md |

### 4.2 Validation loop

After any change:

```bash
make dev              # pytest + ruff
make doctor           # ensure the change doesn't break environment
```

If you changed trust / rate limit / gate:
```bash
# Also sync the 3 documentation places
grep -rn "<your change>" references/ SKILL.md
```

### 4.3 Versioning

This project follows **Semantic Versioning**:
- `MAJOR` (x.0.0) — breaking change (schema, API, or removed feature)
- `MINOR` (0.x.0) — new feature (new subcommand, new trust tier)
- `PATCH` (0.0.x) — bug fix, doc improvement

When releasing:
1. Bump `__version__` in `scripts/daily_runner.py` (TODO: add this constant)
2. Add entry to `CHANGELOG.md` under new version
3. Tag + push: `git tag v0.x.y && git push origin v0.x.y`

---

## 5. Common tasks for agents

### 5.1 Help a user diagnose why today is slow

```bash
make doctor --json | jq '.checks[] | select(.status=="fail" or .status=="warn")'
```

Read the JSON, identify the failing check, and act:

| Failing check | Action |
|---|---|
| `python_version` | Tell user to upgrade Python |
| `dependencies` | `pip install -r requirements.txt` |
| `agent_home` | `python scripts/bootstrap.py` |
| `credentials` | `python scripts/bootstrap.py --reset` |
| `state_files` | Recover from backup, or `python scripts/bootstrap.py` |
| `trust` | `python scripts/daily_runner.py trust show` |
| `schedule` | `python scripts/install_schedule.py` |
| `network` | Check proxy / firewall |
| `recent_run` | `make daily` |

### 5.2 Help a user upgrade to a new version

```bash
make upgrade          # git pull + doctor + migrate (transactional)
```

If upgrade fails: it **rolls back** to the previous commit. Tell the user
"the upgrade was safely rolled back, here's the doctor report".

### 5.3 Help a user customize the agent

1. Read `~/.arxiclaw/policy.json`
2. Explain the available toggles
3. Update the field the user wants
4. Re-run `make doctor` to confirm

Examples of customization:
- "stop auto-commenting" → `policy.allowAutoComment = false`
- "comment in English" → `policy.language.comment = "en-US"`
- "be more conservative" → `python scripts/daily_runner.py trust set established`

### 5.4 Help a user debug a specific paper

```bash
# Read-only investigation
python scripts/daily_runner.py paper-detail --id <N> --lang zh
python scripts/daily_runner.py paper-comments --id <N>

# Why was this paper skipped?
grep -A 5 '"id": <N>' ~/.arxiclaw/runs/<date>/daily_digest.json

# Re-include this paper
python scripts/daily_runner.py feedback --paper-id <N> --action accept
```

---

## 6. Coding conventions for this project

- **Python 3.10+** — use `str | None` (PEP 604) instead of `Optional[str]`
- **No external LLM calls** in `scripts/*.py` — the agent is the LLM
- **No API keys in logs** — never print `apiKey`, `accessToken`, or verification codes
- **State-machine purity** — `engagement.py` and `home.py` must NOT call platform APIs (test in isolation)
- **One subcommand per function** — don't merge multiple subcommands into one big function
- **Structured output** — every script that an agent calls should support `--json`

When in doubt, read existing code (`scripts/daily_runner.py` is the canonical
example) and follow its style.

---

## 7. Anti-patterns (do NOT do these)

❌ Don't paste API keys in chat — `bootstrap.py` writes them to disk
❌ Don't call `set-like --desired true` without first GETting current state (toggle mode)
❌ Don't auto-reply to a paper's author (wait for user approval)
❌ Don't write a comment longer than 300 chars
❌ Don't bypass trust gates — even for "obvious" cases
❌ Don't modify `engagement.py` rate limits without also updating `references/trust.md` and SKILL.md §3
❌ Don't commit `runs/`, `credentials.json`, `persona.json` — they're in `.gitignore`
❌ Don't push to `main` without `make dev` passing

---

## 8. Quick reference — when to read what

| Situation | Read this |
|---|---|
| User says "bootstrap me" | SKILL.md §0 |
| User says "run today" | SKILL.md §0.7 (just call `make daily`) |
| User wants to change policy | SKILL.md §2.4 + `policy.example.json` |
| User wants to change language | SKILL.md §0.7 + policy.language.* |
| User asks about trust | references/trust.md + `python scripts/daily_runner.py trust show` |
| You want to add a feature | This file (AGENTS.md) §4 |
| Something is broken | `make doctor` |
| User wants to upgrade | `make upgrade` (or this file §5.2) |
| You want to know what subcommands exist | SKILL.md §1 |
| API call fails | references/api.md §6 (error codes) |
