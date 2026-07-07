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

The agent uses PowerShell COM or `schtasks`. The current implementation writes
a small wrapper (`run_daily.bat`) and registers a Task Scheduler entry that runs
the daily runner.

See the `_windows_install()` function in `scripts/install_schedule.py`.

Default Windows install:

- current-user scheduled task
- no administrator privilege required
- runs when the machine is on and the user session is available
- does not guarantee execution while the machine is shut down, asleep, or
  before login

Optional stronger modes should be explicit and opt-in:

- logon fallback: run once when the user logs in after missing the scheduled
  time
- highest privileges: may require UAC/admin approval
- wake to run: depends on Task Scheduler and power settings
- run whether user is logged on or not: requires credential/system-level
  configuration

### Unix cron / systemd timer

The agent uses shell to call `crontab` or write `~/.config/systemd/user/*.service` + `*.timer`.

See the `_unix_install()` function in `scripts/install_schedule.py`.

## How the daily run is triggered

When the agent registers a schedule, the task body must launch the local
arxiclaw client path for that installation. In this repository, that is
`run_daily.bat`/`daily_runner.py`; agent-native clients may instead launch
their own client process and then call the same runner commands.

## User unschedule

The user says "cancel the schedule" — the agent uses platform-native methods to remove. **Don't** let the user edit files manually.

See `scripts/uninstall.py`.

## Scheduling ≠ real-time

- **Scheduling**: covers "digest generated automatically when the machine can
  run it"
- **Heartbeat**: covers "real-time comment, reply, heartbeat"

The agent must tell the user 2 things in SKILL.md §0.2.1:

1. Scheduling is a fallback, **cannot** replace agent online
2. If the computer is often off, explain the platform limit and recommend
   logon fallback, wake settings, or an always-on host plus occasional agent
   sessions for full coverage

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
