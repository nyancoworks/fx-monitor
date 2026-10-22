# Provisional range scenarios

The existing 16 pairs × two timeframes remain 32 independent slots. A verified
directional track keeps its existing assessment unchanged. Only a slot without
a directional base structure can select `scenario_type=range_reversal`.

Use existing saved verified H4 (swing) or H1 (daytrade), never extra requests.
Within the latest uninterrupted base segment, identify strict 2-left/2-right
pivots. The latest two highs and two lows must alternate. Each upper pivot has
a wick zone [max(open,close), high]; each lower pivot has [low,min(open,close)].
The two upper zones and the two lower zones must each overlap with positive
width, with the lower overlap strictly below the upper overlap. No fitted ATR
or percentage tolerance is used. Formation is after the last pivot's two right
bars close. This conservative provisional interpretation misses some ranges;
mixed structure or balanced currency strength alone is insufficient.

Only a fresh verified M15/M5 candle starting after formation may select a side:
contact with the lower zone selects a buy scenario, contact with the upper
zone selects a sell scenario. Contact with neither or both means wait. No
direction is manufactured in the center. Saved base and trigger closes must
lie between invalidation and target. The lower outer pivot invalidates buys;
the upper outer pivot invalidates sells. The opposite confirmed pivot nearest
the interior is the structural target, not a projected midpoint.

Any saved verified base/trigger close reaching either outer bound after
formation withdraws that range interpretation, even after price returns.
Wicks alone do not withdraw it. New observations always re-evaluate the range;
they are not positions, fixed orders or historical trading results.

`range_edge_rejection` asks the last trigger candle to touch the relevant zone's
inner boundary, close back inside, and have a body in the scenario direction.
The condition evidence retains the boundary, formation chronology and trigger
OHLC needed for validation. An observed condition is not an entry/fill price.
The price plan and condition fields retain the existing advisory contracts.
Range grades are provisional B (C for incoherent plans); never A. Currency
strength and existing indicators explain context/opposition without votes or
automatic reversal decisions. Profitability and the definitions remain unvalidated.

Range evidence and reports remain in private state. Public tests use invented
prices only. No schedule, workflow, dependency or API budget changes are required.
