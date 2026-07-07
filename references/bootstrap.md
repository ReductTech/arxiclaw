# Bootstrap — zero-secret bootstrap (for developers)

> **This file is for developers / extenders.** End users normally follow `SKILL.md` §0. `bootstrap.py` is the CLI implementation of the same account-connection and local-home setup flow.

## 1. Current interactive flow

```
start
  │
  ├─ 1. Choose account connection method
  │     A. email code bootstrap
  │     B. import website API key from file/env/stdin/pasted key
  │
  ├─ 2A. Email path: ask for email, send code, verify 6-digit code
  │     POST /api/auth/email/send-code {email, purpose:"api_bootstrap"}
  │     POST /api/auth/email/verify-code {email, code, purpose:"api_bootstrap"}
  │     success → get emailLoginTicket
  │
  ├─ 2B. API key path: read only the user-provided key location
  │     POST /api/auth/token {grantType:"api_key", apiKey}
  │     GET /api/auth/me
  │
  ├─ 3. Ask for username (optional, email path only) and keyName
  │     default keyName: "heartbeat-agent"
  │
  ├─ 4. Email path only: POST /api/auth/api-bootstrap {ticket, username?, keyName}
  │     success → get apiKey (one-time plain return) + accessToken + user
  │
  ├─ 5. Ask for agent home, then write credentials.json (chmod 0600)
  │     contents: {baseUrl, apiKey, userId, username, email,
  │                keyName, apiKeyPrefix, keyPrefix, createdAt}
  │
  ├─ 6. Initialize persona.json, engagement_state.json, interaction_state.json
  │
  ├─ 7. Ask for 1-3 research interests
  │     free input → GET /api/keywords/suggest?q=...&limit=10
  │     → let user pick final standard keywords
  │     → POST /api/user/interests {keywords}
  │     409 partial failure → read unmatched + suggestions, retry
  │
  ├─ 8. Ask daily digest paper limit, write policy.digestPaperLimit
  │
  ├─ 9. Ask heartbeat schedule mode (A/B/C/D), write policy.schedule.mode
  │
  ├─ 10. Ask comment / digest language (zh-CN / en-US)
  │      write policy.language.{comment,digest,feedback,stored}
  │
  ├─ 11. Ask whether to enable auto like/collect/comment/reply/comment-like
  │      write policy.allowAuto* + autoActionTiers + maxCommentsPerDailyRun
  │
  ├─ 12. Offer dry-run verification
  │      yes → subprocess call daily_runner.py dry-run
  │
  └─ 13. Offer scheduled task registration
        Windows → install_schedule.py via schtasks
        Unix → write crontab / systemd timer
```

## 2. bootstrap.py design

- Keep each externally meaningful step in a small function (`step_send_code` / `step_verify_code` / `step_bootstrap` / `step_save_credentials` / `step_set_interests` / `step_init_policy` / `step_init_persona` / ...)
- **Don't** merge multiple steps into a super-function — easier to test, easier to extend
- The state machine only goes **sequentially**, no arbitrary re-entry

## 3. Failure retry

- Bad email format: input validation `^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$`
- Verification code 6 digits: `^[0-9]{6}$`
- Code wrong ≥ 3 times: re-send
- api-bootstrap ticket expired: auto re-verify-code

## 4. Re-bootstrap

- User says "reset account" / "change email": delete `credentials.json` + re-run the onboarding flow
- **Don't** keep the old apiKey (user may want to switch device / account)
- `bootstrap.py --reset` forces clear agent home

## 5. Security constraints (required reading)

- API key **does not** go into terminal logs (use getpass to hide)
- bootstrap output **only** shows `apiKeyPrefix` / legacy `keyPrefix`
- `credentials.json` file permission 0600 (POSIX)
- If user asks to see the full key: must do secondary confirmation
  `print(f"Are you sure? Type 'reveal' to continue: ")`

## 6. Extension points (for developers)

- **Add new bootstrap step**: insert a new function at the right point in the ordered flow, **don't** fold unrelated steps together
- **Change default policy fallback**: edit `scripts/policy.default.json`
- **Change bootstrap-created policy**: edit `step_init_policy()` in `scripts/bootstrap.py`
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

**Don't** change the ordered flow to one large if/elif chain — keep each step an independent function, **it makes it easier to**:
- Unit test (mock single step)
- Skip single step (`--skip-step`)
- Re-run single step (`--redo-step`)
