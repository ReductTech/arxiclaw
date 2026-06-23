## Description

A clear and concise description of what this PR does.

## Related Issue

Fixes #(issue number) / Relates to #(issue number).

For larger changes, please open an issue first and link it here.

## Type of change

Please delete options that are not relevant.

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality
      to change)
- [ ] Documentation update
- [ ] Translation update
- [ ] Test addition / improvement

## How Has This Been Tested?

Please describe the tests you ran:

- [ ] `python -m ruff check .` — all pass
- [ ] `python -m compileall -q scripts` — all pass
- [ ] import smoke — scripts import cleanly
- [ ] `python scripts/doctor.py --json` — no unexpected failures
- [ ] `python scripts/daily_runner.py dry-run` — produces a digest
- [ ] Manual testing: describe the steps

## Checklist

- [ ] My code follows the style guidelines of this project (see
      [CONTRIBUTING.md](../CONTRIBUTING.md))
- [ ] I have added focused validation or documented why existing checks cover it
- [ ] I have updated the relevant documentation (README, CHANGELOG, docs/)
- [ ] CI-equivalent smoke checks pass locally
- [ ] I have added an entry to `CHANGELOG.md` under "Unreleased"
- [ ] My commits are signed (`git commit -s`)

## Security Considerations

- [ ] This PR does not log, print, or commit any secrets (apiKey, accessToken,
      verification code, ticket)
- [ ] This PR does not change the rate-limit defaults
- [ ] This PR does not change the trust level logic in a way that auto-demotes
      users

## Screenshots / Output (if applicable)

Add screenshots or terminal output to help explain your changes.
