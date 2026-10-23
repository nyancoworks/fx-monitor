# Optional economic calendar context

Dated official policy documents are handled separately from event calendars;
see [POLICY_REFERENCE.md](POLICY_REFERENCE.md) for the optional offline input.

## Saved economic background overview

New assessments include a versioned `background` inside their calendar context.
For each currency, it separates policy-related events from economic indicators,
retains the next saved scheduled time, and counts uncertain and cancelled events.
This scans all relevant saved events, including those outside the three-event
display limit. A scheduled time, including a provisional one, is not proof of a
release. Missing schedules mean no record in this assessment's reference window,
not no event or safety.

The overview distinguishes availability of saved actual, forecast and prior
strings. Blank, explicitly stale, estimated and cancelled observations are not
counted; actuals also require the past-release window. Availability does not
verify the number, comparable units, a first print, or a forecast surprise.
Policy rate, policy stance and market reaction remain explicitly unassessed:
an event category does not establish any of them. Completing that research needs
separately sourced, dated policy facts and appropriately bounded price evidence.

This is an offline addition using the existing saved input. It adds no provider
request, collection schedule, dependency, task instruction, grade or direction
rule. Old frozen assessments without `background` retain their exact old report
rendering. Historical activation statements below describe implementation stages;
current deployment and natural-operation acceptance are tracked in Issue #1.

## Scope and activation

New calendar contexts carry `value_evidence_version=1`. For displayed events with
saved value fields, the full report shows the original period and unit, missing
actual/forecast strings, and an explicit unassessed forecast comparison. Even
two nonblank strings do not establish matching definitions, a pre-release
forecast, first-print values, or an observed publication clock. Prior values are
not forecasts and their revision status is not inferred. No values are parsed or
subtracted, and an upstream comparison flag does not enable a numeric claim.
Contexts without this version keep their exact historical rendering. This only
adds context to the existing full saved report; task instructions stay unchanged.

`financecalendar_adapter.normalize_calendar(payload, observed_at_utc=...)` is a pure offline adapter for a separately acquired Finance Calendar `/calendar` JSON page. Pass its return value explicitly as `economic_calendar` to `build_scheduled_outlook`. It neither fetches nor saves a provider response. Preserve the original response and its real acquisition clock in private storage; never commit it here. Do not substitute a provider build time or backdated evaluation time for acquisition.

The scheduled builder now has an explicitly disabled-by-default private-file reader. No workflow, frequency, dependencies or default output are changed. Missing calendar input keeps the existing path. Calendar fields do not change any grade, direction, scenario condition, target, RR, expiry or authority. Source actual/consensus/prior strings are not parsed, scored or compared. Policy/rate interpretation and market reaction remain unassessed.

## Documentation contract checked 2026-10-23 JST

- https://www.financecalendar.com/api/
- https://www.financecalendar.com/api/economic-calendar/
- https://www.financecalendar.com/api/coverage/
- https://github.com/awarenessdays/financecalendar-api/blob/main/openapi.json — reviewed blob `4d2f06deedc7733596015133675aec80d61b9182`
- https://github.com/awarenessdays/financecalendar-api/blob/main/DATA-TERMS.md — reviewed blob `d29faa3f10eaf671bf5695bc993ab6570a7e34c4`

These references were first reviewed as documentation/schema, then one owner-approved two-request live sample was checked privately on 2026-10-23 JST. That bounded sample is not ongoing provider or production acceptance. The economic-calendar and coverage documentation was reviewed again on 2026-10-23 JST: actual, prior and consensus can be unavailable, with no guaranteed consensus coverage or result-delivery time. Do not infer that consensus is always supplied or never collected. Official schedule sources generally do not supply market forecasts. A released status, a source URL or a new dataset build does not verify an actual result or recent publisher verification.

## Evidence acceptance and remaining research

| Evidence | Supported saved behavior | Further evidence needed for a stronger claim |
| --- | --- | --- |
| Release schedules | Preserve exact/uncertain times, status, source health and acquisition clocks. | Actual first-publication time and coverage of all relevant events. |
| Policy documents | Preserve dated instrument/rate strings, decision, effective date or explicit unknown, source and review clock. | Latest-decision coverage, implementation and a separately evidenced policy outlook. |
| Actual/prior strings | Preserve original strings, period/unit and credits; suppress future knowledge. | Matching measure, initial vintage and revision history; prior is not a forecast. |
| Consensus | Preserve a supplied string or explicit absence; no substitution or surprise calculation. | A sourced forecast recorded before the release, with comparable period/unit/definition. |
| Price observations | Observe bounded, provider-labelled saved candles without interpolation. | Actual release timing, overlapping news and a causal study; price change alone is not causation. |

