# Private saved-run diagnostics

The existing snapshot commit also saves `data/run-diagnostics.json` in the fixed
private data repository. It contains a bounded view of the current run's
validation report, acquisition status, primary errors, source inventory and
decision-quality reasons. Raw candles and assessment arrays are omitted.
Diagnostic strings remain private and may contain provider details. Configured
key/token values are redacted before this file is written.

The record binds the run/code/evaluation identity and the exact Git blob SHA of
the saved snapshot. The validation exit status and the report's `passed` value
are separate: missing, malformed, inconsistent or ambiguous reports are never
reported as a confirmed pass. A missing current-run report does not reuse the
previous saved report. A later successful run does not erase the previous
diagnostic from Git history.

The file is at most 64 KiB. Oversized records drop pair details and limit the
failure list while retaining the failed status, total failure count and an
explicit truncation marker. Full snapshot inputs remain in their existing
private locations. This is not a general upload of stdout, tracebacks or secrets.

There are no additional market requests, Actions runs, API calls, schedules or
separate pushes. The existing snapshot push includes this small file; it does
add bounded diagnostic bytes to private Git history. Snapshot bytes, compact
export binding, canonical assessments and final workflow failure semantics are
unchanged. This diagnostic does not grant approval to treat a fallback source
as the primary feed or to retry collection.
