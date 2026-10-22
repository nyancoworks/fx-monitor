# Currency strength in strategy review

Canonical swing/daytrade assessments now carry `currency_strength_context`.
It contributes to reasons, opposing evidence, waiting questions, and comparison
of candidates with the same existing price-reaction priority. Report selection
still puts A/B/C first. It does not override a missing price plan, invalidate a
scenario, manufacture a direction, or upgrade/downgrade a grade on its own.

The provisional windows are 24 H1 hours for swing and 6 H1 hours for daytrade.
They are engineering defaults, not periods selected by a profitability test.
An adjacent window of the same length shows improving/weakening strength only
when both comparisons use exactly the same contributing pair set. Missing
previous evidence stays unknown. Windows are defined by completed-candle close
clocks, not receipt time or a claim about provider publication latency.

Only existing, contiguous, verified primary H1 observations are used. No prices
are fetched or filled. The assessed pair itself is excluded from its strength
graph, and the existing equal-edge least-squares solver is reused. This reduces
self-corroboration; related FX prices remain correlated, not independent votes.

The pair's base and quote currencies must connect through other observed pairs.
They may be compared inside a smaller connected component when another currency
is unavailable. Unobserved currencies receive no invented score. If no alternate
path exists, that pair's context is unavailable, while other assessments proceed.
Component-relative levels must not be compared between disconnected components.
The existing eight-currency 24-hour display and export contract are unchanged.

The saved context includes its pair/strategy/evaluation identity, input window,
contributing pairs, component currencies, fit residual, missing-pair reasons and
same-set prior comparison. Optional context is validated with canonical records
and retained by the existing history format. Old records without it remain valid.

Signs use only a floating arithmetic tolerance; positive does not mean
economically significant or profitable. No strength threshold, vote count,
probability, automatic order or permission is introduced.

Trendless structure remains unsupported by the current directional scenario
engine. Balanced strength alone is not evidence of a range, and this change does
not create a range-reversal strategy.
