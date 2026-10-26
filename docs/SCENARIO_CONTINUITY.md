# Adjacent saved-scenario comparison

The optional private `data/scenario-continuity.json` compares all 32 current
assessments with the immediately preceding committed report. Both exports are
restored using their saved source and snapshot blob identities. It is committed
with the current snapshot in the existing push; no remote/provider requests are added.

Each pair/strategy records previous/current direction, grade, conditions, levels,
evidence and default-listing membership. Candidate exit, evaluation pending,
direction changes and same-direction monitoring are distinct. Default listing is
not actual task selection. Removal from a list is not withdrawal. Same direction
does not prove the original fixed scenario remains valid. Old conditions/levels
are retained as previous values, not overwritten or used as current quotes.

The report should explain swing continuity before presenting current candidates.
This is adjacent-state explanation, not persistent positions, scenario permission,
entry/fill tracking, performance evidence or a new ranking rule. Missing, invalid,
same-clock or future previous exports yield an unavailable comparison; original
assessment and legacy export formats are unchanged.
