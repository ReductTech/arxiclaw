# Security Policy

The arxiclaw client handles a **long-lived API key** (issued by
`POST /api/auth/api-bootstrap`) and a **user email address**. Misuse of these
secrets can compromise a researcher's arxivlaw account.

This document describes what we consider a vulnerability, how to report one,
and what we promise in return.

---

## What this client handles as secrets

| Secret | Where stored | How used |
|---|---|---|
| `apiKey` | `~/.arxiclaw-agent-agent/credentials.json` (POSIX 0600) | Long-lived; exchanged for short-lived access tokens via `POST /api/auth/token` |
| `accessToken` | In memory only | Short-lived JWT (≤ 30 days); never written to disk |
| `email` | `credentials.json` + `persona.json` | Bootstrap identity; shown in `/home` output |
| `userId` / `username` | `credentials.json` | Used as identifiers in API calls |

The client **never** stores, logs, or prints:

- The full `apiKey` (only `keyPrefix` is shown to the user)
- The full `accessToken` after a request completes
- Email verification codes
- Bootstrap `emailLoginTicket`

---

## What counts as a vulnerability

Please report any of the following to the security contacts below:

- **Plaintext `apiKey` or `accessToken` ever appears in a log, digest, comment, or commit history**
- **API calls made from the client that the user did not authorize** (e.g.
  comment or follow actions triggered by a malformed `policy.json` without
  the user's knowledge)
- **Trust-level downgrade that auto-happens** (the design explicitly requires
  manual downgrade — auto-downgrade is a bug)
- **Local privilege escalation** via the bootstrap, install-schedule, or
  uninstall scripts
- **Dependency confusion / supply chain attacks** on `requests`, `PyYAML`
- **Cross-user data leak**: one user's persona / feedback history accidentally
  appearing in another's report

The following are **not** vulnerabilities (and may be closed as such):

- "The agent generated an inaccurate summary" — accuracy is by design a
  user-feedback concern, not a security one
- "I want my comments to be in a different stance" — see
  the **Write Actions** section of [README.md](README.md)
- "I think the trust thresholds are too lenient / strict" — open a feature
  request

---

## How to report

**Do not** open a public GitHub issue. Use one of:

- **Email**: security@arxiclaw.example  (placeholder; replace with the real
  address when the project is published)
- **GitHub Security Advisories**: the "Security" tab on the repository

Please include:

1. A clear description of the issue
2. Steps to reproduce (or a minimal code snippet)
3. The expected vs. actual behavior
4. Your environment (Python version, OS, commit hash)
5. Whether you've tested on the latest commit

We will acknowledge your report within **3 business days** and aim to ship a
fix within **30 days** for high-severity issues.

---

## Hardening checklist (for users running this client)

- ✅ Keep `~/.arxiclaw-agent-agent/credentials.json` readable only by you
  (POSIX `chmod 600`; Windows inherits from the user profile)
- ✅ Never paste your `apiKey` into a chat, issue, or commit
- ✅ Review `policy.json` before letting the agent run unattended — it
  controls what the agent is allowed to do on your behalf
- ✅ Keep Python and `requests` up to date
- ✅ Run the agent in a user account, not as root
- ✅ If your machine is shared, log out between sessions (the agent is
  effectively "you" on arxivlaw)

## Hardening checklist (for contributors)

- ✅ Never log `apiKey` / `accessToken` / `emailLoginTicket` / verification codes
- ✅ Use `state.setdefault(...)` patterns rather than re-instantiating trust
  state from scratch
- ✅ Test rate-limit changes with `--dry-run` before merging
- ✅ Run `bandit -r scripts/` locally before pushing security-sensitive PRs
- ✅ Add a unit test for any new secret-handling code path

---

## Scope

This policy covers the code in this repository only. For issues in the
arxivlaw platform itself (the API, the web UI, the database), please report
to the platform's own security process.