Reader/display/history acceptance is distinct from completeness of economic
analysis. Missing forecasts or unverified policy latestness do not require
loosening validation, increasing requests or blocking unrelated development.
Retain them as explicit research gaps. Any proposed new source must establish
coverage, timestamps, revision policy, rights and usage before collection is
enabled; new market requests, frequency or budget still require owner approval.

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

## Existing-run production collector (implemented; activation requires agreement)

The trusted `private_runtime refresh` entry calls the optional collector before the existing FX refresh. No Actions workflow, trigger, schedule, Action pin, dependency or Twelve Data budget changes are required. Without the exact private configuration below, the collector makes zero requests and does not change the refresh environment. `main.py` remains a saved-input consumer and does not fetch this provider itself.

Activation is the following exact contents in the **private** `config/economic-calendar.json`, not in the public code repository:

```json
{"schema":"economic_calendar_collection_v1","enabled":true,"max_requests_per_run":2}
```

This authorizes a new recurring API use, separate from the earlier two-request sample. Do not deploy that enabled configuration without owner agreement to the recurring budget. The previous sample approval is not the activation approval. The production implementation remains off until that private configuration is present.

Each existing trusted refresh invocation then attempts `/status` once and `/calendar` once, keyless, with no automatic retries or redirects. The calendar query uses the existing eight currency areas plus Germany, UTC dates from two days before to eight days after the acquisition day (publisher-date boundaries included), limit 500 and offset 0. Truncation stays partial; it never triggers additional pages. The limit is two provider GET attempts per existing run invocation; a saved/local receipt for the same run prevents reattempt. It is not a guaranteed aggregate daily/IP quota across all clients or operator reruns after a lost runner. There is no new daily schedule or automatic recovery task.

Transport uses a 5-second socket timeout, a 12-second elapsed-time check while reading, and a 4 MiB response bound. No account, key or authentication header is added. Read timing limits do not establish data freshness. Malformed/error responses and partial provider availability do not block the main FX evaluation. Completed received bodies are captured privately with acquisition clocks, SHA-256 digests and HTTP status, under `data/economic-calendar/originals/<run_id>/`. An unsuccessful calendar fetch leaves the prior reference bytes and acquisition clock intact and reports the latest collection as unconfirmed. A successful calendar with unavailable status still supplies reference-only information with unverified source health.

The collector saves its owned originals, receipt, collection outcome and successful reference envelope in one private commit/push before starting the normal FX refresh. This is one additional private data commit/push per enabled invocation, no additional Actions run. It preserves completed provider receipts even when the later FX refresh fails; it does not rewrite saved FX assessment originals. Only its owned paths can be staged. Failed persistence removes only its own staging entries, preserving file bytes; the calendar state is marked unconfirmed and core refresh continues. The normal snapshot/history writers subsequently retain the calendar commit and preserve their existing FX paths/validation. No public payload logging or artifacts are added.

Verified locally with fake transport, synthetic responses and a local bare Git remote: disabled and malformed switches; at most two calls; no redirects/retries; response bounds; successful/failed status and calendar paths; prior-reference preservation; exact raw-byte capture; source-health normalization; all 32 assessments; snapshot/history round trips; optional-collection exceptions through the real private refresh entry; and the calendar commit followed by the existing FX snapshot commit. No recurring production requests were made by these tests.

Before marking production complete: agree the two-GET-per-existing-run budget, deploy the private activation configuration, observe the next natural run without manual dispatch, and verify private receipts, preserved origins, the same-run 32 assessments, validation and actual user-facing report delivery. Configuration, merge, successful local tests and production natural execution are separate states.

The existing enabled ChatGPT FX reporting task was separately updated to read the saved per-assessment economic-calendar context, show uncertain times/source failures/collection failures and preserve attribution. Its schedule and enabled state were preserved. It remains read-only: it must not fetch the calendar, write GitHub or start Actions. Prompt configuration is not proof of delivery; the first natural report containing verified saved calendar context remains an acceptance check.
