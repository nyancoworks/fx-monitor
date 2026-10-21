# Optional saved historical shape references

The existing scheduled producer adds `historical_shape_references` using its
saved H1 cache. No market calls, dependencies, triggers or schedules are added.
This promotes the shape core from private research 081265cf without changing
its definition: 20 OHLC bars offset from first close and scaled by own ATR14,
same 20-bar pivot structure, maximum three non-overlapping nearest examples.
Only after selection attach later 4/12-business-bar prices. Nominal NY
Sunday17–Friday17 hours and complete original UTC H1x4 buckets preserve
timestamps and missing expected bars. Bound input to 500 H1 rows per pair.

Canonical32 identities/time/authority are checked. Review scenarios get H4 or
H1 references independently; others are `not_candidate`. Missing/invalid/stale
or unverified-provider data stays unavailable for this run, with no fallback.
Output contains 32 records and at most three examples each. The 20-bar
structure can differ from the product's full-history structure. No acceptance
distance, probability, profitability or historical first-arrival reconstruction
is established. Past upper/momentum backgrounds are not assumed to match.
The nominal calendar is not a broker's trading-hours certificate.

This field never changes grades, selection, confirmation conditions, targets,
RR or trade operations. The Site draws normalized close curves (distance uses
all OHLC components), leaves the query future blank, and separates past later
prices from forecasts. Missing expected followup bars suppress that example's
later chart. Business-bar counts and elapsed hours remain distinct.

Snapshot saving copies the validated optional field unchanged into the existing
private `data/currency-strength.json`, using that bundle's exact source/root
Git blob binding. Strength and references are independent optional payloads.
This reuses the existing save commit/push and notification read, with no extra
GitHub request. Invalid references are omitted without invalidating strength.
Old snapshots stay readable and are not relabeled as providing references.

Consumers validate schema, clock, identities/directions, count bounds, finite
chart values and disjoint periods. Never combine different runs. Public tests
use synthetic inputs; actual-price comparisons and operational acceptance
belong in private Issue77/handoff. Local success and main reflection do not
prove a later natural run, Site user display or terminal notification arrival.
