# Trend-only swing context v1

The environment policy introduced `contextual_scenario_review_v7_trend_swing`.
Current swing v9 adds H4 wave maturity before M15 priority; see
[swing horizon](SWING_HORIZON.md). This is an
FX Monitor adaptation, not certification of a named trader's complete method.
It does not imply profitability or execution permission.

## Roles

- Confirmed price structure anchors direction. H4/M15 is swing; H1/M5 is daytrade.
- Super Bollinger's lagging location, sigma price position and bandwidth describe
  the environment. An ordinary Bollinger strategy is not added. Shared band
  arithmetic remains necessary to calculate Super Bollinger.
- DMA price position and slope, support/resistance and standard Fibonacci inform
  setup context. Fibonacci projections do not replace structural targets.
- DiNapoli-coefficient MACD, Preferred Stochastic and RCI describe momentum,
  adjustment and persistence. Their shared price origin is not independent votes.
- Saved closed-candle price reactions and price-plan headroom remain separate
  from background evidence, fills, fees and continued validity.

## H4 consolidation exclusion

A swing with verified structural direction is outside monitoring when its fresh,
same-generation H4 Super Bollinger observation has all three features:

1. Lagging span is inside the historical candle's high/low range.
2. H4 close is inside the plus/minus one-sigma band, including the boundaries.
3. Bandwidth is contracting.

This is a disclosed, conservative operational consolidation proxy. It is not a
proven market-regime classifier, and does not claim multi-bar persistence or
the original author's complete entry/exit signal. It uses one indicator family's
context, not collective AND conditions across DMA, MACD, Stochastic and RCI.

The full 32 assessments remain saved. An excluded swing is `skip`, no grade,
with `h4_consolidation_excluded`; it is not a price-based withdrawal or a new
opposite-direction candidate. Existing verified price withdrawals keep priority.
The original price levels and source identity remain saved for explanation.

H4 structure without a direction stays outside monitoring as before. Missing
primary quality stays `evaluation_pending`, never fabricated range. Missing,
stale, future, duplicate or wrong-timeframe auxiliary SB observations are
unverified and do not erase a verified structural direction. Neither bandwidth
contraction alone nor M15 consolidation removes the H4 directional setup.
Conflicting indicators remain cautionary evidence rather than automatic vetoes.

## Version and verification

`swing_environment` saves the reproducible H4 policy decision. Technical context
v2 states the role mapping. Validation checks both without rewriting old records.
Old technical context v1, method versions and exports retain their original
rendering and restoration. Frozen prior conditions and existing research cohorts
must never be relabelled with this new policy.

Local synthetic tests cover exclusion, non-exclusion, primary versus auxiliary
unknowns, lifecycle, 32-assessment export restoration and tamper rejection.
Historical restoration and comparisons test compatibility, not strategy efficacy.
Natural adoption must be verified from a subsequent ordinary saved generation.
Do not dispatch Actions or increase API usage to validate this change.

Public method references (design context, not complete replication):
- https://www.span-model.com/chikouspan/katsuyou_ppt.pdf
- https://www.fibnodes.com/software/newcqg/cqg.asp?page=3
- https://www.fxtrade.co.jp/pdf/indicator/FXTF_hiropi.pdf

Range-reversal generation remains retired. No orders, new market requests,
reporting schedules, email or Sites changes are introduced.
