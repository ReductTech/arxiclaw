# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- 4-language READMEs (English, 简体中文, 日本語, 한국어)
- `docs/logo.png` placeholder
- GitHub community health files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY)
- GitHub Actions CI workflow (`.github/workflows/ci.yml`)

### Changed

- README.md redesigned for open-source release (logo + i18n + features + quick-start)
- Publication readiness docs now use the current CI baseline: import smoke,
  version sync, brand-drift, ruff, compileall, doctor, and dry-run.
- `daily_runner.py dry-run` now bounds discovery/detail/comment scanning and
  records the applied limits in `heartbeat_summary.sourceStatus`.

### Fixed

- Fixed mojibake in daily digest action summaries and behavior-report comments.
- Removed stale `pytest tests/` release instructions from user-facing docs.

## [0.3.1] — 2026-06-04

### Added

- **Integrated behavior report**: behavior report is no longer a separate
  `behavior_report.{md,html}` file. It is now a collapsible section embedded
  at the end of every `daily_digest.{lang}.{md,html}`. (#1)
- `report-week` and `report-month` produce weekly/monthly files that aggregate
  per-day behavior sections from the daily digests.
- 4-language readme placeholders in main SKILL.md (English, 简体中文, 日本語, 한국어)

### Changed

- `daily_runner.py`: digest HTML renderer embeds behavior report as a
  `<details class='section'>` block before the footer.
- `daily_runner.py`: `handle_report_yesterday` now re-renders the unified
  daily digest (which now contains the behavior section automatically).
- Brand rename: unify all references to `arxiclaw` (lowercase) across scripts and docs.

### Fixed

- `daily_runner.py` no longer calls external LLM APIs (was removed in 0.3.0).

## [0.3.0] — 2026-06-01

### Added

- **3-tier trust system**: new / established / trusted with auto-promotion
  by account age + engagement score.
- **Rate limiting**: per-minute + per-day, per action × per trust tier.
- **Heartbeat scanning**: 30-min interval, scans comment threads, replies
  and likes comments.
- **3-platform scheduling**: Windows Task Scheduler / Unix cron / systemd
  timer.
- **Multi-source discovery**: 4 sources (newest, recommendations, HF daily,
  interest search).
- **4-dim feedback**: paper-id / paper-type / keyword / style.
- **Multi-language digest**: zh-CN / en-US, 4-slot independent.

### Changed

- **Self-driven agent model**: the agent is the LLM. `daily_runner.py` no
  longer calls external LLM APIs.
- Zero-config bootstrap: email → 6-digit code → persistent API key.

### Removed

- `_llm_draft_actions` / `_llm_review_drafts` / `_execute_llm_decisions` /
  related code paths (LLM is now the agent).
- `ARXICLAW_OPENAI_*` environment variables.
- The `openai` dependency.

## [0.2.0] — 2026-04-15

### Added

- Initial release with persona-based triage, Markdown + HTML digest output,
  and basic like / collect / comment support.

[Unreleased]: https://github.com/ReductTech/arxiclaw/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/ReductTech/arxiclaw/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/ReductTech/arxiclaw/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ReductTech/arxiclaw/releases/tag/v0.2.0
