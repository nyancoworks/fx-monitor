# Optional economic calendar context

## Scope and activation

`financecalendar_adapter.normalize_calendar(payload, observed_at_utc=...)` is a pure offline adapter for a separately acquired Finance Calendar `/calendar` JSON page. Pass its return value explicitly as `economic_calendar` to `build_scheduled_outlook`. It neither fetches nor saves a provider response. Preserve the original response and its real acquisition clock in private storage; never commit it here. Do not substitute a provider build time or backdated evaluation time for acquisition.

The scheduled builder now has an explicitly disabled-by-default private-file reader. No workflow, frequency, dependencies or default output are changed. Missing calendar input keeps the existing path. Calendar fields do not change any grade, direction, scenario condition, target, RR, expiry or authority. Source actual/consensus/prior strings are not parsed, scored or compared. Policy/rate interpretation and market reaction remain unassessed.

## Documentation contract checked 2026-10-23 JST

- https://www.financecalendar.com/api/
- https://www.financecalendar.com/api/economic-calendar/
- https://www.financecalendar.com/api/coverage/
- https://github.com/awarenessdays/financecalendar-api/blob/main/openapi.json — reviewed blob `4d2f06deedc7733596015133675aec80d61b9182`
- https://github.com/awarenessdays/financecalendar-api/blob/main/DATA-TERMS.md — reviewed blob `d29faa3f10eaf671bf5695bc993ab6570a7e34c4`

These references were first reviewed as documentation/schema, then one owner-approved two-request live sample was checked privately on 2026-10-23 JST. That bounded sample is not ongoing provider or production acceptance. Current documentation says consensus is not collected. Do not promise forecasts or timely actuals from this provider.

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
| Staleness | Explicit `data_stale=true` is labelled stale. Otherwise freshness remains unverified, even with a source link, recent build, or recorded verification. Optional saved `/status` evidence is joined by exact source ID; status acquisition must be no later than calendar acquisition. Missing, future, duplicate or unreported evidence stays unverified. No health fetch is performed. |
| Actual/prior/consensus | Original strings or null, no numeric coercion. Future, timing-uncertain, estimated/cancelled or explicitly stale actual observations are suppressed. Known future numerical vintages suppress the corresponding actual/prior string. Nested numerical history is not copied. |
| Credit and rights | Provider attribution, supported record licence/rights fields and numerical-observation credits are preserved in private saved context and shown for featured events. Original licence notices are retained without truncation. Unknown raw response fields are not copied. |
| Pagination | `page_complete` only means declared count/total match this page length. Missing counts/truncation are disclosed. It does not prove all market events are covered. |
| Coverage | Always `complete=false`, `coverage=unverified` for this adapter. Empty results never establish absence of events or safety. |

The existing event horizons are unchanged: swing from 24 hours before to seven days after evaluation; daytrade from six hours before to 36 hours after. They are reference windows, not scenario expiry.

Each of the 32 assessments stores context, including row copies used by historical storage. JSON, snapshot validation and compressed history round trips are tested with synthetic data. Report display is bounded to three events per featured scenario; remaining and uncertain events are explicitly referenced in the saved assessment. Non-featured scenarios still retain their context. The report is a saved-data view, not a current-market or delivery guarantee.

## Review and remaining production checks

Implemented/tested locally: adapter projection, uncertain dates/ranges, future-information suppression, staleness disclosure, provider/upstream credits, all 32 identities, unchanged core assessments, and storage/report integration. A bounded live sample additionally passed normalization, saved-snapshot/history and display replay. Current provider coverage or production natural operation is not established by those checks.

Before live integration, verify a saved real response privately against the documented schema, per-row source and licence metadata, pagination, acquisition clock, source-health and numerical-vintage evidence. Compare current API with the pinned documentation contract. Historical rows are not a point-in-time first-print archive. Missing currencies/series or consensus must remain disclosed; this provider alone has not been shown sufficient for complete FX fundamental analysis.

Completed bounded live check after explicit owner approval: one `/status` GET and one explicitly dated `/calendar` GET (limit 500, eight FX currency areas plus Germany), no automatic retries, pagination follow-ups, keys, schedule changes or Actions dispatch. Stop after those two requests and inspect privately; if truncated, report partial coverage and discuss additional requests. Those two requests returned HTTP 200; the raw sample and acquisition evidence are preserved privately, not in this repository. No further provider requests were performed during the later source-health and saved-input implementation. Connecting routine acquisition remains a separate decision.


## Saved private input (implemented; not activated in production)

`main.py` calls `build_outlook_with_saved_calendar`. With `FX_ECONOMIC_CALENDAR_SAVED_ENABLED` unset (or not exactly `true`), the wrapper neither reads a calendar file nor changes the existing outlook call/output. To opt in, the operator must also set the existing `FX_DATA_ROOT` to the separate private checkout. The fixed input path is `data/economic-calendar/reference.json` under that root. No public-code-directory input, relative root, symlink input or nonregular file is accepted. Reads are bounded to 4 MiB and nonregular inputs do not block. No file is created, fetched, refreshed or removed by this reader.

The private envelope has this shape (structural example only):

```json
{
  "schema": "financecalendar_saved_input_v1",
  "calendar": {
    "observed_at_utc": 1000000,
    "payload": {"events": [], "count": 0, "total": 0}
  },
  "status": {
    "observed_at_utc": 999999,
    "payload": {"source_health_summary": {"reported": false}, "source_health": []}
  }
}
```

Only actual acquisition clocks belong in a real envelope. Never refresh these clocks merely by copying or reusing an old file. Old inputs retain their acquisition clock and age, and freshness stays unverified; future calendar acquisition is unavailable. Missing, oversized, corrupt or incorrectly placed inputs produce unavailable calendar context while preserving all 32 core assessments. Failure reasons are fixed labels; paths, payloads and private collector error messages are not emitted.

Source-health status, checked/fetched clocks, mode and status acquisition time are retained in each relevant saved event. A status `success` is only a recorded collector result, including static registry checks without a fetch. No source-health status establishes present freshness or same-generation consistency. Degraded/failed/disabled states are shown individually and summarized across all relevant events, including those beyond the display limit. They do not veto candidates, alter grades or create trading permissions. Exact source-ID matching deliberately does not guess a parent or alias when evidence is absent.

No production flag or private data file was set by this change. Routine acquisition, approved request budget/frequency and natural-run verification remain separate work. API calls must not be added just to populate this optional file without owner agreement.
