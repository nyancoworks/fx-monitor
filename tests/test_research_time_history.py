import datetime as dt
import json

from diagnostics.issue43_ny_runtime import empty_checkpoint
from diagnostics.issue43_ny_incremental import empty_archive, ingest
from fx_system.research_time_history import build


def test_private_archive_export_only_uses_closed_h1_and_keeps_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr('fx_system.research_time_history.MAX_WEEKDAYS', 5)
    start = int(dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).timestamp())
    rows = [{'timestamp': start + i*3600, 'open': 1.1, 'high': 1.2,
             'low': 1.0, 'close': 1.15} for i in range(12*24)]
    clock = start + len(rows)*3600
    archive = ingest(empty_archive(), 'EURUSD', rows,
                     as_of=dt.datetime.fromtimestamp(clock, dt.timezone.utc),
                     source_digest='a'*64)
    checkpoint = empty_checkpoint()
    checkpoint['archive'] = archive
    path = tmp_path/'ny17-checkpoint.json'
    path.write_text(json.dumps(checkpoint))
    result = build(path, clock)
    assert result['schema'] == 'private_time_history_v1'
    assert result['provider_native_daily_verified'] is False
    assert result['pairs']['EURUSD']['h1_archived'] == len(rows)
    assert result['pairs']['EURUSD']['d1']
    assert all(bar['session_end_utc'] <= clock for bar in result['pairs']['EURUSD']['d1'])
    assert result['pairs']['USDJPY']['d1'] == []
    assert 'archive' not in result  # H1 originals remain in the existing private state.
