# Small private strength projection

The snapshot stage writes `data/currency-strength.json` in the private data
checkout in the same Git commit as `data/latest.json`, `data/cache.json` and
`data/source.json`. It copies the existing snapshot's `currency_strength`;
there is no extra collection, market request, strength calculation or job.

Readers that cannot download the large root snapshot can read this small file.
Freeze the private main tree first, then read source and projection from that
same commit. Require `schema=saved_currency_strength_v1`, `status=saved`, exact
`source` equality, and `snapshot_git_blob_sha` equal to the tree entry for
`data/latest.json`. Validate the original algorithm, clock, 24-hour window,
coverage, connected status, eight currencies, scores and ranking as before.
`fx_system.strength_export.validate_strength_export` provides this check.

The Git blob identity binds the copied payload to the exact snapshot bytes,
including formatting. It does not attest profitability or turn the projection
into an independent market source. The unchanged root payload remains the
original. A missing or malformed strength payload produces an explicit
unavailable projection for this run, never a previous run's ranking. A valid
but disconnected graph remains unavailable with no invented ranking.

The file is private only. Public stage output, workflow, access settings,
source history, assessment formulas and collection schedule are unchanged.
Synthetic tests exercise copying, source mismatch, unsupported payloads,
symlink rejection and one-commit publication to a local Git remote.

The optional `summary_version=1` / `summary_text` fields provide a short Japanese
24-hour overview for the report opening, after its conclusion. They render the
saved ranking and completed-window end in JST, preserve equal saved scores as
ties, and show coverage and provisional/unavailable states. The text distinguishes
this eight-currency overview from each daytrade candidate's six-hour context;
neither is a direction vote. No new price calculation or request is introduced.
The reader validates source/blob and strength first, and checks summary equality
when present. Old exports without both fields remain valid; readers can format
their verified saved ranking without implying that an absent summary was saved.

Scheduled reports select up to three swing and three daytrade candidates
independently, rather than sharing a three-candidate limit. Fewer candidates
are not filled with skips or with candidates from the other strategy.
