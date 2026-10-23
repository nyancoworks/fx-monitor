# Offline scheduled-event price windows

`diagnostics.calendar_price_windows.review_calendar_price_windows` reads a pinned
saved report/source/blob plus its matching next-generation followup. It reuses
the frozen-scenario identity/history/observation checks before deriving prices.
It fetches/writes nothing and is not called by production or the reporting task.
Keep its inputs and output in private research storage, never public logs.

For related events scheduled strictly after the original saved evaluation and
no later than the next one, measure the saved pair quote difference from the
closed M5 bar ending at the scheduled time to exact endpoints5/15/60minutes
later. These are separate descriptive durations, not trading horizons or policy
parameters. Every intervening bar must exist and be valid, with known saved
provider provenance; no nearest-bar approximation, forward filling, future
endpoint or partial-window return. An unaligned or unknown timestamp, cancelled/
estimated/stale event or non-release time role is unavailable with an explicit
reason. Uncertain-timed related events remain explicit unavailable cases.

The same pair/event ID appearing in both strategies is counted once; conflicting
copies are unavailable. Outside-window and unidentified records have separate
counts. These record counts are not complete calendar coverage. Measurable cases
retain potentially overlapping scheduled IDs, other uncertain-time event counts,
original calendar observation time and whether the event was known before its
scheduled time. Known source labels do not independently verify price accuracy.

All outputs explicitly say actual publication time is unverified and causal
attribution unassessed. Calendar time is not necessarily a release time, including
when the provider calls an event released. A pair quote increase is not a positive
surprise, an economic judgment or direct event-currency strength. There are no
orders, fills, profits, pooled unequal-horizon averages, grading changes or
hindsight candidate selection. Actuals/forecasts and simultaneous news need
separate evidence before interpreting a response.
