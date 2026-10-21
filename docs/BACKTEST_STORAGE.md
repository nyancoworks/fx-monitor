# Derived backtest storage

The existing collection workflow saves backtest observations after its private
snapshot, NY17 archive and monitoring history stages succeed. It makes no new
market requests and adds no schedule or workflow run.

Only the fixed private data repository is accepted, verified private on every
cycle. The existing private writer credential is passed only to this storage
stage. Public output contains fixed stage status and integer request, byte and
added-row counters; full observations and diagnostics remain private.

The dedicated `fx-backtest-derived-v1` Release holds immutable, content-addressed
monthly bundles and two independently uploaded index copies. Release body is
the current pointer. The existing workflow concurrency group provides the single
writer; do not write the pointer from another process. The Release must remain
mutable. The implementation never deletes Git files, commits, tags, original
NY17 data or the Release itself.

M5 and H1 come from the acknowledged private snapshot's cache and source record.
Their Git blob hashes, run and code commit must agree. D1 accepts only the latest
saved NY17 candle for each pair with successful archive persistence, saved
adoption evidence and an explicitly revalidated session boundary. Unknown daily
inputs are reported unavailable; native UTC days are not substituted. This is
forward accumulation, not a multi-year historical download. Existing historical
originals and research remain in their original private source.

Retention is M5 three years, H1 five years and D1 ten years, by UTC partition
month, keeping the cutoff month. Every new row keeps its first capture clock
and saved input reference. Conflicting revisions stop the cycle. Immutable study
pins in the index keep their exact bundle generations beyond the active horizon;
existing pins are preserved. This collector does not create or remove study pins.

Limits are 64 HTTP requests per run including signed download redirects, no
retries, a rate-limit reserve of 200, and 1 GiB for all dedicated assets including
indices, pinned generations and unfinished uploads. At most 900 assets are
accepted. Capacity is checked before publication, with room for new indices.
There is no paid fallback. A failure stops this stage and fails the final workflow
result while previously saved monitoring outputs remain available.

New bundles and both indices are read back and hash checked before pointer
publication. After pointer readback, both index copies must restore, and remote
asset identity/size/SHA256 must match all retained and pinned references before
unreferenced derived assets are removed. Untouched older bundles are checked
against GitHub's SHA256 inventory and decoded in full on use; they are not all
downloaded on every run. Missing hashes, corruption, an unexpected asset or a
changed pointer stop cleanup. A failed cleanup can leave harmless old assets
within the quota; later changed generations can clean them up.

The two index copies share one storage service and the same data bundles. They
do not protect against loss of that account or storage medium. Canonical original
history is preserved separately. Local synthetic transport tests, repository
reflection and a successful natural storage run are distinct acceptance checks.
