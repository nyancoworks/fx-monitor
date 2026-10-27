# Contextual currency strength

Strategy strength uses verified saved H1 data: 24 hours for swing, 6 hours for
daytrade. The assessed pair is excluded from its own cross-pair fit. Neither
ranking nor strength alone sets direction or rejects a price scenario.

The magnitude reference is the median absolute fitted gap in up to twelve prior,
nonoverlapping equal-duration windows, using exactly the current connected input
pairs. A window with any missing, invalid, future or unverified bar is excluded;
closures are never filled. Four valid windows and a nonzero scale are required.
Current windows never enter their own reference. The median separates the lower
and upper part of this recent sample; it is a provisional descriptive scale,
not statistical significance, an optimized trading threshold or a profit claim.
A graph fit residual is not used as temporal volatility.

The saved context retains samples, source pair set, horizon, ratio, adjacent-window
change and the other 6/24-hour direction. Adjacent-window change compares the
previous nonoverlapping period, not the previous notification. The other horizon
is not M5/M15 strength. H4/M15 and H1/M5 price analysis remains unchanged.

Small or unscaled gaps do not automatically promote/demote a grade. An aligned,
nonweakening gap at least as large as the recent median supports existing
same-price-stage candidate comparison. An opposed gap at least as large as the
recent median is material counterevidence: a price reaction that could otherwise
receive A remains a review candidate at B. Range, incomplete-plan, invalidation
and other existing price-context decisions retain their roles. Aligned weakening
is still a caution; it does not become an automatic grade veto. There is no
single-indicator rejection, additive vote or new order/permission function.

Missing or legacy reference metadata is treated as magnitude unverified. Old
saved exports retain their original assessments; they are not regraded on read.
The new strength summary exposes relative size and conflicting horizons to the
existing report without adding collection calls, tasks, dependencies or schedules.
