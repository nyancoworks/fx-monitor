# Super Bollinger phase interpretation

Source checked: Toshihiko Masaki, “相場力学でトレードを極める！スーパーボリンジャー基本解説”
https://real-int.jp/articles/2589

The source distinguishes initial trend development at 2 sigma, continuation outside
1 sigma, and correction on a return inside 1 sigma. Lagging-span position describes
the underlying trend. This implementation is an FX Monitor adaptation, not a full
reproduction of Murphy's method or evidence of profitability.

Regime version 2 uses the retained closing-price/band history. When the most recent
outside-1-sigma excursion agrees with the current lagging-span direction, a current
return inside that band is a correction, including before the centre line breaks.
A renewed move outside the directional band returns to the trend interpretation.
With no such excursion, the existing gradual-trend interpretation remains. Range
and transition states retain the existing lagging-span interpretation. Latest
2-sigma position plus expanding width remains the existing strong-trend context;
this is not a new prediction of trend duration.

MACD momentum, RCI9/26/52, SMA50/200, price structure and standard Fibonacci remain
available as supporting and opposing evidence. A weakening histogram alone does
not turn an otherwise maintained SB trend into a price pullback; contrary momentum
is still retained as a caution. No indicator votes or new collective gate is added.

Timing version 3 adds consecutive confirmed closes outside directional 1 sigma as
continuation evidence, alongside the existing cross/recovery events. The previous
sigma-only pullback restriction is removed. “Conditions observed” is timing evidence,
not an order, grade override or profitability statement. Price-path, risk and opposing
evidence continue to be evaluated separately.

Frozen scenarios keep their recorded versions and condition kinds, including in
follow-through. No original saved data is rewritten. Versions 1/2 retain their
previous timing interpretation, and regime version 1 retains the previous classifier.

Limits: these are deterministic observable definitions, not proof of trading
advantage. Retained history limits the available preceding excursion. A single
band re-entry can be noise; MACD/RCI and higher-timeframe opposition remain visible.
No new data collection, API call, schedule, dependency or workflow is required.

## Band dynamics context (detail version 1)

Additional source: https://real-int.jp/articles/902 describes 3-sigma slope as
momentum context. We use per-bar price differences of the directional 3-sigma
line, not chart-screen angles. Changes in those differences describe acceleration
or slowing of that line, not a guaranteed future price movement.

Count actual consecutive confirmed closes outside 1/2 sigma. Distinguish a fresh
2-sigma crossing, maintained 2-sigma closes, and a return inside 2 sigma while
1 sigma still holds. Compare 3-sigma direction with existing MACD momentum and
explain conflicts. Existing RCI, SMA and Fibonacci evidence remains available.
These correlated price measures are not independent votes, new grade thresholds,
or automatic entry/exit rules. Missing history does not produce invented values.
Old scenarios lacking sb_detail_version retain their old interpretation.

This change improves the observed evidence supplied for discretionary judgment.
Trading accuracy, costs and performance still require real-data evaluation;
synthetic regression tests establish calculation/contract behavior only.
