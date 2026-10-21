# Security practices

This public repository contains application code. Market observations, saved assessments, immutable originals, private research and operational records belong in private storage. Credentials belong in supported secret stores, never in source, tests, logs, artifacts or public issues.

## Before running or changing code

1. Read the current instructions and private operational handoff. Pin remote main and inspect commits since the last trusted head, including actor, parent chain, workflow and dependency changes. Treat an unfamiliar commit or destination as a reason to stop and investigate. A display name or an unsigned author field is not identity verification.
2. Check the effective main rules. Restrict deletions and block non-fast-forward pushes without bypass actors; ordinary fast-forward updates remain possible. These rules prevent destructive history changes, not every malicious new commit or account takeover.
3. Review any changed external Actions against their official upstream repository. Use full 40-character commit SHAs, keep a human-readable version comment, and review updates before replacing pins. Do not rely on mutable major-version tags.

## Before publishing

- Review the full public candidate file list and diff, including failed-run output and artifacts. Check common secret/key formats without printing matched values. Pattern scans are a limited check and cannot establish that no secret exists.
- Validate the workflow locally. Keep its collection trigger, schedule and API budget within the approved scope. Do not create extra Actions runs, pull-request CI or monitoring tasks merely to perform a security check.
- Keep credentials scoped to their intended repository and purpose. Do not repurpose the private data writer as a Site reader or publish secret values to diagnose access.
- Inspect dependency changes and security advisories for the exact resolved versions when available. A version range and a successful test run do not prove that all installed dependencies are vulnerability-free.
- Report what was inspected, what changed, what passed and what remains unverified in private operational records. Leave market data and secrets out of any public report.

## Scope and response

These are development-time checks, not continuous intrusion monitoring. Repository history and file inspection do not replace account security logs, collaborator/app/token review or incident response. If compromise is suspected, stop executing affected code, preserve evidence privately and involve the owner before changing credentials or access.

Do not include credentials or private records in public issue or pull-request discussions.
