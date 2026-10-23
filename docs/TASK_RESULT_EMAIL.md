# Exact recorded task result email preparation

`diagnostics.task_result_email.prepare_task_result_email` is an offline adapter,
not a sender or scheduler. Its inputs and outputs are private. It takes a recorded
task plus explicitly expected task/run/slot identities and a timezone-aware clock.
It rejects mismatched, incomplete, truncated, failed, future or action-blocked
results and unresolved citations. It does not create another market analysis.

The original UTF-8 text and SHA256 are retained. Known ChatGPT URL citations become
their label and full URL. Plain/HTML alternatives preserve all text, newlines and
Markdown characters; HTML is escaped and source links are clickable. This is not
a pixel replica of ChatGPT or a general Markdown renderer. No recipient is chosen.

The stable task/run delivery key excludes body content, so editing a result cannot
turn one run into a new delivery. A supplied reserved key blocks preparation.
This check alone cannot guarantee exactly-once delivery: the caller must atomically
reserve the key in durable private state BEFORE any external draft/send operation,
record its returned ID, and reconcile ambiguous outcomes rather than blindly retry.
Concurrent callers and send-time crashes are not solved by an in-memory key list.

No workflow/task instructions, API budget or schedules are changed. In particular,
the existence of task lookup and Gmail tools in a development chat does not prove
their availability in a future scheduled run or provide a public task-completion
webhook. An end-to-end automatic delivery route remains a separate acceptance step.
Draft creation, send API success and actual recipient arrival are separate states.
Confirm the mailbox/recipient and ongoing sending scope before enabling delivery.
Do not publish source results, generated MIME, addresses or delivery state here.
