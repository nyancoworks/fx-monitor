# Concrete scenario confirmation conditions

`strategy_assessments[].scenario_conditions` supplements the existing saved
assessment with a price level, confirmation timeframe, reaction, observation
stage and withdrawal conditions. It never authorizes orders or changes A/B/C.
The interpretation is versioned `contextual_saved_price_action_v1` and has not
been validated for profitability or parity with a teacher's original method.

The existing market phase and saved price context select a route:

- Pullback context: test the prior two confirmation candles' local low/high,
  reclaim that level at the close, and close in the scenario direction.
- Conflicting structure/trend context: close beyond the prior three candles'
  high/low, then observe a later candle retesting and holding that same level.
  A breakout alone is not a completed retest; a failed retest is explicit.
- Continuation context: close beyond the prior three candles' high/low.

These are provisional price-action definitions for different scenarios, not
votes or a collective AND of indicators. Structural direction, opposing
evidence and price-plan limitations remain visible. Local reaction extremes
are labeled separately from confirmed structural pivots and target prices.

Each level is anchored before its test candle. Conditions use five verified,
contiguous, completed M15 (swing) or M5 (daytrade) candles at the evaluation
clock. Unknown, stale, future or malformed local inputs produce a specific
unavailable reason, not an invented price. Gaps outside this local window do
not independently disqualify it. Levels outside the structural price plan
are not silently moved; withdrawn scenarios cannot reuse old conditions.

Statuses distinguish `waiting`, `awaiting_breakout`, `awaiting_retest`,
`retest_failed`, `conditions_observed`, `unavailable`, `withdrawn` and
`not_applicable`. An observed condition records its saved close and clock;
it does not identify an executed formation price or formation-time RR.
Condition observations do not independently promote grades.

Levels describe the saved evaluation. A new completed candle requires a new
context/anchor evaluation; this is not a frozen signal or a cross-run event
tracker. There is no invented elapsed-time expiry. Existing structural
withdrawal conditions continue to apply.

Raw input windows are transient. The private snapshot/history retains compact
reaction evidence and level provenance, without adding source-candle arrays
to monitoring-result history. New evidence is validated on save/read, while
legacy records without this field remain readable. Public tests use synthetic
prices only. Existing schedules, market requests, workflow, dependencies and
public-log restrictions are unchanged.
