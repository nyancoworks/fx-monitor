# FX Monitor code instructions

- This repository is public. Never commit market observations, saved assessments, captured responses, real-data fixtures, credentials, or private conversation records.
- Keep private state in the separately configured data checkout. Public workflow output is limited to fixed status metadata; inspect failure paths and artifacts as well as stdout.
- Preserve discretionary analysis for 16 pairs x swing/daytrade. No orders, permissions or position management. A/B/C is scenario assessment, not proven profitability.
- Current production profile: Super Bollinger, standard EMA MACD (12,26,9), standard Fibonacci, SMA50/200, RCI9/26/52 plus price structure. Use trigger RCI9 recovery for timing; candle lower-wick/strong bullish-body observation is optional in bullish pullbacks, never an independent PA gate or score. No Span Model, DMA, Preferred Stochastic, SMA100 or DiNapoli MACD in new judgments. Retain old interpreters only for exact historical restoration. No indicator votes or fixed collective AND rules.
- Do not enable collection, manually dispatch Actions, add market requests or increase schedules without owner authorization. Default collection remains disabled while migration is incomplete.
- Validate code locally first. Distinguish local tests, CI, data transfer verification and natural scheduled operation.
- Keep full historical originals and private research evidence in their original private source; never rewrite a frozen detection or source identity.

## Security checks for each development session

- Read SECURITY.md before changes. Pin the current remote main commit and compare it with the last trusted private handoff before executing repository code. Inspect intervening commits, actors and workflow changes. GitHub author names alone are not proof of identity.
- Stop and report unfamiliar changes, unexpected credential requests or changed publication/data destinations; do not run them, rewrite history or rotate/extract secrets to investigate.
- Before publishing, review the complete proposed public file set and diff for credentials, private observations, saved assessments, artifacts and log exposure. Use synthetic test credentials only and never print suspected secret values.
- Pin every external GitHub Action to a full 40-character commit SHA verified in its official upstream repository. Updating a pin requires reviewing the upstream change; do not silently return to tags or branches.
- Keep workflow permissions minimal. Do not run untrusted pull-request code with secrets or add pull_request_target, artifact uploads, automatic CI, schedules or market calls as part of a security check without the required owner authorization.
- Check dependency changes and available security advisories. Preserve honest limits when installed dependency versions, repository access settings, account security events or advisory results cannot be verified.
- Confirm main's active deletion/non-fast-forward rules before reflection. Never bypass those rules or use force pushes. Keep security findings, trusted commit IDs and verification limits in the private operational handoff.
