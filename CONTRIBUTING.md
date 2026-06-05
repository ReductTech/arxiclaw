# Contributing to arxiclaw

Thank you for your interest in contributing! 🎉

This document is short on purpose. Most of what you need is captured in our
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), the per-file docs in
[`docs/`](docs/), and the inline comments in
[`scripts/`](scripts/). Read those first, then come back here for the
mechanics.

---

## What we welcome

- 🐛 **Bug reports** — see [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md)
- 💡 **Feature requests** — see [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md)
- 🌍 **Documentation translations** — see [`docs/`](docs/) for the language set we already have
- 🧪 **Tests** — `pytest tests/` is the entry point; coverage in
  `scripts/daily_runner.py` and `scripts/engagement.py` is welcome
- 🔧 **Small bug fixes** — open an issue first, then a PR

## What needs more discussion

- **Major refactors of the digest pipeline** — open an issue, get a maintainer's
  green light, then propose a PR
- **New trust levels / rate-limit changes** — security-sensitive; will need
  design discussion
- **Anything that touches API key handling** — please read [SECURITY.md](SECURITY.md) first

---

## Development setup

```bash
git clone https://github.com/ReductTech/arxiclaw.git
cd arxiclaw
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest
```

## Local dry-run

To exercise the full pipeline without hitting the platform:

```bash
python scripts/bootstrap.py --dry-run-bootstrap   # 0-network, no email, no API key
python scripts/daily_runner.py dry-run            # reads / writes local artifacts only
python scripts/daily_runner.py home --no-network  # reads engagement_state only
```

## Tests

```bash
pytest tests/ -v
```

Please ensure all tests pass before opening a PR.

---

## Pull Request process

1. **Open an issue first** for non-trivial changes; reference it in the PR.
2. **One concern per PR** — don't mix a typo fix with a refactor.
3. **Pass the CI** — the GitHub Actions workflow in
   [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `pytest` and a
   basic import check on every push.
4. **Sign your commits** (`git commit -s`). The DCO bot will tell you if you
   forget.
5. **Update CHANGELOG.md** under "Unreleased" — one line per change.
6. **Wait for review.** We aim to respond within 7 days.

PR template: [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)

---

## Code style

- **Python**: PEP 8 with line length 100. Use `from __future__ import annotations`
  in every module. Prefer `pathlib.Path` over `os.path`.
- **Comments**: explain *why*, not *what*. The code should be self-explanatory.
- **i18n strings**: when adding user-facing strings, follow the existing
  `I18N_ZH` / `I18N_EN` dicts in `scripts/daily_runner.py`. Do not hardcode
  English or Chinese in code paths.
- **No LLM API keys** in this repo. The agent is the LLM. Never commit
  `ARXICLAW_OPENAI_*` or similar.

---

## Reporting vulnerabilities

**Do not** open a public issue. Follow the process in
[SECURITY.md](SECURITY.md).
