# Optional economic calendar context

## Scope and activation

`financecalendar_adapter.normalize_calendar(payload, observed_at_utc=...)` is a pure offline adapter for a separately acquired Finance Calendar `/calendar` JSON page. Pass its return value explicitly as `economic_calendar` to `build_scheduled_outlook`. It neither fetches nor saves a provider response. Preserve the original response and its real acquisition clock in private storage; never commit it here. Do not substitute a provider build time or backdated evaluation time for acquisition.

No runtime, workflow, frequency, dependencies or default output are changed. Missing calendar input keeps the existing path. Calendar fields do not change any grade, direction, scenario condition, target, RR, expiry or authority. Source actual/consensus/prior strings are not parsed, scored or compared. Policy/rate interpretation and market reaction remain unassessed.

## Documentation contract checked 2026-10-23 JST

- https://www.financecalendar.com/api/
- https://www.financecalendar.com/api/economic-calendar/
- https://www.financecalendar.com/api/coverage/
- https://github.com/awarenessdays/financecalendar-api/blob/main/openapi.json — reviewed blob `4d2f06deedc7733596015133675aec80d61b9182`
- https://github.com/awarenessdays/financecalendar-api/blob/main/DATA-TERMS.md — reviewed blob `d29faa3f10eaf671bf5695bc993ab6570a7e34c4`

These are documentation/schema reviews, not tests against live responses. Current documentation says consensus is not collected. Do not promise forecasts or timely actuals from this provider.

## Projection and limitations

| Provider information | Reference input and handling |
| --- | --- |
| Country | US/GB/EU/DE/JP/CA/AU/CH/NZ map to USD/GBP/EUR/EUR/JPY/CAD/AUD/CHF/NZD. Unknown countries are omitted, not assigned to another currency. |
| Category | Economic indicators and central-bank decisions only; holidays and crypto are out of scope. |
| Stable ID | Duplicate IDs are all omitted rather than choosing between conflicting versions. |
| Exact timestamp | Offset-aware ISO instant retained in UTC seconds; naive/invalid/conflicting aliases become timing uncertainty. |
| Date, date range, timed range | Retained separately; never converted to a midnight or a range-start release instant. |
| Uncertain timing | Currency-relevant windows retained conservatively by publisher date with one boundary day on each side for unknown jurisdiction offset; dated ranges use overlap. Fully undated events remain explicit uncertainties in both strategies. This is inclusion for reference, not an invented occurrence time. |
| Estimated/rescheduled/cancelled | Provider status retained and labelled; no automatic scenario veto. |
| Acquisition | Caller clock must be positive integer; a snapshot later than evaluation is unavailable to that evaluation. |
| Source verification/update/manual review | Distinct clocks; future metadata rows are omitted. Verification age is reported without inventing a freshness threshold. |
| Staleness | Explicit `data_stale=true` is labelled stale. Otherwise freshness remains unverified, even with a source link, recent build, or recorded verification. Source health is not inferred or fetched. |
| Actual/prior/consensus | Original strings or null, no numeric coercion. Future, timing-uncertain, estimated/cancelled or explicitly stale actual observations are suppressed. Known future numerical vintages suppress the corresponding actual/prior string. Nested numerical history is not copied. |
| Credit and rights | Provider attribution, supported record licence/rights fields and numerical-observation credits are preserved in private saved context and shown for featured events. Original licence notices are retained without truncation. Unknown raw response fields are not copied. |
| Pagination | `page_complete` only means declared count/total match this page length. Missing counts/truncation are disclosed. It does not prove all market events are covered. |
| Coverage | Always `complete=false`, `coverage=unverified` for this adapter. Empty results never establish absence of events or safety. |

The existing event horizons are unchanged: swing from 24 hours before to seven days after evaluation; daytrade from six hours before to 36 hours after. They are reference windows, not scenario expiry.

Each of the 32 assessments stores context, including row copies used by historical storage. JSON, snapshot validation and compressed history round trips are tested with synthetic data. Report display is bounded to three events per featured scenario; remaining and uncertain events are explicitly referenced in the saved assessment. Non-featured scenarios still retain their context. The report is a saved-data view, not a current-market or delivery guarantee.

## Review and remaining production checks

Implemented/tested locally: adapter projection, uncertain dates/ranges, future-information suppression, staleness disclosure, provider/upstream credits, all 32 identities, unchanged core assessments, and storage/report integration. No live API response, current provider coverage or production natural run is established by these tests.

Before live integration, verify a saved real response privately against the documented schema, per-row source and licence metadata, pagination, acquisition clock, source-health and numerical-vintage evidence. Compare current API with the pinned documentation contract. Historical rows are not a point-in-time first-print archive. Missing currencies/series or consensus must remain disclosed; this provider alone has not been shown sufficient for complete FX fundamental analysis.

Proposed bounded live check for owner discussion: one `/status` GET and one explicitly dated `/calendar` GET (limit 500, eight FX currency areas plus Germany), no automatic retries, pagination follow-ups, keys, schedule changes or Actions dispatch. Stop after those two requests and inspect privately; if truncated, report partial coverage and discuss additional requests. No such requests are authorized or performed by this patch. Connecting routine acquisition remains a separate decision.
