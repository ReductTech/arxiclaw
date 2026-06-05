# Bootstrap — zero-secret bootstrap (for developers)

> **This file is for developers / extenders.** End users will not read this file — their agent loads SKILL.md §0.6 and automatically calls `bootstrap.py`.

## 1. Full 12-step flow

```
start
  │
  ├─ 1. Ask for email (do not print, do not echo into chat history)
  │
  ├─ 2. POST /api/auth/email/send-code {email, purpose:"api_bootstrap"}
  │     failure → retry 1x, on second failure exit
  │
  ├─ 3. Ask for 6-digit verification code (do not print)
  │
  ├─ 4. POST /api/auth/email/verify-code {email, code, purpose}
  │     failure (invalid/expired) → go back to step 2 and resend
  │     success → get emailLoginTicket
  │
  ├─ 5. Ask for username (optional) and keyName (default "daily-paper-reader")
  │
  ├─ 6. POST /api/auth/api-bootstrap {ticket, username?, keyName}
  │     success → get apiKey (one-time plain return) + accessToken + user
  │
  ├─ 7. Write credentials.json (chmod 0600)
  │     contents: {baseUrl, apiKey, userId, username, email,
  │                keyName, keyPrefix, createdAt}
  │
  ├─ 8. Ask for 1-3 research interests
  │     free input → GET /api/keywords/suggest?q=...&limit=10
  │     → let user pick final standard keywords
  │     → POST /api/user/interests {keywords}
  │     409 partial failure → read unmatched + suggestions, retry
  │
  ├─ 9. Ask comment language (zh-CN / en-US), write policy.language.{comment,digest,feedback,stored}
  │
  ├─ 10. Ask whether to enable auto like/collect/comment (default all on)
  │      write policy.allowAuto* + autoActionTiers + maxCommentsPerDailyRun
  │
  ├─ 11. Ask whether to register daily schedule
  │      Windows → install_schedule.py via schtasks
  │      Unix → write crontab / systemd timer
  │
  └─ 12. Ask whether to run dry-run now
        yes → subprocess call daily_runner.py dry-run
```

## 2. bootstrap.py design

- 12 steps, each an independent function (`step_send_code` / `step_verify_code` / `step_bootstrap` / `step_save_credentials` / `step_set_interests` / `step_save_policy` / `step_save_persona` / ...)
- **Don't** merge multiple steps into a super-function — easier to test, easier to extend
- The state machine only goes **sequentially**, no arbitrary re-entry

## 3. Failure retry

- Bad email format: input validation `^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$`
- Verification code 6 digits: `^[0-9]{6}$`
- Code wrong ≥ 3 times: re-send
- api-bootstrap ticket expired: auto re-verify-code

## 4. Re-bootstrap

- User says "reset account" / "change email": delete `credentials.json` + re-run 12 steps
- **Don't** keep the old apiKey (user may want to switch device / account)
- `bootstrap.py --reset` forces clear agent home

## 5. Security constraints (required reading)

- API key **does not** go into terminal logs (use getpass to hide)
- bootstrap output **only** shows `keyPrefix` (first 16 chars)
- `credentials.json` file permission 0600 (POSIX)
- If user asks to see the full key: must do secondary confirmation
  `print(f"Are you sure? Type 'reveal' to continue: ")`

## 6. Extension points (for developers)

- **Add new bootstrap step**: insert a new function between 12 steps, **don't** change other steps
- **Change default policy**: edit `policy.default.json` directly (bootstrap will copy it to home)
- **Support new platform scheduler**: see [scheduler.md](scheduler.md)

## 7. Standard pattern for adding a bootstrap step

```python
# scripts/bootstrap.py
def step_<NEW_STEP>(home: Path, ...) -> None:
    """Describe the new step."""
    # your implementation
    pass

# add one line in main()
def main():
    ...
    step_<NEW_STEP>(home, ...)
    ...
```

**Don't** change the 12 steps to an if/elif chain — keep each step an independent function, **it makes it easier to**:
- Unit test (mock single step)
- Skip single step (`--skip-step`)
- Re-run single step (`--redo-step`)
