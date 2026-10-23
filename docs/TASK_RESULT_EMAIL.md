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

`reconcile_task_result_email` inspects private Gmail `full` readbacks after a send
attempt. It checks the prepared source hash/key/MIME, exact recipient and subject,
SENT (excluding DRAFT), and both complete plain/HTML bodies. Pass the actual test
subject when a test prefix was used. The helper is conservative: modified or
restructured MIME is not accepted as proof, even if it might display similarly.

An empty search stays `outcome_unknown` and never permits an automatic retry.
Even an exact sent-copy search match is `matching_sent_copy_unbound` without the
immutable message ID recorded from the send response: body/subject alone cannot
prove which send operation or task run created it. Several matching IDs are
reported separately, not silently selected. With a returned provider ID and an
exact sent-copy readback, `provider_sent_copy_verified` confirms that provider
operation only. It does not confirm actual arrival, notifications or reading.
The helper makes no provider calls and never changes a reservation or sends mail.

Automatic forwarding additionally needs an exact notification-to-run binding.
A shared conversation link or close timestamps are insufficient for delayed or
combined notification events. Latest-result lookup must not be treated as a
historical-run lookup. No automatic route is enabled by these offline helpers.
