---
name: Bug Report
about: Report a problem with the arxiclaw client
title: "[Bug] "
labels: bug
assignees: ""
---

## Describe the bug

A clear and concise description of what the bug is.

## To Reproduce

Steps to reproduce the behavior:

1. e.g. "Run `python scripts/daily_runner.py home`"
2. e.g. "With a credentials.json that has userId=19"
3. e.g. "See error: ..."

## Expected behavior

A clear and concise description of what you expected to happen.

## Actual behavior

What actually happened. Please include:

- Full command output (or last 30 lines if very long)
- Exit code
- Any log lines from `~/.arxiclaw/runs/runner.log`

## Environment

- OS: [e.g. Windows 11 / macOS 14 / Ubuntu 22.04]
- Python version: [e.g. 3.11.4]
- Client version: [run `git rev-parse HEAD`]
- Trust level: [run `python scripts/daily_runner.py trust show`]

## Additional context

Anything else that might help — relevant config from `policy.json` /
`persona.json` (with secrets redacted), the platform `keyPrefix` of the
affected account, etc.

**Important**: **Do not paste your `apiKey`, `accessToken`, or any
verification code** in this issue. These are secrets — see
[SECURITY.md](../SECURITY.md) for how to handle suspected leaks.
