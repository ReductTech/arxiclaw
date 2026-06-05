# Scheduler — 3-platform scheduling (for developers)

> **This file is for developers.**
> The user **only** says in chat "run daily at 07:17" — **the agent** uses platform-native APIs to register (the user doesn't touch the command line).

## Default time selection

- **07:17** avoids the peak load spikes
- Timezone: user's machine local time
- Frequency: once per day

## 3-platform implementation

The agent registers via platform-native methods on user authorization:

### Windows Task Scheduler

The agent uses PowerShell COM or schtasks. Task body is "launch the agent client".

See the `_windows_install()` function in `scripts/install_schedule.py`.

### Unix cron / systemd timer

The agent uses shell to call `crontab` or write `~/.config/systemd/user/*.service` + `*.timer`.

See the `_unix_install()` function in `scripts/install_schedule.py`.

## How the daily run is triggered

When the agent registers a schedule, **the task body is "launch the agent client"**. Once the agent client is launched, **it** does the "daily run" itself.

**Don't** use "the schedule runs a Python script" — that violates the "agent is its own LLM" design.

## User unschedule

The user says "cancel the schedule" — the agent uses platform-native methods to remove. **Don't** let the user edit files manually.

See `scripts/uninstall.py`.

## Scheduling ≠ real-time

- **Scheduling**: covers "digest not missed when user is offline"
- **Heartbeat**: covers "real-time comment, reply, heartbeat"

The agent must tell the user 2 things in SKILL.md §0.2.1:

1. Scheduling is a fallback, **cannot** replace agent online
2. If the computer is often off, **enable both** (scheduling + agent occasionally online) for full coverage

## Cross-platform automation

The agent will, during bootstrap:

1. Detect user platform (Windows / macOS / Linux / WSL / Docker)
2. Choose the corresponding registration method
3. **Don't** ask the user "do you want cron or systemd" — the agent decides
4. Fall back on failure

## Extension points (for developers)

Add a new platform (e.g. FreeBSD):

1. Add new function `_freebsd_install()` in `scripts/install_schedule.py`
2. Add `'freebsd': '_freebsd_install'` in `_detect_platform()` at the end
3. Mirror add `_freebsd_uninstall()` in `scripts/uninstall.py`
4. Sync SKILL.md §5

**Don't** modify `_windows_install()` / `_unix_install()` / `_systemd_install()` — keep the 3 functions independent.
