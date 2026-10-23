# Dated official policy references

The existing opted-in private calendar reader also reads the optional, separate
`data/economic-background/reference.json` under `FX_DATA_ROOT`. It never fetches,
refreshes, rewrites or creates that file. The calendar collector does not own it.
With the opt-in disabled, or this file absent, previous output is preserved.
Policy-file failure cannot suppress core FX assessments or usable calendar input;
usable policy references can also survive unavailable calendar input.

The envelope is `{"schema":"saved_policy_reference_v1","facts":[...]}`.
Each fact supplies currency, instrument, rate_text, decision
(raised/lowered/held/changed), published_date and effective_date (publisher ISO
dates, not invented instants),
observed_at_utc (when this system recorded document review, not an HTTP receipt
or publisher update timestamp), source_name, source_url and
source_credit. Rate strings retain ranges and instrument distinctions. There is
no arithmetic across different central-bank instruments, parsing, surprise,
hawkish/dovish score, or automatic FX grade/direction/condition change.

An explicit `effective_date: null` means the reviewed document does not specify
an implementation date; display it as unspecified, never substitute publication
or meeting date. A missing key or malformed date remains invalid. `changed`
records a documented change without inferring its direction from a new level.

The file is bounded to64KiB and128input records; each currency retains at most
four latest known instrument records. Duplicate currency/instrument/publication
dates are all rejected. Superseded and omitted counts are retained. Historical
selection only sees references actually acquired by its evaluation clock; future
effective dates can be retained but do not establish implementation. Identifiers
and instrument names must be curated consistently; aliases are not inferred.

Sources require HTTPS document paths on the currency's official central-bank
domain: Federal Reserve, ECB, BoJ, BoE, BoC, RBA, RBNZ or SNB. Userinfo, query,
fragment, nonstandard ports and lookalike suffixes are rejected. This validates
provenance metadata, not factual accuracy of an extraction. A reviewer must
inspect the official document and preserve its original date and source credit
privately. Missing currencies stay explicitly unrecorded. Reading a document
today does not prove that it is the latest decision, nor reconstruct when this
system knew it in the past. No arbitrary freshness threshold is invented.

References are optional per-assessment economic_calendar_context.policy_reference
with only base/quote currency facts. They survive row copies, history and saved
report exports. Old frozen assessments without this field retain exact old
report rendering. The short reporting task can summarize relevant dated facts;
the existence of the field is not proof of task display or delivery.

This feature accepts dated facts only. Full policy outlook, market expectations,
causal price reaction and economic background coverage remain separate work.
Any new market/calendar API collection, frequency or budget needs owner approval.
